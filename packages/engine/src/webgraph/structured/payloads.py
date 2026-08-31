"""Lift machine-readable data the page already published.

This is the cheapest extraction path in the engine and the first one tried: no model call,
no selector induction, no inference. When a page ships JSON-LD or a hydration payload, the
data is *already* structured and exact -- reading it is strictly better than asking a model
to re-derive it from rendered text.

Sources, in rough order of how directly they describe page content:

- **JSON-LD** (`<script type="application/ld+json">`) -- the richest and most standardised.
- **Microdata / OpenGraph** -- shallow but near-universal.
- **`__NEXT_DATA__`** -- Next.js Pages Router, a single clean JSON blob.
- **RSC flight data** -- Next.js App Router, chunked into `self.__next_f.push(...)` calls
  in a React-specific wire format that plain JSON parsing cannot read.
- **Nuxt / generic initial state** -- `window.__NUXT__`, `window.__INITIAL_STATE__`.

Known limit: hydration payloads describe only the *first* page of paginated content.
Later pages arrive over XHR, so a complete extractor must pair this with request interception.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from lxml.html import HtmlElement

from webgraph.types import PayloadSource, StructuredPayload

__all__ = [
    "extract_initial_state",
    "extract_json_ld",
    "extract_microdata",
    "extract_next_data",
    "extract_open_graph",
    "extract_payloads",
    "extract_rsc_flight",
    "find_balanced_json",
]

_TRAILING_COMMA: Final[re.Pattern[str]] = re.compile(r",\s*([}\]])")
_FLIGHT_PUSH: Final[re.Pattern[str]] = re.compile(
    r"self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*", re.DOTALL
)
_FLIGHT_LINE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]+:(.*)$")
_STATE_ASSIGN: Final[re.Pattern[str]] = re.compile(
    r"window\.(__NUXT__|__INITIAL_STATE__|__APOLLO_STATE__|__PRELOADED_STATE__)\s*=\s*"
)

_MAX_PAYLOAD_BYTES: Final[int] = 8 * 1024 * 1024
"""Refuse absurd payloads rather than letting a malicious page exhaust memory."""


def find_balanced_json(text: str, start: int) -> str | None:
    """Return the complete JSON value beginning at `text[start]`, or None.

    Needed because hydration payloads are embedded in JavaScript, not delimited by anything
    we can regex for. A naive `{.*}` match spans into unrelated code, and a non-greedy one
    stops at the first `}` inside a nested object. This walks the value tracking nesting
    depth while respecting string literals and escapes, which is the only reliable way.
    """
    if start >= len(text) or text[start] not in "{[":
        return None

    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for index in range(start, min(len(text), start + _MAX_PAYLOAD_BYTES)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return None


def _loads(raw: str) -> Any | None:
    """Parse JSON, retrying once with trailing commas stripped.

    Hand-authored JSON-LD blocks routinely carry trailing commas. Recovering them is worth
    the one extra attempt; anything more aggressive risks silently reinterpreting the data.
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(_TRAILING_COMMA.sub(r"\1", raw))
    except json.JSONDecodeError:
        return None


def _flatten_json_ld(data: Any) -> list[Any]:
    """Unwrap the two containers JSON-LD uses for multiple entities: arrays and `@graph`."""
    if isinstance(data, list):
        out: list[Any] = []
        for item in data:
            out.extend(_flatten_json_ld(item))
        return out
    if isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            nested = [n for item in graph for n in _flatten_json_ld(item)]
            rest = {k: v for k, v in data.items() if k != "@graph"}
            return ([rest] if len(rest) > 1 else []) + nested
        return [data]
    return []


def extract_json_ld(root: HtmlElement) -> list[StructuredPayload]:
    """Read every `application/ld+json` block."""
    payloads: list[StructuredPayload] = []
    tree = root.getroottree()

    for script in root.xpath(
        "//script[translate(@type,'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
        "'abcdefghijklmnopqrstuvwxyz')='application/ld+json']"
    ):
        parsed = _loads(script.text_content())
        if parsed is None:
            continue
        for entity in _flatten_json_ld(parsed):
            if entity:
                payloads.append(
                    StructuredPayload(
                        source=PayloadSource.JSON_LD,
                        data=entity,
                        xpath=tree.getpath(script),
                    )
                )
    return payloads


def extract_next_data(root: HtmlElement) -> list[StructuredPayload]:
    """Read the Next.js Pages Router payload: `<script id="__NEXT_DATA__">`.

    Parseable straight from raw HTML with no JavaScript execution, which makes it the
    single highest-value fast path on Next.js sites.
    """
    payloads: list[StructuredPayload] = []
    tree = root.getroottree()

    for script in root.xpath("//script[@id='__NEXT_DATA__']"):
        parsed = _loads(script.text_content())
        if parsed is not None:
            payloads.append(
                StructuredPayload(
                    source=PayloadSource.NEXT_DATA,
                    data=parsed,
                    xpath=tree.getpath(script),
                )
            )
    return payloads


def extract_rsc_flight(html: str) -> list[StructuredPayload]:
    """Reassemble React Server Components flight data.

    App Router pages stream their data as `self.__next_f.push([1, "<chunk>"])` calls. Each
    chunk is a *JavaScript string literal* holding a fragment of a line-oriented wire
    format; the fragments must be JSON-decoded and concatenated before anything is
    parseable. Lines then look like `1:{"a":1}` or `2:I[...]`.

    Only the JSON-valued lines are returned. The rest of the format encodes React element
    trees and module references, which carry no page data worth extracting.
    """
    chunks: list[str] = []
    for match in _FLIGHT_PUSH.finditer(html):
        start = match.end()
        if start >= len(html) or html[start] != '"':
            continue
        literal = _read_js_string(html, start)
        if literal is not None:
            chunks.append(literal)

    if not chunks:
        return []

    stream = "".join(chunks)
    payloads: list[StructuredPayload] = []

    for line in stream.split("\n"):
        line_match = _FLIGHT_LINE.match(line.strip())
        if not line_match:
            continue
        body = line_match.group(1).lstrip()
        if not body or body[0] not in "{[":
            continue
        candidate = find_balanced_json(body, 0)
        if candidate is None:
            continue
        parsed = _loads(candidate)
        if parsed:
            payloads.append(
                StructuredPayload(
                    source=PayloadSource.RSC_FLIGHT,
                    data=parsed,
                    note="reassembled from __next_f chunks",
                )
            )
    return payloads


def _read_js_string(text: str, start: int) -> str | None:
    """Decode the double-quoted JS string literal starting at `text[start]`."""
    if start >= len(text) or text[start] != '"':
        return None
    escaped = False
    for index in range(start + 1, min(len(text), start + _MAX_PAYLOAD_BYTES)):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            literal = text[start : index + 1]
            decoded = _loads(literal)
            return decoded if isinstance(decoded, str) else None
    return None


def extract_initial_state(html: str) -> list[StructuredPayload]:
    """Read `window.__NUXT__`, `__INITIAL_STATE__`, `__APOLLO_STATE__`, `__PRELOADED_STATE__`.

    Only object/array literals are recovered. Nuxt 3 sometimes assigns the result of a
    function call (devalue format) instead, which cannot be read without executing it --
    those are skipped rather than guessed at.
    """
    payloads: list[StructuredPayload] = []

    for match in _STATE_ASSIGN.finditer(html):
        name = match.group(1)
        start = match.end()
        while start < len(html) and html[start] in " \t\r\n":
            start += 1
        candidate = find_balanced_json(html, start)
        if candidate is None:
            continue
        parsed = _loads(candidate)
        if parsed is None:
            continue
        source = PayloadSource.NUXT if name == "__NUXT__" else PayloadSource.INITIAL_STATE
        payloads.append(
            StructuredPayload(source=source, data=parsed, note=f"window.{name}")
        )
    return payloads


def extract_open_graph(root: HtmlElement) -> list[StructuredPayload]:
    """Collect OpenGraph and Twitter card meta tags into one payload."""
    data: dict[str, str] = {}
    for meta in root.xpath("//meta[@property or @name]"):
        key = meta.get("property") or meta.get("name") or ""
        key = key.strip().lower()
        if not (key.startswith(("og:", "twitter:", "article:", "product:"))):
            continue
        content = (meta.get("content") or "").strip()
        if content:
            data[key] = content

    if not data:
        return []
    return [StructuredPayload(source=PayloadSource.OPEN_GRAPH, data=data)]


def extract_microdata(root: HtmlElement) -> list[StructuredPayload]:
    """Read schema.org microdata (`itemscope` / `itemtype` / `itemprop`).

    Only top-level scopes are emitted; nested scopes are recursed into and attached to
    their parent, which preserves the structure the markup intended.
    """
    tree = root.getroottree()
    payloads: list[StructuredPayload] = []

    for scope in root.xpath("//*[@itemscope]"):
        parent_scope = scope.getparent()
        nested = False
        while parent_scope is not None:
            if parent_scope.get("itemscope") is not None:
                nested = True
                break
            parent_scope = parent_scope.getparent()
        if nested:
            continue

        item = _read_microdata_scope(scope)
        if item:
            payloads.append(
                StructuredPayload(
                    source=PayloadSource.MICRODATA,
                    data=item,
                    xpath=tree.getpath(scope),
                )
            )
    return payloads


def _read_microdata_scope(scope: HtmlElement) -> dict[str, Any]:
    item: dict[str, Any] = {}
    item_type = scope.get("itemtype")
    if item_type:
        item["@type"] = item_type.strip()

    for prop in scope.iterdescendants():
        name = prop.get("itemprop")
        if not name:
            continue
        # Skip properties belonging to a nested scope; they are read by the recursion below.
        owner = prop.getparent()
        outside = False
        while owner is not None and owner is not scope:
            if owner.get("itemscope") is not None:
                outside = True
                break
            owner = owner.getparent()
        if outside:
            continue

        value: Any
        if prop.get("itemscope") is not None:
            value = _read_microdata_scope(prop)
        else:
            value = _microdata_value(prop)
        if value in (None, "", {}):
            continue

        if name in item:
            existing = item[name]
            item[name] = [*existing, value] if isinstance(existing, list) else [existing, value]
        else:
            item[name] = value

    return item


def _microdata_value(element: HtmlElement) -> str:
    """Microdata reads the machine-readable attribute when present, else the text."""
    for attribute in ("content", "datetime", "href", "src", "value"):
        raw: str | None = element.get(attribute)
        if raw and raw.strip():
            return str(raw).strip()
    text: str = element.text_content()
    return " ".join(text.split())


def extract_payloads(root: HtmlElement, html: str) -> tuple[StructuredPayload, ...]:
    """Run every structured-data extractor. Order matches trustworthiness, not cost."""
    payloads: list[StructuredPayload] = []
    payloads.extend(extract_json_ld(root))
    payloads.extend(extract_microdata(root))
    payloads.extend(extract_open_graph(root))
    payloads.extend(extract_next_data(root))
    payloads.extend(extract_rsc_flight(html))
    payloads.extend(extract_initial_state(html))
    return tuple(payloads)
