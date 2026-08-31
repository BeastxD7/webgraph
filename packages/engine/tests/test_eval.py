"""Metrics and harness tests.

Scoring code that is subtly wrong is worse than none, because it makes a regression look
like an improvement. These pin the definitions: page-level success is all-or-nothing, a
miss is distinct from a wrong value, and comparison is normalised without being lenient.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from webgraph.eval.harness import format_report, load_corpus, run_case, run_corpus
from webgraph.eval.metrics import score_page, score_run, values_match


class TestValuesMatch:
    @pytest.mark.parametrize(
        ("expected", "actual"),
        [
            ("Widget", "Widget"),
            ("Widget", "widget"),
            ("  spaced  out ", "spaced out"),
            (49, 49.0),
            (49.0, 49),
            (True, True),
            (None, None),
        ],
    )
    def test_matches(self, expected: Any, actual: Any) -> None:
        assert values_match(expected, actual)

    @pytest.mark.parametrize(
        ("expected", "actual"),
        [
            (49, 59),
            ("Widget", "Gadget"),
            (None, 0),
            (0, None),
            (None, ""),
            (True, 1),
            (1, True),
            (False, 0),
        ],
    )
    def test_does_not_match(self, expected: Any, actual: Any) -> None:
        """`None` never equals `0`, and a boolean never equals a number."""
        assert not values_match(expected, actual)


class TestPageScore:
    def test_perfect_page(self) -> None:
        score = score_page("p", "u", {"a": 1, "b": "x"}, {"a": 1, "b": "x"})
        assert score.perfect
        assert score.correct_count == 2
        assert score.missing_count == 0
        assert score.wrong_count == 0

    def test_one_wrong_field_fails_the_page(self) -> None:
        """Page-level success is all-or-nothing -- that is the point of the metric."""
        score = score_page("p", "u", {"a": 1, "b": "x"}, {"a": 1, "b": "WRONG"})
        assert not score.perfect
        assert score.correct_count == 1

    def test_miss_and_wrong_are_distinguished(self) -> None:
        score = score_page("p", "u", {"a": 1, "b": 2}, {"a": 99})
        assert score.wrong_count == 1
        assert score.missing_count == 1

    def test_extra_paths_reported_not_penalised(self) -> None:
        score = score_page("p", "u", {"a": 1}, {"a": 1, "unexpected": 2})
        assert score.perfect
        assert score.extra_paths == ("unexpected",)

    def test_errored_page_is_never_perfect(self) -> None:
        score = score_page("p", "u", {"a": 1}, {}, error="boom")
        assert not score.perfect
        assert score.error == "boom"

    def test_empty_expectation_is_not_perfect(self) -> None:
        """A case with no labels must not inflate the score."""
        assert not score_page("p", "u", {}, {}).perfect


class TestRunScore:
    def test_page_level_versus_field_accuracy(self) -> None:
        """Field accuracy overstates page-level success -- the effect the metric exists for."""
        run = score_run([
            score_page("a", "u", {"x": 1, "y": 2, "z": 3}, {"x": 1, "y": 2, "z": 3}),
            score_page("b", "u", {"x": 1, "y": 2, "z": 3}, {"x": 1, "y": 2, "z": 99}),
        ])
        assert run.page_level_success == 0.5
        assert run.field_accuracy == pytest.approx(5 / 6)
        assert run.field_accuracy > run.page_level_success

    def test_per_field_breakdown(self) -> None:
        run = score_run([
            score_page("a", "u", {"x": 1}, {"x": 1}),
            score_page("b", "u", {"x": 1}, {"x": 2}),
        ])
        assert run.per_field["x"] == (1, 2)

    def test_empty_run(self) -> None:
        run = score_run([])
        assert run.page_level_success == 0.0
        assert run.field_accuracy == 0.0

    def test_summary_is_renderable(self) -> None:
        run = score_run([score_page("a", "u", {"x": 1}, {"x": 1})])
        assert "page_level_success" in run.summary()


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "p.html").write_text(
        '<html><head><script type="application/ld+json">'
        '{"@type":"Product","name":"Widget","offers":{"price":"49"}}'
        "</script></head><body><p>Widget</p></body></html>",
        encoding="utf-8",
    )
    (tmp_path / "gold.json").write_text(
        json.dumps({
            "cases": [{
                "id": "c1",
                "url": "https://example.com/w",
                "html": "pages/p.html",
                "site_type": "ecommerce",
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "offers": {
                            "type": "object",
                            "properties": {"price": {"type": "number"}},
                        },
                    },
                },
                "expected": {"name": "Widget", "offers.price": 49.0},
            }]
        }),
        encoding="utf-8",
    )
    return tmp_path


class TestHarness:
    def test_loads_and_scores_a_corpus(self, corpus: Path) -> None:
        cases = load_corpus(corpus)
        assert len(cases) == 1
        run = run_corpus(cases)
        assert run.page_level_success == 1.0

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match=r"gold\.json"):
            load_corpus(tmp_path)

    def test_missing_snapshot_raises(self, corpus: Path) -> None:
        (corpus / "pages" / "p.html").unlink()
        with pytest.raises(FileNotFoundError, match="snapshot"):
            load_corpus(corpus)

    def test_broken_case_scores_zero_rather_than_aborting(self, corpus: Path) -> None:
        """One crashing page must not hide the results for every other page."""
        case = load_corpus(corpus)[0]
        broken = type(case)(
            id=case.id, url=case.url, html="", schema=case.schema, expected=case.expected
        )
        score = run_case(broken)
        assert score.error is not None
        assert not score.perfect

    def test_report_renders(self, corpus: Path) -> None:
        report = format_report(run_corpus(load_corpus(corpus)))
        assert "Page-level success" in report
        assert "PER-FIELD ACCURACY" in report


class TestShippedCorpus:
    """The repository's own benchmark must stay loadable and honest."""

    CORPUS = Path(__file__).resolve().parents[3] / "benchmark" / "corpus-v0"

    @pytest.mark.skipif(not CORPUS.exists(), reason="benchmark corpus not present")
    def test_corpus_runs(self) -> None:
        run = run_corpus(load_corpus(self.CORPUS))
        assert run.page_count == 6
        assert run.error_count == 0

    @pytest.mark.skipif(not CORPUS.exists(), reason="benchmark corpus not present")
    def test_engine_never_emits_a_wrong_value(self) -> None:
        """The core safety property: decline rather than guess.

        Every failure on this corpus must be a *miss*. A wrong value would mean the
        structured-data path invented something, which is the one thing it must never do.
        """
        run = run_corpus(load_corpus(self.CORPUS))
        assert run.wrong_rate == 0.0
