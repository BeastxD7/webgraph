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
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from webgraph.fetch.render import (
    PLAYWRIGHT_AVAILABLE,
    RenderConfig,
    RenderResult,
    geometry_by_xpath,
    render_page,
)
from webgraph.fetch.static import FetchConfig, fetch_static
from webgraph.pipeline import build_document
from webgraph.profile.technology import RuntimeEvidence
from webgraph.types import Block, Document, ReadingOrderMethod

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

    runtime: RuntimeEvidence = field(default_factory=RuntimeEvidence)
    """What the browser observed, kept so a caller can add to it.

    Site analysis augments this with the page's bundle source, which is too expensive to
    fetch per page but worth fetching once per site."""

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

    The rendered document leads, because its reading order is measured rather than assumed.
    The question is what to do with blocks that exist only in the static one -- they carry no
    geometry, since the browser never laid them out.

    An earlier version appended them all at the end, reasoning that guessing a position would
    corrupt the ordering the render was performed to get right. That is true of guessing, and
    the ordering it produced was still wrong: on `lemonde.fr` the static document contributes
    over two thousand blocks that the rendered one lacks, and every one of them landed after
    the article instead of inside it.

    They are now placed by **observed adjacency**, not by guesswork. A static-only block is
    inserted after the nearest preceding block that appears in *both* documents. That is the
    same principle as anchoring unmeasured blocks within one document, and it is sound across
    two different DOM trees because the anchor is a block both trees actually contain.

    The merged document is relabelled to match. Copying the rendered document's
    `reading_order_method` claimed geometry for a merge that was partly source order --
    `lemonde.fr` reported `geometric-anchored` with 7% of its blocks measured.

    Returns (merged document, blocks only in static, blocks only in rendered).
    """
    static_keys = {_key(b) for b in static_doc.blocks if b.text.strip()}
    rendered_keys = {_key(b) for b in rendered_doc.blocks if b.text.strip()}

    only_static = static_keys - rendered_keys
    only_rendered = rendered_keys - static_keys

    # Static-only blocks, grouped by the shared block they follow. `None` means they precede
    # every shared block and belong at the front.
    following: dict[str | None, list[Block]] = {}
    anchor: str | None = None
    emitted: set[str] = set()
    for block in static_doc.blocks:
        key = _key(block)
        if not key:
            continue
        if key in rendered_keys:
            anchor = key
            continue
        if key in emitted:
            continue
        emitted.add(key)
        following.setdefault(anchor, []).append(block)

    next_index = max((b.dom_index for b in rendered_doc.blocks), default=-1) + 1

    def adopt(block: Block) -> Block:
        nonlocal next_index
        adopted = block.model_copy(update={"dom_index": next_index, "rect": None})
        next_index += 1
        return adopted

    # Blocks before the first shared one lead, but only when something *is* shared. With no
    # common block there is no observed adjacency anywhere, and the front is as arbitrary a
    # choice as the end -- so they go to the end, which at least keeps the rendered page,
    # the authoritative one, at the top.
    anchored_to_front = bool(rendered_keys & static_keys)
    leading = following.pop(None, []) if anchored_to_front else []

    merged: list[Block] = [adopt(b) for b in leading]
    for block in rendered_doc.blocks:
        merged.append(block)
        merged.extend(adopt(extra) for extra in following.get(_key(block), ()))
    if not anchored_to_front:
        merged.extend(adopt(b) for b in following.get(None, ()))

    # Structured payloads are unioned too: a hydration payload can be present in one
    # representation and absent from the other.
    payloads = list(rendered_doc.structured_data)
    known = {repr(p.data) for p in payloads}
    for payload in static_doc.structured_data:
        if repr(payload.data) not in known:
            payloads.append(payload)
            known.add(repr(payload.data))

    method = rendered_doc.reading_order_method
    if only_static and method is not ReadingOrderMethod.DOM_FALLBACK:
        # Part of this document was positioned by adjacency rather than measured. That is a
        # weaker claim than the rendered document alone could make, and it gets the weaker name.
        method = ReadingOrderMethod.GEOMETRIC_ANCHORED

    document = rendered_doc.model_copy(
        update={
            "blocks": tuple(merged),
            "structured_data": tuple(payloads),
            "reading_order_method": method,
        }
    )
    return document, len(only_static), len(only_rendered)


def runtime_evidence(rendered: RenderResult) -> RuntimeEvidence:
    """Repackage what the browser observed into the shape the fingerprinter consumes."""
    return RuntimeEvidence(
        versions=dict(rendered.globals),
        custom_globals=rendered.custom_globals,
        requests=rendered.requests,
        cookies=dict(rendered.cookies),
    )


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
    observed = runtime_evidence(rendered)
    rendered_doc = build_document(
        rendered.html,
        rendered.url or url,
        geometry=geometry,
        headers=static_result.headers,
        runtime=observed,
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
            runtime=observed,
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
        runtime=observed,
    )
