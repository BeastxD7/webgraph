"""Answer a question from the knowledge graph, streaming the path as it is walked.

Four steps, each yielded as an event so a viewer can light the graph up while it happens:

1. **`seeds`** -- no model call. BM25 over the entity index (`name`, `aliases`) and the fact
   index (`fact`, `predicate`), unioned with the entities mentioned in the top sections of
   the observed layer's own BM25 (`ContextAssembler.score_sections`). Proper nouns, prices
   and error strings are what websites get asked about, and lexical seeding is strong on
   exactly those -- and deterministic, so it can be benchmarked.
2. **`hop`** (twice at most) -- expansion over `relations`, mass-normalised per node as in
   `graph/retrieve.py:expand`: a seed spreads a fixed amount of evidence over its
   neighbours rather than copying its score to each, which is what stops a hub from
   collecting a little from every seed and outranking the answer. Generic entities (named
   on most pages) are never expanded through.
3. **`evidence`** -- the quotes: top evidence rows per selected relation, mentions and every
   typed attribute per selected entity, and the blocks of the seed sections. A share of the
   slots is reserved for rows reached by expansion rather than by the seed match, because
   without a reservation expansion is decorative (`Budget.neighbour_share`, measured).
4. **`answer`** -- one model call over numbered evidence. The model cites `[n]` after every
   factual sentence or says the site does not state it. Sentences are parsed; one without a
   valid citation is returned with `unsupported: true`, never silently kept.

Every citation resolves to `url#xpath` plus the verbatim quote, because every evidence row
in the store was verified against a block when it was written.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

from webgraph import config
from webgraph.graph.model import SiteGraph
from webgraph.graph.retrieve import ContextAssembler, tokenize
from webgraph.kg.model import Answer, Citation, Entity, Evidence, Hop, QueryPath, Relation, Sentence
from webgraph.kg.prompts import ANSWER_SYSTEM, answer_prompt
from webgraph.kg.providers import LLMError, Provider, Usage
from webgraph.kg.store import KGStore

__all__ = ["KGRetriever", "RetrievalConfig", "parse_answer"]

_CITE: Final[re.Pattern[str]] = re.compile(r"\[(\d+)\]")
_ABSTAIN: Final[re.Pattern[str]] = re.compile(r"not stated on (?:this|the) (?:site|page|website)", re.IGNORECASE)
_BOUNDARY: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])(?:\s*\[\d+\])*\s+(?=[A-Z0-9\"“(\[])")
_SECTION_QUOTE_CHARS: Final[int] = 320


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    max_hops: int = config.KG_MAX_HOPS
    decay: float = config.KG_HOP_DECAY
    max_entities: int = config.KG_MAX_ENTITIES
    max_relations: int = config.KG_MAX_RELATIONS
    max_evidence: int = config.KG_MAX_EVIDENCE
    graph_share: float = config.KG_GRAPH_EVIDENCE_SHARE
    seed_sections: int = 4


@dataclass(slots=True)
class _Candidate:
    evidence: Evidence
    heading: str
    entity_ids: tuple[str, ...]
    score: float
    source: str
    """`seed`, `graph` (reached by expansion) or `section` (observed-layer BM25)."""


class KGRetriever:
    def __init__(
        self,
        store: KGStore,
        provider: Provider | None,
        *,
        graph: SiteGraph | None = None,
        retrieval: RetrievalConfig | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.graph = graph
        self.config = retrieval or RetrievalConfig()
        self._assembler = ContextAssembler(graph) if graph is not None and graph.sections else None
        self._headings: dict[str, str] = (
            {sid: s.heading for sid, s in graph.sections.items()} if graph is not None else {}
        )

    # -- the walk -----------------------------------------------------------------------

    def retrieve(self, question: str, *, sink: list[_Candidate] | None = None) -> Iterator[dict[str, Any]]:
        """Seeds, hops and evidence -- no model call. `ask` adds the answer.

        `sink`, when given, receives the chosen candidates so `ask` can cite them without
        the event carrying a non-serialisable object.
        """
        cfg = self.config
        path = QueryPath()
        scores: dict[str, float] = defaultdict(float)
        reached_by_graph: set[str] = set()
        relation_scores: dict[str, float] = defaultdict(float)
        question_terms = set(tokenize(question))

        # 1. seeds
        for entity_id, score in self.store.search_entities(question, limit=cfg.max_entities // 2):
            scores[entity_id] += score
        fact_hits = self.store.search_facts(question, limit=cfg.max_relations // 2)
        fact_relations = self.store.relations([rid for rid, _ in fact_hits])
        for rid, score in fact_hits:
            relation = fact_relations.get(rid)
            if relation is None:
                continue
            relation_scores[rid] += score
            scores[relation.subject_id] += score * 0.5
            scores[relation.object_id] += score * 0.5
        seed_sections: list[tuple[str, float]] = []
        if self._assembler is not None:
            for item in self._assembler.score_sections(question, limit=cfg.seed_sections):
                seed_sections.append((item.section.id, item.score))
            for section_id, entity_ids in self.store.entities_in_sections([sid for sid, _ in seed_sections]).items():
                section_score = dict(seed_sections).get(section_id, 0.0)
                for entity_id in entity_ids:
                    scores[entity_id] += section_score * 0.25
        top_seeds = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[: cfg.max_entities // 2]
        scores = defaultdict(float, dict(top_seeds))
        path.seeds = [entity_id for entity_id, _ in top_seeds]
        seed_entities = self.store.entities(path.seeds)
        yield {
            "type": "seeds",
            "entities": [
                {"id": eid, "name": seed_entities[eid].name, "type": seed_entities[eid].type, "score": round(score, 4)}
                for eid, score in top_seeds
                if eid in seed_entities
            ],
            "sections": [{"id": sid, "heading": self._headings.get(sid, ""), "score": round(score, 4)} for sid, score in seed_sections],
        }

        # 2. expand
        adjacency = self.store.adjacency()
        generic = {eid for eid, entity in seed_entities.items() if entity.generic}
        frontier = list(path.seeds)
        for hop in range(1, cfg.max_hops + 1):
            edges: list[Hop] = []
            next_frontier: list[str] = []
            for node in frontier:
                if node in generic:
                    continue
                neighbours = adjacency.get(node, [])
                if not neighbours:
                    continue
                relations = self.store.relations([rid for _, rid, _ in neighbours])
                weighted: list[tuple[str, str, float]] = []
                for neighbour, rid, weight in neighbours:
                    relation = relations.get(rid)
                    if relation is None:
                        continue
                    overlap = len(question_terms & set(tokenize(relation.fact))) / (len(question_terms) or 1)
                    weighted.append((neighbour, rid, weight * (1.0 + overlap)))
                mass = sum(w for _, _, w in weighted) or 1.0
                for neighbour, rid, w in weighted:
                    contribution = scores[node] * (cfg.decay**hop) * (w / mass)
                    if contribution <= 0:
                        continue
                    fresh = neighbour not in scores
                    scores[neighbour] += contribution
                    relation_scores[rid] += contribution
                    edges.append(Hop(from_id=node, to_id=neighbour, relation_id=rid, hop=hop, score=contribution))
                    if fresh:
                        reached_by_graph.add(neighbour)
                        next_frontier.append(neighbour)
            if len(scores) > cfg.max_entities:
                keep = {eid for eid, _ in sorted(scores.items(), key=lambda p: (-p[1], p[0]))[: cfg.max_entities]}
                edges = [e for e in edges if e.to_id in keep and e.from_id in keep]
                next_frontier = [n for n in next_frontier if n in keep]
                scores = defaultdict(float, {eid: s for eid, s in scores.items() if eid in keep})
            path.hops.extend(edges)
            hop_relations = self.store.relations([e.relation_id for e in edges])
            hop_entities = self.store.entities([e.to_id for e in edges])
            generic |= {eid for eid, entity in hop_entities.items() if entity.generic}
            yield {
                "type": "hop",
                "hop": hop,
                "edges": [
                    {
                        "from_id": e.from_id,
                        "to_id": e.to_id,
                        "to_name": hop_entities[e.to_id].name if e.to_id in hop_entities else "",
                        "to_type": hop_entities[e.to_id].type if e.to_id in hop_entities else "",
                        "relation_id": e.relation_id,
                        "predicate": hop_relations[e.relation_id].predicate if e.relation_id in hop_relations else "",
                        "score": round(e.score, 4),
                    }
                    for e in sorted(edges, key=lambda e: -e.score)
                ],
            }
            frontier = next_frontier
            if not frontier:
                break

        # 3. evidence
        candidates = self._candidates(scores, relation_scores, reached_by_graph, seed_sections)
        chosen = _select(candidates, cfg.max_evidence, cfg.graph_share)
        path.evidence = [c.evidence for c in chosen]
        if sink is not None:
            sink.extend(chosen)
        yield {
            "type": "evidence",
            "items": [
                {
                    "n": n,
                    "url": c.evidence.url,
                    "xpath": c.evidence.block_xpath,
                    "anchor": c.evidence.anchor,
                    "quote": c.evidence.quote,
                    "section_id": c.evidence.section_id,
                    "heading": c.heading,
                    "entity_ids": list(c.entity_ids),
                    "source": c.source,
                    "score": round(c.score, 4),
                }
                for n, c in enumerate(chosen, start=1)
            ],
            "path": path.as_dict(),
        }

    def ask(self, question: str) -> Iterator[dict[str, Any]]:
        chosen: list[_Candidate] = []
        path = QueryPath()
        for event in self.retrieve(question, sink=chosen):
            if event["type"] == "evidence":
                path_dict = event["path"]
                path = QueryPath(
                    seeds=list(path_dict["seeds"]),
                    hops=[Hop(h["from_id"], h["to_id"], h["relation_id"], h["hop"], h["score"]) for h in path_dict["hops"]],
                    evidence=[c.evidence for c in chosen],
                )
            yield event

        # 4. answer
        lines = [
            f'[{n}] {c.evidence.url} | {c.heading or "(page)"} | "{c.evidence.quote}"'
            for n, c in enumerate(chosen, start=1)
        ]
        usage = Usage()
        if self.provider is None:
            # One quoted sentence per row, so the sentence splitter sees a boundary between
            # quotes that begin mid-sentence in lowercase.
            text = "Not stated on this site." if not chosen else " ".join(
                f"\u201c{c.evidence.quote.rstrip('.')}\u201d [{n}]." for n, c in enumerate(chosen[:3], start=1)
            )
            model = "none"
        else:
            try:
                result = self.provider.complete_text(
                    ANSWER_SYSTEM,
                    answer_prompt(question, lines),
                    model=self.provider.config.answer_model or self.provider.config.model or None,
                )
            except LLMError as exc:
                yield {"type": "error", "message": f"answer model failed: {exc}"}
                return
            text, usage, model = result.text, result.usage, result.model
        answer = parse_answer(text, chosen_to_citations(chosen), path)
        answer.usage = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "model": model,
            "usd": self.provider.config.usd(usage) if self.provider is not None else None,
        }
        for sentence in answer.sentences:
            yield {"type": "answer_delta", **sentence.as_dict()}
        yield {"type": "answer", **answer.as_dict()}

    # -- evidence gathering ---------------------------------------------------------------

    def _candidates(
        self,
        scores: dict[str, float],
        relation_scores: dict[str, float],
        reached_by_graph: set[str],
        seed_sections: list[tuple[str, float]],
    ) -> list[_Candidate]:
        out: list[_Candidate] = []
        seen: set[str] = set()

        def add(ev: Evidence, entity_ids: tuple[str, ...], score: float, source: str) -> None:
            if ev.id in seen:
                return
            seen.add(ev.id)
            out.append(_Candidate(ev, self._headings.get(ev.section_id, ""), entity_ids, score, source))

        top_relations = sorted(relation_scores.items(), key=lambda p: (-p[1], p[0]))[: self.config.max_relations]
        relations: dict[str, Relation] = self.store.relations([rid for rid, _ in top_relations])
        for rid, score in top_relations:
            relation = relations.get(rid)
            if relation is None:
                continue
            source = "graph" if (relation.subject_id in reached_by_graph or relation.object_id in reached_by_graph) else "seed"
            for ev in relation.evidence[:2]:
                add(ev, (relation.subject_id, relation.object_id), score, source)

        top_entities = sorted(scores.items(), key=lambda p: (-p[1], p[0]))[: self.config.max_entities]
        entities: dict[str, Entity] = self.store.entities([eid for eid, _ in top_entities])
        for eid, score in top_entities:
            entity = entities.get(eid)
            if entity is None:
                continue
            source = "graph" if eid in reached_by_graph else "seed"
            for values in entity.attributes.values():
                for attr in values:
                    add(attr.evidence, (eid,), score * 1.2, source)
            for mention in entity.mentions[:2]:
                add(mention.evidence, (eid,), score * 0.8, source)

        if self.graph is not None:
            for section_id, score in seed_sections:
                section = self.graph.sections.get(section_id)
                page = self.graph.pages.get(section.page_key) if section else None
                if section is None or page is None:
                    continue
                for ref in section.blocks[:6]:
                    text = ref.slice(section.text)
                    if not text.strip() or ref.kind in {"code", "image"}:
                        continue
                    quote = text[:_SECTION_QUOTE_CHARS]
                    ev = Evidence(page.key, page.url, section.id, ref.xpath, (0, len(quote)), quote, page.content_hash)
                    add(ev, (), score * 0.5, "section")
        return out


def _select(candidates: list[_Candidate], limit: int, graph_share: float) -> list[_Candidate]:
    """Best first, with a reserved share of slots for evidence reached by expansion."""
    ranked = sorted(candidates, key=lambda c: (-c.score, c.evidence.id))
    reserved = int(limit * graph_share)
    graph_rows = [c for c in ranked if c.source == "graph"][:reserved]
    chosen = list(graph_rows)
    for c in ranked:
        if len(chosen) >= limit:
            break
        if c not in chosen:
            chosen.append(c)
    return sorted(chosen, key=lambda c: (-c.score, c.evidence.id))[:limit]


def chosen_to_citations(chosen: list[_Candidate]) -> list[Citation]:
    return [
        Citation(
            n=n,
            url=c.evidence.url,
            xpath=c.evidence.block_xpath,
            quote=c.evidence.quote,
            section_id=c.evidence.section_id,
            entity_ids=c.entity_ids,
        )
        for n, c in enumerate(chosen, start=1)
    ]


def parse_answer(text: str, citations: list[Citation], path: QueryPath) -> Answer:
    """Split the model's text into sentences and check each one's citations.

    A sentence is *supported* when at least one of its `[n]` markers names a real evidence
    row. One with no valid marker is kept, flagged `unsupported`, so the reader sees both
    what the model said and that nothing on the site was cited for it. An answer that is
    only the abstention sentence is `abstained` and needs no citation.
    """
    valid = {c.n for c in citations}
    clean = " ".join(text.split())
    abstained = bool(_ABSTAIN.search(clean)) and len(_CITE.findall(clean)) == 0
    pieces = [p.strip() for p in _split_sentences(clean) if p.strip()]
    sentences: list[Sentence] = []
    used: Counter[int] = Counter()
    for piece in pieces:
        numbers = tuple(dict.fromkeys(int(n) for n in _CITE.findall(piece) if int(n) in valid))
        used.update(numbers)
        is_claim = len(_CITE.sub("", piece).split()) >= 3 and not _ABSTAIN.search(piece)
        sentences.append(Sentence(text=piece, citations=numbers, unsupported=is_claim and not numbers))
    cited = [c for c in citations if c.n in used]
    answer_nodes = list(dict.fromkeys(eid for c in cited for eid in c.entity_ids))
    path.answer_nodes = answer_nodes
    return Answer(text=clean, sentences=sentences, citations=cited, path=path, abstained=abstained)


_ABBREVIATION: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)(?:[A-Z]|[A-Za-z]\.[A-Za-z]|Dr|Prof|Mr|Mrs|Ms|Sr|Jr|St|No|Nos|vs|etc|Inc|Ltd|Co|Fig|approx|Rs|Ph\.D|Tech|Sc|Com)$"
)
"""The word before a period that does not end a sentence: an initial (`B.E.`), a title
(`Dr.`), a common abbreviation. Checked on the text before the stop."""


def _split_sentences(text: str) -> list[str]:
    """Sentences with their trailing citations attached, whichever side of the stop they sit."""
    out: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        before = text[start : match.start()].rstrip()
        head = before[:-1] if before.endswith((".", "!", "?")) else before
        if before.endswith(".") and _ABBREVIATION.search(head):
            continue
        out.append(text[start : match.end()].strip())
        start = match.end()
    out.append(text[start:].strip())
    return [s for s in out if s]
