"""Reading direction, and the production path that never asked for it.

`order_blocks` has always reversed column order for `rtl`, and `build_document` has always
accepted the flag. Nothing in between ever set it: `resolve_page` -- the path the API, the
crawler and every benchmark use -- called `build_document` without it, so the parameter
defaulted to False and every Arabic, Hebrew and Persian page was ordered left to right.

That is the engine's least tolerable failure mode. A multi-column RTL page does not come out
slightly worse; it comes out with the columns in the wrong order, labelled `geometric-xy-cut`
as though it had been measured.

Measured on the benchmark corpus once detection was wired up: 5 of 41 pages are RTL, and
`ynet.co.il` -- which carries no `dir` attribute anywhere and is RTL only through CSS and its
`lang="he"` -- moves 3,813 of its 3,924 blocks.
"""

from __future__ import annotations

import pytest
from lxml.html import HtmlElement

from webgraph.dom.blocks import is_rtl_document, parse_html
from webgraph.dom.reading_order import order_blocks
from webgraph.pipeline import build_document
from webgraph.types import Block, ReadingOrderMethod, Rect


def tree(markup: str) -> HtmlElement:
    return parse_html(markup)


class TestDetection:
    @pytest.mark.parametrize(
        "markup",
        [
            '<html dir="rtl"><body><p>x</p></body></html>',
            '<html DIR="RTL"><body><p>x</p></body></html>',
            '<html><body dir="rtl"><p>x</p></body></html>',
            '<html lang="ar"><body><p>x</p></body></html>',
            '<html lang="he-IL"><body><p>x</p></body></html>',
            '<html lang="fa"><body><p>x</p></body></html>',
            '<html lang="ur-PK"><body><p>x</p></body></html>',
            '<html lang="iw"><body><p>x</p></body></html>',
            '<html lang="az-Arab"><body><p>x</p></body></html>',
            '<html lang="pa-Arab-PK"><body><p>x</p></body></html>',
        ],
    )
    def test_right_to_left(self, markup: str) -> None:
        assert is_rtl_document(tree(markup)) is True

    @pytest.mark.parametrize(
        "markup",
        [
            "<html><body><p>x</p></body></html>",
            '<html lang="en"><body><p>x</p></body></html>',
            '<html lang="ja"><body><p>x</p></body></html>',
            '<html lang="fr-FR"><body><p>x</p></body></html>',
            '<html dir="ltr"><body><p>x</p></body></html>',
            '<html dir="auto"><body><p>x</p></body></html>',
            # Latin-script Azerbaijani and Punjabi are left-to-right; only the Arabic
            # script subtag flips them.
            '<html lang="az-Latn"><body><p>x</p></body></html>',
            '<html lang="pa-Guru"><body><p>x</p></body></html>',
        ],
    )
    def test_left_to_right(self, markup: str) -> None:
        assert is_rtl_document(tree(markup)) is False

    def test_explicit_direction_beats_language(self) -> None:
        """A Hebrew-language page that declares `ltr` means it.

        Sites presenting code or tabular data do this deliberately, and the author's
        declaration is better evidence than the language tag.
        """
        markup = '<html lang="he" dir="ltr"><body><p>x</p></body></html>'
        assert is_rtl_document(tree(markup)) is False

    def test_quoting_another_language_does_not_flip_the_page(self) -> None:
        """No character-frequency heuristic, on purpose.

        An English page quoting Arabic -- a dictionary, a news article, this suite's own
        fixtures -- must not have its reading order reversed.
        """
        markup = (
            '<html lang="en"><body><h1>On Arabic typography</h1>'
            "<p>The word is written حاسوب and reads right to left.</p>"
            "<p>مرحبا بالعالم</p></body></html>"
        )
        assert is_rtl_document(tree(markup)) is False


class TestBuildDocumentDetects:
    """The wiring. `rtl=None` means detect; an explicit bool still overrides."""

    _COLUMNS = """
    <html {attrs}><body>
      <div><p>alpha one</p><p>alpha two</p></div>
      <div><p>beta one</p><p>beta two</p></div>
    </body></html>
    """

    def test_detection_runs_without_an_explicit_flag(self) -> None:
        """`rtl` is no longer required at the call site.

        Without geometry the order is DOM order either way, so this asserts the plumbing --
        that detection happens and the document builds -- not the column flip, which is
        covered below where there are rectangles to flip.
        """
        document = build_document(
            self._COLUMNS.format(attrs='lang="ar"'), "http://example.test/"
        )
        assert next(b.text for b in document.blocks) == "alpha one"

    def test_explicit_false_overrides_detection(self) -> None:
        document = build_document(
            self._COLUMNS.format(attrs='dir="rtl"'), "http://example.test/", rtl=False
        )
        assert document.reading_order_method is ReadingOrderMethod.DOM_FALLBACK


class TestColumnOrderActuallyFlips:
    """The reason any of this matters: geometry plus `rtl` reverses the columns."""

    def test_rtl_reads_the_right_column_first(self) -> None:
        def block(text: str, index: int, x: float) -> Block:
            return Block(
                text=text,
                tag="p",
                xpath=f"/html/body/div/p[{index + 1}]",
                dom_index=index,
                rect=Rect(x=x, y=10.0 + 30 * (index % 2), width=180.0, height=20.0),
            )

        left = [block("left one", 0, 0.0), block("left two", 1, 0.0)]
        right = [block("right one", 2, 400.0), block("right two", 3, 400.0)]
        blocks = left + right

        ltr, _ = order_blocks(list(blocks), rtl=False)
        rtl, _ = order_blocks(list(blocks), rtl=True)

        assert ltr[0].text.startswith("left")
        assert rtl[0].text.startswith("right")
        # Same blocks, opposite column order -- nothing is lost, only resequenced.
        assert {b.text for b in ltr} == {b.text for b in rtl}
