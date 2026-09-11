"""What a crawl does with the root, with each page's HTML, and with its content.

Three things measured on the previous architecture, each fixed here and pinned by a test:

- **The root was fetched three times.** `resolve_root` fetched it to follow redirects,
  `analyze_site` fetched it both ways to measure the site, and the crawl fetched it again as
  page one -- three static fetches and two renders of one URL, plus robots.txt and every
  sitemap read twice. The page the analysis measured *is* the root page.
- **Every page's HTML was kept until the crawl ended.** The markup is read once, for links,
  and is the largest field a page carries; retaining it for 200 pages held the whole site in
  memory to compute a handful of entity counts at the end.
- **The main-content selector was called by nothing.** The precision work that lifted Zyte
  from 0.647 to 0.87 lived in a module no product path imported.

Everything here runs without a network: the analysis and the per-page resolution are
replaced with fakes that count.
"""

from __future__ import annotations

from typing import Any

import pytest

from webgraph import site as site_module
from webgraph.analyze import SiteAnalysis, SiteProbe
from webgraph.crawl.discovery import RobotsPolicy
from webgraph.pipeline import build_document
from webgraph.resolve import ResolvedPage, Strategy
from webgraph.site import SiteConfig, extract_site, stream_site

ROOT = "https://example.test/"

PROSE = (
    "The quick brown fox jumped over the lazy dog and continued running through the "
    "field until it reached the far treeline where it finally stopped to rest a while. "
)


def page_html(name: str, links: tuple[str, ...]) -> str:
    nav = "".join(f'<a href="{href}">{href.strip("/") or "home"}</a> ' for href in links)
    body = "".join(f"<p>{PROSE}Paragraph {name} {i}.</p>" for i in range(6))
    return (
        f"<html><head><title>{name}</title></head><body>"
        f"<nav>{nav}</nav><main><h1>Page {name}</h1>{body}</main>"
        f"<footer><a href='/terms'>Terms</a> <a href='/privacy'>Privacy</a></footer>"
        "</body></html>"
    )


PAGES: dict[str, str] = {
    ROOT: page_html("root", ("/", "/a", "/b")),
    f"{ROOT}a": page_html("a", ("/", "/a", "/b")),
    f"{ROOT}b": page_html("b", ("/", "/a", "/b")),
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
def fetches(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Replace the network with a counter. Keys are URLs; values are how often each was
    resolved by the crawl, *excluding* the analysis (`probe`) which is counted separately."""
    counts: dict[str, int] = {"__probe__": 0}

    def fake_probe(root: str, **_: Any) -> SiteProbe:
        counts["__probe__"] += 1
        analysis = SiteAnalysis(root=root, reachable=True)
        return SiteProbe(
            analysis=analysis,
            resolved=resolved_for(root),
            policy=RobotsPolicy(origin=root),
            sitemap_pages=(f"{root}a", f"{root}b"),
        )

    def fake_resolve(url: str, **_: Any) -> ResolvedPage:
        counts[url] = counts.get(url, 0) + 1
        return resolved_for(url)

    monkeypatch.setattr(site_module, "probe_site", fake_probe)
    monkeypatch.setattr(site_module, "resolve_page", fake_resolve)
    return counts


CONFIG = SiteConfig(max_pages=3, concurrency=1, delay_seconds=0.0, verify_inventory=False)

# `extract_site` enumerates before it fetches, and link-following enumeration is a network
# walk this fixture does not fake. The sitemap the fake probe reports is enough.
BATCH_CONFIG = SiteConfig(
    max_pages=3, concurrency=1, delay_seconds=0.0, verify_inventory=False, follow_links=False
)


class TestRootIsFetchedOnce:
    def test_stream_reuses_the_analysed_root(self, fetches: dict[str, int]) -> None:
        events = list(stream_site(ROOT, config=CONFIG))
        pages = [e for e in events if e["type"] == "page"]
        assert [p["url"] for p in pages] == [ROOT, f"{ROOT}a", f"{ROOT}b"]
        assert fetches["__probe__"] == 1
        assert ROOT not in fetches, "the root was resolved again after the analysis"
        assert fetches[f"{ROOT}a"] == 1
        assert fetches[f"{ROOT}b"] == 1

    def test_the_root_is_the_first_page_at_depth_zero(self) -> None:
        first = next(e for e in stream_site(ROOT, config=CONFIG) if e["type"] == "page")
        assert first["url"] == ROOT
        assert first["depth"] == 0
        assert first["ok"]

    def test_the_root_still_extends_the_frontier(self) -> None:
        """Reusing the analysed page must not lose its links -- they are how the crawl
        leaves the root at all when there is no sitemap."""
        first = next(e for e in stream_site(ROOT, config=CONFIG) if e["type"] == "page")
        # `a` and `b` arrived via the sitemap; the footer links did not, so they are the
        # root's own contribution.
        assert set(first["new_urls"]) >= {f"{ROOT}terms", f"{ROOT}privacy"}

    def test_a_page_linking_back_to_the_root_does_not_requeue_it(self) -> None:
        done = next(e for e in stream_site(ROOT, config=CONFIG) if e["type"] == "done")
        assert done["pages_total"] == 3
        # root, a, b, and the two footer links the budget never reached. Every page links
        # back to the root; had that re-queued it, a fourth fetch would have been attempted
        # and the fake resolver would have counted it.
        assert done["discovered"] == 5
        assert done["remaining_queued"] == 2

    def test_extract_site_reuses_the_analysed_root_too(self, fetches: dict[str, int]) -> None:
        result = extract_site(ROOT, config=BATCH_CONFIG)
        assert [p.url for p in result.pages] == [ROOT, f"{ROOT}a", f"{ROOT}b"]
        assert ROOT not in fetches

    def test_budget_of_one_is_the_root_alone(self, fetches: dict[str, int]) -> None:
        config = SiteConfig(max_pages=1, concurrency=1, delay_seconds=0.0, verify_inventory=False)
        pages = [e for e in stream_site(ROOT, config=config) if e["type"] == "page"]
        assert [p["url"] for p in pages] == [ROOT]
        assert not any(url in fetches for url in PAGES)


class TestHtmlIsDropped:
    def test_pages_kept_by_extract_site_carry_no_html(self) -> None:
        result = extract_site(ROOT, config=BATCH_CONFIG)
        assert all(p.document is not None and p.document.html == "" for p in result.pages)

    def test_but_blocks_and_payloads_survive(self) -> None:
        result = extract_site(ROOT, config=BATCH_CONFIG)
        for page in result.pages:
            assert page.document is not None
            assert page.document.blocks
            assert page.text_chars > 0

    def test_the_document_type_permits_it(self) -> None:
        document = build_document(PAGES[ROOT], ROOT)
        slim = document.model_copy(update={"html": ""})
        assert slim.html == ""
        assert slim.blocks == document.blocks
        assert slim.content_hash == document.content_hash


class TestContentIsSelected:
    def test_page_events_carry_the_content_and_say_how(self) -> None:
        first = next(e for e in stream_site(ROOT, config=CONFIG) if e["type"] == "page")
        assert first["content_markdown"]
        assert "Terms" not in first["content_markdown"]
        assert "Paragraph root 3." in first["content_markdown"]
        assert first["content_methods"][0] == "landmarks"
        assert 0 < first["content_blocks"] <= first["blocks"]

    def test_the_full_markdown_is_still_complete(self) -> None:
        """`content_markdown` is an addition, never a substitute: the lose-nothing output
        keeps the footer the content view dropped."""
        first = next(e for e in stream_site(ROOT, config=CONFIG) if e["type"] == "page")
        assert "Terms" in first["markdown"]

    def test_main_content_can_be_switched_off(self) -> None:
        config = SiteConfig(
            max_pages=1, concurrency=1, delay_seconds=0.0, verify_inventory=False,
            main_content=False,
        )
        first = next(e for e in stream_site(ROOT, config=config) if e["type"] == "page")
        assert "main-content" not in first["content_methods"]

    def test_remove_chrome_off_means_no_content_view(self) -> None:
        config = SiteConfig(
            max_pages=1, concurrency=1, delay_seconds=0.0, verify_inventory=False,
            remove_chrome=False,
        )
        first = next(e for e in stream_site(ROOT, config=config) if e["type"] == "page")
        assert first["content_markdown"] == ""
        assert first["content_methods"] == []

    def test_extract_site_fills_content_markdown(self) -> None:
        """The non-streaming path never populated this field at all."""
        result = extract_site(ROOT, config=BATCH_CONFIG)
        assert all(p.content_markdown for p in result.pages)
        assert all("landmarks" in p.content_methods for p in result.pages)


class TestUnreachable:
    def test_an_unreachable_root_is_an_error_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_probe(root: str, **_: Any) -> SiteProbe:
            return SiteProbe(SiteAnalysis(root=root, reachable=False, error="HTTP 503"))

        monkeypatch.setattr(site_module, "probe_site", fake_probe)
        events = list(stream_site(ROOT, config=CONFIG))
        assert events[-1]["type"] == "error"
        assert "503" in events[-1]["message"]
