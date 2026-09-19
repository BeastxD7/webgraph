"""The knowledge graph's value types.

Everything here is a plain frozen dataclass, for the same reason `graph/model.py` is: the
graph is built in a process, held in a SQLite file, and exported to whatever wants it. No
row exists without evidence -- `Relation.evidence` is non-empty by construction, a `Mention`
is an `Evidence`, and an `Attribute` carries its own -- so there is no unverified tier to
filter out later. `Evidence.to_provenance` is the one-line bridge to `types.Provenance`,
which is what the rest of the engine cites with.

Identity is content-addressed and deterministic. Two builds of the same crawl with the same
model output produce the same ids, so a re-sync into Neo4j is a `MERGE`, not a duplicate.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Final

from webgraph.types import Extractor, Modality, Provenance

__all__ = [
    "Answer",
    "Attribute",
    "Citation",
    "Entity",
    "Evidence",
    "Hop",
    "Mention",
    "QueryPath",
    "Relation",
    "Sentence",
    "entity_id",
    "evidence_id",
    "norm_name",
    "relation_id",
    "snake_case",
]

_WS: Final[re.Pattern[str]] = re.compile(r"\s+")
_PUNCT = "\\s\"'\u201c\u201d\u2018\u2019.,;:!?()\\[\\]{}<>\u00ab\u00bb-"
_EDGE_PUNCT: Final[re.Pattern[str]] = re.compile(f"^[{_PUNCT}]+|[{_PUNCT}]+$")
_POSSESSIVE: Final[re.Pattern[str]] = re.compile("(?:'s|\u2019s)$")
_NOT_SNAKE: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
_CAMEL: Final[re.Pattern[str]] = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def norm_name(name: str) -> str:
    """The merge key for a name: NFKC, casefold, whitespace collapsed, edge punctuation and a
    trailing possessive removed. LightRAG's open duplicate bug (#1323) is exact match without
    casefolding; this is the deterministic part of the fix, and the only part v1 does."""
    text = unicodedata.normalize("NFKC", name)
    text = _WS.sub(" ", text).strip()
    text = _EDGE_PUNCT.sub("", text)
    text = _POSSESSIVE.sub("", text)
    return text.casefold().strip()


def snake_case(predicate: str) -> str:
    """`Teaches`, `teaches at`, `TEACHES_AT`, `teachesAt` -> `teaches_at`."""
    text = _CAMEL.sub("_", predicate.strip())
    text = _NOT_SNAKE.sub("_", text.lower()).strip("_")
    return text or "related_to"


def _short_hash(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def entity_id(entity_type: str, name: str) -> str:
    return "ent_" + _short_hash(entity_type, norm_name(name))


def relation_id(subject_id: str, predicate: str, object_id: str) -> str:
    return "rel_" + _short_hash(subject_id, snake_case(predicate), object_id)


def evidence_id(page_key: str, block_xpath: str, start: int, end: int) -> str:
    return "ev_" + _short_hash(page_key, block_xpath, str(start), str(end))


@dataclass(frozen=True, slots=True)
class Evidence:
    """A verbatim quote located in one block of one section of one page.

    This is what none of the systems studied store: a *span*. `block_xpath` is the block's
    provenance anchor, `span` the character offsets of `quote` inside that block's text, and
    `quote` the text itself so a reader can check without refetching. `content_hash` is the
    page's, so a later crawl can tell whether the evidence is still on the page.
    """

    page_key: str
    url: str
    section_id: str
    block_xpath: str
    span: tuple[int, int]
    quote: str
    content_hash: str = ""
    crawled_at: str = ""

    @property
    def id(self) -> str:
        return evidence_id(self.page_key, self.block_xpath, *self.span)

    @property
    def anchor(self) -> str:
        """`url#xpath`: the citation form every answer sentence uses."""
        return f"{self.url}#{self.block_xpath}" if self.block_xpath else self.url

    def to_provenance(self, *, confidence: float = 1.0) -> Provenance:
        return Provenance(
            source_url=self.url,
            extractor=Extractor.LLM,
            modality=Modality.TEXT,
            confidence=confidence,
            source_xpath=self.block_xpath or None,
            source_span=self.span,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "page_key": self.page_key,
            "url": self.url,
            "section_id": self.section_id,
            "block_xpath": self.block_xpath,
            "span": list(self.span),
            "quote": self.quote,
            "content_hash": self.content_hash,
            "crawled_at": self.crawled_at,
        }


@dataclass(frozen=True, slots=True)
class Mention:
    """An entity named in a block, with the words that named it."""

    entity_id: str
    surface: str
    evidence: Evidence
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class Attribute:
    """A typed value on an entity -- a price, a date, a duration -- with its evidence.

    Prices and dates are attributes, not entities: `Offer.price = 149 USD/month` is what
    makes an exact-match question answerable without a model reading anything.
    """

    key: str
    value: str
    unit: str
    evidence: Evidence


@dataclass(slots=True)
class Entity:
    id: str
    type: str
    name: str
    aliases: tuple[str, ...] = ()
    description: str | None = None
    attributes: dict[str, list[Attribute]] = field(default_factory=dict)
    mentions: list[Mention] = field(default_factory=list)
    extractor: Extractor = Extractor.LLM
    generic: bool = False
    """Named on most pages: kept, shown, but never expanded through."""

    first_seen: str = ""
    last_seen: str = ""

    @property
    def evidence_count(self) -> int:
        return len({m.evidence.id for m in self.mentions}) + sum(
            len(values) for values in self.attributes.values()
        )

    @property
    def pages(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(m.evidence.page_key for m in self.mentions))


@dataclass(slots=True)
class Relation:
    """`subject -predicate-> object`, stated in `fact`, quoted in `evidence` (never empty)."""

    id: str
    subject_id: str
    predicate: str
    object_id: str
    fact: str
    evidence: list[Evidence]
    confidence: float = 1.0
    valid_from: str | None = None
    valid_to: str | None = None
    first_seen: str = ""
    last_seen: str = ""
    retired_at: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("a relation without evidence cannot exist in the knowledge graph")

    @property
    def weight(self) -> int:
        """Distinct evidence blocks. A relation stated in three places outranks one stated once."""
        return len({(e.page_key, e.block_xpath) for e in self.evidence})


@dataclass(frozen=True, slots=True)
class Hop:
    from_id: str
    to_id: str
    relation_id: str
    hop: int
    score: float


@dataclass(slots=True)
class QueryPath:
    """What retrieval walked to answer a question -- streamed step by step to the UI."""

    seeds: list[str] = field(default_factory=list)
    hops: list[Hop] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    answer_nodes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seeds": list(self.seeds),
            "hops": [
                {
                    "from_id": h.from_id,
                    "to_id": h.to_id,
                    "relation_id": h.relation_id,
                    "hop": h.hop,
                    "score": round(h.score, 4),
                }
                for h in self.hops
            ],
            "evidence": [e.as_dict() for e in self.evidence],
            "answer_nodes": list(self.answer_nodes),
        }


@dataclass(frozen=True, slots=True)
class Citation:
    n: int
    url: str
    xpath: str
    quote: str
    section_id: str
    entity_ids: tuple[str, ...] = ()

    @property
    def anchor(self) -> str:
        return f"{self.url}#{self.xpath}" if self.xpath else self.url

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "url": self.url,
            "xpath": self.xpath,
            "anchor": self.anchor,
            "quote": self.quote,
            "section_id": self.section_id,
            "entity_ids": list(self.entity_ids),
        }


@dataclass(frozen=True, slots=True)
class Sentence:
    text: str
    citations: tuple[int, ...]
    unsupported: bool
    """True when the sentence makes a claim and cites nothing valid. Rendered dimmed, never
    dropped: a reader should see what the model said and that nothing on the site backs it."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "citations": list(self.citations),
            "unsupported": self.unsupported,
        }


@dataclass(slots=True)
class Answer:
    text: str
    sentences: list[Sentence]
    citations: list[Citation]
    path: QueryPath
    usage: dict[str, Any] = field(default_factory=dict)
    abstained: bool = False
    """The model said the site does not state it. The honest answer, and a scored one."""

    @property
    def unsupported_count(self) -> int:
        return sum(1 for s in self.sentences if s.unsupported)

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "sentences": [s.as_dict() for s in self.sentences],
            "citations": [c.as_dict() for c in self.citations],
            "path": self.path.as_dict(),
            "usage": dict(self.usage),
            "abstained": self.abstained,
            "unsupported": self.unsupported_count,
        }
