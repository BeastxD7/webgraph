"""Watch: a store, an incremental re-crawl that says which section changed, noise rules
that keep a timestamp from being a change, a feed, and the CLI over it.

The site is served locally in two versions. The second version edits one section, adds
an item to a list, removes one page, adds another, and bumps a "last updated" line and a
visitor counter on the front page -- which is the change a monitor must *not* report.
Rendering is switched off for the analysis so no browser is launched; every fetch is real.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from xml.etree import ElementTree as ET

import pytest

from webgraph.cli import main
from webgraph.watch import (
    RunSummary,
    WatchStore,
    create_watch,
    export_changes,
    list_changes,
    run_watch,
    site_config_from,
    stream_watch,
)
from webgraph.watch.noise import NoiseRules
from webgraph.watch.sections import sections_from_markdown
from webgraph.watch.store import PageRecord

PROSE = (
    "The institute was founded to teach engineering to the district and has grown into "
    "five departments with a research centre. Its library holds forty thousand volumes. "
)


def page(title: str, body: str, links: tuple[str, ...] = ()) -> str:
    nav = "".join(f'<a href="{href}">{href}</a> ' for href in links)
    return (
        f"<html><head><title>{title}</title></head><body>"
        f"<nav>{nav}</nav><main>{body}</main>"
        "<footer><p>Visitors: 1,204,551</p></footer></body></html>"
    )


LINKS_V1 = ("/", "/about.html", "/circulars.html", "/old.html")
LINKS_V2 = ("/", "/about.html", "/circulars.html", "/new.html")


def version_one() -> dict[str, str]:
    return {
        "index.html": page(
            "College",
            f"<h1>Welcome</h1><p>{PROSE}</p><p>Last updated: 12 Sep 2026</p>"
            "<p>Visitors: 1,204,551</p>",
            LINKS_V1,
        ),
        "about.html": page(
            "About",
            f"<h1>About</h1><h2>History</h2><p>{PROSE}</p>"
            f"<h2>Contact</h2><p>The office is open from nine to five on weekdays. {PROSE}</p>",
            LINKS_V1,
        ),
        "circulars.html": page(
            "Circulars",
            f"<h1>Circulars</h1><p>{PROSE}</p><h2>2026</h2>"
            "<ul><li>Fee notification for the odd semester examinations.</li>"
            "<li>Revised timetable for the third semester laboratory sessions.</li></ul>",
            LINKS_V1,
        ),
        "old.html": page("Old", f"<h1>Old page</h1><p>{PROSE}</p>", LINKS_V1),
    }


def version_two() -> dict[str, str]:
    return {
        "index.html": page(
            "College",
            f"<h1>Welcome</h1><p>{PROSE}</p><p>Last updated: 13 Sep 2026</p>"
            "<p>Visitors: 1,204,902</p>",
            LINKS_V2,
        ),
        "about.html": page(
            "About",
            f"<h1>About</h1><h2>History</h2><p>{PROSE}</p>"
            f"<h2>Contact</h2><p>The office is open from eight to four on weekdays. {PROSE}</p>",
            LINKS_V2,
        ),
        "circulars.html": page(
            "Circulars",
            f"<h1>Circulars</h1><p>{PROSE}</p><h2>2026</h2>"
            "<ul><li>Fee notification for the odd semester examinations.</li>"
            "<li>Revised timetable for the third semester laboratory sessions.</li>"
            "<li>Circular on the internal assessment schedule for October.</li></ul>",
            LINKS_V2,
        ),
        "new.html": page("New", f"<h1>Admissions open</h1><p>{PROSE}</p>", LINKS_V2),
    }


class _Handler(SimpleHTTPRequestHandler):
    broken: ClassVar[set[str]] = set()

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path in type(self).broken:
            self.send_error(500, "broken on purpose")
            return
        super().do_GET()


class Site:
    def __init__(self, directory: Path, url: str, handler: type[_Handler]) -> None:
        self.directory = directory
        self.url = url
        self.handler = handler

    def serve(self, files: dict[str, str]) -> None:
        for existing in self.directory.glob("*.html"):
            existing.unlink()
        for name, html in files.items():
            (self.directory / name).write_text(html, encoding="utf-8")


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Site]:
    # No browser: the analysis renders once when Playwright is available, and nothing here
    # needs it.
    monkeypatch.setattr("webgraph.analyze.PLAYWRIGHT_AVAILABLE", False)
    from webgraph.fetch import robots

    robots.forget()
    root = tmp_path / "site"
    root.mkdir()
    handler = type("Handler", (_Handler,), {"broken": set()})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(root)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    served = Site(root, f"http://127.0.0.1:{httpd.server_address[1]}/", handler)
    served.serve(version_one())
    try:
        yield served
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "watch.sqlite3"


CONFIG: dict[str, Any] = {
    "complete": False,
    "concurrency": 2,
    "delay_seconds": 0,
    "host_interval_seconds": 0,
    "max_pages": 20,
}


class TestStoreRoundTrip:
    def test_watch_run_pages_changes(self, db: Path) -> None:
        store = WatchStore(db)
        watch = store.create_watch("https://example.test/", {"max_pages": 5}, schedule_seconds=3600)
        assert store.get_watch(watch.id) == watch
        assert [w.id for w in store.list_watches()] == [watch.id]
        assert watch.config == {"max_pages": 5}
        assert watch.schedule_seconds == 3600

        run = store.start_run(watch.id)
        assert store.last_finished_run(watch.id) is None, "an unfinished run is not a baseline"
        record = PageRecord(
            url="https://example.test/a",
            content_hash="abc",
            title="A",
            markdown="# A\n\nBody.",
            fetched_at=time.time(),
            strategy="static-only",
            sections=({"heading": "A", "level": 1, "text": "Body."},),
        )
        store.save_page(run.id, record)
        store.save_page(run.id, PageRecord(url="https://example.test/b", error="HTTP 404"))
        store.finish_run(run.id, pages_ok=1, pages_failed=1, stopped_by=None)

        finished = store.last_finished_run(watch.id)
        assert finished is not None and finished.id == run.id
        assert finished.pages_ok == 1 and finished.pages_failed == 1
        pages = store.pages_of(run.id)
        assert pages["https://example.test/a"] == record
        assert not pages["https://example.test/b"].ok

        before = time.time()
        change = store.add_change(
            run.id,
            watch.id,
            url="https://example.test/a",
            kind="changed",
            before_hash="old",
            after_hash="abc",
            title="A",
            sections=[{"kind": "edited", "heading": "A", "before": "Old.", "after": "Body."}],
        )
        [stored] = store.changes(watch.id)
        assert stored == change
        assert stored.sections[0]["heading"] == "A"
        assert store.changes(watch.id, since=before - 1)[0].id == change.id
        assert store.changes(watch.id, since=time.time() + 1) == []
        assert store.changes(watch.id, run_id=run.id + 1) == []

    def test_the_schema_has_the_four_tables(self, db: Path) -> None:
        import sqlite3

        WatchStore(db)
        with sqlite3.connect(db) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"watches", "runs", "pages", "changes"} <= names

    def test_deleting_a_watch_takes_its_runs_along(self, db: Path) -> None:
        store = WatchStore(db)
        watch = store.create_watch("https://example.test/")
        run = store.start_run(watch.id)
        store.save_page(run.id, PageRecord(url="https://example.test/"))
        assert store.delete_watch(watch.id)
        assert store.get_watch(watch.id) is None
        assert store.pages_of(run.id) == {}

    def test_a_watch_needs_an_http_root(self, db: Path) -> None:
        with pytest.raises(ValueError):
            create_watch("ftp://example.test/", store=db)

    def test_the_config_is_validated_on_create(self, db: Path) -> None:
        with pytest.raises(ValueError):
            create_watch("https://example.test/", {"strategy": "telepathy"}, store=db)


class TestSiteConfigFromWatchConfig:
    def test_complete_is_sugar_for_the_strategy(self) -> None:
        from webgraph.resolve import Strategy

        assert site_config_from({"complete": True}).strategy is Strategy.UNION
        assert site_config_from({"complete": False}).strategy is Strategy.STATIC_ONLY
        assert site_config_from({"strategy": "static-only"}).strategy is Strategy.STATIC_ONLY

    def test_unknown_keys_are_ignored_and_limits_apply(self) -> None:
        config = site_config_from({"max_pages": 7, "colour": "red", "noise": False})
        assert config.max_pages == 7
        assert config.max_seconds == 3600, "the crawl's own limits still apply"


class TestIncrementalRun:
    def test_the_first_run_is_a_baseline(self, site: Site, db: Path) -> None:
        watch = create_watch(site.url, CONFIG, store=db)
        summary = run_watch(watch.id, store=db)
        assert summary.baseline is True
        assert summary.pages_ok == 4
        assert summary.changes == ()
        assert not summary.any_change
        assert "Baseline" in summary.summary()
        store = WatchStore(db)
        pages = store.pages_of(summary.run_id)
        assert set(pages) == {site.url, f"{site.url}about.html", f"{site.url}circulars.html", f"{site.url}old.html"}
        about = pages[f"{site.url}about.html"]
        assert about.content_hash
        assert [s["heading"] for s in about.sections if s["heading"]] == ["About", "History", "Contact"]

    def test_the_second_run_reports_added_removed_and_changed_with_sections(
        self, site: Site, db: Path
    ) -> None:
        watch = create_watch(site.url, CONFIG, store=db)
        run_watch(watch.id, store=db)
        site.serve(version_two())

        events = list(stream_watch(watch.id, store=db))
        assert events[0]["type"] == "watch"
        assert events[0]["baseline"] is False
        assert events[0]["previous_pages"] == 4
        done = events[-1]
        assert done["type"] == "done"
        assert done["baseline"] is False
        assert done["changes"] == {"added": 1, "removed": 1, "changed": 2}
        assert done["suppressed"] == 1, "the front page differed only in its timestamp and counter"
        assert done["unverified"] == 0, "every page of the previous run was fetched again"
        assert done["stopped_by"] is None

        streamed = [e for e in events if e["type"] == "change"]
        by_url = {e["url"]: e for e in streamed}
        assert by_url[f"{site.url}new.html"]["kind"] == "added"
        gone = by_url[f"{site.url}old.html"]
        assert gone["kind"] == "removed"
        assert gone["before_hash"] and gone["after_hash"] == ""

        about = by_url[f"{site.url}about.html"]
        assert about["kind"] == "changed"
        [contact] = about["sections"]
        assert contact["kind"] == "edited"
        assert contact["heading"] == "Contact"
        assert "nine to five" in contact["before"]
        assert "eight to four" in contact["after"]

        circulars = by_url[f"{site.url}circulars.html"]
        [year] = circulars["sections"]
        assert year["heading"] == "2026"
        assert "internal assessment" in year["after"]
        assert "internal assessment" not in year["before"]

        # The store agrees with the stream.
        recorded = list_changes(watch.id, store=db)
        assert {c.url: c.kind for c in recorded} == {e["url"]: e["kind"] for e in streamed}

    def test_the_page_events_are_forwarded_without_their_markdown(self, site: Site, db: Path) -> None:
        watch = create_watch(site.url, CONFIG, store=db)
        pages = [e for e in stream_watch(watch.id, store=db) if e["type"] == "page"]
        assert pages and all("markdown" not in e and e["content_hash"] for e in pages if e["ok"])

    def test_a_third_run_over_the_same_site_reports_nothing(self, site: Site, db: Path) -> None:
        watch = create_watch(site.url, CONFIG, store=db)
        run_watch(watch.id, store=db)
        site.serve(version_two())
        run_watch(watch.id, store=db)
        summary = run_watch(watch.id, store=db)
        assert not summary.any_change
        assert summary.unchanged == 4
        assert summary.suppressed == 0
        assert "No change" in summary.summary()

    def test_a_server_error_is_not_a_removed_page(self, site: Site, db: Path) -> None:
        watch = create_watch(site.url, CONFIG, store=db)
        run_watch(watch.id, store=db)
        site.handler.broken.add("/old.html")
        summary = run_watch(watch.id, store=db)
        assert summary.removed == 0
        assert summary.pages_failed == 1
        assert not summary.any_change

    def test_a_page_the_cap_never_reached_is_unverified_not_gone(self, site: Site, db: Path) -> None:
        watch = create_watch(site.url, CONFIG, store=db)
        run_watch(watch.id, store=db)
        site.serve(version_two())
        summary = run_watch(watch.id, store=db, adjust=lambda c: c.__class__(**{**_fields(c), "max_pages": 1}))
        assert summary.stopped_by == "pages"
        assert summary.removed == 0
        assert summary.unverified == 3
        assert summary.pages_ok == 1

    def test_noise_off_reports_the_timestamp(self, site: Site, db: Path) -> None:
        watch = create_watch(site.url, {**CONFIG, "noise": False}, store=db)
        run_watch(watch.id, store=db)
        site.serve(version_two())
        summary = run_watch(watch.id, store=db)
        front = [c for c in summary.changes if c.url == site.url]
        assert front, "with the rules off, the bumped timestamp is a change"
        assert summary.suppressed == 0

    def test_a_stopped_run_is_finished_but_is_not_the_baseline(self, site: Site, db: Path) -> None:
        """A tab closed at page three must not turn every real page into `added` next time."""
        watch = create_watch(site.url, CONFIG, store=db)
        first = run_watch(watch.id, store=db)
        calls = {"n": 0}

        def stop_soon() -> bool:
            calls["n"] += 1
            return calls["n"] > 1

        events = list(stream_watch(watch.id, store=db, should_stop=stop_soon))
        assert events[-1]["type"] == "done"
        store = WatchStore(db)
        stopped = store.last_finished_run(watch.id)
        assert stopped is not None and stopped.id != first.run_id
        assert stopped.stopped_by == "stopped"
        baseline = store.baseline_run(watch.id)
        assert baseline is not None and baseline.id == first.run_id

        third = run_watch(watch.id, store=db)
        assert not third.any_change
        assert third.unchanged == 4

    def test_a_run_that_read_nothing_is_not_the_baseline(self, db: Path) -> None:
        store = WatchStore(db)
        watch = store.create_watch("https://example.test/")
        empty = store.start_run(watch.id)
        store.finish_run(empty.id, pages_ok=0, pages_failed=1, stopped_by=None)
        assert store.last_finished_run(watch.id) is not None
        assert store.baseline_run(watch.id) is None

    def test_a_run_that_ended_at_a_limit_is_a_baseline(self, db: Path) -> None:
        store = WatchStore(db)
        watch = store.create_watch("https://example.test/")
        capped = store.start_run(watch.id)
        store.finish_run(capped.id, pages_ok=80, pages_failed=0, stopped_by="pages")
        errored = store.start_run(watch.id)
        store.finish_run(errored.id, pages_ok=3, pages_failed=0, stopped_by="error")
        baseline = store.baseline_run(watch.id)
        assert baseline is not None and baseline.id == capped.id

    def test_a_wall_is_not_a_removed_page(self) -> None:
        from webgraph.watch import _gone

        assert _gone("HTTP 404")
        assert _gone("HTTP 410: page does not exist")
        assert not _gone("HTTP 403")
        assert not _gone("blocked: the server returned a Cloudflare challenge (403)")
        assert not _gone(None)

    def test_the_previous_runs_pages_are_seeded_before_the_sitemap(self) -> None:
        from webgraph.crawl.frontier import CrawlScope, Frontier

        frontier = Frontier(scope=CrawlScope(root="https://example.test/"))
        seeds = frontier.extend(["https://example.test/known"], 1, via="seed")
        seeds += frontier.extend(["https://example.test/from-sitemap"], 1, via="sitemap")
        assert frontier.pop() == ("https://example.test/known", 1)
        citation = frontier.citation("https://example.test/known")
        assert citation is not None and citation.via == "seed"


def _fields(config: Any) -> dict[str, Any]:
    from dataclasses import fields

    return {f.name: getattr(config, f.name) for f in fields(config)}


class TestNoiseRules:
    rules = NoiseRules.default()

    @pytest.mark.parametrize(
        "block",
        [
            "12/09/2026",
            "2026-09-12T10:42:00Z",
            "Last updated: 12 Sep 2026",
            "Updated on September 12, 2026 at 10:42 am",
            "Visitors: 1,204,551",
            "You are visitor number 88123",
            "10:42 am",
            "3 days ago",
            "© 2026 SMVITM",
            "Page generated in 0.031 seconds",
            "Friday, 12 September 2026, 10:00 IST",
        ],
    )
    def test_a_block_that_is_a_date_time_or_counter_is_noise(self, block: str) -> None:
        assert self.rules.is_noise(block)

    @pytest.mark.parametrize(
        "block",
        [
            "Results announced on 12/09/2026",
            "Enjoy the sun this summer",
            "Apply now",
            "Apply online for admission",
            "Since 2019 the college offers a degree",
            "Total seats: 120",
            "Circular: exam fee notification for the 2026 batch",
            "Posted by admin in News",
        ],
    )
    def test_a_sentence_that_contains_one_is_compared(self, block: str) -> None:
        assert not self.rules.is_noise(block)

    def test_clean_drops_noise_blocks_and_link_queries(self) -> None:
        text = "Intro para.\n\nLast updated: 12 Sep 2026\n\n![logo](/img/logo.png?v=123)\n\nBody   text\nhere."
        assert self.rules.clean(text) == "Intro para.\n\n![logo](/img/logo.png)\n\nBody text here."

    def test_the_rules_are_a_config_list(self) -> None:
        from webgraph import config

        rules = NoiseRules.from_config({"noise_patterns": [r"\bbuild\s+[a-f0-9]{7}\b"]})
        assert len(rules.patterns) == len(config.WATCH_NOISE_PATTERNS) + 1
        assert rules.is_noise("Build 3fa9c2e")
        assert not NoiseRules.default().is_noise("Build 3fa9c2e")
        assert NoiseRules.from_config({"noise": False}).enabled is False

    def test_a_short_block_no_pattern_touches_is_not_noise(self) -> None:
        assert not self.rules.is_noise("Admissions open")


class TestSections:
    def test_headings_own_what_follows(self) -> None:
        md = "Lead.\n\n# Title\n\nPara one.\n\n## Part A\n\nText a.\n\n```\n# not a heading\n```\n\n## Part B ¶\n\nText b."
        sections = sections_from_markdown(md)
        assert [(s.level, s.heading) for s in sections] == [(0, ""), (1, "Title"), (2, "Part A"), (2, "Part B")]
        assert sections[0].text == "Lead."
        assert "# not a heading" in sections[2].text
        assert sections[3].text == "Text b."

    def test_no_headings_is_one_section(self) -> None:
        [only] = sections_from_markdown("Just text.\n\nMore.")
        assert only.heading == "" and only.level == 0


class TestFeeds:
    def _watch_with_changes(self, db: Path) -> str:
        store = WatchStore(db)
        watch = store.create_watch("https://example.test/")
        run = store.start_run(watch.id)
        store.finish_run(run.id, pages_ok=2, pages_failed=0, stopped_by=None)
        store.add_change(
            run.id, watch.id, url="https://example.test/circulars", kind="changed", title="Circulars",
            before_hash="a", after_hash="b",
            sections=[{"kind": "edited", "heading": "2026", "before": "two items", "after": "three items & more"}],
        )
        store.add_change(run.id, watch.id, url="https://example.test/new", kind="added", title="New", after_hash="c")
        return watch.id

    def test_rss_is_well_formed_and_complete(self, db: Path) -> None:
        watch_id = self._watch_with_changes(db)
        xml = export_changes(watch_id, fmt="rss", store=db, feed_url="https://api.test/feed.xml")
        root = ET.fromstring(xml)
        assert root.tag == "rss" and root.get("version") == "2.0"
        channel = root.find("channel")
        assert channel is not None
        for required in ("title", "link", "description", "lastBuildDate"):
            assert channel.findtext(required)
        items = channel.findall("item")
        assert len(items) == 2
        for item in items:
            for required in ("title", "link", "guid", "pubDate", "description"):
                assert item.findtext(required), required
        assert "2026" in (items[0].findtext("title") or "") or "2026" in (items[1].findtext("title") or "")
        assert "&" not in xml.replace("&amp;", "").replace("&lt;", "").replace("&gt;", "").replace("&quot;", "").replace("&#", "")

    def test_atom_is_well_formed_and_complete(self, db: Path) -> None:
        watch_id = self._watch_with_changes(db)
        xml = export_changes(watch_id, fmt="atom", store=db, feed_url="https://api.test/feed.xml")
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml)
        assert root.tag == "{http://www.w3.org/2005/Atom}feed"
        for required in ("a:id", "a:title", "a:updated"):
            assert root.findtext(required, namespaces=ns)
        assert root.find("a:link[@rel='self']", ns) is not None
        entries = root.findall("a:entry", ns)
        assert len(entries) == 2
        for entry in entries:
            for required in ("a:id", "a:title", "a:updated"):
                assert entry.findtext(required, namespaces=ns), required
            assert entry.find("a:link", ns) is not None
            assert entry.findtext("a:content", namespaces=ns)
        ids = [e.findtext("a:id", namespaces=ns) for e in entries]
        assert len(set(ids)) == 2, "each change has its own id, so a reader never repeats one"

    def test_markdown_and_json(self, db: Path) -> None:
        watch_id = self._watch_with_changes(db)
        md = export_changes(watch_id, fmt="md", store=db)
        assert "1 new, 0 gone, 1 changed" in md
        assert "**2026**" in md and "was: two items" in md
        payload = json.loads(export_changes(watch_id, fmt="json", store=db))
        assert payload["watch"]["id"] == watch_id
        assert {c["kind"] for c in payload["changes"]} == {"added", "changed"}

    def test_since_filters(self, db: Path) -> None:
        watch_id = self._watch_with_changes(db)
        assert json.loads(export_changes(watch_id, since=time.time() + 60, fmt="json", store=db))["changes"] == []

    def test_an_unknown_format_is_refused(self, db: Path) -> None:
        watch_id = self._watch_with_changes(db)
        with pytest.raises(ValueError):
            export_changes(watch_id, fmt="pdf", store=db)


class TestCli:
    def test_create_run_changes(self, site: Site, db: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["watch", "create", site.url, "--db", str(db), "--max-pages", "20"]) == 0
        watch_id = capsys.readouterr().out.strip()
        assert len(watch_id) == 12

        assert main(["watch", "list", "--db", str(db)]) == 0
        assert site.url in capsys.readouterr().out

        assert main(["--quiet", "watch", "run", watch_id, "--db", str(db), "--fail-on-change"]) == 0
        assert "Baseline" in capsys.readouterr().out

        site.serve(version_two())
        code = main(["--quiet", "watch", "run", watch_id, "--db", str(db), "--fail-on-change"])
        out = capsys.readouterr().out
        assert code == 1, "non-zero on change, for a scheduled job"
        assert "1 new, 1 gone, 2 changed" in out
        assert "Contact" in out

        assert main(["watch", "changes", watch_id, "--db", str(db), "--format", "rss"]) == 0
        xml = capsys.readouterr().out
        assert ET.fromstring(xml).tag == "rss"

        assert main(["watch", "changes", watch_id, "--db", str(db), "--since", "1h", "--format", "json"]) == 0
        assert len(json.loads(capsys.readouterr().out)["changes"]) == 4

        assert main(["watch", "run", watch_id, "--db", str(db), "--json"]) == 0
        summary = json.loads(capsys.readouterr().out)
        assert summary["changed"] == 0 and summary["unchanged"] == 4

    def test_a_watch_config_file_is_read(self, site: Site, db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        config_file = tmp_path / "watch.json"
        config_file.write_text(json.dumps({**CONFIG, "noise": False}), encoding="utf-8")
        assert main(["watch", "create", site.url, "--db", str(db), "--config", str(config_file), "--json"]) == 0
        created = json.loads(capsys.readouterr().out)
        assert created["config"]["noise"] is False
        assert created["config"]["max_pages"] == 20


class TestRunSummary:
    def test_round_trips_through_its_dict(self) -> None:
        summary = RunSummary(
            watch_id="w", run_id=1, baseline=False, pages_ok=3, pages_failed=0, stopped_by=None,
            added=1, removed=0, changed=1, suppressed=1, unchanged=0, unverified=0, duration_seconds=1.0,
        )
        assert summary.any_change
        assert summary.as_dict()["changes"] == []
        assert "1 new, 0 gone, 1 changed" in summary.summary()
