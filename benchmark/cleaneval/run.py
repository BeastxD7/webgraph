"""Score the engine on CleanEval-1 (Baroni, Chantree, Kilgarriff, Sharoff; LREC 2008).

Why this benchmark
------------------
CleanEval is the original shared task for this problem. It was run in 2007 by organisers at
Trento, Lexical Computing and Leeds, scored by their own program against gold standards
produced by paid annotators, with nine independent teams submitting. Nobody in that setup
had a product in the field. Eighteen years later almost every extraction benchmark in
circulation is published by a party whose own extractor appears in the comparison, so an
old, small, independently-run corpus is worth more than its size suggests: it is one of the
few numbers in this repo that no interested party arranged.

    finalrun-input/   740 HTML files, each wrapped in <text id="URL" title=… >
    GoldStandard/     681 hand-cleaned .txt files

Both come from the CleanEval distribution; point `--corpus` at a directory holding them. The
counts differ, and the run scores the 681-file intersection and prints the shortfall rather
than hiding it -- 59 input pages have no published gold standard.

The two scorers, and why both
------------------------------
CleanEval has two official scoring programs and they measure different things.

`cleaneval.prl` (Francis Chantree) is the program that produced the paper's Table 5. It runs
a Levenshtein alignment over the whole file and reports **TM** ("Text and Markup"), **TO**
("Text Only") and their average **Ave**. It is the only way to get a number that stands next
to the published participant scores. It is also pure-Perl O(n*m) alignment: one page pair
takes about seventy seconds, so `--official` scores a seeded random sample rather than all
681, and says so in its own output. That is a real limitation and it is stated, not papered
over.

`cleaneval.py` (Stefan Evert, 2008, shipped as `cleaneval_scorer.zip`) is the fast one:
`difflib` alignment over whitespace tokens, reporting precision, recall and F over words and
separately over segment markers. Every modern paper that reports "CleanEval F1" is reporting
something in this family. It is Python 2 and is loaded here **without editing its source**:
the metric region is sliced off before the first `print >>` statement and executed with
Python-2 builtin semantics restored through the exec globals, so `normalize`, `make_diff`
and `evaluate` are upstream's own bytes. `--validate` proves it, by predicting the gold
standard back at itself and requiring 100.00 on every measure.

Why the output carries <p>/<h>/<l>
-----------------------------------
CleanEval's task definition is not "return the text". It is "return the text with paragraph,
header and list-item boundaries marked", using exactly those three tags and no others. Both
scorers care: `cleaneval.py`'s word tokenizer treats each tag as a token, so an untagged
submission loses recall against a gold standard that has them (measurably: 97.48 F instead
of 100.00 for otherwise-perfect text), and the Perl scorer's TM half is entirely about them.

So the engine's block kinds are mapped onto the task's three tags -- HEADING to `<h>`,
LIST_ITEM to `<l>`, everything else to `<p>` -- and the run reports word scores **both with
and without** the tags emitted, so nothing is hidden behind a formatting choice. No Markdown
is emitted in any variant: these are text-alignment metrics and Markdown punctuation would
enter the token stream as words the annotator never wrote.

What this benchmark cannot see
-------------------------------
Cached 2007 HTML with no network. Geometric reading order needs a browser render and is
unavailable, so every page falls back to DOM order; the run prints the
`reading_order_method` distribution rather than asserting it. Cross-page chrome detection
needs several pages per site and the corpus is one page per URL.

Usage
-----
    uv run --package webgraph python benchmark/cleaneval/run.py --corpus … --validate
    uv run --package webgraph python benchmark/cleaneval/run.py --corpus …
    uv run --package webgraph python benchmark/cleaneval/run.py --corpus … --official 24
"""

from __future__ import annotations

import argparse
import builtins
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

VARIANTS: Final[tuple[str, ...]] = ("raw", "landmarks", "prose", "main")
"""The four ways to turn a parsed document into text, in increasing order of how much they
throw away. See `benchmark/wceb/run.py` for the full argument; the short version is that
they form a precision/recall ladder and only the spread says whether the engine's problem is
noise or reach. `main` is `strip_landmarks` then `select_main_content`."""

PROSE_KINDS: Final[frozenset[str]] = frozenset(
    {"paragraph", "heading", "list-item", "quote"}
)

TAG_FOR_KIND: Final[dict[str, str]] = {"heading": "<h>", "list-item": "<l>"}
"""CleanEval allows three segment markers and no more. Anything that is not a heading or a
list item is a paragraph as far as the task is concerned -- including tables, code and image
captions, which the 2007 guidelines had no category for."""

PUBLISHED: Final[tuple[tuple[str, float, float, float], ...]] = (
    # LREC 2008 paper, Table 5: nine English participants, "Text and Markup" / "Text Only" /
    # their average. The paper's own summary of this table is that every non-student system
    # landed between 70% and 75% Ave, with the top four inside 74.0-74.7, and that TO ran
    # roughly twenty points above TM because inserting the markup was the harder half.
    #
    # The names are deliberately omitted. The only copy of this table available here is an
    # OCR of the PDF in which the two-column layout collapsed and the participant names no
    # longer line up with the number triples. Attaching a name to a number on that evidence
    # would be inventing a citation, so the rows below are the number set, sorted, with the
    # student and non-student groups kept separate as the paper keeps them.
    ("non-student", 65.3, 84.1, 74.7),
    ("non-student", 65.3, 83.4, 74.3),
    ("non-student", 65.5, 83.0, 74.2),
    ("non-student", 65.6, 82.5, 74.0),
    ("non-student", 63.9, 83.4, 73.6),
    ("non-student", 60.3, 82.9, 71.6),
    ("non-student", 59.5, 80.9, 70.2),
    ("non-student", 45.5, 60.2, 52.9),
    ("student", 53.5, 73.5, 63.5),
)


# --------------------------------------------------------------------------------------
# The fast scorer: Stefan Evert's cleaneval.py, loaded unedited


def load_evert(corpus: Path) -> tuple[Any, Any, Any, Any]:
    """Return `(normalize, make_diff, evaluate, re_WS)` from upstream's Python 2 source.

    The file is not edited and not vendored. Everything from `write_alignment` down is the
    CLI and the alignment dump, both of which use `print >>` and are Python 2 syntax errors;
    everything above is the metric. Slicing at that boundary and compiling the head is what
    makes upstream's own bytes runnable here. The two Python 2 builtins the metric depends on
    -- `file` and a `filter` that returns a list -- are supplied through the exec globals
    rather than by touching the source.
    """
    path = corpus / "cleaneval.py"
    if not path.exists():
        raise SystemExit(f"no cleaneval.py under {corpus} -- unpack cleaneval_scorer.zip there")
    source = path.read_text(encoding="latin-1")
    head = source[: source.index("def write_alignment")]
    namespace: dict[str, Any] = {
        "__name__": "cleaneval_upstream",
        "file": open,
        "filter": lambda f, it: list(builtins.filter(f, it)),
    }
    exec(compile(head, str(path), "exec"), namespace)  # noqa: S102 -- upstream's own metric
    return (
        namespace["normalize"],
        namespace["make_diff"],
        namespace["evaluate"],
        namespace["re_WS"],
    )


_EVERT: tuple[Any, Any, Any, Any] | None = None


def evert_score(corpus: Path, text: str, gold: str) -> tuple[float, ...]:
    """`(word F, P, R, tag F, P, R)` as percentages, via upstream's own functions.

    Both sides are handled as bytes decoded latin-1, which is what the Python 2 original did
    with whatever encoding the files happened to be in. Doing anything cleverer would change
    the tokenization and stop the numbers being comparable to 2008's.
    """
    global _EVERT
    if _EVERT is None:
        _EVERT = load_evert(corpus)
    normalize, make_diff, evaluate, re_WS = _EVERT
    from difflib import SequenceMatcher

    text_w = re_WS.split(normalize(text))
    gold_w = re_WS.split(normalize(gold))
    return tuple(evaluate(make_diff(SequenceMatcher(None, text_w, gold_w), text_w, gold_w))[:6])


def validate(corpus: Path, pairs: Sequence[tuple[str, str]]) -> bool:
    """Predict the gold standard back at itself and require a perfect score.

    A scorer loaded by slicing and exec'ing somebody else's Python 2 file has many ways to be
    subtly wrong -- a builtin that returns an iterator instead of a list silently zeroes the
    tag counts, for instance. The identity test catches all of them at once: if `normalize`
    and `evaluate` are intact, gold against gold is 100.00 on every measure and nothing else
    is.
    """
    print(f"validating the Evert scorer by identity over {len(pairs)} gold files")
    totals = [0.0] * 6
    for _, gold in pairs:
        for index, value in enumerate(evert_score(corpus, gold, gold)):
            totals[index] += value
    means = [t / len(pairs) for t in totals]
    print(f"  identity  word F={means[0]:.2f} P={means[1]:.2f} R={means[2]:.2f}")
    print(f"            tag  F={means[3]:.2f} P={means[4]:.2f} R={means[5]:.2f}")
    stripped = [0.0] * 6
    for _, gold in pairs:
        untagged = re.sub(r"<[phlPHL]>", "", gold)
        for index, value in enumerate(evert_score(corpus, untagged, gold)):
            stripped[index] += value
    means_s = [t / len(pairs) for t in stripped]
    print(
        f"  same text, markers removed: word F={means_s[0]:.2f} tag F={means_s[3]:.2f} "
        "-- this is the cost of not emitting <p>/<h>/<l>"
    )
    ok = all(abs(m - 100.0) < 1e-9 for m in means)
    print(f"  verdict: {'MATCH' if ok else 'MISMATCH'}")
    return ok


# --------------------------------------------------------------------------------------
# Extraction


@dataclass(slots=True)
class PageOutcome:
    """What one cached page produced, before it is scored."""

    page_id: str
    tagged: dict[str, str]
    """Variant text in CleanEval submission format: one segment per line, `<p>`/`<h>`/`<l>`
    leading each."""

    plain: dict[str, str]
    """The same text with the markers left off, to price the formatting choice."""

    blocks: int
    kept: int
    reading_order: str
    error: str | None = None


_TEXT_WRAPPER: Final[re.Pattern[str]] = re.compile(
    r'<text\s+id="([^"]*)"', re.IGNORECASE
)


def extract(corpus: Path, page_id: str) -> PageOutcome:
    """Parse one input page and derive all four variants from the single parse."""
    from webgraph.boilerplate import strip_landmarks
    from webgraph.main_content import select_main_content
    from webgraph.pipeline import build_document

    empty = dict.fromkeys(VARIANTS, "")
    path = corpus / "finalrun-input" / f"{page_id}.html"
    try:
        raw = path.read_bytes()
        html = raw.decode("utf-8", errors="replace")
        # CleanEval wraps every input in <text id="…" title="…">. The id is the page's real
        # URL, and `build_document` absolutises hrefs against it and profiles its host, so
        # feeding a placeholder would change what the engine sees.
        match = _TEXT_WRAPPER.search(html[:2000])
        url = match.group(1) if match else "https://example.invalid/"
        document = build_document(html, url or "https://example.invalid/")
    except Exception as exc:  # a corpus page failing must not stop the run
        return PageOutcome(page_id, empty, empty, 0, 0, "none", f"{type(exc).__name__}: {exc}")

    blocks = list(document.blocks)
    landmarks = strip_landmarks(blocks)
    main = select_main_content(landmarks)
    selections = {
        "raw": blocks,
        "landmarks": landmarks,
        "prose": [b for b in blocks if str(b.kind) in PROSE_KINDS],
        "main": main,
    }
    return PageOutcome(
        page_id=page_id,
        tagged={k: _render(v, tags=True) for k, v in selections.items()},
        plain={k: _render(v, tags=False) for k, v in selections.items()},
        blocks=len(blocks),
        kept=len(main),
        reading_order=str(document.reading_order_method),
    )


def _render(blocks: Iterable[Any], *, tags: bool) -> str:
    lines = []
    for block in blocks:
        text = " ".join(block.text.split())
        if not text:
            continue
        marker = TAG_FOR_KIND.get(str(block.kind), "<p>") if tags else ""
        lines.append(f"{marker}{text}" if marker else text)
    return "\n".join(lines)


def _extract_star(args: tuple[Path, str]) -> PageOutcome:
    return extract(*args)


# --------------------------------------------------------------------------------------
# The official scorer: cleaneval.prl


_PERL_TM: Final[re.Pattern[str]] = re.compile(
    r"Overall Score for Text and Markup Scoring:\s*([\d.]+)%"
)
_PERL_TO: Final[re.Pattern[str]] = re.compile(
    r"Overall Score for Text Only Scoring:\s*([\d.]+)%"
)
_PERL_AVE: Final[re.Pattern[str]] = re.compile(
    r"Your Score on This Task is:\s*([\d.]+)%"
)


def perl_score(
    scorer: Path, prediction: str, gold: bytes, timeout: int
) -> tuple[float, float, float] | None:
    """Run `cleaneval.prl` on one page pair and parse TM / TO / Ave off its stdout.

    Every call gets its own temporary directory, and this is not tidiness. The script writes
    `<name>_LOG.txt`, `results/`, `tracing/`, `Alignments/`, `Edit_Distances/` and
    `Segment_Validity/` into the current working directory, named after the contestant file,
    so two concurrent calls in one directory overwrite each other's intermediates and the
    scores that come back are silently wrong. It also prompts on stdin for the language,
    which is why "E" is piped in.
    """
    work = Path(tempfile.mkdtemp(prefix="cleaneval-"))
    try:
        (work / "cont.txt").write_bytes(prediction.encode("utf-8"))
        (work / "gold.txt").write_bytes(gold)
        result = subprocess.run(
            ["perl", str(scorer), "cont.txt", "gold.txt"],
            cwd=work,
            input=b"E\n",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        out = result.stdout.decode("utf-8", errors="replace")
        tm, to, ave = _PERL_TM.search(out), _PERL_TO.search(out), _PERL_AVE.search(out)
        if not (tm and to and ave):
            return None
        return float(tm.group(1)), float(to.group(1)), float(ave.group(1))
    except subprocess.TimeoutExpired:
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------------------
# Aggregation


@dataclass(slots=True)
class Aggregate:
    rows: list[tuple[float, ...]] = field(default_factory=list)

    def add(self, row: Sequence[float]) -> None:
        self.rows.append(tuple(row))

    def mean(self, index: int) -> float:
        return sum(r[index] for r in self.rows) / len(self.rows) if self.rows else 0.0

    def __len__(self) -> int:
        return len(self.rows)


def report(
    scores: dict[str, Aggregate],
    plain_scores: dict[str, Aggregate],
    outcomes: dict[str, PageOutcome],
    total: int,
    missing_gold: int,
) -> None:
    print(f"\n{'=' * 84}")
    print(f"CleanEval-1 final run -- {total} pages scored, engine offline over cached HTML")
    print("metric: cleaneval.py (Evert 2008), whitespace-token P/R/F, per-page mean")
    print("output format: CleanEval segment markers <p>/<h>/<l> emitted, no Markdown")

    print(f"\n  {'variant':<12} {'word F':>8} {'word P':>8} {'word R':>8} "
          f"{'tag F':>8} {'tag P':>8} {'tag R':>8}")
    print(f"  {'-' * 64}")
    for variant in VARIANTS:
        agg = scores[variant]
        print(
            f"  {variant:<12} {agg.mean(0):>8.2f} {agg.mean(1):>8.2f} {agg.mean(2):>8.2f} "
            f"{agg.mean(3):>8.2f} {agg.mean(4):>8.2f} {agg.mean(5):>8.2f}"
        )

    print("\n  the same runs with the segment markers left off")
    print(f"  {'variant':<12} {'word F':>8} {'word P':>8} {'word R':>8}")
    print(f"  {'-' * 40}")
    for variant in VARIANTS:
        agg = plain_scores[variant]
        print(f"  {variant:<12} {agg.mean(0):>8.2f} {agg.mean(1):>8.2f} {agg.mean(2):>8.2f}")

    failures = [o for o in outcomes.values() if o.error]
    orders = Counter(o.reading_order for o in outcomes.values() if not o.error)
    empties = [o for o in outcomes.values() if not o.error and o.blocks == 0]
    emitted = sum(o.blocks for o in outcomes.values())
    selected = sum(o.kept for o in outcomes.values())
    print(f"\n  input pages with no published gold standard: {missing_gold} (not scored)")
    print(f"  parse failures: {len(failures)}; parsed to zero blocks: {len(empties)}")
    print(f"  reading order:  {dict(orders)}")
    if emitted:
        print(
            f"  select_main_content kept {selected:,} of {emitted:,} blocks "
            f"({selected / emitted:.1%})"
        )
    for outcome in failures[:5]:
        print(f"    {outcome.page_id}: {outcome.error}")


def report_official(
    results: dict[str, list[tuple[float, float, float]]],
    sample: Sequence[str],
    timeouts: dict[str, int],
) -> None:
    print(f"\n{'=' * 84}")
    print("cleaneval.prl (Chantree) -- the program that produced the paper's Table 5")
    print(f"seeded random sample of {len(sample)} pages; ~70s of Perl per page pair is why")

    # Every mean carries its standard error, because the thing it is being compared against
    # is a cluster of participants only 0.7 points wide (74.0-74.7 Ave). A sample mean with
    # no dispersion invites a ranking the sample cannot support; printing +-SEM makes the
    # comparison's actual resolution visible instead of leaving it to a caveat in prose.
    print(f"\n  {'variant':<12} {'N':>5} {'TM +- SEM':>16} {'TO +- SEM':>16} {'Ave +- SEM':>16}")
    print(f"  {'-' * 70}")
    for variant in VARIANTS:
        rows = results.get(variant, [])
        if not rows:
            continue
        cells = []
        for index in range(3):
            values = [r[index] for r in rows]
            mean = sum(values) / len(values)
            sem = (
                statistics.stdev(values) / len(values) ** 0.5 if len(values) > 1 else float("nan")
            )
            cells.append(f"{mean:>8.1f} +-{sem:>5.1f}")
        print(f"  {variant:<12} {len(rows):>5} " + " ".join(cells))
    for variant, count in timeouts.items():
        if count:
            print(f"  {variant}: {count} page(s) timed out and are excluded from its row")

    print("\n  the nine English participants of 2007, same metric, all 681 pages")
    print(f"  {'group':<14} {'TM':>8} {'TO':>8} {'Ave':>8}")
    print(f"  {'-' * 40}")
    for group, tm, to, ave in PUBLISHED:
        print(f"  {group:<14} {tm:>8.1f} {to:>8.1f} {ave:>8.1f}")
    print("  (participant names omitted on purpose -- see PUBLISHED in this file)")
    print("  Their column is the full corpus; ours is a sample, so read the comparison as")
    print("  a range check and not a ranking.")


# --------------------------------------------------------------------------------------


def pairs(corpus: Path) -> tuple[list[str], int]:
    """Page ids present in both directories, and how many inputs lack a gold standard."""
    inputs = {p.stem for p in (corpus / "finalrun-input").glob("*.html")}
    gold = {p.stem for p in (corpus / "GoldStandard").glob("*.txt")}
    if not inputs or not gold:
        raise SystemExit(f"expected finalrun-input/ and GoldStandard/ under {corpus}")
    return sorted(inputs & gold, key=lambda s: (len(s), s)), len(inputs - gold)


def run(
    corpus: Path,
    *,
    jobs: int,
    limit: int | None,
    official: int,
    seed: int,
    timeout: int,
    do_validate: bool,
) -> None:
    page_ids, missing_gold = pairs(corpus)
    if limit:
        page_ids = page_ids[:limit]
    golds = {
        pid: (corpus / "GoldStandard" / f"{pid}.txt").read_bytes() for pid in page_ids
    }
    print(f"{len(page_ids)} input/gold pairs under {corpus}", file=sys.stderr)

    if do_validate:
        sample = [(pid, golds[pid].decode("latin-1")) for pid in page_ids[:120]]
        if not validate(corpus, sample):
            raise SystemExit(1)

    outcomes: dict[str, PageOutcome] = {}
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        tasks = [(corpus, pid) for pid in page_ids]
        for done, outcome in enumerate(pool.map(_extract_star, tasks, chunksize=4), 1):
            outcomes[outcome.page_id] = outcome
            if done % 100 == 0:
                print(f"  extracted {done}/{len(tasks)}", file=sys.stderr)

    # Pages that failed to parse are scored as the empty string, not skipped: dropping them
    # would raise the mean by removing the hardest pages from it.
    scores = {v: Aggregate() for v in VARIANTS}
    plain_scores = {v: Aggregate() for v in VARIANTS}
    for pid in page_ids:
        gold = golds[pid].decode("latin-1")
        outcome = outcomes.get(pid)
        for variant in VARIANTS:
            tagged = (outcome.tagged[variant] if outcome else "").encode("utf-8").decode("latin-1")
            plain = (outcome.plain[variant] if outcome else "").encode("utf-8").decode("latin-1")
            scores[variant].add(evert_score(corpus, tagged, gold))
            plain_scores[variant].add(evert_score(corpus, plain, gold))

    report(scores, plain_scores, outcomes, len(page_ids), missing_gold)

    if official:
        scorer = corpus / "cleaneval.prl"
        if not scorer.exists():
            print(f"\n  no cleaneval.prl under {corpus} -- official TM/TO/Ave not run")
            return
        rng = random.Random(seed)
        sample = sorted(rng.sample(page_ids, min(official, len(page_ids))))
        print(f"\nrunning cleaneval.prl over {len(sample)} pages x {len(VARIANTS)} variants",
              file=sys.stderr)
        results: dict[str, list[tuple[float, float, float]]] = {v: [] for v in VARIANTS}
        timeouts = {v: 0 for v in VARIANTS}
        work = [
            (scorer, v, pid, outcomes[pid].tagged[v] if pid in outcomes else "", golds[pid], timeout)
            for v in VARIANTS
            for pid in sample
        ]
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for done, (variant, row) in enumerate(pool.map(_official_star, work, chunksize=1), 1):
                if row is None:
                    timeouts[variant] += 1
                else:
                    results[variant].append(row)
                print(f"  perl {done}/{len(work)}", file=sys.stderr)
        report_official(results, sample, timeouts)


def _official_star(
    args: tuple[Path, str, str, str, bytes, int],
) -> tuple[str, tuple[float, float, float] | None]:
    scorer, variant, _page_id, prediction, gold, timeout = args
    return variant, perl_score(scorer, prediction, gold, timeout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(os.environ.get("CLEANEVAL_CORPUS", "benchmark/cleaneval/corpus")),
        help="directory holding finalrun-input/, GoldStandard/, cleaneval.py, cleaneval.prl",
    )
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    parser.add_argument("--limit", type=int, default=None, help="first N pages, for a smoke run")
    parser.add_argument(
        "--official", type=int, default=0, metavar="N",
        help="also run cleaneval.prl for TM/TO/Ave over N sampled pages (slow: ~70s each)",
    )
    parser.add_argument("--seed", type=int, default=20070607, help="sample seed for --official")
    parser.add_argument("--timeout", type=int, default=1200, help="per-pair Perl timeout, seconds")
    parser.add_argument("--validate", action="store_true", help="identity-test the scorer first")
    args = parser.parse_args()
    run(
        args.corpus.resolve(),
        jobs=args.jobs,
        limit=args.limit,
        official=args.official,
        seed=args.seed,
        timeout=args.timeout,
        do_validate=args.validate,
    )
