r"""Score this engine on Zyte's `article-extraction-benchmark` against 34 other systems.

What this measures, and what it does not
----------------------------------------
The corpus is 181 cached news and blog pages with a hand-checked `articleBody` for each. The
metric is 4-gram shingle TP/FP/FN, normalised per document so a long page does not outweigh a
short one, then macro-averaged into precision, recall and F1. A second figure, `accuracy`, is
the share of pages whose token sequence matches the ground truth *exactly*.

This is an **article-body** benchmark. This engine is not an article-body extractor: it turns
a whole page into ordered, typed blocks and keeps everything a reader would see, chrome
included. Scoring it here answers one narrow question -- how much of what it keeps is article
prose -- and nothing about whether the block structure is right. Read the recall column, then
read the precision column, and do not average them into a verdict.

The comparison trap
-------------------
Compare like with like. The first version of the sibling `content_quality` measurement
reported danluu.com as "51.8% of content missing" because trafilatura had been called with
`include_links=True`, inflating its character count with `[text](url)`, while the engine
emitted no links at all. Plain against plain, the two agreed to 98%.

Zyte's `articleBody` is **plain text**. So every variant here is built from block `.text`,
never `.rich_text` and never `to_markdown()`.

Be precise about why that matters, because half the intuition is wrong. `evaluate.py`
tokenises with `re.compile(r'\w+')`, so Markdown *punctuation* is invisible to the metric:
`1 | Kyle Busch | 5040` and `1 Kyle Busch 5040` tokenise identically, and `##` in front of a
heading costs nothing. What is **not** invisible is the text Markdown adds. A link rendered
as `[iFixit](https://www.ifixit.com/News/16-inch-macbook-pro)` contributes `https`,
`www`, `ifixit`, `com`, `News` and every URL slug word as real tokens the ground truth does
not have -- false positives on each shingle they touch, in the middle of otherwise correct
prose. Same for image `src` paths. That is the trap, and `.text` avoids it.

The four variants
-----------------
Reported together, always. Picking the best one and calling it "the" number is the same
mistake as the link trap, one level up.

- `webgraph_raw`         -- `document.text`, everything the engine kept.
- `webgraph_landmarks`   -- `strip_landmarks()`: drops `<nav>` and `<footer>` blocks. Single
                            page, no corpus, so it is what a one-shot caller actually gets.
- `webgraph_prose`       -- PARAGRAPH/HEADING/LIST_ITEM/QUOTE only. Tables, images, code and
                            captions are excluded because the ground truth is prose.
- `webgraph_prose_landmarks` -- both filters. The closest thing to an article extractor this
                            engine can be talked into without touching `src/`.

The empty-prediction asymmetry
------------------------------
`evaluate.py` averages precision only over documents where `tp + fp > 0`, but recall over
documents where `tp + fn > 0`. An empty `articleBody` therefore vanishes from the precision
mean while still scoring recall 0 -- so a page that crashes and falls back to `""` *raises*
the reported precision. This script counts failures and empties and prints them next to the
scores; a non-zero count means the precision figure needs an asterisk.

Usage
-----
    git clone https://github.com/scrapinghub/article-extraction-benchmark  # 181 pages, MIT
    uv run --package webgraph python benchmark/article_extraction/run.py \\
        --corpus path/to/article-extraction-benchmark
    cd path/to/article-extraction-benchmark && python3 evaluate.py

`evaluate.py` has no dependencies and scores every `output/*.json` it finds, so the engine's
four rows land in the same table as the 34 systems already there.

`--ablate` scores each block-kind exclusion separately; `--oracle` reports the ceiling for
main-content selection over the engine's existing blocks. Both live here rather than in a
throwaway script because the README quotes them, and a quoted number nobody can re-derive is
a rumour.

**Pin the source before quoting a score.** The first pass of this measurement ran against a
working tree that another change was landing in, and a 377-line edit to the DOM layer moved
`webgraph_raw` from 0.623 to 0.643 mid-run. To reproduce a published figure:

    git archive HEAD | tar -x -C /tmp/pinned
    PYTHONPATH=/tmp/pinned/packages/engine/src uv run --package webgraph python \\
        benchmark/article_extraction/run.py --corpus <checkout>
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from webgraph.types import Block

PROSE_KINDS: Final[tuple[str, ...]] = ("paragraph", "heading", "list-item", "quote")
"""Block kinds that can plausibly appear in a plain-text `articleBody`.

Excludes IMAGE (alt text is not body copy), CODE, FIGURE_CAPTION and TABLE.

**The TABLE exclusion is not merely weak, it is negative.** Ablated one kind at a time on
top of `strip_landmarks`, the four exclusions are worth:

    image    +0.018 F1
    caption  +0.005
    code     +0.000
    table    -0.004

So the whole +0.020 that `webgraph_prose_landmarks` gains comes from dropping IMAGE alt text
and figure captions. Dropping tables *loses* F1. The original worry -- that `|` separators
would not match a ground truth written without them -- was simply wrong: the metric tokenises
on `\\w+`, so separators are invisible and the cells match fine. On autoracing.com.br's NASCAR
standings, where the table *is* the article, the exclusion takes the page from F1 0.756 to
0.187 and nothing anywhere pays that back.

Kept as-is so the reported variant matches the definition it is published under, and because
a wrong number that is measured beats a right number that is asserted. A block-kind filter is
the wrong instrument regardless -- it cannot tell a standings table from a nav table. The
README says what the right one is.
"""


def join(blocks: Iterable[Block]) -> str:
    """The same join `Document.text` uses, so variants differ only by which blocks survive."""
    return "\n\n".join(b.text for b in blocks if b.text.strip())


def variants(blocks: Sequence[Block]) -> dict[str, str]:
    """All four texts from one parse.

    Built from a single `Document` on purpose: re-parsing per variant would be four times the
    work and would let a non-deterministic parse make the variants incomparable.
    """
    from webgraph.boilerplate import strip_landmarks

    kept = strip_landmarks(blocks)
    prose = [b for b in blocks if b.kind.value in PROSE_KINDS]
    prose_kept = [b for b in kept if b.kind.value in PROSE_KINDS]
    return {
        "webgraph_raw": join(blocks),
        "webgraph_landmarks": join(kept),
        "webgraph_prose": join(prose),
        "webgraph_prose_landmarks": join(prose_kept),
    }


def _metric(corpus: Path):
    """Borrow `evaluate.py`'s scorer instead of reimplementing it.

    It has no dependencies and it is the arbiter for the published numbers, so scoring the
    side analyses with anything else would make them incomparable to the leaderboard.
    """
    sys.path.insert(0, str(corpus.resolve()))
    from evaluate import metrics_from_tp_fp_fns, string_shingle_matching

    return string_shingle_matching, metrics_from_tp_fp_fns


def _pages(corpus: Path, limit: int | None):
    """Yield `(key, ground-truth body, blocks)` for each page, parsed once."""
    from webgraph.pipeline import build_document

    ground_truth = json.loads((corpus / "ground-truth.json").read_text(encoding="utf8"))
    keys = sorted(ground_truth)[:limit] if limit else sorted(ground_truth)
    for key in keys:
        with gzip.open(corpus / "html" / f"{key}.html.gz", "rt", encoding="utf8") as handle:
            html = handle.read()
        yield (
            key,
            ground_truth[key]["articleBody"],
            build_document(html, ground_truth[key].get("url", "")).blocks,
        )


def ablate(corpus: Path, *, limit: int | None = None) -> None:
    """Score each block-kind exclusion separately, on top of `strip_landmarks`.

    Written because the assumption it tests turned out to be false. The TABLE exclusion was
    justified on the theory that `|` separators would not match a separator-free ground truth;
    the metric tokenises on `\\w+`, so they are invisible, and excluding tables *loses* F1.
    Every kind filter in this file is therefore reported by measurement, not by argument.
    """
    from webgraph.boilerplate import strip_landmarks

    shingle, aggregate = _metric(corpus)
    drops: dict[str, set[str]] = {
        "none": set(),
        "minus IMAGE": {"image"},
        "minus FIGURE_CAPTION": {"figure-caption"},
        "minus CODE": {"code"},
        "minus TABLE": {"table"},
        "minus IMAGE+CAPTION": {"image", "figure-caption"},
        "minus all four (prose)": {"image", "figure-caption", "code", "table"},
    }
    scores: dict[str, list[tuple[float, float, float]]] = {name: [] for name in drops}
    for _key, true, blocks in _pages(corpus, limit):
        kept = strip_landmarks(blocks)
        for name, drop in drops.items():
            text = join(b for b in kept if b.kind.value not in drop)
            scores[name].append(shingle(true=true, pred=text))

    base = aggregate(scores["none"])["f1"]
    print(f"\n{'exclusion':<26}{'F1':>8}{'P':>8}{'R':>8}{'delta':>9}")
    for name, entries in scores.items():
        m = aggregate(entries)
        delta = "" if name == "none" else f"{m['f1'] - base:+.3f}"
        print(f"{name:<26}{m['f1']:>8.3f}{m['precision']:>8.3f}{m['recall']:>8.3f}{delta:>9}")


def oracle(corpus: Path, *, limit: int | None = None, stride_divisor: int = 60) -> None:
    """Best contiguous run of the engine's own blocks per page, chosen using the answer.

    This is a **ceiling, not a forecast**. It asks one question: is the article body present
    as a contiguous span of blocks the engine already produces? If it is, the gap to the
    leaderboard is main-content *selection* and nothing about extraction has to change. A
    real heuristic, which cannot see the ground truth, lands materially below this.

    Start and end candidates are sampled on a stride rather than exhaustively, so the figure
    is itself a lower bound on the true best window.

    Runs over the *unfiltered* block list -- no landmark strip, no kind filter -- so that the
    only thing being credited is selection.
    """
    shingle, aggregate = _metric(corpus)
    # `metrics_from_tp_fp_fns` divides by (precision + recall), which is zero for a window
    # that overlaps the article not at all -- common, since most windows are pure chrome.
    from evaluate import precision_score, recall_score

    def page_f1(entry: tuple[float, float, float]) -> float:
        p, r = precision_score(*entry), recall_score(*entry)
        return 2 * p * r / (p + r) if p + r else 0.0

    best_per_page: list[tuple[float, float, float]] = []
    for _key, true, raw_blocks in _pages(corpus, limit):
        blocks = [b for b in raw_blocks if b.text.strip()]
        count = len(blocks)
        stride = max(1, count // stride_divisor)
        best, best_f1 = (0.0, 1.0, 0.0), -1.0
        for start in range(0, count, stride):
            for end in range(start + 1, count + 1, stride):
                entry = shingle(true=true, pred=join(blocks[start:end]))
                f1 = page_f1(entry)
                if f1 > best_f1:
                    best_f1, best = f1, entry
        best_per_page.append(best)

    m = aggregate(best_per_page)
    print(
        f"\noracle contiguous-block window (stride 1/{stride_divisor}, so a LOWER bound):\n"
        f"  F1={m['f1']:.3f}  P={m['precision']:.3f}  R={m['recall']:.3f}\n"
        "  A ceiling on what selection over these blocks could reach -- not a prediction."
    )


def run(corpus: Path, *, limit: int | None = None) -> None:
    from webgraph.pipeline import build_document

    ground_truth = json.loads((corpus / "ground-truth.json").read_text(encoding="utf8"))
    keys = sorted(ground_truth)[:limit] if limit else sorted(ground_truth)

    outputs: dict[str, dict[str, dict[str, str]]] = {name: {} for name in variants(())}
    failures: list[tuple[str, str]] = []
    empties: dict[str, int] = dict.fromkeys(outputs, 0)
    started = time.time()

    for index, key in enumerate(keys, start=1):
        url = ground_truth[key].get("url", "")
        try:
            with gzip.open(corpus / "html" / f"{key}.html.gz", "rt", encoding="utf8") as handle:
                html = handle.read()
            texts = variants(build_document(html, url).blocks)
        except Exception as exc:  # noqa: BLE001 -- a crash is a result, not a reason to stop
            failures.append((key, f"{type(exc).__name__}: {exc}"))
            texts = dict.fromkeys(outputs, "")
        for name, text in texts.items():
            outputs[name][key] = {"articleBody": text}
            if not text.strip():
                empties[name] += 1
        if index % 25 == 0 or index == len(keys):
            print(f"  {index}/{len(keys)}  {time.time() - started:.0f}s", file=sys.stderr)

    version = _version()
    for name, output in outputs.items():
        path = corpus / "output" / f"{name}.json"
        path.write_text(json.dumps({"version": version, "output": output}), encoding="utf8")
        print(f"wrote {path}  ({empties[name]} empty of {len(output)})")

    _report_duplication(outputs["webgraph_prose_landmarks"])

    if failures:
        print(f"\n{len(failures)} page(s) failed to parse -- PRECISION IS OVERSTATED:")
        for key, error in failures:
            print(f"  {key}  {error}")
        print(
            "evaluate.py drops tp==fp==0 documents from the precision mean but keeps them in\n"
            "the recall mean, so every empty prediction is a free precision point."
        )


def _report_duplication(output: dict[str, dict[str, str]]) -> None:
    """Share of emitted characters that repeat a block already emitted on the same page.

    A distinct precision leak from chrome: some pages emit a comment or list entry twice, once
    whole and once split into its parts. The metric counts shingles with multiplicity, so the
    second copy is pure false positive. Reported on every run rather than measured once,
    because a number quoted in the README that nobody can re-derive is a rumour.
    """
    total = duplicated = heavy = 0
    for entry in output.values():
        blocks = [b for b in entry["articleBody"].split("\n\n") if b.strip()]
        seen: set[str] = set()
        page_dup = 0
        for block in blocks:
            key = " ".join(block.split()).casefold()
            if key in seen:
                page_dup += len(block)
            seen.add(key)
        page_total = sum(len(b) for b in blocks)
        total += page_total
        duplicated += page_dup
        if page_total and page_dup / page_total > 0.25:
            heavy += 1
    share = 100 * duplicated / total if total else 0.0
    print(
        f"\nduplicate block text in webgraph_prose_landmarks: {share:.1f}% of output chars, "
        f"{heavy} of {len(output)} pages over 25%"
    )


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("webgraph")
    except PackageNotFoundError:
        return "dev"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="checkout of scrapinghub/article-extraction-benchmark",
    )
    parser.add_argument("--limit", type=int, help="score only the first N pages, for a smoke run")
    parser.add_argument(
        "--ablate",
        action="store_true",
        help="score each block-kind exclusion separately instead of writing output",
    )
    parser.add_argument(
        "--oracle",
        action="store_true",
        help="ceiling for main-content selection over the engine's existing blocks",
    )
    args = parser.parse_args()
    if not (args.corpus / "ground-truth.json").is_file():
        parser.error(f"{args.corpus} is not an article-extraction-benchmark checkout")
    if args.ablate:
        ablate(args.corpus, limit=args.limit)
    elif args.oracle:
        oracle(args.corpus, limit=args.limit)
    else:
        run(args.corpus, limit=args.limit)
