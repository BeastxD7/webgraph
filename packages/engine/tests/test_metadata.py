"""`read_metadata`: what a page declares in its `<head>`, and which declarations name
another site.

The first case is bhavyadhanwani.dev's head as served: `canonical` and `og:url` both name
the site's previous host. The second is persyn.ai's: a `www.` canonical on a page served at
the bare domain, which is the same site and must not be flagged.
"""

from __future__ import annotations

from typing import Any

import pytest

from webgraph import site as site_module
from webgraph.analyze import SiteAnalysis, SiteProbe
from webgraph.crawl.discovery import RobotsPolicy
from webgraph.metadata import MAX_ALTERNATES, MAX_VALUE_CHARS, read_metadata
from webgraph.page import stream_page
from webgraph.pipeline import build_document
from webgraph.resolve import ResolvedPage, Strategy
from webgraph.site import SiteConfig, stream_site
from webgraph.types import PayloadSource, StructuredPayload

URL = "https://www.bhavyadhanwani.dev/"

HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>I Only Create</title>
<meta name="description" content="Portfolio of a developer who only creates.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0b0b0f">
<meta name="robots" content="index, follow, max-snippet:-1">
<meta name="generator" content="Next.js">
<link rel="canonical" href="https://bhavyaz-portfolio.vercel.app"/>
<meta property="og:url" content="https://bhavyaz-portfolio.vercel.app"/>
<meta property="og:title" content="I Only Create"/>
<meta property="og:image" content="/og.png"/>
<meta property="og:type" content="website"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:site" content="@bhavyaz"/>
<link rel="icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<link rel="alternate" type="application/rss+xml" href="/feed.xml">
<link rel="alternate" hreflang="en" href="https://www.bhavyadhanwani.dev/">
<link rel="alternate" hreflang="hi" href="https://www.bhavyadhanwani.dev/hi/">
</head><body><main><h1>Projects</h1><a href="/projects">Enter the Experience</a></main></body></html>"""


class TestReadMetadata:
    def test_the_head_as_declared(self) -> None:
        payloads = (
            StructuredPayload(
                source=PayloadSource.JSON_LD,
                data={"@context": "https://schema.org", "@type": "Person", "name": "Bhavya"},
            ),
            StructuredPayload(
                source=PayloadSource.JSON_LD,
                data={"@graph": [{"@type": "WebSite"}, {"@type": ["Person", "Thing"]}]},
            ),
            StructuredPayload(source=PayloadSource.OPEN_GRAPH, data={"og:type": "website"}),
        )
        meta = read_metadata(HEAD, URL, structured_data=payloads)

        assert meta.url == URL
        assert meta.title == "I Only Create"
        assert meta.description == "Portfolio of a developer who only creates."
        assert meta.language == "en"
        assert meta.charset == "utf-8"
        assert meta.robots == "index, follow, max-snippet:-1"
        assert meta.generator == "Next.js"
        assert meta.theme_color == "#0b0b0f"
        assert meta.viewport == "width=device-width, initial-scale=1"
        assert meta.canonical == "https://bhavyaz-portfolio.vercel.app"
        # Relative addresses are made absolute against the page's own URL.
        assert meta.icons == (f"{URL}favicon.ico", f"{URL}apple-touch-icon.png")
        assert meta.manifest == f"{URL}site.webmanifest"
        assert meta.feeds == (f"{URL}feed.xml",)
        assert (
            meta.open_graph["og:image"] == f"{URL}og.png"
            or meta.open_graph["og:image"] == "/og.png"
        )
        assert meta.open_graph["og:title"] == "I Only Create"
        assert meta.twitter == {"twitter:card": "summary_large_image", "twitter:site": "@bhavyaz"}
        assert meta.alternates == (
            {"hreflang": "en", "href": URL},
            {"hreflang": "hi", "href": f"{URL}hi/"},
        )
        assert meta.alternate_count == 2
        # JSON-LD types in order of first appearance, `@graph` walked, lists flattened; the
        # Open Graph payload contributes nothing here (it is not a schema.org claim).
        assert meta.schema_types == ("Person", "WebSite", "Thing")
        # Both declared addresses name the old host -- the fact nothing on the page shows.
        assert meta.declared_elsewhere == (
            "canonical -> https://bhavyaz-portfolio.vercel.app",
            "og:url -> https://bhavyaz-portfolio.vercel.app",
        )

    def test_a_www_canonical_is_the_same_site(self) -> None:
        html = '<html><head><link rel="canonical" href="https://www.persyn.ai/"></head></html>'
        meta = read_metadata(html, "https://persyn.ai/")
        assert meta.canonical == "https://www.persyn.ai/"
        assert meta.declared_elsewhere == ()

    def test_an_empty_head_declares_nothing(self) -> None:
        blank = read_metadata("<html><body><p>hi</p></body></html>", URL)
        assert blank.as_dict()["title"] is None
        assert blank.as_dict()["open_graph"] == {}
        # No markup at all is not an error either: the same nothing, with the URL.
        assert read_metadata("", URL) == blank
        assert read_metadata("   ", URL).url == URL

    def test_values_are_folded_and_capped(self) -> None:
        long = "word " * 200
        html = f'<html><head><title>  A\n  title </title><meta name="description" content="{long}"></head></html>'
        meta = read_metadata(html, URL)
        assert meta.title == "A title"
        assert meta.description is not None and len(meta.description) == MAX_VALUE_CHARS

    def test_alternates_are_capped_but_counted(self) -> None:
        links = "".join(
            f'<link rel="alternate" hreflang="x{i}" href="/x{i}/">'
            for i in range(MAX_ALTERNATES + 10)
        )
        meta = read_metadata(f"<html><head>{links}</head></html>", URL)
        assert len(meta.alternates) == MAX_ALTERNATES
        assert meta.alternate_count == MAX_ALTERNATES + 10


# ---- the events carry it -------------------------------------------------------------

PROSE = (
    "The quick brown fox jumped over the lazy dog and continued running through the "
    "field until it reached the far treeline where it finally stopped to rest a while. "
)
PAGE = HEAD.replace("<main>", "<main>" + "".join(f"<p>{PROSE}{i}.</p>" for i in range(6)))


def resolved_for(url: str) -> ResolvedPage:
    document = build_document(PAGE, url)
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


@pytest.fixture
def faked(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_probe(root: str, **_: Any) -> SiteProbe:
        document = resolved_for(root).document
        from webgraph.metadata import read_metadata as read

        analysis = SiteAnalysis(
            root=root,
            reachable=True,
            metadata=read(
                document.html, document.url, structured_data=document.structured_data
            ).as_dict(),
        )
        return SiteProbe(
            analysis=analysis,
            resolved=resolved_for(root),
            policy=RobotsPolicy(origin=root),
            sitemap_pages=(),
        )

    def fake_resolve(url: str, **_: Any) -> ResolvedPage:
        if url != URL:
            raise ValueError(f"not a page on this site: {url}")
        return resolved_for(url)

    monkeypatch.setattr(site_module, "probe_site", fake_probe)
    monkeypatch.setattr(site_module, "resolve_page", fake_resolve)
    import webgraph.page as page_module

    monkeypatch.setattr(page_module, "resolve_page", fake_resolve)


@pytest.mark.usefixtures("faked")
def test_the_analysis_event_carries_the_metadata() -> None:
    events = list(
        stream_site(
            URL,
            config=SiteConfig(
                concurrency=1, delay_seconds=0.0, host_interval_seconds=0.0, verify_inventory=False
            ),
        )
    )
    analysis = next(e for e in events if e["type"] == "analysis")
    assert analysis["metadata"]["title"] == "I Only Create"
    assert analysis["metadata"]["declared_elsewhere"] == [
        "canonical -> https://bhavyaz-portfolio.vercel.app",
        "og:url -> https://bhavyaz-portfolio.vercel.app",
    ]


@pytest.mark.usefixtures("faked")
def test_the_resolve_event_carries_the_metadata() -> None:
    events = list(stream_page(URL, strategy=Strategy.STATIC_ONLY))
    resolve = next(e for e in events if e["type"] == "resolve")
    assert resolve["metadata"]["title"] == "I Only Create"
    assert resolve["metadata"]["language"] == "en"
    assert resolve["metadata"]["declared_elsewhere"][0].startswith("canonical -> ")
