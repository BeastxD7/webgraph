"""Several sites, joined into one graph.

The question this answers: once you have crawled two websites, are they two graphs or one?

They are one, and the joins are already in the data:

1. **Links across sites.** Every crawl sees hrefs pointing off-site. Those are dropped for
   crawling -- correctly, since scope has to stop somewhere -- but kept on the graph. Add the
   second site and an edge that pointed nowhere becomes an edge between two crawled pages,
   labelled with the anchor text a human wrote.

2. **Entities the sites agree on.** Two sites publishing `@id: https://acme.example/#org`,
   or two `Organization` blocks both named "Acme", are describing the same thing. Merging
   them lets a question seeded on one site reach a section on the other through a shared
   subject rather than through shared words.

Both joins are observed. Nothing here guesses that two things are the same because they
look similar; identity comes from a URL the sites both published, or from a typed name they
both used.

Cost of the merge
-----------------
`merged()` produces an ordinary `SiteGraph`, so every retrieval path works over a corpus
with no changes. The merge is a copy, which is the honest trade: a corpus of ten 2,000-page
sites is large, and anything bigger than a laptop belongs in the export path and a real
database rather than in one process's memory.

Deliberately *not* done
-----------------------
No fuzzy entity resolution. "Acme Inc." and "Acme Corporation" are left as two entities. A
similarity threshold that merges them will also merge things that are not the same, and a
wrongly merged entity silently fuses two subjects -- the same failure mode as a wrongly
removed block of chrome, and the same decision: fail open.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Final

from webgraph.crawl.frontier import canonical_key
from webgraph.fetch.static import FetchConfig, fetch_static
from webgraph.graph.model import Entity, SiteGraph


def _key(url: str) -> str:
    """Graph identity for a URL: host and path, no scheme. Matches `graph.build`."""
    try:
        key = canonical_key(url) or url
    except Exception:
        key = url
    return key.split("://", 1)[-1]

__all__ = ["Corpus", "CrossSiteEdge"]

MIN_ENTITY_NAME_CHARS: Final[int] = 4
"""Below this a name is too generic to establish identity across sites -- "API", "Docs"."""


@dataclass(frozen=True, slots=True)
class CrossSiteEdge:
    """One link that turned out to point at another crawled site."""

    source_page: str
    target_page: str
    source_site: str
    target_site: str
    anchors: tuple[str, ...] = ()


@dataclass
class Corpus:
    """A set of site graphs and the joins between them."""

    sites: dict[str, SiteGraph] = field(default_factory=dict)

    def add(self, graph: SiteGraph) -> None:
        self.sites[graph.root] = graph

    # -- joins ---------------------------------------------------------

    def cross_links(self) -> list[CrossSiteEdge]:
        """Off-site links whose target is a page some other site in the corpus crawled."""
        # Aliases as well as canonical keys: a site links to the address it knows, which is
        # often the one that redirects to the page rather than the page's final URL.
        owner: dict[str, str] = {}
        resolved: dict[str, str] = {}
        for root, graph in self.sites.items():
            for key in graph.pages:
                owner[key] = root
                resolved[key] = key
            for alias, key in graph.aliases.items():
                if key in graph.pages:
                    owner.setdefault(alias, root)
                    resolved.setdefault(alias, key)

        edges: list[CrossSiteEdge] = []
        for root, graph in self.sites.items():
            for page_key, targets in graph.external_links.items():
                for target_key, anchors in targets.items():
                    target_site = owner.get(target_key)
                    if target_site is None or target_site == root:
                        continue
                    edges.append(
                        CrossSiteEdge(
                            source_page=page_key,
                            target_page=resolved.get(target_key, target_key),
                            source_site=root,
                            target_site=target_site,
                            anchors=anchors,
                        )
                    )
        return edges

    def shared_entities(self) -> dict[str, list[str]]:
        """Entity key -> the roots of every site that describes it.

        Only entities named on more than one site are returned; a shared entity is only
        interesting as a bridge.
        """
        seen: dict[str, set[str]] = defaultdict(set)
        for root, graph in self.sites.items():
            for entity in graph.entities.values():
                if entity.name and len(entity.name) < MIN_ENTITY_NAME_CHARS:
                    continue
                seen[entity.key].add(root)
        return {key: sorted(roots) for key, roots in seen.items() if len(roots) > 1}

    # -- merge ---------------------------------------------------------

    def merged(self) -> SiteGraph:
        """One graph over every site, with the cross-site joins materialised.

        The result is an ordinary `SiteGraph`, so `ContextAssembler` and the exporters work
        over a corpus without knowing one exists.
        """
        combined = SiteGraph(root=" + ".join(sorted(self.sites)))

        for graph in self.sites.values():
            for page in graph.pages.values():
                combined.add_page(page)
            for section in graph.sections.values():
                combined.add_section(section)
            for link in graph.links.values():
                for anchor in link.anchors or ("",):
                    combined.add_link(link.source, link.target, anchor)
            for alias, key in graph.aliases.items():
                combined.add_alias(alias, key)
            for alias, key in graph.aliases.items():
                combined.add_alias(alias, key)
            for entity in graph.entities.values():
                # `add_entity` unions the page lists of entities that share a key, which is
                # the entity join: one subject, described by several sites.
                combined.add_entity(entity)
            for section_id, entity_keys in graph.mentions.items():
                for entity_key in entity_keys:
                    combined.add_mention(section_id, entity_key)
            for section_id, linked in graph.section_links.items():
                for target in linked:
                    combined.add_section_link(section_id, target)
            for page_key, external in graph.external_links.items():
                for url, anchors in external.items():
                    for anchor in anchors or ("",):
                        combined.add_external_link(page_key, url, anchor)

        # Cross-site links become ordinary link edges once both endpoints are present, so
        # expansion crosses site boundaries without any special case in the retriever.
        for edge in self.cross_links():
            for anchor in edge.anchors or ("",):
                combined.add_link(edge.source_page, edge.target_page, anchor)

        return combined

    def resolve_external(
        self,
        *,
        config: FetchConfig | None = None,
        max_lookups: int = 60,
        concurrency: int = 8,
    ) -> int:
        """Follow redirects on off-site links that point at a site in this corpus.

        Sites link to the address they publish, not the address a crawl ends up with. Flask
        links to `jinja.palletsprojects.com/templates`; the crawl filed that page under
        `/en/stable/templates` after a redirect it never had cause to request. The link is
        real, both endpoints are crawled, and the join fails on a version prefix.

        One request per unresolved target settles it. Bounded hard, because this is network
        I/O in what is otherwise a pure merge:

        - only targets whose **host already belongs to a site in the corpus** -- a link to
          github.com is not going to become an internal edge;
        - deduplicated, so a footer link repeated on 200 pages costs one request;
        - capped at `max_lookups`.

        Explicit rather than automatic: `merged()` stays pure, and a caller who does not want
        the engine touching the network simply does not call this.

        Returns the number of new aliases registered.
        """
        hosts = {root.split("://")[-1].split("/")[0] for root in self.sites}
        known: set[str] = set()
        for graph in self.sites.values():
            known |= set(graph.pages) | set(graph.aliases)

        candidates: list[str] = []
        for graph in self.sites.values():
            for targets in graph.external_links.values():
                for target in targets:
                    if target in known or target in candidates:
                        continue
                    if target.split("/")[0] in hosts:
                        candidates.append(target)
        candidates = candidates[:max_lookups]
        if not candidates:
            return 0

        def probe(target: str) -> tuple[str, str] | None:
            for scheme in ("https", "http"):
                try:
                    result = fetch_static(f"{scheme}://{target}", config=config)
                except Exception:
                    continue
                if result.ok and result.url:
                    return target, _key(result.url)
            return None

        registered = 0
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            for outcome in pool.map(probe, candidates):
                if outcome is None:
                    continue
                alias, final = outcome
                if alias == final:
                    continue
                for graph in self.sites.values():
                    if final in graph.pages:
                        graph.add_alias(alias, final)
                        registered += 1
                        break
        return registered

    def describe(self) -> dict[str, int]:
        merged = self.merged()
        return {
            "sites": len(self.sites),
            **merged.describe(),
            "cross_site_links": len(self.cross_links()),
            "shared_entities": len(self.shared_entities()),
        }

    def bridges(self) -> list[tuple[str, str, str]]:
        """Human-readable account of what actually joins the sites.

        Returned rather than logged because "these two sites are connected" is a claim, and
        a claim in this project comes with the evidence for it.
        """
        rows: list[tuple[str, str, str]] = []
        for edge in self.cross_links():
            label = edge.anchors[0] if edge.anchors else "(no anchor text)"
            rows.append((edge.source_site, edge.target_site, f'links as "{label}"'))
        for key, roots in self.shared_entities().items():
            name = key.split(":", 1)[-1]
            for other in roots[1:]:
                rows.append((roots[0], other, f"both describe {name[:60]}"))
        return rows


def entity_bridge(first: Entity, second: Entity) -> bool:
    """Whether two entities are the same subject.

    Identity, never similarity: a shared `@id` the sites both published, or the same type
    and the same name. Anything looser fuses two subjects on a threshold, which is silent
    and unrecoverable.
    """
    return first.key == second.key
