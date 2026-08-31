"""API tests against a real local HTTP server.

A stubbed fetch would test the handler but not the pipeline it wraps. Serving the benchmark
snapshots over real HTTP exercises fetch, parse, profile and extract exactly as production
would, while staying hermetic -- nothing here reaches the public internet.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webgraph_api.main import app

PAGES = Path(__file__).resolve().parents[3] / "benchmark" / "corpus-v0" / "pages"

PRODUCT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "sku": {"type": "string"},
        "offers": {
            "type": "object",
            "properties": {"price": {"type": "number"}, "currency": {"type": "string"}},
        },
    },
}


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    handler = partial(_QuietHandler, directory=str(PAGES))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


class TestHealth:
    def test_reports_status_and_capability(self, client: TestClient) -> None:
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert isinstance(body["render_available"], bool)
        assert body["max_concurrent_renders"] >= 1


class TestExtract:
    def test_extracts_json_ld_product(self, client: TestClient, server: str) -> None:
        response = client.post(
            "/api/extract",
            json={"url": f"{server}/ecommerce_jsonld.html", "schema": PRODUCT_SCHEMA},
        )
        assert response.status_code == 200
        body = response.json()

        assert body["facts"]["name"]["value"] == "Aurora Desk Lamp"
        assert body["facts"]["offers.price"]["value"] == 129.0
        assert body["facts"]["offers.currency"]["value"] == "GBP"

    def test_every_fact_carries_provenance(self, client: TestClient, server: str) -> None:
        """A value without a source cannot be checked by whoever consumes it."""
        body = client.post(
            "/api/extract",
            json={"url": f"{server}/ecommerce_jsonld.html", "schema": PRODUCT_SCHEMA},
        ).json()

        for fact in body["facts"].values():
            assert fact["extractor"] == "structured-data"
            assert fact["modality"] == "dom-json"
            assert 0.0 < fact["confidence"] <= 1.0
            assert fact["source"]

    def test_page_metadata_included(self, client: TestClient, server: str) -> None:
        body = client.post(
            "/api/extract",
            json={"url": f"{server}/ecommerce_jsonld.html", "schema": PRODUCT_SCHEMA},
        ).json()

        page = body["page"]
        assert page["payloads"] == ["json-ld"]
        assert page["content_hash"]
        assert page["reading_order_measured"] is False

    def test_hydration_payload_page(self, client: TestClient, server: str) -> None:
        schema = {
            "type": "object",
            "properties": {"title": {"type": "string"}, "price": {"type": "number"}},
        }
        body = client.post(
            "/api/extract", json={"url": f"{server}/nextjs_hydration.html", "schema": schema}
        ).json()

        assert body["facts"]["title"]["value"] == "Systems Design Intensive"
        assert body["page"]["frameworks"] == ["next.js"]

    def test_page_without_structured_data_returns_no_facts(
        self, client: TestClient, server: str
    ) -> None:
        """An empty result, not an error -- and crucially not an invented value."""
        response = client.post(
            "/api/extract", json={"url": f"{server}/docs_static.html", "schema": PRODUCT_SCHEMA}
        )
        assert response.status_code == 200
        assert response.json()["facts"] == {}


class TestText:
    def test_returns_reading_ordered_text(self, client: TestClient, server: str) -> None:
        body = client.post("/api/text", json={"url": f"{server}/docs_static.html"}).json()
        assert "Configuring retries" in body["text"]
        assert body["page"]["reading_order"] == "dom-fallback"

    def test_script_content_excluded(self, client: TestClient, server: str) -> None:
        body = client.post("/api/text", json={"url": f"{server}/ecommerce_jsonld.html"}).json()
        assert "ld+json" not in body["text"]
        assert "@context" not in body["text"]


class TestErrorHandling:
    def test_unreachable_host_is_502(self, client: TestClient) -> None:
        response = client.post("/api/text", json={"url": "http://127.0.0.1:9/nope"})
        assert response.status_code == 502
        assert "could not fetch" in response.json()["detail"]

    def test_missing_page_is_502(self, client: TestClient, server: str) -> None:
        response = client.post("/api/text", json={"url": f"{server}/absent.html"})
        assert response.status_code == 502

    def test_non_http_scheme_rejected(self, client: TestClient) -> None:
        response = client.post("/api/text", json={"url": "file:///etc/passwd"})
        assert response.status_code == 422

    def test_schema_without_properties_rejected(self, client: TestClient, server: str) -> None:
        response = client.post(
            "/api/extract",
            json={"url": f"{server}/ecommerce_jsonld.html", "schema": {"type": "object"}},
        )
        assert response.status_code == 422

    def test_missing_body_field_rejected(self, client: TestClient) -> None:
        assert client.post("/api/extract", json={"url": "https://example.com"}).status_code == 422
