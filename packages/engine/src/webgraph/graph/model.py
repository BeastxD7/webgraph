"""The site graph: what a crawl knows about how a website hangs together.

Why this exists, and why it is cheap
------------------------------------
The published approaches to graph-structured retrieval -- GraphRAG, LightRAG and their
descendants -- spend a language model to *infer* a graph from flat text: entities are
guessed, relations are guessed, and the bill scales with the corpus.

A crawled website does not need that, because **a website already is a graph** and the crawl
already holds the edges:

| edge | where it comes from | what an inferred graph would have paid for it |
|---|---|---|
| page links to page | `<a href>` | an LLM pass over both pages |
| the link *means* this | the anchor text — written by a human | an LLM-written relation label |
| section belongs to page | heading structure in reading order | a chunker's guess |
| section is under section | heading levels | a chunker's guess |
| page describes entity | JSON-LD / microdata, already typed and often `@id`-keyed | entity extraction |
| page is a child of page | the URL path | nothing; usually lost |

Every edge here is therefore **observed, not inferred** — deterministic, reproducible, free,
and carrying provenance. That is the same commitment the extraction engine makes, extended
one layer up.

What the graph is for
---------------------
A 200-page crawl is several million tokens: more than fits in any context window, and far
more than should be spent on one question. The graph exists so that a bounded context can be
assembled that is *about* the question — seeded lexically, then widened along real edges to
the pages a human would have clicked through to. See `graph/retrieve.py`.

Representation
--------------
Plain dataclasses and adjacency dictionaries, deliberately. The graph is built once per
crawl, queried in-process, and is small enough to hold in memory for any site a laptop can
crawl: a 2,000-page site produces roughly 20,000 sections. A database is an export target
(`graph/export.py`), not a dependency, so the engine never requires one to be installed and
the schema is not hostage to one vendor's Cypher dialect.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "Entity",
    "EntityMention",
    "Link",
    "PageNode",
    "Section",
    "SiteGraph",
    "section_id",
]

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'_-]*")


def section_id(page_key: str, order: int) -> str:
    """Stable identifier for a section, so exports and reruns agree."""
    return f"{page_key}#s{order}"


@dataclass(frozen=True, slots=True)
class Section:
    """A heading-scoped run of content: the unit retrieval actually works on.

    Pages are the wrong granularity in both directions. A 20,000-character page swamps a
    context budget for one relevant paragraph, and a fixed-size chunk cuts across the
    argument. A heading owns the text beneath it until the next heading of equal or higher
    level, which is the author's own idea of where a topic starts and stops.

    This is only available because reading order was recovered first: on a multi-column page
    the DOM order of headings and paragraphs does not say which text sits under which
    heading, and sections built from it are silently wrong.
    """

    id: str
    page_key: str
    """Canonical key of the owning page.

    Every join in the graph -- links, sections, mentions -- keys on the canonical form, so
    that `/a` and `/a/` are one node. The URL a reader should click lives on `PageNode.url`.
    """

    order: int
    """Position within the page, in reading order."""

    heading: str
    level: int
    """Heading depth, 1-6. Level 0 marks content before the first heading."""

    text: str
    parent_id: str | None = None

    @property
    def chars(self) -> int:
        return len(self.text)

    def tokens(self) -> list[str]:
        """Lower-cased word tokens of the heading and body, for lexical scoring."""
        return [m.group(0).lower() for m in _WORD.finditer(f"{self.heading} {self.text}")]


@dataclass(frozen=True, slots=True)
class PageNode:
    key: str
    """Canonical key: the identity every edge joins on."""

    url: str
    """The URL the site actually served, for display and for linking out to."""

    title: str
    depth: int
    """Crawl depth: hops from the root."""

    chars: int
    section_ids: tuple[str, ...] = ()
    content_hash: str = ""


@dataclass(frozen=True, slots=True)
class Link:
    """A hyperlink, kept with its anchor text.

    The anchor is the valuable half. It is a human-written description of the target, which
    is exactly the relation label an inferred graph pays a model to invent -- and it is
    better, because the site's own author chose it.
    """

    source: str
    target: str
    anchors: tuple[str, ...] = ()
    count: int = 1


@dataclass(frozen=True, slots=True)
class Entity:
    """Something the site published machine-readable data about.

    Identity is the payload's content, so the same `Organization` block on 90 pages is one
    entity that appeared on 90 pages. That collapse is only possible at site level, and it
    is the difference between "90 organisations" and "one organisation, described 90 times".
    """

    key: str
    type: str
    name: str
    data: dict[str, Any] = field(default_factory=dict)
    pages: tuple[str, ...] = ()

    @property
    def page_count(self) -> int:
        return len(self.pages)


@dataclass(frozen=True, slots=True)
class EntityMention:
    section_id: str
    entity_key: str
    count: int = 1


MAX_ANCHORS: Final[int] = 6
"""Anchor texts kept per link. Beyond a handful they repeat, and the list is only ever read
as a description of the target."""


@dataclass
class SiteGraph:
    """Nodes and edges for one crawled site.

    Adjacency is materialised in both directions on insert. Retrieval walks outward from a
    seed set and needs `links_to` and `linked_from` equally often, and rebuilding the reverse
    index per query on a 20,000-section graph is the difference between a query costing
    milliseconds and costing a second.
    """

    root: str = ""
    pages: dict[str, PageNode] = field(default_factory=dict)
    sections: dict[str, Section] = field(default_factory=dict)
    entities: dict[str, Entity] = field(default_factory=dict)

    links: dict[tuple[str, str], Link] = field(default_factory=dict)
    links_to: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    linked_from: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    mentions: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    """section id -> entity keys."""

    mentioned_in: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    """entity key -> section ids."""

    external_links: dict[str, dict[str, tuple[str, ...]]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    """page key -> {external URL: anchor texts}.

    Off-site links were previously discarded as out of scope, which they are *for crawling*.
    They are not out of scope for the graph: when a second site is added to the corpus, an
    edge that pointed nowhere becomes an edge between two crawled pages, and the two sites
    are joined by a link a human actually wrote. Keeping them costs a dictionary and is the
    difference between a corpus of separate graphs and a connected one.
    """

    aliases: dict[str, str] = field(default_factory=dict)
    """Other keys the same page answers to -> its canonical key.

    A site links to `jinja.palletsprojects.com/templates/`; the crawl followed a redirect and
    filed the page under `/en/stable/templates`. Without aliases the edge points at nothing,
    and two sites that reference each other constantly look unconnected. Populated from the
    URL that was requested and from the page's own `rel=canonical`.
    """

    section_links: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    """section id -> page keys linked *from inside that section*.

    Page-level link edges are too coarse to retrieve with. A documentation page links to
    fifty others; knowing that one of them answers the question is no help when all fifty
    arrive with the same score. A link inside the paragraph that matched the query is a
    different kind of evidence -- it is the link a human reading that paragraph would have
    clicked.
    """

    def add_page(self, page: PageNode) -> None:
        self.pages[page.key] = page

    def add_section(self, section: Section) -> None:
        self.sections[section.id] = section

    def add_link(self, source: str, target: str, anchor: str = "") -> None:
        """Record a hyperlink. Repeats accumulate a count and collect distinct anchors."""
        if source == target:
            return
        key = (source, target)
        existing = self.links.get(key)
        if existing is None:
            self.links[key] = Link(
                source=source,
                target=target,
                anchors=(anchor,) if anchor.strip() else (),
                count=1,
            )
        else:
            anchors = existing.anchors
            if anchor.strip() and anchor not in anchors and len(anchors) < MAX_ANCHORS:
                anchors = (*anchors, anchor)
            self.links[key] = Link(
                source=source, target=target, anchors=anchors, count=existing.count + 1
            )
        self.links_to[source].add(target)
        self.linked_from[target].add(source)

    def add_entity(self, entity: Entity) -> None:
        existing = self.entities.get(entity.key)
        if existing is None:
            self.entities[entity.key] = entity
            return
        merged_pages = tuple(dict.fromkeys((*existing.pages, *entity.pages)))
        self.entities[entity.key] = Entity(
            key=existing.key,
            type=existing.type,
            name=existing.name or entity.name,
            data=existing.data or entity.data,
            pages=merged_pages,
        )

    def add_alias(self, alias: str, page_key: str) -> None:
        if alias and alias != page_key:
            self.aliases.setdefault(alias, page_key)

    def resolve_key(self, key: str) -> str | None:
        """The crawled page a key refers to, following aliases. `None` if not crawled."""
        if key in self.pages:
            return key
        target = self.aliases.get(key)
        return target if target in self.pages else None

    def add_external_link(self, page_key: str, url: str, anchor: str = "") -> None:
        anchors = self.external_links[page_key].get(url, ())
        if anchor.strip() and anchor not in anchors and len(anchors) < MAX_ANCHORS:
            anchors = (*anchors, anchor)
        self.external_links[page_key][url] = anchors

    def add_section_link(self, section_id_: str, target_key: str) -> None:
        self.section_links[section_id_].add(target_key)

    def link_specificity(self, target_key: str) -> float:
        """How topical a link to `target_key` is, from how many pages point at it.

        A target linked from every page is navigation; a target linked from two pages is a
        topic. This is the boilerplate insight applied to edges rather than to text, and it
        is available for the same reason: the crawl saw the whole site.

        Returns roughly 1.0 for a page linked from one other, falling towards 0 as the
        in-degree approaches the size of the site.
        """
        total = len(self.pages) or 1
        in_degree = len(self.linked_from.get(target_key, ())) or 1
        if in_degree >= total:
            return 0.0
        import math

        return math.log(total / in_degree) / math.log(total + 1)

    def add_mention(self, section_id_: str, entity_key: str) -> None:
        self.mentions[section_id_].add(entity_key)
        self.mentioned_in[entity_key].add(section_id_)

    # -- derived views -------------------------------------------------

    def sections_of(self, page_key: str) -> list[Section]:
        page = self.pages.get(page_key)
        if page is None:
            return []
        return [self.sections[i] for i in page.section_ids if i in self.sections]

    def parent_path(self, page_key: str) -> str | None:
        """The nearest ancestor page by URL path, if the crawl reached it.

        `/docs/guides/deploy` is a child of `/docs/guides`. This is hierarchy the site
        publishes in its URLs and that a link graph alone does not capture -- plenty of deep
        pages are linked only from a sibling, never from their own parent.

        Keys carry no scheme, so the comparison is a plain host-and-path one. An earlier
        version partitioned a key that still had `https://` on the front, which made every
        candidate `https:/…` and meant this edge never once fired.
        """
        host, _, path = page_key.partition("/")
        segments = [part for part in path.split("/") if part]
        while segments:
            segments.pop()
            candidate = "/".join([host, *segments]) if segments else host
            if candidate in self.pages and candidate != page_key:
                return candidate
        return None

    def describe(self) -> dict[str, int]:
        return {
            "pages": len(self.pages),
            "sections": len(self.sections),
            "entities": len(self.entities),
            "links": len(self.links),
            "mentions": sum(len(v) for v in self.mentions.values()),
        }
