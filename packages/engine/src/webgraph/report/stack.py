"""How old the detected stack is, when its version says.

A version is only a number until it is placed in time: "WordPress 5.1.1" means little to a
site owner, "released February 2019" means something. The table below holds the release
dates that could be verified on 16 Sep 2026 -- WordPress 4.0-7.1 from the release table on
en.wikipedia.org/wiki/WordPress, cross-checked against wordpress.org/download/releases for
7.x; Drupal 7-9 from en.wikipedia.org/wiki/Drupal and 10.0.0 / 11.0.0 from their
drupal.org release pages; Joomla 3-6 from en.wikipedia.org/wiki/Joomla; Next.js 13-16 from
the GitHub Releases API (`published_at`). A version that is not in the table is reported
as a version and nothing more: no date is guessed.

Only the branch matters: 5.1.1 is dated by 5.1, because a point release is a security
patch of the branch and its own date says nothing about how old the software is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Final

__all__ = ["RELEASE_DATES", "StackEntry", "stack_entries"]

RELEASE_DATES: Final[dict[str, dict[str, date]]] = {
    "WordPress": {
        "4.0": date(2014, 9, 4), "4.1": date(2014, 12, 18), "4.2": date(2015, 4, 23),
        "4.3": date(2015, 8, 18), "4.4": date(2015, 12, 8), "4.5": date(2016, 4, 12),
        "4.6": date(2016, 8, 16), "4.7": date(2016, 12, 6), "4.8": date(2017, 6, 8),
        "4.9": date(2017, 11, 16), "5.0": date(2018, 12, 6), "5.1": date(2019, 2, 21),
        "5.2": date(2019, 5, 7), "5.3": date(2019, 11, 12), "5.4": date(2020, 3, 31),
        "5.5": date(2020, 8, 11), "5.6": date(2020, 12, 8), "5.7": date(2021, 3, 9),
        "5.8": date(2021, 7, 20), "5.9": date(2022, 1, 25), "6.0": date(2022, 5, 24),
        "6.1": date(2022, 11, 1), "6.2": date(2023, 3, 29), "6.3": date(2023, 8, 8),
        "6.4": date(2023, 11, 7), "6.5": date(2024, 4, 2), "6.6": date(2024, 7, 16),
        "6.7": date(2024, 11, 12), "6.8": date(2025, 4, 15), "6.9": date(2025, 12, 2),
        "7.0": date(2026, 5, 20), "7.1": date(2026, 8, 19),
    },
    "Drupal": {
        "7": date(2011, 1, 5), "8": date(2015, 11, 19), "9": date(2020, 6, 3),
        "10": date(2022, 12, 15), "11": date(2024, 8, 2),
    },
    "Joomla": {
        "3": date(2012, 9, 27), "4": date(2021, 8, 17), "5": date(2023, 10, 17),
        "6": date(2025, 10, 14),
    },
    "Next.js": {
        "13": date(2022, 10, 27), "14": date(2023, 10, 26), "15": date(2024, 10, 21),
        "16": date(2025, 10, 22),
    },
}
"""Release date of each branch, keyed by the branch a version is placed in: `major.minor`
for WordPress, `major` for the rest."""

_BRANCH_PARTS: Final[dict[str, int]] = {"WordPress": 2}


def _branch(name: str, version: str) -> str:
    parts = version.strip().split(".")
    keep = _BRANCH_PARTS.get(name, 1)
    return ".".join(parts[:keep])


@dataclass(frozen=True, slots=True)
class StackEntry:
    name: str
    category: str
    version: str | None
    released: date | None
    """When the version's branch was released, from `RELEASE_DATES`; None when the table
    does not have it or the version is unknown."""
    age_years: float | None
    """Years between the branch release and `today`, one decimal."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "version": self.version,
            "released": self.released.isoformat() if self.released else None,
            "age_years": self.age_years,
        }


def stack_entries(
    technologies: tuple[dict[str, Any], ...], *, today: date | None = None
) -> tuple[StackEntry, ...]:
    """The detected technologies, each dated where the table allows."""
    now = today or date.today()
    entries: list[StackEntry] = []
    for tech in technologies:
        name = str(tech.get("name") or "")
        version = tech.get("version")
        version = str(version) if version else None
        released = RELEASE_DATES.get(name, {}).get(_branch(name, version)) if version else None
        age = round((now - released).days / 365.25, 1) if released else None
        entries.append(
            StackEntry(
                name=name,
                category=str(tech.get("category") or ""),
                version=version,
                released=released,
                age_years=age,
            )
        )
    return tuple(entries)
