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

from dataclasses import dataclass
from statistics import median

from webgraph.types import Block, ReadingOrderMethod

__all__ = ["OrderingConfig", "detect_columns", "order_blocks"]

_EPSILON = 1e-6
_TIE_TOLERANCE = 0.95
"""Gaps within this fraction of the widest are treated as equivalent and cut together."""


@dataclass(frozen=True, slots=True)
class OrderingConfig:
    """Tuning for cut detection.

    Gap thresholds are expressed as multiples of the median block height rather than as
    absolute pixels, so the same config works on a dense sidebar and an airy landing page.
    """

    min_row_gap_ratio: float = 0.6
    """A vertical whitespace band must exceed this multiple of median block height to count
    as a row separator. Below it, the gap is ordinary line spacing."""

    min_col_gap_ratio: float = 1.0
    """A horizontal whitespace band must exceed this multiple of median block height to
    count as a column gutter. Set higher than the row threshold because inline spacing
    between words and inline elements is common and must not be read as a column break."""

    min_absolute_gap: float = 8.0
    """Floor in CSS pixels, guarding against degenerate tiny-text pages."""

    max_depth: int = 24
    """Recursion guard. Deeply nested cuts past this point are ordered positionally."""

    min_measured_share: float = 0.3
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
    unit = median(heights) if heights else 16.0

    if len(measured) == len(blocks):
        # Nothing to anchor, so neither guard applies: complete geometry is always used.
        ordered = _cut(list(blocks), rtl=rtl, config=config, unit=unit, depth=0)
        return ordered, ReadingOrderMethod.GEOMETRIC_XY_CUT

    if len(measured) < len(blocks) * config.min_measured_share:
        # Too little geometry to lead with. Anchoring most of a document to a handful of
        # measurements would dress source order up as a measurement.
        return sorted(blocks, key=lambda b: b.dom_index), ReadingOrderMethod.DOM_FALLBACK

    ordered = _cut(list(measured), rtl=rtl, config=config, unit=unit, depth=0)
    return _anchor_unmeasured(ordered, blocks), ReadingOrderMethod.GEOMETRIC_ANCHORED


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
        return _positional(blocks)

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

    return _positional(blocks)


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


def _find_gaps(
    blocks: list[Block], *, axis: str, min_gap: float
) -> tuple[list[float], float]:
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


def _partition(
    blocks: list[Block], *, axis: str, boundaries: list[float]
) -> list[list[Block]]:
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


def _positional(blocks: list[Block]) -> list[Block]:
    """Order an atomic region: top to bottom, then left to right, DOM order as tiebreak.

    The DOM-index tiebreak matters for blocks that share a position exactly -- without it
    the sort is unstable across runs and output becomes non-deterministic.
    """

    def key(b: Block) -> tuple[float, float, int]:
        if b.rect is None:
            return (0.0, 0.0, b.dom_index)
        return (b.rect.y, b.rect.x, b.dom_index)

    return sorted(blocks, key=key)


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
