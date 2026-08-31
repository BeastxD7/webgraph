"""Scoring for extraction runs.

The headline metric is **page-level success**: the fraction of pages where *every* expected
field was extracted correctly. Field-level F1 is reported too, but is deliberately not the
headline -- published results show it overstating usable quality by roughly 3x (a system at
94.78% field F1 delivered only 70.73% fully-correct pages). For an unattended pipeline, a
page with one wrong field is a wrong page.

Value comparison is normalised but never lenient about meaning: whitespace and case are
folded, numbers compare within a relative tolerance, but `None` never equals `0` and a
missing value never counts as a match.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "FieldOutcome",
    "PageScore",
    "RunScore",
    "score_page",
    "score_run",
    "values_match",
]

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
_NUMERIC_TOLERANCE: Final[float] = 1e-6


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return _WHITESPACE.sub(" ", value).strip().casefold()
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return float(value)
    return value


def values_match(expected: Any, actual: Any) -> bool:
    """Compare an expected value against an extracted one.

    Numeric comparison uses a relative tolerance so that `49` and `49.0` agree, while
    `49` and `59` do not. Booleans are compared before numbers so `True` never matches `1`.
    """
    if expected is None or actual is None:
        return expected is None and actual is None

    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual

    left, right = _normalize_scalar(expected), _normalize_scalar(actual)

    if isinstance(left, float) and isinstance(right, float):
        return math.isclose(left, right, rel_tol=_NUMERIC_TOLERANCE, abs_tol=_NUMERIC_TOLERANCE)

    return bool(left == right)


@dataclass(frozen=True, slots=True)
class FieldOutcome:
    """What happened to one expected field on one page."""

    path: str
    expected: Any
    actual: Any
    correct: bool
    present: bool
    """Whether anything at all was extracted for this path. Distinguishes a *miss*
    (nothing found) from a *wrong value*, which have different engineering fixes."""


@dataclass(frozen=True, slots=True)
class PageScore:
    page_id: str
    url: str
    outcomes: tuple[FieldOutcome, ...]
    extra_paths: tuple[str, ...] = ()
    """Paths extracted that the gold set does not mention. Not penalised -- a gold set is
    rarely exhaustive -- but reported, because a sudden rise signals hallucinated fields."""

    error: str | None = None

    @property
    def expected_count(self) -> int:
        return len(self.outcomes)

    @property
    def correct_count(self) -> int:
        return sum(1 for o in self.outcomes if o.correct)

    @property
    def missing_count(self) -> int:
        return sum(1 for o in self.outcomes if not o.present)

    @property
    def wrong_count(self) -> int:
        """Extracted, but with the wrong value. The dangerous failure mode."""
        return sum(1 for o in self.outcomes if o.present and not o.correct)

    @property
    def perfect(self) -> bool:
        """Every expected field correct. This is what page-level success counts."""
        return self.error is None and self.expected_count > 0 and self.correct_count == self.expected_count


@dataclass(frozen=True, slots=True)
class RunScore:
    pages: tuple[PageScore, ...]
    per_field: dict[str, tuple[int, int]] = field(default_factory=dict)
    """path -> (correct, expected), for finding which fields drag the score down."""

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def page_level_success(self) -> float:
        """THE headline metric: fraction of pages with every field correct."""
        if not self.pages:
            return 0.0
        return sum(1 for p in self.pages if p.perfect) / len(self.pages)

    @property
    def field_accuracy(self) -> float:
        """Fraction of expected fields extracted correctly. Reported, never the headline."""
        expected = sum(p.expected_count for p in self.pages)
        if not expected:
            return 0.0
        return sum(p.correct_count for p in self.pages) / expected

    @property
    def miss_rate(self) -> float:
        expected = sum(p.expected_count for p in self.pages)
        if not expected:
            return 0.0
        return sum(p.missing_count for p in self.pages) / expected

    @property
    def wrong_rate(self) -> float:
        expected = sum(p.expected_count for p in self.pages)
        if not expected:
            return 0.0
        return sum(p.wrong_count for p in self.pages) / expected

    @property
    def error_count(self) -> int:
        return sum(1 for p in self.pages if p.error)

    def summary(self) -> str:
        return (
            f"pages={self.page_count} "
            f"page_level_success={self.page_level_success:.1%} "
            f"field_accuracy={self.field_accuracy:.1%} "
            f"missing={self.miss_rate:.1%} wrong={self.wrong_rate:.1%} "
            f"errors={self.error_count}"
        )


def score_page(
    page_id: str,
    url: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    error: str | None = None,
) -> PageScore:
    """Compare one page's extraction against its gold labels."""
    outcomes = tuple(
        FieldOutcome(
            path=path,
            expected=want,
            actual=actual.get(path),
            correct=path in actual and values_match(want, actual[path]),
            present=path in actual,
        )
        for path, want in sorted(expected.items())
    )
    extra = tuple(sorted(set(actual) - set(expected)))
    return PageScore(page_id=page_id, url=url, outcomes=outcomes, extra_paths=extra, error=error)


def score_run(pages: list[PageScore]) -> RunScore:
    """Aggregate page scores, including a per-field breakdown."""
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for page in pages:
        for outcome in page.outcomes:
            totals[outcome.path][1] += 1
            if outcome.correct:
                totals[outcome.path][0] += 1

    return RunScore(
        pages=tuple(pages),
        per_field={path: (correct, total) for path, (correct, total) in sorted(totals.items())},
    )
