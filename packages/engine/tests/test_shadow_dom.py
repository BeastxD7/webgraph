"""Content inside shadow roots, which was invisible twice over.

A TreeWalker stops at a shadow boundary and `outerHTML` does not serialise across one. So a
component rendering its content inside an open shadow root was absent from the HTML lxml
parses *and* absent from the geometry map, with nothing reporting it. The loss is total, not
partial -- the failure class this engine treats as intolerable.

Web Almanac 2024: shadow DOM on 2.51% of mobile pages (0.39% in 2022, a 6x rise in two
years); custom elements on 7.9%. Readability, trafilatura and Resiliparse do not handle it.

Two halves, tested separately:

1. The browser walks into open roots when stamping and measuring, and serialises them as
   `<template shadowrootmode="open">` via `getHTML()`.
2. `flatten_shadow_roots` unwraps those templates before anything strips `<template>` --
   without which the content would be discarded again, one step later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from webgraph.dom.blocks import flatten_shadow_roots, parse_html
from webgraph.fetch.render import (
    PLAYWRIGHT_AVAILABLE,
    RenderConfig,
    geometry_by_xpath,
    render_page,
)
from webgraph.pipeline import build_document

_PAGE = """<!doctype html><html><head><title>Shadow</title></head><body>
<p>LIGHT DOM PARAGRAPH</p>
<div id="host"></div>
<template id="inert"><p>INERT TEMPLATE never rendered by the page</p></template>
<script>
  const root = document.getElementById('host').attachShadow({mode: 'open'});
  const h = document.createElement('h2'); h.textContent = 'SHADOW HEADING';
  const p = document.createElement('p');
  p.textContent = 'SHADOW BODY TEXT that only exists inside the shadow root.';
  root.append(h, p);
</script>
</body></html>"""


class TestFlattening:
    """The parser half. Runs with no browser."""

    def test_a_serialised_shadow_root_is_unwrapped(self) -> None:
        html = (
            "<html><body><div id='host'>"
            '<template shadowrootmode="open"><h2>Inside</h2><p>Shadow body</p></template>'
            "</div></body></html>"
        )
        root = parse_html(html)
        assert "Inside" in root.text_content()
        assert not root.xpath("//template")

    def test_an_inert_template_is_left_alone(self) -> None:
        """A `<template>` without `shadowrootmode` is markup the page has *not* rendered.

        Flattening it would invent content -- the opposite failure to losing shadow content,
        and no more acceptable.
        """
        html = "<html><body><template><p>Not rendered</p></template></body></html>"
        root = parse_html(html)
        assert root.xpath("//template")

    def test_nested_shadow_roots_are_unwrapped(self) -> None:
        html = (
            "<html><body><div>"
            '<template shadowrootmode="open"><section><div>'
            '<template shadowrootmode="open"><p>Deep</p></template>'
            "</div></section></template>"
            "</div></body></html>"
        )
        root = parse_html(html)
        assert "Deep" in root.text_content()
        assert not root.xpath("//template")

    def test_the_count_is_returned(self) -> None:
        html = (
            "<html><body>"
            '<div><template shadowrootmode="open"><p>a</p></template></div>'
            '<div><template shadowrootmode="open"><p>b</p></template></div>'
            "<div><template><p>c</p></template></div>"
            "</body></html>"
        )
        # `parse_html` has already flattened, so re-parse without it to count.
        from lxml import html as lxml_html

        root = lxml_html.document_fromstring(html)
        assert flatten_shadow_roots(root) == 2

    def test_text_following_a_shadow_root_survives(self) -> None:
        html = (
            "<html><body><div>"
            '<template shadowrootmode="open"><p>Shadow</p></template>'
            "Tail text after the host"
            "</div></body></html>"
        )
        root = parse_html(html)
        content = root.text_content()
        assert "Shadow" in content
        assert "Tail text" in content


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="needs the 'render' extra")
class TestPiercing:
    """The browser half, end to end."""

    @pytest.fixture
    def page(self, tmp_path: Path) -> str:
        target = tmp_path / "shadow.html"
        target.write_text(_PAGE, encoding="utf-8")
        return target.as_uri()

    def test_shadow_content_is_extracted(self, page: str) -> None:
        result = render_page(page, config=RenderConfig(settle_ms=300, dismiss_gates=False))
        assert result.ok
        assert result.shadow_roots == 1
        document = build_document(result.html, page)
        text = document.text
        assert "SHADOW HEADING" in text
        assert "SHADOW BODY TEXT" in text

    def test_shadow_blocks_carry_geometry(self, page: str) -> None:
        """Not merely present -- positioned. Without a rectangle a block cannot take part in
        reading order, which is most of the point of recovering it."""
        result = render_page(page, config=RenderConfig(settle_ms=300, dismiss_gates=False))
        geometry = geometry_by_xpath(result.html, result.rects)
        document = build_document(result.html, page, geometry=geometry)
        shadow = [b for b in document.blocks if "SHADOW" in b.text]
        assert shadow
        assert all(b.rect is not None for b in shadow)

    def test_light_dom_is_not_duplicated(self, page: str) -> None:
        result = render_page(page, config=RenderConfig(settle_ms=300, dismiss_gates=False))
        document = build_document(result.html, page)
        assert sum(1 for b in document.blocks if "LIGHT DOM" in b.text) == 1

    def test_an_unrendered_template_stays_out(self, page: str) -> None:
        result = render_page(page, config=RenderConfig(settle_ms=300, dismiss_gates=False))
        document = build_document(result.html, page)
        assert "INERT TEMPLATE" not in document.text

    def test_a_page_without_shadow_roots_is_unaffected(self, tmp_path: Path) -> None:
        target = tmp_path / "plain.html"
        target.write_text(
            "<!doctype html><html><body><h1>Title</h1><p>Body</p></body></html>",
            encoding="utf-8",
        )
        result = render_page(
            target.as_uri(), config=RenderConfig(settle_ms=200, dismiss_gates=False)
        )
        assert result.ok
        assert result.shadow_roots == 0
        assert "Title" in build_document(result.html, target.as_uri()).text
