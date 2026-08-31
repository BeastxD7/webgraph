"""End-to-end reading-order tests against a real browser.

Synthetic geometry proves the algorithm; these prove the *chain* -- that Chromium's
measurements survive marker stamping, HTML serialisation, lxml parsing, and XPath rekeying
without losing the correspondence between element and rectangle.

Every fixture is a layout where DOM order and visual order genuinely disagree, so a
regression to a plain tree walk fails here loudly.

Marked `render`; deselect with `-m 'not render'` where no browser is available.
"""

from __future__ import annotations

import pathlib

import pytest

from webgraph.fetch.render import (
    PLAYWRIGHT_AVAILABLE,
    RenderConfig,
    geometry_by_xpath,
    render_page,
)
from webgraph.pipeline import build_document
from webgraph.types import Document, ReadingOrderMethod

pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="playwright not installed"),
]

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CONFIG = RenderConfig(wait_until="load", settle_ms=150)


def render_fixture(name: str) -> tuple[Document, Document]:
    """Return (geometric document, DOM-order document) for the same fixture."""
    url = (FIXTURES / f"{name}.html").resolve().as_uri()
    result = render_page(url, config=CONFIG)
    assert result.ok, f"render failed: {result.error}"
    assert result.rects, "browser returned no geometry"

    geometry = geometry_by_xpath(result.html, result.rects)
    assert geometry, "marker ids did not rekey to XPaths"

    return (
        build_document(result.html, url, geometry=geometry),
        build_document(result.html, url),
    )


def firsts(document: Document) -> list[str]:
    return [b.text.split()[0] for b in document.blocks if b.text.strip()]


class TestFlexOrderReversal:
    """`order:` on flex children detaches visual sequence from source sequence."""

    def test_visual_order_recovered(self) -> None:
        geometric, dom = render_fixture("flex_order")
        assert firsts(geometric) == ["ALPHA", "BETA", "GAMMA"]
        assert firsts(dom) == ["GAMMA", "ALPHA", "BETA"], "fixture no longer discriminates"
        assert geometric.reading_order_method is ReadingOrderMethod.GEOMETRIC_XY_CUT
        assert geometric.dom_order_differs is True


class TestRowReverseColumns:
    """`flex-direction: row-reverse` puts the right-hand column first in source."""

    def test_header_columns_footer(self) -> None:
        geometric, dom = render_fixture("two_column")
        assert firsts(geometric) == [
            "HEADER", "LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT", "FOOTER",
        ]
        assert firsts(dom)[1] == "RIGHT", "fixture no longer discriminates"

    def test_spanning_elements_bracket_the_columns(self) -> None:
        geometric, _ = render_fixture("two_column")
        order = firsts(geometric)
        assert order[0] == "HEADER"
        assert order[-1] == "FOOTER"


class TestGridPlacement:
    """Explicit `grid-column` / `grid-row` placement reorders relative to source."""

    def test_reads_rows_left_to_right(self) -> None:
        geometric, dom = render_fixture("grid_placement")
        assert firsts(geometric) == ["A1", "B1", "A2", "B2"]
        assert firsts(dom) == ["B1", "A1", "B2", "A2"], "fixture no longer discriminates"


class TestCssMultiColumn:
    """`column-count` flows text into columns; source order already matches reading order.

    The value of this case is that geometry must *not* make it worse -- a column-aware
    algorithm that interleaved here would be actively harmful.
    """

    def test_columns_read_down_then_across(self) -> None:
        geometric, dom = render_fixture("css_columns")
        assert firsts(geometric) == ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX"]
        assert firsts(geometric) == firsts(dom)


class TestGeometryPlumbing:
    def test_marker_attributes_rekey_to_xpaths(self) -> None:
        url = (FIXTURES / "two_column.html").resolve().as_uri()
        result = render_page(url, config=CONFIG)
        geometry = geometry_by_xpath(result.html, result.rects)
        assert all(path.startswith("/html") for path in geometry)

    def test_every_block_receives_geometry(self) -> None:
        geometric, _ = render_fixture("two_column")
        assert all(b.rect is not None for b in geometric.blocks)

    def test_hidden_elements_are_not_measured(self) -> None:
        """display:none elements have no box and must be excluded, not measured as zero-area."""
        url = (FIXTURES / "flex_order.html").resolve().as_uri()
        result = render_page(url, config=CONFIG)
        assert all(r.width > 0 and r.height > 0 for r in result.rects.values())


class TestRenderFailure:
    def test_unreachable_url_degrades_gracefully(self) -> None:
        result = render_page("http://127.0.0.1:9/nothing", config=RenderConfig(timeout_ms=3000))
        assert result.ok is False
        assert result.error
