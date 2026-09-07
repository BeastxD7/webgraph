"""Does union-by-adjacency put static-only blocks in the right place?

What is being measured
----------------------
`resolve.union_documents` merges two representations of one page. Blocks present in both are
ordered by the rendered document, whose order was measured from geometry. Blocks present
only in the static document carry no geometry, and the engine places each one **after the
nearest preceding block that appears in both documents**.

That rule was adopted in D67 on the strength of a descriptive observation -- on lemonde.fr
the static-only blocks moved from "all at the end" to "positions 0 to 2,696, median 1,293".
That shows the mechanism fires. It does not show the placements are *correct*, and the
recall change reported alongside it (0.989 -> 0.994) is confounded with a table-text fix made
in the same session. So the rule has never actually been measured.

Method: ablation against the rendered document
-----------------------------------------------
The rendered document's block order is the best ground truth available -- it was measured in
a browser. So the truth can be manufactured:

1. Find the blocks present in **both** documents. Their true order is known.
2. Delete a clustered run of them from the *rendered* document. They now appear only in the
   static document, which is exactly the input condition the placement rule handles.
3. Run the merge and ask where those blocks came back.
4. Score by pairwise order accuracy against the original rendered order.

Blinded in clustered runs, not at random, for the reason recorded in D66: real static-only
blocks arrive in runs, and random blinding is a materially easier problem.

The trap that would make every number meaningless
--------------------------------------------------
The rule chooses an anchor by walking the **static** document's order, and is scored against
the **rendered** document's order. On a page where those two orders agree, any placement rule
scores near 1.0 and the benchmark has measured nothing.

So every page is also scored for **order disagreement** -- the share of shared-block pairs
whose relative order differs between the two documents -- and results are reported bucketed
by it. An aggregate over a corpus of low-disagreement pages is a flattering number about
nothing, the same failure mode as random-vs-clustered blinding in D66.

The second difficulty axis, which the first run made obvious
-------------------------------------------------------------
Order disagreement turned out not to be the main thing separating easy pages from hard ones.
**Anchor density** is: static-only blocks per shared block. lemonde.fr and bbc.co.uk both
render behind a consent wall, so their rendered documents are a fraction of their static ones
-- lemonde contributes 2,548 static-only blocks against 30 shared, about 85 per anchor. The
rule is then placing very long runs against a single observed adjacency, which is a harder
problem than any amount of order disagreement.

Both axes are reported, and the ablation share is swept so the sparse-anchor regime is
actually exercised rather than assumed away.

Baselines
---------
- `append-end`: the pre-D67 implementation. All static-only blocks after everything else.
- `random`: static-only blocks inserted at uniformly random positions. The floor. If
  adjacency does not clearly beat this, the finding is a bug rather than a result.

Two phases, because the experiment needs many runs per page
------------------------------------------------------------
`fetch` hits the network once per site and caches the static HTML, the rendered HTML (with
its `data-wg-id` markers intact -- a re-fetch would lose them and silently drop all geometry)
and the measured rectangles. `score` runs entirely offline over that cache, so ablation
shares, seeds and baselines can be swept without refetching.

Usage
-----
    uv run python benchmark/union_adjacency/run.py fetch [--limit N] [--concurrency N]
    uv run python benchmark/union_adjacency/run.py score [--json out.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Final

from webgraph.fetch.render import RenderConfig, geometry_by_xpath, render_page
from webgraph.fetch.static import FetchConfig, fetch_static
from webgraph.pipeline import build_document
from webgraph.resolve import union_documents
from webgraph.types import Block, Document

# The engine's own deduplication key, imported rather than reimplemented so this benchmark
# cannot drift from the code it is measuring.
from webgraph.resolve import _key as block_key  # noqa: PLC2701

HERE: Final[Path] = Path(__file__).parent
DEFAULT_SITES: Final[Path] = HERE / "sites.txt"
DEFAULT_CACHE: Final[Path] = HERE / "cache"

ABLATION_SHARES: Final[tuple[float, ...]] = (0.10, 0.25, 0.40, 0.60, 0.80)
"""How much of the shared-block set to blind, swept rather than fixed.

The sweep is the point, and the first run is what forced it. On lemonde.fr the static
document contributes 2,548 blocks the rendered one lacks against only **30** shared blocks --
roughly 85 static-only blocks per available anchor. Blinding 10% of a shared set never
reaches that regime, so a fixed low share would have measured a condition the hard pages
never actually present.

Raising the share thins the anchors, which is the same stress in miniature. Accuracy is
therefore reported per share, so the reader can see where the rule starts to fail rather
than being handed one aggregate that hides it. This mirrors D66, which swept measured share
from 90% down to 10% for exactly this reason."""

SEEDS: Final[tuple[int, ...]] = (11, 29, 47)
MAX_PAIRS: Final[int] = 40_000
"""Cap on sampled pairs per accuracy computation. lemonde.fr has thousands of blocks and the
exact pairwise count is quadratic; a large random sample settles the number to three decimals."""

DISAGREEMENT_BUCKETS: Final[tuple[tuple[str, float, float], ...]] = (
    ("low    <0.02", 0.0, 0.02),
    ("medium <0.10", 0.02, 0.10),
    ("high   <0.25", 0.10, 0.25),
    ("severe >=0.25", 0.25, 1.01),
)


def slug(url: str) -> str:
    """Readable cache filename, plus a hash so distinct URLs cannot collide.

    The readable part strips every non-ASCII character, so two Arabic Wikipedia articles --
    or any two URLs differing only outside [a-z0-9] -- slugify identically and silently
    overwrite one another. That happened during the first run of this benchmark: a stale
    404 entry was served from cache for a corrected URL. Same fix as `graph/store.py`:
    the slug makes it readable, the hash makes it unique.
    """
    readable = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")[:64]
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{readable}-{digest}"


def load_sites(path: Path, limit: int | None) -> list[str]:
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if line:
            urls.append(line)
    return urls[:limit] if limit else urls


# ---------------------------------------------------------------------------
# Phase 1 -- fetch and cache
# ---------------------------------------------------------------------------


def fetch_one(url: str, cache: Path) -> dict[str, Any]:
    """Fetch one page both ways and cache it. Returns a status record."""
    target = cache / f"{slug(url)}.json"
    if target.exists():
        return {"url": url, "status": "cached"}

    record: dict[str, Any] = {"url": url}
    started = time.monotonic()

    static = fetch_static(url, config=FetchConfig(timeout_seconds=25.0))
    record["static_ok"] = static.ok and static.is_html and bool(static.html.strip())
    record["static_html"] = static.html if record["static_ok"] else ""
    record["static_url"] = static.url
    record["static_error"] = None if static.ok else static.error

    rendered = render_page(url, config=RenderConfig(timeout_ms=45_000))
    record["render_ok"] = rendered.ok
    # The post-collect outerHTML, markers included. A re-fetch would lose them and every
    # page would silently rebind zero geometry.
    record["rendered_html"] = rendered.html if rendered.ok else ""
    record["rendered_url"] = rendered.url
    record["render_error"] = rendered.error
    record["rects"] = (
        {k: {"x": v.x, "y": v.y, "width": v.width, "height": v.height}
         for k, v in rendered.rects.items()}
        if rendered.ok
        else {}
    )
    record["fetch_seconds"] = round(time.monotonic() - started, 1)

    target.write_text(json.dumps(record), encoding="utf-8")
    return {
        "url": url,
        "status": "ok" if (record["static_ok"] and record["render_ok"]) else "partial",
        "static_ok": record["static_ok"],
        "render_ok": record["render_ok"],
        "seconds": record["fetch_seconds"],
    }


def run_fetch(sites: list[str], cache: Path, concurrency: int) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    print(f"Fetching {len(sites)} sites both ways at concurrency {concurrency}.")
    print("Each site costs one HTTP fetch plus one Chromium render; expect a few minutes.\n")

    done = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for result in pool.map(lambda u: fetch_one(u, cache), sites):
            done += 1
            mark = {"ok": "  ok", "cached": "cach", "partial": "PART"}[result["status"]]
            extra = ""
            if result["status"] == "partial":
                extra = f"  static={result.get('static_ok')} render={result.get('render_ok')}"
            print(f"  [{done:>3}/{len(sites)}] {mark}  {result['url'][:64]}{extra}")

    print(f"\nCached in {cache}")


# ---------------------------------------------------------------------------
# Phase 2 -- rebuild documents from cache
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pair:
    url: str
    static_doc: Document
    rendered_doc: Document


def load_pair(path: Path) -> Pair | tuple[str, str]:
    """Rebuild both documents from a cache file, or return (url, reason) if impossible."""
    record = json.loads(path.read_text(encoding="utf-8"))
    url = record["url"]

    if not record.get("static_ok") or not record.get("render_ok"):
        reason = "static fetch failed" if not record.get("static_ok") else "render failed"
        return url, reason

    from webgraph.types import Rect

    try:
        static_doc = build_document(record["static_html"], record["static_url"] or url)
    except ValueError as exc:
        return url, f"static parse: {exc}"

    rects = {k: Rect(**v) for k, v in record["rects"].items()}
    geometry = geometry_by_xpath(record["rendered_html"], rects)
    try:
        rendered_doc = build_document(
            record["rendered_html"], record["rendered_url"] or url, geometry=geometry
        )
    except ValueError as exc:
        return url, f"rendered parse: {exc}"

    return Pair(url=url, static_doc=static_doc, rendered_doc=rendered_doc)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def first_positions(blocks: tuple[Block, ...] | list[Block]) -> dict[str, int]:
    """Key -> index of its first occurrence. Duplicate text collapses, as it does in the merge."""
    out: dict[str, int] = {}
    for index, block in enumerate(blocks):
        key = block_key(block)
        if key and key not in out:
            out[key] = index
    return out


def pairwise_accuracy(
    truth: dict[str, int],
    produced: dict[str, int],
    *,
    focus: set[str] | None = None,
    kind: str = "any",
    rng: random.Random,
) -> tuple[float, int]:
    """Share of key pairs whose relative order in `produced` matches `truth`.

    `focus` restricts scoring to pairs touching the blinded set. Without it the number is
    dominated by pairs of untouched blocks, whose order the merge preserves by construction --
    they would inflate every method, including the random baseline, toward 1.

    `kind` decomposes that further, and the decomposition is necessary rather than optional:

    - `cross` -- exactly one member blinded. **Was the run put in the right place?** This is
      the question the placement rule exists to answer.
    - `within` -- both members blinded. Only asks whether the run's own internal order
      survived, which every method that keeps static order gets right for free.
    - `any` -- the union of the two. At high blinding shares this is swamped by `within`
      pairs, because a contiguous run of 80% of the document has far more internal pairs
      than external ones. Reading `any` alone therefore credits a method for preserving an
      order it never had to decide, which is how append-end appears to overtake adjacency.
    """
    keys = [k for k in truth if k in produced]
    if len(keys) < 2:
        return 0.0, 0

    total = len(keys) * (len(keys) - 1) // 2
    if total <= MAX_PAIRS:
        pairs = [(keys[i], keys[j]) for i in range(len(keys)) for j in range(i + 1, len(keys))]
    else:
        pairs = []
        for _ in range(MAX_PAIRS):
            a, b = rng.sample(keys, 2)
            pairs.append((a, b))

    if focus is not None:
        if kind == "cross":
            pairs = [(a, b) for a, b in pairs if (a in focus) != (b in focus)]
        elif kind == "within":
            pairs = [(a, b) for a, b in pairs if a in focus and b in focus]
        else:
            pairs = [(a, b) for a, b in pairs if a in focus or b in focus]
    if not pairs:
        return 0.0, 0

    correct = 0
    for a, b in pairs:
        if (truth[a] < truth[b]) == (produced[a] < produced[b]):
            correct += 1
    return correct / len(pairs), len(pairs)


def order_disagreement(pair: Pair, rng: random.Random) -> float:
    """Share of shared-block pairs ordered differently by the two documents.

    Zero means the static and rendered documents agree on the order of everything they have
    in common -- on such a page any placement rule looks correct, so the benchmark's headline
    number must be read per bucket rather than in aggregate.
    """
    static_pos = first_positions(pair.static_doc.blocks)
    rendered_pos = first_positions(pair.rendered_doc.blocks)
    shared = set(static_pos) & set(rendered_pos)
    if len(shared) < 2:
        return 0.0
    accuracy, counted = pairwise_accuracy(
        {k: rendered_pos[k] for k in shared},
        {k: static_pos[k] for k in shared},
        rng=rng,
    )
    return 1.0 - accuracy if counted else 0.0


# ---------------------------------------------------------------------------
# Ablation and placement methods
# ---------------------------------------------------------------------------


def ablate(rendered: Document, victims: set[str]) -> Document:
    """Remove every block whose key is in `victims`.

    By key, not by object: `union_documents` decides what is static-only by comparing key
    sets, so leaving one same-keyed block behind means the ablated key stays in
    `rendered_keys` and the merge never treats it as static-only. The ablation would then
    silently do nothing and the page would score a perfect 1.0.
    """
    kept = tuple(b for b in rendered.blocks if block_key(b) not in victims)
    return rendered.model_copy(update={"blocks": kept})


def clustered_victims(
    shared_in_rendered_order: list[str], share: float, rng: random.Random
) -> set[str]:
    """Pick a contiguous run of shared keys, per the D66 clustering lesson."""
    count = max(1, int(len(shared_in_rendered_order) * share))
    if count >= len(shared_in_rendered_order):
        count = len(shared_in_rendered_order) - 1
    start = rng.randint(0, len(shared_in_rendered_order) - count)
    return set(shared_in_rendered_order[start : start + count])


def place_adjacency(static_doc: Document, rendered_ablated: Document) -> dict[str, int]:
    """The shipped rule. Calls the real `union_documents`, not a copy of it."""
    merged, _only_static, _only_rendered = union_documents(static_doc, rendered_ablated)
    return first_positions(merged.blocks)


def place_append_end(static_doc: Document, rendered_ablated: Document) -> dict[str, int]:
    """The pre-D67 implementation: everything static-only goes after everything else."""
    rendered_keys = {block_key(b) for b in rendered_ablated.blocks if b.text.strip()}
    order: list[Block] = list(rendered_ablated.blocks)
    seen: set[str] = set()
    for block in static_doc.blocks:
        key = block_key(block)
        if key and key not in rendered_keys and key not in seen:
            seen.add(key)
            order.append(block)
    return first_positions(order)


def place_random(
    static_doc: Document, rendered_ablated: Document, rng: random.Random
) -> dict[str, int]:
    """The floor. Static-only blocks inserted at uniformly random positions."""
    rendered_keys = {block_key(b) for b in rendered_ablated.blocks if b.text.strip()}
    order: list[Block] = list(rendered_ablated.blocks)
    seen: set[str] = set()
    for block in static_doc.blocks:
        key = block_key(block)
        if key and key not in rendered_keys and key not in seen:
            seen.add(key)
            order.insert(rng.randint(0, len(order)), block)
    return first_positions(order)


# ---------------------------------------------------------------------------
# Per-page experiment
# ---------------------------------------------------------------------------


@dataclass
class PageResult:
    url: str
    shared: int = 0
    static_only: int = 0
    rendered_only: int = 0
    disagreement: float = 0.0
    scores: dict[str, list[float]] = field(default_factory=dict)
    cross: dict[str, list[float]] = field(default_factory=dict)
    by_share: dict[float, dict[str, list[float]]] = field(default_factory=dict)
    by_share_cross: dict[float, dict[str, list[float]]] = field(default_factory=dict)
    ablation_no_ops: int = 0
    note: str = ""

    @property
    def anchor_density(self) -> float:
        """Real static-only blocks per shared block.

        The genuine difficulty measure for this rule, and higher than order disagreement on
        every hard page in the corpus. A page with 85 static-only blocks per anchor is asking
        the rule to place long runs against a single observed adjacency."""
        return self.static_only / self.shared if self.shared else float("inf")

    def mean(self, method: str) -> float:
        values = self.scores.get(method, [])
        return sum(values) / len(values) if values else 0.0

    def mean_cross(self, method: str) -> float:
        values = self.cross.get(method, [])
        return sum(values) / len(values) if values else 0.0


METHODS: Final[tuple[str, ...]] = ("adjacency", "append-end", "random")


def run_page(pair: Pair) -> PageResult:
    result = PageResult(url=pair.url)
    rng = random.Random(1234)

    static_pos = first_positions(pair.static_doc.blocks)
    truth = first_positions(pair.rendered_doc.blocks)
    shared = set(static_pos) & set(truth)

    result.shared = len(shared)
    result.static_only = len(set(static_pos) - set(truth))
    result.rendered_only = len(set(truth) - set(static_pos))

    if len(shared) < 8:
        result.note = "no usable shared blocks -- adjacency has nothing to anchor to"
        return result

    result.disagreement = order_disagreement(pair, rng)

    shared_ordered = [k for k, _ in sorted(
        ((k, truth[k]) for k in shared), key=lambda kv: kv[1]
    )]

    for method in METHODS:
        result.scores[method] = []
        result.cross[method] = []

    for share in ABLATION_SHARES:
        result.by_share.setdefault(share, {m: [] for m in METHODS})
        result.by_share_cross.setdefault(share, {m: [] for m in METHODS})
        for seed in SEEDS:
            local = random.Random(seed)
            victims = clustered_victims(shared_ordered, share, local)
            if not victims:
                continue
            ablated = ablate(pair.rendered_doc, victims)

            # The merge must actually see these as static-only. If it does not, the
            # ablation was a no-op and the page would score a meaningless 1.0.
            _merged, only_static, _only_rendered = union_documents(pair.static_doc, ablated)
            if only_static < len(victims):
                result.ablation_no_ops += 1
                continue

            for method in METHODS:
                if method == "adjacency":
                    produced = place_adjacency(pair.static_doc, ablated)
                elif method == "append-end":
                    produced = place_append_end(pair.static_doc, ablated)
                else:
                    produced = place_random(
                        pair.static_doc, ablated, random.Random(seed * 7919)
                    )

                accuracy, counted = pairwise_accuracy(
                    truth, produced, focus=victims, rng=local
                )
                if counted:
                    result.scores[method].append(accuracy)
                    result.by_share[share][method].append(accuracy)

                cross_acc, cross_n = pairwise_accuracy(
                    truth, produced, focus=victims, kind="cross", rng=local
                )
                if cross_n:
                    result.cross[method].append(cross_acc)
                    result.by_share_cross[share][method].append(cross_acc)

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def bucket_of(disagreement: float) -> str:
    for label, low, high in DISAGREEMENT_BUCKETS:
        if low <= disagreement < high:
            return label
    return DISAGREEMENT_BUCKETS[-1][0]


def report(results: list[PageResult], skipped: list[tuple[str, str]]) -> dict[str, Any]:
    scored = [r for r in results if r.scores.get("adjacency")]
    no_anchor = [r for r in results if r.note]

    print("\n" + "=" * 84)
    print("UNION BY ADJACENCY -- placement accuracy against the rendered document's order")
    print("=" * 84)

    print(f"\n  Sites in corpus        {len(results) + len(skipped)}")
    print(f"  Fetched both ways      {len(results)}")
    print(f"  Scored                 {len(scored)}")
    print(f"  No shared blocks       {len(no_anchor)}   <- adjacency has nothing to anchor to")
    if skipped:
        print(f"  Unusable               {len(skipped)}")

    if not scored:
        print("\n  Nothing to score.")
        return {"scored": 0}

    print("\n  PER PAGE  (mean pairwise order accuracy over pairs involving a blinded block)")
    print("  'anch/blk' is static-only blocks per shared block -- the real difficulty measure.")
    print("  Scores are CROSS pairs only: exactly one member blinded, i.e. placement accuracy.")
    print(f"\n    {'page':<30} {'disagr':>7} {'shared':>7} {'st-only':>8} {'per-anch':>9}"
          f" {'adjac':>7} {'append':>7} {'random':>7}")
    print("    " + "-" * 87)
    for r in sorted(scored, key=lambda r: -r.anchor_density):
        host = re.sub(r"^https?://(www\.)?", "", r.url)[:29]
        print(
            f"    {host:<30} {r.disagreement:>7.3f} {r.shared:>7} {r.static_only:>8}"
            f" {r.anchor_density:>9.1f} "
            f"{r.mean_cross('adjacency'):>7.3f} {r.mean_cross('append-end'):>7.3f}"
            f" {r.mean_cross('random'):>7.3f}"
        )

    print("\n  BY ORDER DISAGREEMENT")
    print("  A page whose two documents agree on order scores high under any rule. Only the")
    print("  lower rows carry evidence about the placement decision.")
    print(f"\n    {'bucket':<16} {'pages':>6} {'adjacency':>11} {'append-end':>11} {'random':>9}")
    print("    " + "-" * 58)

    buckets: dict[str, list[PageResult]] = {label: [] for label, _, _ in DISAGREEMENT_BUCKETS}
    for r in scored:
        buckets[bucket_of(r.disagreement)].append(r)

    bucket_out: dict[str, Any] = {}
    for label, _, _ in DISAGREEMENT_BUCKETS:
        rows = buckets[label]
        if not rows:
            print(f"    {label:<16} {0:>6}           --          --        --")
            continue
        means = {m: sum(r.mean(m) for r in rows) / len(rows) for m in METHODS}
        bucket_out[label] = {"pages": len(rows), **{m: round(means[m], 4) for m in METHODS}}
        print(
            f"    {label:<16} {len(rows):>6} {means['adjacency']:>11.3f} "
            f"{means['append-end']:>11.3f} {means['random']:>9.3f}"
        )

    print("\n  BY ABLATION SHARE")
    print("  CROSS = pairs with exactly one blinded member: was the run PLACED correctly?")
    print("  ANY   = also counts blinded-vs-blinded pairs, which every order-preserving")
    print("          method gets right for free. At high shares ANY is swamped by them.")
    print(f"\n    {'blinded':<9} {'--------- cross ---------':^27} {'---------- any ----------':^27}")
    print(f"    {'':<9} {'adjac':>8} {'append':>8} {'rand':>8}  {'adjac':>8} {'append':>8} {'rand':>8}")
    print("    " + "-" * 63)
    share_out: dict[str, Any] = {}
    for share in ABLATION_SHARES:
        rows = [r for r in scored if r.by_share.get(share, {}).get("adjacency")]
        xrows = [r for r in scored if r.by_share_cross.get(share, {}).get("adjacency")]
        if not rows:
            continue
        means = {
            m: sum(sum(r.by_share[share][m]) / len(r.by_share[share][m]) for r in rows) / len(rows)
            for m in METHODS
        }
        xmeans = {
            m: (sum(sum(r.by_share_cross[share][m]) / len(r.by_share_cross[share][m])
                    for r in xrows) / len(xrows)) if xrows else 0.0
            for m in METHODS
        }
        share_out[f"{share:.2f}"] = {
            "cross": {m: round(xmeans[m], 4) for m in METHODS},
            "any": {m: round(means[m], 4) for m in METHODS},
        }
        print(
            f"    {share:>6.0%}   {xmeans['adjacency']:>8.3f} {xmeans['append-end']:>8.3f}"
            f" {xmeans['random']:>8.3f}  {means['adjacency']:>8.3f} {means['append-end']:>8.3f}"
            f" {means['random']:>8.3f}"
        )

    overall = {m: sum(r.mean(m) for r in scored) / len(scored) for m in METHODS}
    xscored = [r for r in scored if r.cross.get("adjacency")]
    overall_cross = {
        m: sum(r.mean_cross(m) for r in xscored) / len(xscored) for m in METHODS
    } if xscored else {m: 0.0 for m in METHODS}

    print("\n  OVERALL")
    print(f"    {'':<14} {'cross':>9} {'any':>9}")
    for method in METHODS:
        print(f"    {method:<14} {overall_cross[method]:>9.4f} {overall[method]:>9.4f}")
    print(f"\n    adjacency - append-end   cross {overall_cross['adjacency'] - overall_cross['append-end']:+.4f}"
          f"   any {overall['adjacency'] - overall['append-end']:+.4f}")

    print("\n  CORPUS SHAPE")
    shares = [r.static_only / max(r.static_only + r.shared, 1) for r in scored]
    print(f"    Median static-only share of the static document   {median(shares):.1%}")
    print(f"    Median shared blocks per page                     {median([r.shared for r in scored]):.0f}")
    densities = sorted(r.anchor_density for r in scored)
    print(f"    Median static-only blocks per anchor              {median(densities):.1f}")
    print(f"    Worst                                             {densities[-1]:.1f}")
    no_ops = sum(r.ablation_no_ops for r in results)
    if no_ops:
        print(f"    Ablation no-ops discarded                         {no_ops}")

    if no_anchor:
        print("\n  PAGES WITH NO SHARED BLOCKS  (merge falls back to end-placement by design)")
        for r in no_anchor:
            print(f"    {re.sub(r'^https?://(www\\.)?', '', r.url)[:60]}"
                  f"   shared={r.shared} static-only={r.static_only}")

    if skipped:
        print("\n  UNUSABLE")
        for url, reason in skipped:
            print(f"    {re.sub(r'^https?://(www\\.)?', '', url)[:52]:<54} {reason}")

    return {
        "scored": len(scored),
        "overall_cross": {m: round(overall_cross[m], 4) for m in METHODS},
        "overall_any": {m: round(overall[m], 4) for m in METHODS},
        "by_bucket": bucket_out,
        "by_share": share_out,
        "no_shared_blocks": [r.url for r in no_anchor],
        "pages": [
            {
                "url": r.url,
                "disagreement": round(r.disagreement, 4),
                "shared": r.shared,
                "static_only": r.static_only,
                "anchor_density": round(r.anchor_density, 2),
                **{m: round(r.mean_cross(m), 4) for m in METHODS},
                **{f"{m}_any": round(r.mean(m), 4) for m in METHODS},
            }
            for r in scored
        ],
    }


def run_score(cache: Path, json_out: Path | None) -> None:
    files = sorted(cache.glob("*.json"))
    if not files:
        print(f"No cache in {cache}. Run the fetch phase first.", file=sys.stderr)
        raise SystemExit(1)

    results: list[PageResult] = []
    skipped: list[tuple[str, str]] = []

    print(f"Scoring {len(files)} cached pages offline.")
    for path in files:
        loaded = load_pair(path)
        if isinstance(loaded, tuple):
            skipped.append(loaded)
            continue
        results.append(run_page(loaded))

    payload = report(results, skipped)
    if json_out:
        json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\n  Wrote {json_out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["fetch", "score"])
    parser.add_argument("--sites", type=Path, default=DEFAULT_SITES)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=4,
                        help="parallel fetches; each holds a Chromium (default 4)")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    if args.phase == "fetch":
        run_fetch(load_sites(args.sites, args.limit), args.cache, args.concurrency)
    else:
        run_score(args.cache, args.json)


if __name__ == "__main__":
    main()
