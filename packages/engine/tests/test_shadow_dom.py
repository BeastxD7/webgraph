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
from webgraph.types import BlockKind

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

    def test_text_following_the_host_survives(self) -> None:
        html = (
            "<html><body><div>"
            '<template shadowrootmode="open"><p>Shadow</p></template>'
            "</div>Tail text after the host</body></html>"
        )
        root = parse_html(html)
        content = root.text_content()
        assert "Shadow" in content
        assert "Tail text" in content

    def test_light_text_of_a_slotless_host_is_not_rendered(self) -> None:
        """Text inside the host beside its shadow root is a light-DOM text node; with no
        `<slot>` to take it the browser paints the shadow tree alone. An earlier version
        kept it ("text following a shadow root survives"), which read a component's no-JS
        fallback as page text."""
        html = (
            "<html><body><div>"
            '<template shadowrootmode="open"><p>Shadow</p></template>'
            "Light text nobody sees"
            "</div></body></html>"
        )
        assert parse_html(html).text_content().strip() == "Shadow"


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


CARD = (
    "<html><body><main>"
    '<my-card><template shadowrootmode="open">'
    '<div class="card"><h2><slot name="title">Untitled card</slot></h2>'
    "<p>Shadow intro paragraph shown above the body.</p>"
    '<div class="body"><slot>Nothing was slotted here.</slot></div>'
    '<footer><slot name="footer"></slot></footer></div>'
    "</template>"
    '<span slot="title">Quarterly results</span>'
    "<p>Revenue grew twelve percent on the back of strong demand.</p>"
    "<p>Costs were flat, so margins expanded.</p>"
    '<span slot="footer">Published 14 Sep</span>'
    '<p slot="nowhere">This light child is assigned to no slot and never renders.</p>'
    "</my-card>"
    "<p>After the component, the page goes on with a closing paragraph.</p>"
    "</main></body></html>"
)


class TestSlotComposition:
    """A shadow root's `<slot>`s are where the host's own children are painted.

    Unwrapping the serialised shadow root and leaving the light DOM behind it read the
    component the way no browser shows it: the slots' *fallback* text ("Untitled card",
    "Nothing was slotted here") came out although the browser had replaced it -- invented
    text, the worst failure the whole-page output can have -- the slotted children landed
    after the entire shadow tree instead of at their slot, a title slotted into an `<h2>`
    stopped being a heading, and a light child assigned to no slot, which the browser never
    renders, was read as a paragraph. The flat tree is composed the way the browser
    composes it: each slot is replaced by what is assigned to it, or by its fallback when
    nothing is; the unassigned rest is dropped.
    """

    def test_slotted_children_replace_their_slots_in_place(self) -> None:
        document = build_document(CARD, "https://x.test/")
        texts = [b.text for b in document.blocks]
        assert texts == [
            "Quarterly results",
            "Shadow intro paragraph shown above the body.",
            "Revenue grew twelve percent on the back of strong demand.",
            "Costs were flat, so margins expanded.",
            "Published 14 Sep",
            "After the component, the page goes on with a closing paragraph.",
        ]

    def test_a_filled_slots_fallback_is_never_shown(self) -> None:
        text = build_document(CARD, "https://x.test/").text
        assert "Untitled card" not in text
        assert "Nothing was slotted here" not in text

    def test_slotted_content_takes_the_slots_structure(self) -> None:
        """`<h2><slot name="title">` with a span slotted in is a heading in the browser."""
        document = build_document(CARD, "https://x.test/")
        title = next(b for b in document.blocks if b.text == "Quarterly results")
        assert title.kind is BlockKind.HEADING

    def test_a_child_assigned_to_no_slot_is_not_rendered(self) -> None:
        assert "never renders" not in build_document(CARD, "https://x.test/").text

    def test_an_empty_slot_shows_its_fallback(self) -> None:
        html = (
            '<html><body><x-note><template shadowrootmode="open">'
            "<p><slot>No note was given for this entry.</slot></p></template></x-note>"
            "</body></html>"
        )
        assert build_document(html, "https://x.test/").text == "No note was given for this entry."

    def test_light_text_goes_to_the_default_slot(self) -> None:
        html = (
            '<html><body><x-badge><template shadowrootmode="open">'
            "<b>Status: </b><slot>unknown</slot></template>Shipped on time</x-badge></body></html>"
        )
        text = build_document(html, "https://x.test/").text
        assert "Shipped on time" in text and "unknown" not in text

    def test_only_the_first_slot_of_a_name_is_filled(self) -> None:
        """Per the spec, a second slot with the same name gets nothing -- and shows its fallback."""
        html = (
            '<html><body><x-two><template shadowrootmode="open">'
            '<p><slot name="a">first fallback</slot></p><p><slot name="a">second fallback</slot></p>'
            '</template><span slot="a">Assigned once</span></x-two></body></html>'
        )
        text = build_document(html, "https://x.test/").text
        assert text.count("Assigned once") == 1
        assert "first fallback" not in text and "second fallback" in text

    def test_a_host_without_slots_keeps_nothing_of_the_light_dom(self) -> None:
        """No slot means the browser paints the shadow tree alone; the host's children are
        markup nobody sees. Before this the light DOM was kept behind the shadow content."""
        html = (
            '<html><body><x-only><template shadowrootmode="open"><p>Shadow only</p></template>'
            "<p>Light child that the browser does not render</p></x-only></body></html>"
        )
        assert build_document(html, "https://x.test/").text == "Shadow only"

    def test_nested_components_compose_inside_out(self) -> None:
        html = (
            '<html><body><x-outer><template shadowrootmode="open">'
            '<x-inner><template shadowrootmode="open"><h3><slot>inner fallback</slot></h3></template>'
            '<slot name="heading">outer fallback</slot></x-inner>'
            "<p>Outer shadow paragraph.</p></template>"
            '<span slot="heading">Composed heading</span></x-outer></body></html>'
        )
        document = build_document(html, "https://x.test/")
        assert [b.text for b in document.blocks] == ["Composed heading", "Outer shadow paragraph."]
        assert document.blocks[0].kind is BlockKind.HEADING


_SLOT_PAGE = """<!doctype html><html><head><title>Slots</title></head><body>
<p>LIGHT PARAGRAPH before the component.</p>
<x-card><span slot="title">SLOTTED TITLE</span><p>SLOTTED BODY that came from the light DOM.</p></x-card>
<script>
  const root = document.querySelector('x-card').attachShadow({mode: 'open'});
  root.innerHTML = '<h2><slot name="title">FALLBACK TITLE</slot></h2><div><slot>FALLBACK BODY</slot></div><p>SHADOW FOOTER</p>';
</script>
</body></html>"""


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="needs the 'render' extra")
class TestSlotsEndToEnd:
    def test_the_browser_serialisation_composes_the_same_way(self, tmp_path: Path) -> None:
        target = tmp_path / "slots.html"
        target.write_text(_SLOT_PAGE, encoding="utf-8")
        result = render_page(target.as_uri(), config=RenderConfig(settle_ms=300, dismiss_gates=False))
        assert result.ok and result.shadow_roots == 1
        document = build_document(result.html, target.as_uri())
        texts = [b.text for b in document.blocks]
        assert texts == [
            "LIGHT PARAGRAPH before the component.",
            "SLOTTED TITLE",
            "SLOTTED BODY that came from the light DOM.",
            "SHADOW FOOTER",
        ]
        assert "FALLBACK" not in document.text


_OFFSCREEN_PAGE = """<!doctype html><html><head><title>Offscreen</title></head><body>
<div style="position: absolute; left: -20914565266523px; top: 0px;"><a href="https://x.test/">SPAM LINK ONE</a></div>
<div style="position: absolute; top: -9999px;"><a href="https://x.test/">SPAM LINK TWO</a></div>
<h1>REAL HEADING</h1>
<p style="position: relative; left: -20px;">NUDGED PARAGRAPH that is still on the page.</p>
<p>REAL BODY TEXT of the page.</p>
</body></html>"""


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="needs the 'render' extra")
class TestOffscreenEndToEnd:
    """The renderer marks a box lying entirely off the page as `offscreen`, and the
    document built from its HTML has no trace of it -- while a nudged box stays."""

    def test_offscreen_text_is_not_on_the_page(self, tmp_path: Path) -> None:
        target = tmp_path / "offscreen.html"
        target.write_text(_OFFSCREEN_PAGE, encoding="utf-8")
        result = render_page(target.as_uri(), config=RenderConfig(settle_ms=300, dismiss_gates=False))
        assert result.ok
        assert result.html.count('data-wg-hidden="offscreen"') >= 2  # the div and its anchor, twice
        document = build_document(result.html, target.as_uri())
        assert [b.text for b in document.blocks] == [
            "REAL HEADING",
            "NUDGED PARAGRAPH that is still on the page.",
            "REAL BODY TEXT of the page.",
        ]
