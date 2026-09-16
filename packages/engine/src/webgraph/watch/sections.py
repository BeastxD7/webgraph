"""Cut a page's content Markdown into heading-scoped sections.

The graph builder cuts sections from a document's blocks (`graph.build.sections_from_document`);
a watch works from the `page` event a crawl streams, which carries the page as Markdown --
the whole page and, when chrome was removed, the content alone. The content Markdown is
what a watch compares, so sections are cut from it here, by the same rule: a heading owns
everything after it until the next heading of equal or higher level, and text before the
first heading is a level-0 section.

The result is the graph's own `Section` type, so `graph.diff.diff_sections` matches them
across runs unchanged -- by heading first, by position second.
"""

from __future__ import annotations

import re
from typing import Any, Final

from webgraph.graph.model import Section, section_id

__all__ = ["sections_from_markdown", "sections_from_records"]

_HEADING: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_FENCE: Final[re.Pattern[str]] = re.compile(r"^(?:```|~~~)")
_PERMALINK: Final[re.Pattern[str]] = re.compile(r"[\s]*[¶#§]+[\s]*$")


def sections_from_markdown(markdown: str, *, page_key: str = "") -> list[Section]:
    """Heading-scoped sections of a Markdown document, in order. Never empty for non-empty
    text: a page with no headings is one level-0 section."""
    sections: list[Section] = []
    heading = ""
    level = 0
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(buffer).strip()
        buffer.clear()
        if not body and not heading:
            return
        sections.append(
            Section(
                id=section_id(page_key, len(sections)),
                page_key=page_key,
                order=len(sections),
                heading=heading,
                level=level,
                text=body,
            )
        )

    for line in markdown.splitlines():
        if _FENCE.match(line.strip()):
            in_fence = not in_fence
            buffer.append(line)
            continue
        match = None if in_fence else _HEADING.match(line)
        if match is None:
            buffer.append(line)
            continue
        flush()
        level = len(match.group(1))
        heading = _PERMALINK.sub("", match.group(2).strip()).strip()
    flush()
    return sections


def sections_from_records(
    records: list[dict[str, Any]] | tuple[dict[str, Any], ...], *, page_key: str = ""
) -> list[Section]:
    """Sections as stored (`{"heading", "level", "text"}`) back into `Section`s."""
    return [
        Section(
            id=section_id(page_key, index),
            page_key=page_key,
            order=index,
            heading=str(record.get("heading") or ""),
            level=int(record.get("level") or 0),
            text=str(record.get("text") or ""),
        )
        for index, record in enumerate(records)
    ]
