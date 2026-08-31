"""Run the extraction engine over a labelled corpus and score it.

This is the development harness and the benchmark, deliberately the same thing. A benchmark
maintained separately from the thing it measures drifts out of date; one that *is* the test
loop cannot.

Corpus format -- a directory containing `gold.json`:

    {
      "cases": [
        {
          "id": "product-jsonld",
          "url": "https://example.com/widget",
          "html": "pages/widget.html",
          "site_type": "ecommerce",
          "schema": { "type": "object", "properties": { ... } },
          "expected": { "name": "Widget", "offers.price": 49.0 }
        }
      ]
    }

HTML is stored as a local snapshot rather than re-fetched. Live pages change, and a
benchmark whose answers change underneath it measures nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webgraph.eval.metrics import PageScore, RunScore, score_page, score_run
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.pipeline import build_document
from webgraph.types import Rect

__all__ = ["GoldCase", "format_report", "load_corpus", "run_case", "run_corpus"]


@dataclass(frozen=True, slots=True)
class GoldCase:
    id: str
    url: str
    html: str
    schema: dict[str, Any]
    expected: dict[str, Any]
    site_type: str = "unknown"
    geometry: dict[str, Rect] | None = None
    """Optional saved measurements, so reading-order behaviour is reproducible without
    launching a browser during scoring."""


def load_corpus(directory: Path) -> list[GoldCase]:
    """Read `gold.json` and the HTML snapshots it references."""
    manifest_path = directory / "gold.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"no gold.json in {directory}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases: list[GoldCase] = []

    for raw in manifest.get("cases", []):
        html_path = directory / raw["html"]
        if not html_path.exists():
            raise FileNotFoundError(f"case {raw['id']}: missing snapshot {html_path}")

        geometry = None
        if raw.get("geometry"):
            geometry = {
                path: Rect(**box) for path, box in raw["geometry"].items()
            }

        cases.append(
            GoldCase(
                id=raw["id"],
                url=raw["url"],
                html=html_path.read_text(encoding="utf-8"),
                schema=raw["schema"],
                expected=raw["expected"],
                site_type=raw.get("site_type", "unknown"),
                geometry=geometry,
            )
        )
    return cases


def run_case(case: GoldCase) -> PageScore:
    """Extract one case and score it. Failures become scores, not exceptions.

    A crashing page must be visible in the report as a zero rather than aborting the run --
    otherwise a regression that breaks one page hides the results for all the others.
    """
    try:
        document = build_document(case.html, case.url, geometry=case.geometry)
        facts = extract_facts(document.structured_data, case.schema, case.url)
        actual = {path: fact.value for path, fact in merge_facts(facts).items()}
        return score_page(case.id, case.url, case.expected, actual)
    except Exception as exc:
        return score_page(
            case.id, case.url, case.expected, {}, error=f"{type(exc).__name__}: {exc}"
        )


def run_corpus(cases: Iterable[GoldCase]) -> RunScore:
    return score_run([run_case(case) for case in cases])


def format_report(score: RunScore, *, verbose: bool = False) -> str:
    """Render a run as a readable report.

    Missing and wrong values are separated throughout: a miss means the extractor never
    found the field, a wrong value means it found something and got it incorrect. They have
    different fixes and conflating them hides which one is happening.
    """
    lines: list[str] = []
    lines.append("=" * 68)
    lines.append("EXTRACTION BENCHMARK")
    lines.append("=" * 68)
    lines.append("")
    lines.append(f"  Page-level success   {score.page_level_success:>7.1%}   <- headline metric")
    lines.append(f"  Field accuracy       {score.field_accuracy:>7.1%}")
    lines.append(f"  Fields missing       {score.miss_rate:>7.1%}")
    lines.append(f"  Fields wrong         {score.wrong_rate:>7.1%}")
    lines.append(f"  Pages                {score.page_count:>7}")
    if score.error_count:
        lines.append(f"  Errored pages        {score.error_count:>7}")
    lines.append("")

    perfect = [p for p in score.pages if p.perfect]
    imperfect = [p for p in score.pages if not p.perfect]

    lines.append(f"PAGES  ({len(perfect)} perfect / {len(imperfect)} imperfect)")
    lines.append("-" * 68)
    for page in score.pages:
        mark = "PASS" if page.perfect else "FAIL"
        detail = f"{page.correct_count}/{page.expected_count}"
        note = f"  ERROR {page.error}" if page.error else ""
        lines.append(f"  [{mark}] {page.page_id:<28} {detail:>7}{note}")

    if imperfect or verbose:
        lines.append("")
        lines.append("FIELD DETAIL")
        lines.append("-" * 68)
        for page in score.pages:
            if page.perfect and not verbose:
                continue
            lines.append(f"  {page.page_id}")
            for outcome in page.outcomes:
                if outcome.correct and not verbose:
                    continue
                status = "ok " if outcome.correct else ("MISS" if not outcome.present else "WRONG")
                lines.append(
                    f"    {status:<6} {outcome.path:<26} "
                    f"expected={outcome.expected!r} actual={outcome.actual!r}"
                )
            if page.extra_paths:
                lines.append(f"    extra: {', '.join(page.extra_paths[:8])}")

    if score.per_field:
        lines.append("")
        lines.append("PER-FIELD ACCURACY")
        lines.append("-" * 68)
        for path, (correct, total) in score.per_field.items():
            ratio = correct / total if total else 0.0
            bar = "#" * int(ratio * 20)
            lines.append(f"  {path:<30} {correct:>3}/{total:<3} {ratio:>6.1%} {bar}")

    lines.append("")
    lines.append(score.summary())
    return "\n".join(lines)
