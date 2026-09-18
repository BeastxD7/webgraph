"""A page's relative links resolve against the address it was served at, not its canonical.

Regression for bhavyadhanwani.dev: a two-page Next.js site that declares its previous host,
`bhavyaz-portfolio.vercel.app`, as `<link rel="canonical">` on every page (and lists that host
in its sitemap). Its home page has exactly one link, `<a href="/projects">`. Resolving that
against the canonical made it `https://bhavyaz-portfolio.vercel.app/projects` -- off-site under
`strict_domain` -- and the crawl finished after one page, reporting the frontier exhausted.

The network is faked as in `test_crawl_limits.py`.
"""

from __future__ import annotations

from typing import Any

import pytest

from webgraph import site as site_module
from webgraph.analyze import SiteAnalysis, SiteProbe
from webgraph.crawl.discovery import RobotsPolicy
from webgraph.pipeline import build_document
from webgraph.resolve import ResolvedPage, Strategy
from webgraph.site import SiteConfig, stream_site

ROOT = "https://www.example.test/"
OLD_HOST = "https://old-host.example.net"

PROSE = (
    "The quick brown fox jumped over the lazy dog and continued running through the "
    "field until it reached the far treeline where it finally stopped to rest a while. "
)


def page_html(name: str, links: tuple[str, ...]) -> str:
    anchors = "".join(f'<a href="{href}">Enter {href}</a>' for href in links)
    body = "".join(f"<p>{PROSE}Paragraph {name} {i}.</p>" for i in range(6))
    return (
        f"<html><head><title>{name}</title>"
        f'<link rel="canonical" href="{OLD_HOST}{"" if name == "root" else "/" + name}"/>'
        f"</head><body><main><h1>Page {name}</h1>{body}<section>{anchors}</section></main>"
        "</body></html>"
    )


PAGES: dict[str, str] = {
    ROOT: page_html("root", ("/projects",)),
    f"{ROOT}projects": page_html("projects", ("/",)),
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
            raise ValueError(f"not a page on this site: {url}")
        return resolved_for(url)

    monkeypatch.setattr(site_module, "probe_site", fake_probe)
    monkeypatch.setattr(site_module, "resolve_page", fake_resolve)
    return asked


def test_a_link_is_followed_even_when_the_canonical_names_another_host(fetched: list[str]) -> None:
    events = list(
        stream_site(
            ROOT,
            config=SiteConfig(
                concurrency=1, delay_seconds=0.0, host_interval_seconds=0.0, verify_inventory=False
            ),
        )
    )
    done = next(e for e in events if e["type"] == "done")
    pages = [e for e in events if e["type"] == "page"]

    assert done["pages_ok"] == 2, [e.get("url") for e in pages]
    assert f"{ROOT}projects" in fetched
    assert not any(OLD_HOST in url for url in fetched), "the canonical's host must never be fetched"

    # The citation says how /projects entered the crawl: the home page, by its link text.
    projects = next(e for e in pages if e["url"] == f"{ROOT}projects")
    assert projects["citation"] == {
        "via": "link",
        "found_on": ROOT,
        "anchor": "Enter /projects",
        "depth": 1,
    }
    # And the home page reported the discovery, rather than an empty frontier.
    home = next(e for e in pages if e["url"] == ROOT)
    assert home["new_urls"] == [f"{ROOT}projects"]
