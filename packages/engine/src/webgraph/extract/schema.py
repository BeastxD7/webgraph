"""Map structured payloads onto a user-supplied JSON Schema.

This is where the zero-cost path turns into actual extracted facts. A page that ships
JSON-LD already contains the answer; the only work left is deciding which of its keys
corresponds to which field of the requested schema, coercing the value, and recording where
it came from.

Matching strategy, cheapest and most certain first:

1. **Exact key** at the current level (`price` -> `price`).
2. **Declared alias**, via the `x-webgraph-aliases` schema extension. Explicit beats clever:
   a caller who knows their domain can name the vocabulary directly.
3. **Normalised key** -- case and separators folded, so `priceAmount`, `price_amount` and
   `Price Amount` all match `price_amount`.
4. **Bounded descent** into nested objects, nearest match wins.

Confidence falls with each step, because each is a weaker claim about what the page meant.
Nothing here guesses at semantics: if no key matches, no fact is emitted. A missing value is
recoverable downstream; a wrong one silently poisons everything built on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from webgraph.types import (
    Extractor,
    Fact,
    Modality,
    PayloadSource,
    Provenance,
    StructuredPayload,
)

__all__ = [
    "ALIAS_EXTENSION",
    "SCHEMA_ORG_ALIASES",
    "extract_facts",
    "merge_facts",
    "normalize_key",
]

ALIAS_EXTENSION: Final[str] = "x-webgraph-aliases"
"""Schema keyword for caller-declared alternative key names."""

_NON_ALNUM: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")

_MAX_DESCENT: Final[int] = 6
"""How deep to search nested objects for a field. Hydration payloads nest deeply
(`props.pageProps.data.product.price`), but unbounded descent starts matching coincidences."""

SCHEMA_ORG_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "name": ("title", "headline", "productname", "og:title"),
    "title": ("name", "headline", "og:title"),
    "description": ("summary", "abstract", "og:description"),
    "price": ("priceamount", "amount", "lowprice", "offers.price"),
    "currency": ("pricecurrency", "currencycode"),
    "image": ("thumbnail", "imageurl", "og:image"),
    "url": ("permalink", "canonical", "og:url"),
    "brand": ("manufacturer", "vendor"),
    "sku": ("productid", "identifier", "mpn"),
    "author": ("creator", "byline"),
    "datepublished": ("published", "publishdate", "article:published_time"),
    "rating": ("ratingvalue", "aggregaterating"),
}
"""Vocabulary bridges for the fields that recur across schema.org, OpenGraph and ad-hoc
payloads. Deliberately small -- a large speculative table produces confident wrong matches."""

_CONFIDENCE: Final[dict[str, float]] = {
    "exact": 0.95,
    "declared-alias": 0.92,
    "normalized": 0.88,
    "known-alias": 0.80,
    "nested": 0.72,
}

_SOURCE_WEIGHT: Final[dict[PayloadSource, float]] = {
    PayloadSource.JSON_LD: 1.0,
    PayloadSource.MICRODATA: 0.98,
    PayloadSource.NEXT_DATA: 0.95,
    PayloadSource.RSC_FLIGHT: 0.93,
    PayloadSource.NUXT: 0.93,
    PayloadSource.INITIAL_STATE: 0.90,
    PayloadSource.OPEN_GRAPH: 0.85,
}
"""OpenGraph is scored lowest because it is written for social previews, not accuracy --
its title is frequently a marketing variant of the real one."""


def normalize_key(key: str) -> str:
    """Fold case and separators so `price_amount`, `priceAmount` and `Price Amount` unify."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key)
    return _NON_ALNUM.sub("", spaced.lower())


@dataclass(frozen=True, slots=True)
class _Match:
    value: Any
    how: str
    depth: int


def _candidate_names(field: str, subschema: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (declared aliases, known aliases) for a schema field."""
    declared = [str(a) for a in subschema.get(ALIAS_EXTENSION, []) if isinstance(a, str)]
    known = list(SCHEMA_ORG_ALIASES.get(normalize_key(field), ()))
    return declared, known


def _lookup(
    data: Any,
    field: str,
    declared: list[str],
    known: list[str],
    *,
    depth: int = 0,
) -> _Match | None:
    """Find the value for `field` inside `data`, preferring the most certain match."""
    if not isinstance(data, dict) or depth > _MAX_DESCENT:
        return None

    if field in data and data[field] is not None:
        return _Match(data[field], "exact", depth)

    for alias in declared:
        if alias in data and data[alias] is not None:
            return _Match(data[alias], "declared-alias", depth)

    normalized = {normalize_key(k): k for k in data}

    target = normalize_key(field)
    if target in normalized and data[normalized[target]] is not None:
        return _Match(data[normalized[target]], "normalized", depth)

    for alias in declared + known:
        key = normalize_key(alias)
        if key in normalized and data[normalized[key]] is not None:
            return _Match(data[normalized[key]], "known-alias", depth)

    # Bounded descent. Breadth-first so that a shallower match always beats a deeper one.
    for value in data.values():
        if isinstance(value, dict):
            found = _lookup(value, field, declared, known, depth=depth + 1)
            if found is not None:
                return _Match(found.value, "nested" if found.how == "exact" else found.how, found.depth)
    return None


def _coerce(value: Any, expected: str | list[str] | None) -> Any | None:
    """Convert a payload value to the schema's type, or None when it cannot be trusted.

    Returning None rather than a best guess is deliberate: `"contact us"` coerced to a price
    of 0 is far worse than no price at all.
    """
    if expected is None:
        return value
    types = expected if isinstance(expected, list) else [expected]

    for expected_type in types:
        if expected_type == "string":
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, int | float | bool):
                return str(value)
        elif expected_type in {"number", "integer"}:
            if isinstance(value, bool):
                continue
            if isinstance(value, int | float):
                return int(value) if expected_type == "integer" else float(value)
            if isinstance(value, str):
                cleaned = re.sub(r"[^\d.\-]", "", value.strip())
                if cleaned and cleaned not in {"-", ".", "-."}:
                    try:
                        number = float(cleaned)
                    except ValueError:
                        continue
                    return int(number) if expected_type == "integer" else number
        elif expected_type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
                return value.strip().lower() == "true"
        elif expected_type == "array":
            return value if isinstance(value, list) else [value]
        elif expected_type == "object":
            if isinstance(value, dict):
                return value
        elif expected_type == "null":
            if value is None:
                return None
    return None


def _walk(
    subschema: dict[str, Any],
    data: Any,
    path: str,
    payload: StructuredPayload,
    url: str,
    out: list[Fact],
) -> None:
    """Recursively bind schema nodes to payload values."""
    schema_type = subschema.get("type")

    if schema_type == "object" or "properties" in subschema:
        properties = subschema.get("properties", {})
        if not isinstance(data, dict):
            return
        for field, child in properties.items():
            if not isinstance(child, dict):
                continue
            declared, known = _candidate_names(field, child)
            match = _lookup(data, field, declared, known)
            if match is None:
                continue
            child_path = f"{path}.{field}" if path else field
            _emit(child, match, child_path, payload, url, out)
        return

    if schema_type == "array":
        items = subschema.get("items")
        if not isinstance(items, dict) or not isinstance(data, list):
            return
        for index, element in enumerate(data):
            _walk(items, element, f"{path}.{index}", payload, url, out)


def _emit(
    subschema: dict[str, Any],
    match: _Match,
    path: str,
    payload: StructuredPayload,
    url: str,
    out: list[Fact],
) -> None:
    schema_type = subschema.get("type")

    if schema_type == "object" or "properties" in subschema:
        _walk(subschema, match.value, path, payload, url, out)
        return

    if schema_type == "array":
        items = subschema.get("items")
        value = match.value if isinstance(match.value, list) else [match.value]
        if isinstance(items, dict) and (items.get("type") == "object" or "properties" in items):
            for index, element in enumerate(value):
                _walk(items, element, f"{path}.{index}", payload, url, out)
            return
        for index, element in enumerate(value):
            coerced = _coerce(element, items.get("type") if isinstance(items, dict) else None)
            if coerced is not None:
                out.append(_fact(f"{path}.{index}", coerced, match, payload, url))
        return

    coerced = _coerce(match.value, schema_type)
    if coerced is not None:
        out.append(_fact(path, coerced, match, payload, url))


def _fact(
    path: str, value: Any, match: _Match, payload: StructuredPayload, url: str
) -> Fact:
    base = _CONFIDENCE.get(match.how, 0.7)
    weight = _SOURCE_WEIGHT.get(payload.source, 0.85)
    # Each level of descent is a weaker claim that this key means what we think it means.
    decay = 0.97**match.depth
    return Fact(
        path=path,
        value=value,
        provenance=Provenance(
            source_url=url,
            extractor=Extractor.STRUCTURED_DATA,
            modality=Modality.DOM_JSON,
            confidence=round(min(base * weight * decay, 1.0), 4),
            source_xpath=payload.xpath,
            note=f"{payload.source.value}:{match.how}",
        ),
    )


def extract_facts(
    payloads: tuple[StructuredPayload, ...] | list[StructuredPayload],
    schema: dict[str, Any],
    url: str,
) -> list[Fact]:
    """Extract every fact the payloads can supply for `schema`.

    Returns all candidates including duplicates from different sources; call `merge_facts`
    to resolve them into one value per path.
    """
    facts: list[Fact] = []
    for payload in payloads:
        _walk(schema, payload.data, "", payload, url, facts)
    return facts


def merge_facts(facts: list[Fact]) -> dict[str, Fact]:
    """Resolve competing facts to one per path, using the precedence rules in `Fact.outranks`."""
    best: dict[str, Fact] = {}
    for fact in facts:
        current = best.get(fact.path)
        if current is None or fact.outranks(current):
            best[fact.path] = fact
    return best
