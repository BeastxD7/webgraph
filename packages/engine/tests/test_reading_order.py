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
        # Unique per block: `dom_index or 1` gave blocks 0 and 1 the same path, and two
        # blocks sharing a path read as one repeated container.
        xpath=f"/html/body/p[{(dom_index or 0) + 1}]",
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
            Block(text=f"u{i}", tag="p", xpath=f"/p[{i + 2}]", dom_index=i + 1) for i in range(5)
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
        blocks = [
            block(f"b{i}", (i % 3) * 250.0, (i // 3) * 40.0, w=200, dom_index=i)
            for i in range(count)
        ]
        ordered, _ = order_blocks(blocks)
        assert sorted(b.dom_index for b in ordered) == sorted(b.dom_index for b in blocks)


class TestRowBanding:
    """Sub-pixel `y` differences must not override left-to-right order.

    Found by `benchmark/reading_order`. supabase.com renders its top navigation with
    `Pricing` at y=70.4 and `Product` at y=71.0 -- six tenths of a pixel apart, on the same
    visual row -- and a plain `(y, x)` sort therefore read the bar as
    `Pricing, Docs, Blog, Product, Developers`. Hebrew Wikipedia's menu row failed the same
    way. Any horizontal nav or row of cards with fractional offsets was affected.
    """

    @staticmethod
    def _row(texts_and_x: list[tuple[str, float, float]]) -> list[Block]:
        """Blocks on one visual row, each with its own slightly different `y`."""
        return [
            Block(
                text=text,
                tag="a",
                xpath=f"/html/body/nav/a[{i + 1}]",
                dom_index=i,
                rect=Rect(x=x, y=y, width=60.0, height=34.0),
            )
            for i, (text, x, y) in enumerate(texts_and_x)
        ]

    def test_a_nav_bar_reads_left_to_right_despite_subpixel_offsets(self) -> None:
        blocks = self._row(
            [
                ("Product", 332.0, 71.0),
                ("Developers", 421.7, 71.0),
                ("Pricing", 635.2, 70.4),
                ("Docs", 701.0, 70.4),
            ]
        )
        ordered, _ = order_blocks(list(reversed(blocks)))
        assert [b.text for b in ordered] == ["Product", "Developers", "Pricing", "Docs"]

    def test_the_same_bar_reads_right_to_left_when_rtl(self) -> None:
        blocks = self._row(
            [("first", 600.0, 20.0), ("second", 400.0, 20.4), ("third", 200.0, 20.0)]
        )
        ordered, _ = order_blocks(list(blocks), rtl=True)
        assert [b.text for b in ordered] == ["first", "second", "third"]

    def test_a_tall_block_does_not_swallow_the_rows_beside_it(self) -> None:
        """The regression that decided the banding criterion.

        A 400px sidebar must not band with short blocks that merely fall inside its extent,
        or they get ordered by x and lose their vertical relationship. Overlap is therefore
        measured against the taller block, not the shorter.
        """
        sidebar = Block(
            text="sidebar",
            tag="nav",
            xpath="/html/body/nav",
            dom_index=0,
            rect=Rect(x=900.0, y=0.0, width=200.0, height=400.0),
        )
        upper = Block(
            text="upper",
            tag="p",
            xpath="/html/body/p[1]",
            dom_index=1,
            rect=Rect(x=100.0, y=50.0, width=500.0, height=30.0),
        )
        lower = Block(
            text="lower",
            tag="p",
            xpath="/html/body/p[2]",
            dom_index=2,
            rect=Rect(x=100.0, y=300.0, width=500.0, height=30.0),
        )
        ordered, _ = order_blocks([sidebar, lower, upper])
        text = [b.text for b in ordered]
        assert text.index("upper") < text.index("lower")


class TestBridgedColumns:
    """A region no clean cut can split: a sidebar with no vertical gaps bridges every row,
    and a wide banner across the top bridges every column. Measured on MDN, the sidebar's
    links and the right-hand table of contents came out zipped together, one line each in
    turn, because position order was all that was left."""

    @staticmethod
    def page() -> list[Block]:
        blocks = [block("banner", 0, 0, w=1000, h=30, dom_index=0)]
        # Left sidebar: a dense list, 30px apart with 24px items -- no row gap anywhere.
        for i in range(12):
            blocks.append(block(f"side{i}", 0, 50 + i * 30, w=200, h=24, dom_index=1 + i))
        # Right column: a table of contents at the same vertical positions.
        for i in range(12):
            blocks.append(block(f"toc{i}", 700, 50 + i * 30, w=200, h=24, dom_index=13 + i))
        blocks.append(block("footer", 0, 420, w=1000, h=30, dom_index=25))
        return blocks

    def test_columns_are_read_whole_not_zipped(self) -> None:
        ordered, method = order_blocks(self.page())
        names = texts(ordered)
        assert method is ReadingOrderMethod.GEOMETRIC_XY_CUT
        side = [n for n in names if n.startswith("side")]
        toc = [n for n in names if n.startswith("toc")]
        assert side == [f"side{i}" for i in range(12)]
        assert toc == [f"toc{i}" for i in range(12)]
        # No interleaving: every sidebar item precedes every toc item.
        assert names.index("side11") < names.index("toc0")

    def test_a_banner_comes_first_and_a_footer_last(self) -> None:
        """A wide block across the columns is read where it sits, not first because it is
        wide. Reading a footer before the columns above it measured as a loss on every
        stacked pair on the page."""
        names = texts(order_blocks(self.page())[0])
        assert names[0] == "banner"
        assert names[-1] == "footer"

    def test_too_many_straddlers_means_it_is_one_thing(self) -> None:
        """Half the blocks crossing the line is a single column of mixed widths, not two."""
        blocks = []
        for i in range(10):
            width = 1000 if i % 2 else 300
            blocks.append(block(f"p{i}", 0, i * 40, w=width, h=24, dom_index=i))
            blocks.append(block(f"r{i}", 700, i * 40, w=200, h=24, dom_index=100 + i))
        names = texts(order_blocks(blocks)[0])
        # Position order: each row's left then right, top to bottom.
        assert names[:4] == ["p0", "r0", "p1", "r1"]


class TestGutterRail:
    """docs.python.org: a 12px-wide, 900px-tall sidebar handle standing in the 36px gutter
    between the sidebar and the article. Measured, it splits the gutter into two gaps too
    narrow to cut and bridges every row; the sidebar was then zipped with the article."""

    @staticmethod
    def page() -> list[Block]:
        blocks = []
        # Sidebar: short items, no vertical gaps. Article: two-line paragraphs, so the
        # median block height is 51 -- larger than the gutter.
        for i in range(6):
            blocks.append(block(f"side{i}", 26, 100 + i * 30, w=323, h=24, dom_index=i))
        blocks.append(block("rail", 354, 100, w=12, h=900, dom_index=6))
        for i in range(10):
            blocks.append(block(f"para{i}", 385, 100 + i * 60, w=800, h=51, dom_index=7 + i))
        return blocks

    def test_sidebar_then_article(self) -> None:
        ordered, method = order_blocks(self.page())
        names = texts(ordered)
        assert method is ReadingOrderMethod.GEOMETRIC_ANCHORED, "the rail is anchored, not measured"
        assert names[:6] == [f"side{i}" for i in range(6)]
        assert names[-10:] == [f"para{i}" for i in range(10)]

    def test_line_unit_is_the_one_liners(self) -> None:
        from webgraph.dom.reading_order import _line_unit

        assert _line_unit([]) == 16.0
        assert _line_unit([24.0] * 6 + [51.0] * 10) == 24.0
        assert _line_unit([17.0, 17.0, 17.0, 17.0]) == 17.0


class TestFloats:
    """en.wikipedia "Computer": a right-floated gallery -- five images and a caption list --
    beside the lead paragraphs. Geometry alone dealt its pieces out between the paragraphs;
    the renderer's float mark says they are one thing."""

    @staticmethod
    def page() -> list[Block]:
        blocks = []
        for i in range(4):
            blocks.append(block(f"para{i}", 0, 100 + i * 120, w=900, h=100, dom_index=i))
        for j in range(3):
            b = block(f"gallery{j}", 650, 110 + j * 130, w=240, h=110, dom_index=4 + j)
            blocks.append(b.model_copy(update={"float_of": "/html/body/div[9]"}))
        return blocks

    def test_float_members_stay_together(self) -> None:
        ordered, _ = order_blocks(self.page())
        names = texts(ordered)
        where = [names.index(f"gallery{j}") for j in range(3)]
        assert where == list(range(where[0], where[0] + 3)), names
        paras = [n for n in names if n.startswith("para")]
        assert paras == [f"para{i}" for i in range(4)]


class TestNestedCards:
    """allbirds.com's product page is a column of Shopify `section[*]`s -- each a card --
    and its details section holds three `li[*]` slides side by side: picture, heading,
    paragraph, with 10px between the columns and 25px between the rows. Cut by geometry
    inside the section card, it read as three headings and then three paragraphs."""

    SLIDES = (
        ("THE DETAILS", "A true original."),
        ("MATERIALLY BETTER", "Merino wool."),
        ("WASH & CARE", "Machine approved."),
    )

    @staticmethod
    def card(path: str, text: str, x: float, y: float, w: float, h: float, i: int) -> Block:
        rect = Rect(x=x, y=y, width=w, height=h)
        return Block(text=text, tag="p", xpath=path, dom_index=i, rect=rect)

    def page(self, *, sections: int = 4) -> list[Block]:
        blocks: list[Block] = []
        # Enough sections, each small, for `section[*]` to be a card on the page.
        for s in range(1, sections + 1):
            stem = f"/html/body/main/section[{s}]"
            if s != 2:
                y = 100 + s * 600
                blocks.append(self.card(f"{stem}/h2", f"Section {s}", 34, y, 900, 20, 0))
                blocks.append(self.card(f"{stem}/p", f"Text {s}.", 34, y + 40, 900, 60, 0))
                continue
            for n, (head, body) in enumerate(self.SLIDES, start=1):
                x = 34 + (n - 1) * 461
                slide = f"{stem}/div/ul/li[{n}]"
                blocks.append(self.card(f"{slide}/img", f"img{n}", x, 1169, 451, 451, 0))
                blocks.append(self.card(f"{slide}/h3", head, x, 1645, 451, 16, 0))
                blocks.append(self.card(f"{slide}/p", body, x, 1675, 419, 44, 0))
        return [b.model_copy(update={"dom_index": i}) for i, b in enumerate(blocks)]

    def test_slides_in_a_row_are_read_one_at_a_time(self) -> None:
        ordered, method = order_blocks(self.page())
        assert method is ReadingOrderMethod.GEOMETRIC_XY_CUT
        wanted = [text for pair in self.SLIDES for text in pair]
        assert [n for n in texts(ordered) if n in wanted] == wanted

    def test_slides_that_overlap_are_not_a_row(self) -> None:
        """supabase.com's customer stories: five 560px cards offset by 84px, drawn over one
        another. Not a row -- geometry reads the row of logos before any story, as the
        page shows -- and a column of stacked cards is not one either."""
        from webgraph.dom.reading_order import _card_rows

        def cards(xs: list[float], ys: list[float]) -> dict[str, list[Block]]:
            return {
                f"/html/body/div/div[{n}]": [
                    self.card(f"/html/body/div/div[{n}]/h3", "h", x, y, 560, 20, n),
                    self.card(f"/html/body/div/div[{n}]/p", "p", x, y + 30, 560, 40, n),
                ]
                for n, (x, y) in enumerate(zip(xs, ys, strict=True), start=1)
            }

        fanned = cards([958, 1042, 1126, 1210], [4450] * 4)
        stacked = cards([34] * 4, [100, 200, 300, 400])
        row = cards([34, 600, 1166, 1732], [100] * 4)
        assert _card_rows(fanned, unit=16) == ({}, set(fanned))
        assert _card_rows(stacked, unit=16) == ({}, set(stacked))
        rows, loose = _card_rows(row, unit=16)
        assert loose == set()
        assert rows == {"/html/body/div/div[*]": list(row)}
