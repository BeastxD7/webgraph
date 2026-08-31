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
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.fetch.render import PLAYWRIGHT_AVAILABLE, geometry_by_xpath, render_page
from webgraph.fetch.static import fetch_static
from webgraph.graph.build import GraphBuilder
from webgraph.graph.entities import derive_entities
from webgraph.graph.export import to_jsonl
from webgraph.graph.retrieve import Budget, ContextAssembler
from webgraph.pipeline import build_document
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.resolve import Strategy
from webgraph.site import SiteConfig, stream_site
from webgraph.types import BlockKind, Document, Rect

MAX_CONCURRENT_RENDERS = 2
"""Browser launches are the memory bottleneck. Two at a time is what a 16 GB laptop
tolerates alongside a dev server; raise it only with measurements."""

MAX_CONCURRENT_CRAWLS = 3
"""Whole-site crawls in flight at once, across all callers.

Each crawl runs its own worker pool of browsers, so this multiplies: three crawls at
concurrency 6 is already eighteen page fetches in flight. Requests beyond the cap wait
rather than being rejected -- a crawl is a long operation and a queue is friendlier than
a 429 -- and are told they are waiting.
"""

CRAWL_QUEUE_HIGH_WATER = 64
"""Events buffered before the producer throttles.

A `page` event carries the whole document. A client that cannot keep up must not be able
to turn the buffer into an unbounded memory leak.
"""

MAX_CACHED_GRAPHS = 4
"""Site graphs kept in memory, evicted oldest-first.

A graph is the by-product of a crawl and is what makes the context endpoint answerable
without re-crawling. Four is a compromise: a 2,000-page site is roughly 20,000 sections and
tens of megabytes, and this is a single-process service on someone's laptop. Persist to
JSONL (`GET /api/graph/export`) for anything that should outlive the process.
"""

_render_slots = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)

_graphs: OrderedDict[str, GraphBuilder] = OrderedDict()
_graphs_lock = threading.Lock()


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
    schema_: dict[str, Any] = Field(
        alias="schema", description="JSON Schema describing the fields to extract"
    )
    render: bool = Field(
        default=False,
        description="Force a browser render. Needed for accurate reading order and for "
        "client-rendered pages.",
    )
    rtl: bool = Field(default=False, description="Right-to-left reading direction")


class TextRequest(BaseModel):
    url: str
    render: bool = False
    rtl: bool = False


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
    reading_order: Literal["geometric-xy-cut", "dom-fallback", "single-block"]
    reading_order_measured: bool = Field(
        description="False means order was assumed from source, not measured from layout"
    )
    dom_order_differs: bool = Field(
        description="True when the page uses CSS to reorder content away from source order"
    )
    blocks: int
    frameworks: list[str]
    requires_render: bool
    payloads: list[str]


class ExtractResponse(BaseModel):
    page: PageInfo
    facts: dict[str, FactOut]


class TextResponse(BaseModel):
    page: PageInfo
    text: str
    markdown: str = Field(
        default="",
        description="Structure-preserving Markdown: headings, images, links, tables, code.",
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


class HealthResponse(BaseModel):
    status: Literal["ok"]
    render_available: bool
    max_concurrent_renders: int


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


app = FastAPI(
    title="webgraph",
    version="0.1.0",
    description="Universal web content extraction with provenance and reading-order recovery.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # The dev frontend only. A permissive default would ship to production unnoticed.
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
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


def _load_blocking(url: str, want_render: bool) -> tuple[str, dict[str, Rect], str]:
    """Fetch and optionally render. Runs in a worker thread -- both calls are blocking."""
    result = fetch_static(url)
    if not result.ok:
        raise HTTPException(status_code=502, detail=f"could not fetch page: {result.error}")
    if not result.is_html:
        raise HTTPException(
            status_code=415, detail=f"unsupported content type: {result.content_type}"
        )

    if not want_render:
        probe = build_document(result.html, result.url)
        if not probe.profile.requires_render:
            return result.html, {}, result.url

    if not PLAYWRIGHT_AVAILABLE:
        return result.html, {}, result.url

    rendered = render_page(url)
    if not rendered.ok:
        # A render failure degrades to static HTML rather than failing the request: partial
        # content with honest metadata beats a 500.
        return result.html, {}, result.url

    return rendered.html, geometry_by_xpath(rendered.html, rendered.rects), rendered.url


async def _load(url: str, want_render: bool) -> tuple[str, dict[str, Rect], str]:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must be http or https")

    if want_render:
        async with _render_slots:
            return await asyncio.to_thread(_load_blocking, url, True)
    return await asyncio.to_thread(_load_blocking, url, False)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        render_available=PLAYWRIGHT_AVAILABLE,
        max_concurrent_renders=MAX_CONCURRENT_RENDERS,
    )


@app.post("/api/text", response_model=TextResponse)
async def get_text(request: TextRequest) -> TextResponse:
    """Return page text in recovered reading order."""
    html, geometry, url = await _load(request.url, request.render)
    document = build_document(html, url, geometry=geometry, rtl=request.rtl)

    images = [b.href for b in document.blocks if b.kind is BlockKind.IMAGE and b.href]
    tables = sum(1 for b in document.blocks if b.kind is BlockKind.TABLE)

    return TextResponse(
        page=_page_info(document, bool(geometry)),
        text=document.text,
        markdown=to_markdown(document, options=MarkdownOptions()),
        images=images,
        tables=tables,
    )


@app.post("/api/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest) -> ExtractResponse:
    """Extract facts matching a JSON Schema, each with its provenance."""
    if not isinstance(request.schema_, dict) or "properties" not in request.schema_:
        raise HTTPException(
            status_code=422, detail="schema must be a JSON Schema object with 'properties'"
        )

    html, geometry, url = await _load(request.url, request.render)
    document = build_document(html, url, geometry=geometry, rtl=request.rtl)
    merged = merge_facts(extract_facts(document.structured_data, request.schema_, url))

    return ExtractResponse(
        page=_page_info(document, bool(geometry)),
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


@app.post("/api/site/stream")
async def site_stream(request: SiteRequest) -> StreamingResponse:
    """Run the whole-site pipeline, streaming each stage as it completes.

    A blocking response is not viable: a union crawl renders every page in a browser, so a
    40-page site runs for minutes. Streaming also reflects the real shape of the work --
    the stack is known in seconds, the inventory shortly after, pages one at a time.
    """
    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must be http or https")

    config = SiteConfig(
        max_pages=request.max_pages,
        concurrency=request.concurrency,
        strategy=Strategy.UNION if request.complete else Strategy.STATIC_ONLY,
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

            def produce() -> None:
                try:
                    for event in stream_site(
                        request.url,
                        config=config,
                        should_stop=stop.is_set,
                        builder=builder,
                    ):
                        if stop.is_set():
                            return
                        while queue.qsize() > CRAWL_QUEUE_HIGH_WATER and not stop.is_set():
                            time.sleep(0.05)
                        loop.call_soon_threadsafe(queue.put_nowait, event)
                except Exception as exc:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "error", "message": f"{type(exc).__name__}: {exc}"},
                    )
                finally:
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

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
