"""Score the engine on WCXB, the only public extraction benchmark that labels page type.

Why this benchmark and not another
----------------------------------
`benchmark/content_quality` scores against a *vote of three extractors*, which is honest
about having no ground truth but cannot tell you where the engine is weak in a way anyone
else can check. WCXB has 2,008 human-reviewed pages across seven page types, and its whole
point is that the type breakdown is where extractors differ: on articles the published
leaders sit within three points of each other (F1 0.91-0.93), and on products they spread
across twenty (0.41-0.64). An overall number hides that. A per-type number is the finding.

Obtain the corpus with

    git clone --depth 1 https://github.com/Murrough-Foley/web-content-extraction-benchmark

and point `--corpus` at the clone. It is CC-BY-4.0, 192 MB, and deliberately not vendored
here: it is somebody else's dataset on somebody else's release cadence.

Why the metric is imported rather than reimplemented
----------------------------------------------------
The corpus ships `evaluate.py`, and this runner imports `load_ground_truth` and `word_f1`
from the clone instead of writing its own word-bag scorer. Two reasons. The first is that
the published leaderboard was produced by that file, so anything else is not comparable.
The second is subtler and easy to get wrong: WCXB averages **per-page F1**, not F1 computed
from corpus-wide precision and recall. Its own dev row for rs-trafilatura reads F1 0.859
with P 0.863 and R 0.890 -- 0.859 is not the harmonic mean of those two, and a runner that
aggregated the other way would report a number that looks like the leaderboard's and is not.

Why plain text and not Markdown
--------------------------------
The metric is a bag of `\\w+` tokens. Markdown syntax survives that tokenizer as words --
a fenced block's language tag, a link's URL split into path segments -- so asking the engine
for Markdown would charge it precision for punctuation it was told to emit. `document.text`
is the fair input.

What this benchmark cannot see
-------------------------------
Every page is cached HTML with no network, which switches off two of the three things this
engine does that a single-pass DOM extractor does not:

* **Geometric reading order** needs a browser render for box geometry. Offline, every
  document falls back to DOM order and says so via `reading_order_method`; the run prints
  the distribution so the claim is checked, not asserted.
* **Cross-page chrome detection** needs six or more pages from one site. WCXB has 1,613
  domains over 2,008 pages -- seven domains clear the threshold. The feature is
  structurally unavailable, not merely unused, and the run prints that count too.

`strip_landmarks` survives, because it works on one page. So the three variants below are
the whole of what this benchmark can measure about this engine.

Usage
-----
    uv run --package webgraph python benchmark/wcxb/run.py --corpus /path/to/clone
    uv run --package webgraph python benchmark/wcxb/run.py --corpus … --split test
    uv run --package webgraph python benchmark/wcxb/run.py --corpus … --worst product
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Final

VARIANTS: Final[tuple[str, ...]] = ("raw", "landmarks", "prose", "content", "routed-oof", "routed-truth")
"""The four ways to turn a parsed document into text.

`content` is the production path -- `webgraph.content.select_content`: landmarks, then the
main-content boundary. It is what every crawl page's `content_markdown`, `/api/text` and
`webgraph text --content` ship, so its row is the product's number.

`raw` is `document.text`: every block the parser found, in reading order. `landmarks` is
that with `<nav>` and `<footer>` subtrees dropped -- the shipped single-page default.
`prose` keeps only PARAGRAPH, HEADING, LIST_ITEM and QUOTE blocks, which is a stricter
filter than `content_quality`'s (that one excludes CODE, TABLE and FIGURE_CAPTION and so
still keeps IMAGE alt text). Reporting all three matters because they trade the same way
every time -- each one buys precision with recall -- and only the spread says whether the
engine's problem is noise or reach.
"""

TYPE_ORDER: Final[tuple[str, ...]] = (
    "article",
    "documentation",
    "service",
    "forum",
    "collection",
    "listing",
    "product",
)
"""Ordered as the corpus README orders its own per-type table, easiest type first, so the
two can be read side by side without re-sorting either."""

PROSE_KINDS: Final[frozenset[str]] = frozenset(
    {"paragraph", "heading", "list-item", "quote"}
)

PUBLISHED_DEV_F1: Final[dict[str, dict[str, float]]] = {
    # From the corpus README's "F1 by Page Type (Development Set)" table. Reproduced here
    # for side-by-side printing only -- these are the authors' numbers, not ours, and this
    # runner has never executed any of these systems.
    "rs-trafilatura": {
        "article": 0.932, "documentation": 0.932, "service": 0.844, "forum": 0.808,
        "collection": 0.716, "listing": 0.707, "product": 0.641, "overall": 0.859,
    },
    "MinerU-HTML": {
        "article": 0.928, "documentation": 0.838, "service": 0.824, "forum": 0.794,
        "collection": 0.506, "listing": 0.710, "product": 0.619, "overall": 0.827,
    },
    "trafilatura": {
        "article": 0.926, "documentation": 0.888, "service": 0.763, "forum": 0.585,
        "collection": 0.553, "listing": 0.589, "product": 0.567, "overall": 0.791,
    },
    "dom-smoothie": {
        "article": 0.908, "documentation": 0.868, "service": 0.714, "forum": 0.530,
        "collection": 0.504, "listing": 0.596, "product": 0.502, "overall": 0.762,
    },
    "readability": {
        "article": 0.825, "documentation": 0.736, "service": 0.604, "forum": 0.466,
        "collection": 0.445, "listing": 0.496, "product": 0.407, "overall": 0.675,
    },
}


def load_evaluator(corpus: Path) -> ModuleType:
    """Import the corpus's own `evaluate.py` as a module.

    It resolves splits from `Path(__file__).parent`, so importing it from the clone is also
    what points it at the clone's ground truth. Copying the file here would fork the metric
    the first time upstream changed it.
    """
    path = corpus / "evaluate.py"
    if not path.exists():
        raise SystemExit(f"no evaluate.py under {corpus} -- is that a WCXB clone?")
    spec = importlib.util.spec_from_file_location("wcxb_evaluate", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(slots=True)
class PageOutcome:
    """What one cached page produced, before it is scored."""

    file_id: str
    texts: dict[str, str]
    blocks: int
    duplicate_blocks: int
    """Blocks whose whitespace-normalised text repeats one already emitted.

    A word-bag metric counts multiplicity, so a page that emits the same string twice is
    charged twice for it. This is the number that says whether a precision loss is the
    engine keeping the wrong things or keeping the right things more than once.
    """

    reading_order: str
    error: str | None = None


_OOF_CACHE: dict[str, dict[str, Any]] | None = None


def _oof_type(file_id: str) -> str | None:
    """The router's out-of-fold prediction for this page, from `$WCXB_ROUTER_OOF`."""
    global _OOF_CACHE
    if _OOF_CACHE is None:
        path = os.environ.get("WCXB_ROUTER_OOF")
        _OOF_CACHE = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    entry = _OOF_CACHE.get(file_id)
    return str(entry["type"]) if entry else None


def _truth_type(corpus: Path, split: str, file_id: str) -> str | None:
    path = corpus / split / "ground-truth" / f"{file_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return ((data.get("_internal") or {}).get("page_type") or {}).get("primary")


def extract(corpus: Path, split: str, file_id: str, url: str) -> PageOutcome:
    """Parse one cached page and derive all three variants from the single parse."""
    from webgraph.boilerplate import strip_landmarks
    from webgraph.content import select_content
    from webgraph.pagetype import policy_for
    from webgraph.pipeline import build_document

    empty = dict.fromkeys(VARIANTS, "")
    path = corpus / split / "html" / f"{file_id}.html.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            html = handle.read()
        document = build_document(html, url or "https://example.invalid/")
    except Exception as exc:  # a corpus page failing must not stop the run
        return PageOutcome(file_id, empty, 0, 0, "none", f"{type(exc).__name__}: {exc}")

    blocks = list(document.blocks)
    page_type = _truth_type(corpus, split, file_id)
    texts = {
        "raw": document.text,
        "landmarks": _join(strip_landmarks(blocks)),
        "prose": _join(b for b in blocks if str(b.kind) in PROSE_KINDS),
        # `model=None` is mandatory here and not a style choice. `select_content` defaults
        # to the shipped block model, and that model was trained on all of WCXB **dev** --
        # scoring it on dev would be scoring a model on its own training data. This variant
        # is the contiguous boundary step. The model's honest number on dev is the
        # out-of-fold one: `benchmark/train/blockmodel_oof.py`.
        "content": _join(select_content(blocks, model=None).blocks),
        # Routing: per-type selector policy (`webgraph.pagetype.policy_for`).
        #   routed-oof   -- the type predicted by the router *out of fold* (a router that
        #                   never trained on this page), read from $WCXB_ROUTER_OOF. This is
        #                   the honest number.
        #   routed-truth -- the annotated type: the ceiling routing could reach with a
        #                   perfect router. Diagnostic only; never quote it as a score.
        "routed-oof": _join(
            select_content(blocks, model=None, config=policy_for(_oof_type(file_id))).blocks
        ),
        "routed-truth": _join(
            select_content(blocks, model=None, config=policy_for(page_type)).blocks
        ),
    }
    keys = [" ".join(b.text.split()) for b in blocks if b.text.strip()]
    return PageOutcome(
        file_id=file_id,
        texts=texts,
        blocks=len(blocks),
        duplicate_blocks=len(keys) - len(set(keys)),
        reading_order=str(document.reading_order_method),
    )


def _join(blocks: Iterable[object]) -> str:
    return "\n\n".join(b.text for b in blocks if b.text.strip())  # type: ignore[attr-defined]


def _extract_star(args: tuple[Path, str, str, str]) -> PageOutcome:
    return extract(*args)


@dataclass(slots=True)
class Aggregate:
    """Running per-page means. WCXB averages pages, not tokens -- see the module docstring."""

    precision: list[float] = field(default_factory=list)
    recall: list[float] = field(default_factory=list)
    f1: list[float] = field(default_factory=list)
    kept: list[float] = field(default_factory=list)
    """Share of the `with[]` snippets present: content the extraction had to keep."""

    leaked: list[float] = field(default_factory=list)
    """Share of the `without[]` snippets present: boilerplate it had to drop. Lower is
    better, and it localises a precision loss the way a precision number alone cannot --
    it names the chrome that got through."""

    def add(self, p: float, r: float, f: float, kept: float, leaked: float) -> None:
        self.precision.append(p)
        self.recall.append(r)
        self.f1.append(f)
        self.kept.append(kept)
        self.leaked.append(leaked)

    def __len__(self) -> int:
        return len(self.f1)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def score(
    evaluator: ModuleType, ground_truth: dict, outcomes: dict[str, PageOutcome]
) -> dict[str, tuple[Aggregate, dict[str, Aggregate]]]:
    """Score every variant over every ground-truth page.

    Pages that failed to parse are scored as the empty string rather than skipped. Dropping
    them would quietly raise the mean by removing the hardest pages from it.
    """
    out: dict[str, tuple[Aggregate, dict[str, Aggregate]]] = {}
    for variant in VARIANTS:
        overall = Aggregate()
        by_type: dict[str, Aggregate] = defaultdict(Aggregate)
        for file_id, entry in sorted(ground_truth.items()):
            outcome = outcomes.get(file_id)
            text = outcome.texts[variant] if outcome else ""
            p, r, f = evaluator.word_f1(text, entry["main_content"])
            kept = evaluator.snippet_check(text, entry["with"])
            leaked = evaluator.snippet_check(text, entry["without"])
            overall.add(p, r, f, kept, leaked)
            by_type[entry["page_type"]].add(p, r, f, kept, leaked)
        out[variant] = (overall, dict(by_type))
    return out


def report(
    scores: dict[str, tuple[Aggregate, dict[str, Aggregate]]],
    outcomes: dict[str, PageOutcome],
    ground_truth: dict,
    split: str,
) -> None:
    total = len(next(iter(scores.values()))[0])
    print(f"\n{'=' * 78}\nWCXB {split} split -- {total} pages, engine offline over cached HTML")

    print(f"\n  {'variant':<12} {'P':>7} {'R':>7} {'F1':>7} {'with':>7} {'without':>8}")
    print(f"  {'-' * 52}")
    for variant in VARIANTS:
        agg, _ = scores[variant]
        print(
            f"  {variant:<12} {_mean(agg.precision):>7.3f} {_mean(agg.recall):>7.3f} "
            f"{_mean(agg.f1):>7.3f} {_mean(agg.kept):>7.1%} {_mean(agg.leaked):>8.1%}"
        )
    print("  `with` is required content found (higher better); `without` is boilerplate")
    print("  that leaked (lower better). Both come from the corpus's own snippet lists.")

    print(f"\n  F1 by page type\n  {'type':<15} {'N':>5}", end="")
    for variant in VARIANTS:
        print(f" {variant:>10}", end="")
    print(f"\n  {'-' * 56}")
    for page_type in TYPE_ORDER:
        first = scores[VARIANTS[0]][1].get(page_type)
        if first is None:
            continue
        print(f"  {page_type:<15} {len(first):>5}", end="")
        for variant in VARIANTS:
            print(f" {_mean(scores[variant][1][page_type].f1):>10.3f}", end="")
        print()

    best = max(VARIANTS, key=lambda v: _mean(scores[v][0].f1))
    print(f"\n  P/R and snippet rates for the best variant ({best})")
    print(f"  {'type':<15} {'N':>5} {'F1':>7} {'P':>7} {'R':>7} {'with':>7} {'without':>8}")
    print(f"  {'-' * 60}")
    for page_type in TYPE_ORDER:
        agg = scores[best][1].get(page_type)
        if agg is None:
            continue
        print(
            f"  {page_type:<15} {len(agg):>5} {_mean(agg.f1):>7.3f} {_mean(agg.precision):>7.3f} "
            f"{_mean(agg.recall):>7.3f} {_mean(agg.kept):>7.1%} {_mean(agg.leaked):>8.1%}"
        )

    if split == "dev":
        print("\n  Against the F1 the corpus README publishes for the same split")
        print("  (their numbers, not reproduced here -- this runner ran no other system)")
        header = f"  {'type':<15} {'engine':>8}"
        for name in PUBLISHED_DEV_F1:
            header += f" {name[:11]:>12}"
        print(header)
        print(f"  {'-' * (25 + 13 * len(PUBLISHED_DEV_F1))}")
        for page_type in (*TYPE_ORDER, "overall"):
            if page_type == "overall":
                ours = _mean(scores[best][0].f1)
            else:
                agg = scores[best][1].get(page_type)
                if agg is None:
                    continue
                ours = _mean(agg.f1)
            row = f"  {page_type:<15} {ours:>8.3f}"
            for values in PUBLISHED_DEV_F1.values():
                row += f" {values[page_type]:>12.3f}"
            print(row)
        print("\n  Disclosure: rs-trafilatura, the top row, is written by the same author as")
        print("  this benchmark, who also maintains the leaderboard. The corpus and metric")
        print("  are open and inspectable and this run used both unmodified; the ranking of")
        print("  the author's own system on the author's own benchmark is still not")
        print("  independent evidence and should not be read as such.")

    failures = [o for o in outcomes.values() if o.error]
    orders = Counter(o.reading_order for o in outcomes.values() if not o.error)
    empties = [o for o in outcomes.values() if not o.error and o.blocks == 0]
    duplicated = sum(o.duplicate_blocks for o in outcomes.values())
    emitted = sum(o.blocks for o in outcomes.values())
    print(f"\n  parse failures: {len(failures)}; parsed to zero blocks: {len(empties)}")
    print(f"  reading order:  {dict(orders)}")
    print(
        f"  repeated blocks: {duplicated:,} of {emitted:,} emitted "
        f"({duplicated / emitted:.1%}) -- charged twice by a multiset metric"
    )
    for outcome in failures[:5]:
        print(f"    {outcome.file_id}: {outcome.error}")

    # The corpus annotates a page whose content only exists after JavaScript with
    # `main_content: ""`. Under this metric that scores 0.0 for any extractor that returns
    # text and 1.0 for one that returns nothing -- so these pages do not merely fail to
    # reward rendering, they punish it. Worth printing because it is a ceiling on the total,
    # and because it is the clearest evidence of what this benchmark is not measuring.
    blank = [fid for fid, entry in ground_truth.items() if not entry["main_content"].strip()]
    if blank:
        silent = sum(1 for fid in blank if not (outcomes[fid].texts["raw"] if fid in outcomes else ""))
        types = Counter(ground_truth[fid]["page_type"] for fid in blank)
        print(
            f"\n  pages whose ground truth is empty: {len(blank)} "
            f"({len(blank) / total:.1%} of the split) -- {dict(types)}"
        )
        print(
            f"  the engine returned nothing on {silent} of them, so it takes "
            f"{(len(blank) - silent) / total:.1%} of unavoidable F1 loss there. A renderer"
        )
        print("  that recovered the real content of those pages would score 0.0 on them.")


def worst_pages(
    evaluator: ModuleType,
    ground_truth: dict,
    outcomes: dict[str, PageOutcome],
    page_type: str,
    variant: str,
    limit: int,
) -> None:
    """List the lowest-F1 pages of one type, so a weak column can be opened and read."""
    rows = []
    for file_id, entry in ground_truth.items():
        if entry["page_type"] != page_type:
            continue
        outcome = outcomes.get(file_id)
        text = outcome.texts[variant] if outcome else ""
        p, r, f = evaluator.word_f1(text, entry["main_content"])
        rows.append((f, p, r, file_id, len(text), len(entry["main_content"])))
    rows.sort()
    print(f"\n  worst {limit} {page_type} pages on the `{variant}` variant")
    print(f"  {'file':<8} {'F1':>6} {'P':>6} {'R':>6} {'ours':>9} {'truth':>9}")
    for f, p, r, file_id, ours, truth in rows[:limit]:
        print(f"  {file_id:<8} {f:>6.3f} {p:>6.3f} {r:>6.3f} {ours:>9,} {truth:>9,}")


def run(
    corpus: Path,
    split: str,
    *,
    jobs: int,
    limit: int | None,
    out: Path | None,
    worst: str | None,
) -> None:
    evaluator = load_evaluator(corpus)
    ground_truth = evaluator.load_ground_truth(split)
    if limit:
        ground_truth = dict(sorted(ground_truth.items())[:limit])
    print(f"{len(ground_truth)} ground-truth pages from {corpus / split}")

    urls = _urls(corpus, split)
    tasks = [(corpus, split, file_id, urls.get(file_id, "")) for file_id in sorted(ground_truth)]

    outcomes: dict[str, PageOutcome] = {}
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for done, outcome in enumerate(pool.map(_extract_star, tasks, chunksize=4), 1):
            outcomes[outcome.file_id] = outcome
            if done % 100 == 0:
                print(f"  extracted {done}/{len(tasks)}", file=sys.stderr)

    scores = score(evaluator, ground_truth, outcomes)
    report(scores, outcomes, ground_truth, split)

    if worst:
        best = max(VARIANTS, key=lambda v: _mean(scores[v][0].f1))
        worst_pages(evaluator, ground_truth, outcomes, worst, best, 12)

    if out:
        out.mkdir(parents=True, exist_ok=True)
        for variant in VARIANTS:
            target = out / f"webgraph-{variant}-{split}.json"
            target.write_text(
                json.dumps({fid: o.texts[variant] for fid, o in outcomes.items()}),
                encoding="utf-8",
            )
        print(f"\n  predictions written under {out}")


def _urls(corpus: Path, split: str) -> dict[str, str]:
    """The page's real URL, read from its ground truth.

    Worth the extra pass: `build_document` absolutises hrefs against it and the profiler
    reads its host, so a placeholder would change what the engine sees.
    """
    urls: dict[str, str] = {}
    for path in sorted((corpus / split / "ground-truth").glob("*.json")):
        try:
            urls[path.stem] = json.loads(path.read_text(encoding="utf-8")).get("url", "")
        except (OSError, json.JSONDecodeError):
            continue
    return urls


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(os.environ.get("WCXB_CORPUS", "benchmark/wcxb/corpus")),
        help="path to a WCXB clone (default: $WCXB_CORPUS, else benchmark/wcxb/corpus)",
    )
    parser.add_argument("--split", default="dev", choices=("dev", "test"))
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    parser.add_argument("--limit", type=int, default=None, help="first N pages, for a smoke run")
    parser.add_argument("--out", type=Path, default=None, help="write per-variant predictions here")
    parser.add_argument(
        "--worst",
        default=None,
        choices=TYPE_ORDER,
        help="also list the lowest-scoring pages of this type",
    )
    args = parser.parse_args()
    run(
        args.corpus.resolve(),
        args.split,
        jobs=args.jobs,
        limit=args.limit,
        out=args.out,
        worst=args.worst,
    )
