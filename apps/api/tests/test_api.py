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
        # React is implied by Next.js rather than detected: a Next.js build exposes
        # `__NEXT_DATA__` and nothing that names React directly.
        assert body["page"]["frameworks"] == ["next.js", "React"]

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

    def test_the_page_type_is_reported(self, client: TestClient, server: str) -> None:
        """The router labels the page; it does not change what is extracted from it."""
        body = client.post("/api/text", json={"url": f"{server}/ecommerce_jsonld.html"}).json()
        assert body["page_type"] in {
            "article", "documentation", "service", "forum",
            "collection", "listing", "product", "unknown",
        }
        assert 0.0 <= body["page_type_confidence"] <= 1.0

    def test_content_selection_names_the_step_that_drew_the_line(
        self, client: TestClient, server: str
    ) -> None:
        body = client.post("/api/text", json={"url": f"{server}/docs_static.html"}).json()
        methods = body["content_methods"]
        assert "main-content" not in methods or "block-model" not in methods
        if methods:
            assert body["content_blocks"] <= body["page"]["blocks"]


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

    def test_a_missing_url_is_still_rejected(self, client: TestClient) -> None:
        assert client.post("/api/extract", json={}).status_code == 422


class TestAutoSchema:
    """Extraction with no schema supplied: the engine picks one from the page type.

    The schema is only half of it. The other half is which structured-data node gets read --
    a product page from a WordPress shop ships `Organization`, `WebSite`, `WebPage`,
    `BreadcrumbList` and `Product`, all with a `name`, and reading them all reports the
    shop's name as the product's on a measured 15% of product pages and 46% of category
    pages.
    """

    def test_no_schema_means_the_engine_chooses_one(self, client: TestClient, server: str) -> None:
        body = client.post(
            "/api/extract", json={"url": f"{server}/ecommerce_jsonld.html"}
        ).json()
        assert body["schema_choice"] is not None
        assert body["schema_choice"]["page_type"]
        assert body["schema_choice"]["fields"]

    def test_the_choice_says_which_nodes_it_read(self, client: TestClient, server: str) -> None:
        """A caller who did not write the schema is owed the reasoning: "no price" means
        something different when the page was typed as an article."""
        choice = client.post(
            "/api/extract", json={"url": f"{server}/ecommerce_jsonld.html"}
        ).json()["schema_choice"]
        assert choice["payloads_considered"] >= choice["payloads_used"]
        if choice["payloads_used"]:
            assert choice["subject_types"]

    def test_a_supplied_schema_is_left_alone(self, client: TestClient, server: str) -> None:
        """The gate narrows payloads only when the engine chose the vocabulary. A caller
        asking for the site's `Organization` by hand may mean exactly that."""
        body = client.post(
            "/api/extract",
            json={
                "url": f"{server}/ecommerce_jsonld.html",
                "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        ).json()
        assert body["schema_choice"] is None

    def test_a_malformed_schema_is_still_rejected(self, client: TestClient, server: str) -> None:
        """Omitting the schema is now a request; sending a broken one is still an error."""
        response = client.post(
            "/api/extract", json={"url": f"{server}/docs_static.html", "schema": {"type": "object"}}
        )
        assert response.status_code == 422


class TestTextStream:
    """The streaming single-page endpoint.

    Once the first byte is sent an HTTP status can no longer say anything, so a failure has
    to arrive as an event. These check that it does, rather than escaping as a 500 halfway
    through a response nobody can parse.
    """

    @staticmethod
    def events(client: TestClient, url: str) -> list[dict]:
        import json

        with client.stream("POST", "/api/text/stream", json={"url": url}) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            return [
                json.loads(line[len("data: ") :])
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]

    def test_a_real_page_streams_stages_then_done(self, client: TestClient, server: str) -> None:
        got = self.events(client, f"{server}/docs_static.html")
        assert got[-1]["type"] == "done"
        stages = [event.get("stage") for event in got]
        for stage in ("resolve", "parse", "classify", "select"):
            assert stage in stages

    def test_the_done_event_carries_the_page(self, client: TestClient, server: str) -> None:
        done = self.events(client, f"{server}/docs_static.html")[-1]
        assert "Configuring retries" in done["text"]
        assert done["markdown"]

    def test_a_missing_page_arrives_as_an_error_event(self, client: TestClient, server: str) -> None:
        got = self.events(client, f"{server}/absent.html")
        assert got[-1]["type"] == "error"
        assert got[-1]["message"]
        assert not any(event["type"] == "done" for event in got)

    def test_an_unreachable_host_arrives_as_an_error_event(self, client: TestClient) -> None:
        got = self.events(client, "http://127.0.0.1:9/nope")
        assert got[-1]["type"] == "error"

    def test_a_refused_scheme_is_rejected_before_streaming_starts(self, client: TestClient) -> None:
        """This one *can* be a status code: nothing has been sent yet."""
        response = client.post("/api/text/stream", json={"url": "file:///etc/passwd"})
        assert response.status_code in (400, 422)

    def test_the_classifier_reports_whether_it_was_available(
        self, client: TestClient, server: str
    ) -> None:
        classify = next(
            event
            for event in self.events(client, f"{server}/docs_static.html")
            if event["type"] == "classify"
        )
        assert isinstance(classify["available"], bool)
        assert 0.0 <= classify["confidence"] <= 1.0


class TestRunHeader:
    """The first frame of a stream, and the file it names.

    This is the join between what a reader copies out of the browser and what the server
    kept. If the two cannot be put side by side, neither is evidence of anything.
    """

    @staticmethod
    def stream(client: TestClient, url: str) -> list[dict]:
        import json

        with client.stream("POST", "/api/text/stream", json={"url": url}) as response:
            return [
                json.loads(line[len("data: ") :])
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]

    def test_the_first_frame_names_the_run_and_its_trace(
        self, client: TestClient, server: str
    ) -> None:
        first = self.stream(client, f"{server}/docs_static.html")[0]
        assert first["type"] == "run"
        assert first["run"] and first["trace"]
        assert first["url"].endswith("/docs_static.html")
        assert first["mode"] == "page"
        assert first["engine"]

    def test_the_trace_is_named_not_located(self, client: TestClient, server: str) -> None:
        """A file name is useful to whoever has the server; a path is the server's business.

        Also keeps a copied log from carrying a temp directory into a bug report.
        """
        first = self.stream(client, f"{server}/docs_static.html")[0]
        assert "/" not in first["trace"] and "\\" not in first["trace"]
        assert first["run"] in first["trace"]

    def test_a_failed_run_still_gets_a_header(self, client: TestClient, server: str) -> None:
        """The run that went wrong is the one whose id someone will need."""
        got = self.stream(client, f"{server}/absent.html")
        assert got[0]["type"] == "run"
        assert got[-1]["type"] == "error"

    def test_two_runs_of_the_same_page_get_separate_traces(
        self, client: TestClient, server: str
    ) -> None:
        """Host plus a second-granularity timestamp is not unique.

        Two tabs pointed at one site within the same second used to open the same path in
        "w" mode, and the second silently erased the first.
        """
        one = self.stream(client, f"{server}/docs_static.html")[0]
        two = self.stream(client, f"{server}/docs_static.html")[0]
        assert one["run"] != two["run"]
        assert one["trace"] != two["trace"]

    def test_the_trace_file_records_the_run_and_its_failure(
        self, client: TestClient, server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What is on disk is the same run, ending with the reason it ended.

        A trace closed by the tracer's own `finally` would be shut before the handler's
        `except` ran, and the failure -- the single line worth keeping -- would be the one
        line missing.
        """
        import json

        import webgraph_api.main as api

        monkeypatch.setattr(api, "TRACE_DIR", tmp_path)
        header = self.stream(client, f"{server}/absent.html")[0]

        written = tmp_path / header["trace"]
        records = [json.loads(line) for line in written.read_text(encoding="utf-8").splitlines()]
        assert records[0]["type"] == "run" and records[0]["seq"] == 1
        assert all(record["run"] == header["run"] for record in records)
        assert any(record["type"] == "error" for record in records)
        assert records[-1]["type"] == "trace-closed"

    def test_an_unwritable_trace_directory_does_not_fail_the_run(
        self, client: TestClient, server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Observability that can take the product down is not observability.

        The header is still emitted: the run id is real whether or not anything could be
        written under it, and a client that branched on its absence would break here.
        """
        import webgraph_api.main as api

        blocked = tmp_path / "not-a-directory"
        blocked.write_text("", encoding="utf-8")
        monkeypatch.setattr(api, "TRACE_DIR", blocked / "runs")

        got = self.stream(client, f"{server}/docs_static.html")
        assert got[0]["type"] == "run" and got[0]["run"]
        assert got[-1]["type"] == "done"

    def test_the_site_header_reports_the_caps_that_were_applied(
        self, client: TestClient, server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asking for 500 pages on a host capped at 3 is a run of 3, and the log says 3."""
        import json

        import webgraph_api.main as api

        monkeypatch.setattr(api, "PAGE_CAP", 3)
        with client.stream(
            "POST",
            "/api/site/stream",
            json={"url": f"{server}/docs_static.html", "max_pages": 500, "concurrency": 2},
        ) as response:
            first = next(
                json.loads(line[len("data: ") :])
                for line in response.iter_lines()
                if line.startswith("data: ") and '"run"' in line
            )
        assert first["type"] == "run"
        assert first["mode"] == "site"
        assert first["max_pages"] == 3
