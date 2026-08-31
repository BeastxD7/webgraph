"""Assemble a bounded context about a question from an unbounded crawl.

The problem
-----------
A 200-page crawl is several million characters. No context window holds it, and even where
one does, filling it is both slow and worse than filling it well. Something has to choose
what goes in.

Why lexical seeding rather than embeddings
------------------------------------------
BM25 needs no model, no API key, no index build and no GPU, and it is deterministic --
which means the retrieval half of this system can be benchmarked the same way the extraction
half is. It is also strong on exactly the queries websites get: proper nouns, product names,
error strings, prices. Embeddings help on paraphrase, and the seeding step is deliberately
isolated behind one function so that a vector seeder can be dropped in and *measured against*
this one rather than assumed to be better.

Why the graph is where the value is
-----------------------------------
Lexical or vector, a similarity search can only return text that resembles the question.
Websites routinely answer a question across two pages: the feature is described on one page
and its price on another, and the second page never repeats the feature's name. Nothing in
the query resembles the page holding the answer.

What does connect them is a link -- usually with anchor text written by a human that names
the relationship. Expansion walks those edges outward from the seeds, so a page nobody would
have retrieved is included because a page that *was* retrieved points at it.

The three tiers
---------------
When content is cut to fit a budget, the usual failure is that the reader cannot tell what
was cut. So the budget is spent in tiers:

1. **Full sections** for the best matches.
2. **Openings** -- heading plus the first few hundred characters -- for the next band.
3. **A map** -- title, URL and section headings -- for everything else that survived
   expansion.

The map costs very little and changes the failure mode completely: instead of silently
omitting the pricing page, the context says the pricing page exists and where it is, which
is exactly what an agent needs to decide to fetch it.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Final

from webgraph.graph.model import Section, SiteGraph

__all__ = [
    "Assembled",
    "Budget",
    "ContextAssembler",
    "ScoredSection",
    "tokenize",
]

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'_-]*")

CHARS_PER_TOKEN: Final[float] = 4.0
"""Rough conversion for budgeting. Deliberately approximate: the budget is a guard rail, and
tokenising precisely would tie the engine to one model's vocabulary."""

K1: Final[float] = 1.5
B: Final[float] = 0.75
DEDUP_PREFIX_CHARS: Final[int] = 300
"""Characters of a section's opening used to recognise a near-duplicate."""

HEADING_WEIGHT: Final[int] = 3
"""A heading term is worth three body terms. Headings are the author's own summary of the
section, and a query matching one is a much stronger signal than a passing mention."""


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(text)]


@dataclass(frozen=True, slots=True)
class Budget:
    """How much context to produce, and how to divide it."""

    max_chars: int = 400_000
    """Total assembled size. 400k characters is roughly 100k tokens."""

    full_share: float = 0.65
    """Share spent on complete sections."""

    opening_share: float = 0.20
    """Share spent on section openings."""

    neighbour_share: float = 0.35
    """Share of the content budget reserved for sections reached by expansion.

    Without a reservation, expansion is decorative. Seeds always score higher, so at any
    realistic budget they fill the context and every linked page is packed out -- measured
    at 25% multi-hop recall with no reservation. The reservation is what converts the graph
    from a ranking tweak into a retrieval mechanism. See the sweep in MEMORY.md for how this
    value was chosen.
    """

    per_page_sections: int = 3
    """Sections one page may contribute to the full tier.

    Without a cap, one long page takes every slot in its tier. A context assembled from a
    single page cannot answer a question that spans two, which is most of what a whole-site
    crawl is for.
    """

    opening_chars: int = 400
    map_entries: int = 400
    """Pages named in the map tier. The remaining share caps it in practice."""

    @property
    def max_tokens(self) -> int:
        return int(self.max_chars / CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class ScoredSection:
    section: Section
    score: float
    hops: int
    """0 for a lexical seed, 1 for a direct neighbour, and so on."""

    reason: str
    """Why this section is here, in words -- 'matched query', 'linked from … as "Pricing"'.

    Kept because retrieval decisions are the hardest part of the system to debug, and a
    ranked list with no explanation cannot be argued with.
    """


@dataclass
class Assembled:
    """The context, plus enough accounting to see what was chosen and why."""

    text: str
    sections_full: list[ScoredSection] = field(default_factory=list)
    sections_opening: list[ScoredSection] = field(default_factory=list)
    pages_mapped: list[str] = field(default_factory=list)
    seeds: list[ScoredSection] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)


class ContextAssembler:
    """Builds and holds the lexical index for one site graph.

    Constructed once per graph and reused across queries: the index is the expensive part
    and the query is not.
    """

    def __init__(self, graph: SiteGraph) -> None:
        self.graph = graph
        self._doc_tokens: dict[str, Counter[str]] = {}
        self._doc_len: dict[str, int] = {}
        self._df: Counter[str] = Counter()

        for section in graph.sections.values():
            terms = Counter(tokenize(section.text))
            for term in tokenize(section.heading):
                terms[term] += HEADING_WEIGHT
            self._doc_tokens[section.id] = terms
            self._doc_len[section.id] = sum(terms.values())
            for term in terms:
                self._df[term] += 1

        self._n = max(len(self._doc_tokens), 1)
        self._avg_len = (sum(self._doc_len.values()) / self._n) if self._doc_len else 1.0

    # -- seeding -------------------------------------------------------

    def score_sections(self, query: str, *, limit: int = 40) -> list[ScoredSection]:
        """Rank sections by BM25 against `query`."""
        terms = tokenize(query)
        if not terms:
            return []

        idf = {
            term: math.log(1 + (self._n - self._df[term] + 0.5) / (self._df[term] + 0.5))
            for term in set(terms)
            if self._df[term]
        }
        if not idf:
            return []

        scored: list[tuple[float, str]] = []
        for section_id_, counts in self._doc_tokens.items():
            length = self._doc_len[section_id_] or 1
            total = 0.0
            for term, weight in idf.items():
                freq = counts.get(term, 0)
                if not freq:
                    continue
                total += weight * (freq * (K1 + 1)) / (
                    freq + K1 * (1 - B + B * length / self._avg_len)
                )
            if total > 0:
                scored.append((total, section_id_))

        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [
            ScoredSection(
                section=self.graph.sections[section_id_],
                score=score,
                hops=0,
                reason="matched query",
            )
            for score, section_id_ in scored[:limit]
        ]

    # -- expansion -----------------------------------------------------

    def expand(
        self,
        seeds: list[ScoredSection],
        query: str,
        *,
        max_hops: int = 2,
        decay: float = 0.45,
        per_page: int = 4,
        accumulate: bool = True,
        normalize: bool = True,
    ) -> list[ScoredSection]:
        """Widen the seed set along real edges.

        `decay` is what stops a two-hop neighbourhood from swamping the seeds. It is set so
        that a one-hop section needs roughly twice a seed's lexical score to outrank it,
        which keeps expansion additive rather than displacing what actually matched.
        """
        query_terms = set(tokenize(query))

        # Evidence accumulates; it does not compete. An earlier version kept whichever of
        # the lexical and propagated scores was larger, which throws away the case the whole
        # design is for: a page that matches the question *weakly* and is *also* linked from
        # a page that matches it strongly. Neither signal alone lifts it into a tight budget;
        # together they should, and only a sum expresses that.
        total: dict[str, float] = {s.section.id: s.score for s in seeds}
        best: dict[str, ScoredSection] = {s.section.id: s for s in seeds}
        frontier = list(seeds)

        for hop in range(1, max_hops + 1):
            next_frontier: list[ScoredSection] = []
            for item in frontier:
                neighbours = self._neighbours(item, query_terms, per_page)
                # Mass conservation. A seed spreads a fixed amount of evidence across its
                # neighbours rather than handing each of them a full copy of its own score.
                #
                # Without this, summing rewards hubs: a page linked from everywhere collects
                # a small contribution from every seed and outranks the page that actually
                # answers the question. Measured on two sites, unnormalised summing cost
                # 10-17 points of recall on the realistic case even while it helped the
                # pathological one.
                mass = sum(w for _, _, w in neighbours) if normalize else 1.0
                divisor = mass if mass > 0 else 1.0
                for candidate, reason, weight in neighbours:
                    share = (weight / divisor) if normalize else weight
                    contribution = item.score * (decay**hop) * share
                    if contribution <= 0:
                        continue
                    previous = total.get(candidate.id, 0.0)
                    # `accumulate=False` is the ablation: keep the strongest single piece of
                    # evidence instead of summing. Retained because it is the obvious
                    # implementation and the measurement against it is the argument for this
                    # one.
                    total[candidate.id] = (
                        previous + contribution if accumulate else max(previous, contribution)
                    )
                    existing = best.get(candidate.id)
                    # The recorded reason is the strongest single piece of evidence, not the
                    # last one seen, so the explanation matches why the section ranks where
                    # it does.
                    if existing is None or contribution > getattr(existing, "_top", 0.0):
                        entry = ScoredSection(
                            section=candidate,
                            score=total[candidate.id],
                            hops=existing.hops if existing is not None else hop,
                            reason=existing.reason if existing is not None and existing.hops == 0 else reason,
                        )
                        best[candidate.id] = entry
                        if previous == 0.0:
                            next_frontier.append(entry)
            frontier = next_frontier
            if not frontier:
                break

        # Rewrite the scores once at the end: entries created early in the walk hold the
        # running total as it stood then, not the final one.
        for section_id_, score in total.items():
            entry = best[section_id_]
            best[section_id_] = ScoredSection(
                section=entry.section, score=score, hops=entry.hops, reason=entry.reason
            )

        return sorted(best.values(), key=lambda s: (-s.score, s.section.id))

    def _neighbours(
        self, item: ScoredSection, query_terms: set[str], per_page: int
    ) -> list[tuple[Section, str, float]]:
        """Neighbours of one section, each with a weight in [0, 1].

        The weight is what makes expansion a retrieval mechanism rather than a flood. An
        undifferentiated walk gives every one of a documentation page's fifty outbound links
        the same score, and the one that answers the question loses the tie-break to
        whichever URL sorts first.

        Three signals, none of which needs a model:

        - **Where the link sits.** A link inside the section that matched is the link a
          human reading that paragraph would have clicked. A link elsewhere on the page is a
          much weaker claim.
        - **How specific the link is.** A target linked from every page is navigation; one
          linked from two pages is a topic. Same insight as cross-page chrome detection,
          applied to edges.
        - **What the anchor says.** Anchor text overlapping the query is a human having
          labelled that edge with the words the question used.
        """
        graph = self.graph
        page_key = item.section.page_key
        out: list[tuple[Section, str, float]] = []

        # Structural: the sections around this one, and its parent. A section is frequently
        # unintelligible without the one that set it up.
        for sibling in graph.sections_of(page_key):
            if abs(sibling.order - item.section.order) == 1:
                out.append((sibling, "adjacent section on the same page", 0.8))
        if item.section.parent_id and item.section.parent_id in graph.sections:
            out.append((graph.sections[item.section.parent_id], "parent section", 0.9))

        in_section = graph.section_links.get(item.section.id, set())
        for target in graph.links_to.get(page_key, ()):
            link = graph.links.get((page_key, target))
            anchors = " ".join(link.anchors) if link else ""
            hit = query_terms & set(tokenize(anchors))

            specificity = graph.link_specificity(target)
            here = target in in_section
            weight = (1.0 if here else 0.35) * (0.25 + 0.75 * specificity)
            if hit:
                weight = min(1.0, weight + 0.4)

            if weight < 0.15:
                # Site navigation. Following it would pull the whole site in at one hop.
                continue

            if hit:
                label = f'link anchored on {", ".join(sorted(hit))}'
            elif here:
                label = f'linked from this section as "{anchors[:60]}"' if anchors else "linked from this section"
            else:
                label = f'linked from this page as "{anchors[:60]}"' if anchors else "linked from this page"

            for section in graph.sections_of(target)[:per_page]:
                out.append((section, label, weight))

        # Inbound links: the page that introduces this one usually explains what it is.
        # Weak on purpose -- being linked to says less than choosing to link.
        for source in list(graph.linked_from.get(page_key, ()))[:per_page]:
            for section in graph.sections_of(source)[:2]:
                out.append((section, "page that links here", 0.3))

        # Shared entities: two pages describing the same Product or Organization are about
        # the same thing even when they share no vocabulary.
        for entity_key in graph.mentions.get(item.section.id, ()):
            for other_id in list(graph.mentioned_in.get(entity_key, ()))[:per_page]:
                other = graph.sections.get(other_id)
                if other is not None and other.id != item.section.id:
                    entity = graph.entities.get(entity_key)
                    name = entity.name if entity and entity.name else entity_key
                    out.append((other, f"also describes {name}", 0.7))

        # URL hierarchy: a parent page states what a whole section of the site is for.
        parent = graph.parent_path(page_key)
        if parent:
            for section in graph.sections_of(parent)[:2]:
                out.append((section, "parent page in the URL hierarchy", 0.5))

        return out

    # -- packing -------------------------------------------------------

    def assemble(
        self,
        query: str,
        *,
        budget: Budget | None = None,
        seed_limit: int = 40,
        max_hops: int = 2,
        accumulate: bool = True,
        normalize: bool = True,
    ) -> Assembled:
        """Seed, expand, then spend the budget in tiers."""
        budget = budget or Budget()
        seeds = self.score_sections(query, limit=seed_limit)
        ranked = (
            self.expand(
                seeds, query, max_hops=max_hops, accumulate=accumulate, normalize=normalize
            )
            if seeds
            else []
        )

        full_cap = int(budget.max_chars * budget.full_share)
        used_opening_holder = [0]
        opening_cap = int(budget.max_chars * budget.opening_share)

        # Two purses, not one. Seeds outscore everything they reached, so a single greedy
        # pass spends the whole budget on them and the graph contributes nothing.
        neighbour_cap = int(full_cap * budget.neighbour_share)
        seed_cap = full_cap - neighbour_cap

        full: list[ScoredSection] = []
        opening: list[ScoredSection] = []
        used = {0: 0, 1: 0}  # 0 = seeds, 1 = reached by expansion
        caps = {0: seed_cap, 1: neighbour_cap}
        per_page: Counter[str] = Counter()
        leftover: list[ScoredSection] = []

        # Version archives, print views and pagination give a site several near-identical
        # copies of the same section. Unchecked they take three slots out of fourteen for
        # one piece of content -- observed on attrs.org, whose crawl reaches `/en/19.2.0/`
        # alongside `/en/stable/`. Identity is the normalised text, so a copy that differs
        # only in whitespace still counts as the same thing.
        seen_text: set[tuple[int, int]] = set()

        def duplicate(item: ScoredSection) -> bool:
            # An exact hash is not enough. Copies of a page under different version paths
            # differ in a version number, a date or a link target, so they hash apart while
            # being the same content to a reader. Fingerprinting the *opening* plus a coarse
            # length bucket catches them, and two genuinely different sections would have to
            # share three hundred identical characters and a similar length to collide.
            normalized = " ".join(item.section.text.split()).casefold()
            fingerprint = (hash(normalized[:DEDUP_PREFIX_CHARS]), len(normalized) // 200)
            if fingerprint in seen_text:
                return True
            seen_text.add(fingerprint)
            return False

        def cost_of(item: ScoredSection) -> int:
            # Measured, not estimated. Each section is rendered with a provenance header
            # naming its page, URL, reason and hop count, which runs well past any constant
            # and pushed the assembled context 7% past a limit the caller had set precisely
            # so that it would fit somewhere.
            return len(item.section.text) + len(self._header(item)) + 2

        # Pass one: each purse spends only its own reservation. Spilling here is what made
        # an earlier version's reservation inert -- seeds exhausted the shared budget before
        # a single neighbour was considered, and the sweep over `neighbour_share` came out
        # flat because the parameter had no effect at all.
        for item in sorted(ranked, key=lambda s: (-s.score, s.section.id)):
            if duplicate(item):
                continue
            purse = 0 if item.hops == 0 else 1
            # Diversity cap: without it one long page takes every slot in its tier, and a
            # context assembled from one page cannot answer a question that spans two.
            if per_page[item.section.page_key] >= budget.per_page_sections:
                leftover.append(item)
                continue
            cost = cost_of(item)
            if used[purse] + cost <= caps[purse]:
                used[purse] += cost
                per_page[item.section.page_key] += 1
                full.append(item)
            else:
                leftover.append(item)

        # Pass two: whatever neither tier wanted. An unspent reservation is worse than a
        # slightly lopsided context.
        remaining = full_cap - used[0] - used[1]
        for item in leftover:
            cost = cost_of(item)
            if cost <= remaining:
                remaining -= cost
                per_page[item.section.page_key] += 1
                full.append(item)
            elif used_opening_holder[0] + budget.opening_chars <= opening_cap:
                opening.append(item)
                used_opening_holder[0] += budget.opening_chars + len(self._header(item))

        full.sort(key=lambda s: (-s.score, s.section.id))

        covered = {s.section.page_key for s in full} | {s.section.page_key for s in opening}
        candidates = [key for key in self.graph.pages if key not in covered]

        # The map is the last claim on the budget, not an addition to it. Left uncapped it
        # took the assembled context 7% past a limit the caller set precisely so it would
        # fit somewhere.
        map_budget = max(0, budget.max_chars - used[0] - used[1] - used_opening_holder[0])
        mapped: list[str] = []
        map_used = 0
        for key in candidates[: budget.map_entries]:
            line = self._map_line(key)
            if map_used + len(line) > map_budget:
                break
            map_used += len(line)
            mapped.append(key)

        text = self._render(query, full, opening, mapped, budget)

        # Final guard. The preamble and tier headings are not attributable to any one
        # section, so the per-item accounting can still land a little over. The map is the
        # cheapest thing in the context, so it is what gives way -- a caller who asked for
        # 18,000 characters must not be handed 18,500.
        while len(text) > budget.max_chars and mapped:
            mapped.pop()
            text = self._render(query, full, opening, mapped, budget)

        return Assembled(
            text=text,
            sections_full=full,
            sections_opening=opening,
            pages_mapped=mapped,
            seeds=seeds,
            stats={
                "chars": float(len(text)),
                "approx_tokens": len(text) / CHARS_PER_TOKEN,
                "sections_considered": float(len(ranked)),
                "sections_full": float(len(full)),
                "sections_opening": float(len(opening)),
                "pages_mapped": float(len(mapped)),
                "pages_in_graph": float(len(self.graph.pages)),
                "budget_used": len(text) / budget.max_chars if budget.max_chars else 0.0,
            },
        )

    def _render(
        self,
        query: str,
        full: list[ScoredSection],
        opening: list[ScoredSection],
        mapped: list[str],
        budget: Budget,
    ) -> str:
        parts: list[str] = [
            f"# Context assembled for: {query}",
            "",
            f"Site: {self.graph.root} — {len(self.graph.pages)} pages, "
            f"{len(self.graph.sections)} sections indexed.",
            "",
        ]

        if full:
            parts.append("## Relevant content\n")
            for item in full:
                parts.append(self._header(item))
                parts.append(item.section.text)
                parts.append("")

        if opening:
            parts.append("## Further content (openings only)\n")
            for item in opening:
                parts.append(self._header(item))
                body = item.section.text[: budget.opening_chars]
                suffix = "…" if len(item.section.text) > budget.opening_chars else ""
                parts.append(f"{body}{suffix}")
                parts.append("")

        if mapped:
            # The map is what stops a truncated context from lying by omission: whatever was
            # cut is still named, with its address, so it can be asked for.
            parts.append("## Other pages on this site (not included above)\n")
            for key in mapped:
                parts.append(self._map_line(key).rstrip("\n"))
            parts.append("")

        return "\n".join(parts)

    def _map_line(self, page_key: str) -> str:
        """One page in the map tier: what it is, where it is, what it covers."""
        page = self.graph.pages[page_key]
        headings = [s.heading for s in self.graph.sections_of(page_key)[:6] if s.heading]
        trail = f" — {'; '.join(headings)}" if headings else ""
        return f"- {page.title} <{page.url}>{trail}\n"

    def _header(self, item: ScoredSection) -> str:
        page = self.graph.pages.get(item.section.page_key)
        url = page.url if page else item.section.page_key
        title = page.title if page else item.section.page_key
        heading = item.section.heading or "(opening)"
        return (
            f"### {heading}\n"
            f"*{title} — <{url}> · {item.reason} · {item.hops} hop(s)*\n"
        )


def index_sections_by_page(sections: list[Section]) -> dict[str, list[Section]]:
    grouped: dict[str, list[Section]] = defaultdict(list)
    for section in sections:
        grouped[section.page_key].append(section)
    return grouped
