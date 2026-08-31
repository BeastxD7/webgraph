"""Complete-content page resolution: fetch both ways, keep everything.

Why this module exists
----------------------
Measured against 24 real sites, two things turned out to be true at once:

1. **You cannot predict partial content loss.** Heuristics catch the catastrophic cases --
   a page with zero text is obviously a shell -- but they cannot catch `angular.dev` at 68%
   or `notion.com` at 82%. A page holding 2,078 characters carries no signal that another
   969 appear after hydration. There is nothing left to tune.

2. **Rendering is not a strict upgrade.** `bbc.co.uk/news` yields 19,908 characters
   statically and 9,279 rendered, because a consent wall replaces the article. Choosing the
   rendered document would have thrown away half the page.

Together those rule out picking a side. If the requirement is to lose nothing, the only
sound strategy is to obtain both representations and **union** them, then report how much
each contributed so the completeness claim is a measurement rather than an assertion.

Cost note
---------
`UNION` costs one extra fetch plus a browser render. That is the price of completeness and
it is charged deliberately. `STATIC_ONLY` remains available for bulk crawling where the
budget matters more than the last few percent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from webgraph.fetch.render import PLAYWRIGHT_AVAILABLE, RenderConfig, geometry_by_xpath, render_page
from webgraph.fetch.static import FetchConfig, fetch_static
from webgraph.pipeline import build_document
from webgraph.types import Block, Document

__all__ = [
    "MISSING_STATUSES",
    "PageMissingError",
    "ResolvedPage",
    "Strategy",
    "resolve_page",
    "union_documents",
]

MISSING_STATUSES: Final[frozenset[int]] = frozenset({404, 410})
"""Statuses meaning the page does not exist. Never render these.

A browser renders a server's 404 page perfectly happily, producing "Not Found -- The
requested URL was not found on this server" as though it were content. Measured on
ionidea.com, whose relative links resolve into hundreds of URLs that do not exist: without
this gate every one of them yielded a document.

Deliberately excludes 403/429/5xx. Those usually mean *blocked* or *transient*, not
*absent* -- and rendering frequently succeeds where a static fetch was refused."""


class PageMissingError(Exception):
    """Raised when a URL does not exist. Distinct from a transport failure."""

    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"HTTP {status}: page does not exist")
        self.url = url
        self.status = status

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")


class Strategy(StrEnum):
    STATIC_ONLY = "static-only"
    """Cheap path. Used when rendering is unavailable or explicitly disabled."""

    RENDERED_ONLY = "rendered-only"
    """Static fetch failed or returned nothing usable."""

    UNION = "union"
    """Both representations obtained and merged. The completeness path."""


@dataclass(frozen=True, slots=True)
class ResolvedPage:
    """A page resolved as completely as the configured strategy allows."""

    url: str
    document: Document
    strategy: Strategy

    static_chars: int
    rendered_chars: int
    union_chars: int

    blocks_only_in_static: int
    blocks_only_in_rendered: int
    render_error: str | None = None

    @property
    def static_coverage(self) -> float:
        """Share of the final content the static fetch alone would have given you.

        Clamped to 1.0. The raw ratio can exceed it because the union deduplicates repeated
        blocks: a page that renders the same navigation three times contributes those
        characters three times to `static_chars` but once to the union. The clamp keeps the
        number readable as "how much would I have had", which is the question it answers.
        """
        return min(self.static_chars / self.union_chars, 1.0) if self.union_chars else 0.0

    @property
    def rendered_coverage(self) -> float:
        """Share of the final content a render alone would have given you. Clamped to 1.0."""
        return min(self.rendered_chars / self.union_chars, 1.0) if self.union_chars else 0.0

    @property
    def render_added_content(self) -> bool:
        return self.blocks_only_in_rendered > 0

    @property
    def render_lost_content(self) -> bool:
        """True when the rendered page dropped content the static HTML had.

        Consent walls, paywalls and lazy-unmounted sections all cause this. It is the reason
        the rendered document cannot simply replace the static one.
        """
        return self.blocks_only_in_static > 0

    def summary(self) -> str:
        return (
            f"{self.strategy.value}: {self.union_chars} chars "
            f"(static {self.static_coverage:.0%}, rendered {self.rendered_coverage:.0%}, "
            f"+{self.blocks_only_in_rendered} render-only blocks, "
            f"+{self.blocks_only_in_static} static-only blocks)"
        )


def _key(block: Block) -> str:
    """Identity for deduplication: normalised text.

    Text rather than XPath, because the two representations of a page rarely agree on
    structure -- hydration rewrites the tree -- but the words themselves are stable.
    """
    return _WHITESPACE.sub(" ", block.text).strip().casefold()


def union_documents(static_doc: Document, rendered_doc: Document) -> tuple[Document, int, int]:
    """Merge two representations of one page, losing nothing.

    The rendered document leads because its reading order is measured rather than assumed.
    Blocks that exist only in the static document are appended afterwards, in their own
    order. They are appended rather than interleaved because there is no geometry for them --
    guessing a position would corrupt the very ordering the render was performed to get right.

    Returns (merged document, blocks only in static, blocks only in rendered).
    """
    static_keys = {_key(b) for b in static_doc.blocks if b.text.strip()}
    rendered_keys = {_key(b) for b in rendered_doc.blocks if b.text.strip()}

    only_static = static_keys - rendered_keys
    only_rendered = rendered_keys - static_keys

    merged: list[Block] = list(rendered_doc.blocks)
    seen = set(rendered_keys)

    next_index = max((b.dom_index for b in rendered_doc.blocks), default=-1) + 1
    for block in static_doc.blocks:
        key = _key(block)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(block.model_copy(update={"dom_index": next_index, "rect": None}))
        next_index += 1

    # Structured payloads are unioned too: a hydration payload can be present in one
    # representation and absent from the other.
    payloads = list(rendered_doc.structured_data)
    known = {repr(p.data) for p in payloads}
    for payload in static_doc.structured_data:
        if repr(payload.data) not in known:
            payloads.append(payload)
            known.add(repr(payload.data))

    document = rendered_doc.model_copy(
        update={
            "blocks": tuple(merged),
            "structured_data": tuple(payloads),
        }
    )
    return document, len(only_static), len(only_rendered)


def resolve_page(
    url: str,
    *,
    strategy: Strategy | None = None,
    fetch_config: FetchConfig | None = None,
    render_config: RenderConfig | None = None,
) -> ResolvedPage:
    """Resolve a page as completely as possible.

    With `strategy` unset the decision is made per page: render whenever the profiler is not
    confident the static HTML is complete, then union. Set `Strategy.STATIC_ONLY` for bulk
    crawls where budget matters more than the last few percent.
    """
    static_result = fetch_static(url, config=fetch_config)

    # Gate on status before anything else. A 404 page renders perfectly well, and without
    # this the engine extracts server error pages as though they were content.
    if static_result.status in MISSING_STATUSES:
        raise PageMissingError(url, static_result.status)

    static_doc: Document | None = None

    if static_result.ok and static_result.is_html and static_result.html.strip():
        try:
            static_doc = build_document(
                static_result.html, static_result.url, headers=static_result.headers
            )
        except ValueError:
            static_doc = None

    if strategy is Strategy.STATIC_ONLY:
        if static_doc is None:
            raise ValueError(f"static fetch produced no document for {url}: {static_result.error}")
        chars = len(static_doc.text)
        return ResolvedPage(
            url=static_doc.url,
            document=static_doc,
            strategy=Strategy.STATIC_ONLY,
            static_chars=chars,
            rendered_chars=0,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
        )

    should_render = (
        PLAYWRIGHT_AVAILABLE
        and (strategy is Strategy.UNION or static_doc is None or static_doc.profile.requires_render
             or strategy is None)
    )

    if not should_render:
        if static_doc is None:
            raise ValueError(f"could not resolve {url}: {static_result.error}")
        chars = len(static_doc.text)
        return ResolvedPage(
            url=static_doc.url,
            document=static_doc,
            strategy=Strategy.STATIC_ONLY,
            static_chars=chars,
            rendered_chars=0,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
            render_error="rendering not available",
        )

    rendered = render_page(url, config=render_config)

    if not rendered.ok:
        if static_doc is None:
            raise ValueError(f"could not resolve {url}: {rendered.error}")
        chars = len(static_doc.text)
        return ResolvedPage(
            url=static_doc.url,
            document=static_doc,
            strategy=Strategy.STATIC_ONLY,
            static_chars=chars,
            rendered_chars=0,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
            render_error=rendered.error,
        )

    geometry = geometry_by_xpath(rendered.html, rendered.rects)
    rendered_doc = build_document(
        rendered.html,
        rendered.url or url,
        geometry=geometry,
        headers=static_result.headers,
        runtime_globals=rendered.globals,
    )

    if static_doc is None:
        chars = len(rendered_doc.text)
        return ResolvedPage(
            url=rendered_doc.url,
            document=rendered_doc,
            strategy=Strategy.RENDERED_ONLY,
            static_chars=0,
            rendered_chars=chars,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
        )

    merged, only_static, only_rendered = union_documents(static_doc, rendered_doc)

    return ResolvedPage(
        url=merged.url,
        document=merged,
        strategy=Strategy.UNION,
        static_chars=len(static_doc.text),
        rendered_chars=len(rendered_doc.text),
        union_chars=len(merged.text),
        blocks_only_in_static=only_static,
        blocks_only_in_rendered=only_rendered,
    )
