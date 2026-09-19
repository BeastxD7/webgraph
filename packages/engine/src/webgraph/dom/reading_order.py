"""Recover human reading order from block geometry.

The problem
-----------
Source order is not reading order. CSS reorders content freely: `order` on flex
children, `flex-direction: row-reverse`, explicit `grid-row`/`grid-column` placement,
floats, and absolute positioning all let the visual sequence diverge from the DOM.
A depth-first tree walk therefore produces *silently* wrong text on exactly the pages
where order matters most -- news, documentation, academic papers, anything multi-column.

Sorting every block by its `y` coordinate does not fix it either. On a two-column page
that interleaves the columns line by line, which is worse than DOM order, not better.

The approach
------------
Recursive XY-cut, the same family of algorithm used to recover reading order from PDFs.
At each step we look for a band of whitespace that cleanly separates the region:

  1. Measure the widest whitespace band on each axis -- horizontal gutters that split the
     region into stacked row bands, and vertical gutters that split it into columns.
  2. Cut on whichever axis has the **wider** band, at that band only, then recurse.
     Row bands are read top to bottom; columns left to right (right to left when `rtl`).
  3. If neither axis has a qualifying band, the region is atomic: sort by `y`, then `x`.

Two details carry most of the correctness:

*Wider gutter wins.* Always cutting rows first reads a grid-aligned multi-column layout
across instead of down, because the row gaps qualify too. A genuine column gutter is
wider than inter-paragraph leading, so comparing widths picks the right axis.

*Cut once, then recurse.* Cutting at every qualifying gap at once slices a
header-over-columns page into rows before the columns are ever seen. Taking the widest
band first -- the break below the header -- lets the recursion find the columns beneath it.

Fallback
--------
Static HTML has no geometry. We then return DOM order and label it `DOM_FALLBACK`, so
downstream consumers can see that the ordering was assumed rather than measured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from webgraph import config
from webgraph.types import Block, ReadingOrderMethod, Rect

__all__ = ["OrderingConfig", "detect_columns", "order_blocks"]

_EPSILON = 1e-6
_TIE_TOLERANCE = 0.95
"""Gaps within this fraction of the widest are treated as equivalent and cut together."""

_ROW_BAND_OVERLAP = 0.5
"""Share of the *taller* block's height that must overlap before it joins the current row.

Scale-free on purpose: a pixel tolerance would have to be tuned per font size, while overlap
works on a 12px sidebar and a 72px hero without a constant.

Taller rather than shorter, and the difference was measured rather than reasoned. Across
592,520 precedence assertions on 39 pages (`benchmark/reading_order`):

```
                     overall   discriminating   stacked   side-by-side
sort by (y, x)        0.9945       0.9343        1.0000       0.8346
band vs min height    0.9981       0.9403        0.9981       0.9969
band vs max height    0.9974       0.9921        1.0000       0.9219
```

The min variant scores 0.0007 higher overall -- noise -- by fixing more side-by-side pairs at
the cost of breaking stacked ones that were previously perfect. The max variant introduces
**no regression at all** and is right on 99.2% of the pairs where geometric order and source
order actually disagree, against 94.0%. Taking the conservative one is the same trade this
engine makes everywhere else: do not make a correct answer wrong in order to fix more of a
wrong one."""


@dataclass(frozen=True, slots=True)
class OrderingConfig:
    """Tuning for cut detection.

    Gap thresholds are expressed as multiples of the median block height rather than as
    absolute pixels, so the same config works on a dense sidebar and an airy landing page.
    """

    min_row_gap_ratio: float = config.ORDER_MIN_ROW_GAP_RATIO
    """A vertical whitespace band must exceed this multiple of median block height to count
    as a row separator. Below it, the gap is ordinary line spacing."""

    min_col_gap_ratio: float = config.ORDER_MIN_COL_GAP_RATIO
    """A horizontal whitespace band must exceed this multiple of median block height to
    count as a column gutter. Set higher than the row threshold because inline spacing
    between words and inline elements is common and must not be read as a column break."""

    min_absolute_gap: float = config.ORDER_MIN_ABSOLUTE_GAP
    """Floor in CSS pixels, guarding against degenerate tiny-text pages."""

    max_depth: int = config.ORDER_MAX_DEPTH
    """Recursion guard. Deeply nested cuts past this point are ordered positionally."""

    min_measured_share: float = config.ORDER_MIN_MEASURED_SHARE
    """Share of blocks that must carry geometry before it is allowed to lead the ordering.

    Set by measurement, having first been guessed at 0.5. Method: take pages the browser
    measured almost completely, treat their full-geometry order as ground truth, blind a
    share of blocks, and score the anchored result by how often a pair of blocks keeps its
    correct relative order.

    Blinding in **clustered runs**, because that is the shape of the real thing -- a
    collapsed section, or the blocks that exist only in the static half of a union fetch.
    Random blinding is a materially easier problem and overstates how well this works.

    ```
    share measured   90%   75%   60%   50%   40%   30%   20%   10%
    clustered       1.00  0.97  0.97  0.98  0.92  0.92  0.88  0.91
    random          0.99  0.99  0.98  0.98  0.97  0.96  0.96  0.94
    source order    0.89  <- what falling back produces
    ```

    Anchoring beats the fallback down to about 30% and loses below roughly 25%. The crossover
    is noisy over six pages, so the threshold sits on the conservative side of it.

    The guessed 0.5 was costing real accuracy: a union document merges static-only blocks,
    which by construction carry no rectangle, so its measured share is always lower than the
    rendered document's. Four sites in a robustness sweep -- lemonde.fr, shopify.com,
    ar.wikipedia and aljazeera -- sat between 0.34 and 0.47 and read in source order.
    """


def order_blocks(
    blocks: list[Block],
    *,
    rtl: bool = False,
    config: OrderingConfig | None = None,
) -> tuple[list[Block], ReadingOrderMethod]:
    """Return `blocks` in reading order, plus the method used to establish it.

    An earlier version abandoned geometry entirely if *any* block lacked a rectangle, on the
    grounds that mixing measured and assumed positions gives an order that is neither. The
    reasoning was right about naive mixing and wrong about the consequence: a browser does not
    measure what it does not display, so a single collapsed `<details>` was enough to
    downgrade a whole page. Measured across seven real documentation pages, **every one** fell
    back -- including one where 103 of 108 blocks had been measured.

    Unmeasured blocks are now *anchored* instead. The measured blocks are ordered
    geometrically, and each unmeasured block is placed immediately after its nearest
    preceding measured block in source order. That is the right answer for the case that
    produces them: the body of a collapsed disclosure belongs directly after the control that
    opens it, which is exactly where the DOM puts it.

    The result is labelled `GEOMETRIC_ANCHORED`, not `GEOMETRIC_XY_CUT`. It is a weaker claim
    and gets its own name.
    """
    config = config or OrderingConfig()

    if not blocks:
        return [], ReadingOrderMethod.DOM_FALLBACK
    if len(blocks) == 1:
        return list(blocks), ReadingOrderMethod.SINGLE_BLOCK

    measured = [b for b in blocks if b.rect is not None]
    if not measured:
        return sorted(blocks, key=lambda b: b.dom_index), ReadingOrderMethod.DOM_FALLBACK

    heights = [b.rect.height for b in measured if b.rect is not None and b.rect.height > 0]
    unit = _line_unit(heights)

    blocks = _demote_backdrops(_demote_rails(blocks, unit))
    measured = [b for b in blocks if b.rect is not None]

    if len(measured) == len(blocks):
        # Nothing to anchor, so neither guard applies: complete geometry is always used.
        ordered = _cut_with_cards(list(blocks), rtl=rtl, config=config, unit=unit)
        return ordered, ReadingOrderMethod.GEOMETRIC_XY_CUT

    if len(measured) < len(blocks) * config.min_measured_share:
        # Too little geometry to lead with. Anchoring most of a document to a handful of
        # measurements would dress source order up as a measurement.
        return sorted(blocks, key=lambda b: b.dom_index), ReadingOrderMethod.DOM_FALLBACK

    ordered = _cut_with_cards(list(measured), rtl=rtl, config=config, unit=unit)
    return _anchor_unmeasured(ordered, blocks), ReadingOrderMethod.GEOMETRIC_ANCHORED


_UNIT_QUANTILE: Final[float] = 0.25


def _line_unit(heights: list[float]) -> float:
    """The height of a line of text on this page, estimated from its block heights.

    The gap thresholds are multiples of this. It used to be the median block height, which
    is the height of a *typical block*, not of a line: on docs.python.org the typical block
    is a two-line paragraph 51px tall, so the column threshold came out at 51px and the
    36px gutter between the sidebar and the article was never a cut -- the sidebar's
    "Previous topic" was read between the article's first two paragraphs. The lower
    quartile of block heights is the one-liners -- headings, list items, short paragraphs
    -- whose height is the line height, on that page as on a page of short blocks where
    the two estimates agree.
    """
    if not heights:
        return 16.0
    ordered = sorted(heights)
    return ordered[min(len(ordered) - 1, int(len(ordered) * _UNIT_QUANTILE))]


_RAIL_ASPECT: Final[float] = 8.0


def _demote_rails(blocks: list[Block], unit: float) -> list[Block]:
    """Strip the measurement from a rail: a block no wider than a line and many lines tall.

    A rail is furniture standing *in* a gutter -- the "«" handle that collapses the sidebar
    on docs.python.org is 12px wide and 901px tall and sits in the 36px between the sidebar
    and the article. Left measured, it does two kinds of damage: it splits the gutter into
    two gaps too narrow to cut, so the columns are never separated, and it bridges every
    row, so no band can be cut either; the page then falls to position order and the
    sidebar's "Previous topic" is read between the article's first two paragraphs.
    Unmeasured, it is anchored where the DOM puts it -- between the two columns -- and the
    gutter is whole again.
    """
    out: list[Block] = []
    for block in blocks:
        rect = block.rect
        if rect is not None and rect.width <= unit and rect.height >= rect.width * _RAIL_ASPECT:
            block = block.model_copy(update={"rect": None})
        out.append(block)
    return out


_MIN_BACKDROP_COVER: Final[int] = 3


def _demote_backdrops(blocks: list[Block]) -> list[Block]:
    """Strip the measurement from a backdrop: a block with no text whose box holds other
    blocks.

    lakshx.in/docs/* opens with a decorative `<img>` -- no alt text -- laid over the whole
    first screen, 1440 x 900 at the page's origin, with the sidebar, the header and the
    article's first paragraphs drawn on top of it. Measured, it is one block that touches
    every gutter on that screen: no vertical band separates the sidebar from the article
    while the image spans both, so the cut falls back to position order and the sidebar's
    lower entries ("Code Graph", "Music", "Voice") are read between the article's
    paragraphs, on every page of the docs. A text block is a leaf and never holds another;
    a box that holds others is *under* them, not beside them, and has no place in the
    order of what a reader reads. Unmeasured, the image is anchored where the DOM puts it
    (the top of the page, which is also where it is) and the gutter is whole.

    Only a textless block, and only one holding at least three others: a hero image with a
    caption laid over it holds one, and stays where its box says.
    """
    measured = [b for b in blocks if b.rect is not None]
    out: list[Block] = []
    for block in blocks:
        rect = block.rect
        if rect is None or block.text.strip():
            out.append(block)
            continue
        held = 0
        for other in measured:
            if other is block or other.rect is None:
                continue
            if _holds(rect, other.rect):
                held += 1
                if held >= _MIN_BACKDROP_COVER:
                    block = block.model_copy(update={"rect": None})
                    break
        out.append(block)
    return out


def _holds(outer: Rect, inner: Rect) -> bool:
    """Whether `inner` lies wholly within `outer`."""
    return (
        inner.x >= outer.x - _EPSILON
        and inner.y >= outer.y - _EPSILON
        and inner.x + inner.width <= outer.x + outer.width + _EPSILON
        and inner.y + inner.height <= outer.y + outer.height + _EPSILON
    )


_INDEXED_STEP: Final[re.Pattern[str]] = re.compile(r"\[\d+\]")
_MAX_CARD_SHARE: Final[float] = 0.2
"""The largest a repeated container may be, as a share of the page's measured blocks, and
still count as a card. A page is not a card of itself."""
_MIN_CARD_SIBLINGS: Final[int] = 3


def _card_of(
    xpath: str,
    siblings: dict[str, set[str]],
    sizes: dict[str, int],
    limit: int,
    *,
    within: str = "",
) -> str | None:
    """The outermost repeated container this block belongs to, or None.

    A card is `/main/ul/li[3]`: the ancestor whose template `/main/ul/li[*]` occurs with
    several distinct indices, each holding a bounded number of blocks. The outermost such
    ancestor, so that a card's inner `div[*]`s do not split it into pieces; bounded, so
    that `/html/body/div[*]` -- two halves of a page -- is not two cards.

    `within` is the card already being read, when there is one: only the steps below it
    count, so the cards nested inside it can be found in their turn.
    """
    matches = list(_INDEXED_STEP.finditer(xpath, len(within)))
    for match in matches:  # outermost first
        template = xpath[: match.start()] + "[*]"
        instance = xpath[: match.end()]
        if (
            len(siblings.get(template, ())) >= _MIN_CARD_SIBLINGS
            and sizes.get(instance, 0) <= limit
        ):
            return instance
    return None


def _bounds(members: list[Block]) -> Rect:
    rects = [m.rect for m in members if m.rect is not None]
    x0, y0 = min(r.x for r in rects), min(r.y for r in rects)
    x1, y1 = max(r.right for r in rects), max(r.bottom for r in rects)
    return Rect(x=x0, y=y0, width=x1 - x0, height=y1 - y0)


def _card_rows(
    cards: dict[str, list[Block]], *, unit: float
) -> tuple[dict[str, list[str]], set[str]]:
    """The templates whose cards stand in one row, and the cards of every other template.

    A row is what a geometric cut gets wrong: cards beside each other, closer together
    than their own parts are, are read across instead of down. So a row is exactly the
    case worth binding -- every card of the template sharing vertical extent with every
    other and standing wholly to one side of it (within a line's tolerance: supabase.com's
    product cards let a picture bleed 2px into the next column). Anything else is left to
    geometry, which already reads it: a column of stacked rows, and a fan of slides drawn
    over one another (supabase.com's customer stories -- five 560px cards offset by 84px,
    where geometry rightly reads the row of logos before any story).
    """
    by_template: dict[str, list[str]] = {}
    for key in cards:
        by_template.setdefault(_INDEXED_STEP.sub("[*]", key), []).append(key)
    rows: dict[str, list[str]] = {}
    loose: set[str] = set()
    for template, keys in by_template.items():
        boxes = {k: _bounds(cards[k]) for k in keys}
        in_a_row = len(keys) >= _MIN_CARD_SIBLINGS
        for i, a in enumerate(keys):
            for b in keys[i + 1 :]:
                ra, rb = boxes[a], boxes[b]
                shares_rows = ra.y < rb.bottom and rb.y < ra.bottom
                to_a_side = ra.right <= rb.x + unit or rb.right <= ra.x + unit
                if not (shares_rows and to_a_side):
                    in_a_row = False
        if in_a_row:
            rows[template] = sorted(keys, key=lambda k: boxes[k].x)
        else:
            loose.update(keys)
    return rows, loose


def _cut_with_cards(
    blocks: list[Block],
    *,
    rtl: bool,
    config: OrderingConfig,
    unit: float,
    within: str = "",
    depth: int = 0,
    limit: int | None = None,
) -> list[Block]:
    """XY-cut over the page with each repeated card treated as one block.

    A product grid defeats a geometric cut twice over. Its cards nearly touch -- an 11px
    gutter between 312px cards on allbirds.com, narrower than any row gap -- so no column
    cut is found, and the row gap between a card's image and its title *is* found, so the
    page is read as a row of images, then a row of titles, then a row of prices. Every
    card's parts end up interleaved with its neighbours'.

    The DOM knows what geometry does not: the card is a repeated sibling container, and
    everything inside it belongs together. So each card is collapsed to one block spanning
    its members' rectangles, the cut runs over cards and loose blocks alike, and each card
    is then expanded by its own geometry -- image, name, colour, price, top to bottom --
    which no neighbouring card can interleave with any more.

    Cards nest, and the rule applies inside a card as it does on the page. A Shopify
    product page is a column of `section[*]`s, each one a card by this rule; its "details"
    section holds three `li[*]` slides side by side -- picture, heading, paragraph -- with
    10px between the columns and 25px between the rows. Read as one card and cut by
    geometry inside, that section came out as three headings and then three paragraphs
    (allbirds.com, "THE DETAILS / MATERIALLY BETTER / WASH & CARE" before any of their
    text). `within` names the card being expanded, and the cards inside it are found
    below it.
    """
    measured = [b for b in blocks if b.rect is not None]
    siblings: dict[str, set[str]] = {}
    sizes: dict[str, int] = {}
    for b in measured:
        for match in _INDEXED_STEP.finditer(b.xpath):
            template = b.xpath[: match.start()] + "[*]"
            instance = b.xpath[: match.end()]
            siblings.setdefault(template, set()).add(match.group(0))
            sizes[instance] = sizes.get(instance, 0) + 1
    # The bound is the page's, not the card's: three slides of three blocks are cards in a
    # nine-block section as much as on the page.
    if limit is None:
        limit = max(1, int(len(measured) * _MAX_CARD_SHARE))

    cards: dict[str, list[Block]] = {}
    loose: list[Block] = []
    row_order: dict[str, list[list[Block]]] = {}
    for b in blocks:
        if b.rect is None:
            card = None
        elif b.float_of is not None:
            # The browser said this sits in a float: beside the flow, with text wrapping
            # around it. A thumbnail and its caption, or an infobox and its rows, are one
            # thing however the paragraphs beside them fall. Measured on en.wikipedia's
            # "Computer": a right-floated gallery of five images and their caption list
            # was dealt out one piece at a time between the lead's paragraphs.
            card = b.float_of
        else:
            card = _card_of(b.xpath, siblings, sizes, limit, within=within)
        if card is None:
            loose.append(b)
        else:
            cards.setdefault(card, []).append(b)

    # Cards of one block are just blocks; only a card with several members changes anything.
    for key in [k for k, members in cards.items() if len(members) < 2]:
        loose.extend(cards.pop(key))
    if within:
        # Inside a card, only a *row* of cards is bound, and the row is one thing: its
        # cards are read left to right (right to left on an RTL page) and each one top to
        # bottom. Binding every nested sibling instead was measured on the reading-order
        # board: supabase.com's front page 0.999 -> 0.985 against the axioms, from a
        # fan of overlapping slides read one at a time and a row of cards whose bleeding
        # pictures left the cut nothing to cut, so it fell back to an order that was
        # neither. See `_card_rows`.
        rows, unbound = _card_rows(cards, unit=unit)
        for key in unbound:
            loose.extend(cards.pop(key))
        for template, keys in rows.items():
            members = [m for k in keys for m in cards.pop(k)]
            cards[template] = members
            row_order[template] = [
                [m for m in members if m.xpath.startswith(k + "/") or m.xpath == k]
                for k in (reversed(keys) if rtl else keys)
            ]
    if not cards:
        return _cut(blocks, rtl=rtl, config=config, unit=unit, depth=depth)

    proxies: dict[int, list[Block]] = {}
    stand_ins: list[Block] = []
    for key, members in cards.items():
        rects = [m.rect for m in members if m.rect is not None]
        x0 = min(r.x for r in rects)
        y0 = min(r.y for r in rects)
        x1 = max(r.right for r in rects)
        y1 = max(r.bottom for r in rects)
        first = min(members, key=lambda m: m.dom_index)
        proxy = first.model_copy(
            update={"rect": Rect(x=x0, y=y0, width=x1 - x0, height=y1 - y0), "xpath": key}
        )
        proxies[id(proxy)] = members
        stand_ins.append(proxy)

    ordered = _cut([*loose, *stand_ins], rtl=rtl, config=config, unit=unit, depth=depth)
    out: list[Block] = []
    for b in ordered:
        inside = proxies.get(id(b))
        if inside is None:
            out.append(b)
            continue
        # Inside the card, geometry again: a card is small enough that its own layout is
        # unambiguous, and a badge the author placed last in the markup but drew at the top
        # is read at the top. Source order was tried and measured 0.2 points worse on the
        # stacked axiom for exactly that reason. And cards again, for the ones nested in
        # this one; a float is the browser's grouping, not the markup's, and stays whole.
        key = b.xpath
        if key in row_order:
            for card_members in row_order[key]:
                out.extend(_cut(card_members, rtl=rtl, config=config, unit=unit, depth=depth + 1))
        elif any(m.float_of == key for m in inside):
            out.extend(_cut(inside, rtl=rtl, config=config, unit=unit, depth=depth + 1))
        else:
            out.extend(
                _cut_with_cards(
                    inside,
                    rtl=rtl,
                    config=config,
                    unit=unit,
                    within=key,
                    depth=depth + 1,
                    limit=limit,
                )
            )
    return out


def _anchor_unmeasured(ordered: list[Block], every: list[Block]) -> list[Block]:
    """Slot the unmeasured blocks back in, each after its nearest measured predecessor.

    Runs of consecutive unmeasured blocks keep their source order, so a collapsed section's
    paragraphs stay in the order they were written.
    """
    measured_positions = {id(block): index for index, block in enumerate(ordered)}
    by_source = sorted(every, key=lambda b: b.dom_index)

    following: dict[int, list[Block]] = {}
    leading: list[Block] = []
    anchor: Block | None = None

    for block in by_source:
        if id(block) in measured_positions:
            anchor = block
            continue
        if anchor is None:
            # Nothing measured precedes it; it goes at the front, before everything.
            leading.append(block)
        else:
            following.setdefault(id(anchor), []).append(block)

    result: list[Block] = list(leading)
    for block in ordered:
        result.append(block)
        result.extend(following.get(id(block), ()))
    return result


def _cut(
    blocks: list[Block],
    *,
    rtl: bool,
    config: OrderingConfig,
    unit: float,
    depth: int,
) -> list[Block]:
    """Recursively partition `blocks` into reading order."""
    if len(blocks) <= 1 or depth >= config.max_depth:
        return _positional(blocks, rtl=rtl)

    row_threshold = max(config.min_absolute_gap, unit * config.min_row_gap_ratio)
    col_threshold = max(config.min_absolute_gap, unit * config.min_col_gap_ratio)

    row_boundaries, row_gap = _find_gaps(blocks, axis="y", min_gap=row_threshold)
    col_boundaries, col_gap = _find_gaps(blocks, axis="x", min_gap=col_threshold)

    # Take whichever axis is separated by the wider gutter.
    #
    # Always cutting rows first is wrong: on a grid-aligned multi-column layout the row
    # gaps also qualify, and cutting on them reads *across* the columns instead of down
    # them. Comparing gutter widths resolves it -- a real column gutter is wider than
    # inter-paragraph leading, while a section break below a spanning header is wider
    # than any column gap (there usually isn't one, since the header bridges it).
    use_columns = bool(col_boundaries) and (not row_boundaries or col_gap > row_gap)

    if use_columns:
        columns = _partition(blocks, axis="x", boundaries=col_boundaries)
        if rtl:
            columns.reverse()
        out: list[Block] = []
        for column in columns:
            out.extend(_cut(column, rtl=rtl, config=config, unit=unit, depth=depth + 1))
        return out

    if row_boundaries:
        out = []
        for band in _partition(blocks, axis="y", boundaries=row_boundaries):
            out.extend(_cut(band, rtl=rtl, config=config, unit=unit, depth=depth + 1))
        return out

    # No clean cut on either axis. Before giving up and reading by position, look for a
    # cut that a *few* blocks straddle. This is the deadlock a docs site produces: a
    # sidebar list with no vertical gaps bridges every row, and a wide banner across the
    # top bridges every column, so no whitespace band crosses the whole region -- yet the
    # region is plainly three columns. Measured on MDN, the sidebar's links and the
    # right-hand table of contents came out zipped together, one line each in turn,
    # because position order was all that was left. A cut that only the banner crosses
    # separates them; the banner is read first, then each column in turn.
    bridged = _tolerant_cut(blocks, rtl=rtl, config=config, unit=unit, depth=depth)
    if bridged is not None:
        return bridged

    return _positional(blocks, rtl=rtl)


_MAX_BRIDGE_SHARE: Final[float] = 0.04
"""Blocks that may straddle a tolerant cut, as a share of the region (and never fewer than
one). Above this the region is not two things with something across them; it is one thing."""


def _tolerant_cut(
    blocks: list[Block],
    *,
    rtl: bool,
    config: OrderingConfig,
    unit: float,
    depth: int,
) -> list[Block] | None:
    """Cut into columns where at most a few wide blocks straddle the gutter, or None.

    Every block edge along x is a candidate line. A line qualifies when the blocks it
    crosses are few, both sides hold more than a stray block, and once the bridges are set
    aside the sides are separated by a real gutter. The widest such gutter wins.

    The bridges are not read first. A wide block across the columns is a banner when it sits
    at the top and a footer when it sits at the bottom, and reading a footer before the
    columns above it puts the end of the page first -- measured as a 0.8-point loss on the
    stacked axiom when this did exactly that. Instead each bridge divides the region into
    the bands above and below it: the columns of a band are read left to right, then the
    bridge, then the next band. A banner therefore comes first and a footer last, and a
    mid-page bridge separates what is above from what is below, which is what it does on
    the screen.

    Columns only. The mirror case -- a horizontal cut that a tall sidebar straddles -- is
    left to position order, because a tall bridge has no equivalent "above / below" reading
    that is right often enough to ship.
    """
    measured = [b for b in blocks if b.rect is not None]
    if len(measured) < 4:
        return None
    allowance = max(1, int(len(measured) * _MAX_BRIDGE_SHARE))
    threshold = max(config.min_absolute_gap, unit * config.min_col_gap_ratio)

    extents = _extents(measured, "x")
    best: tuple[float, float] | None = None  # (gap, line)
    edges = sorted({start for start, _, _ in extents} | {end for _, end, _ in extents})
    for line in edges:
        before = [e for e in extents if e[1] <= line + _EPSILON]
        after = [e for e in extents if e[0] >= line - _EPSILON]
        straddling = len(extents) - len(before) - len(after)
        if straddling > allowance or len(before) < 2 or len(after) < 2:
            continue
        gap = min(a[0] for a in after) - max(b[1] for b in before)
        if gap >= threshold and (best is None or gap > best[0]):
            best = (gap, line)
    if best is None:
        return None
    _, line = best

    left = [b for s_, e_, b in extents if e_ <= line + _EPSILON]
    right = [b for s_, e_, b in extents if s_ >= line - _EPSILON]
    sided = {id(b) for b in left} | {id(b) for b in right}
    bridges = sorted(
        (b for b in measured if id(b) not in sided), key=lambda b: b.rect.y if b.rect else 0.0
    )
    unmeasured = [b for b in blocks if b.rect is None]

    def band(items: list[Block], top: float, bottom: float) -> list[Block]:
        return [
            b
            for b in items
            if b.rect is not None and top <= (b.rect.y + b.rect.bottom) / 2 < bottom
        ]

    columns = [left, right]
    if rtl:
        columns.reverse()
    out: list[Block] = []
    top = float("-inf")
    for bridge in [*bridges, None]:
        bottom = bridge.rect.y if bridge is not None and bridge.rect is not None else float("inf")
        for column in columns:
            part = band(column, top, bottom)
            if part:
                out.extend(_cut(part, rtl=rtl, config=config, unit=unit, depth=depth + 1))
        if bridge is not None:
            out.append(bridge)
            top = bottom
    # Blocks without geometry cannot be placed by a cut; they follow, in source order.
    out.extend(unmeasured)
    return out


def _extents(blocks: list[Block], axis: str) -> list[tuple[float, float, Block]]:
    out: list[tuple[float, float, Block]] = []
    for b in blocks:
        if b.rect is None:
            continue
        if axis == "y":
            out.append((b.rect.y, b.rect.bottom, b))
        else:
            out.append((b.rect.x, b.rect.right, b))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def _find_gaps(blocks: list[Block], *, axis: str, min_gap: float) -> tuple[list[float], float]:
    """Locate whitespace bands along `axis`.

    Returns the cut positions and the width of the widest qualifying gap. The width is
    what lets the caller decide which axis separates the region more decisively.
    """
    intervals = _extents(blocks, axis)
    if len(intervals) < 2:
        return [], 0.0

    # Merge overlapping extents; the holes between merged runs are the candidate cuts.
    merged: list[tuple[float, float]] = []
    cur_start, cur_end, _ = intervals[0]
    for start, end, _ in intervals[1:]:
        if start <= cur_end + _EPSILON:
            cur_end = max(cur_end, end)
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = start, end
    merged.append((cur_start, cur_end))

    candidates: list[tuple[float, float]] = []
    widest = 0.0
    for i in range(len(merged) - 1):
        gap = merged[i + 1][0] - merged[i][1]
        if gap >= min_gap:
            candidates.append((gap, (merged[i][1] + merged[i + 1][0]) / 2.0))
            widest = max(widest, gap)

    if not candidates:
        return [], 0.0

    # Cut only at the widest band (and any band effectively tied with it), never at every
    # qualifying gap at once.
    #
    # Cutting everywhere is what breaks a header-over-columns layout: the row gaps
    # *between* the column rows also qualify, so the columns get sliced into rows before
    # the column structure is ever seen, and the text reads across instead of down.
    # Cutting at the widest gap first lets the recursion discover the columns underneath.
    # The tie tolerance keeps uniformly-spaced single-column pages to one cut rather than
    # recursing once per paragraph.
    threshold = widest * _TIE_TOLERANCE
    boundaries = [pos for gap, pos in candidates if gap >= threshold]
    return boundaries, widest


def _partition(blocks: list[Block], *, axis: str, boundaries: list[float]) -> list[list[Block]]:
    """Split blocks into groups delimited by `boundaries` along `axis`."""
    groups: list[list[Block]] = [[] for _ in range(len(boundaries) + 1)]
    for start, _end, block in _extents(blocks, axis):
        index = 0
        for boundary in boundaries:
            if start >= boundary:
                index += 1
            else:
                break
        groups[index].append(block)
    return [g for g in groups if g]


def _positional(blocks: list[Block], *, rtl: bool = False) -> list[Block]:
    """Order an atomic region: group into visual rows, then read along each row.

    Sorting by `(y, x)` looks equivalent and is not, because `y` is a float measured from a
    real layout. Measured on supabase.com, the top navigation renders `Pricing` at y=70.4 and
    `Product` at y=71.0 -- **six tenths of a pixel apart, on the same visual row** -- and a
    tuple sort on exact `y` therefore read the bar as `Pricing, Docs, Blog, Product,
    Developers`. Any horizontal nav or row of cards whose items differ by sub-pixel amounts
    came out scrambled, and the same failure appeared on Hebrew Wikipedia's menu row.

    So blocks are first banded into rows by vertical overlap -- the way a reader sees a line
    of items as one line -- and only then ordered along the row. Right to left when `rtl`,
    for the same reason columns reverse.

    Banding is by *overlap*, not by a `y` tolerance in pixels: a tolerance has to be tuned to
    a font size, while overlap is scale-free and works on a dense sidebar and an airy hero
    alike. The band is the row's first block and does not grow -- see the comment below.
    """

    def top(b: Block) -> tuple[float, float, int]:
        if b.rect is None:
            return (0.0, 0.0, b.dom_index)
        return (b.rect.y, b.rect.x, b.dom_index)

    ordered = sorted(blocks, key=top)

    rows: list[list[Block]] = []
    band: tuple[float, float] | None = None
    for block in ordered:
        if block.rect is None:
            # No geometry: it cannot join a band, and starting one would capture the blocks
            # after it. Its own row, in the position source order put it.
            rows.append([block])
            band = None
            continue

        height = block.rect.height
        if band is not None and height > 0:
            overlap = min(band[1], block.rect.bottom) - max(band[0], block.rect.y)
            # Measured against the TALLER of the two, so only genuine peers band together.
            # Against the shorter one, a tall block anchors a band that swallows short blocks
            # both above and below it, which then get ordered by x and lose their vertical
            # relationship outright.
            reference = max(height, band[1] - band[0])
            # The band is the row's FIRST block and never grows. Letting it expand to cover
            # each joiner was measured as a net loss: a tall item dragged the band downward,
            # absorbed the blocks genuinely below it, and ordered them by x. A fixed anchor
            # band cannot creep.
            if reference > 0 and overlap >= reference * _ROW_BAND_OVERLAP:
                rows[-1].append(block)
                continue

        rows.append([block])
        band = (block.rect.y, block.rect.bottom)

    def along(b: Block) -> tuple[float, int]:
        if b.rect is None:
            return (0.0, b.dom_index)
        # DOM order breaks an exact tie, so the sort stays deterministic across runs.
        return (-b.rect.x if rtl else b.rect.x, b.dom_index)

    return [block for row in rows for block in sorted(row, key=along)]


def detect_columns(
    blocks: list[Block],
    *,
    min_gap: float = 16.0,
) -> int:
    """Count top-level columns. Diagnostic helper, used by tests and the profiler."""
    positioned = [b for b in blocks if b.rect is not None]
    if len(positioned) < 2:
        return 1
    boundaries, _ = _find_gaps(positioned, axis="x", min_gap=min_gap)
    return len(boundaries) + 1
