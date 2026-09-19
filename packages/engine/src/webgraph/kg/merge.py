"""Turn per-section extractions into one graph: deterministic merge, no model.

Three rules, in order of confidence:

1. **Same type, same normalised name** is one entity (`model.norm_name`: NFKC, casefold,
   whitespace, edge punctuation, possessive). LightRAG's open duplicate issue (#1323) is exact
   match without casefolding; this is the fix's deterministic half.
2. **Aliases the model returned** merge a new name into an existing same-type entity, and an
   open type (`Faculty`) merges into a same-name core type (`Person`). Two *core* types with
   one name -- `Person` vs `Organization` -- stay apart: that is a real ambiguity, not a
   spelling.
3. **Near-duplicates**: MinHash/LSH over 3-gram shingles of the normalised name proposes
   candidate pairs; a pair of the same type with exact Jaccard >= 0.9 merges. That catches a
   typo or a doubled space, not a synonym. No LLM adjudication (graphiti's last step): it
   is the expensive, non-reproducible part, and v1 measures without it first.

Structured data first. JSON-LD and microdata entities the page published enter before any
model output, typed by the site itself; on a type conflict the structured type wins, which
is `Fact.outranks` applied to the graph.

The generic-name guard is `graph/entities.py`'s: an entity named on more than 60% of pages
is the site's own name. It stays an entity -- it is real -- but retrieval never expands
through it, because a hop through it reaches everything, which reaches nothing.

Everything is order-dependent and the order is fixed by the caller (sections by page
in-degree, depth, position), so two builds of one crawl produce one graph.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final

from webgraph import config
from webgraph.graph.model import Entity as ObservedEntity
from webgraph.graph.model import SiteGraph
from webgraph.kg.extract import Extracted, locate_quote
from webgraph.kg.model import (
    Attribute,
    Entity,
    Evidence,
    Mention,
    Relation,
    entity_id,
    norm_name,
    relation_id,
    snake_case,
)
from webgraph.kg.prompts import CORE_TYPES
from webgraph.types import Extractor

__all__ = ["STRUCTURED_TYPE_MAP", "MergeResult", "Merger", "jaccard", "shingles"]

_CORE: Final[frozenset[str]] = frozenset(CORE_TYPES)
STRUCTURED_TYPE_MAP: Final[dict[str, str]] = {
    "EducationalOrganization": "Organization",
    "CollegeOrUniversity": "Organization",
    "School": "Organization",
    "Corporation": "Organization",
    "LocalBusiness": "Organization",
    "NGO": "Organization",
    "GovernmentOrganization": "Organization",
    "Article": "Document",
    "NewsArticle": "Document",
    "BlogPosting": "Document",
    "WebPage": "Document",
    "Thing": "Topic",
}
_STRUCTURED_ATTRIBUTES: Final[tuple[str, ...]] = (
    "price",
    "startDate",
    "endDate",
    "jobTitle",
    "telephone",
    "email",
    "duration",
    "datePublished",
    "foundingDate",
    "priceCurrency",
)
_MINHASH_K: Final[int] = 64
_BANDS: Final[int] = 16
_PRIME: Final[int] = (1 << 61) - 1
_RNG = random.Random(20260916)
_HASHES: Final[list[tuple[int, int]]] = [
    (_RNG.randrange(1, _PRIME), _RNG.randrange(0, _PRIME)) for _ in range(_MINHASH_K)
]


def shingles(name: str, n: int = 3) -> frozenset[str]:
    padded = f"  {norm_name(name)} "
    if len(padded) < n:
        return frozenset({padded})
    return frozenset(padded[i : i + n] for i in range(len(padded) - n + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _minhash(shingle_set: frozenset[str]) -> list[int]:
    # A stable hash, not `hash()`: string hashing is salted per process, and the merge
    # must produce the same graph from one run to the next.
    values = [
        int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=6).digest(), "big")
        for s in sorted(shingle_set)
    ]
    return [min((a * v + b) % _PRIME for v in values) for a, b in _HASHES]


@dataclass(slots=True)
class MergeResult:
    entities: dict[str, Entity]
    relations: dict[str, Relation]
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _Draft:
    type: str
    name: str
    aliases: list[str] = field(default_factory=list)
    attributes: list[Attribute] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    extractor: Extractor = Extractor.LLM
    order: int = 0

    @property
    def key(self) -> tuple[str, str]:
        return (self.type, norm_name(self.name))

    @property
    def evidence_count(self) -> int:
        return len(self.mentions) + len(self.attributes)


class Merger:
    def __init__(
        self,
        *,
        jaccard_threshold: float = config.KG_MERGE_JACCARD,
        generic_page_share: float = config.KG_GENERIC_PAGE_SHARE,
        total_pages: int = 0,
        seen_at: str = "",
    ) -> None:
        self.jaccard_threshold = jaccard_threshold
        self.generic_page_share = generic_page_share
        self.total_pages = total_pages
        self.seen_at = seen_at
        self._drafts: dict[tuple[str, str], _Draft] = {}
        self._by_norm: dict[str, list[tuple[str, str]]] = defaultdict(list)
        """norm(name or alias) -> keys of drafts that answer to it."""
        self._relations: list[tuple[str, str, str, str, list[Evidence]]] = []
        self._counter = 0
        self.stats: Counter[str] = Counter()

    # -- inputs ---------------------------------------------------------------------------

    def add_structured(self, graph: SiteGraph) -> None:
        """JSON-LD / microdata entities, located in the page text so they carry evidence."""
        for observed in sorted(graph.entities.values(), key=lambda e: (e.type, e.name, e.key)):
            if (
                observed.type in {"Subject", "Symbol"}
                or not observed.name
                or len(observed.name) < 3
            ):
                continue
            draft = self._locate_structured(graph, observed)
            if draft is None:
                self.stats["structured_not_on_page"] += 1
                continue
            self.stats["structured_entities"] += 1
            self._absorb(draft)

    def _locate_structured(self, graph: SiteGraph, observed: ObservedEntity) -> _Draft | None:
        etype = STRUCTURED_TYPE_MAP.get(observed.type, observed.type)
        draft = _Draft(type=etype, name=observed.name, extractor=Extractor.STRUCTURED_DATA)
        data = observed.data if isinstance(observed.data, dict) else {}
        wanted = {k: _scalar(data.get(k)) for k in _STRUCTURED_ATTRIBUTES if _scalar(data.get(k))}
        offers = data.get("offers")
        if isinstance(offers, dict):
            for k in ("price", "priceCurrency"):
                value = _scalar(offers.get(k))
                if value:
                    wanted[k] = value
        currency = wanted.pop("priceCurrency", "")
        for page_key in observed.pages:
            page = graph.pages.get(page_key)
            if page is None:
                continue
            for section in graph.sections_of(page_key):
                for ref in section.blocks:
                    text = ref.slice(section.text)
                    span = locate_quote(text, observed.name)
                    if span is not None:
                        ev = Evidence(
                            page.key,
                            page.url,
                            section.id,
                            ref.xpath,
                            span,
                            text[span[0] : span[1]],
                            page.content_hash,
                        )
                        draft.mentions.append(
                            Mention(entity_id="", surface=observed.name, evidence=ev)
                        )
                    for key, value in list(wanted.items()):
                        vspan = locate_quote(text, value)
                        if vspan is not None:
                            ev = Evidence(
                                page.key,
                                page.url,
                                section.id,
                                ref.xpath,
                                vspan,
                                text[vspan[0] : vspan[1]],
                                page.content_hash,
                            )
                            unit = currency if key == "price" else ""
                            draft.attributes.append(
                                Attribute(key=snake_case(key), value=value, unit=unit, evidence=ev)
                            )
                            del wanted[key]
        return draft if draft.mentions else None

    def add_extracted(self, extracted: Extracted) -> None:
        for entity in extracted.entities:
            draft = _Draft(
                type=entity.type,
                name=entity.name,
                aliases=list(entity.aliases),
                attributes=list(entity.attributes),
                mentions=[
                    Mention(entity_id="", surface=m.surface, evidence=m.evidence)
                    for m in entity.mentions
                ],
            )
            self._absorb(draft)
        for relation in extracted.relations:
            self._relations.append(
                (
                    relation.subject,
                    relation.predicate,
                    relation.object,
                    relation.fact,
                    list(relation.evidence),
                )
            )

    # -- merging ------------------------------------------------------------------------

    def _absorb(self, draft: _Draft) -> None:
        self._counter += 1
        draft.order = self._counter
        target = self._find_home(draft)
        if target is None:
            self._drafts[draft.key] = draft
            self._index(draft)
            return
        self._merge_into(target, draft)

    def _find_home(self, draft: _Draft) -> _Draft | None:
        norm = norm_name(draft.name)
        exact = self._drafts.get(draft.key)
        if exact is not None:
            return exact
        # Same name, different type: open type joins a core type; structured wins over LLM.
        for key in self._by_norm.get(norm, []):
            other = self._drafts.get(key)
            if other is None:
                continue
            if other.type == draft.type:
                return other
            if _compatible(other.type, draft.type):
                self.stats["type_reconciled"] += 1
                return other
        # The new name is an alias someone else declared, or one of its aliases is a name.
        for alias in draft.aliases:
            for key in self._by_norm.get(norm_name(alias), []):
                other = self._drafts.get(key)
                if other is not None and other.type == draft.type:
                    self.stats["alias_merged"] += 1
                    return other
        return None

    def _merge_into(self, target: _Draft, draft: _Draft) -> None:
        if (
            draft.extractor is Extractor.STRUCTURED_DATA
            and target.extractor is not Extractor.STRUCTURED_DATA
        ):
            # Structured wins: its type and its name, the model's rows underneath.
            del self._drafts[target.key]
            target.type, target.name, target.extractor = (
                draft.type,
                draft.name,
                Extractor.STRUCTURED_DATA,
            )
            self._drafts[target.key] = target
        elif target.type != draft.type and target.type not in _CORE and draft.type in _CORE:
            del self._drafts[target.key]
            target.type = draft.type
            self._drafts[target.key] = target
        for alias in [draft.name, *draft.aliases]:
            if norm_name(alias) != norm_name(target.name) and alias not in target.aliases:
                target.aliases.append(alias)
        target.mentions.extend(draft.mentions)
        target.attributes.extend(draft.attributes)
        self._index(target)
        self._index(draft, as_key=target.key)

    def _index(self, draft: _Draft, *, as_key: tuple[str, str] | None = None) -> None:
        key = as_key or draft.key
        for name in [draft.name, *draft.aliases]:
            bucket = self._by_norm[norm_name(name)]
            if key not in bucket:
                bucket.append(key)

    def _near_duplicates(self) -> None:
        drafts = sorted(self._drafts.values(), key=lambda d: d.order)
        if len(drafts) < 2:
            return
        sigs = {d.key: _minhash(shingles(d.name)) for d in drafts}
        rows = _MINHASH_K // _BANDS
        buckets: dict[tuple[str, int, tuple[int, ...]], list[tuple[str, str]]] = defaultdict(list)
        for d in drafts:
            sig = sigs[d.key]
            for band in range(_BANDS):
                buckets[(d.type, band, tuple(sig[band * rows : (band + 1) * rows]))].append(d.key)
        merged_into: dict[tuple[str, str], tuple[str, str]] = {}
        for members in buckets.values():
            if len(members) < 2:
                continue
            for i, a in enumerate(members):
                for b in members[i + 1 :]:
                    a_key, b_key = _resolve(merged_into, a), _resolve(merged_into, b)
                    if a_key == b_key or a_key not in self._drafts or b_key not in self._drafts:
                        continue
                    da, db = self._drafts[a_key], self._drafts[b_key]
                    if jaccard(shingles(da.name), shingles(db.name)) < self.jaccard_threshold:
                        continue
                    keep, drop = (
                        (da, db)
                        if (da.evidence_count, -da.order) >= (db.evidence_count, -db.order)
                        else (db, da)
                    )
                    del self._drafts[drop.key]
                    merged_into[drop.key] = keep.key
                    self._merge_into(keep, drop)
                    self.stats["near_duplicate_merged"] += 1

    # -- output ---------------------------------------------------------------------------

    def finish(self) -> MergeResult:
        self._near_duplicates()
        entities: dict[str, Entity] = {}
        id_of_key: dict[tuple[str, str], str] = {}
        for draft in sorted(self._drafts.values(), key=lambda d: d.order):
            eid = entity_id(draft.type, draft.name)
            id_of_key[draft.key] = eid
            attributes: dict[str, list[Attribute]] = defaultdict(list)
            seen_attr: set[tuple[str, str, str]] = set()
            for attr in draft.attributes:
                marker = (attr.key, norm_name(attr.value), attr.evidence.id)
                if marker not in seen_attr:
                    seen_attr.add(marker)
                    attributes[attr.key].append(attr)
            seen_mentions: set[str] = set()
            mentions: list[Mention] = []
            for mention in draft.mentions:
                if mention.evidence.id not in seen_mentions:
                    seen_mentions.add(mention.evidence.id)
                    mentions.append(
                        Mention(eid, mention.surface, mention.evidence, mention.confidence)
                    )
            entity = Entity(
                id=eid,
                type=draft.type,
                name=draft.name,
                aliases=tuple(dict.fromkeys(draft.aliases)),
                attributes=dict(attributes),
                mentions=mentions,
                extractor=draft.extractor,
                first_seen=self.seen_at,
                last_seen=self.seen_at,
            )
            if (
                self.total_pages
                and len(entity.pages) > self.total_pages * self.generic_page_share
                and self.total_pages >= 3
            ):
                entity.generic = True
                self.stats["generic_entities"] += 1
            entities[eid] = entity

        def resolve(name: str) -> str | None:
            for key in self._by_norm.get(norm_name(name), []):
                if key in id_of_key:
                    return id_of_key[key]
            return None

        relations: dict[str, Relation] = {}
        for subject, predicate, obj, fact, evidence in self._relations:
            sid, oid = resolve(subject), resolve(obj)
            if sid is None or oid is None:
                self.stats["relation_unresolved"] += 1
                continue
            if sid == oid:
                self.stats["relation_self"] += 1
                continue
            rid = relation_id(sid, predicate, oid)
            existing = relations.get(rid)
            if existing is None:
                relations[rid] = Relation(
                    id=rid,
                    subject_id=sid,
                    predicate=predicate,
                    object_id=oid,
                    fact=fact,
                    evidence=list(_dedupe(evidence)),
                    first_seen=self.seen_at,
                    last_seen=self.seen_at,
                )
            else:
                existing.evidence = list(_dedupe([*existing.evidence, *evidence]))
                self.stats["relation_merged"] += 1
        self.stats["entities"] = len(entities)
        self.stats["relations"] = len(relations)
        return MergeResult(entities=entities, relations=relations, stats=dict(self.stats))


def _dedupe(evidence: Iterable[Evidence]) -> Iterable[Evidence]:
    seen: set[str] = set()
    for ev in evidence:
        if ev.id not in seen:
            seen.add(ev.id)
            yield ev


def _resolve(
    mapping: dict[tuple[str, str], tuple[str, str]], key: tuple[str, str]
) -> tuple[str, str]:
    while key in mapping:
        key = mapping[key]
    return key


def _compatible(existing: str, incoming: str) -> bool:
    """An open type may join a core type of the same name; two core types may not."""
    return (existing in _CORE) != (incoming in _CORE) or (
        existing not in _CORE and incoming not in _CORE
    )


def _scalar(value: Any) -> str:
    if isinstance(value, str | int | float) and not isinstance(value, bool):
        text = str(value).strip()
        return text if 2 <= len(text) <= 120 else ""
    if isinstance(value, list) and value:
        return _scalar(value[0])
    return ""
