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

import html
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
    # No `lowprice`: on an `AggregateOffer` that is the cheapest variant, and reporting the
    # cheapest variant as the price is how a £400 laptop gets advertised at £89. No
    # `offers.price` either -- it normalises to `offersprice`, which no payload is ever
    # spelled as, so it has never matched anything. Nested offers are reached by declaring
    # `offers` as an object in the schema.
    "price": ("priceamount", "amount"),
    "currency": ("pricecurrency", "currencycode"),
    "image": ("thumbnail", "imageurl", "og:image"),
    "url": ("permalink", "canonical", "og:url"),
    "brand": ("manufacturer", "vendor"),
    # No `mpn`: a manufacturer part number identifies the part, a SKU identifies the
    # merchant's stock line. Two shops selling the same part share an mpn and have
    # different SKUs, so merging them makes inventory look like one item.
    "sku": ("productid", "identifier"),
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
        # Lists are entered as well as objects, at the same depth. A publisher who wrapped
        # one offer in an array -- which WooCommerce does on every product -- had not
        # changed what the page means, and reading only dicts answered "no price" for a
        # large share of the web's shops for no reason to do with the page.
        for candidate in _objects(value):
            found = _lookup(candidate, field, declared, known, depth=depth + 1)
            if found is not None:
                return _Match(
                    found.value, "nested" if found.how == "exact" else found.how, found.depth
                )
    return None


def _objects(value: Any) -> list[dict[str, Any]]:
    """The dictionaries inside a value: itself, or the ones a list holds, in order."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


_ISO_DATE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}"  # a date, and then optionally a time
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
"""ISO-8601, and nothing that merely resembles it.

7% of `datePublished` values in a 2,008-page census are not ISO, and they include
`"13/11/2025 09:21:40"` -- day-month or month-day, and for any day below 13 nothing in the
string says which. Guessing is wrong eleven months of the year."""

_GROUPED: Final[re.Pattern[str]] = re.compile(r"^\d{1,3}(?:([ .,\u00a0])\d{3})+$")
"""A number written with thousands separators and no decimal part: `1,299`, `1.299`."""


def _to_number(raw: str) -> float | None:
    """Read a price the way the page's own locale wrote it, or decline.

    The old rule -- strip everything but digits, dots and minus -- turns the European
    `"19,99"` into `1999.0`: a hundred times the real price, emitted with full confidence.
    That is the worst shape a bug here can take, because nothing downstream can tell it from
    a correct answer. Comma-decimal is 34% of string-valued prices in the census, and the
    reason is the two largest e-commerce platforms: WooCommerce formats through PHP's
    `number_format` with the store's own separator, and Shopify quotes the price as a string.

    The rule is positional: whichever of `.` or `,` appears **last** is the decimal point,
    provided one or two digits follow it. A separator followed by exactly three digits is a
    thousands group in both conventions -- `"1.299"` and `"1,299"` both read as 1299, since
    a price of one-and-a-bit written to three decimals is far rarer than a price of 1,299.

    Anything that parses under neither convention yields nothing: `"1.2.3"`, `"12,34,56"`,
    `"1,2345"`. A missing price is recoverable downstream; a wrong one is not.
    """
    text = raw.strip().replace("\u00a0", " ")
    # Currency symbols, spaces and stray letters around the number. schema.org asks
    # publishers not to include them and publishers include them anyway.
    text = re.sub(r"[^\d.,\- ]", "", text).strip()
    if not text or not any(ch.isdigit() for ch in text):
        return None

    negative = text.startswith("-")
    text = text.lstrip("-")

    if _GROUPED.fullmatch(text):
        # Every separator delimits a group of exactly three: no decimal part at all.
        digits = re.sub(r"[ .,]", "", text)
        return -float(digits) if negative else float(digits)

    last = max(text.rfind("."), text.rfind(","))
    if last < 0:
        try:
            value = float(text.replace(" ", ""))
        except ValueError:
            return None
        return -value if negative else value

    whole, fraction = text[:last], text[last + 1 :]
    # One to two digits after the final separator is a fraction; three is a thousands group
    # and was handled above; anything else is not a number we can read.
    if not fraction.isdigit() or not 1 <= len(fraction) <= 2:
        return None
    # Whatever precedes the decimal point must itself be a well-formed integer -- plain
    # digits, or digits in groups of three. Without this check `"1.2.3"` reads as 12.3 and
    # `"12,34,56"` as 1234.56, both of which are inventions.
    if not (whole.isdigit() or _GROUPED.fullmatch(whole)):
        return None
    whole_digits = re.sub(r"[ .,]", "", whole)
    value = float(f"{whole_digits}.{fraction}")
    return -value if negative else value


def _enum_value(value: Any, allowed: list[Any]) -> Any | None:
    """Match a schema.org enum by its final path segment.

    The same state arrives as `https://schema.org/InStock`, `http://schema.org/InStock` and
    bare `InStock`, and the `http://` half is not legacy drift -- Shopify's current default
    themes emit it. Anything outside the set, including the one page in the census that says
    `OutStock`, yields nothing: a typo is not a state.
    """
    if value in allowed:
        return value
    if not isinstance(value, str):
        return None
    tail = value.rstrip("/").rsplit("/", 1)[-1]
    for candidate in allowed:
        if isinstance(candidate, str) and tail == candidate:
            return candidate
    return None


def _coerce(
    value: Any, expected: str | list[str] | None, subschema: dict[str, Any] | None = None
) -> Any | None:
    """Convert a payload value to the schema's type, or None when it cannot be trusted.

    Returning None rather than a best guess is deliberate: `"contact us"` coerced to a price
    of 0 is far worse than no price at all.

    Two standard JSON Schema keywords narrow what is accepted, when the schema declares
    them: `enum` (matched by final path segment, for schema.org's URL-shaped states) and
    `format: "date-time"` (ISO-8601 or nothing). Standard keywords rather than an extension
    of our own, so a caller writing a schema by hand needs to learn nothing new.
    """
    if subschema is not None:
        allowed = subschema.get("enum")
        if isinstance(allowed, list):
            return _enum_value(value, allowed)

    if expected is None:
        return value
    types = expected if isinstance(expected, list) else [expected]
    wants_date = subschema is not None and subschema.get("format") == "date-time"

    for expected_type in types:
        if expected_type == "string":
            text: str | None = None
            if isinstance(value, str):
                # JSON-LD is JSON, so entities in it were never meant to survive; they do,
                # on roughly one page in six carrying it, because the emitter built the
                # string out of already-escaped HTML.
                text = html.unescape(value).strip()
            elif isinstance(value, int | float | bool):
                text = str(value)
            if text is None:
                continue
            if wants_date:
                # Some emitters quote the value a second time, inside the string.
                stripped = text.strip('"')
                return stripped if _ISO_DATE.match(stripped) else None
            return text
        elif expected_type in {"number", "integer"}:
            if isinstance(value, bool):
                continue
            if isinstance(value, int | float):
                return int(value) if expected_type == "integer" else float(value)
            if isinstance(value, str):
                number = _to_number(value)
                if number is not None:
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
        # A list where an object was asked for: take its first object. The page shipped one
        # thing in a container, not several things.
        value = match.value
        if isinstance(value, list):
            first = _objects(value)
            if not first:
                return
            value = first[0]
        _walk(subschema, value, path, payload, url, out)
        return

    if schema_type == "array":
        items = subschema.get("items")
        value = match.value if isinstance(match.value, list) else [match.value]
        if isinstance(items, dict) and (items.get("type") == "object" or "properties" in items):
            for index, element in enumerate(value):
                _walk(items, element, f"{path}.{index}", payload, url, out)
            return
        for index, element in enumerate(value):
            coerced = _coerce(
                element,
                items.get("type") if isinstance(items, dict) else None,
                items if isinstance(items, dict) else None,
            )
            if coerced is not None:
                out.append(_fact(f"{path}.{index}", coerced, match, payload, url))
        return

    coerced = _coerce(match.value, schema_type, subschema)
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
