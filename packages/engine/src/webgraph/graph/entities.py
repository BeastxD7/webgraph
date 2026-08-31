"""Derive entities for sites that publish no structured data.

The problem
-----------
Entities came only from JSON-LD and microdata. Marketing sites publish those; documentation
sites do not. Measured across attrs, pytest, Flask, Jinja and Click: **zero entities, zero
mentions** on all five. The `MENTIONS` edge and the cross-site entity bridge were inert on
exactly the corpus where they would be most useful.

Two derivations, both observed rather than inferred
---------------------------------------------------
**1. A page's subject is what other pages call it.** The anchor texts pointing *at* a page
are the site's own names for it, written by its authors, agreed across many pages. Flask's
docs call one Jinja page "Jinja", "Jinja Template Documentation" and "templates"; the
consensus of those is a better name for the subject than anything a model would invent, and
it is free.

**2. A code symbol is defined where it appears as a heading.** `render_template`,
`BaseLoader`, `Environment` -- documentation names its symbols in headings and refers to
them in prose as inline code. A section that mentions `BaseLoader` is about the page that
defines it, whether or not it links there.

What this buys, measured
------------------------
Not what was expected. The derivation works -- 0 entities becomes 31 to 75 per site, 0
mentions becomes 115 to 473 -- but on documentation corpora **neither retrieval claim
survives measurement**:

- **Within a site, retrieval is unchanged.** Sweeping the mention edge's weight from 0.0 to
  0.7 moves mean gold-page recall across three sites by less than a point in either
  direction (42.6% -> 42.1% no-overlap, 74.9% -> 75.8% weak-overlap). A section that merely
  names the same subject is much weaker evidence than a link someone chose to write.
- **Across sites, it bridges nothing.** On Flask + Jinja + Click, shared entities: **zero**.
  Subject keys are page-scoped by design, and the symbols each site defines do not overlap.

So this is kept as a **descriptive** feature, not a retrieval one: the entity list is a
useful account of what a site is about, with the aliases its own authors use, and the
machinery is the foundation for sites that *do* publish structured data, where `@id` values
bridge exactly as intended (see `test_corpus.py`). The mention edge's default weight is set
where it was measured harmless.

What was deliberately not done: keying subjects by name so they would bridge. Half the names
derived are generic -- "Introduction", "Getting Started", "Environment" -- and name-keying
would declare every site's introduction to be the same subject. A bridge that wrong is worse
than no bridge.

Why it does not overreach
-------------------------
A mention is recorded only when the name appears verbatim, at a word boundary. There is no
similarity threshold and no stemming, because a wrong mention is an edge that pulls
irrelevant content into every context assembled near it -- expensive and invisible. Names
that are too short, too common across the site, or ordinary English are dropped before they
can produce one.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Final

from webgraph.graph.model import Entity, SiteGraph

__all__ = [
    "MAX_NAME_PAGE_SHARE",
    "MIN_NAME_CHARS",
    "derive_code_symbols",
    "derive_entities",
    "derive_page_subjects",
]

MIN_NAME_CHARS: Final[int] = 4
"""Below this a name cannot establish identity. "API", "CLI", "Env"."""

MAX_NAME_CHARS: Final[int] = 60
"""Above this the anchor text is a sentence, not a name."""

MAX_NAME_PAGE_SHARE: Final[float] = 0.6
"""A name appearing on more than this share of pages is not discriminating.

Every page of the Flask documentation says "Flask". Linking every section on the site to one
entity produces a hub that connects everything to everything, which is the same as
connecting nothing.
"""

MIN_CODE_USES: Final[int] = 2
"""Times a heading's text must also appear as inline code before the heading counts as a
definition. `Environment` is a class because the site writes it in backticks; `Installation`
is a section because it never does."""

MIN_ANCHOR_AGREEMENT: Final[int] = 2
"""Distinct source pages that must use an anchor before it counts as the site's name for a
target. One page's phrasing is a phrasing; two pages agreeing is a name."""

_INLINE_CODE: Final[re.Pattern[str]] = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]{2,60})`")
_SYMBOLIC: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*$")

_COMMON_ANCHORS: Final[frozenset[str]] = frozenset(
    {
        "here", "this", "link", "more", "read more", "learn more", "docs",
        "documentation", "home", "back", "next", "previous", "index", "source",
        "github", "edit", "click here", "see", "see also", "reference", "guide",
        "api", "overview", "changelog", "download", "contents", "top", "page",
    }
)
"""Anchor texts that name the act of linking rather than the thing linked to."""


def derive_page_subjects(graph: SiteGraph) -> int:
    """Give each page an entity named by what other pages call it.

    Returns the number of entities created.
    """
    inbound: dict[str, Counter[str]] = {}
    for link in graph.links.values():
        if link.target not in graph.pages:
            continue
        bucket = inbound.setdefault(link.target, Counter())
        # Fragment-free anchors only. A link to `/api/#jinja2.Undefined` names that section,
        # and once the fragment is stripped it lands on the same edge as a link to `/api/` --
        # which produced the subject "Environment, also called Undefined".
        for anchor in link.page_anchors:
            name = " ".join(anchor.split())
            if _usable_name(name):
                # Counted once per source page, so a footer link repeated across a template
                # does not look like agreement.
                bucket[name] += 1

    created = 0
    for page_key, names in inbound.items():
        best = [name for name, count in names.most_common(4) if count >= MIN_ANCHOR_AGREEMENT]
        if not best:
            continue
        page = graph.pages[page_key]
        entity = Entity(
            key=f"Subject:{page_key}",
            type="Subject",
            name=best[0],
            data={"aliases": best, "page": page.url, "title": page.title},
            pages=(page_key,),
        )
        graph.add_entity(entity)
        created += 1
        _link_mentions(graph, entity, best)
    return created


def derive_code_symbols(graph: SiteGraph) -> int:
    """Connect sections that name a symbol to the section that defines it.

    A symbol is defined where it appears as a heading; it is mentioned wherever it appears
    as inline code. That is documentation's own convention, not a heuristic about language.
    """
    # Every identifier the site ever writes as inline code. A heading is only treated as a
    # definition if the site *also* uses the name as code somewhere, which is what separates
    # `Environment` the class from `Installation` the section. Two independent pieces of
    # evidence, rather than a guess about capitalisation.
    as_code: Counter[str] = Counter()
    for section in graph.sections.values():
        for match in _INLINE_CODE.finditer(section.text):
            as_code[match.group(1)] += 1

    defined: dict[str, str] = {}
    for section in graph.sections.values():
        candidate = section.heading.strip().split("(")[0].strip()
        if candidate in defined:
            continue
        if _usable_symbol(candidate) or (
            _plausible_symbol(candidate) and as_code[candidate] >= MIN_CODE_USES
        ):
            defined[candidate] = section.id

    if not defined:
        return 0

    total_pages = max(len(graph.pages), 1)
    appearances: Counter[str] = Counter()
    per_section: dict[str, set[str]] = {}
    for section in graph.sections.values():
        found = {m.group(1) for m in _INLINE_CODE.finditer(section.text)} & defined.keys()
        if not found:
            continue
        per_section[section.id] = found
        for symbol in found:
            appearances[symbol] += 1

    created = 0
    for symbol, definition_id in defined.items():
        if appearances[symbol] == 0:
            continue
        if appearances[symbol] > total_pages * MAX_NAME_PAGE_SHARE * 4:
            continue
        section = graph.sections[definition_id]
        entity = Entity(
            key=f"Symbol:{symbol}",
            type="Symbol",
            name=symbol,
            data={"defined_in": section.page_key, "heading": section.heading},
            pages=(section.page_key,),
        )
        graph.add_entity(entity)
        graph.add_mention(definition_id, entity.key)
        created += 1

    for section_id, symbols in per_section.items():
        for symbol in symbols:
            key = f"Symbol:{symbol}"
            if key in graph.entities:
                graph.add_mention(section_id, key)
    return created


def derive_entities(graph: SiteGraph) -> dict[str, int]:
    """Run every derivation. Safe to call more than once; entities merge by key."""
    return {
        "subjects": derive_page_subjects(graph),
        "symbols": derive_code_symbols(graph),
    }


def _usable_name(name: str) -> bool:
    if not (MIN_NAME_CHARS <= len(name) <= MAX_NAME_CHARS):
        return False
    if name.casefold() in _COMMON_ANCHORS:
        return False
    # A name has to look like one: some letters, and not a bare number or path.
    return bool(re.search(r"[A-Za-z]{3}", name)) and not name.startswith(("http", "/"))


def _plausible_symbol(candidate: str) -> bool:
    """A single identifier-shaped word, with no claim yet that it is a symbol."""
    return (
        MIN_NAME_CHARS <= len(candidate) <= 40
        and bool(_SYMBOLIC.match(candidate))
        and " " not in candidate
    )


def _usable_symbol(candidate: str) -> bool:
    if not (MIN_NAME_CHARS <= len(candidate) <= MAX_NAME_CHARS):
        return False
    if not _SYMBOLIC.match(candidate):
        return False
    # An ordinary word in a heading is not a symbol. Requiring an underscore, a dot or
    # internal capitalisation keeps `render_template`, `jinja2.Environment` and `BaseLoader`
    # while dropping `Templates` and `Installation`.
    return "_" in candidate or "." in candidate or bool(re.search(r"[a-z][A-Z]", candidate))


def _link_mentions(graph: SiteGraph, entity: Entity, names: list[str]) -> None:
    """Record sections that name the entity, unless the name is everywhere.

    Case-insensitive whole-word matching, no stemming. A wrong mention is an edge that drags
    irrelevant content into every context assembled near it, and it is invisible when it
    happens.
    """
    patterns = [
        re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])", re.IGNORECASE)
        for name in names
        if _usable_name(name)
    ]
    if not patterns:
        return

    matched: list[str] = []
    pages_hit: set[str] = set()
    for section in graph.sections.values():
        if section.page_key in entity.pages:
            continue
        haystack = f"{section.heading}\n{section.text}"
        if any(pattern.search(haystack) for pattern in patterns):
            matched.append(section.id)
            pages_hit.add(section.page_key)

    if len(pages_hit) > max(1, len(graph.pages)) * MAX_NAME_PAGE_SHARE:
        # The site's own name, or a word it uses constantly. An entity every section
        # mentions connects everything to everything, which connects nothing.
        return

    for section_id in matched:
        graph.add_mention(section_id, entity.key)
