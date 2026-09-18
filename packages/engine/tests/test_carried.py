"""What a page carries that is not on it: the canvas verdict, the addresses in its scripts,
and the links to other sites -- reported on the page event, never queued.

The shape is bhavyadhanwani.dev/projects: one `<canvas>`, seven words, a link home, and
three projects that exist only as a data array in a bundle, each with a repository and a
live address on other hosts.
"""

from __future__ import annotations

from typing import Any

import pytest

from webgraph import site as site_module
from webgraph.analyze import SiteAnalysis, SiteProbe
from webgraph.carried import CANVAS_MAX_WORDS, MAX_SCRIPT_LINKS, canvas_verdict, script_links
from webgraph.crawl.discovery import RobotsPolicy
from webgraph.pipeline import build_document
from webgraph.resolve import ResolvedPage, Strategy
from webgraph.site import SiteConfig, stream_site

ROOT = "https://www.example.test/"
PROSE = (
    "The quick brown fox jumped over the lazy dog and continued running through the "
    "field until it reached the far treeline where it finally stopped to rest a while. "
)

# A minified bundle: the author's data array, and the noise a bundle also carries.
BUNDLE = (
    'var p=[{name:"jarvis",github:"https://github.com/someone/jarvis.git",live:"https://jarvis.example.net/"},'
    '{name:"dole",github:"https://github.com/someone/dole.git",live:"https://www.dole-shole.example/"},'
    '{"name":"self","live":"https://www.example.test/"}];'
    "/*! core-js https://github.com/zloirock/core-js/blob/LICENSE */"
    'var cj={version:"3.38.1",license:"https://github.com/zloirock/core-js/blob/v3.38.1/LICENSE",'
    'homepage:"https://core-js.example/"};'
    'var u=new URL("https://a"),v="http://n";if(x)throw Error("see https://docs.pmnd.rs/objects");'
    'fetch("https://api.example.test/data")'
)


class TestScriptLinks:
    def test_named_values_are_taken_and_bare_urls_are_not(self) -> None:
        found = script_links(BUNDLE, page_url=ROOT)
        assert [(link.key, link.url) for link in found] == [
            ("github", "https://github.com/someone/jarvis.git"),
            ("live", "https://jarvis.example.net/"),
            ("github", "https://github.com/someone/dole.git"),
            ("live", "https://www.dole-shole.example/"),
        ]
        # Left out: the page's own address; the regex test strings, the docs link and the
        # fetch call (bare URLs, not named values); and core-js's `license`/`homepage`
        # (named, but a library's provenance, never the site's).

    def test_empty_source(self) -> None:
        assert script_links("", page_url=ROOT) == ()

    def test_capped(self) -> None:
        source = "".join(f'x{i}:"https://h{i}.example.net/"' for i in range(MAX_SCRIPT_LINKS + 5))
        assert len(script_links(source)) == MAX_SCRIPT_LINKS


class TestCanvasVerdict:
    def test_a_canvas_with_few_words_is_a_canvas_page(self) -> None:
        html = "<html><body><canvas></canvas><p>Click on the Project for Details</p><a href='/'>Home</a></body></html>"
        verdict = canvas_verdict(build_document(html, ROOT + "projects"))
        assert verdict is not None
        assert verdict.canvases == 1
        assert verdict.words == 7

    def test_a_canvas_inside_an_article_is_not(self) -> None:
        body = "".join(
            f"<p>{PROSE}{i}.</p>" for i in range(3)
        )  # distinct, or the pipeline folds them
        html = f"<html><body><canvas></canvas>{body}</body></html>"
        assert canvas_verdict(build_document(html, ROOT)) is None

    def test_no_canvas_is_not(self) -> None:
        assert canvas_verdict(build_document("<html><body><p>hi</p></body></html>", ROOT)) is None

    def test_the_threshold(self) -> None:
        words = " ".join("w" for _ in range(CANVAS_MAX_WORDS))
        html = f"<html><body><canvas></canvas><p>{words}</p></body></html>"
        assert canvas_verdict(build_document(html, ROOT)) is None


# ---- the page event ------------------------------------------------------------------

HOME = (
    "<html><head><title>home</title></head><body><main>"
    + "".join(f"<p>{PROSE}{i}.</p>" for i in range(6))
    + '<a href="/projects">Enter</a> <a href="https://github.com/someone">GitHub</a>'
    ' <a href="https://github.com/someone">GitHub again</a> <a href="mailto:x@example.test">mail</a>'
    "</main></body></html>"
)
PROJECTS = (
    '<html><head><title>projects</title><script src="/_next/static/chunks/app.js"></script></head>'
    "<body><canvas></canvas><p>Click on the Project for Details</p><a href='/'>Home</a></body></html>"
)
PAGES = {ROOT: HOME, f"{ROOT}projects": PROJECTS}


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


@pytest.fixture
def faked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    bundles_read: list[str] = []

    def fake_probe(root: str, **_: Any) -> SiteProbe:
        return SiteProbe(
            analysis=SiteAnalysis(root=root, reachable=True),
            resolved=resolved_for(root),
            policy=RobotsPolicy(origin=root),
            sitemap_pages=(),
        )

    def fake_resolve(url: str, **_: Any) -> ResolvedPage:
        if url not in PAGES:
            raise ValueError(f"not a page on this site: {url}")
        return resolved_for(url)

    def fake_bundle(_html: str, base_url: str, **_: Any) -> str:
        bundles_read.append(base_url)
        return BUNDLE

    monkeypatch.setattr(site_module, "probe_site", fake_probe)
    monkeypatch.setattr(site_module, "resolve_page", fake_resolve)
    monkeypatch.setattr(site_module, "collect_bundle_source", fake_bundle)
    return bundles_read


def test_the_page_event_reports_what_the_page_carries(faked: list[str]) -> None:
    events = list(
        stream_site(
            ROOT,
            config=SiteConfig(
                concurrency=1, delay_seconds=0.0, host_interval_seconds=0.0, verify_inventory=False
            ),
        )
    )
    pages = {e["url"]: e for e in events if e["type"] == "page"}
    done = next(e for e in events if e["type"] == "done")

    home = pages[ROOT]
    assert home["canvas"] is None
    # Other-site links from real anchors: deduplicated, with their anchor text; mailto: is
    # not a site. Same-site links are not here -- they were queued instead.
    assert home["links_out"]["external"] == [
        {"url": "https://github.com/someone", "anchor": "GitHub"}
    ]
    assert home["links_out"]["in_script"] == []
    assert home["new_urls"] == [f"{ROOT}projects"]

    projects = pages[f"{ROOT}projects"]
    assert projects["canvas"] == {"canvases": 1, "words": 7, "script_bytes": len(BUNDLE)}
    # What each fetch gave rides on every page event (static-only here, so no render).
    assert projects["static_chars"] > 0 and projects["rendered_chars"] == 0
    assert [link["url"] for link in projects["links_out"]["in_script"]] == [
        "https://github.com/someone/jarvis.git",
        "https://jarvis.example.net/",
        "https://github.com/someone/dole.git",
        "https://www.dole-shole.example/",
        # The site's own root, stored as a project's `live` address: kept, because it is a
        # statement the script makes; only the page's own address is left out.
        "https://www.example.test/",
    ]
    # Found in script, never queued: the crawl is still two pages, the frontier ran dry.
    assert projects["new_urls"] == []
    assert done["pages_ok"] == 2 and done["exhausted"] is True
    # The bundle was read for the canvas page only.
    assert faked == [f"{ROOT}projects"]
