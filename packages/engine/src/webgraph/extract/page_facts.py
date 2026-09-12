"""One call from a page to its facts: classify, pick a schema, read the right node.

`extract_facts` binds payloads to a schema and knows nothing about schema.org; `schema_for`
knows the vocabulary; `subject_tiers` knows which node is the page's. This composes the
three in the order they have to run, so that the API, the CLI and the benchmark all do the
same thing rather than three similar things.

The one piece of logic that lives here is the tiering. A page's `WebPage` node is the CMS
describing the URL it served: its `name` is the `<title>`, which is the article's title on
many sites and "Acme Blog | Acme" on many others. Letting it compete with the `Article`
node costs accuracy; ignoring it costs coverage on the 40% of article pages that ship no
`Article` node at all. Using it *only where the specific node said nothing* keeps both --
measured on 869 labelled pages, it recovers most of the coverage the gate costs without
bringing back the wrong values.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final

from webgraph.extract.pageschema import schema_for
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.extract.subject import node_types, subject_tiers
from webgraph.pagetype import PageType
from webgraph.types import Fact, PayloadSource, StructuredPayload

__all__ = ["PageFacts", "facts_for_page"]

_GENERIC_PENALTY = 0.9
"""How much less a value from a `WebPage` wrapper is worth than one from the real node.

Not a guess about correctness -- it is already only used where nothing better existed --
but a statement to whatever reads the fact later that this came from the page's envelope
rather than from a description of its subject."""


@dataclass(frozen=True, slots=True)
class PageFacts:
    """The facts, and enough about how they were chosen to argue with the result."""

    page_type: PageType
    facts: dict[str, Fact]
    schema: dict[str, Any]
    subject_types: tuple[str, ...] = ()
    payloads_considered: int = 0
    payloads_used: int = 0
    filled_from_generic: tuple[str, ...] = field(default=())
    """Paths no node about the page supplied, taken from its wrapper or its social preview.
    Each such fact's provenance note says which."""


_SEPARATORS: Final[tuple[str, ...]] = (" | ", " - ", " \u2013 ", " \u2014 ", " :: ", " \u00b7 ")
"""How a CMS joins a page's title to its site's name in `og:title`."""


def _site_name(social: list[StructuredPayload]) -> str:
    """The site's own name, as Open Graph states it."""
    for payload in social:
        if isinstance(payload.data, dict):
            name = payload.data.get("og:site_name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return ""


def _without_site_name(value: str, site: str) -> str:
    """`"What is Cloud Computing? | Google Cloud"` -> `"What is Cloud Computing?"`.

    Only when the page itself said what its site is called. Without `og:site_name` this
    would be guessing that whatever follows a pipe is a site name, and plenty of real
    headlines contain a pipe or a dash of their own. With it, the trim is something the
    page asserted rather than something we inferred.
    """
    if not site:
        return value
    for separator in _SEPARATORS:
        suffix = f"{separator}{site}"
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)].strip()
        prefix = f"{site}{separator}"
        if value.startswith(prefix) and len(value) > len(prefix):
            return value[len(prefix) :].strip()
    return value


def _fill_gaps(
    facts: dict[str, Fact],
    payloads: list[StructuredPayload],
    schema: dict[str, Any],
    url: str,
    label: str,
    filled: list[str],
    trim: str = "",
) -> None:
    """Add what `payloads` can supply, but only for paths nothing has answered yet.

    Never overwrites. The order of the tiers is the whole design: a weaker source that can
    displace a stronger one is not a fallback, it is a second opinion nobody asked for.
    """
    if not payloads:
        return
    for path, fact in merge_facts(extract_facts(payloads, schema, url)).items():
        if path in facts:
            continue
        value = fact.value
        if trim and isinstance(value, str):
            value = _without_site_name(value, trim)
        provenance = fact.provenance.model_copy(
            update={
                "confidence": round(fact.provenance.confidence * _GENERIC_PENALTY, 4),
                "note": f"{fact.provenance.note} ({label})",
            }
        )
        facts[path] = fact.model_copy(update={"value": value, "provenance": provenance})
        filled.append(path)


def facts_for_page(
    payloads: Iterable[StructuredPayload], page_type: PageType, url: str = ""
) -> PageFacts:
    """Everything the page's own structured data says, under the schema for its type.

    Returns an empty result rather than a guess for `PageType.UNKNOWN`, and for a page whose
    structured data is all about the site: on category pages that is the common case, and
    saying nothing is the difference between "this shop sells no products" and "IKEA".
    """
    considered = list(payloads)
    schema = schema_for(page_type)
    if schema is None:
        return PageFacts(
            page_type=page_type,
            facts={},
            schema={"type": "object", "properties": {}},
            payloads_considered=len(considered),
        )

    primary, generic = subject_tiers(considered, page_type, url)
    facts = merge_facts(extract_facts(primary, schema, url)) if primary else {}

    filled: list[str] = []
    _fill_gaps(facts, generic, schema, url, "page wrapper", filled)

    # Open Graph last, and only into gaps. It is written for social previews, so it is a
    # marketing variant of the truth often enough that it must never outrank a node that
    # describes the page. But measured on article pages it is right far more often than it
    # is wrong, and it is the only thing present on many pages that ship no article node at
    # all -- 95% of article pages carry `og:title`. Used this way it is coverage the gate
    # would otherwise throw away, not a competitor to the real answer.
    social = [p for p in considered if p.source is PayloadSource.OPEN_GRAPH]
    _fill_gaps(facts, social, schema, url, "social preview", filled, trim=_site_name(social))

    used = primary or (generic if filled else [])
    return PageFacts(
        page_type=page_type,
        facts=facts,
        schema=schema,
        subject_types=tuple(sorted({name for p in used for name in node_types(p.data)})),
        payloads_considered=len(considered),
        payloads_used=len(used),
        filled_from_generic=tuple(sorted(filled)),
    )
