"""Reading-order recovery tests.

These use synthetic geometry rather than real pages so that each layout pathology is
isolated. The cases that matter are the ones where DOM order and visual order disagree --
a test suite that only exercises well-behaved single-column pages would pass with a
plain DOM walk and prove nothing.
"""

from __future__ import annotations

import pytest

from webgraph.dom.reading_order import OrderingConfig, detect_columns, order_blocks
from webgraph.types import Block, ReadingOrderMethod, Rect


def block(
    text: str,
    x: float,
    y: float,
    w: float = 200,
    h: float = 20,
    dom_index: int | None = None,
) -> Block:
    return Block(
        text=text,
        tag="p",
        xpath=f"/html/body/p[{dom_index or 1}]",
        dom_index=dom_index if dom_index is not None else 0,
        rect=Rect(x=x, y=y, width=w, height=h),
    )


def texts(blocks: list[Block]) -> list[str]:
    return [b.text for b in blocks]


class TestSingleColumn:
    def test_orders_top_to_bottom(self) -> None:
        blocks = [
            block("third", 0, 200, dom_index=2),
            block("first", 0, 0, dom_index=0),
            block("second", 0, 100, dom_index=1),
        ]
        ordered, method = order_blocks(blocks)
        assert texts(ordered) == ["first", "second", "third"]
        assert method is ReadingOrderMethod.GEOMETRIC_XY_CUT

    def test_single_block_is_labelled(self) -> None:
        ordered, method = order_blocks([block("only", 0, 0)])
        assert texts(ordered) == ["only"]
        assert method is ReadingOrderMethod.SINGLE_BLOCK

    def test_empty_input(self) -> None:
        ordered, method = order_blocks([])
        assert ordered == []
        assert method is ReadingOrderMethod.DOM_FALLBACK


class TestTwoColumn:
    """The canonical failure: sorting by `y` interleaves columns."""

    def _layout(self) -> list[Block]:
        # Left column at x=0, right column at x=400, vertically interleaved on purpose
        # so that a naive y-sort would alternate between them.
        return [
            block("L1", 0, 0, w=300, dom_index=0),
            block("R1", 400, 10, w=300, dom_index=3),
            block("L2", 0, 40, w=300, dom_index=1),
            block("R2", 400, 50, w=300, dom_index=4),
            block("L3", 0, 80, w=300, dom_index=2),
            block("R3", 400, 90, w=300, dom_index=5),
        ]

    def test_columns_are_not_interleaved(self) -> None:
        ordered, _ = order_blocks(self._layout())
        assert texts(ordered) == ["L1", "L2", "L3", "R1", "R2", "R3"]

    def test_naive_y_sort_would_have_failed(self) -> None:
        """Guards the test itself: confirms the fixture actually discriminates."""
        naive = sorted(self._layout(), key=lambda b: b.rect.y)  # type: ignore[union-attr]
        assert texts(naive) == ["L1", "R1", "L2", "R2", "L3", "R3"]

    def test_detect_columns(self) -> None:
        assert detect_columns(self._layout()) == 2

    def test_rtl_reverses_column_order(self) -> None:
        ordered, _ = order_blocks(self._layout(), rtl=True)
        assert texts(ordered) == ["R1", "R2", "R3", "L1", "L2", "L3"]


class TestSpanningHeader:
    """A full-width header must precede the columns it sits above.

    This is why the algorithm attempts a horizontal cut before a vertical one.
    """

    def test_header_then_columns_then_footer(self) -> None:
        blocks = [
            block("HEADER", 0, 0, w=700, h=40, dom_index=0),
            block("L1", 0, 100, w=300, dom_index=1),
            block("R1", 400, 100, w=300, dom_index=3),
            block("L2", 0, 140, w=300, dom_index=2),
            block("R2", 400, 140, w=300, dom_index=4),
            block("FOOTER", 0, 300, w=700, h=40, dom_index=5),
        ]
        ordered, _ = order_blocks(blocks)
        assert texts(ordered) == ["HEADER", "L1", "L2", "R1", "R2", "FOOTER"]

    def test_three_columns(self) -> None:
        blocks = [
            block("A1", 0, 0, w=200, dom_index=0),
            block("B1", 250, 0, w=200, dom_index=1),
            block("C1", 500, 0, w=200, dom_index=2),
            block("A2", 0, 40, w=200, dom_index=3),
            block("B2", 250, 40, w=200, dom_index=4),
            block("C2", 500, 40, w=200, dom_index=5),
        ]
        ordered, _ = order_blocks(blocks)
        assert texts(ordered) == ["A1", "A2", "B1", "B2", "C1", "C2"]
        assert detect_columns(blocks) == 3


class TestCssReordering:
    """Geometry must win over DOM order when CSS has reordered content.

    This models `order:` on flex children -- the visual sequence is the reverse of source.
    """

    def test_flex_order_reversal_is_corrected(self) -> None:
        blocks = [
            block("visually third", 0, 200, dom_index=0),
            block("visually first", 0, 0, dom_index=1),
            block("visually second", 0, 100, dom_index=2),
        ]
        ordered, method = order_blocks(blocks)
        assert texts(ordered) == ["visually first", "visually second", "visually third"]
        assert method is ReadingOrderMethod.GEOMETRIC_XY_CUT
        # DOM order would have produced the wrong sequence.
        assert texts(sorted(blocks, key=lambda b: b.dom_index)) != texts(ordered)

    def test_row_reverse_columns(self) -> None:
        """`flex-direction: row-reverse`: source order is right column first."""
        blocks = [
            block("R1", 400, 0, w=300, dom_index=0),
            block("R2", 400, 40, w=300, dom_index=1),
            block("L1", 0, 0, w=300, dom_index=2),
            block("L2", 0, 40, w=300, dom_index=3),
        ]
        ordered, _ = order_blocks(blocks)
        assert texts(ordered) == ["L1", "L2", "R1", "R2"]


class TestFallback:
    def test_missing_geometry_falls_back_to_dom_order(self) -> None:
        blocks = [
            Block(text="b", tag="p", xpath="/p[2]", dom_index=1),
            Block(text="a", tag="p", xpath="/p[1]", dom_index=0),
        ]
        ordered, method = order_blocks(blocks)
        assert texts(ordered) == ["a", "b"]
        assert method is ReadingOrderMethod.DOM_FALLBACK

    def test_a_few_unmeasured_blocks_do_not_discard_the_geometry(self) -> None:
        """A browser does not measure what it does not display.

        One collapsed `<details>` used to downgrade a whole page: measured across seven real
        documentation pages, every one fell back, including one where 103 of 108 blocks had
        been measured.
        """
        blocks = [
            block("first", 0, 0, dom_index=0),
            block("second", 0, 100, dom_index=1),
            block("third", 0, 200, dom_index=2),
            Block(text="collapsed", tag="p", xpath="/p[4]", dom_index=3),
        ]
        ordered, method = order_blocks(blocks)
        assert method is ReadingOrderMethod.GEOMETRIC_ANCHORED
        assert texts(ordered) == ["first", "second", "third", "collapsed"]

    def test_an_unmeasured_block_follows_its_measured_predecessor(self) -> None:
        """The body of a collapsed disclosure belongs after the control that opens it, which
        is exactly where source order puts it."""
        blocks = [
            block("intro", 0, 0, dom_index=0),
            Block(text="hidden panel", tag="p", xpath="/p[2]", dom_index=1),
            block("outro", 0, 100, dom_index=2),
        ]
        ordered, method = order_blocks(blocks)
        assert method is ReadingOrderMethod.GEOMETRIC_ANCHORED
        assert texts(ordered) == ["intro", "hidden panel", "outro"]

    def test_anchoring_respects_the_recovered_order_not_source_order(self) -> None:
        """Measured blocks are placed by geometry; unmeasured ones follow their source-order
        predecessor into that sequence.

        Here CSS shows the second element first. The collapsed block sits after "visually
        first" in the source, so that is where it lands -- *between* the two measured blocks
        in the recovered order, not at the end of it. Source order decides which measured
        block it attaches to; geometry decides where that block is.
        """
        blocks = [
            block("visually second", 0, 100, dom_index=0),
            block("visually first", 0, 0, dom_index=1),
            Block(text="collapsed", tag="p", xpath="/p[3]", dom_index=2),
        ]
        ordered, method = order_blocks(blocks)
        assert method is ReadingOrderMethod.GEOMETRIC_ANCHORED
        assert texts(ordered) == ["visually first", "collapsed", "visually second"]

    def test_an_unmeasured_block_before_anything_measured_leads(self) -> None:
        blocks = [
            Block(text="orphan", tag="p", xpath="/p[1]", dom_index=0),
            block("a", 0, 0, dom_index=1),
            block("b", 0, 100, dom_index=2),
        ]
        ordered, _ = order_blocks(blocks)
        assert texts(ordered) == ["orphan", "a", "b"]

    def test_mostly_unmeasured_still_falls_back(self) -> None:
        """Anchoring a majority of blocks to a minority of measurements would be source order
        wearing a measurement's name."""
        blocks = [block("measured", 0, 0, dom_index=0)] + [
            Block(text=f"u{i}", tag="p", xpath=f"/p[{i + 2}]", dom_index=i + 1)
            for i in range(5)
        ]
        _ordered, method = order_blocks(blocks)
        assert method is ReadingOrderMethod.DOM_FALLBACK

    def test_a_run_of_unmeasured_blocks_keeps_its_own_order(self) -> None:
        blocks = [
            block("intro", 0, 0, dom_index=0),
            Block(text="p1", tag="p", xpath="/p[2]", dom_index=1),
            Block(text="p2", tag="p", xpath="/p[3]", dom_index=2),
            block("outro", 0, 100, dom_index=3),
        ]
        ordered, _ = order_blocks(blocks)
        assert texts(ordered) == ["intro", "p1", "p2", "outro"]


class TestRobustness:
    def test_deterministic_for_identical_rects(self) -> None:
        blocks = [
            block("second", 0, 0, dom_index=1),
            block("first", 0, 0, dom_index=0),
        ]
        first_run, _ = order_blocks(blocks)
        second_run, _ = order_blocks(list(reversed(blocks)))
        assert texts(first_run) == texts(second_run) == ["first", "second"]

    def test_tight_line_spacing_is_not_a_row_cut(self) -> None:
        """Ordinary leading must not be mistaken for a section break -- it would still
        order correctly here, but excessive cutting degrades to O(n) recursion depth."""
        blocks = [block(f"line{i}", 0, i * 21.0, h=20, dom_index=i) for i in range(30)]
        ordered, _ = order_blocks(blocks)
        assert texts(ordered) == [f"line{i}" for i in range(30)]

    def test_respects_max_depth(self) -> None:
        blocks = [block(f"b{i}", 0, i * 100.0, dom_index=i) for i in range(60)]
        ordered, _ = order_blocks(blocks, config=OrderingConfig(max_depth=2))
        assert len(ordered) == 60
        assert len({b.text for b in ordered}) == 60

    @pytest.mark.parametrize("count", [0, 1, 2, 5, 50])
    def test_never_drops_or_duplicates_blocks(self, count: int) -> None:
        blocks = [block(f"b{i}", (i % 3) * 250.0, (i // 3) * 40.0, w=200, dom_index=i)
                  for i in range(count)]
        ordered, _ = order_blocks(blocks)
        assert sorted(b.dom_index for b in ordered) == sorted(b.dom_index for b in blocks)
