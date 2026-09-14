"""HTTP API over the extraction engine.

Design notes that matter for a service rather than a library:

- **Rendering is opt-in and bounded.** A browser launch costs hundreds of milliseconds and
  roughly 150 MB of RSS, so it runs in a worker thread with a concurrency cap. Without the
  cap a handful of simultaneous requests will exhaust memory on a laptop.
- **Errors are HTTP status codes, not tracebacks.** A fetch failure is the remote site's
  problem, reported as 502; a bad schema is the caller's, reported as 422.
- **Provenance is part of the response, not a debug extra.** Every value carries where it
  came from and how confident the engine is, because a fact without a source cannot be
  checked by whoever consumes it.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from webgraph.content import select_content
from webgraph.extract.page_facts import facts_for_page
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.fetch import guard
from webgraph.fetch.render import PLAYWRIGHT_AVAILABLE, RenderConfig
from webgraph.fetch.static import FetchConfig
from webgraph.graph.build import GraphBuilder
from webgraph.graph.entities import derive_entities
from webgraph.graph.export import to_jsonl
from webgraph.graph.retrieve import Budget, ContextAssembler
from webgraph.graph.store import GraphStore
from webgraph.page import stream_page
from webgraph.pagetype import PageType, default_router, policy_for
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.resolve import (
    PageBlockedError,
    PageMissingError,
    PageShellError,
    ResolvedPage,
    Strategy,
    resolve_page,
    resolve_supplied,
)
from webgraph.settings import Settings, describe_config
from webgraph.site import SiteConfig, stream_site
from webgraph.trace import RunTrace, trace_events
from webgraph.types import BlockKind, Document, ReadingOrderMethod

# Every value a deployment can set lives in `webgraph.settings.Settings` (defaults in `webgraph.config`), read once here. The
# reasoning for each cap is beside its field there; these names are kept because the rest of
# this module -- and the tests that monkeypatch them -- refer to them.
SETTINGS = Settings.from_env()



def _origins_from_env(settings: Settings | None = None) -> list[str]:
    """Browser origins allowed to call this API: `WEBGRAPH_ALLOWED_ORIGINS`, or the dev
    frontend when nothing is configured. Never `*`: this service fetches arbitrary URLs on
    the caller's behalf, so an open CORS policy would hand every page on the internet a
    proxy that runs inside our network."""
    configured = (settings or Settings.from_env()).allowed_origins
    return list(configured) or ["http://localhost:3000", "http://127.0.0.1:3000"]


ALLOWED_ORIGINS: list[str] = _origins_from_env(SETTINGS)
PAGE_CAP = SETTINGS.max_pages
CONCURRENCY_CAP = SETTINGS.max_concurrency
MAX_CONCURRENT_RENDERS = SETTINGS.max_concurrent_renders
MAX_CONCURRENT_CRAWLS = SETTINGS.max_concurrent_crawls

CRAWL_QUEUE_HIGH_WATER = 64
"""Events buffered before the producer throttles.

A `page` event carries the whole document. A client that cannot keep up must not be able
to turn the buffer into an unbounded memory leak.
"""

MAX_CACHED_GRAPHS = 4
"""Site graphs kept in memory, evicted oldest-first.

A graph is the by-product of a crawl and is what makes the context endpoint answerable
without re-crawling. Four is a compromise: a 2,000-page site is roughly 20,000 sections and
tens of megabytes, and this is a single-process service on someone's laptop. Graphs evicted
from here are not lost: they are written to disk and read back on demand.
"""

_render_slots = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)

_graphs: OrderedDict[str, GraphBuilder] = OrderedDict()
_graphs_lock = threading.Lock()

_store = GraphStore()
"""Graphs on disk, so a restart does not throw away minutes of crawling.

Set `WEBGRAPH_GRAPH_DIR` to move it. The format is the export format, so a stored graph is
also a file that `webgraph ask --graph` reads directly.
"""


def _remember_graph(root: str, builder: GraphBuilder) -> None:
    with _graphs_lock:
        _graphs[root] = builder
        _graphs.move_to_end(root)
        while len(_graphs) > MAX_CACHED_GRAPHS:
            _graphs.popitem(last=False)


def _recall_graph(root: str) -> GraphBuilder | None:
    with _graphs_lock:
        builder = _graphs.get(root)
        if builder is not None:
            _graphs.move_to_end(root)
            return builder

    # Not in memory. A crawl costs minutes; reading a file costs milliseconds.
    stored = _store.load(root)
    if stored is None:
        return None
    revived = GraphBuilder(root)
    revived.graph = stored
    _remember_graph(root, revived)
    return revived


def _persist_graph(root: str, builder: GraphBuilder) -> None:
    """Write a finished graph out. Failures are logged, never raised.

    Persistence is a convenience on top of a crawl that has already succeeded; letting a
    read-only cache directory turn a completed crawl into an error would be the wrong trade.
    """
    if not builder.graph.sections:
        return
    try:
        _store.save(builder.graph, root)
        _store.prune()
    except Exception as exc:
        print(f"could not persist graph for {root}: {type(exc).__name__}: {exc}")
_crawl_slots = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)
_crawl_pool = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_CRAWLS, thread_name_prefix="webgraph-crawl"
)
"""Crawls run here rather than on the default executor.

`asyncio.to_thread` and every other default-executor user share a single pool; a few
long-running crawls parked in it starve ordinary requests for the life of the process.
"""


class ExtractRequest(BaseModel):
    url: str = Field(description="Page URL to extract from")
    schema_: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="JSON Schema describing the fields to extract. Omit it and the engine "
        "classifies the page and uses the schema for that page type.",
    )
    render: bool = Field(
        default=False,
        description="Force a browser render. Needed for accurate reading order and for "
        "client-rendered pages.",
    )
    rtl: bool = Field(default=False, description="Right-to-left reading direction")


class RenderOptions(BaseModel):
    """Per-request overrides for the browser. Every field defaults to `webgraph.config`."""

    timeout_ms: int | None = Field(default=None, ge=1_000, le=120_000)
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] | None = None
    settle_ms: int | None = Field(default=None, ge=0, le=10_000)
    dismiss_gates: bool | None = None
    reveal_collapsed: bool | None = None
    viewport_width: int | None = Field(default=None, ge=320, le=3840)
    viewport_height: int | None = Field(default=None, ge=320, le=2160)


class FetchOptions(BaseModel):
    """Per-request overrides for the plain HTTP fetch."""

    timeout_seconds: float | None = Field(default=None, ge=1, le=120)
    retries: int | None = Field(default=None, ge=0, le=5)


class CrawlOptions(BaseModel):
    """Per-request overrides for a whole-site crawl. Defaults come from `webgraph.config`;
    the host's caps in `Settings` still apply on top."""

    max_depth: int | None = Field(default=None, ge=0, le=50)
    strict_domain: bool | None = None
    delay_seconds: float | None = Field(default=None, ge=0, le=10)
    verify_inventory: bool | None = None
    follow_links: bool | None = None
    discovery_limit: int | None = Field(default=None, ge=0, le=10_000)
    sitemap_limit: int | None = Field(default=None, ge=0, le=200_000)
    respect_robots: bool | None = None
    remove_chrome: bool | None = None
    main_content: bool | None = None


def _applied(dataclass_default: Any, options: BaseModel | None) -> Any:
    """A config dataclass with the request's non-null overrides applied."""
    if options is None:
        return dataclass_default
    overrides = {k: v for k, v in options.model_dump().items() if v is not None}
    return replace(dataclass_default, **overrides) if overrides else dataclass_default


class TextRequest(BaseModel):
    url: str
    render: bool = Field(
        default=False,
        description="Fetch through a browser as well and merge the two. Ignored when `html` "
        "is supplied: there is nothing to render.",
    )
    rtl: bool = False
    html: str | None = Field(
        default=None,
        description="The page's HTML, when the caller already has it -- from their own "
        "signed-in browser, an extension, a saved file. Nothing is fetched: the engine reads "
        "this instead, for the sites that refuse every automated fetch (a Cloudflare "
        "challenge, a login wall). `url` is still required and is the page's address: links "
        "and images are made absolute against it and a pasted login page is judged against "
        "it. A pasted wall is refused (502) exactly like a fetched one. Reading order is "
        "source order and text a browser would have hidden may appear; the stream's "
        "`render_error` says so.",
    )
    include_hidden_text: bool = Field(
        default=False,
        description="Keep the text a browser holds but a sighted reader never sees: "
        "screen-reader-only labels (`sr-only`, `visually-hidden`), skip links, wiki "
        "edit controls. Off by default -- they label controls rather than say anything, "
        "and on a category page they can outweigh the products -- and on for a caller "
        "that wants every string in the DOM.",
    )
    fetch: FetchOptions | None = None
    render_options: RenderOptions | None = Field(default=None, alias="renderOptions")

    model_config = {"populate_by_name": True}


class FactOut(BaseModel):
    value: Any
    confidence: float
    extractor: str
    modality: str
    source: str | None = None
    source_xpath: str | None = None


class PageInfo(BaseModel):
    url: str
    content_hash: str
    reading_order: Literal[
        "geometric-xy-cut", "geometric-anchored", "dom-fallback", "single-block"
    ]
    reading_order_measured: bool = Field(
        description="False means order was assumed from source, not measured from layout. "
        "`geometric-anchored` counts as measured: most blocks were, and the rest -- collapsed "
        "or offscreen content a browser never lays out -- were placed beside their source-order "
        "neighbours."
    )
    dom_order_differs: bool = Field(
        description="True when the page uses CSS to reorder content away from source order"
    )
    blocks: int
    frameworks: list[str]
    requires_render: bool
    payloads: list[str]


class SchemaChoice(BaseModel):
    """Why these fields and not others -- shown whenever the engine picked the schema.

    A caller who supplied their own schema knows what they asked for. A caller who did not
    is owed the reasoning, because "no price" means something different when the page was
    typed as an article than when it was typed as a product and the price was genuinely
    absent.
    """

    page_type: str
    confidence: float
    fields: list[str]
    subject_types: list[str] = Field(
        default_factory=list,
        description="The @type of each structured-data node accepted as describing this "
        "page. Empty means the page shipped structured data about its site or its "
        "breadcrumbs but nothing about itself, which is the common case on category pages.",
    )
    payloads_considered: int = 0
    payloads_used: int = 0
    filled_from_fallback: list[str] = Field(
        default_factory=list,
        description="Fields no node about the page supplied, taken from the page's own "
        "wrapper or its social-preview tags. Each such fact's source says which.",
    )


class ExtractResponse(BaseModel):
    page: PageInfo
    facts: dict[str, FactOut]
    schema_choice: SchemaChoice | None = Field(
        default=None, description="Present when the engine chose the schema itself."
    )


class TextResponse(BaseModel):
    page: PageInfo
    text: str
    markdown: str = Field(
        default="",
        description="Structure-preserving Markdown: headings, images, links, tables, code.",
    )
    content_markdown: str = Field(
        default="",
        description="The page reduced to its content: `<nav>`/`<footer>` landmarks removed, "
        "then the main-content boundary drawn around the densest run of prose. Empty when "
        "nothing was removed. Cross-page chrome removal needs a whole crawl and is applied "
        "only there; `content_methods` says which steps fired here.",
    )
    content_methods: list[str] = Field(
        default_factory=list,
        description="Steps that removed something to produce `content_markdown`, in order: "
        "any of `landmarks`, `main-landmark`, `article-element`, `article-body`, "
        "`block-model`, `main-content`.",
    )
    comments_markdown: str = Field(
        default="",
        description="The comment thread found under the content and left out of "
        "`content_markdown`, as Markdown in page order. Empty when the page has none, or "
        "when the comments are the page (a forum thread, a Hacker News item) and are in "
        "`content_markdown` already. The article is the article; the discussion is here.",
    )
    content_blocks: int = Field(
        default=0, description="Blocks kept in `content_markdown`, out of `page.blocks`."
    )
    page_type: str = Field(
        default="unknown",
        description="What kind of page this is, from a trained classifier over URL, payload "
        "and structure signals: one of `article`, `documentation`, `service`, `forum`, "
        "`collection`, `listing`, `product`, or `unknown` when no type is confident enough. "
        "Reported, not acted on -- content selection does not branch on it.",
    )
    page_type_confidence: float = Field(
        default=0.0,
        description="Probability the classifier assigned to `page_type`, 0.0 when unknown.",
    )
    images: list[str] = Field(default_factory=list, description="Absolute image URLs found")
    tables: int = Field(default=0, description="Tables extracted with their rows intact")


class SiteRequest(BaseModel):
    url: str = Field(description="Site root URL")
    max_pages: int = Field(
        default=0,
        ge=0,
        le=100000,
        description="0 means unbounded -- crawl until the frontier is exhausted.",
    )
    concurrency: int = Field(default=6, ge=1, le=12)
    complete: bool = Field(
        default=True,
        description="Union static and rendered fetches per page. Slower, but neither mode "
        "alone is complete -- see the engine's resolve module.",
    )
    crawl: CrawlOptions | None = None
    fetch: FetchOptions | None = None
    render_options: RenderOptions | None = Field(default=None, alias="renderOptions")

    model_config = {"populate_by_name": True}


class HealthResponse(BaseModel):
    status: Literal["ok"]
    render_available: bool
    max_concurrent_renders: int
    private_hosts_blocked: bool
    """Whether this instance refuses to fetch loopback and link-local addresses.

    Exposed because it is the one setting whose misconfiguration is invisible until it
    is exploited: a deployment with this False looks perfectly healthy."""
    max_pages: int
    """The server-side page cap. 0 means crawls run until the frontier is exhausted."""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # On by default here, unlike in the engine. This is the process that takes URLs
    # from strangers, and an unguarded one will fetch its own host's credentials on
    # request. `WEBGRAPH_ALLOW_PRIVATE_HOSTS=1` opts out for local work on localhost.
    blocked = guard.configure_from_env(default=True)
    print(f"host policy: private addresses {'blocked' if blocked else 'ALLOWED'}")
    print(f"allowed origins: {', '.join(ALLOWED_ORIGINS)}")
    print(f"page cap: {PAGE_CAP or 'none'}, concurrency cap: {CONCURRENCY_CAP or 'none'}")
    yield


app = FastAPI(
    title="webgraph",
    version="0.1.0",
    description="Universal web content extraction with provenance and reading-order recovery.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _measured(resolved: ResolvedPage) -> bool:
    """Whether the reading order came from a rendered layout. `geometric-anchored` counts:
    most blocks were measured and the rest placed beside them -- see `PageInfo`."""
    return resolved.document.reading_order_method in (
        ReadingOrderMethod.GEOMETRIC_XY_CUT,
        ReadingOrderMethod.GEOMETRIC_ANCHORED,
    )


def _page_info(document: Document, measured: bool) -> PageInfo:
    return PageInfo(
        url=document.url,
        content_hash=document.content_hash,
        reading_order=document.reading_order_method.value,
        reading_order_measured=measured,
        dom_order_differs=document.dom_order_differs,
        blocks=len(document.blocks),
        frameworks=list(document.profile.frameworks),
        requires_render=document.profile.requires_render,
        payloads=[p.source.value for p in document.structured_data],
    )


def _resolve_blocking(request: TextRequest | ExtractRequest) -> ResolvedPage:
    """Resolve the page the way the streaming route and the crawl do. Runs in a worker
    thread -- both fetches are blocking.

    Until PR #81 this route fetched and parsed on its own: static HTML, a browser only when
    the static document looked like a JavaScript shell, and no wall check at all. Every
    refusal the engine learned to name -- a Cloudflare block page (#64), a login redirect
    (#67, #73), a browser served a wall while the plain fetch got the page -- lived in
    `resolve_page`, which only `/api/text/stream` called, so the blocking API could still
    return "Sorry, you have been blocked" as a page of text with a green tick. One path now.

    `render=False` still means what it meant: plain HTTP, escalated to the browser when the
    static document is a shell that needs one. That is one more static fetch for a shell
    than a single `resolve_page` call would make, and a shell is the cheap case. Without a
    browser, a shell is still a document for `/api/extract` -- its hydration payload is the
    whole point of that page -- and a refusal for `/api/text`, which would have nothing to say.
    """
    strategy = Strategy.UNION if request.render else Strategy.STATIC_ONLY
    options: dict[str, Any] = {
        "fetch_config": _applied(FetchConfig(), getattr(request, "fetch", None)),
        "render_config": _applied(RenderConfig(), getattr(request, "render_options", None)),
        "include_hidden_text": getattr(request, "include_hidden_text", False),
        "rtl": request.rtl,
    }
    try:
        resolved = resolve_page(request.url, strategy=strategy, **options)
    except PageShellError as exc:
        shell = exc.document
        if strategy is Strategy.STATIC_ONLY and PLAYWRIGHT_AVAILABLE:
            try:
                return resolve_page(request.url, strategy=Strategy.UNION, **options)
            except PageShellError as still_a_shell:
                # The browser ran it and it stayed empty: a shell whose script never
                # filled the page. The payload is still what the extract route reads.
                shell = still_a_shell.document
        if isinstance(request, ExtractRequest):
            return ResolvedPage(
                url=shell.url,
                document=shell,
                strategy=Strategy.STATIC_ONLY,
                static_chars=0,
                rendered_chars=0,
                union_chars=0,
                blocks_only_in_static=0,
                blocks_only_in_rendered=0,
                render_error="the page stayed a JavaScript shell; facts read from its payload",
            )
        raise
    if (
        strategy is Strategy.STATIC_ONLY
        and resolved.document.profile.requires_render
        and PLAYWRIGHT_AVAILABLE
    ):
        resolved = resolve_page(request.url, strategy=Strategy.UNION, **options)
    return resolved


def _supplied(request: TextRequest) -> ResolvedPage:
    """The caller's own HTML, read in a worker thread: parsing a large page is CPU-bound
    and the event loop should not wait on it. Nothing here touches the network."""
    assert request.html is not None
    return resolve_supplied(
        request.html, request.url, include_hidden_text=request.include_hidden_text, rtl=request.rtl
    )


async def _resolve(request: TextRequest | ExtractRequest) -> ResolvedPage:
    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must be http or https")

    if isinstance(request, TextRequest) and request.html is not None:
        # Nothing is fetched, so nothing needs a render slot or the shell escalation in
        # `_resolve_blocking`; and the failure messages must not say "fetch", because no
        # fetch happened -- an oversize paste or a paste with no readable text is the
        # caller's HTML being refused, and the detail should say that.
        try:
            return await asyncio.to_thread(_supplied, request)
        except PageBlockedError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        if request.render:
            async with _render_slots:
                return await asyncio.to_thread(_resolve_blocking, request)
        # A shell escalates to the browser inside `_resolve_blocking`, outside the render
        # slots; the crawl's browser pool bounds it the same way it bounds the stream route.
        return await asyncio.to_thread(_resolve_blocking, request)
    except PageMissingError as exc:
        raise HTTPException(status_code=502, detail=f"could not fetch page: {exc}") from exc
    except PageBlockedError as exc:
        # The server answered, but with a wall. 502 like every other "could not fetch": the
        # page was not obtained, and a caller that treats the body as content would be
        # reading the wall. The message says which wall (`kind`) and quotes it.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"could not fetch page: {exc}") from exc


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        render_available=PLAYWRIGHT_AVAILABLE,
        max_concurrent_renders=MAX_CONCURRENT_RENDERS,
        private_hosts_blocked=guard.private_hosts_blocked(),
        max_pages=PAGE_CAP,
    )


@app.post("/api/text", response_model=TextResponse)
async def get_text(request: TextRequest) -> TextResponse:
    """Return page text in recovered reading order."""
    resolved = await _resolve(request)
    document = resolved.document

    images = [b.href for b in document.blocks if b.kind is BlockKind.IMAGE and b.href]
    tables = sum(1 for b in document.blocks if b.kind is BlockKind.TABLE)

    # The same reduction the crawl applies, minus cross-page chrome, which one page cannot
    # know. One function decides what "content" means -- see `webgraph.content`.
    router = default_router()
    routing = router.route(document) if router is not None else None
    # See `webgraph.site._content_of`: on a listing the page type is the difference between
    # returning the items and returning the footer.
    selection = select_content(
        document.blocks,
        config=policy_for(routing.page_type if routing else None),
        title=document.title,
    )
    content = (
        to_markdown(
            document.model_copy(update={"blocks": tuple(selection.blocks)}),
            options=MarkdownOptions(),
        )
        if selection.changed
        else ""
    )
    comments = (
        to_markdown(
            document.model_copy(update={"blocks": selection.comments}), options=MarkdownOptions()
        )
        if selection.comments
        else ""
    )

    return TextResponse(
        page=_page_info(document, _measured(resolved)),
        text=document.text,
        markdown=to_markdown(document, options=MarkdownOptions()),
        content_markdown=content,
        comments_markdown=comments,
        content_methods=list(selection.methods),
        content_blocks=selection.kept,
        page_type=str(routing.page_type) if routing else "unknown",
        page_type_confidence=round(routing.confidence, 4) if routing else 0.0,
        images=images,
        tables=tables,
    )


@app.post("/api/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest) -> ExtractResponse:
    """Extract facts matching a JSON Schema, each with its provenance.

    With no schema the engine classifies the page and uses the schema for that type, and
    reads only the structured-data node that describes the page -- not the site's
    `Organization`, not its breadcrumbs. Without that gate, a category page reports the
    shop's name as its own 46% of the time.
    """
    if request.schema_ is not None and (
        not isinstance(request.schema_, dict) or "properties" not in request.schema_
    ):
        raise HTTPException(
            status_code=422, detail="schema must be a JSON Schema object with 'properties'"
        )

    resolved = await _resolve(request)
    document, url = resolved.document, resolved.url

    choice: SchemaChoice | None = None
    if request.schema_ is not None:
        merged = merge_facts(
            extract_facts(list(document.structured_data), request.schema_, url)
        )
    else:
        # No router means no page type, which means no schema to choose. Degrading to a
        # default schema would be picking a vocabulary at random.
        router = default_router()
        routing = router.route(document, url) if router else None
        page_type = routing.page_type if routing else PageType.UNKNOWN
        # The gate runs only on an auto-chosen schema. A caller who wrote their own schema
        # may well be reaching for the site's `Organization` on purpose, and narrowing their
        # payloads without being asked would be this endpoint deciding what they meant.
        page = facts_for_page(document.structured_data, page_type, url)
        merged = page.facts
        choice = SchemaChoice(
            page_type=page_type.value,
            confidence=round(routing.confidence, 4) if routing else 0.0,
            fields=sorted(page.schema.get("properties", {})),
            subject_types=list(page.subject_types),
            payloads_considered=page.payloads_considered,
            payloads_used=page.payloads_used,
            filled_from_fallback=list(page.filled_from_generic),
        )

    return ExtractResponse(
        page=_page_info(document, _measured(resolved)),
        schema_choice=choice,
        facts={
            path: FactOut(
                value=fact.value,
                confidence=fact.provenance.confidence,
                extractor=fact.provenance.extractor.value,
                modality=fact.provenance.modality.value,
                source=fact.provenance.note,
                source_xpath=fact.provenance.source_xpath,
            )
            for path, fact in sorted(merged.items())
        },
    )


@app.exception_handler(guard.BlockedHostError)
async def _blocked_host(_request: Request, exc: guard.BlockedHostError) -> JSONResponse:
    """A refused address is a 403 with the reason, not a 500 with none.

    `guard.check_url` raises before a stream sends its first byte, and an unhandled
    exception there produced a bare 500 *without CORS headers* -- so the browser reported
    "Cannot reach the API. Is it running?" for a request the API had deliberately refused.
    The one message that could not have been less true. Routed through a JSONResponse so
    the CORS middleware decorates it like any other answer.
    """
    return JSONResponse(status_code=403, content={"detail": f"refused: {exc}"})


def _sse(event: dict[str, Any]) -> str:
    """Encode one Server-Sent Event.

    SSE rather than a websocket: the stream is one-directional, it survives ordinary HTTP
    infrastructure, and the browser reconnect semantics come for free.
    """
    return f"data: {json.dumps(event, default=str)}\n\n"


class ContextRequest(BaseModel):
    url: str = Field(description="Root of a site that has already been crawled")
    query: str = Field(description="What the context should be about")
    max_chars: int = Field(
        default=120_000,
        ge=1_000,
        le=4_000_000,
        description="Size of the assembled context. Roughly four characters per token.",
    )
    max_hops: int = Field(default=2, ge=0, le=3)


class ContextSource(BaseModel):
    heading: str
    page_url: str
    page_title: str
    hops: int
    score: float
    reason: str
    chars: int
    tier: Literal["full", "opening"]


class ContextResponse(BaseModel):
    text: str
    sources: list[ContextSource]
    pages_mapped: list[str]
    stats: dict[str, float]
    graph: dict[str, int]


@app.post("/api/site/context", response_model=ContextResponse)
async def site_context(request: ContextRequest) -> ContextResponse:
    """Assemble a bounded context about `query` from a crawled site.

    The crawl is the expensive part and has already happened; this is a query over its
    graph. Answers arrive in milliseconds, so it runs on the event loop rather than a thread.
    """
    builder = _recall_graph(request.url)
    if builder is None:
        raise HTTPException(
            status_code=404,
            detail=f"No graph for {request.url}. Crawl it first.",
        )

    graph = builder.graph
    if not graph.sections:
        raise HTTPException(
            status_code=409, detail="The crawl has not produced any content yet."
        )

    # Derived on demand rather than during the crawl: it needs the whole link graph to know
    # what other pages call a page, and it is idempotent, so asking twice costs nothing.
    if not graph.entities:
        derive_entities(graph)

    assembler = ContextAssembler(graph)
    assembled = assembler.assemble(
        request.query,
        budget=Budget(max_chars=request.max_chars),
        max_hops=request.max_hops,
    )

    def source(item: Any, tier: str) -> ContextSource:
        page = graph.pages.get(item.section.page_key)
        return ContextSource(
            heading=item.section.heading or "(opening)",
            page_url=page.url if page else item.section.page_key,
            page_title=page.title if page else item.section.page_key,
            hops=item.hops,
            score=round(item.score, 4),
            reason=item.reason,
            chars=item.section.chars,
            tier=tier,  # type: ignore[arg-type]
        )

    return ContextResponse(
        text=assembled.text,
        sources=[source(item, "full") for item in assembled.sections_full]
        + [source(item, "opening") for item in assembled.sections_opening],
        pages_mapped=[
            graph.pages[key].url for key in assembled.pages_mapped if key in graph.pages
        ],
        stats={k: round(v, 4) for k, v in assembled.stats.items()},
        graph=graph.describe(),
    )


class GraphEntity(BaseModel):
    key: str
    type: str
    name: str
    aliases: list[str]
    pages: list[str]


class GraphHub(BaseModel):
    url: str
    title: str
    inbound: int
    outbound: int
    sections: int
    specificity: float


class GraphSummary(BaseModel):
    root: str
    counts: dict[str, int]
    entities: list[GraphEntity]
    hubs: list[GraphHub]
    deepest: list[str]


@app.get("/api/site/graph/summary", response_model=GraphSummary)
async def site_graph_summary(url: str, limit: int = 24) -> GraphSummary:
    """What the crawl learned about how the site is put together.

    Hubs are ranked by inbound links, which is the site telling you what it considers
    central. `specificity` is the inverse: a page linked from everything is navigation, and
    showing both together is what distinguishes the two.
    """
    builder = _recall_graph(url)
    if builder is None:
        raise HTTPException(status_code=404, detail=f"No graph for {url}. Crawl it first.")

    graph = builder.graph
    if not graph.entities and graph.sections:
        derive_entities(graph)

    hubs = sorted(
        graph.pages.values(),
        key=lambda page: (
            -len(graph.linked_from.get(page.key, ())),
            -len(page.section_ids),
        ),
    )[:limit]

    return GraphSummary(
        root=graph.root,
        counts=graph.describe(),
        entities=[
            GraphEntity(
                key=entity.key,
                type=entity.type,
                name=entity.name or entity.key,
                aliases=[str(a) for a in (entity.data.get("aliases") or [])][:4],
                pages=[
                    graph.pages[key].url for key in entity.pages if key in graph.pages
                ][:4],
            )
            for entity in sorted(
                graph.entities.values(), key=lambda e: (-e.page_count, e.name)
            )[:limit]
        ],
        hubs=[
            GraphHub(
                url=page.url,
                title=page.title,
                inbound=len(graph.linked_from.get(page.key, ())),
                outbound=len(graph.links_to.get(page.key, ())),
                sections=len(page.section_ids),
                specificity=round(graph.link_specificity(page.key), 3),
            )
            for page in hubs
        ],
        deepest=[
            graph.pages[key].url
            for key in sorted(
                graph.pages, key=lambda k: -graph.pages[k].depth
            )[:8]
        ],
    )


@app.get("/api/site/graph")
async def site_graph(url: str) -> StreamingResponse:
    """Stream the site graph as JSON Lines, for loading elsewhere.

    Streamed rather than assembled: a large graph is tens of megabytes, and buffering it to
    build a response body would double the peak memory of the process that owns it.
    """
    builder = _recall_graph(url)
    if builder is None:
        raise HTTPException(status_code=404, detail=f"No graph for {url}. Crawl it first.")

    graph = builder.graph

    async def lines() -> AsyncIterator[str]:
        for line in to_jsonl(graph):
            yield line + "\n"

    host = url.replace("https://", "").replace("http://", "").strip("/").replace("/", "_")
    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{host}.graph.jsonl"'},
    )


def _effective_max_pages(requested: int) -> int:
    """Apply the host's page cap to what the client asked for.

    A request of 0 means "until the frontier is exhausted", so on a capped host it is the
    largest possible ask, not the smallest -- it has to clamp down to the cap rather than
    through it.
    """
    if not PAGE_CAP:
        return requested
    return PAGE_CAP if requested == 0 else min(requested, PAGE_CAP)


def _engine_version() -> str:
    """The installed engine's version, or "unknown" rather than a number that is a guess.

    Read once at import: a log line that names the wrong build sends whoever reads it to the
    wrong source."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("webgraph")
    except PackageNotFoundError:
        return "unknown"


TRACE_DIR: Final[Path] = (SETTINGS.trace_dir or Path(tempfile.gettempdir())) / "webgraph-runs"
"""Where run traces are written. See `Settings.trace_dir`."""


ENGINE_VERSION: Final[str] = _engine_version()


def _open_trace(url: str) -> RunTrace:
    """One file per run, named so it can be found by host and time without an index.

    The run id is in the filename as well as inside the file. Host and second alone are not
    unique -- two tabs pointed at the same site in the same second would have opened the
    same path in `"w"` mode, and the second run would have silently erased the first. A
    trace that can vanish is worse than no trace, because it is trusted.
    """
    host = re.sub(r"[^a-z0-9.-]+", "-", urlsplit(url).netloc.lower()) or "site"
    run_id = uuid.uuid4().hex[:12]
    stamp = time.strftime("%Y%m%dT%H%M%S")
    return RunTrace(TRACE_DIR / f"{host}-{stamp}-{run_id}.jsonl", run_id=run_id)


def _run_header(url: str, trace: RunTrace, **options: Any) -> dict[str, Any]:
    """The first frame of a stream, and the first line of its trace.

    Everything needed to read the rest of the log without guessing: which address, which
    options were *actually applied* after this host's caps, which engine, and the id of the
    file on the server holding the same events. The file name travels; the path does not --
    a client has no use for the server's directory layout.
    """
    return {
        "type": "run",
        "run": trace.run_id,
        "trace": trace.path.name,
        "url": url,
        "engine": ENGINE_VERSION,
        "started": time.time(),
        **options,
    }


class ConfigResponse(BaseModel):
    settings: dict[str, dict[str, Any]] = Field(
        description="Every setting in webgraph/config.py: value, comment, section."
    )
    overridable: dict[str, list[str]] = Field(
        description="Which of them a request may override, by request field: crawl, fetch, "
        "renderOptions. Everything else is changed by editing config.py."
    )
    caps: dict[str, int] = Field(description="The host's caps from the environment; 0 means none.")


@app.get("/api/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """The engine's settings, as the settings page shows them.

    Values and comments come straight from `webgraph/config.py`, so the page and the file
    never disagree. The `overridable` map says which a request may change per run.
    """
    return ConfigResponse(
        settings=describe_config(),
        overridable={
            "crawl": sorted(CrawlOptions.model_fields),
            "fetch": sorted(FetchOptions.model_fields),
            "renderOptions": sorted(RenderOptions.model_fields),
        },
        caps={
            "max_pages": PAGE_CAP,
            "max_concurrency": CONCURRENCY_CAP,
            "max_concurrent_renders": MAX_CONCURRENT_RENDERS,
            "max_concurrent_crawls": MAX_CONCURRENT_CRAWLS,
        },
    )


@app.post("/api/text/stream")
async def text_stream(request: TextRequest) -> StreamingResponse:
    """One page, streamed stage by stage.

    The same pipeline `/api/text` runs, reported as it happens. Behind a browser render a
    single page can take ten seconds, and a request that says nothing until it finishes is
    indistinguishable from one that has hung -- which is why the whole-site crawl has always
    streamed and this, until now, did not.

    Every failure arrives as an `error` event and closes the stream. Nothing here raises
    into a half-written response: once the first byte is sent an HTTP status can no longer
    say anything, so the status is not where failure is reported.
    """
    # Checked before a single byte is sent, because after that a status code can no longer
    # say anything. Everything that can only be discovered *during* the run reports as an
    # event instead.
    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must be http or https")
    supplied = request.html is not None
    if not supplied:
        # The guard exists to stop this process fetching addresses inside its own network,
        # and it resolves the host to do so. With the HTML supplied nothing is fetched --
        # `url` names the document and is the base for its links -- so there is nothing
        # for it to stop, and a DNS lookup on a name that need not resolve would only fail
        # a request that has everything it needs.
        guard.check_url(request.url)

    # The header reports the run, not the request: `render` on a supplied page is ignored
    # (see `TextRequest.html`), and a log claiming a browser ran would be the small untruth
    # `stream_page` takes care not to tell.
    strategy = (
        Strategy.SUPPLIED
        if supplied
        else Strategy.UNION
        if request.render
        else Strategy.STATIC_ONLY
    )
    fetch_config = _applied(FetchConfig(), request.fetch)
    render_config = _applied(RenderConfig(), request.render_options)

    async def generate() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        trace = _open_trace(request.url)
        # First frame and first line, identical. A log someone pastes into a bug report and
        # the file left on the server now name each other, so the two can be put side by
        # side without anyone having to guess which run they are looking at.
        header = _run_header(
            request.url,
            trace,
            mode="page",
            strategy=strategy.value,
            render=request.render and not supplied,
            supplied=supplied,
        )
        trace.write(header)
        yield _sse(header)

        def produce() -> None:
            # The trace is owned here rather than by `trace_events`, so that the failure
            # below is written *before* the file closes. A tracer that closed it in its own
            # `finally` would miss exactly the event worth keeping.
            try:
                for event in trace_events(
                    stream_page(
                        request.url,
                        strategy=strategy,
                        fetch_config=fetch_config,
                        render_config=render_config,
                        include_hidden_text=request.include_hidden_text,
                        html=request.html,
                    ),
                    trace,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, dict(event))
            except Exception as exc:
                failure = {
                    "type": "error",
                    "stage": "unknown",
                    "message": f"{type(exc).__name__}: {exc}",
                }
                trace.write(failure)
                loop.call_soon_threadsafe(queue.put_nowait, failure)
            finally:
                trace.write({"type": "trace-closed"})
                trace.close()
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(_crawl_pool, produce)

        while True:
            event = await queue.get()
            if event is None:
                return
            yield _sse(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _effective_concurrency(requested: int) -> int:
    """Apply the host's concurrency cap. Unlike pages, 0 is not a meaningful request here."""
    return min(requested, CONCURRENCY_CAP) if CONCURRENCY_CAP else requested


@app.post("/api/site/stream")
async def site_stream(request: SiteRequest) -> StreamingResponse:
    """Run the whole-site pipeline, streaming each stage as it completes.

    A blocking response is not viable: a union crawl renders every page in a browser, so a
    40-page site runs for minutes. Streaming also reflects the real shape of the work --
    the stack is known in seconds, the inventory shortly after, pages one at a time.
    """
    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must be http or https")

    config = _applied(
        SiteConfig(
            max_pages=_effective_max_pages(request.max_pages),
            concurrency=_effective_concurrency(request.concurrency),
            strategy=Strategy.UNION if request.complete else Strategy.STATIC_ONLY,
            fetch=_applied(FetchConfig(), request.fetch),
            render=_applied(RenderConfig(), request.render_options),
        ),
        request.crawl,
    )

    async def generate() -> AsyncIterator[str]:
        if _crawl_slots.locked():
            yield _sse(
                {
                    "type": "stage",
                    "stage": "analyze",
                    "message": "Waiting for a crawl slot",
                }
            )

        async with _crawl_slots:
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            loop = asyncio.get_running_loop()

            # A generator cannot be interrupted from outside; closing it only raises at the
            # next `yield`, which never comes while a batch of renders is in flight. The
            # engine therefore polls this flag itself, and the `finally` below sets it when
            # the client goes away. Without it every abandoned tab leaves a full-speed crawl
            # running until the process exits.
            stop = threading.Event()

            # The graph is filled in as pages arrive and kept after the stream ends, so the
            # context endpoint can answer questions about this site without re-crawling it.
            builder = GraphBuilder(request.url)
            _remember_graph(request.url, builder)

            # Emitted after the slot is acquired, not before: a run that spent two minutes
            # queued did not start two minutes ago, and every `at` in the trace below is
            # measured from here.
            trace = _open_trace(request.url)
            header = _run_header(
                request.url,
                trace,
                mode="site",
                # The caps this host applied, not what the client asked for. A log that
                # reports the request rather than the run explains nothing when they differ.
                max_pages=config.max_pages,
                concurrency=config.concurrency,
                # None means Stage 0's measured verdict decides per site, which is a real
                # answer and not a missing one.
                strategy=config.strategy.value if config.strategy else "measured",
                complete=request.complete,
                max_depth=config.max_depth,
                strict_domain=config.strict_domain,
            )
            trace.write(header)
            yield _sse(header)

            def produce() -> None:
                try:
                    # Every run leaves a file behind. The stream is consumed and dropped, so
                    # without this the only evidence a crawl ever happened is whatever a
                    # human was looking at -- and the questions that come afterwards ("which
                    # page linked to the one that failed?") are exactly the ones nobody can
                    # answer from memory.
                    for event in trace_events(
                        stream_site(
                            request.url,
                            config=config,
                            should_stop=stop.is_set,
                            builder=builder,
                        ),
                        trace,
                    ):
                        if stop.is_set():
                            return
                        while queue.qsize() > CRAWL_QUEUE_HIGH_WATER and not stop.is_set():
                            time.sleep(0.05)
                        loop.call_soon_threadsafe(queue.put_nowait, event)
                except Exception as exc:
                    failure = {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
                    trace.write(failure)
                    loop.call_soon_threadsafe(queue.put_nowait, failure)
                finally:
                    # Recorded whichever way the crawl ended, including the early `return`
                    # above when the reader walked away mid-crawl -- "stopped at page 40" is
                    # a different fact from "finished", and the file should say which.
                    trace.write({"type": "trace-closed", "stopped": stop.is_set()})
                    trace.close()
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            loop.run_in_executor(_crawl_pool, produce)

            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield _sse(event)
            finally:
                stop.set()
                await asyncio.to_thread(_persist_graph, request.url, builder)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
