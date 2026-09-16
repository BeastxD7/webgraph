"""One section in, verified assertions out.

The model is asked for entities, attributes and relations, each carrying the `[bN]` marker
of the block it read and a verbatim quote from that block. This module owns the two halves
of that contract: it renders the section with markers, and it checks every quote against
the block's text before anything becomes a row. A quote that is not found is a rejected
assertion, counted by reason -- never a row with a weaker confidence, because a wrong xpath
is worse than no assertion.

Verification is exact after normalisation, not fuzzy. Normalisation is what a copying model
plausibly changes without changing the words: whitespace, Unicode compatibility forms, curly
quotes and dashes, and Markdown syntax around a link or an emphasis. Each normalised character
keeps its index in the original text, so the span recorded is in the block's own coordinates.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Final

import jsonschema

from webgraph.graph.model import BlockRef, PageNode, Section
from webgraph.kg.model import Attribute, Evidence, snake_case
from webgraph.kg.prompts import (
    EXTRACT_SCHEMA,
    EXTRACT_SYSTEM,
    PREDICATE_SYNONYMS,
    REVERSED,
    extract_prompt,
)
from webgraph.kg.providers import LLMError, Provider, Usage

__all__ = [
    "Extracted",
    "ExtractedEntity",
    "ExtractedMention",
    "ExtractedRelation",
    "Prepared",
    "extract_section",
    "locate_quote",
    "normalise_predicate",
    "prepare",
    "verify",
]

MAX_QUOTE_CHARS: Final[int] = 400
_MD_LINK: Final[re.Pattern[str]] = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_IMAGE: Final[re.Pattern[str]] = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_QUOTES: Final[dict[str, str]] = {
    "\u201c": '"', "\u201d": '"', "\u201e": '"',  # curly double quotes
    "\u2018": "'", "\u2019": "'", "\u201a": "'",  # curly single quotes
    "\u2013": "-", "\u2014": "-", "\u2010": "-",  # dashes
    "\u00a0": " ",  # no-break space
}
_SYNTAX: Final[frozenset[str]] = frozenset("*_`")


@dataclass(frozen=True, slots=True)
class Prepared:
    section: Section
    page: PageNode
    blocks: list[tuple[str, str, BlockRef]]
    """`(marker, text, ref)` for each citable block, in order."""

    prompt: str
    known: list[tuple[str, str]]

    @property
    def input_chars(self) -> int:
        return len(EXTRACT_SYSTEM) + len(self.prompt)


@dataclass(frozen=True, slots=True)
class ExtractedMention:
    surface: str
    evidence: Evidence


@dataclass(slots=True)
class ExtractedEntity:
    name: str
    type: str
    aliases: list[str] = field(default_factory=list)
    attributes: list[Attribute] = field(default_factory=list)
    mentions: list[ExtractedMention] = field(default_factory=list)


@dataclass(slots=True)
class ExtractedRelation:
    subject: str
    predicate: str
    object: str
    fact: str
    evidence: list[Evidence]


@dataclass(slots=True)
class Extracted:
    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    rejected: Counter[str] = field(default_factory=Counter)
    misnumbered: int = 0
    """Quotes found in a block other than the one the model named. Kept, and counted,
    because a rising number says the model is not reading the markers."""

    usage: Usage = field(default_factory=Usage)
    cached: bool = False

    @property
    def accepted(self) -> int:
        return sum(len(e.mentions) + len(e.attributes) for e in self.entities) + sum(
            len(r.evidence) for r in self.relations
        )

    @property
    def rejected_count(self) -> int:
        return sum(self.rejected.values())


def prepare(section: Section, page: PageNode, known: list[tuple[str, str]], *, heading_path: str = "") -> Prepared:
    """Render the section for the model, with a marker per block."""
    blocks: list[tuple[str, str, BlockRef]] = []
    for index, ref in enumerate(section.blocks):
        text = ref.slice(section.text)
        if text.strip():
            blocks.append((f"b{index}", text, ref))
    prompt = extract_prompt(
        url=page.url,
        title=page.title,
        heading_path=heading_path or section.heading,
        blocks=[(marker, text) for marker, text, _ in blocks],
        known_entities=known,
    )
    return Prepared(section=section, page=page, blocks=blocks, prompt=prompt, known=known)


def extract_section(provider: Provider, prepared: Prepared, *, model: str | None = None) -> tuple[Extracted, str]:
    """Call the model once (twice on a schema violation), verify, and return the result with
    the raw response text so the caller can cache it."""
    usage = Usage()
    raw_text = ""
    last_error = ""
    for attempt in range(2):
        user = prepared.prompt if not last_error else (
            f"{prepared.prompt}\n\nYour previous reply was rejected: {last_error[:300]}. "
            "Return only the JSON object."
        )
        try:
            result = provider.complete_json(EXTRACT_SYSTEM, user, EXTRACT_SCHEMA, model=model)
        except LLMError as exc:
            if exc.retryable and attempt == 0:
                last_error = str(exc)
                continue
            raise
        usage = usage + result.usage
        raw_text = result.text
        try:
            payload = result.json()
            jsonschema.validate(payload, EXTRACT_SCHEMA)
        except LLMError as exc:
            last_error = str(exc)
            continue
        except jsonschema.ValidationError as exc:
            last_error = exc.message
            continue
        extracted = verify(payload, prepared)
        extracted.usage = usage
        return extracted, raw_text
    rejected: Counter[str] = Counter({"invalid_json" if "JSON" in last_error else "schema_violation": 1})
    return Extracted(rejected=rejected, usage=usage), raw_text


def verify(payload: dict[str, Any], prepared: Prepared) -> Extracted:
    """Keep only assertions whose quote is found in a block of this section."""
    out = Extracted()
    by_marker = {marker: (text, ref) for marker, text, ref in prepared.blocks}
    page, section = prepared.page, prepared.section

    def evidence_for(item: Any) -> Evidence | None:
        if not isinstance(item, dict):
            out.rejected["bad_evidence"] += 1
            return None
        marker = str(item.get("block") or "").strip().strip("[]")
        quote = str(item.get("quote") or "")
        if not quote.strip():
            out.rejected["empty_quote"] += 1
            return None
        if len(quote) > MAX_QUOTE_CHARS:
            out.rejected["quote_too_long"] += 1
            return None
        # The named block first, then the others: models mis-number more often than they
        # invent, and the quote is what is being verified, not the model's arithmetic.
        order = ([marker] if marker in by_marker else []) + [m for m in by_marker if m != marker]
        for candidate in order:
            text, ref = by_marker[candidate]
            span = locate_quote(text, quote)
            if span is not None:
                if candidate != marker:
                    out.misnumbered += 1
                return Evidence(
                    page_key=page.key,
                    url=page.url,
                    section_id=section.id,
                    block_xpath=ref.xpath,
                    span=span,
                    quote=text[span[0] : span[1]],
                    content_hash=page.content_hash,
                )
        out.rejected["quote_not_found"] += 1
        return None

    names: dict[str, ExtractedEntity] = {}
    for raw in payload.get("entities") or []:
        if not isinstance(raw, dict):
            continue
        name = " ".join(str(raw.get("name") or "").split())
        etype = _pascal(str(raw.get("type") or "Thing"))
        if not name:
            out.rejected["empty_name"] += 1
            continue
        entity = names.get(name) or ExtractedEntity(name=name, type=etype)
        for alias in raw.get("aliases") or []:
            clean = " ".join(str(alias).split())
            if clean and clean != name and clean not in entity.aliases:
                entity.aliases.append(clean)
        for mention in raw.get("mentions") or []:
            ev = evidence_for(mention)
            if ev is not None:
                entity.mentions.append(ExtractedMention(surface=str(mention.get("quote") or name)[:200], evidence=ev))
        for attribute in raw.get("attributes") or []:
            if not isinstance(attribute, dict):
                continue
            key = snake_case(str(attribute.get("key") or ""))
            value = " ".join(str(attribute.get("value") or "").split())
            if not key or not value:
                out.rejected["empty_attribute"] += 1
                continue
            ev = evidence_for(attribute)
            if ev is not None:
                entity.attributes.append(Attribute(key=key, value=value[:200], unit=str(attribute.get("unit") or "")[:40], evidence=ev))
        if entity.mentions or entity.attributes:
            names[name] = entity
        else:
            out.rejected["entity_without_evidence"] += 1

    for raw in payload.get("relations") or []:
        if not isinstance(raw, dict):
            continue
        subject = " ".join(str(raw.get("subject") or "").split())
        obj = " ".join(str(raw.get("object") or "").split())
        predicate = normalise_predicate(str(raw.get("predicate") or ""))
        if snake_case(str(raw.get("predicate") or "")) in REVERSED:
            subject, obj = obj, subject
        if not subject or not obj:
            out.rejected["empty_relation"] += 1
            continue
        if subject == obj:
            out.rejected["self_relation"] += 1
            continue
        if subject not in names or obj not in names:
            # A relation between names the model never grounded as entities. Not
            # inventing entities for it: those would be rows with no mention evidence.
            out.rejected["unknown_entity_in_relation"] += 1
            continue
        evidence = [ev for ev in (evidence_for(e) for e in raw.get("evidence") or []) if ev is not None]
        if not evidence:
            out.rejected["relation_without_evidence"] += 1
            continue
        fact = " ".join(str(raw.get("fact") or "").split())[:200] or f"{subject} {predicate.replace('_', ' ')} {obj}"
        out.relations.append(ExtractedRelation(subject=subject, predicate=predicate, object=obj, fact=fact, evidence=evidence))

    out.entities = list(names.values())
    return out


def normalise_predicate(predicate: str) -> str:
    snake = snake_case(predicate)
    return PREDICATE_SYNONYMS.get(snake, snake)


def _pascal(type_name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", type_name.strip())
    joined = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return joined or "Thing"


def _normalise(text: str, *, keep_map: bool) -> tuple[str, list[int]]:
    """Normalised text and, per normalised character, its index in `text`.

    Markdown link and image syntax collapses to the label; emphasis and code markers are
    dropped; runs of whitespace become one space; typographic quotes and dashes become
    their ASCII forms; NFKC handles ligatures and full-width forms. Nothing here changes
    a word, so a match after normalisation is still a verbatim match.
    """
    # Link syntax first, on the raw string, recording which original indexes survive.
    keep = [True] * len(text)
    for pattern in (_MD_IMAGE, _MD_LINK):
        for m in pattern.finditer(text):
            label_start = m.start(1)
            label_end = m.end(1)
            for i in range(m.start(), m.end()):
                if not (label_start <= i < label_end):
                    keep[i] = False
    out: list[str] = []
    mapping: list[int] = []
    previous_space = True
    for index, char in enumerate(text):
        if not keep[index] or char in _SYNTAX:
            continue
        char = _QUOTES.get(char, char)
        for folded in unicodedata.normalize("NFKC", char):
            if folded.isspace():
                if previous_space:
                    continue
                out.append(" ")
                mapping.append(index)
                previous_space = True
            else:
                out.append(folded)
                mapping.append(index)
                previous_space = False
    while out and out[-1] == " ":
        out.pop()
        mapping.pop()
    return "".join(out), (mapping if keep_map else [])


def locate_quote(block_text: str, quote: str) -> tuple[int, int] | None:
    """Character span of `quote` in `block_text`, or `None` if it is not there verbatim."""
    needle, _ = _normalise(quote, keep_map=False)
    if not needle:
        return None
    haystack, mapping = _normalise(block_text, keep_map=True)
    at = haystack.find(needle)
    if at < 0:
        # Same letters in the same order, different case: a model that starts its quote
        # with a capital or lower-cases a heading has still copied the words. Length-
        # preserving folding keeps the index map valid.
        at = _fold(haystack).find(_fold(needle))
        if at < 0:
            return None
    start = mapping[at]
    end = mapping[at + len(needle) - 1] + 1
    return start, end


def _fold(text: str) -> str:
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text)
