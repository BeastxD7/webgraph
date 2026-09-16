"""Prompts, the model's output schema, and the type vocabulary.

`PROMPT_VERSION` is part of the LLM cache key: change a prompt, bump it, and every section
is re-read; leave it, and a re-crawl costs only the sections whose text changed.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = [
    "ANSWER_SYSTEM",
    "CORE_TYPES",
    "EXTRACT_SCHEMA",
    "EXTRACT_SYSTEM",
    "PREDICATE_SYNONYMS",
    "PROMPT_VERSION",
    "answer_prompt",
    "extract_prompt",
]

PROMPT_VERSION: Final[str] = "extract-v1/answer-v1"

CORE_TYPES: Final[tuple[str, ...]] = (
    "Organization",
    "Person",
    "Product",
    "Service",
    "Course",
    "Event",
    "Place",
    "Document",
    "Offer",
    "Topic",
    "ContactPoint",
    "Role",
)
"""Twelve core types; anything else is allowed as the most specific PascalCase noun and is
counted in `/api/graph/stats` so a frequent open type can be promoted for that site."""

PREDICATE_SYNONYMS: Final[dict[str, str]] = {
    "is_part_of": "part_of",
    "belongs_to": "part_of",
    "member_of": "part_of",
    "works_at": "affiliated_with",
    "works_for": "affiliated_with",
    "employed_by": "affiliated_with",
    "affiliated_to": "affiliated_with",
    "located_at": "located_in",
    "based_in": "located_in",
    "situated_in": "located_in",
    "offered_by": "offers",
    "provides": "offers",
    "teaches_at": "teaches",
    "taught_by": "teaches",
    "headed_by": "heads",
    "led_by": "heads",
    "leads": "heads",
    "principal_of": "heads",
    "director_of": "heads",
    "founded_by": "founded",
    "established_by": "founded",
    "contact": "has_contact",
    "phone": "has_contact",
    "email": "has_contact",
    "accredited_by": "accredited_by",
    "approved_by": "accredited_by",
    "recognised_by": "accredited_by",
    "recognized_by": "accredited_by",
    "affiliated_with_university": "affiliated_with",
}
"""A small table, on purpose. Predicates are free text from the model, snake_cased, and
these collapse the spellings that are the same relation; anything else is kept as written.
Note the directional ones are folded to one predicate but *not* reversed -- `taught_by` is
mapped to `teaches` only when the extractor also swaps subject and object, which
`extract.py` does for the entries in `REVERSED`."""

REVERSED: Final[frozenset[str]] = frozenset({"taught_by", "headed_by", "led_by", "founded_by", "established_by", "offered_by"})

_EVIDENCE: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "block": {"type": "string", "description": "the [bN] marker of the block the quote is in"},
        "quote": {"type": "string", "description": "verbatim text copied from that block, 3-40 words"},
    },
    "required": ["block", "quote"],
    "additionalProperties": False,
}

EXTRACT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "value": {"type": "string"},
                                "unit": {"type": "string"},
                                "block": {"type": "string"},
                                "quote": {"type": "string"},
                            },
                            "required": ["key", "value", "unit", "block", "quote"],
                            "additionalProperties": False,
                        },
                    },
                    "mentions": {"type": "array", "items": _EVIDENCE},
                },
                "required": ["name", "type", "aliases", "attributes", "mentions"],
                "additionalProperties": False,
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object": {"type": "string"},
                    "fact": {"type": "string"},
                    "evidence": {"type": "array", "items": _EVIDENCE},
                },
                "required": ["subject", "predicate", "object", "fact", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["entities", "relations"],
    "additionalProperties": False,
}
"""Strict: every property required, no extras, so OpenAI `strict: true` accepts it and a
small local model has the least room to improvise."""

EXTRACT_SYSTEM: Final[str] = """You read one section of a web page and state, as data, what it says.

Rules:
1. Only what the section states. Nothing from your own knowledge, nothing implied.
2. Every mention, attribute and relation carries a `block` (the [bN] marker) and a `quote`
   copied VERBATIM from that block: same words, same spelling, same punctuation, 3 to 40
   words. Anything whose quote is not found verbatim in the block is discarded, so copy,
   never paraphrase.
3. Entity types: use one of Organization, Person, Product, Service, Course, Event, Place,
   Document, Offer, Topic, ContactPoint, Role when it fits; otherwise the most specific
   PascalCase noun. Prices, dates, durations, counts, phone numbers and emails are
   ATTRIBUTES of an entity (key, value, unit), never entities.
4. `name` is the entity's canonical name as the page writes it; put other spellings in
   `aliases`. Reuse the names in "Known entities" exactly when the section refers to them.
5. Relations: `predicate` is a short snake_case verb phrase (teaches, offers, part_of,
   located_in, heads, affiliated_with, accredited_by, has_contact). `fact` is one sentence
   of at most 200 characters restating the relation in the page's words.
6. Return only the JSON object described by the schema. No commentary."""


def extract_prompt(
    *,
    url: str,
    title: str,
    heading_path: str,
    blocks: list[tuple[str, str]],
    known_entities: list[tuple[str, str]],
) -> str:
    """The user turn: page context, known entities, and the section with block markers.

    Short markers (`[b3]`) rather than XPaths keep the output small and the mapping ours.
    """
    known = "\n".join(f"- {name} ({type_})" for name, type_ in known_entities) or "- (none)"
    body = "\n\n".join(f"[{marker}] {text}" for marker, text in blocks)
    return (
        f"Page: {title or url}\nURL: {url}\nHeading path: {heading_path or '(top of page)'}\n\n"
        f"Known entities on this page (use these names exactly):\n{known}\n\n"
        f"Section blocks:\n\n{body}\n\n"
        "Return the JSON object."
    )


ANSWER_SYSTEM: Final[str] = """You answer a question about one website using only the numbered evidence provided.

Rules:
1. Every sentence that states a fact ends with the citation(s) that support it, written
   as [n] with n from the evidence list. A sentence may carry several: [2][5].
2. If the evidence does not answer the question, reply with exactly one sentence:
   "Not stated on this site." and no citation.
3. Do not use knowledge from outside the evidence. Do not cite a number that is not in
   the list. Prefer the evidence's own words for names, numbers and dates.
4. Be brief: usually one to four sentences. No preamble, no headings, no bullet lists."""


def answer_prompt(question: str, evidence_lines: list[str]) -> str:
    listing = "\n".join(evidence_lines) or "(no evidence found)"
    return f"Question: {question}\n\nEvidence:\n{listing}\n\nAnswer with citations:"
