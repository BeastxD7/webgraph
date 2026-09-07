"""Does geometric reading order actually beat a DOM walk? By how much, on real pages?

Why this benchmark has to exist
--------------------------------
Reading-order recovery is this engine's central claim, and until now its only evidence was
the six-page blinding table in `dom/reading_order.py`. Meanwhile **no public benchmark
measures reading order for HTML at all** -- and not by oversight. Every HTML extraction
benchmark scores a bag of words or n-grams:

    Zyte article-extraction-benchmark   4-gram shingle bags
    WCXB                                word bags, lowercased
    WebMainBench                        ROUGE-N
    SIGIR'25 multilingual eval          ROUGE-L + Levenshtein

A bag of words is *order-destroying by construction*. It cannot tell a correctly-read
two-column page from one read straight across, because both contain the same words. ROUGE-L
catches local order but cannot distinguish column interleaving from omission. So the thing
this engine is built to do is invisible to every number the field currently reports.

The PDF world does measure it -- olmOCR-Bench uses binary span-order unit tests, ParseBench
uses pairwise precedence assertions -- and those metrics port to a linearised DOM directly,
because neither needs page coordinates in the output. This is that port.

The circularity trap, and how it is avoided
--------------------------------------------
The obvious design is to treat the XY-cut output as ground truth and score a DOM walk
against it. That measures nothing: it assumes the answer.

So the assertions here are generated from **geometric axioms**, not from any ordering
algorithm. Two facts about reading order are true regardless of how you compute it:

  1. **Stacked.** If A and B share horizontal extent and A ends entirely above B starts,
     then A is read before B. This is what "reading down a column" means.
  2. **Side by side.** If A and B share vertical extent and A ends entirely to the left of
     where B starts, then A is read before B -- reversed when the document is right-to-left.

Neither rule consults `dom_index`, and neither is derived from `_cut`. XY-cut is one
candidate answer to these axioms and DOM order is another; both are then scored against
them. A pair that satisfies neither rule (diagonal, overlapping, ambiguous) generates no
assertion, which is the honest treatment of a case where reading order genuinely is not
determined by geometry.

What the numbers mean
---------------------
`agree` is the share of all assertions an ordering satisfies. The number that matters is
`discriminating`: the assertions where DOM order and geometric order actually disagree, and
therefore the only ones carrying information about which is better. A page where both score
1.000 is a page where reading order recovery was never needed -- and reporting a corpus
average without that split is how you get a flattering number about nothing.

Usage
-----
    uv run --package webgraph python benchmark/reading_order/run.py
    uv run --package webgraph python benchmark/reading_order/run.py --json out.json

Reads the page cache that `benchmark/union_adjacency` populates -- rendered HTML plus its
measured rectangles. Run `make bench-union-fetch` first if it is empty.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Final

from webgraph.dom.blocks import is_rtl_document, parse_html
from webgraph.fetch.render import geometry_by_xpath
from webgraph.pipeline import build_document
from webgraph.types import Block, Rect

DEFAULT_CACHE: Final[Path] = Path(__file__).parent.parent / "union_adjacency" / "cache"

MIN_COLUMN_GAP: Final[float] = 24.0
"""Horizontal whitespace, in CSS pixels, before two blocks count as separate columns.

Generous. A narrow gap is inter-word or inter-cell spacing, and an assertion built on one
would be noise asserted as fact. The point of this benchmark is that its assertions are not
arguable, so the bar for generating one is set high rather than for coverage."""

MIN_ROW_GAP: Final[float] = 2.0
"""Vertical whitespace before two blocks count as stacked. Small: adjacent paragraphs in a
column genuinely do touch, and their order is not in doubt."""

OVERLAP_TOLERANCE: Final[float] = 4.0
"""Slack when asking whether two blocks share an axis, absorbing sub-pixel layout jitter."""

MIN_SHARED_FRACTION: Final[float] = 0.5
"""Share of an extent that must overlap before two blocks count as occupying the same band.

Applied against the narrower block for the stacked axiom (`_shares`) and against *both*
blocks for side-by-side (`_co_occupies`). A block overlapping a column by two pixels is not
in that column and must not anchor an assertion."""

MAX_PAIRS_PER_PAGE: Final[int] = 60_000
"""Pairs sampled per page. Exhaustive is quadratic and lemonde.fr has thousands of blocks."""


@dataclass(frozen=True, slots=True)
class Assertion:
    """`before` must be read before `after`. `rule` records which axiom produced it."""

    before: int
    after: int
    rule: str


def _shares(lo_a: float, hi_a: float, lo_b: float, hi_b: float) -> bool:
    """Whether two extents overlap enough that the *narrower* one sits inside the other.

    Right for the stacked axiom: a full-width heading above a narrow column block shares the
    column's horizontal extent completely, and "heading first" is exactly the assertion we
    want. Wrong for side-by-side -- see `_co_occupies`.
    """
    overlap = min(hi_a, hi_b) - max(lo_a, lo_b)
    if overlap <= 0:
        return False
    narrower = min(hi_a - lo_a, hi_b - lo_b)
    if narrower <= 0:
        return False
    return overlap >= narrower * MIN_SHARED_FRACTION


def _co_occupies(lo_a: float, hi_a: float, lo_b: float, hi_b: float) -> bool:
    """Whether two extents substantially share a band -- measured against **both**, not the
    narrower one.

    This distinction was found by running the benchmark against itself. Using `_shares` for
    the side-by-side axiom made a 29.7px line of body text a "side-by-side peer" of a
    1,062px right-hand sidebar on docs.pytest.org, purely because the line's own height was
    fully inside the sidebar's. It then asserted a reading order between a single line and
    an entire column, which geometry does not settle at all -- and the assertion failed,
    making a correct XY-cut look wrong.

    Two blocks are side-by-side peers only if each occupies most of the shared band: two
    cards in a row, two cells of a row. A short block beside a tall column is a block inside
    one column and a whole other column, and their order is decided by the column structure,
    which is precisely the thing under test and therefore cannot be assumed here.
    """
    overlap = min(hi_a, hi_b) - max(lo_a, lo_b)
    if overlap <= 0:
        return False
    height_a, height_b = hi_a - lo_a, hi_b - lo_b
    if height_a <= 0 or height_b <= 0:
        return False
    return overlap >= height_a * MIN_SHARED_FRACTION and overlap >= height_b * MIN_SHARED_FRACTION


def assertions_for(blocks: list[Block], *, rtl: bool, rng: random.Random) -> list[Assertion]:
    """Derive unambiguous precedence assertions from geometry alone.

    Deliberately generates nothing for pairs whose order geometry does not settle. Coverage
    is not the goal; an assertion nobody would dispute is.
    """
    measured = [(index, b) for index, b in enumerate(blocks) if b.rect is not None]
    if len(measured) < 2:
        return []

    # Pair sampling must not depend on the ordering under test. Enumerating `blocks` as the
    # engine returned them made the sampled pairs -- and therefore the assertion count -- a
    # function of the answer, so two runs of a changed orderer were not comparable: an A/B
    # showed 592,666 assertions against 592,388 for no reason but the sample. Sorting by
    # source position fixes the set; the indices returned still address the caller's list.
    measured.sort(key=lambda pair: pair[1].dom_index)

    pairs: list[tuple[int, int]]
    total = len(measured) * (len(measured) - 1) // 2
    if total <= MAX_PAIRS_PER_PAGE:
        pairs = [(i, j) for i in range(len(measured)) for j in range(i + 1, len(measured))]
    else:
        pairs = [
            (i, j)
            for i, j in (
                sorted(rng.sample(range(len(measured)), 2)) for _ in range(MAX_PAIRS_PER_PAGE)
            )
        ]

    out: list[Assertion] = []
    for i, j in pairs:
        index_a, a = measured[i]
        index_b, b = measured[j]
        ra, rb = a.rect, b.rect
        if ra is None or rb is None:
            continue

        # Axiom 1 -- stacked in the same column band.
        if _shares(ra.x, ra.right, rb.x, rb.right):
            if rb.y - ra.bottom >= MIN_ROW_GAP:
                out.append(Assertion(index_a, index_b, "stacked"))
                continue
            if ra.y - rb.bottom >= MIN_ROW_GAP:
                out.append(Assertion(index_b, index_a, "stacked"))
                continue

        # Axiom 2 -- side by side on the same row band. Direction flips for RTL.
        if _co_occupies(ra.y, ra.bottom, rb.y, rb.bottom):
            if rb.x - ra.right >= MIN_COLUMN_GAP:
                first, second = (index_b, index_a) if rtl else (index_a, index_b)
                out.append(Assertion(first, second, "side-by-side"))
            elif ra.x - rb.right >= MIN_COLUMN_GAP:
                first, second = (index_a, index_b) if rtl else (index_b, index_a)
                out.append(Assertion(first, second, "side-by-side"))

    return out


def score(order: list[int], claims: list[Assertion]) -> tuple[int, int]:
    """(satisfied, total) for one ordering. `order` is block indices in reading sequence."""
    position = {block_index: rank for rank, block_index in enumerate(order)}
    satisfied = 0
    counted = 0
    for claim in claims:
        if claim.before not in position or claim.after not in position:
            continue
        counted += 1
        if position[claim.before] < position[claim.after]:
            satisfied += 1
    return satisfied, counted


@dataclass
class PageResult:
    url: str
    blocks: int = 0
    measured: int = 0
    rtl: bool = False
    method: str = ""
    claims: int = 0
    dom_ok: int = 0
    geo_ok: int = 0
    discriminating: int = 0
    dom_ok_disc: int = 0
    geo_ok_disc: int = 0
    by_rule: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    note: str = ""

    @property
    def dom_rate(self) -> float:
        return self.dom_ok / self.claims if self.claims else 0.0

    @property
    def geo_rate(self) -> float:
        return self.geo_ok / self.claims if self.claims else 0.0

    @property
    def dom_rate_disc(self) -> float:
        return self.dom_ok_disc / self.discriminating if self.discriminating else 0.0

    @property
    def geo_rate_disc(self) -> float:
        return self.geo_ok_disc / self.discriminating if self.discriminating else 0.0


def run_page(url: str, html: str, rects: dict[str, Rect]) -> PageResult:
    result = PageResult(url=url)
    geometry = geometry_by_xpath(html, rects)
    try:
        document = build_document(html, url, geometry=geometry)
    except ValueError as exc:
        result.note = f"parse failed: {exc}"
        return result

    blocks = list(document.blocks)
    result.blocks = len(blocks)
    result.measured = sum(1 for b in blocks if b.rect is not None)
    result.rtl = is_rtl_document(parse_html(html))
    result.method = document.reading_order_method.value

    if result.measured < 8:
        result.note = f"only {result.measured} measured blocks"
        return result

    rng = random.Random(20260907)
    claims = assertions_for(blocks, rtl=result.rtl, rng=rng)
    if not claims:
        result.note = "geometry settled no pair"
        return result

    # `document.blocks` is already in the engine's recovered order, so its own indices are
    # the geometric ordering. DOM order is those same blocks sorted by source position.
    geo_order = list(range(len(blocks)))
    dom_order = sorted(geo_order, key=lambda i: blocks[i].dom_index)

    result.claims = len(claims)
    result.geo_ok, _ = score(geo_order, claims)
    result.dom_ok, _ = score(dom_order, claims)

    geo_pos = {b: r for r, b in enumerate(geo_order)}
    dom_pos = {b: r for r, b in enumerate(dom_order)}
    discriminating = [
        c
        for c in claims
        if (geo_pos[c.before] < geo_pos[c.after]) != (dom_pos[c.before] < dom_pos[c.after])
    ]
    result.discriminating = len(discriminating)
    if discriminating:
        result.geo_ok_disc, _ = score(geo_order, discriminating)
        result.dom_ok_disc, _ = score(dom_order, discriminating)

    for rule in ("stacked", "side-by-side"):
        subset = [c for c in claims if c.rule == rule]
        if subset:
            g, _ = score(geo_order, subset)
            d, _ = score(dom_order, subset)
            result.by_rule[rule] = (len(subset), g, d)

    return result


def report(results: list[PageResult]) -> dict[str, Any]:
    scored = [r for r in results if r.claims]
    skipped = [r for r in results if not r.claims]

    print("\n" + "=" * 86)
    print("READING ORDER -- geometric recovery vs a DOM walk, scored on geometric axioms")
    print("=" * 86)
    print(f"\n  Pages scored   {len(scored)}")
    if skipped:
        print(f"  Skipped        {len(skipped)}")

    if not scored:
        print("\n  Nothing to score. Run `make bench-union-fetch` to populate the page cache.")
        return {"scored": 0}

    print("\n  PER PAGE   'disc' = assertions where the two orderings disagree")
    print(f"\n    {'page':<32}{'rtl':>4}{'blocks':>7}{'claims':>8}{'geo':>7}{'dom':>7}"
          f"{'disc':>7}{'geo|d':>7}{'dom|d':>7}")
    print("    " + "-" * 82)
    for r in sorted(scored, key=lambda r: -r.discriminating):
        host = re.sub(r"^https?://(www\.)?", "", r.url)[:31]
        print(
            f"    {host:<32}{'yes' if r.rtl else '':>4}{r.blocks:>7}{r.claims:>8}"
            f"{r.geo_rate:>7.3f}{r.dom_rate:>7.3f}{r.discriminating:>7}"
            f"{r.geo_rate_disc:>7.3f}{r.dom_rate_disc:>7.3f}"
        )

    total_claims = sum(r.claims for r in scored)
    geo = sum(r.geo_ok for r in scored) / total_claims
    dom = sum(r.dom_ok for r in scored) / total_claims
    total_disc = sum(r.discriminating for r in scored)

    print("\n  OVERALL  (assertion-weighted)")
    print(f"    assertions generated        {total_claims:,}")
    print(f"    geometric reading order     {geo:.4f}")
    print(f"    DOM order                   {dom:.4f}")
    print(f"    difference                  {geo - dom:+.4f}")

    print("\n  WHERE IT MATTERS")
    print(f"    discriminating assertions   {total_disc:,}"
          f"  ({total_disc / total_claims:.1%} of all)")
    if total_disc:
        geo_d = sum(r.geo_ok_disc for r in scored) / total_disc
        dom_d = sum(r.dom_ok_disc for r in scored) / total_disc
        print(f"    geometric                   {geo_d:.4f}")
        print(f"    DOM                         {dom_d:.4f}")
        print("\n    These are the pairs the two orderings sequence differently -- the only")
        print("    ones carrying information about which method is right.")

    print("\n  BY AXIOM")
    for rule in ("stacked", "side-by-side"):
        rows = [r.by_rule[rule] for r in scored if rule in r.by_rule]
        if not rows:
            continue
        n = sum(x[0] for x in rows)
        print(f"    {rule:<14} n={n:>8,}   geo {sum(x[1] for x in rows) / n:.4f}"
              f"   dom {sum(x[2] for x in rows) / n:.4f}")

    rtl_pages = [r for r in scored if r.rtl]
    if rtl_pages:
        n = sum(r.claims for r in rtl_pages)
        print(f"\n  RIGHT-TO-LEFT PAGES  ({len(rtl_pages)})")
        print(f"    geometric {sum(r.geo_ok for r in rtl_pages) / n:.4f}"
              f"   dom {sum(r.dom_ok for r in rtl_pages) / n:.4f}")

    methods: dict[str, int] = {}
    for r in scored:
        methods[r.method] = methods.get(r.method, 0) + 1
    print("\n  ORDERING METHOD USED")
    for name, count in sorted(methods.items(), key=lambda kv: -kv[1]):
        print(f"    {name:<22} {count}")
    print(f"\n    median measured share  "
          f"{median([r.measured / r.blocks for r in scored if r.blocks]):.1%}")

    return {
        "scored": len(scored),
        "assertions": total_claims,
        "geometric": round(geo, 4),
        "dom": round(dom, 4),
        "discriminating": total_disc,
        "geometric_discriminating": round(
            sum(r.geo_ok_disc for r in scored) / total_disc, 4
        ) if total_disc else None,
        "dom_discriminating": round(
            sum(r.dom_ok_disc for r in scored) / total_disc, 4
        ) if total_disc else None,
        "pages": [
            {
                "url": r.url,
                "rtl": r.rtl,
                "blocks": r.blocks,
                "assertions": r.claims,
                "geometric": round(r.geo_rate, 4),
                "dom": round(r.dom_rate, 4),
                "discriminating": r.discriminating,
                "geometric_disc": round(r.geo_rate_disc, 4),
                "dom_disc": round(r.dom_rate_disc, 4),
                "method": r.method,
            }
            for r in scored
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    files = sorted(args.cache.glob("*.json"))[: args.limit]
    if not files:
        print(f"No cached pages in {args.cache}. Run `make bench-union-fetch` first.")
        raise SystemExit(1)

    results: list[PageResult] = []
    for path in files:
        record = json.loads(path.read_text(encoding="utf-8"))
        html = record.get("rendered_html") or ""
        if not html or not record.get("render_ok"):
            continue
        rects = {k: Rect(**v) for k, v in record["rects"].items()}
        results.append(run_page(record["rendered_url"] or record["url"], html, rects))

    payload = report(results)
    if args.json:
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\n  Wrote {args.json}")


if __name__ == "__main__":
    main()
