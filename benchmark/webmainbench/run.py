r"""Score the engine on WebMainBench, the only corpus here that scores tables and code apart.

Why this benchmark and not another
----------------------------------
Every other content measurement in this tree scores one number over one blob of text.
`benchmark/content_quality` scores against a *vote of trafilatura, readability and jusText*;
`benchmark/article_extraction` scores 4-gram shingles against a prose `articleBody`; WCXB
scores a bag of `\w+` tokens. All three are structurally blind to the thing this engine
spends most of its code on, and worse than blind -- actively misleading about it:

* jusText drops `<pre>` entirely, so a code block the engine keeps is a *precision loss*
  against the vote.
* trafilatura's text mode collapses newlines and indentation inside code, so faithful code
  is scored as a mismatch even when both tools "found" it.
* a `\w+` bag cannot tell `| a | b |` from `a b`, so getting a table's *structure* right
  earns exactly nothing, and getting it wrong costs exactly nothing.

WebMainBench splits the score by content type -- `text_edit`, `code_edit`, `formula_edit`,
`table_edit` and `table_TEDS` -- against Markdown ground truth annotated element-by-element
on the original HTML (`cc-select="true"`). It is the instrument that can see the work.

Obtain it with

    git clone --depth 1 https://github.com/opendatalab/WebMainBench   # Apache-2.0
    huggingface-cli download opendatalab/WebMainBench --repo-type dataset \
        --include 'WebMainBench_545.jsonl' --local-dir <corpus>/data

and point `--corpus` at the clone, `--dataset` at the jsonl. Deliberately not vendored: the
545-sample file alone is 109 MB of someone else's data on someone else's release cadence.

Which leaderboard row is the target -- read this before quoting a number
-----------------------------------------------------------------------
The project README publishes **two tables that are not comparable**, and it is very easy to
splice them into a single fake row. They are:

1. *ROUGE-N F1 on the full 7,809* -- magic-html 0.7138, Readability 0.6543, Trafilatura
   0.6402, Resiliparse 0.6290. A single whole-document similarity, no type breakdown. Its
   pipeline lives in the separate MinerU-HTML repo (`eval_baselines.py`), not here.
2. *Fine-grained edit distance on the 545 calibrated subset* -- mineru-html **0.8256**,
   magic-html **0.4996**, trafilatura(md) **0.4013**, trafilatura(txt) 0.3718, resiliparse
   **0.2898**. Five type columns plus their mean.

`overall` in this runner is table 2. Comparing it to 0.7138 or 0.6402 is comparing a
five-way type average to a ROUGE score; the baselines on *this* metric sit near 0.29-0.50,
and mineru-html's 0.8256 is the only number in the brief's "leaderboard" that belongs here.
Only the 545 subset carries `groundtruth_content`, which is why the fine-grained metrics are
545-only; the full 7,809 has `main_html`/`convert_main_content` instead. Note also that the
companion paper is **arXiv:2511.23119** (*Dripper*), which is what the README badge cites.

Why the metric is imported rather than reimplemented
----------------------------------------------------
`MetricCalculator` is imported out of the clone. Nothing here recomputes edit distance or
TEDS. Doing so would have been a trap, because the shipped code does three things no
reimplementation from the README would:

* **`text_edit` is not "text minus code/tables/formulas"**, despite the class docstring
  saying exactly that. With no `content_list` on either side, `BaseMetric.split_content`
  falls through to `_extract_from_markdown`, whose `text` key is `text` -- *the whole
  markdown, unmodified*. So `text_edit` is whole-document character similarity, and the
  code/table/formula columns overlap it rather than partitioning it.
* **Empty-vs-empty is a `success=False` result, not a 1.0.** `EditDistanceMetric` returns
  `create_error_result` when `max_len == 0`, and `aggregate_results` keeps only successes.
  So a page with no table on either side silently leaves the `table_edit` mean, and
  `table_TEDS` follows it out because it is skipped when `table_edit` failed. **Every
  column therefore has a different N**, and this runner prints N per column. A `table_TEDS`
  over 90 table-bearing pages means something very different from one over 545.
* **`overall` is a per-sample mean, then averaged** -- not the mean of the five column
  means. The two differ whenever columns have different N, which is always. The published
  mineru-html row is the proof: its five columns average 0.8656 but its `overall` is 0.8256.

Importing `webmainbench.metrics` naively fails: the package `__init__` pulls in the
extractor registry, which imports trafilatura, resiliparse, magic_html and torch. This
runner registers a stub parent module with the right `__path__` so the metric subpackage
imports without any of that. Licence chain inherited by doing so: apted (MIT), rapidfuzz
(MIT), beautifulsoup4 (MIT), jieba (MIT). No IBM PubTabNet `TEDS.py` (NOASSERTION), no
`table-recognition-metric` (pulls GPL-2.0 `Levenshtein`). All are `bench`-group deps; the
engine's runtime dependency list is untouched.

Markdown, not plain text -- and this is the *opposite* of the sibling runners
-----------------------------------------------------------------------------
`benchmark/article_extraction` and `benchmark/wcxb` both feed the scorer `document.text`,
because their metrics tokenise on `\w+` and Markdown syntax would be charged as false-
positive words. **Here the reverse holds.** The metric is character-level Levenshtein, the
ground truth is Markdown (`##` headings, ``` fences, `|` tables, `$` math), and the
splitters key on precisely that syntax: `CodeSplitter` finds ``` fences and 4-space
indents, `TableSplitter` finds `|` rows and `<table>`. Feed this scorer plain text and
`code_edit`, `table_edit` and `table_TEDS` are **0.0 by construction** -- which is exactly
how resiliparse, the one TEXT-mode system on the board, scores 0.0000 on both table
columns. So every variant here is `to_markdown()`.

Links and images are off, and that is not a guess. The ground truth contains a markdown
link in **1 of 545 documents** (0.02% of ground-truth characters) and an image in 4. Under
a character-level edit distance every `](https://…)` is pure inserted cost, and because
`text_edit` is the whole document it moves `overall`, not just a side column. This is the
`include_links=True` trap from `benchmark/article_extraction` in its most expensive form.
Independently confirmed against the corpus rather than argued: the clone's *own*
`TrafilaturaExtractor` -- which produced the published 0.4013 row -- sets
`include_images=False, include_links=False, output_format="markdown"`. `--ablate-links`
measures the cost rather than asserting it.

Offline deviation from the published protocol, stated loudly
------------------------------------------------------------
The published 545 numbers were produced with `USE_LLM=true`, which routes extracted spans
through DeepSeek to strip currency (`$1,150.00`) from the formula bucket. This runner forces
`use_llm: False` and is fully offline. Scope of the deviation: `CodeSplitter.extract` and
`TableSplitter.extract` never call the LLM path at all (both call `extract_basic` directly,
and their `_llm_enhance` is the identity), so **code, table and TEDS are unaffected** and
`text_edit` is unaffected. Only `formula_edit` changes. It changes *symmetrically* --
`split_content` is called without `field_name`, so `should_use_llm(None)` is True for the
prediction and the ground truth alike, and disabling it disables both sides -- but a
regex-only formula bucket keeps `$`-delimited currency on both sides, and 53.8% of the
ground-truth documents contain a `$`. Read `formula_edit` as "regex-delimited math-ish
spans", not as the published column. Passing `use_llm: False` explicitly also matters
mechanically: left truthy with no API key, `enhance_with_llm` still writes one cache file
per call into the clone's `.cache/`, seeding thousands of files that a later run *with* a
key would read back as genuine LLM output.

What this benchmark cannot see
-------------------------------
Cached static HTML, no network, one page at a time. That switches off two of the three
things this engine does that a single-pass DOM extractor does not:

* **Geometric reading order** needs a browser render for box geometry. Offline every
  document falls back to DOM order; the run prints the `reading_order_method` distribution
  so the claim is checked rather than asserted.
* **Cross-page chrome detection** needs six or more pages from one site. The 545 subset is
  drawn from 5,434 unique domains across the full set; the run prints how many domains
  clear the threshold, which is approximately none.

`strip_landmarks` survives, because it works on one page. So the three variants below are
the whole of what this benchmark can measure about this engine.

Usage
-----
    uv run --package webgraph python benchmark/webmainbench/run.py \
        --corpus <clone> --dataset <clone>/data/WebMainBench_545.jsonl
    … --calibrate            # also score trafilatura(md) and resiliparse, same harness
    … --ablate-links         # cost of include_links/include_images, measured
    … --worst table_TEDS     # lowest-scoring pages of one column
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import types
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from webgraph.types import Block, Document

VARIANTS: Final[tuple[str, ...]] = ("raw", "landmarks", "prose")
"""The three ways to turn a parsed document into Markdown.

`raw` is every block the parser found, in reading order. `landmarks` is that with `<nav>`
and `<footer>` subtrees dropped -- the shipped single-page default. `prose` keeps only
PARAGRAPH/HEADING/LIST_ITEM/QUOTE.

**`prose` is reported for consistency with the sibling runners, not because it is a
candidate here.** It excludes CODE and TABLE by construction, so its `code_edit`,
`table_edit` and `table_TEDS` columns are 0.0 on every page where the ground truth has one
-- the same shape as resiliparse's published 0.0000/0.0000. That is arithmetic, not a
finding, and it makes `prose`'s `overall` incomparable to the leaderboard. It is printed so
the cost of the filter is visible rather than hidden.
"""

PROSE_KINDS: Final[frozenset[str]] = frozenset(
    {"paragraph", "heading", "list-item", "quote"}
)

METRICS: Final[tuple[str, ...]] = (
    "overall",
    "text_edit",
    "code_edit",
    "formula_edit",
    "table_edit",
    "table_TEDS",
)
"""Column order copied from `examples/run_545_leaderboard.py` so the two print alike."""

PUBLISHED_545: Final[dict[str, dict[str, float]]] = {
    # From the README's "Fine-Grained Metrics on 545-Sample Subset" table. The authors'
    # numbers, printed for side-by-side reading only. mineru-html's row is also the check
    # that this runner's aggregation is right: these five columns average 0.8656 while the
    # published `overall` is 0.8256, because `overall` is a per-sample mean over columns
    # with different N. A runner whose `overall` equalled its column mean would be wrong.
    "mineru-html": {
        "overall": 0.8256, "text_edit": 0.8621, "code_edit": 0.9093,
        "formula_edit": 0.9399, "table_edit": 0.6780, "table_TEDS": 0.7388,
    },
    "magic-html": {
        "overall": 0.4996, "text_edit": 0.7800, "code_edit": 0.4150,
        "formula_edit": 0.6385, "table_edit": 0.2638, "table_TEDS": 0.4006,
    },
    "trafilatura(md)": {
        "overall": 0.4013, "text_edit": 0.7826, "code_edit": 0.1801,
        "formula_edit": 0.6237, "table_edit": 0.1202, "table_TEDS": 0.2999,
    },
    "trafilatura(txt)": {
        "overall": 0.3718, "text_edit": 0.7819, "code_edit": 0.0000,
        "formula_edit": 0.6389, "table_edit": 0.1278, "table_TEDS": 0.3106,
    },
    "resiliparse": {
        "overall": 0.2898, "text_edit": 0.7435, "code_edit": 0.0422,
        "formula_edit": 0.6631, "table_edit": 0.0000, "table_TEDS": 0.0000,
    },
}


def load_calculator(corpus: Path) -> Any:
    """Import `MetricCalculator` from the clone without executing its package `__init__`.

    The real `webmainbench/__init__.py` imports the extractor registry, which imports
    trafilatura, resiliparse, magic_html and torch -- none of which the *metric* code needs.
    Registering a stub parent with the correct `__path__` lets `webmainbench.metrics.*`
    resolve its relative imports (`from ..config import LLM_CONFIG`) against the real
    directory while the heavy `__init__` never runs. `spec_from_file_location` on a single
    file, as `benchmark/wcxb/run.py` does, cannot work here: these modules are a package.
    """
    package = corpus / "webmainbench"
    if not (package / "metrics" / "calculator.py").is_file():
        raise SystemExit(f"no webmainbench/metrics under {corpus} -- is that a clone?")

    if str(corpus) not in sys.path:
        sys.path.insert(0, str(corpus))
    if "webmainbench" not in sys.modules:
        stub = types.ModuleType("webmainbench")
        stub.__path__ = [str(package)]  # type: ignore[attr-defined]
        sys.modules["webmainbench"] = stub
    _stub_openai()

    from webmainbench.metrics.calculator import MetricCalculator

    return MetricCalculator


def _stub_openai() -> None:
    """Satisfy `base_content_splitter`'s unconditional `from openai import OpenAI`.

    The import is module-level; the *use* is not -- `OpenAI(...)` is constructed only inside
    `if self.use_llm and config['llm_base_url'] and config['llm_api_key']`, and this runner
    passes `use_llm: False`. Rather than adding an LLM SDK to a deliberately offline
    benchmark's dependency list, a stub stands in, and its `OpenAI` **raises**. That makes
    the offline claim checkable instead of merely stated: if any code path ever did reach
    for a client, this run would abort rather than quietly turn into a networked one.

    Skipped entirely if the real `openai` is installed, so nothing is shadowed.
    """
    if "openai" in sys.modules:
        return
    try:
        import openai  # noqa: F401
    except ImportError:
        pass
    else:
        return

    def _forbidden(*args: object, **kwargs: object) -> object:
        raise RuntimeError(
            "the WebMainBench runner is offline (use_llm=False) and must not build an "
            "LLM client -- see load_calculator"
        )

    stub = types.ModuleType("openai")
    stub.OpenAI = _forbidden  # type: ignore[attr-defined]
    sys.modules["openai"] = stub


def markdown(document: Document, blocks: Sequence[Block], *, links: bool) -> str:
    """Render a block subset as Markdown through the engine's own renderer.

    Goes through `to_markdown` rather than joining strings so that fences, pipe rows and
    heading hashes are produced by shipped code -- the benchmark is meant to measure the
    renderer, not a benchmark-local imitation of it.
    """
    from webgraph.render_markdown import MarkdownOptions, to_markdown

    view = document.model_copy(update={"blocks": tuple(blocks)})
    return to_markdown(
        view, options=MarkdownOptions(include_links=links, include_images=links)
    )


@dataclass(slots=True)
class PageOutcome:
    """What one cached page produced, before it is scored."""

    track_id: str
    texts: dict[str, str]
    blocks: int
    reading_order: str
    host: str
    error: str | None = None


def main_content_selector() -> Any:
    """`select_main_content` if this tree has it, else None.

    Optional because it is a newer, opt-in entry point: `build_document` does not call it and
    `Document.blocks` stays complete. It is reported here because this benchmark's ground
    truth *is* main content, so the selector is the direct answer to the column the three
    standard variants are weakest on -- but guarded, so the runner still works in a tree
    that predates it.
    """
    try:
        from webgraph.main_content import select_main_content
    except ImportError:
        return None
    return select_main_content


def extract(record: dict, *, links: bool = False) -> PageOutcome:
    """Parse one cached page and derive every variant from the single parse."""
    from webgraph.boilerplate import strip_landmarks
    from webgraph.pipeline import build_document

    track_id = record["track_id"]
    host = urlsplit(record.get("url") or "").netloc
    select = main_content_selector()
    names = (*VARIANTS, "main-content") if select else VARIANTS
    empty = dict.fromkeys(names, "")
    try:
        document = build_document(record["html"], record.get("url") or "https://example.invalid/")
    except Exception as exc:  # noqa: BLE001 -- a crash is a result, not a reason to stop
        return PageOutcome(track_id, empty, 0, "none", host, f"{type(exc).__name__}: {exc}")

    blocks = list(document.blocks)
    kept = strip_landmarks(blocks)
    texts = {
        "raw": markdown(document, blocks, links=links),
        "landmarks": markdown(document, kept, links=links),
        "prose": markdown(
            document, [b for b in blocks if b.kind.value in PROSE_KINDS], links=links
        ),
    }
    if select:
        # `strip_landmarks` first, then the selector -- the composition the selector was
        # tuned as on Zyte. Running the selector over the raw list makes it re-derive
        # nav/footer removal from link density alone, which is a different system.
        texts["main-content"] = markdown(document, select(kept), links=links)
    return PageOutcome(
        track_id=track_id,
        texts=texts,
        blocks=len(blocks),
        reading_order=document.reading_order_method.value,
        host=host,
    )


@dataclass(slots=True)
class Column:
    """One metric's surviving per-page scores.

    Only `success=True` results land here, mirroring `BaseMetric.aggregate_results`. The
    count is carried because it is not 545 and differs per column -- see the module
    docstring.
    """

    scores: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    def __len__(self) -> int:
        return len(self.scores)


@contextmanager
def time_limit(seconds: int) -> Iterator[None]:
    """Raise inside the scorer if one page takes longer than `seconds`.

    Needed because APTED is superlinear and this corpus contains tables far outside the size
    it was meant for. One ground-truth "table" -- hcqyfuwu.com/261.html, row 69 -- parses to
    a **24,216-node** tree, because the annotators kept a legacy nested layout table as main
    content. A tree edit distance against that does not finish in any useful time, and an
    unguarded run wedges on it forever with no output at all.

    This is deliberately *not* a change to the metric. `TEDSMetric._tree_edit_distance`
    already wraps its APTED call in `except Exception` and falls back to the node-count
    difference, and its module docstring names the reason: "When apted fails (e.g. excessive
    nesting), falls back to node count difference, ensuring batch evaluation is not
    interrupted." The authors anticipated this exact case but keyed the fallback on an
    exception APTED never raises -- it simply runs. Interrupting it turns a hang into the
    fallback its authors intended. The run prints how many pages took that path, because a
    fallback distance is a different quantity from a true edit distance and a reader is
    entitled to know how many rows are one rather than the other.
    """

    def handler(signum: int, frame: object) -> None:
        raise TimeoutError(f"page exceeded {seconds}s")

    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def score_texts(
    calculator: Any, records: Sequence[dict], texts: dict[str, str], *, budget: int = 90
) -> tuple[dict[str, dict[str, float]], set[str]]:
    """Score one system's predictions over the corpus with the corpus's own calculator.

    Returns the per-page scores and the set of pages that blew the wall-clock budget.

    **The timed-out set is returned rather than swallowed, and that is the whole point.**
    An earlier version dropped a timed-out page from that system's columns and moved on,
    which is wrong twice: it raises the mean by deleting the hardest page from it, and
    because SIGALRM is *wall-clock* it deletes a different page depending on machine load,
    so two runs of identical code produce different tables. That was observed here -- the
    `main-content` row read 0.3396 and 0.3315 on back-to-back invocations of the same
    commit over the same 20 pages. Whatever page trips the budget must therefore be removed
    from **every** system or from none, which is a decision the caller can only take once
    all systems have run. Hence: report, do not resolve.
    """
    per_page: dict[str, dict[str, float]] = {}
    timed_out: set[str] = set()
    for record in records:
        track_id = record["track_id"]
        try:
            with time_limit(budget):
                results = calculator.calculate_all(
                    predicted_content=texts.get(track_id, ""),
                    groundtruth_content=record["groundtruth_content"],
                    predicted_content_list=None,
                    groundtruth_content_list=None,
                )
        except TimeoutError:
            timed_out.add(track_id)
            per_page[track_id] = {}
            continue
        page: dict[str, float] = {}
        for name in METRICS:
            result = results.get(name)
            if result is not None and result.success:
                page[name] = result.score
        per_page[track_id] = page
    if timed_out:
        print(f"    {len(timed_out)} page(s) hit the {budget}s scoring budget", file=sys.stderr)
    return per_page, timed_out


def columns_from(
    per_page: dict[str, dict[str, float]], excluded: frozenset[str]
) -> dict[str, Column]:
    """Rebuild the aggregate columns from per-page scores, minus a shared exclusion set.

    Equivalent to `BaseMetric.aggregate_results` -- only successes are present in `per_page`
    to begin with -- except that the same pages are dropped from every system, so the rows
    of the printed table stay comparable to each other.
    """
    columns = {name: Column() for name in METRICS}
    for track_id, scores in per_page.items():
        if track_id in excluded:
            continue
        for name, value in scores.items():
            columns[name].scores.append(value)
    return columns


def cache_path(directory: Path, label: str) -> Path:
    return directory / f"{label.replace('/', '-').replace(' ', '_')}.json"


def save_scores(
    directory: Path, label: str, per_page: dict[str, dict[str, float]], timed_out: set[str]
) -> None:
    """Persist one system's scores the moment it finishes.

    A full run is six systems over 545 pages and the report prints only at the very end, so
    an interruption at system five used to lose all five. The previous session's log ends at
    `extracted 545/545` with no scored row surviving, which is exactly that failure.
    """
    directory.mkdir(parents=True, exist_ok=True)
    cache_path(directory, label).write_text(
        json.dumps({"per_page": per_page, "timed_out": sorted(timed_out)}),
        encoding="utf-8",
    )


def load_scores(
    directory: Path, label: str
) -> tuple[dict[str, dict[str, float]], set[str]] | None:
    path = cache_path(directory, label)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["per_page"], set(payload["timed_out"])


def _row(label: str, columns: dict[str, Column], *, width: int = 18) -> str:
    cells = "".join(f"{columns[name].mean:>13.4f}" for name in METRICS)
    return f"  {label:<{width}}{cells}"


def _counts(columns: dict[str, Column], *, width: int = 18) -> str:
    cells = "".join(f"{len(columns[name]):>13,}" for name in METRICS)
    return f"  {'N (scored)':<{width}}{cells}"


def header(width: int = 18) -> str:
    cells = "".join(f"{name:>13}" for name in METRICS)
    return f"  {'system':<{width}}{cells}\n  {'-' * (width + 13 * len(METRICS))}"


def report(
    results: dict[str, dict[str, Column]],
    outcomes: dict[str, PageOutcome],
    records: Sequence[dict],
) -> None:
    print(f"\n{'=' * 96}")
    print(
        f"WebMainBench 545-sample calibrated subset -- {len(records)} pages, "
        "engine offline over cached HTML"
    )
    print("Markdown in, links and images off. Fine-grained edit-distance protocol.\n")

    print(header())
    for label, columns in results.items():
        print(_row(label, columns))
    first = next(iter(results.values()))
    print(_counts(first))
    print(
        "\n  N differs per column by design: a page with no table on either side returns\n"
        "  success=False from the edit-distance metric and leaves the table means entirely.\n"
        "  `overall` is a per-sample mean over that page's surviving columns, then averaged,\n"
        "  so it is NOT the mean of this row -- see the module docstring."
    )

    print("\n\n  Against the README's 545-subset table (the authors' numbers, not ours --")
    print("  this runner has executed no system other than the ones labelled below)")
    print()
    print(header())
    for label, columns in results.items():
        print(_row(label, columns))
    for name, values in PUBLISHED_545.items():
        cells = "".join(f"{values[m]:>13.4f}" for m in METRICS)
        print(f"  {name + ' *':<18}{cells}")
    print(
        "\n  * published. Two reasons the starred rows are a reference and NOT the"
        " comparison:\n"
        "  (a) their per-column N is not published, and N moves with the prediction (a\n"
        "      column counts pages where EITHER side produced that type), so a starred\n"
        "      cell and an unstarred one are means over different page sets;\n"
        "  (b) they were produced with USE_LLM=true, which this offline runner cannot do.\n"
        "  The rows scored HERE -- trafilatura(md) and resiliparse, same calculator, same\n"
        "  settings, same exclusion set -- are the comparison. Run with --calibrate to get\n"
        "  them; without it the engine's numbers are unfalsifiable.\n"
        "  Separately: the ROUGE-N numbers people usually quote for this corpus\n"
        "  (magic-html 0.7138, trafilatura 0.6402, resiliparse 0.6290) are a DIFFERENT\n"
        "  metric on the full 7,809 and do not belong in this table at all."
    )

    _report_blindspots(outcomes, records)


def _report_blindspots(outcomes: dict[str, PageOutcome], records: Sequence[dict]) -> None:
    """Print the evidence for the module docstring's "cannot see" claims."""
    parsed = [o for o in outcomes.values() if not o.error]
    failures = [o for o in outcomes.values() if o.error]
    orders = Counter(o.reading_order for o in parsed)
    hosts = Counter(o.host for o in parsed if o.host)
    clustered = sum(1 for count in hosts.values() if count >= 6)
    empties = sum(1 for o in parsed if o.blocks == 0)

    print(f"\n\n  What this run could not exercise\n  {'-' * 60}")
    print(f"  parse failures: {len(failures)}; parsed to zero blocks: {empties}")
    print(f"  reading_order_method: {dict(orders)}")
    print(
        "    every document is DOM order -- geometric ordering needs a browser render for\n"
        "    box geometry, and this corpus is cached HTML with no network."
    )
    print(
        f"  distinct hosts: {len(hosts)} over {len(parsed)} pages; "
        f"{clustered} host(s) reach the 6-page threshold"
    )
    print(
        "    cross-page chrome detection is structurally unavailable, not merely unused."
    )
    if failures:
        for outcome in failures[:5]:
            print(f"    {outcome.track_id}: {outcome.error}")

    meta = Counter()
    for record in records:
        for key in ("table", "code", "equation"):
            if record.get("meta", {}).get(key):
                meta[key] += 1
    print(
        f"\n  annotator labels over {len(records)} pages: "
        f"table {meta['table']}, code {meta['code']}, equation {meta['equation']}"
    )
    print(
        "    compare against the N row above: the splitters are regex/BeautifulSoup over\n"
        "    Markdown, so they do not agree with the annotators, and a column's N is the\n"
        "    number of pages where EITHER side produced that content type."
    )


SEGMENTS: Final[tuple[str, ...]] = (
    "simple", "mid", "hard", "has table", "has code", "has formula", "prose only"
)
"""Page slices, from the annotators' own `meta`.

The brief that commissioned this run asked whether the main-content selector "helps or hurts
on non-article page types". The corpus does not label page type -- `meta['style']` is `None`
on all 545 -- so the available cuts are the annotators' difficulty `level` and their
content-type flags. `prose only` is the complement: no table, no code, no equation, which is
as close to "plain article" as this corpus gets. That is the column to read the selector on.
"""


def segments_of(record: dict) -> list[str]:
    meta = record.get("meta") or {}
    names = [meta.get("level") or "?"]
    for key, label in (("table", "has table"), ("code", "has code"), ("equation", "has formula")):
        if meta.get(key):
            names.append(label)
    if not any(meta.get(k) for k in ("table", "code", "equation")):
        names.append("prose only")
    return names


def segment_report(
    pages: dict[str, dict[str, dict[str, float]]],
    records: Sequence[dict],
    excluded: frozenset[str],
    metric: str = "overall",
) -> None:
    """Break one metric down by page slice, so a single mean cannot hide a bimodal system.

    Computed from the same per-page scores the main table aggregates, not a second run.
    """
    members: dict[str, list[str]] = {name: [] for name in SEGMENTS}
    for record in records:
        if record["track_id"] in excluded:
            continue
        for name in segments_of(record):
            if name in members:
                members[name].append(record["track_id"])

    print(f"\n\n  `{metric}` by page slice (annotators' `meta`; slices overlap)")
    width = 22
    head = "".join(f"{name:>13}" for name in SEGMENTS)
    print(f"  {'system':<{width}}{head}")
    print(f"  {'-' * (width + 13 * len(SEGMENTS))}")
    for label, per_page in pages.items():
        cells = ""
        for name in SEGMENTS:
            values = [
                per_page[tid][metric]
                for tid in members[name]
                if tid in per_page and metric in per_page[tid]
            ]
            cells += f"{sum(values) / len(values):>13.4f}" if values else f"{'--':>13}"
        print(f"  {label:<{width}}{cells}")
    counts = "".join(f"{len(members[name]):>13,}" for name in SEGMENTS)
    print(f"  {'N (pages)':<{width}}{counts}")


def worst_pages(
    per_page: dict[str, dict[str, float]],
    records: Sequence[dict],
    outcomes: dict[str, PageOutcome],
    metric: str,
    variant: str,
    limit: int,
) -> None:
    """List the lowest-scoring pages of one column so a weak number can be read."""
    by_id = {r["track_id"]: r for r in records}
    rows = [
        (scores[metric], track_id)
        for track_id, scores in per_page.items()
        if metric in scores
    ]
    rows.sort()
    print(f"\n\n  worst {limit} pages on `{metric}` for the `{variant}` variant")
    print(f"  {'score':>7}  {'ours':>8} {'truth':>8}  url")
    print(f"  {'-' * 86}")
    for value, track_id in rows[:limit]:
        record = by_id[track_id]
        outcome = outcomes.get(track_id)
        ours = len(outcome.texts[variant]) if outcome else 0
        print(
            f"  {value:>7.4f}  {ours:>8,} {len(record['groundtruth_content']):>8,}  "
            f"{record.get('url', '')[:66]}"
        )
        print(f"           track_id={track_id}  meta={record.get('meta', {})}")


def calibrate(records: Sequence[dict]) -> dict[str, dict[str, str]]:
    """Run trafilatura and resiliparse through this harness, to check the harness.

    Without this every webgraph number is unfalsifiable: a low `table_TEDS` could equally
    mean the engine is weak on tables or that the scorer was fed the wrong shape. These two
    systems have published rows on exactly this metric, so reproducing them near 0.4013 and
    0.2898 is what licenses reading the engine's row at all.

    Configured to match the clone's own extractors, which produced the published numbers:
    `TrafilaturaExtractor` sets markdown output with links and images off; the resiliparse
    extractor is plain text, which is why its published table columns are 0.0000.
    """
    texts: dict[str, dict[str, str]] = {"trafilatura(md)": {}, "resiliparse": {}}
    from resiliparse.extract.html2text import extract_plain_text
    from resiliparse.parse.html import HTMLTree
    from trafilatura import extract as trafilatura_extract

    for record in records:
        html, track_id = record["html"], record["track_id"]
        try:
            content = trafilatura_extract(
                html,
                url=record.get("url"),
                favor_precision=False,
                favor_recall=False,
                include_comments=True,
                include_tables=True,
                include_images=False,
                include_links=False,
                with_metadata=False,
                output_format="markdown",
            )
        except Exception:  # noqa: BLE001 -- a crash is a result
            content = ""
        texts["trafilatura(md)"][track_id] = content or ""
        try:
            texts["resiliparse"][track_id] = extract_plain_text(
                HTMLTree.parse(html), main_content=True
            )
        except Exception:  # noqa: BLE001
            texts["resiliparse"][track_id] = ""
    return texts


def ablate_links(calculator: Any, records: Sequence[dict]) -> None:
    """Measure what links and images cost, rather than asserting it.

    The sibling `benchmark/article_extraction` documents this trap costing a *comparison*.
    Here it would cost the headline: `text_edit` is the whole markdown document, so inserted
    `](https://…)` spans move `overall` directly.
    """
    print("\n\n  Cost of include_links / include_images, on the `landmarks` variant")
    print(f"  ground truth: 1 of {len(records)} documents contains a markdown link\n")
    print(header(width=22))
    for label, links in (("links+images off", False), ("links+images on", True)):
        texts = {
            outcome.track_id: outcome.texts["landmarks"]
            for outcome in (extract(record, links=links) for record in records)
        }
        per_page, timed_out = score_texts(calculator, records, texts)
        print(_row(label, columns_from(per_page, frozenset(timed_out)), width=22))


def rouge_full(corpus: Path, dataset: Path, *, limit: int | None, stride: int) -> None:
    """Score the full 7,809 file on ROUGE-N F1, the corpus's *other* protocol.

    Different file, different ground-truth field, different metric. The full set carries
    `main_html` and `convert_main_content` and has no `groundtruth_content` at all, which is
    precisely why the fine-grained type columns are 545-only. Reported separately and never
    averaged with them.

    The metric class is the corpus's own `TextRougeNgramMetric` -- ROUGE-N with N=5 over
    jieba tokens, which is what the README describes -- so this is imported, not
    reimplemented. **The pipeline is still not identical to the paper's.** The published
    numbers come from `eval_baselines.py` in the separate MinerU-HTML repo, which normalises
    every extractor's output through `html2text` first. This runner feeds the engine's own
    Markdown straight in. Treat the result as indicative of the engine's standing, not as a
    drop-in replacement for a row in the paper's Table 2.

    `--stride` takes every Nth record rather than the first N: the file is not shuffled, and
    a prefix would sample whatever ordering the release happened to use.
    """
    if str(corpus) not in sys.path:
        load_calculator(corpus)
    from webmainbench.metrics.text_metrics import TextRougeNgramMetric

    metric = TextRougeNgramMetric("rouge_n", {"ngram": 5})
    scores: dict[str, list[float]] = {name: [] for name in VARIANTS}
    by_level: dict[str, list[float]] = {}
    seen = 0
    with dataset.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index % stride or not line.strip():
                continue
            record = json.loads(line)
            truth = record.get("convert_main_content") or ""
            if not truth.strip():
                continue
            outcome = extract(record)
            for name in VARIANTS:
                scores[name].append(
                    metric.calculate(predicted=outcome.texts[name], groundtruth=truth).score
                )
            level = record.get("meta", {}).get("level", "?")
            by_level.setdefault(level, []).append(scores["landmarks"][-1])
            seen += 1
            if seen % 50 == 0:
                print(f"  scored {seen}", file=sys.stderr)
            if limit and seen >= limit:
                break

    def mean(values: Sequence[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    print(f"\n{'=' * 96}")
    print(f"WebMainBench FULL set -- ROUGE-N F1 (N=5, jieba), {seen} pages sampled every {stride}")
    print("A DIFFERENT metric and a different ground-truth field from the 545 table above.")
    print("Metric imported from the corpus; pipeline NOT identical to the paper's (no")
    print("html2text normalisation, which the published eval_baselines.py applies).\n")
    for name in VARIANTS:
        print(f"  webgraph {name:<12} {mean(scores[name]):.4f}")
    print("\n  by annotator difficulty (landmarks variant)")
    for level, values in sorted(by_level.items()):
        print(f"  {level:<12} {len(values):>5}  {mean(values):.4f}")
    print("\n  published on the full 7,809 (authors' numbers, ROUGE-N F1):")
    print("    Dripper 0.8779   magic-html 0.7138   Readability 0.6543")
    print("    Trafilatura 0.6402   Resiliparse 0.6290")


def load_records(dataset: Path, limit: int | None) -> list[dict]:
    records = []
    with dataset.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
            if limit and len(records) >= limit:
                break
    missing = [r for r in records if not r.get("groundtruth_content")]
    if missing:
        raise SystemExit(
            f"{len(missing)} of {len(records)} records have no `groundtruth_content` -- "
            "this looks like the full 7,809 file, which carries `main_html` instead and "
            "is scored by ROUGE-N in the separate MinerU-HTML repo, not by this protocol."
        )
    return records


def run(
    corpus: Path,
    dataset: Path,
    *,
    limit: int | None,
    do_calibrate: bool,
    do_ablate: bool,
    worst: str | None,
    scores_dir: Path,
    resume: bool,
) -> None:
    calculator_cls = load_calculator(corpus)
    # `use_llm: False` is load-bearing twice over -- see the module docstring's protocol
    # deviation note. It also stops `enhance_with_llm` seeding the clone's `.cache/`.
    calculator = calculator_cls({"use_llm": False})

    records = load_records(dataset, limit)
    print(f"{len(records)} ground-truth pages from {dataset}")

    outcomes: dict[str, PageOutcome] = {}
    for index, record in enumerate(records, start=1):
        outcome = extract(record)
        outcomes[outcome.track_id] = outcome
        if index % 50 == 0 or index == len(records):
            print(f"  extracted {index}/{len(records)}", file=sys.stderr)

    variants = tuple(next(iter(outcomes.values())).texts) if outcomes else VARIANTS
    systems: dict[str, dict[str, str]] = {
        f"webgraph {variant}": {tid: o.texts[variant] for tid, o in outcomes.items()}
        for variant in variants
    }
    if do_calibrate:
        systems.update(calibrate(records))

    pages: dict[str, dict[str, dict[str, float]]] = {}
    timed_out: set[str] = set()
    for label, texts in systems.items():
        cached = load_scores(scores_dir, label) if resume else None
        if cached is not None:
            per_page, slow = cached
            print(f"  reused {label} from {cache_path(scores_dir, label).name}", file=sys.stderr)
        else:
            per_page, slow = score_texts(calculator, records, texts)
            print(f"  scored {label}", file=sys.stderr)
        save_scores(scores_dir, label, per_page, slow)
        pages[label] = per_page
        timed_out |= slow

    # One exclusion set for every system, decided only once all of them have run -- see
    # `score_texts`. Applying it per system would make the rows incomparable.
    excluded = frozenset(timed_out)
    results = {label: columns_from(per_page, excluded) for label, per_page in pages.items()}
    if excluded:
        print(
            f"\n  {len(excluded)} page(s) exceeded the scoring budget and are excluded "
            f"from EVERY row: {', '.join(sorted(excluded))}",
        )

    report(results, outcomes, records)
    segment_report(pages, records, excluded, "overall")
    segment_report(pages, records, excluded, "text_edit")

    if worst:
        best = max(variants, key=lambda v: results[f"webgraph {v}"]["overall"].mean)
        worst_pages(pages[f"webgraph {best}"], records, outcomes, worst, best, 4)

    if do_ablate:
        ablate_links(calculator, records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(os.environ.get("WEBMAINBENCH_CORPUS", "benchmark/webmainbench/corpus")),
        help="path to an opendatalab/WebMainBench clone (default: $WEBMAINBENCH_CORPUS)",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="WebMainBench_545.jsonl (default: <corpus>/data/WebMainBench_545.jsonl)",
    )
    parser.add_argument("--limit", type=int, default=None, help="first N pages, for a smoke run")
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="also score trafilatura(md) and resiliparse through this same harness",
    )
    parser.add_argument(
        "--ablate-links",
        action="store_true",
        help="measure what include_links/include_images costs on this metric",
    )
    parser.add_argument(
        "--worst", default=None, choices=METRICS, help="list the lowest-scoring pages"
    )
    parser.add_argument(
        "--rouge",
        action="store_true",
        help="score the FULL 7,809 file on ROUGE-N instead (needs webmainbench.jsonl)",
    )
    parser.add_argument(
        "--stride", type=int, default=1, help="with --rouge, take every Nth record"
    )
    parser.add_argument(
        "--scores-dir",
        type=Path,
        default=Path(".scores"),
        help="where per-system scores are written as each system finishes (default: .scores)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse any per-system scores already in --scores-dir instead of rescoring",
    )
    args = parser.parse_args()
    corpus = args.corpus.resolve()
    default = "webmainbench.jsonl" if args.rouge else "WebMainBench_545.jsonl"
    dataset = (args.dataset or corpus / "data" / default).resolve()
    if not dataset.is_file():
        parser.error(f"{dataset} not found -- download it from the HF dataset repo")
    if args.rouge:
        rouge_full(corpus, dataset, limit=args.limit, stride=args.stride)
        raise SystemExit(0)
    run(
        corpus,
        dataset,
        limit=args.limit,
        do_calibrate=args.calibrate,
        do_ablate=args.ablate_links,
        worst=args.worst,
        scores_dir=args.scores_dir.resolve(),
        resume=args.resume,
    )
