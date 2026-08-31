"""Turn extracted documents into a site graph, incrementally.

Incrementally matters. A crawl streams pages for minutes; waiting until it finishes to build
anything means the graph is useless during the only period when someone is watching. The
builder therefore accepts one page at a time and keeps the graph queryable throughout, which
also means a stopped crawl still leaves a usable graph behind.

Link targets are recorded whether or not the target has been crawled yet. An edge to a page
that arrives ten minutes later is still an edge, and dropping it would make the graph depend
on crawl order.
"""

from __future__ import annotations

import re
from typing import Any, Final
from urllib.parse import urljoin

from webgraph.crawl.frontier import canonical_key, normalize_url, same_site
from webgraph.graph.model import Entity, PageNode, Section, SiteGraph, section_id
from webgraph.types import BlockKind, Document

__all__ = ["GraphBuilder", "sections_from_document"]

MAX_SECTION_CHARS: Final[int] = 6_000
"""A section longer than this is split.

Some pages have one heading and twenty thousand characters under it. Left whole, such a
section either swallows a context budget or is dropped entirely -- both of which lose the
paragraph that mattered. Splitting on paragraph boundaries keeps the pieces readable and
keeps their order.
"""

_MARKDOWN_LINK: Final[re.Pattern[str]] = re.compile(r"\]\(([^)\s]+)")
"""Link targets inside a section's rich Markdown."""

MIN_SECTION_CHARS: Final[int] = 40
"""Below this a section is a stray label, not content."""


def sections_from_document(document: Document, *, page_key: str = "") -> list[Section]:
    """Cut a document into heading-scoped sections, in reading order.

    A heading owns everything after it until the next heading of equal or higher level. That
    is the author's own idea of where a topic begins and ends, and it beats a fixed-size
    chunker for exactly the reason the author wrote the heading in the first place.

    This depends on reading order having been recovered first. On a multi-column layout,
    source order does not say which paragraphs sit under which heading, and sections built
    from it interleave two topics without any sign that they have.
    """
    key = page_key or document.url
    sections: list[Section] = []
    heading = ""
    level = 0
    buffer: list[str] = []
    # Heading level -> id of the most recent section at that level, for parent links.
    open_at_level: dict[int, str] = {}

    def flush() -> None:
        nonlocal buffer
        body = "\n\n".join(part for part in buffer if part.strip()).strip()
        buffer = []
        if not body and not heading:
            return
        if len(body) + len(heading) < MIN_SECTION_CHARS:
            return

        for piece in _split_long(body):
            order = len(sections)
            parent = next(
                (open_at_level[lvl] for lvl in range(level - 1, 0, -1) if lvl in open_at_level),
                None,
            )
            new = Section(
                id=section_id(key, order),
                page_key=key,
                order=order,
                heading=heading,
                level=level,
                text=piece,
                parent_id=parent,
            )
            sections.append(new)
            if level:
                open_at_level[level] = new.id
                # A new heading closes every deeper one; `##` after `###` starts a sibling
                # branch, not a child of the section that just ended.
                for deeper in [lvl for lvl in open_at_level if lvl > level]:
                    del open_at_level[deeper]

    for block in document.blocks:
        if block.kind is BlockKind.HEADING:
            flush()
            heading = block.text.strip()
            level = block.level or 1
            continue
        rendered = block.rich_text or block.text
        if rendered.strip():
            buffer.append(rendered.strip())

    flush()
    return sections


def _split_long(body: str) -> list[str]:
    """Split an oversized section on paragraph boundaries, never mid-sentence."""
    if len(body) <= MAX_SECTION_CHARS:
        return [body] if body else []

    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in body.split("\n\n"):
        if size and size + len(paragraph) > MAX_SECTION_CHARS:
            pieces.append("\n\n".join(current))
            current, size = [], 0
        current.append(paragraph)
        size += len(paragraph) + 2
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _entity_name(data: dict[str, Any]) -> str:
    for field_name in ("name", "headline", "title", "legalName", "og:title"):
        value = data.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return ""


def _entity_key(entity_type: str, data: dict[str, Any]) -> str:
    """Identity for an entity across pages.

    `@id` when the site publishes one -- that is the site declaring identity itself, which
    beats any similarity heuristic. Otherwise type plus name, so the same Organization block
    repeated on 90 pages collapses to one entity that appeared 90 times.
    """
    declared = data.get("@id")
    if isinstance(declared, str) and declared.strip():
        return f"{entity_type}:{declared.strip()}"
    name = _entity_name(data)
    if name:
        return f"{entity_type}:{name.casefold()}"
    return f"{entity_type}:{hash(repr(sorted(data.items()))) & 0xFFFFFFFF:08x}"


class GraphBuilder:
    """Accumulates a `SiteGraph` one page at a time."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.graph = SiteGraph(root=root)

    def add(
        self,
        document: Document,
        *,
        depth: int = 0,
        title: str = "",
        anchored_links: list[tuple[str, str]] | None = None,
    ) -> list[Section]:
        """Add one extracted page. Returns the sections it produced."""
        key = _canonical(document.url)
        sections = sections_from_document(document, page_key=key)
        for section in sections:
            self.graph.add_section(section)

        self.graph.add_page(
            PageNode(
                key=key,
                url=document.url,
                title=title or _page_title(document),
                depth=depth,
                chars=len(document.text),
                section_ids=tuple(s.id for s in sections),
                content_hash=document.content_hash,
            )
        )

        for href, anchor in anchored_links or []:
            target = normalize_url(urljoin(document.url, href))
            if target is None or not same_site(target, self.root):
                continue
            # Canonical form on both sides: `/a` and `/a/` are one page, and an edge that
            # distinguishes them would fragment the neighbourhood of every URL.
            self.graph.add_link(key, _canonical(target), anchor)

        # Which section each link sat in. Sections carry rich Markdown, so the links are
        # already in the text as `[label](url)` -- no second parse of the HTML is needed,
        # and the association is exact rather than inferred from position.
        for section in sections:
            for href in _MARKDOWN_LINK.findall(section.text):
                target = normalize_url(urljoin(document.url, href))
                if target is None or not same_site(target, self.root):
                    continue
                self.graph.add_section_link(section.id, _canonical(target))

        self._add_entities(document, sections, page_key=key)
        return sections

    def _add_entities(
        self, document: Document, sections: list[Section], *, page_key: str
    ) -> None:
        """Attach entities the page published, and link them to the sections that name them.

        Mentions are matched on the entity's name appearing in the section text. That is a
        deliberately conservative rule: it produces no mention rather than a speculative one,
        which is the same trade the fact extractor makes.
        """
        for payload in document.structured_data:
            if not isinstance(payload.data, dict):
                continue
            entity_type = str(payload.data.get("@type") or payload.source.value)
            key = _entity_key(entity_type, payload.data)
            name = _entity_name(payload.data)
            self.graph.add_entity(
                Entity(
                    key=key,
                    type=entity_type,
                    name=name,
                    data=payload.data,
                    pages=(page_key,),
                )
            )
            if not name or len(name) < 3:
                continue
            needle = name.casefold()
            for section in sections:
                if needle in section.text.casefold() or needle in section.heading.casefold():
                    self.graph.add_mention(section.id, key)


def _canonical(url: str) -> str:
    """Canonical key, falling back to the URL itself if it cannot be normalised."""
    try:
        return canonical_key(url) or url
    except Exception:
        return url


def _page_title(document: Document) -> str:
    for block in document.blocks:
        if block.kind is BlockKind.HEADING and block.text.strip():
            return block.text.strip()[:200]
    return document.url
