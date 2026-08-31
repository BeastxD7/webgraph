"""What changed on a site since it was last crawled.

Every piece needed for this already exists and was built for other reasons. Pages carry a
`content_hash` computed over their extracted text; graphs are stored between runs; sections
are heading-scoped, so a difference can be reported as "the Pricing section changed" rather
than as a character offset. Change detection is the three of them put together.

Why the hash is over extracted text, not the HTML
------------------------------------------------
A page's HTML changes constantly and means nothing: a build id, a cache-busting asset URL, a
CSRF token, a timestamp in a comment. Hashing the markup reports every page as changed on
every crawl, which is the same as reporting nothing.

The hash is over the text the engine extracted, in recovered reading order, so it changes
when what the page *says* changes. Combined with chrome removal, a sitewide footer edit does
not mark all 2,000 pages as changed either.

What a section-level diff needs that a page-level one does not
-------------------------------------------------------------
Knowing a page changed is nearly useless on a page of any size. Sections are matched across
crawls by heading first and position second, so the report can say which part moved, and the
text of a changed section can be shown side by side. Matching on heading rather than index is
what survives a section being inserted above the one you care about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from webgraph.graph.model import PageNode, Section, SiteGraph

__all__ = ["PageChange", "SectionChange", "SiteDiff", "diff_graphs"]

MAX_SECTION_DETAIL: Final[int] = 40
"""Sections reported per changed page. Beyond this the page was rewritten, not edited."""


@dataclass(frozen=True, slots=True)
class SectionChange:
    kind: str
    """`added`, `removed` or `edited`."""

    heading: str
    before: str = ""
    after: str = ""

    @property
    def delta_chars(self) -> int:
        return len(self.after) - len(self.before)


@dataclass(frozen=True, slots=True)
class PageChange:
    url: str
    title: str
    sections: tuple[SectionChange, ...] = ()

    @property
    def delta_chars(self) -> int:
        return sum(change.delta_chars for change in self.sections)


@dataclass
class SiteDiff:
    """Pages and sections that differ between two crawls of the same site."""

    added: list[PageNode] = field(default_factory=list)
    removed: list[PageNode] = field(default_factory=list)
    changed: list[PageChange] = field(default_factory=list)
    unchanged: int = 0

    @property
    def any_change(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def summary(self) -> str:
        if not self.any_change:
            return f"No change. {self.unchanged} pages identical."
        parts = []
        if self.added:
            parts.append(f"{len(self.added)} new")
        if self.removed:
            parts.append(f"{len(self.removed)} gone")
        if self.changed:
            parts.append(f"{len(self.changed)} changed")
        return f"{', '.join(parts)}; {self.unchanged} unchanged."


def diff_graphs(before: SiteGraph, after: SiteGraph) -> SiteDiff:
    """Compare two crawls of one site.

    Pages are matched on canonical key, so a URL that gained a trailing slash or moved
    between http and https is the same page rather than one removal and one addition.
    """
    result = SiteDiff()

    for key, page in after.pages.items():
        previous = before.pages.get(key)
        if previous is None:
            result.added.append(page)
            continue
        if previous.content_hash and previous.content_hash == page.content_hash:
            result.unchanged += 1
            continue
        changes = _diff_sections(before.sections_of(key), after.sections_of(key))
        if changes:
            result.changed.append(
                PageChange(url=page.url, title=page.title, sections=tuple(changes))
            )
        else:
            # Hashes differ but no section does: whitespace, or a block below the section
            # threshold. Not worth reporting as a change.
            result.unchanged += 1

    for key, page in before.pages.items():
        if key not in after.pages:
            result.removed.append(page)

    result.changed.sort(key=lambda change: -abs(change.delta_chars))
    return result


def _diff_sections(
    before: list[Section], after: list[Section]
) -> list[SectionChange]:
    """Match sections across crawls by heading, falling back to position.

    Heading first, because matching on index reports every section below an inserted one as
    changed -- which is how a one-paragraph addition turns into "the whole page changed".
    """
    changes: list[SectionChange] = []

    before_by_heading: dict[str, list[Section]] = {}
    for section in before:
        before_by_heading.setdefault(_key(section), []).append(section)

    matched: set[int] = set()
    for index, section in enumerate(after):
        candidates = before_by_heading.get(_key(section))
        if candidates:
            previous = candidates.pop(0)
        elif index < len(before) and not _key(section) and not _key(before[index]):
            # Unheaded sections have no name to match on, so position is all there is.
            previous = before[index]
        else:
            changes.append(
                SectionChange(kind="added", heading=section.heading, after=section.text)
            )
            continue

        matched.add(id(previous))
        if _normalise(previous.text) != _normalise(section.text):
            changes.append(
                SectionChange(
                    kind="edited",
                    heading=section.heading,
                    before=previous.text,
                    after=section.text,
                )
            )

    for section in before:
        if id(section) in matched:
            continue
        if any(_key(section) == _key(other) for other in after):
            continue
        changes.append(
            SectionChange(kind="removed", heading=section.heading, before=section.text)
        )

    return changes[:MAX_SECTION_DETAIL]


def _key(section: Section) -> str:
    return " ".join(section.heading.split()).casefold()


def _normalise(text: str) -> str:
    return " ".join(text.split())
