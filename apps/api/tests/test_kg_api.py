"""`/api/graph/*`: the WebGraph routes, behind `WEBGRAPH_KG`.

Hermetic: the crawled graph is built from the fixture site's HTML files and injected into
the API's graph cache, the model is the `FakeProvider`, and the knowledge graph lands in a
temporary directory. Nothing here reaches the network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from webgraph.graph.build import GraphBuilder
from webgraph.kg.offline import graph_from_directory

from webgraph_api import kg_routes
from webgraph_api.main import _remember_graph, app

FIXTURE = Path(__file__).resolve().parents[3] / "benchmark" / "kg" / "fixtures" / "site"
ROOT = "https://kg-fixture.test/"
FAKE = {"provider": "fake", "model": "fake-1"}


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    out = []
    for frame in response.text.split("\n\n"):
        for line in frame.split("\n"):
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("WEBGRAPH_KG", "1")
    monkeypatch.setenv("WEBGRAPH_KG_DIR", str(tmp_path / "kg"))
    builder = GraphBuilder(ROOT)
    builder.graph = graph_from_directory(FIXTURE, ROOT)
    _remember_graph(ROOT, builder)
    with TestClient(app) as test_client:
        yield test_client


class TestFlag:
    def test_routes_404_with_the_flag_named_when_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WEBGRAPH_KG", raising=False)
        with TestClient(app) as client:
            assert client.get("/api/health").json()["webgraph"] is False
            for method, path, body in (
                ("get", f"/api/graph/stats?url={ROOT}", None),
                ("get", f"/api/graph?url={ROOT}", None),
                ("post", "/api/graph/build", {"url": ROOT, "provider": FAKE}),
                ("post", "/api/graph/query", {"url": ROOT, "question": "q"}),
                ("post", "/api/graph/sync/neo4j", {"url": ROOT, "uri": "bolt://x", "user": "u", "password": "p"}),
            ):
                response = client.get(path) if method == "get" else client.post(path, json=body)
                assert response.status_code == 404, path
                assert "WEBGRAPH_KG=1" in response.json()["detail"]

    def test_health_reports_the_flag_when_on(self, client: TestClient) -> None:
        assert client.get("/api/health").json()["webgraph"] is True


class TestBuildAndQuery:
    def test_build_streams_estimate_first_and_done_last(self, client: TestClient) -> None:
        events = _events(client.post("/api/graph/build", json={"url": ROOT, "provider": FAKE}))
        kinds = [e["type"] for e in events]
        assert kinds[0] == "estimate" and kinds[-1] == "done"
        assert events[0]["sections"] == 23 and events[0]["provider"]["has_key"] is False
        assert "api_key" not in json.dumps(events)
        assert kinds.count("section") == 23 and "merge" in kinds
        done = events[-1]
        assert done["stats"]["entities"] > 10 and done["stats"]["rejected"] >= 0
        assert not done["truncated"]

    def test_build_needs_a_crawled_graph(self, client: TestClient) -> None:
        response = client.post("/api/graph/build", json={"url": "https://never-crawled.test/", "provider": FAKE})
        assert response.status_code == 404 and "site/stream" in response.json()["detail"]

    def test_build_needs_a_model(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WEBGRAPH_LLM_MODEL", raising=False)
        response = client.post("/api/graph/build", json={"url": ROOT, "provider": {"provider": "ollama"}})
        assert response.status_code == 422 and "provider.model" in response.json()["detail"]

    def test_api_key_env_cannot_point_at_an_arbitrary_server_variable(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "AKIA-not-for-you")
        body = {"url": ROOT, "provider": {"model": "m", "base_url": "https://collector.example/v1", "api_key_env": "AWS_SECRET_ACCESS_KEY"}}
        response = client.post("/api/graph/build", json=body)
        assert response.status_code == 422
        assert "api_key_env may name one of" in response.json()["detail"]
        assert "AKIA-not-for-you" not in response.text

    def test_a_422_never_echoes_the_key(self, client: TestClient) -> None:
        # A missing field makes FastAPI echo the whole body as `input`, key included.
        response = client.post("/api/graph/build", json={"provider": {"model": "m", "api_key": "sk-very-secret"}})
        assert response.status_code == 422
        assert "sk-very-secret" not in response.text
        assert "[redacted]" in response.text

    def test_budget_cap_is_honoured(self, client: TestClient) -> None:
        events = _events(client.post("/api/graph/build", json={"url": ROOT, "provider": FAKE, "budget": {"max_input_tokens": 1500}}))
        assert any(e["type"] == "budget" and e["reason"] == "max_input_tokens" for e in events)
        assert events[-1]["truncated"] is True

    def test_query_streams_the_path_then_a_cited_answer(self, client: TestClient) -> None:
        _events(client.post("/api/graph/build", json={"url": ROOT, "provider": FAKE}))
        events = _events(client.post("/api/graph/query", json={"url": ROOT, "question": "What is the tuition fee for B.E. Computer Science?", "provider": FAKE}))
        kinds = [e["type"] for e in events]
        assert kinds[0] == "seeds" and "hop" in kinds and "evidence" in kinds and kinds[-1] == "answer"
        assert kinds.index("evidence") < kinds.index("answer_delta") < kinds.index("answer")
        answer = events[-1]
        assert "₹1,20,000" in answer["text"]
        assert answer["citations"] and all("#/html/" in c["anchor"] for c in answer["citations"])
        assert answer["unsupported"] == 0 and answer["path"]["seeds"]

    def test_query_without_a_model_is_extractive(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WEBGRAPH_LLM_MODEL", raising=False)
        _events(client.post("/api/graph/build", json={"url": ROOT, "provider": FAKE}))
        events = _events(client.post("/api/graph/query", json={"url": ROOT, "question": "TechFest 2026"}))
        assert events[-1]["type"] == "answer" and events[-1]["usage"]["model"] == "none" and events[-1]["citations"]

    def test_no_model_wins_over_a_configured_model(self, client: TestClient) -> None:
        _events(client.post("/api/graph/build", json={"url": ROOT, "provider": FAKE}))
        events = _events(client.post("/api/graph/query", json={"url": ROOT, "question": "TechFest 2026", "provider": FAKE, "no_model": True}))
        assert events[-1]["type"] == "answer" and events[-1]["usage"]["model"] == "none"

    def test_query_before_build_is_404(self, client: TestClient) -> None:
        response = client.post("/api/graph/query", json={"url": ROOT, "question": "q"})
        assert response.status_code == 404 and "graph/build" in response.json()["detail"]


class TestInspectExportSync:
    @pytest.fixture(autouse=True)
    def _built(self, client: TestClient) -> None:
        _events(client.post("/api/graph/build", json={"url": ROOT, "provider": FAKE}))

    def test_stats_and_nodes(self, client: TestClient) -> None:
        stats = client.get("/api/graph/stats", params={"url": ROOT}).json()
        assert stats["counts"]["entities"] > 10 and stats["fts"] is True and stats["last_run"]["model"] == "fake-1"
        graph = client.get("/api/graph", params={"url": ROOT, "limit": 50}).json()
        assert len(graph["nodes"]) == min(50, stats["counts"]["entities"])
        node_ids = {n["id"] for n in graph["nodes"]}
        assert graph["edges"] and all(e["source"] in node_ids and e["target"] in node_ids for e in graph["edges"])
        assert {"id", "type", "name", "evidence", "degree"} <= set(graph["nodes"][0])

    def test_entity_detail_carries_quotes_and_anchors(self, client: TestClient) -> None:
        graph = client.get("/api/graph", params={"url": ROOT}).json()
        rao = next(n for n in graph["nodes"] if n["name"] == "Dr. Anita Rao")
        detail = client.get("/api/graph/entity", params={"url": ROOT, "id": rao["id"]}).json()
        assert detail["type"] == "Person" and detail["mentions"]
        mention = detail["mentions"][0]
        assert mention["anchor"] == f"{mention['url']}#{mention['block_xpath']}" and mention["quote"]
        assert client.get("/api/graph/entity", params={"url": ROOT, "id": "ent_nope"}).status_code == 404

    def test_exports_parse(self, client: TestClient) -> None:
        jsonl = client.get("/api/graph/export", params={"url": ROOT, "fmt": "jsonl"})
        rows = [json.loads(line) for line in jsonl.text.splitlines() if line.strip()]
        assert rows[0]["kind"] == "kg" and any(r["kind"] == "relation" for r in rows)
        assert jsonl.headers["content-disposition"].endswith('.kg.jsonl"')
        cypher = client.get("/api/graph/export", params={"url": ROOT, "fmt": "cypher"}).text
        assert "MERGE (e:Entity" in cypher and "RELATED {predicate:" in cypher
        jsonld = client.get("/api/graph/export", params={"url": ROOT, "fmt": "jsonld"}).json()
        assert jsonld["@context"]["prov"] and jsonld["@graph"]
        assert client.get("/api/graph/export", params={"url": ROOT, "fmt": "xml"}).status_code == 422

    def test_sync_without_the_driver_reports_the_extra(self, client: TestClient) -> None:
        events = _events(client.post("/api/graph/sync/neo4j", json={"url": ROOT, "uri": "bolt://127.0.0.1:1", "user": "neo4j", "password": "hunter2"}))
        assert events[-1]["type"] in {"error", "done"}
        if events[-1]["type"] == "error":
            assert "kg-neo4j" in events[-1]["message"] or "bolt" in events[-1]["message"].lower() or "connect" in events[-1]["message"].lower()
        assert "hunter2" not in json.dumps(events)

    def test_delete_drops_the_file(self, client: TestClient) -> None:
        assert client.delete("/api/graph", params={"url": ROOT}).json()["deleted"] is True
        assert client.get("/api/graph/stats", params={"url": ROOT}).status_code == 404
        assert client.delete("/api/graph", params={"url": ROOT}).json()["deleted"] is False

    def test_flag_is_part_of_the_router(self) -> None:
        assert "WEBGRAPH_KG=1" in kg_routes.FLAG_MESSAGE


class TestValidationHandler:
    def test_a_validator_exception_in_ctx_still_renders_a_422(self) -> None:
        # Pydantic puts the raised exception object itself in `ctx` when a field validator
        # raises; a handler that skips `jsonable_encoder` turns that 422 into a 500.
        import asyncio

        from fastapi.exceptions import RequestValidationError

        from webgraph_api.main import _validation_error

        exc = RequestValidationError([
            {"type": "value_error", "loc": ("body", "provider"), "msg": "bad", "input": {"api_key": "sk-secret"}, "ctx": {"error": ValueError("boom")}}
        ])
        response = asyncio.run(_validation_error(None, exc))  # type: ignore[arg-type]
        assert response.status_code == 422
        body = json.loads(response.body)
        assert "error" in body["detail"][0]["ctx"]  # encoded, as FastAPI's own handler would
        assert body["detail"][0]["input"]["api_key"] == "[redacted]"
