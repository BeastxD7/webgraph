"""Discovery is visible: what robots.txt said, which sitemaps were tried, what was found.

The owner watched two whole-site crawls (vtu.ac.in, sode-edu.in, 14 Sep 2026). Neither
site publishes a sitemap, and the only word the crawl's stream had on the matter was
`from_sitemap: 0` -- nothing about whether robots.txt existed, what it asked, which sitemap
addresses were tried and what came back. On vtu.ac.in 7,907 of the 17,126 discovered URLs
were PDFs; the crawl spent a third of six hours fetching them one at a time to refuse each
as not HTML, and nothing on screen said so.

Three things are pinned here: the robots policy keeps the file and the rules that apply to
this client; the sitemap walk records every address it tried; and the frontier tallies what
it finds by kind, which the stream reports on every `frontier` and `page` event.

`crawl.discovery` binds `fetch_static` at import, so it is stubbed *there* -- the
`webgraph.fetch.robots` stub in `conftest.py` does not reach it.
"""

from __future__ import annotations

from typing import Any

import pytest

from webgraph.crawl import discovery
from webgraph.crawl.discovery import (
    RobotsPolicy,
    SitemapAttempt,
    discover_sitemap_urls,
    discover_sitemaps,
    group_for_client,
    load_robots,
)
from webgraph.crawl.frontier import KINDS, CrawlScope, Frontier, url_kind
from webgraph.fetch.static import FetchConfig, FetchResult

ROOT = "https://x.test/"

ROBOTS = """# a real-looking file
User-agent: googlebot
Disallow: /nothing-for-google/

User-agent: *
Disallow: /admin/
Disallow: /tmp/  # scratch
Allow: /tmp/public/
Crawl-delay: 2

Sitemap: https://x.test/from-robots.xml
"""

SITEMAP_INDEX = """<?xml version="1.0"?>
<sitemapindex><sitemap><loc>https://x.test/part-1.xml</loc></sitemap></sitemapindex>"""

SITEMAP_PART = """<?xml version="1.0"?>
<urlset><url><loc>https://x.test/a</loc></url><url><loc>https://x.test/b</loc></url></urlset>"""


def _result(url: str, html: str, status: int = 200, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        url=url,
        requested_url=url,
        status=status,
        html=html,
        content_type=content_type,
        elapsed_seconds=0.01,
        ok=status < 400,
        error=None if status < 400 else f"HTTP {status}",
    )


def serve(monkeypatch: pytest.MonkeyPatch, files: dict[str, tuple[str, int]]) -> list[str]:
    """A host serving `files` (url -> (body, status)); everything else 404. Records fetches."""
    fetched: list[str] = []

    def fetch(url: str, *, config: FetchConfig | None = None) -> FetchResult:  # noqa: ARG001
        fetched.append(url)
        body, status = files.get(url, ("<html><body>Not found</body></html>", 404))
        return _result(url, body, status)

    monkeypatch.setattr(discovery, "fetch_static", fetch)
    return fetched


class TestRobotsIsKept:
    def test_the_file_and_the_rules_for_this_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        serve(monkeypatch, {f"{ROOT}robots.txt": (ROBOTS, 200)})
        policy = load_robots(ROOT)
        assert policy.fetched and policy.status == 200
        assert policy.text == ROBOTS
        assert policy.group == "*"
        # Googlebot's group is not ours; the comment on the `/tmp/` line is not a rule.
        assert policy.rules == (
            "Disallow: /admin/",
            "Disallow: /tmp/",
            "Allow: /tmp/public/",
            "Crawl-delay: 2",
        )
        assert policy.crawl_delay == 2.0
        assert policy.sitemaps == ("https://x.test/from-robots.xml",)

    def test_a_group_naming_this_client_wins_over_the_wildcard(self) -> None:
        group = group_for_client(
            "User-agent: *\nDisallow: /\n\nUser-agent: webgraph\nAllow: /docs\n"
        )
        assert group is not None
        assert group.label == "webgraph"
        assert group.lines == ("Allow: /docs",)

    def test_no_group_for_us_means_no_rules(self) -> None:
        assert group_for_client("User-agent: googlebot\nDisallow: /\n") is None

    def test_a_missing_file_records_its_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        serve(monkeypatch, {})
        policy = load_robots(ROOT)
        assert not policy.fetched
        assert policy.status == 404
        assert policy.text == "" and policy.rules == () and policy.group is None
        assert policy.allows(f"{ROOT}anything")

    def test_the_single_page_path_keeps_the_same_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`fetch.robots.policy_for` builds its policy with the same function, so the page
        refusal and the crawl report never disagree about what the file said."""
        from webgraph.fetch import robots as robots_module

        def fetch(url: str, *, config: FetchConfig | None = None) -> FetchResult:  # noqa: ARG001
            return _result(url, ROBOTS)

        monkeypatch.setattr(robots_module, "fetch_static", fetch)
        robots_module.forget()
        policy, text = robots_module.policy_for(f"{ROOT}page")
        assert text == ROBOTS
        assert policy.text == ROBOTS
        assert policy.rules[0] == "Disallow: /admin/"


class TestSitemapAttemptsAreRecorded:
    def test_no_sitemap_anywhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The vtu.ac.in shape: no robots `Sitemap:` line, both conventional addresses 404."""
        serve(monkeypatch, {})
        urls, attempts = discover_sitemaps(ROOT)
        assert urls == []
        assert [a.as_dict() for a in attempts] == [
            {
                "url": f"{ROOT}sitemap.xml",
                "status": 404,
                "ok": False,
                "urls": 0,
                "index": False,
                "source": "conventional",
            },
            {
                "url": f"{ROOT}sitemap_index.xml",
                "status": 404,
                "ok": False,
                "urls": 0,
                "index": False,
                "source": "conventional",
            },
        ]

    def test_robots_advertised_first_then_conventional_with_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        serve(
            monkeypatch,
            {
                f"{ROOT}robots.txt": (ROBOTS, 200),
                f"{ROOT}from-robots.xml": (SITEMAP_INDEX, 200),
                f"{ROOT}part-1.xml": (SITEMAP_PART, 200),
            },
        )
        policy = load_robots(ROOT)
        urls, attempts = discover_sitemaps(ROOT, policy=policy)
        assert urls == ["https://x.test/a", "https://x.test/b"]
        by_url = {a.url: a for a in attempts}
        assert [a.url for a in attempts] == [
            f"{ROOT}from-robots.xml",
            f"{ROOT}sitemap.xml",
            f"{ROOT}sitemap_index.xml",
            f"{ROOT}part-1.xml",
        ]
        assert by_url[f"{ROOT}from-robots.xml"] == SitemapAttempt(
            f"{ROOT}from-robots.xml", 200, ok=True, urls=0, index=True, source="robots"
        )
        assert by_url[f"{ROOT}part-1.xml"] == SitemapAttempt(
            f"{ROOT}part-1.xml", 200, ok=True, urls=2, index=False, source="index"
        )
        assert by_url[f"{ROOT}sitemap.xml"].status == 404

    def test_a_200_that_is_not_a_sitemap_is_not_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A soft 404 -- the site's HTML "not found" page at 200 -- is not a sitemap."""
        serve(monkeypatch, {f"{ROOT}sitemap.xml": ("<html><body>Not found</body></html>", 200)})
        _, attempts = discover_sitemaps(ROOT)
        first = attempts[0]
        assert first.status == 200 and first.ok is False and first.urls == 0

    def test_the_old_entry_point_still_returns_the_urls_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        serve(monkeypatch, {f"{ROOT}sitemap.xml": (SITEMAP_PART, 200)})
        assert discover_sitemap_urls(ROOT) == ["https://x.test/a", "https://x.test/b"]


class TestUrlKind:
    @pytest.mark.parametrize(
        ("url", "kind"),
        [
            ("https://x.test/circulars/notice.pdf", "pdf"),
            ("https://x.test/files/NOTICE.PDF", "pdf"),
            ("https://x.test/img/logo.png", "image"),
            ("https://x.test/photo.JPG", "image"),
            ("https://x.test/downloads/form.docx", "other_file"),
            ("https://x.test/build.zip", "other_file"),
            ("https://x.test/2024/06/", "archive"),
            ("https://x.test/2024/06", "archive"),
            ("https://x.test/2024/06/15/", "archive"),
            ("https://x.test/date/2024/", "archive"),
            ("https://x.test/blog/date/2024/06/15/", "archive"),
            ("https://x.test/category/news/", "category"),
            ("https://x.test/categories/news", "category"),
            ("https://x.test/tag/exams/", "tag"),
            ("https://x.test/tags/exams", "tag"),
            ("https://x.test/about", "page"),
            ("https://x.test/", "page"),
            # A date-based permalink is a post, not an archive of posts.
            ("https://x.test/2024/06/my-post/", "page"),
            # Digits that are not a date are an id.
            ("https://x.test/product/5678", "page"),
            ("https://x.test/thread/1234", "page"),
            ("https://x.test/thread/2024/57", "page"),
            ("https://x.test/2024/", "page"),
            # The word alone is not the taxonomy.
            ("https://x.test/category/", "page"),
            ("https://x.test/tags/", "page"),
        ],
    )
    def test_kinds(self, url: str, kind: str) -> None:
        assert url_kind(url) == kind


class TestFrontierTallies:
    def test_every_kind_is_reported_zeros_included(self) -> None:
        frontier = Frontier(scope=CrawlScope(root=ROOT))
        assert tuple(frontier.kinds) == KINDS
        assert all(count == 0 for count in frontier.kinds.values())

    def test_accepted_and_refused_addresses_are_both_counted_once(self) -> None:
        frontier = Frontier(scope=CrawlScope(root=ROOT))
        frontier.mark_seen(ROOT)
        links = [
            "/about",
            "/about/",  # the same page
            "/circulars/a.pdf",
            "/circulars/b.pdf",
            "/img/logo.png",
            "/img/logo.png?v=2",  # a different address for the tally, as for a browser
            "/img/logo.png#top",  # the same image
            "/downloads/form.docx",
            "/2024/06/",
            "/category/news/",
            "/tag/exams/",
            "https://other.test/x.png",  # not this site
            "mailto:someone@x.test",
        ]
        accepted = frontier.extend(links, 1, base=ROOT)
        # Since #94 a PDF is counted and cited but not queued; `fetch_files` restores the
        # old behaviour and is pinned in `test_crawl_limits.py`.
        assert f"{ROOT}circulars/a.pdf" not in accepted, "files are counted, not queued"
        assert f"{ROOT}img/logo.png" not in accepted, "images are not queued"
        assert frontier.kinds == {
            "page": 2,  # the root and /about
            "pdf": 2,
            "image": 2,
            "other_file": 1,
            "archive": 1,
            "category": 1,
            "tag": 1,
        }

    def test_the_tally_is_a_dict_of_ints_for_the_stream(self) -> None:
        frontier = Frontier(scope=CrawlScope(root=ROOT))
        frontier.extend(["/a.pdf"], 1, base=ROOT)
        assert dict(frontier.kinds)["pdf"] == 1


class TestTheStreamReportsIt:
    """`stream_site` with the network replaced: the probe is faked as `test_site_pipeline`
    does, and returns a policy with a file and a sitemap walk that found nothing."""

    @pytest.fixture(autouse=True)
    def offline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph import site as site_module
        from webgraph.analyze import SiteAnalysis, SiteProbe
        from webgraph.pipeline import build_document
        from webgraph.resolve import ResolvedPage, Strategy

        html = (
            "<html><head><title>Root</title></head><body><main><h1>Root</h1>"
            "<p>Enough prose to count as a page, and then some more of it to be sure.</p>"
            '<a href="/circulars/a.pdf">Circular</a> <a href="/img/logo.png">Logo</a> '
            '<a href="/2024/06/">June</a> <a href="/about">About</a></main></body></html>'
        )

        def resolved_for(url: str) -> ResolvedPage:
            document = build_document(html, url)
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

        listed: list[str] = []

        def fake_probe(root: str, **_: Any) -> SiteProbe:
            return SiteProbe(
                analysis=SiteAnalysis(root=root, reachable=True),
                resolved=resolved_for(root),
                policy=RobotsPolicy(
                    origin=root.rstrip("/"),
                    fetched=True,
                    status=200,
                    text=ROBOTS,
                    rules=("Disallow: /admin/", "Crawl-delay: 2"),
                    group="*",
                    crawl_delay=2.0,
                ),
                sitemap_pages=tuple(listed),
                sitemap_attempts=(
                    SitemapAttempt(
                        f"{root}sitemap.xml",
                        404,
                        ok=False,
                        urls=0,
                        index=False,
                        source="conventional",
                    ),
                    SitemapAttempt(
                        f"{root}sitemap_index.xml",
                        404,
                        ok=False,
                        urls=0,
                        index=False,
                        source="conventional",
                    ),
                ),
            )

        monkeypatch.setattr(site_module, "probe_site", fake_probe)
        monkeypatch.setattr(site_module, "resolve_page", lambda url, **_: resolved_for(url))
        self.listed = listed

    def _events(self) -> list[dict[str, Any]]:
        from webgraph.site import SiteConfig, stream_site

        return list(
            stream_site(
                ROOT,
                config=SiteConfig(
                    max_pages=1, concurrency=1, delay_seconds=0.0, host_interval_seconds=0.0
                ),
            )
        )

    def test_a_discovery_event_follows_the_analysis(self) -> None:
        events = self._events()
        types = [e["type"] for e in events]
        assert types.index("analysis") < types.index("discovery") < types.index("frontier")
        event = next(e for e in events if e["type"] == "discovery")
        assert event["robots"] == {
            "found": True,
            "url": "https://x.test/robots.txt",
            "fetched_status": 200,
            "group": "*",
            "rules_for_us": ["Disallow: /admin/", "Crawl-delay: 2"],
            "crawl_delay": 2.0,
            "text": ROBOTS,
            "text_truncated": False,
            "text_chars": len(ROBOTS),
        }
        assert event["sitemaps"]["found"] == 0
        assert event["sitemaps"]["total_urls"] == 0
        assert [a["status"] for a in event["sitemaps"]["attempts"]] == [404, 404]
        assert event["seeds"] == 0

    def test_a_sitemap_naming_only_the_root_is_in_scope_and_seeds_nothing(self) -> None:
        """lakshx.in's sitemap lists the home page and nothing else. The home page was
        fetched before the crawl began, so it seeded nothing -- and `seeds == 0` beside
        `total_urls == 1` read, on screen, as "every listed address is on another site".
        `in_scope` is the count the scope admits, whatever was already known."""
        self.listed[:] = ["https://x.test"]
        event = next(e for e in self._events() if e["type"] == "discovery")
        assert event["sitemaps"]["total_urls"] == 1
        assert event["sitemaps"]["in_scope"] == 1
        assert event["seeds"] == 0

    def test_a_sitemap_naming_another_host_is_out_of_scope(self) -> None:
        self.listed[:] = ["https://elsewhere.test/a", "https://elsewhere.test/b"]
        event = next(e for e in self._events() if e["type"] == "discovery")
        assert event["sitemaps"]["total_urls"] == 2
        assert event["sitemaps"]["in_scope"] == 0

    def test_the_done_event_names_the_depth_cap(self) -> None:
        from webgraph.site import SiteConfig, stream_site

        events = list(
            stream_site(
                ROOT,
                config=SiteConfig(
                    max_pages=1,
                    max_depth=3,
                    concurrency=1,
                    delay_seconds=0.0,
                    host_interval_seconds=0.0,
                ),
            )
        )
        done = next(e for e in events if e["type"] == "done")
        assert done["limits"]["max_depth"] == 3

    def test_the_robots_text_is_capped_but_the_rules_are_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph import site as site_module

        monkeypatch.setattr(site_module, "DISCOVERY_ROBOTS_TEXT_CHARS", 10)
        event = next(e for e in self._events() if e["type"] == "discovery")
        assert event["robots"]["text"] == ROBOTS[:10]
        assert event["robots"]["text_truncated"] is True
        assert event["robots"]["text_chars"] == len(ROBOTS)
        assert event["robots"]["rules_for_us"] == ["Disallow: /admin/", "Crawl-delay: 2"]

    def test_frontier_and_page_events_carry_the_kinds(self) -> None:
        events = self._events()
        frontier = next(e for e in events if e["type"] == "frontier")
        assert frontier["discovered_kinds"] == dict.fromkeys(KINDS, 0) | {"page": 1}
        page = next(e for e in events if e["type"] == "page")
        kinds = page["discovered_kinds"]
        assert kinds["pdf"] == 1
        assert kinds["image"] == 1, "an image is counted though it is never queued"
        assert kinds["archive"] == 1
        assert kinds["page"] == 2  # the root and /about
        # A copy, not the frontier's own dict: the API serialises later, on another thread.
        assert kinds is not frontier["discovered_kinds"]


class TestTheAnalysisCarriesItToo:
    def test_analyze_site_reports_rules_and_attempts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`analyze_site` (the CLI's `analyze`) exposes the same facts as the stream."""
        from webgraph import analyze as analyze_module
        from webgraph.pipeline import build_document
        from webgraph.resolve import ResolvedPage, Strategy

        serve(
            monkeypatch,
            {f"{ROOT}robots.txt": (ROBOTS, 200), f"{ROOT}part-1.xml": (SITEMAP_PART, 200)},
        )
        html = "<html><head><title>R</title></head><body><main><p>Some words for a root page.</p></main></body></html>"

        def fake_resolve(url: str, **_: Any) -> ResolvedPage:
            document = build_document(html, url)
            return ResolvedPage(
                url=url,
                document=document,
                strategy=Strategy.STATIC_ONLY,
                static_chars=len(document.text),
                rendered_chars=0,
                union_chars=len(document.text),
                blocks_only_in_static=0,
                blocks_only_in_rendered=0,
            )

        monkeypatch.setattr(analyze_module, "resolve_page", fake_resolve)
        analysis = analyze_module.analyze_site(ROOT)
        assert analysis.robots_found
        assert analysis.robots_rules == (
            "Disallow: /admin/",
            "Disallow: /tmp/",
            "Allow: /tmp/public/",
            "Crawl-delay: 2",
        )
        assert [a["url"] for a in analysis.sitemap_attempts] == [
            f"{ROOT}from-robots.xml",
            f"{ROOT}sitemap.xml",
            f"{ROOT}sitemap_index.xml",
        ]
        assert all(a["status"] == 404 for a in analysis.sitemap_attempts)
        report = analysis.report()
        assert "Disallow: /admin/" in report
        assert "404  https://x.test/sitemap.xml  (not a sitemap)" in report
