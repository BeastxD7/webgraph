"""Score the engine on the Webis Web Content Extraction Benchmark (Bevendorff et al., 2023).

Why this benchmark
------------------
Every other extraction benchmark this repo runs was assembled by somebody with a system in
the comparison. WCXB's author wrote rs-trafilatura, which tops WCXB. Firecrawl's benchmark
is Firecrawl's. Trafilatura's evaluation is run by trafilatura's maintainer. Those corpora
are still useful and this repo still runs them, but none of them is independent evidence.

WCEB is. It is a SIGIR 2023 reproducibility study by a group with no extractor in the field:
Janek Bevendorff, Sanket Gupta, Johannes Kiesel and Benno Stein at Bauhaus-Universitat
Weimar / Leipzig. They took **eight existing annotated datasets** -- CleanEval, Dragnet,
CETD, L3S-GN1, Google-Trends-2017, Readability, Scrapinghub and CleanPortalEval -- converted
them to one format, and ran twenty-two extractors over all 3,985 pages with one metric. The
per-page scores for all twenty-two are published as CSVs in the repository, which is why the
baseline columns below are *computed from the authors' own files* rather than transcribed
from the paper: this runner reads `outputs/metrics-computed/rouge/<dataset>/rouge_<model>.csv`
and averages it the same way it averages ours.

    git clone https://github.com/chatnoir-eu/web-content-extraction-benchmark
    cd web-content-extraction-benchmark/datasets && tar xf combined.tar.xz
    cd ../outputs && tar xf metrics-computed.tar.xz

The metric, and why it is reconstructed rather than imported
------------------------------------------------------------
WCEB scores **ROUGE-LSum F1** over whitespace tokens: union longest-common-subsequence
between the extracted plain text and the annotated plain text, sentence-split on both sides.
It rewards keeping the right words *in the right order* and is far less forgiving of
reordering than the bag-of-words F1 that WCXB and Zyte use.

`benchmark/wcxb/run.py` imports the corpus's own `evaluate.py` and argues there that
reimplementing a metric forks it. The same instinct applies here, and the same instinct is
why this file does *not* simply `from extraction_benchmark.eval import rouge_eval`: that
module imports `Levenshtein` at module scope, which is GPL-2.0, and this repo's `bench`
dependency group already documents a deliberate refusal to pull it in. So the compromise is:

* the **tokenizer is imported** from upstream (`extraction_benchmark.util.tokenize_ws`);
* the six lines of `rouge_eval` that construct the scorer and apply its empty-target rule
  are restated here, character for character against upstream;
* and `--validate` rescores upstream's own extractor outputs and diffs the result against
  upstream's own per-page CSVs, printing both the per-page deviation distribution and the
  aggregate disagreement.

Run `--validate` before believing any number this file prints; it is the only reason to
trust a restated metric at all. Expect the per-page agreement to be close but not exact, and
read AGREEMENT_TOLERANCE for why that is a fact about the corpus's age and not about this
file: side by side in one process, this restatement and upstream's own `rouge_eval` agree
exactly, and the residual is upstream's code disagreeing with upstream's published CSVs.

Why plain text and not Markdown
--------------------------------
ROUGE-LSum tokenizes on whitespace after lowercasing and stripping non-alphanumerics. Every
piece of Markdown syntax that survives that -- a link target's path segments, a heading's
hashes, a table's pipes -- enters the token stream as content the annotator never wrote and
is charged as a precision loss. `document.text` is the fair input.

What this benchmark cannot see
-------------------------------
The corpus is cached HTML with no network, so geometric reading order is unavailable and
every page falls back to DOM order; the run prints the `reading_order_method` distribution
rather than asserting it. Cross-page chrome detection needs several pages from one site and
the corpus is one page per URL, so that is structurally unavailable too. What is left is the
single-page half of the engine, which is what the four variants below measure.

Usage
-----
    uv run --package webgraph python benchmark/wceb/run.py --corpus /path/to/clone --validate
    uv run --package webgraph python benchmark/wceb/run.py --corpus /path/to/clone
    uv run --package webgraph python benchmark/wceb/run.py --corpus … -d cleaneval -d dragnet

Needs `rouge-score` (Apache-2.0) importable. It is not an engine dependency.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from webgraph.types import blocks_text

VARIANTS: Final[tuple[str, ...]] = tuple(
    os.environ.get(
        "WCEB_VARIANTS", "raw,landmarks,prose,main,boundary,boundary+comments,model"
    ).split(",")
)
"""The columns to score. `WCEB_VARIANTS=main,boundary` skips the diagnostic ones; ROUGE-LSum
over 3,985 pages costs about twenty minutes per column on eight cores.

`boundary+comments` is the production path's `content` with its `comments` appended -- the
two fields the API returns, joined. Dragnet and cetd count a page's comment thread as
content, so this is the like-for-like number on those two corpora and an over-count on the
six that do not; it is reported, not ranked."""
"""The four ways to turn a parsed document into text, in increasing order of how much they
throw away.

`raw` is `document.text` -- every block the parser found, in reading order, which is the
engine's actual promise. `landmarks` drops `<nav>` and `<footer>` subtrees; it is the shipped
single-page default. `prose` keeps only PARAGRAPH, HEADING, LIST_ITEM and QUOTE. `main` is
`strip_landmarks` followed by `select_main_content`, the Kadane maximum-subarray selector in
`webgraph.main_content`, which is opt-in precisely because it breaks the no-loss promise.

Reporting all four is the point. They form a precision/recall ladder, and the interesting
question is not which wins overall but *where each wins* -- `main` was tuned on articles
(`block_cost = 15.0` was swept on Zyte's 181 article pages) and its own docstring flags it
as unvalidated elsewhere. WCEB's eight datasets are not all articles, so the per-dataset
table below is the finding and the pooled row is the headline.
"""

PROSE_KINDS: Final[frozenset[str]] = frozenset(
    {"paragraph", "heading", "list-item", "quote"}
)

DATASETS: Final[tuple[str, ...]] = (
    "cleaneval",
    "cleanportaleval",
    "cetd",
    "dragnet",
    "google-trends-2017",
    "l3s-gn1",
    "readability",
    "scrapinghub",
)

BASELINES: Final[tuple[str, ...]] = (
    "resiliparse",
    "trafilatura",
    "boilerpipe",
    "readability",
    "justext",
    "bs4",
)
"""The five systems the paper's abstract names, plus `bs4` as the floor.

`bs4` is BeautifulSoup's `get_text()` -- no extraction at all, the whole document flattened.
It is the honest comparison for the engine's `raw` variant, which is also "keep everything",
and the gap between them is how much the engine's parsing alone is worth before any
boilerplate policy is applied.
"""

VALIDATION_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("cleaneval", "trafilatura"),
    ("cleaneval", "resiliparse"),
    ("scrapinghub", "readability"),
)


# --------------------------------------------------------------------------------------
# The metric


def _scorer() -> Any:
    """Build upstream's ROUGE scorer with upstream's own tokenizer and parameters.

    Kept in one function so `--validate` and the real run cannot drift apart. The clone's
    `src` is put on the path here rather than in `__main__` because macOS spawns worker
    processes instead of forking them: a `sys.path` edit made under `if __name__ ==
    "__main__"` never reaches a worker, and the run would die on the first scored page.
    `$WCEB_CORPUS` is inherited by workers, so deriving the path from it does reach them.
    """
    clone = os.environ.get("WCEB_CORPUS")
    if clone and str(Path(clone) / "src") not in sys.path:
        sys.path.insert(0, str(Path(clone) / "src"))
    from extraction_benchmark.util import tokenize_ws
    from rouge_score import rouge_scorer, tokenizers

    class Tokenizer(tokenizers.Tokenizer):  # upstream extraction_benchmark.eval.Tokenizer
        def tokenize(self, text: str) -> list[str]:
            return tokenize_ws(text)

    return rouge_scorer.RougeScorer(
        ["rougeLsum"], use_stemmer=False, split_summaries=True, tokenizer=Tokenizer()
    )


_SCORER: Any = None


def rouge(target: str, pred: str) -> tuple[float, float, float]:
    """Precision, recall and F1 for one page, restating `extraction_benchmark.eval.rouge_eval`.

    The empty-target branch is upstream's and matters more than it looks: WCEB annotates a
    page with no main content as the empty string, and upstream awards recall 1.0 there --
    and precision and F1 too, but only to an extractor that also returned nothing. An
    extractor that emits text on such a page scores 0.0 and cannot avoid it.
    """
    global _SCORER
    if _SCORER is None:
        _SCORER = _scorer()
    score = _SCORER.score(target, pred)["rougeLsum"]
    precision, recall, f1 = score.precision, score.recall, score.fmeasure
    if not target.strip():
        recall = 1.0
        if not pred.strip():
            precision, f1 = 1.0, 1.0
    return precision, recall, f1


AGREEMENT_TOLERANCE: Final[float] = 5e-4
"""How far the aggregate F1 may drift before the restated metric is a different metric.

The per-page maximum is deliberately *not* the criterion, and the reason was measured rather
than assumed. Running upstream's own `extraction_benchmark.eval.rouge_eval` beside the
restatement below, in one process over 250 CleanEval pages, the two agree to **0.000e+00**:
the restatement is not merely equivalent to upstream's function, it is the same computation.
The residual disagreement is between upstream's own code and upstream's own published CSVs
-- 7 pages in 250, up to 1.4e-03 -- which is the corpus's three-year-old scores meeting a
2026 `rouge-score`/NLTK install, not anything this file does. Scrapinghub shows no
disagreement at all, so it is specific to some pages and not a global shift.

What must therefore agree is the aggregate, because that is what any comparison is made of,
and it does: 0.85462 against a published 0.85461. Half a thousandth of F1 is an order of
magnitude below the narrowest gap in the published field.
"""


def validate(corpus: Path, *, limit: int | None = None) -> bool:
    """Rescore upstream's own extractor outputs and diff against upstream's own CSVs.

    Upstream ships `outputs/model-outputs.tar.xz` (what each extractor produced) beside
    `outputs/metrics-computed.tar.xz` (what those outputs scored). Running the first through
    this file's metric must reproduce the second. Both the per-page distribution and the
    aggregate are printed, because they answer different questions: the distribution says
    whether any page is scored differently at all, and the aggregate says whether it matters
    to a published number. The verdict is taken on the aggregate -- see AGREEMENT_TOLERANCE.
    """
    print("validating the metric against upstream's published per-page scores")
    print(f"  {'dataset':<12} {'model':<12} {'N':>5} {'mean|d|':>10} {'p99|d|':>10} "
          f"{'max|d|':>10} {'F1 ours':>9} {'F1 theirs':>10} {'delta':>10}")
    print(f"  {'-' * 92}")
    worst_aggregate = 0.0
    for dataset, model in VALIDATION_PAIRS:
        truth = _ground_truth(corpus, dataset)
        published: dict[str, tuple[float, float, float]] = {}
        path = corpus / "outputs" / "metrics-computed" / "rouge" / dataset / f"rouge_{model}.csv"
        if not path.exists():
            print(f"  {dataset}/{model}: no published CSV at {path} -- skipped")
            continue
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                published[row["hash_key"]] = (
                    float(row["prec"]), float(row["rec"]), float(row["f1"])
                )
        outputs = _model_output(corpus, dataset, model)
        if outputs is None:
            print(f"  {dataset}/{model}: no model output jsonl -- skipped")
            continue
        deviations: list[float] = []
        ours_f1: list[float] = []
        theirs_f1: list[float] = []
        for page_id, text in sorted(outputs.items()):
            if page_id not in truth or page_id not in published:
                continue
            if limit and len(deviations) >= limit:
                break
            ours = rouge(truth[page_id][0], text)
            deviations.append(max(abs(a - b) for a, b in zip(ours, published[page_id])))
            ours_f1.append(ours[2])
            theirs_f1.append(published[page_id][2])
        if not deviations:
            continue
        ordered = sorted(deviations)
        p99 = ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))]
        mine, theirs = _mean(ours_f1), _mean(theirs_f1)
        delta = abs(mine - theirs)
        worst_aggregate = max(worst_aggregate, delta)
        print(
            f"  {dataset:<12} {model:<12} {len(deviations):>5} {_mean(deviations):>10.2e} "
            f"{p99:>10.2e} {ordered[-1]:>10.2e} {mine:>9.5f} {theirs:>10.5f} {delta:>10.2e}"
        )
    ok = worst_aggregate < AGREEMENT_TOLERANCE
    print(f"  worst aggregate F1 disagreement: {worst_aggregate:.2e} -> "
          f"{'MATCH' if ok else 'MISMATCH'} (tolerance {AGREEMENT_TOLERANCE:.0e})")
    return ok


def _model_output(corpus: Path, dataset: str, model: str) -> dict[str, str] | None:
    """Upstream's own output for one extractor, from wherever the clone keeps it."""
    for candidate in (
        corpus / "outputs" / "model-outputs" / dataset / f"{model}.jsonl",
        corpus / "model-outputs" / dataset / f"{model}.jsonl",
        corpus.parent / "keep" / f"{model}.jsonl",
    ):
        if candidate.exists():
            return {
                row["page_id"]: row.get("plaintext") or ""
                for row in _read_jsonl(candidate)
            }
    return None


def _read_jsonl(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _ground_truth(corpus: Path, dataset: str) -> dict[str, tuple[str, str]]:
    """`page_id -> (annotated plain text, url)` for one dataset."""
    path = corpus / "datasets" / "combined" / "ground-truth" / f"{dataset}.jsonl"
    if not path.exists():
        raise SystemExit(f"no ground truth at {path} -- was combined.tar.xz extracted?")
    return {
        row["page_id"]: (row.get("plaintext") or "", row.get("url") or "")
        for row in _read_jsonl(path)
    }


# --------------------------------------------------------------------------------------
# Extraction


@dataclass(slots=True)
class PageOutcome:
    """What one cached page produced, before it is scored."""

    page_id: str
    texts: dict[str, str]
    blocks: int
    kept: int
    """Blocks surviving the `main` variant. The gap to `blocks` is what it threw away."""

    reading_order: str
    error: str | None = None


@lru_cache(maxsize=1)
def _model():  # type: ignore[no-untyped-def]
    """The shipped block model, loaded once per worker process."""
    from webgraph.blockmodel import BlockModel

    return BlockModel.load()


def extract(corpus: Path, dataset: str, page_id: str, url: str) -> PageOutcome:
    """Parse one cached page and derive all four variants from the single parse."""
    from webgraph.boilerplate import strip_landmarks
    from webgraph.content import select_content
    from webgraph.main_content import select_main_content
    from webgraph.pipeline import build_document

    empty = dict.fromkeys(VARIANTS, "")
    path = corpus / "datasets" / "combined" / "html" / dataset / f"{page_id}.html"
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
        document = build_document(html, url or "https://example.invalid/")
    except Exception as exc:  # a corpus page failing must not stop the run
        return PageOutcome(page_id, empty, 0, 0, "none", f"{type(exc).__name__}: {exc}")

    blocks = list(document.blocks)
    landmarks = strip_landmarks(blocks)
    main = select_main_content(landmarks)
    model = _model()
    production = select_content(blocks, model=None)
    texts = {
        "raw": document.text,
        "landmarks": _join(landmarks),
        "prose": _join(b for b in blocks if str(b.kind) in PROSE_KINDS),
        "main": _join(main),
        # The two last steps of the production path, against each other over the same
        # earlier steps. `boundary` is `select_main_content`, asked for by `model=None`;
        # `model` is the trained per-block classifier. Passing `model=None` explicitly is
        # load-bearing: `select_content` now defaults to the model, so omitting it would
        # make these two columns the same number and the comparison would say nothing.
        # WCEB is an untouched test set for the model -- eight corpora, none of them WCXB.
        "boundary": _join(production.blocks),
        "boundary+comments": _join((*production.blocks, *production.comments)),
        "model": _join(select_content(blocks, model=model).blocks) if model else _join(main),
    }
    return PageOutcome(
        page_id=page_id,
        texts=texts,
        blocks=len(blocks),
        kept=len(main),
        reading_order=str(document.reading_order_method),
    )


def _join(blocks: Iterable[Any]) -> str:
    return blocks_text(blocks)


def _extract_star(args: tuple[Path, str, str, str]) -> PageOutcome:
    return extract(*args)


def _score_star(args: tuple[str, str, str]) -> tuple[str, float, float, float]:
    variant, target, pred = args
    return (variant, *rouge(target, pred))


# --------------------------------------------------------------------------------------
# Aggregation


@dataclass(slots=True)
class Aggregate:
    """Running per-page scores.

    WCEB's own `aggregate_scores` labels its headline bar chart "Mean F1 Page Scores (Micro
    Average)" and computes it by concatenating every page of every dataset and taking the
    mean -- so the pooled row here is page-weighted, exactly as upstream's is, and the
    per-dataset rows are means within one dataset.
    """

    precision: list[float] = field(default_factory=list)
    recall: list[float] = field(default_factory=list)
    f1: list[float] = field(default_factory=list)

    def add(self, p: float, r: float, f: float) -> None:
        self.precision.append(p)
        self.recall.append(r)
        self.f1.append(f)

    def __len__(self) -> int:
        return len(self.f1)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: Sequence[float]) -> float:
    return statistics.median(values) if values else 0.0


def baseline_scores(corpus: Path, datasets: Sequence[str]) -> dict[str, dict[str, Aggregate]]:
    """The authors' own per-page CSVs, averaged the same way ours are.

    Reading their files rather than the paper's table means the baseline column and the
    engine column went through one aggregation, so a difference between them is a difference
    in extraction and not in arithmetic. This runner has never executed any of these systems.
    """
    out: dict[str, dict[str, Aggregate]] = {}
    root = corpus / "outputs" / "metrics-computed" / "rouge"
    for model in BASELINES:
        per_dataset: dict[str, Aggregate] = {}
        pooled = Aggregate()
        for dataset in datasets:
            path = root / dataset / f"rouge_{model}.csv"
            if not path.exists():
                continue
            agg = Aggregate()
            with path.open(encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    agg.add(float(row["prec"]), float(row["rec"]), float(row["f1"]))
                    pooled.add(float(row["prec"]), float(row["rec"]), float(row["f1"]))
            per_dataset[dataset] = agg
        if pooled:
            per_dataset["_pooled"] = pooled
            out[model] = per_dataset
    return out


def report(
    scores: dict[str, dict[str, Aggregate]],
    outcomes: dict[str, PageOutcome],
    baselines: dict[str, dict[str, Aggregate]],
    datasets: Sequence[str],
) -> None:
    total = len(scores[VARIANTS[0]]["_pooled"])
    print(f"\n{'=' * 88}")
    print(f"WCEB (Bevendorff et al., SIGIR 2023) -- {total} pages, engine offline over cached HTML")
    print("metric: ROUGE-LSum, per-page, pooled mean (upstream's own micro average)")

    print(f"\n  {'variant':<12} {'P':>8} {'R':>8} {'F1':>8} {'median F1':>11}")
    print(f"  {'-' * 49}")
    for variant in VARIANTS:
        agg = scores[variant]["_pooled"]
        print(
            f"  {variant:<12} {_mean(agg.precision):>8.3f} {_mean(agg.recall):>8.3f} "
            f"{_mean(agg.f1):>8.3f} {_median(agg.f1):>11.3f}"
        )
    print(f"\n  {'baseline':<12} {'N':>6} {'P':>8} {'R':>8} {'F1':>8} {'median F1':>11}")
    print(f"  {'-' * 56}")
    for model, per_dataset in baselines.items():
        agg = per_dataset["_pooled"]
        # N is printed because `baseline_scores` skips a dataset whose CSV is absent without
        # saying so. A baseline row covering fewer pages than the engine's is not comparable
        # to it, and without this column the two would print identically.
        flag = "" if len(agg) == total else "  <- DIFFERENT PAGE SET, not comparable"
        print(
            f"  {model:<12} {len(agg):>6} {_mean(agg.precision):>8.3f} "
            f"{_mean(agg.recall):>8.3f} {_mean(agg.f1):>8.3f} {_median(agg.f1):>11.3f}{flag}"
        )
    print("  baseline rows are the authors' published per-page CSVs, averaged by this file;")
    print("  no baseline system was executed here.")

    print(f"\n  F1 by dataset\n  {'dataset':<20} {'N':>5}", end="")
    for variant in VARIANTS:
        print(f" {variant:>10}", end="")
    for model in baselines:
        print(f" {model[:11]:>12}", end="")
    print(f"\n  {'-' * (25 + 11 * len(VARIANTS) + 13 * len(baselines))}")
    for dataset in datasets:
        agg = scores[VARIANTS[0]].get(dataset)
        if agg is None:
            continue
        print(f"  {dataset:<20} {len(agg):>5}", end="")
        for variant in VARIANTS:
            print(f" {_mean(scores[variant][dataset].f1):>10.3f}", end="")
        for per_dataset in baselines.values():
            cell = per_dataset.get(dataset)
            if cell is None:
                print(f" {'no CSV':>12}", end="")
            elif len(cell) != len(agg):
                print(f" {_mean(cell.f1):>10.3f}!{len(cell)}", end="")
            else:
                print(f" {_mean(cell.f1):>12.3f}", end="")
        print()
    print("  `no CSV` means upstream published no score for that pair; a `!N` suffix means")
    print("  the cell covers N pages and not the engine's N, so it is not comparable.")

    best = max(VARIANTS, key=lambda v: _mean(scores[v]["_pooled"].f1))
    print(f"\n  P / R by dataset for the engine's best variant ({best})")
    print(f"  {'dataset':<20} {'N':>5} {'F1':>8} {'P':>8} {'R':>8}")
    print(f"  {'-' * 53}")
    for dataset in datasets:
        agg = scores[best].get(dataset)
        if agg is None:
            continue
        print(
            f"  {dataset:<20} {len(agg):>5} {_mean(agg.f1):>8.3f} "
            f"{_mean(agg.precision):>8.3f} {_mean(agg.recall):>8.3f}"
        )

    failures = [o for o in outcomes.values() if o.error]
    orders = Counter(o.reading_order for o in outcomes.values() if not o.error)
    empties = [o for o in outcomes.values() if not o.error and o.blocks == 0]
    emitted = sum(o.blocks for o in outcomes.values())
    selected = sum(o.kept for o in outcomes.values())
    print(f"\n  parse failures: {len(failures)}; parsed to zero blocks: {len(empties)}")
    print(f"  reading order:  {dict(orders)}")
    print(
        f"  select_main_content kept {selected:,} of {emitted:,} blocks "
        f"({selected / emitted:.1%}) -- the rest is what `main` throws away"
    )
    for outcome in failures[:5]:
        print(f"    {outcome.page_id}: {outcome.error}")


# --------------------------------------------------------------------------------------


def run(corpus: Path, datasets: Sequence[str], *, jobs: int, limit: int | None) -> None:
    scores: dict[str, dict[str, Aggregate]] = {
        variant: {"_pooled": Aggregate()} for variant in VARIANTS
    }
    outcomes: dict[str, PageOutcome] = {}

    for dataset in datasets:
        truth = _ground_truth(corpus, dataset)
        page_ids = sorted(truth)
        if limit:
            page_ids = page_ids[:limit]
        print(f"\n{dataset}: {len(page_ids)} pages", file=sys.stderr)

        tasks = [(corpus, dataset, pid, truth[pid][1]) for pid in page_ids]
        local: dict[str, PageOutcome] = {}
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for done, outcome in enumerate(pool.map(_extract_star, tasks, chunksize=4), 1):
                local[outcome.page_id] = outcome
                if done % 200 == 0:
                    print(f"  extracted {done}/{len(tasks)}", file=sys.stderr)
        outcomes.update(local)

        # Pages that failed to parse are scored as the empty string, not skipped: dropping
        # them would raise the mean by removing the hardest pages from it.
        work = [
            (variant, truth[pid][0], local[pid].texts[variant] if pid in local else "")
            for variant in VARIANTS
            for pid in page_ids
        ]
        for variant in VARIANTS:
            scores[variant][dataset] = Aggregate()
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for done, (variant, p, r, f) in enumerate(
                pool.map(_score_star, work, chunksize=8), 1
            ):
                scores[variant][dataset].add(p, r, f)
                scores[variant]["_pooled"].add(p, r, f)
                if done % 1000 == 0:
                    print(f"  scored {done}/{len(work)}", file=sys.stderr)

        # Print each dataset the moment it finishes. ROUGE-LSum over 3,985 pages x 4
        # variants is an hour of CPU, and a run that only speaks at the end is a run whose
        # first seven datasets are lost when the eighth one is interrupted.
        row = "  ".join(
            f"{v}={_mean(scores[v][dataset].f1):.3f}" for v in VARIANTS
        )
        print(f"  {dataset} done: {row}", file=sys.stderr)

    report(scores, outcomes, baseline_scores(corpus, datasets), datasets)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(os.environ.get("WCEB_CORPUS", "benchmark/wceb/corpus")),
        help="path to a WCEB clone (default: $WCEB_CORPUS, else benchmark/wceb/corpus)",
    )
    parser.add_argument(
        "-d", "--dataset", action="append", choices=DATASETS, dest="datasets",
        help="restrict to these datasets (repeatable; default: all eight)",
    )
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    parser.add_argument("--limit", type=int, default=None, help="first N pages per dataset")
    parser.add_argument(
        "--validate", action="store_true",
        help="rescore upstream's own outputs against upstream's own CSVs, then exit",
    )
    parser.add_argument(
        "--validate-limit", type=int, default=None, metavar="N",
        help="check only the first N pages of each validation pair (ROUGE is slow)",
    )
    args = parser.parse_args()
    corpus = args.corpus.resolve()
    os.environ["WCEB_CORPUS"] = str(corpus)  # so spawned workers find extraction_benchmark

    if args.validate:
        raise SystemExit(0 if validate(corpus, limit=args.validate_limit) else 1)
    run(corpus, tuple(args.datasets or DATASETS), jobs=args.jobs, limit=args.limit)
