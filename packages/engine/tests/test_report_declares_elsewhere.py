"""Site Truth Report findings for a site that declares another host as its own -- in its
canonicals, in its sitemap -- and for pages that draw their content in a canvas. The
shape is bhavyadhanwani.dev after its move from a Vercel host to its own domain.
"""

from __future__ import annotations

from webgraph.pipeline import build_document
from webgraph.report.pages import PageReport, measure_page
from webgraph.report.score import integrity_findings
from webgraph.resolve import ResolvedPage, Strategy

HOST = "www.example.test"
OLD = "https://old-host.example.net"
PROSE = (
    "The quick brown fox jumped over the lazy dog and continued running through the "
    "field until it reached the far treeline where it finally stopped to rest a while. "
)


def resolved(url: str, html: str) -> ResolvedPage:
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
        static_words=len(document.text.split()),
        union_words=len(document.text.split()),
    )


def page(url: str, html: str) -> PageReport:
    return measure_page(resolved(url, html), requested_url=url, host=HOST)


def test_canonicals_on_another_host_are_a_high_finding() -> None:
    home = page(
        f"https://{HOST}/",
        f'<html><head><link rel="canonical" href="{OLD}"></head><body><p>{PROSE}1.</p></body></html>',
    )
    about = page(
        f"https://{HOST}/about",
        f'<html><head><link rel="canonical" href="{OLD}/about"></head><body><p>{PROSE}2.</p></body></html>',
    )
    fine = page(
        f"https://{HOST}/blog",
        f'<html><head><link rel="canonical" href="https://example.test/blog"></head><body><p>{PROSE}3.</p></body></html>',
    )
    findings = integrity_findings([home, about, fine], [])
    kinds = [f.kind for f in findings]
    assert kinds == ["canonical_elsewhere"]
    finding = findings[0]
    assert finding.severity == "high"
    assert "2 of 3 sampled pages" in finding.detail
    assert "old-host.example.net (2)" in finding.detail
    assert finding.page == f"https://{HOST}/"
    # `www.` and the bare domain are one site: the blog's canonical raises nothing.


def test_a_sitemap_entirely_on_another_host() -> None:
    findings = integrity_findings([], [], sitemap_elsewhere=(2, ("old-host.example.net",)))
    assert [f.kind for f in findings] == ["sitemap_elsewhere"]
    assert "Every one of the 2 addresses" in findings[0].detail
    assert "old-host.example.net" in findings[0].detail
    # None when at least one address was on this host: `build_site_report` passes None.
    assert integrity_findings([], [], sitemap_elsewhere=None) == ()


def test_pages_drawn_in_a_canvas() -> None:
    drawn = page(
        f"https://{HOST}/projects",
        "<html><body><canvas></canvas><p>Click on the Project for Details</p><a href='/'>Home</a></body></html>",
    )
    written = page(f"https://{HOST}/", f"<html><body><p>{PROSE}1.</p></body></html>")
    assert drawn.canvas is True and written.canvas is False
    assert drawn.as_dict()["canvas"] is True
    findings = integrity_findings([drawn, written], [])
    assert [f.kind for f in findings] == ["canvas_content"]
    assert findings[0].severity == "medium"
    assert "/projects (7 words)" in findings[0].detail
    assert findings[0].page == drawn.url
