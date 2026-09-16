"""A crawl has limits by default, counts files instead of fetching them, keeps only what
the end of the run needs, and is polite per host rather than per worker.

The six-hour whole-site run of vtu.ac.in (docs: Limits and large sites) is the case behind
every test here: no cap by default, 5,730 PDFs fetched one at a time to be refused, every
page held in memory until the end, and four workers each honouring the delay on their own.

Everything runs without a network: the analysis and per-page resolution are faked, as in
`test_site_pipeline.py`, and the fake resolver records every URL it was asked for.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from webgraph import config
from webgraph import site as site_module
from webgraph.analyze import SiteAnalysis, SiteProbe
from webgraph.crawl.discovery import RobotsPolicy
from webgraph.crawl.frontier import FILE_KINDS, CrawlScope, Frontier
from webgraph.crawl.politeness import HostThrottle
from webgraph.pipeline import build_document
from webgraph.resolve import ResolvedPage, Strategy
from webgraph.site import SiteConfig, stream_site

ROOT = "https://example.test/"
PDF = f"{ROOT}circulars/2026-09-notice.pdf"

PROSE = (
    "The quick brown fox jumped over the lazy dog and continued running through the "
    "field until it reached the far treeline where it finally stopped to rest a while. "
)

ORG = '{"@context": "https://schema.org", "@type": "Organization", "name": "Example"}'


def page_html(name: str, links: tuple[str, ...]) -> str:
    nav = "".join(f'<a href="{href}">{href.strip("/") or "home"}</a> ' for href in links)
    body = "".join(f"<p>{PROSE}Paragraph {name} {i}.</p>" for i in range(6))
    return (
        f"<html><head><title>{name}</title>"
        f'<script type="application/ld+json">{ORG}</script></head><body>'
        f"<nav>{nav}</nav><main><h1>Page {name}</h1>{body}"
        f'<p><a href="/circulars/2026-09-notice.pdf">Notice (PDF)</a></p></main>'
        "</body></html>"
    )


# Every page links to the root, /a, /b and /c, and to one PDF.
LINKS = ("/", "/a", "/b", "/c")
PAGES: dict[str, str] = {
    ROOT: page_html("root", LINKS),
    f"{ROOT}a": page_html("a", LINKS),
    f"{ROOT}b": page_html("b", LINKS),
    f"{ROOT}c": page_html("c", LINKS),
}


def resolved_for(url: str) -> ResolvedPage:
    document = build_document(PAGES[url], url)
    chars = len(document.text)
    return ResolvedPage(
        url=url,
        document=document,
        strategy=Strategy.STATIC_ONLY,
        static_chars=chars,
        rendered_chars=0,
        union_chars=chars,
        blocks_only_in_static=0,
        blocks_only_in_rendered=0,
    )


@pytest.fixture(autouse=True)
def fetched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the network. Returns the list of URLs the crawl asked to resolve, in order;
    a URL that is not a page (the PDF) is refused the way the real resolver refuses it."""
    asked: list[str] = []

    def fake_probe(root: str, **_: Any) -> SiteProbe:
        return SiteProbe(
            analysis=SiteAnalysis(root=root, reachable=True),
            resolved=resolved_for(root),
            policy=RobotsPolicy(origin=root),
            sitemap_pages=(),
        )

    def fake_resolve(url: str, **_: Any) -> ResolvedPage:
        asked.append(url)
        if url not in PAGES:
            raise ValueError("browser: the server returned a file download rather than a page")
        return resolved_for(url)

    monkeypatch.setattr(site_module, "probe_site", fake_probe)
    monkeypatch.setattr(site_module, "resolve_page", fake_resolve)
    return asked


def crawl(**overrides: Any) -> list[dict[str, Any]]:
    options: dict[str, Any] = {
        "concurrency": 1,
        "delay_seconds": 0.0,
        "host_interval_seconds": 0.0,
        "verify_inventory": False,
    }
    options.update(overrides)
    return list(stream_site(ROOT, config=SiteConfig(**options)))


def done_of(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(e for e in events if e["type"] == "done")


class TestDefaultsAreBounded:
    def test_the_page_cap_is_no_longer_zero(self) -> None:
        assert config.CRAWL_MAX_PAGES == 500
        assert SiteConfig().max_pages == 500

    def test_there_is_a_time_limit_and_a_queue_limit(self) -> None:
        assert config.CRAWL_MAX_SECONDS == 3600
        assert config.CRAWL_MAX_QUEUE == 20_000
        assert SiteConfig().max_seconds == 3600
        assert SiteConfig().max_queue == 20_000

    def test_files_are_not_fetched_by_default(self) -> None:
        assert config.CRAWL_FETCH_FILES is False
        assert SiteConfig().fetch_files is False

    def test_one_page_a_second_per_host(self) -> None:
        assert config.CRAWL_HOST_INTERVAL_SECONDS == 1.0
        assert SiteConfig().host_interval_seconds == 1.0


class TestStoppedBy:
    def test_the_page_cap_names_itself(self) -> None:
        done = done_of(crawl(max_pages=2))
        assert done["pages_total"] == 2
        assert done["stopped_by"] == "pages"
        assert done["exhausted"] is False
        assert done["remaining_queued"] > 0
        assert done["limits"]["max_pages"] == 2

    def test_a_frontier_that_ran_dry_was_not_stopped_by_anything(self) -> None:
        done = done_of(crawl(max_pages=0))
        assert done["pages_total"] == 4
        assert done["stopped_by"] is None
        assert done["exhausted"] is True

    def test_a_cap_that_lands_exactly_on_the_last_page_is_not_a_stop(self) -> None:
        done = done_of(crawl(max_pages=4))
        assert done["pages_total"] == 4
        assert done["stopped_by"] is None
        assert done["exhausted"] is True

    def test_zero_pages_is_an_explicit_ask_for_unbounded(self) -> None:
        stage = next(e for e in crawl(max_pages=0) if e.get("stage") == "extract")
        assert stage["unlimited"] is True
        assert stage["max_pages"] == 0

    def test_the_time_limit_names_itself(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The clock is advanced by the fake resolver, so each fetched page costs 100 s."""
        clock = {"now": 0.0}
        monkeypatch.setattr(site_module, "_monotonic", lambda: clock["now"])
        real_resolve = site_module.resolve_page

        def slow_resolve(url: str, **kw: Any) -> ResolvedPage:
            clock["now"] += 100.0
            return real_resolve(url, **kw)

        monkeypatch.setattr(site_module, "resolve_page", slow_resolve)
        done = done_of(crawl(max_pages=0, max_seconds=100))
        # The root (already in hand) and one fetched page, then the limit is reached.
        assert done["pages_total"] == 2
        assert done["stopped_by"] == "time"
        assert done["exhausted"] is False
        assert done["stopped"] is False
        assert done["limits"]["max_seconds"] == 100

    def test_the_queue_cap_names_itself(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pages that link only to the root: an address the cap turns away is never
        re-found, so the run drains a frontier that lost pages and must say so."""
        leaf_pages = {url: page_html(url, ("/",)) for url in PAGES}
        leaf_pages[ROOT] = page_html("root", LINKS)
        monkeypatch.setitem(PAGES, ROOT, leaf_pages[ROOT])
        for url in (f"{ROOT}a", f"{ROOT}b", f"{ROOT}c"):
            monkeypatch.setitem(PAGES, url, leaf_pages[url])

        done = done_of(crawl(max_pages=0, max_queue=1))
        assert done["pages_total"] == 2, "the root and the one address the queue had room for"
        assert done["queue_refused"] == 2
        assert done["stopped_by"] == "queue"
        assert done["exhausted"] is False
        assert done["limits"]["max_queue"] == 1

    def test_the_page_cap_wins_over_the_queue_cap(self) -> None:
        done = done_of(crawl(max_pages=2, max_queue=1))
        assert done["stopped_by"] == "pages"

    def test_the_callers_stop_is_not_a_limit(self) -> None:
        calls = {"n": 0}

        def stop_after_two() -> bool:
            calls["n"] += 1
            return calls["n"] > 2

        events = list(
            stream_site(
                ROOT,
                config=SiteConfig(
                    max_pages=0, concurrency=1, delay_seconds=0.0, host_interval_seconds=0.0
                ),
                should_stop=stop_after_two,
            )
        )
        done = done_of(events)
        assert done["stopped"] is True
        assert done["stopped_by"] is None
        assert done["exhausted"] is False


class TestFilesAreCountedNotFetched:
    def test_a_pdf_link_is_never_resolved(self, fetched: list[str]) -> None:
        done = done_of(crawl(max_pages=0))
        assert PDF not in fetched, "the crawl fetched a PDF it could only refuse"
        assert all(url in PAGES for url in fetched)
        # Not a refusal either: nothing was attempted, so nothing failed.
        assert done["failed"] == 0
        assert done["pages_total"] == 4

    def test_but_it_is_counted_and_cited(self) -> None:
        events = crawl(max_pages=0)
        done = done_of(events)
        assert done["skipped"] == {"image": 0, "other_file": 0, "pdf": 1}
        assert done["skipped_total"] == 1
        assert done["fetch_files"] is False
        [entry] = done["skipped_urls"]
        assert entry["url"] == PDF
        assert entry["kind"] == "pdf"
        assert entry["found_on"] == ROOT, "the page that linked to it"
        assert entry["anchor"] == "Notice (PDF)"
        assert entry["via"] == "link"
        # And in the running tally from the moment it was found.
        first = next(e for e in events if e["type"] == "page")
        assert first["discovered_kinds"]["pdf"] == 1

    def test_the_skipped_list_is_capped_but_the_count_is_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        many = "".join(f'<a href="/files/{i}.pdf">f{i}</a>' for i in range(12))
        monkeypatch.setitem(PAGES, ROOT, page_html("root", LINKS).replace("</main>", f"{many}</main>"))
        monkeypatch.setattr(site_module, "SKIPPED_URLS_REPORTED", 5)
        done = done_of(crawl(max_pages=1))
        assert done["skipped_total"] == 13
        assert done["skipped"]["pdf"] == 13
        assert len(done["skipped_urls"]) == 5

    def test_fetch_files_opts_back_in(self, fetched: list[str]) -> None:
        done = done_of(crawl(max_pages=0, fetch_files=True))
        assert PDF in fetched
        assert done["failed"] == 1, "fetched, and refused as not HTML, as before"
        assert done["skipped_total"] == 0
        assert done["fetch_files"] is True

    def test_the_frontier_keeps_the_citation_without_queuing(self) -> None:
        frontier = Frontier(scope=CrawlScope(root=ROOT))
        accepted = frontier.extend(
            ["/x.pdf", "/img/a.png", "/deck.pptx", "/page"],
            1,
            base=ROOT,
            found_on=ROOT,
            anchors={"/x.pdf": "Syllabus"},
        )
        assert accepted == [f"{ROOT}page"]
        assert len(frontier) == 1
        assert frontier.skipped == {"image": 1, "other_file": 1, "pdf": 1}
        assert set(frontier.skipped_urls) == {f"{ROOT}x.pdf", f"{ROOT}img/a.png", f"{ROOT}deck.pptx"}
        citation = frontier.citation(f"{ROOT}x.pdf")
        assert citation is not None
        assert citation.found_on == ROOT
        assert citation.anchor == "Syllabus"
        assert citation.via == "link"

    def test_file_kinds_are_the_three_that_are_never_pages(self) -> None:
        assert set(FILE_KINDS) == {"pdf", "image", "other_file"}

    def test_a_sitemap_pdf_is_skipped_too(self) -> None:
        frontier = Frontier(scope=CrawlScope(root=ROOT))
        assert frontier.extend([f"{ROOT}a.pdf", f"{ROOT}a"], 1, via="sitemap") == [f"{ROOT}a"]
        assert frontier.skipped["pdf"] == 1

    def test_the_queue_cap_refuses_and_counts(self) -> None:
        frontier = Frontier(scope=CrawlScope(root=ROOT), max_queue=2)
        accepted = frontier.extend(["/a", "/b", "/c", "/d"], 1, base=ROOT)
        assert accepted == [f"{ROOT}a", f"{ROOT}b"]
        assert frontier.refused_by_cap == 2
        assert frontier.queue_capped is True
        # Draining makes room; a refused address was not marked seen, so it can return.
        frontier.pop()
        assert frontier.extend(["/c"], 1, base=ROOT) == [f"{ROOT}c"]


class TestRetention:
    """The end of a crawl reads each page's facts and its schema.org payloads; nothing
    else about a page is kept once its event has been yielded."""

    def test_kept_drops_blocks_markup_and_page_metadata(self) -> None:
        page = site_module._page_from_resolved(resolved_for(ROOT), None)
        assert page.document is not None and page.document.blocks
        kept = site_module._kept(page)
        assert kept.document is not None
        assert kept.document.blocks == ()
        assert kept.document.html == ""
        assert kept.markdown == ""
        assert kept.images == ()
        assert kept.url == ROOT

    def test_kept_keeps_entity_payloads_and_facts(self) -> None:
        page = site_module._page_from_resolved(resolved_for(ROOT), None)
        kept = site_module._kept(page)
        assert kept.document is not None
        sources = {payload.source for payload in kept.document.structured_data}
        assert sources <= set(site_module._ENTITY_SOURCES)
        assert any(
            isinstance(p.data, dict) and p.data.get("@type") == "Organization"
            for p in kept.document.structured_data
        )
        assert kept.facts == page.facts

    def test_entities_are_still_aggregated_across_the_whole_run(self) -> None:
        done = done_of(crawl(max_pages=0))
        [org] = [e for e in done["entities"] if e["type"] == "Organization"]
        assert org["pages"] == 4

    def test_the_content_view_still_uses_cross_page_chrome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Chrome is detected from a sample of full pages; the sample is released once it is
        known, and the pages after it are still reduced against it."""
        from webgraph.boilerplate import MIN_PAGES

        many = {f"{ROOT}p{i}": page_html(f"p{i}", LINKS) for i in range(MIN_PAGES + 2)}
        for url, html in many.items():
            monkeypatch.setitem(PAGES, url, html)
        monkeypatch.setitem(
            PAGES,
            ROOT,
            page_html("root", LINKS).replace(
                "</main>", "".join(f'<a href="/p{i}">p{i}</a>' for i in range(MIN_PAGES + 2)) + "</main>"
            ),
        )
        asked: list[str] = []

        def fake_probe(root: str, **_: Any) -> SiteProbe:
            return SiteProbe(
                analysis=SiteAnalysis(root=root, reachable=True),
                resolved=resolved_for(root),
                policy=RobotsPolicy(origin=root),
                sitemap_pages=(),
            )

        def fake_resolve(url: str, **_: Any) -> ResolvedPage:
            asked.append(url)
            return resolved_for(url)

        monkeypatch.setattr(site_module, "probe_site", fake_probe)
        monkeypatch.setattr(site_module, "resolve_page", fake_resolve)
        events = crawl(max_pages=0)
        done = done_of(events)
        assert done["chrome_blocks"] > 0 or done["chrome_slots"] > 0
        last = [e for e in events if e["type"] == "page"][-1]
        assert "site-chrome" in last["content_methods"]


class TestHostThrottle:
    def test_slots_are_one_interval_apart_whoever_asks(self) -> None:
        """Reserved under a lock: two callers arriving at the same instant leave with slots
        an interval apart, not with the same one."""
        now = {"t": 100.0}
        slept: list[float] = []
        throttle = HostThrottle(1.0, clock=lambda: now["t"], sleep=slept.append)
        waits = [throttle.wait(f"{ROOT}{i}") for i in range(4)]
        assert waits == [0.0, 1.0, 2.0, 3.0]
        assert slept == [1.0, 2.0, 3.0]

    def test_hosts_do_not_share_an_interval(self) -> None:
        now = {"t": 0.0}
        throttle = HostThrottle(1.0, clock=lambda: now["t"], sleep=lambda _: None)
        assert throttle.wait("https://a.test/") == 0.0
        assert throttle.wait("https://b.test/") == 0.0
        assert throttle.wait("https://a.test/x") == 1.0

    def test_time_already_passed_is_not_owed(self) -> None:
        now = {"t": 0.0}
        throttle = HostThrottle(1.0, clock=lambda: now["t"], sleep=lambda _: None)
        throttle.wait(ROOT)
        now["t"] = 5.0
        assert throttle.wait(ROOT) == 0.0

    def test_zero_interval_never_waits(self) -> None:
        throttle = HostThrottle(0.0, sleep=lambda _: pytest.fail("slept"))
        assert throttle.wait(ROOT) == 0.0

    def test_two_real_workers_are_spaced_by_the_interval(self) -> None:
        interval = 0.05
        throttle = HostThrottle(interval)
        stamps: list[float] = []
        lock = threading.Lock()

        def worker() -> None:
            for i in range(3):
                throttle.wait(f"{ROOT}{i}")
                with lock:
                    stamps.append(time.monotonic())

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        gaps = [b - a for a, b in zip(sorted(stamps), sorted(stamps)[1:], strict=False)]
        assert len(gaps) == 5
        assert min(gaps) >= interval * 0.9, gaps


class TestTheCrawlIsPolitePerHost:
    def test_two_workers_never_fetch_closer_than_the_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        interval = 0.05
        stamps: list[float] = []
        lock = threading.Lock()

        def fake_probe(root: str, **_: Any) -> SiteProbe:
            return SiteProbe(
                analysis=SiteAnalysis(root=root, reachable=True),
                resolved=resolved_for(root),
                policy=RobotsPolicy(origin=root),
                sitemap_pages=(),
            )

        def fake_resolve(url: str, **_: Any) -> ResolvedPage:
            with lock:
                stamps.append(time.monotonic())
            return resolved_for(url)

        monkeypatch.setattr(site_module, "probe_site", fake_probe)
        monkeypatch.setattr(site_module, "resolve_page", fake_resolve)
        done = done_of(crawl(max_pages=0, concurrency=2, host_interval_seconds=interval))
        assert done["pages_total"] == 4
        assert len(stamps) == 3
        gaps = [b - a for a, b in zip(sorted(stamps), sorted(stamps)[1:], strict=False)]
        assert min(gaps) >= interval * 0.9, gaps

    def test_the_sites_crawl_delay_is_honoured_when_larger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, float] = {}

        class Spy(HostThrottle):
            def __init__(self, interval_seconds: float, **kw: Any) -> None:
                seen["interval"] = interval_seconds
                super().__init__(0.0, **kw)

        monkeypatch.setattr(site_module, "HostThrottle", Spy)

        def fake_probe(root: str, **_: Any) -> SiteProbe:
            return SiteProbe(
                analysis=SiteAnalysis(root=root, reachable=True),
                resolved=resolved_for(root),
                policy=RobotsPolicy(origin=root, crawl_delay=3.0),
                sitemap_pages=(),
            )

        monkeypatch.setattr(site_module, "probe_site", fake_probe)
        monkeypatch.setattr(site_module, "resolve_page", lambda url, **_: resolved_for(url))
        crawl(max_pages=1, host_interval_seconds=1.0)
        assert seen["interval"] == 3.0
