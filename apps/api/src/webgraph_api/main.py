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
import os
import re
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from webgraph.content import select_content
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.fetch import guard
from webgraph.fetch.render import PLAYWRIGHT_AVAILABLE, geometry_by_xpath, render_page
from webgraph.fetch.static import fetch_static
from webgraph.graph.build import GraphBuilder
from webgraph.graph.entities import derive_entities
from webgraph.graph.export import to_jsonl
from webgraph.graph.retrieve import Budget, ContextAssembler
from webgraph.graph.store import GraphStore
from webgraph.page import stream_page
from webgraph.pagetype import default_router, policy_for
from webgraph.pipeline import build_document
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.resolve import Strategy
from webgraph.site import SiteConfig, stream_site
from webgraph.trace import RunTrace, trace_events
from webgraph.types import BlockKind, Document, Rect


def _origins_from_env() -> list[str]:
    """Browser origins allowed to call this API.

    Comma-separated in `WEBGRAPH_ALLOWED_ORIGINS`; the dev frontend when unset. Never `*`:
    this service fetches arbitrary URLs on the caller's behalf, so an open CORS policy would
    hand every page on the internet a proxy that runs inside our network.
    """
    raw = os.environ.get("WEBGRAPH_ALLOWED_ORIGINS", "")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["http://localhost:3000", "http://127.0.0.1:3000"]


ALLOWED_ORIGINS = _origins_from_env()

PAGE_CAP = int(os.environ.get("WEBGRAPH_MAX_PAGES", "0"))
"""Hard ceiling on pages per crawl, applied after the request is parsed. 0 disables it.

`SiteRequest.max_pages` defaults to 0, meaning "crawl until the frontier is exhausted",
which is the right default for someone running this on their own laptop and an unacceptable
one for a shared deployment: a single caller can otherwise hold a crawl slot for hours. The
cap lives in the environment rather than the model because the right number is a property of
the host, not of the API.
"""

CONCURRENCY_CAP = int(os.environ.get("WEBGRAPH_MAX_CONCURRENCY", "0"))
"""Ceiling on per-crawl worker concurrency. 0 disables it.

The request model already allows up to 12, which is right for a laptop with headroom and
wrong for a two-core container: twelve workers there means twelve browsers competing for
two cores and a fixed memory budget."""

MAX_CONCURRENT_RENDERS = int(os.environ.get("WEBGRAPH_MAX_CONCURRENT_RENDERS", "2"))
"""Browser launches are the memory bottleneck. Two at a time is what a 16 GB laptop
tolerates alongside a dev server; raise it only with measurements."""

MAX_CONCURRENT_CRAWLS = int(os.environ.get("WEBGRAPH_MAX_CONCURRENT_CRAWLS", "3"))
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
        "any of `landmarks`, `main-landmark`, `block-model`, `main-content`.",
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
        private_hosts_blocked=guard.private_hosts_blocked(),
        max_pages=PAGE_CAP,
    )


@app.post("/api/text", response_model=TextResponse)
async def get_text(request: TextRequest) -> TextResponse:
    """Return page text in recovered reading order."""
    html, geometry, url = await _load(request.url, request.render)
    document = build_document(html, url, geometry=geometry, rtl=request.rtl)

    images = [b.href for b in document.blocks if b.kind is BlockKind.IMAGE and b.href]
    tables = sum(1 for b in document.blocks if b.kind is BlockKind.TABLE)

    # The same reduction the crawl applies, minus cross-page chrome, which one page cannot
    # know. One function decides what "content" means -- see `webgraph.content`.
    router = default_router()
    routing = router.route(document) if router is not None else None
    # See `webgraph.site._content_of`: on a listing the page type is the difference between
    # returning the items and returning the footer.
    selection = select_content(
        document.blocks, config=policy_for(routing.page_type if routing else None)
    )
    content = (
        to_markdown(
            document.model_copy(update={"blocks": tuple(selection.blocks)}),
            options=MarkdownOptions(),
        )
        if selection.changed
        else ""
    )

    return TextResponse(
        page=_page_info(document, bool(geometry)),
        text=document.text,
        markdown=to_markdown(document, options=MarkdownOptions()),
        content_markdown=content,
        content_methods=list(selection.methods),
        content_blocks=selection.kept,
        page_type=str(routing.page_type) if routing else "unknown",
        page_type_confidence=round(routing.confidence, 4) if routing else 0.0,
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


TRACE_DIR: Final[Path] = Path(
    os.environ.get("WEBGRAPH_TRACE_DIR", tempfile.gettempdir())
) / "webgraph-runs"
"""Where run traces are written. A temp directory by default: a trace is diagnostic, and a
server that fills a disk with them by default has replaced one problem with another. Point
`$WEBGRAPH_TRACE_DIR` somewhere durable to keep them."""


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
    guard.check_url(request.url)

    strategy = Strategy.UNION if request.render else Strategy.STATIC_ONLY

    async def generate() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        trace = _open_trace(request.url)
        # First frame and first line, identical. A log someone pastes into a bug report and
        # the file left on the server now name each other, so the two can be put side by
        # side without anyone having to guess which run they are looking at.
        header = _run_header(
            request.url, trace, mode="page", strategy=strategy.value, render=request.render
        )
        trace.write(header)
        yield _sse(header)

        def produce() -> None:
            # The trace is owned here rather than by `trace_events`, so that the failure
            # below is written *before* the file closes. A tracer that closed it in its own
            # `finally` would miss exactly the event worth keeping.
            try:
                for event in trace_events(
                    stream_page(request.url, strategy=strategy), trace
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

    config = SiteConfig(
        max_pages=_effective_max_pages(request.max_pages),
        concurrency=_effective_concurrency(request.concurrency),
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
