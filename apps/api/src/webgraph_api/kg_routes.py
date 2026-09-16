"""WebGraph routes: build, query, inspect, export and sync a site's knowledge graph.

Behind `WEBGRAPH_KG=1`. When the flag is off every route answers 404 with a message that
names the flag, so a client can tell "not enabled" from "not found".

Keys stay local. A provider config travels in the request body, is used for that request,
and is never persisted, traced or echoed: the app-level validation handler redacts it from
422 bodies (FastAPI's default echoes the offending input), `ProviderConfig.redacted()` is
the only form that appears in an event, and nothing here writes a run trace.

The graph a build reads is the stored `SiteGraph` from a crawl (`/api/site/stream` or
`webgraph graph`); the knowledge graph it writes is one SQLite file per site under
`WEBGRAPH_KG_DIR`. One build per site at a time: SQLite has one writer.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from webgraph.graph.model import SiteGraph
from webgraph.kg.build import BuildConfig, KGBuilder
from webgraph.kg.export import to_cypher, to_jsonl, to_jsonld
from webgraph.kg.neo4j import Neo4jUnavailableError, sync_to_neo4j
from webgraph.kg.providers import LLMError, Provider, ProviderConfig, make_provider
from webgraph.kg.retrieve import KGRetriever, RetrievalConfig
from webgraph.kg.store import KGStore

__all__ = ["FLAG_MESSAGE", "create_router", "kg_enabled"]

FLAG_MESSAGE = "WebGraph is not enabled on this server. Start the API with WEBGRAPH_KG=1 to serve /api/graph/*."

_builds_lock = threading.Lock()
_building: set[str] = set()
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="webgraph-kg-api")


def kg_enabled() -> bool:
    """Read per request, not at import: a test flips the variable and expects the change."""
    from webgraph import config

    return os.environ.get("WEBGRAPH_KG", "").strip().lower() in {"1", "true", "yes", "on"} or bool(config.DEPLOY_KG)


def _require_enabled() -> None:
    if not kg_enabled():
        raise HTTPException(status_code=404, detail=FLAG_MESSAGE)


class ProviderIn(BaseModel):
    provider: str | None = Field(default=None, description="openai-compatible | anthropic | gemini, or a preset name such as ollama, groq, openai")
    base_url: str | None = None
    model: str | None = None
    answer_model: str | None = None
    api_key: str | None = Field(default=None, description="Used for this request only; never stored or logged.")
    api_key_env: str | None = None
    json_mode: Literal["json_schema", "json_object", "prompt"] | None = None
    price_per_m_in: float | None = None
    price_per_m_out: float | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=16)


class BudgetIn(BaseModel):
    max_pages: int = Field(default=0, ge=0)
    max_sections: int = Field(default=0, ge=0)
    max_input_tokens: int = Field(default=2_000_000, ge=0)
    max_usd: float = Field(default=0.0, ge=0.0)


class BuildRequest(BaseModel):
    url: str
    provider: ProviderIn | None = None
    budget: BudgetIn = Field(default_factory=BudgetIn)
    gleanings: int = Field(default=0, ge=0, le=1)
    rebuild: bool = False


class QueryRequest(BaseModel):
    url: str
    question: str = Field(min_length=1, max_length=2000)
    provider: ProviderIn | None = None
    max_hops: int = Field(default=2, ge=0, le=3)


class SyncRequest(BaseModel):
    url: str
    uri: str
    user: str
    password: str
    database: str | None = None
    typed_edges: bool = False


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _stream(events: Iterator[dict[str, Any]], *, on_end: Callable[[], None] | None = None) -> StreamingResponse:
    """Run a blocking event generator in the pool and relay it as SSE."""

    async def generate() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        stop = threading.Event()

        def produce() -> None:
            try:
                for event in events:
                    if stop.is_set():
                        return
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except LLMError as exc:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": f"provider: {exc}"})
            except Exception as exc:  # the stream must end with a reason, not hang
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(_pool, produce)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield _sse(event)
        finally:
            stop.set()
            if on_end is not None:
                on_end()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _provider_for(body: ProviderIn | None, *, required: bool) -> Provider | None:
    try:
        config = ProviderConfig.from_dict(body.model_dump(exclude_none=True) if body else {}, base=ProviderConfig.from_env())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if not config.model and config.provider != "fake":
        if required:
            raise HTTPException(
                status_code=422,
                detail="No model configured. Send provider.model in the request or set WEBGRAPH_LLM_MODEL on the server.",
            )
        return None
    return make_provider(config)


def _store_for(url: str, *, must_exist: bool) -> KGStore:
    if must_exist and not KGStore.exists_for(url):
        raise HTTPException(status_code=404, detail=f"No knowledge graph for {url}. Build it first with POST /api/graph/build.")
    return KGStore.for_site(url)


def create_router(recall_graph: Callable[[str], SiteGraph | None]) -> APIRouter:
    router = APIRouter(prefix="/api/graph", tags=["webgraph"])

    @router.post("/build")
    async def build(request: BuildRequest) -> StreamingResponse:
        """Read every section of a crawled site with the model and write the knowledge graph.

        Events: `estimate` (first, before any call), `stage`, `section`, `budget`, `merge`,
        `done`, `error`. Needs a stored graph for `url`; crawl first.
        """
        _require_enabled()
        graph = recall_graph(request.url)
        if graph is None or not graph.sections:
            raise HTTPException(status_code=404, detail=f"No crawled graph for {request.url}. Run /api/site/stream first.")
        provider = _provider_for(request.provider, required=True)
        assert provider is not None
        with _builds_lock:
            if request.url in _building:
                raise HTTPException(status_code=409, detail="A build for this site is already running.")
            _building.add(request.url)

        def release() -> None:
            with _builds_lock:
                _building.discard(request.url)

        try:
            store = _store_for(request.url, must_exist=False)
            builder = KGBuilder(
                graph,
                provider,
                store,
                build_config=BuildConfig(
                    max_pages=request.budget.max_pages,
                    max_sections=request.budget.max_sections,
                    max_input_tokens=request.budget.max_input_tokens,
                    max_usd=request.budget.max_usd,
                    concurrency=provider.config.max_concurrency,
                    gleanings=request.gleanings,
                    rebuild=request.rebuild,
                ),
            )
        except Exception:
            release()  # otherwise the site stays "building" (409) until the process restarts
            raise

        def events() -> Iterator[dict[str, Any]]:
            try:
                yield from builder.run()
            finally:
                store.close()

        return _stream(events(), on_end=release)

    @router.post("/query")
    async def query(request: QueryRequest) -> StreamingResponse:
        """Answer a question from the knowledge graph, streaming the path as it is walked.

        Events: `seeds`, `hop` (per hop), `evidence`, `answer_delta` (per sentence), `answer`.
        Without a model the answer is extractive: the best-matching quotes, cited.
        """
        _require_enabled()
        store = _store_for(request.url, must_exist=True)
        provider = _provider_for(request.provider, required=False)
        retriever = KGRetriever(store, provider, graph=recall_graph(request.url), retrieval=RetrievalConfig(max_hops=request.max_hops))

        def events() -> Iterator[dict[str, Any]]:
            try:
                yield from retriever.ask(request.question)
            finally:
                store.close()

        return _stream(events())

    @router.get("/stats")
    async def stats(url: str) -> dict[str, Any]:
        _require_enabled()
        store = _store_for(url, must_exist=True)
        try:
            return {"url": url, **store.stats()}
        finally:
            store.close()

    @router.get("")
    async def nodes(url: str, limit: int = 2000, min_evidence: int = 1) -> dict[str, Any]:
        """Nodes and edges for a graph view, degree-pruned to `limit` entities."""
        _require_enabled()
        store = _store_for(url, must_exist=True)
        try:
            entities = store.entity_summaries(limit=max(1, min(limit, 5000)), min_evidence=max(1, min_evidence))
            ids = {e["id"] for e in entities}
            return {"url": url, "nodes": entities, "edges": store.relation_summaries(ids)}
        finally:
            store.close()

    @router.get("/entity")
    async def entity(url: str, id: str) -> dict[str, Any]:
        """One entity with its mentions (quotes, url#xpath), attributes and relations."""
        _require_enabled()
        store = _store_for(url, must_exist=True)
        try:
            found = store.get_entity(id)
            if found is None:
                raise HTTPException(status_code=404, detail=f"No entity {id}.")
            relation_ids = [rid for _, rid, _ in store.adjacency().get(id, [])]
            relations = store.relations(relation_ids)
            neighbours = store.entities([r.subject_id for r in relations.values()] + [r.object_id for r in relations.values()])
            return {
                "id": found.id,
                "type": found.type,
                "name": found.name,
                "aliases": list(found.aliases),
                "generic": found.generic,
                "extractor": found.extractor.value,
                "mentions": [{"surface": m.surface, **m.evidence.as_dict(), "anchor": m.evidence.anchor} for m in found.mentions],
                "attributes": {
                    key: [{"value": a.value, "unit": a.unit, **a.evidence.as_dict(), "anchor": a.evidence.anchor} for a in values]
                    for key, values in found.attributes.items()
                },
                "relations": [
                    {
                        "id": r.id,
                        "predicate": r.predicate,
                        "subject": {"id": r.subject_id, "name": neighbours[r.subject_id].name if r.subject_id in neighbours else r.subject_id},
                        "object": {"id": r.object_id, "name": neighbours[r.object_id].name if r.object_id in neighbours else r.object_id},
                        "fact": r.fact,
                        "weight": r.weight,
                        "evidence": [{**e.as_dict(), "anchor": e.anchor} for e in r.evidence],
                    }
                    for r in relations.values()
                ],
            }
        finally:
            store.close()

    @router.get("/export")
    async def export(url: str, fmt: Literal["jsonl", "cypher", "jsonld"] = "jsonl") -> StreamingResponse:
        _require_enabled()
        store = _store_for(url, must_exist=True)
        host = url.replace("https://", "").replace("http://", "").strip("/").replace("/", "_")

        def lines() -> Iterator[str]:
            try:
                if fmt == "jsonl":
                    for line in to_jsonl(store):
                        yield line + "\n"
                elif fmt == "cypher":
                    for line in to_cypher(store):
                        yield line + "\n"
                else:
                    yield json.dumps(to_jsonld(store), indent=1)
            finally:
                store.close()

        media = {"jsonl": "application/x-ndjson", "cypher": "text/plain; charset=utf-8", "jsonld": "application/ld+json"}[fmt]
        extension = {"jsonl": "kg.jsonl", "cypher": "kg.cypher", "jsonld": "kg.jsonld"}[fmt]
        return StreamingResponse(
            lines(), media_type=media, headers={"Content-Disposition": f'attachment; filename="{host}.{extension}"'}
        )

    @router.post("/sync/neo4j")
    async def sync_neo4j(request: SyncRequest) -> StreamingResponse:
        """Push the graph over bolt in `UNWIND $rows MERGE` batches. Credentials are used
        for this request and held by nothing afterwards."""
        _require_enabled()
        store = _store_for(request.url, must_exist=True)

        def events() -> Iterator[dict[str, Any]]:
            try:
                yield from sync_to_neo4j(
                    store,
                    uri=request.uri,
                    user=request.user,
                    password=request.password,
                    database=request.database,
                    typed_edges=request.typed_edges,
                )
            except Neo4jUnavailableError as exc:
                yield {"type": "error", "message": str(exc)}
            finally:
                store.close()

        return _stream(events())

    @router.delete("")
    async def drop(url: str) -> dict[str, Any]:
        _require_enabled()
        path = KGStore.path_for(url)
        existed = path.exists()
        for suffix in ("", "-wal", "-shm"):
            candidate = path.with_name(path.name + suffix)
            if candidate.exists():
                candidate.unlink()
        return {"url": url, "deleted": existed}

    return router
