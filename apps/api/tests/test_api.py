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
from typing import ClassVar

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
            "article",
            "documentation",
            "service",
            "forum",
            "collection",
            "listing",
            "product",
            "unknown",
        }
        assert 0.0 <= body["page_type_confidence"] <= 1.0

    def test_hidden_text_is_off_by_default_and_on_by_request(
        self, client: TestClient, server: str
    ) -> None:
        """The swatch labels a screen reader announces are not in the default text; a
        caller who wants every string in the DOM asks with `include_hidden_text`."""
        default = client.post("/api/text", json={"url": f"{server}/hidden_labels.html"}).json()
        assert (
            "Option: BILLY" not in default["text"] and "Skip to main content" not in default["text"]
        )
        assert "BILLY bookcase, white" in default["text"]
        full = client.post(
            "/api/text", json={"url": f"{server}/hidden_labels.html", "include_hidden_text": True}
        ).json()
        assert "Option: BILLY, Bookcase, oak effect" in full["text"]
        assert "Skip to main content" in full["text"] and "[edit]" in full["text"]

    def test_the_comment_thread_comes_back_beside_the_content(
        self, client: TestClient, server: str
    ) -> None:
        """An article with a thread under it: the thread is not in `content_markdown` and is
        in `comments_markdown`, in page order."""
        body = client.post("/api/text", json={"url": f"{server}/article_with_comments.html"}).json()
        assert "Reply 0:" not in body["content_markdown"]
        assert "Paragraph 7 of the story" in body["content_markdown"]
        assert body["comments_markdown"].index("Reply 0:") < body["comments_markdown"].index(
            "Reply 5:"
        )
        assert "Paragraph 7" not in body["comments_markdown"]

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
        body = client.post("/api/extract", json={"url": f"{server}/ecommerce_jsonld.html"}).json()
        choice = body["schema_choice"]
        assert choice is not None
        assert choice["page_type"]
        # Below the router's confidence floor the type is `unknown` and there is no schema
        # to offer -- an empty field list is that decision reported, not a failure. Above
        # it, the schema for the type is what the fields are.
        if choice["page_type"] == "unknown":
            assert choice["fields"] == [] and choice["confidence"] < 0.5
        else:
            assert choice["fields"] and choice["confidence"] >= 0.5

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

    def test_a_missing_page_arrives_as_an_error_event(
        self, client: TestClient, server: str
    ) -> None:
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


class TestRefusedAddresses:
    """A private address is refused with a reason the browser can read.

    The streaming endpoint used to let the guard's exception escape before the first byte,
    producing a bare 500 with no CORS headers -- which a browser reports as a network
    failure, and which the web client then described as "Cannot reach the API. Is it
    running?" for a request the API had deliberately refused.
    """

    def test_the_stream_refuses_with_a_403_and_a_reason(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.fetch import guard

        monkeypatch.setattr(guard, "_blocked", True)
        response = client.post(
            "/api/text/stream",
            json={"url": "http://127.0.0.1:8000/api/health"},
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 403
        assert "refused" in response.json()["detail"]
        # The CORS header is the whole point: without it the browser hides the status.
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_the_plain_endpoint_agrees(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.fetch import guard

        monkeypatch.setattr(guard, "_blocked", True)
        response = client.post("/api/text", json={"url": "http://10.0.0.1/"})
        assert response.status_code in (403, 502)
        assert response.json()["detail"]


class TestConfigEndpoint:
    def test_settings_come_from_config_py_with_their_comments(self, client: TestClient) -> None:
        from webgraph import config

        body = client.get("/api/config").json()
        depth = body["settings"]["CRAWL_MAX_DEPTH"]
        assert depth["value"] == config.CRAWL_MAX_DEPTH
        assert "breadth-first" in depth["comment"]
        assert depth["section"].startswith("Crawling")

    def test_it_says_what_a_request_may_override(self, client: TestClient) -> None:
        body = client.get("/api/config").json()
        assert "max_depth" in body["overridable"]["crawl"]
        assert "strict_domain" in body["overridable"]["crawl"]
        assert "timeout_ms" in body["overridable"]["renderOptions"]
        assert "caps" in body


class TestPerRequestOptions:
    def test_crawl_options_are_applied_and_reported(self, client: TestClient, server: str) -> None:
        import json

        with client.stream(
            "POST",
            "/api/site/stream",
            json={
                "url": f"{server}/docs_static.html",
                "max_pages": 1,
                "concurrency": 1,
                "complete": False,
                "crawl": {"max_depth": 2, "strict_domain": False},
            },
        ) as response:
            header = next(
                json.loads(line[len("data: ") :])
                for line in response.iter_lines()
                if line.startswith("data: ") and '"type": "run"' in line
            )
        assert header["max_depth"] == 2
        assert header["strict_domain"] is False

    def test_an_out_of_range_option_is_rejected_before_anything_runs(
        self, client: TestClient, server: str
    ) -> None:
        response = client.post(
            "/api/text/stream",
            json={"url": f"{server}/docs_static.html", "renderOptions": {"timeout_ms": 5}},
        )
        assert response.status_code == 422

    def test_an_unknown_option_is_ignored_not_fatal(self, client: TestClient, server: str) -> None:
        """A newer client sending a field this server does not know should still be served."""
        response = client.post(
            "/api/text",
            json={
                "url": f"{server}/docs_static.html",
                "fetch": {"timeout_seconds": 5, "colour": "red"},
            },
        )
        assert response.status_code == 200


WALL = """<!doctype html><html><head><title>Attention Required! | Cloudflare</title></head>
<body><h1>Sorry, you have been blocked</h1>
<p>You are unable to access example.com</p>
<h2>Why have I been blocked?</h2>
<p>This website is using a security service to protect itself from online attacks. The
action you just performed triggered the security solution. There are several actions that
could trigger this block including submitting a certain word or phrase, a SQL command or
malformed data.</p>
<p>Cloudflare Ray ID: 8c1d2e3f4a5b6c7d</p></body></html>"""


@pytest.fixture
def wall_server(tmp_path: Path) -> Iterator[str]:
    """A site that answers every request with a bot-management block page."""
    (tmp_path / "wall.html").write_text(WALL, encoding="utf-8")
    handler = partial(_QuietHandler, directory=str(tmp_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


class TestWallsOnTheBlockingRoutes:
    """`/api/text` and `/api/extract` used to fetch and parse on their own, without the
    wall checks `resolve_page` runs for the streaming route -- so a Cloudflare block page
    came back as a page of text with a green tick. Both routes now resolve the page the
    same way, and a wall is a refusal."""

    def test_text_refuses_a_block_page(self, client: TestClient, wall_server: str) -> None:
        response = client.post("/api/text", json={"url": f"{wall_server}/wall.html"})
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert "block page" in detail and "you have been blocked" in detail.lower()

    def test_extract_refuses_a_block_page(self, client: TestClient, wall_server: str) -> None:
        response = client.post("/api/extract", json={"url": f"{wall_server}/wall.html"})
        assert response.status_code == 502
        assert "block page" in response.json()["detail"]

    def test_a_real_page_still_reads(self, client: TestClient, server: str) -> None:
        response = client.post("/api/text", json={"url": f"{server}/ecommerce_jsonld.html"})
        assert response.status_code == 200
        assert response.json()["text"]


SUPPLIED_PAGE = """<html><head><title>Behind a wall</title></head><body>
<h1>Behind a wall</h1>
<p>The first paragraph of a page the engine could not fetch, pasted in by a reader who had it
open in their own browser, with <a href="/next">a relative link</a>.</p>
<p>A second paragraph, so the page has some words in it.</p></body></html>"""


class TestSuppliedHtml:
    """Bring your own HTML. Some sites refuse every automated fetch, and the engine does
    not disguise the client to get past them; a caller who already has the page hands its
    HTML over in `html` and gets the same output. The `url` points at a host that does not
    exist, which is the proof that nothing was fetched: on `main` the field is ignored and
    the route tries to fetch it."""

    URL = "http://nope.invalid/page"

    def test_text_reads_the_supplied_html_without_fetching(self, client: TestClient) -> None:
        response = client.post("/api/text", json={"url": self.URL, "html": SUPPLIED_PAGE})
        assert response.status_code == 200, response.text
        body = response.json()
        assert "first paragraph of a page the engine could not fetch" in body["text"]
        assert "# Behind a wall" in body["markdown"]
        # `url` is the base for links, as on a fetched page.
        assert "http://nope.invalid/next" in body["markdown"]
        assert body["page"]["url"] == self.URL
        assert body["page"]["reading_order_measured"] is False

    def test_render_is_ignored_when_html_is_supplied(self, client: TestClient) -> None:
        """There is nothing to render; asking for it must not turn into a fetch."""
        response = client.post(
            "/api/text", json={"url": self.URL, "html": SUPPLIED_PAGE, "render": True}
        )
        assert response.status_code == 200, response.text

    def test_the_stream_reads_it_too(self, client: TestClient) -> None:
        import json

        with client.stream(
            "POST", "/api/text/stream", json={"url": self.URL, "html": SUPPLIED_PAGE}
        ) as response:
            assert response.status_code == 200
            got = [
                json.loads(line[len("data: ") :])
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]
        assert got[0]["type"] == "run"
        assert got[0]["strategy"] == "supplied"
        assert got[0]["supplied"] is True
        assert got[0]["render"] is False
        assert got[1] == {
            "type": "stage",
            "stage": "resolve",
            "state": "running",
            "message": "Reading the HTML supplied by the caller",
        }
        resolve = next(e for e in got if e["type"] == "resolve")
        assert resolve["strategy"] == "supplied"
        assert not [e for e in got if e["type"] == "error"]
        assert got[-1]["type"] == "done"
        assert "first paragraph of a page the engine could not fetch" in got[-1]["text"]

    def test_a_pasted_block_page_is_refused(self, client: TestClient) -> None:
        """Never a false output: the wall a reader pasted is the wall a fetch would have
        been served, and is refused the same way."""
        response = client.post("/api/text", json={"url": self.URL, "html": WALL})
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert "block page" in detail and "you have been blocked" in detail.lower()

    def test_a_pasted_block_page_ends_the_stream_with_an_error(self, client: TestClient) -> None:
        import json

        with client.stream(
            "POST", "/api/text/stream", json={"url": self.URL, "html": WALL}
        ) as response:
            got = [
                json.loads(line[len("data: ") :])
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]
        assert got[-1]["type"] == "error"
        assert "block page" in got[-1]["message"]

    def test_the_url_is_still_required(self, client: TestClient) -> None:
        """Passes on `main` too -- `url` was always required. Kept so the new field is
        seen not to have loosened the schema: without an address the links have no base
        and a login page nothing to be judged against."""
        response = client.post("/api/text", json={"html": SUPPLIED_PAGE})
        assert response.status_code == 422

    def test_the_url_must_still_be_http(self, client: TestClient) -> None:
        response = client.post(
            "/api/text", json={"url": "file:///etc/passwd", "html": SUPPLIED_PAGE}
        )
        assert response.status_code == 422
        response = client.post("/api/text/stream", json={"url": "ftp://x/", "html": SUPPLIED_PAGE})
        assert response.status_code == 422

    def test_oversize_html_is_refused_with_a_reason(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph import config

        monkeypatch.setattr(config, "FETCH_MAX_BYTES", 1_000)
        big = "<html><body><p>" + "words " * 400 + "</p></body></html>"
        response = client.post("/api/text", json={"url": self.URL, "html": big})
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert "over the 1,000-byte limit" in detail
        # No fetch happened, and the detail must not claim one did.
        assert detail.startswith("could not read the supplied HTML")


ROBOTS_CLOSED = "User-agent: *\nDisallow: /\n"
PLAIN_PAGE = (
    "<html><body><h1>An article</h1><p>Enough words here to be a real page of its own, "
    "with a second sentence so the boundary step has something to keep.</p></body></html>"
)


@pytest.fixture
def closed_server(tmp_path: Path) -> Iterator[str]:
    """A site whose robots.txt asks every automated client to stay out."""
    (tmp_path / "robots.txt").write_text(ROBOTS_CLOSED, encoding="utf-8")
    (tmp_path / "article.html").write_text(PLAIN_PAGE, encoding="utf-8")
    handler = partial(_QuietHandler, directory=str(tmp_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


class TestRobotsOnASinglePage:
    """The crawl honoured robots.txt from the start; a single page through `/api/text`
    never did. Now it does, and the caller can say otherwise in so many words."""

    def test_a_disallowed_page_is_refused_with_the_rule(
        self, client: TestClient, closed_server: str
    ) -> None:
        from webgraph.fetch import robots

        robots.forget()
        response = client.post(
            "/api/text",
            json={"url": f"{closed_server}/article.html", "fetch": {"respect_robots": True}},
        )
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert "robots.txt disallows /article.html" in detail
        assert "Disallow: /" in detail
        assert "supply the HTML" in detail

    def test_the_default_reads_it(self, client: TestClient, closed_server: str) -> None:
        """Off by default since 19 Sep 2026: the engine reads what it can reach and the
        caller asks for the site's rules to be obeyed."""
        response = client.post("/api/text", json={"url": f"{closed_server}/article.html"})
        assert response.status_code == 200

    def test_the_caller_can_decline_the_check(self, client: TestClient, closed_server: str) -> None:
        from webgraph.fetch import robots

        robots.forget()
        response = client.post(
            "/api/text",
            json={"url": f"{closed_server}/article.html", "fetch": {"respect_robots": False}},
        )
        assert response.status_code == 200
        assert "An article" in response.json()["text"]


REPORT_ROBOTS = (
    "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nContent-Signal: search=yes, ai-input=yes, ai-train=no\n"
    "Disallow: /wp-admin/\n"
)
REPORT_LLMS = "# Acme College\n\n> A college.\n\n## Pages\n- [About](/about.html): who we are\n"
REPORT_SECURITY = "Contact: mailto:security@acme.test\nExpires: 2027-01-01T00:00:00.000Z\n"
REPORT_INDEX = (
    "<html lang='en'><head><title>Acme College | Home</title>"
    "<meta name='description' content='A college that teaches things.'></head><body>"
    "<h1>Acme College</h1><p>Enough words here to be a page of its own, with a second sentence "
    "so the boundary step has something to keep, and a third for good measure.</p>"
    "<nav><a href='/about.html'>About</a> <a href='/gone.html'>Gone</a></nav>"
    "<div style='position:absolute; left:-20914565266523px'>"
    + "".join(f"<a href='https://spam{i}.example/slot'>casino slot {i}</a> " for i in range(8))
    + "</div></body></html>"
)
REPORT_ABOUT = (
    "<html lang='en'><head><title>About | Acme College</title></head><body><h1>About</h1>"
    "<p>Enough words here to be a page of its own, with a second sentence so the boundary "
    "step has something to keep.</p><a href='/'>Home</a></body></html>"
)


@pytest.fixture
def report_server(tmp_path: Path) -> Iterator[str]:
    """A small site with a robots.txt naming GPTBot and an off-screen block of links to
    eight foreign hosts on its front page."""
    (tmp_path / "robots.txt").write_text(REPORT_ROBOTS, encoding="utf-8")
    (tmp_path / "index.html").write_text(REPORT_INDEX, encoding="utf-8")
    (tmp_path / "about.html").write_text(REPORT_ABOUT, encoding="utf-8")
    (tmp_path / "llms.txt").write_text(REPORT_LLMS, encoding="utf-8")
    (tmp_path / ".well-known").mkdir()
    (tmp_path / ".well-known" / "security.txt").write_text(REPORT_SECURITY, encoding="utf-8")
    handler = partial(_QuietHandler, directory=str(tmp_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


class TestSiteReport:
    def test_the_report_reads_robots_per_bot_and_finds_the_injected_links(
        self, client: TestClient, report_server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph import config
        from webgraph.fetch import robots

        monkeypatch.setattr(config, "REPORT_REQUEST_INTERVAL_SECONDS", 0.0)
        robots.forget()
        response = client.post("/api/site/report", json={"url": f"{report_server}/", "pages": 2})
        assert response.status_code == 200
        body = response.json()
        assert body["reachable"] is True
        # Without a working browser (CI's API job has the Playwright package but no
        # Chromium) the render-dependent parts are rescaled out of the score, and
        # `measured_weight` says so -- that is the contract: 100 with a browser, 75 without.
        assert body["score"]["total"] < 100
        assert body["score"]["measured_weight"] in (75, 100)

        bots = {b["token"]: b for b in body["robots"]["bots"]}
        assert bots["GPTBot"]["access"] == "blocked" and bots["GPTBot"]["via"] == "named"
        assert bots["GPTBot"]["lines"] == ["Disallow: /"]
        # `/wp-admin/` under `*` is housekeeping, not a restriction on reading the site.
        assert bots["ClaudeBot"]["access"] == "allowed" and bots["ClaudeBot"]["via"] == "wildcard"
        assert bots["ClaudeBot"]["disallowed"] == 1 and bots["ClaudeBot"]["content_paths"] == []

        root = body["pages"][0]
        assert root["hidden_links"] == 8
        assert root["hidden_external_hosts"] == 8
        assert root["static_words"] > 0
        # `rendered_words` is 0 wherever no browser could run (CI's API job); with one it
        # is the page's word count. Either is a true report, and the score's
        # `measured_weight` already said which case this is.
        assert root["rendered_words"] > 0 or body["score"]["measured_weight"] == 75
        assert "casino" not in root["title"]
        assert [p["requested_url"] for p in body["pages"]] == [
            f"{report_server}/",
            f"{report_server}/about.html",
        ]
        assert [d["status"] for d in root["dead_links"]] == [404]

        kinds = [f["kind"] for f in body["findings"]]
        assert kinds[0] == "injected_links"
        assert body["findings"][0]["severity"] == "high"

        assert body["suggested_robots_txt"].startswith(REPORT_ROBOTS)
        assert body["suggested_llms_txt"].startswith("# Acme College\n")
        assert "never impersonates" in body["measured"]["statement"]

        # What the site declares to machines, through real HTTP against the local server:
        # the Content-Signal line, the llms.txt (its one link checked), the security.txt,
        # and the well-known files that are not there.
        signals = {s["key"]: s for s in body["signals"]["signals"]}
        assert [g["key"] for g in body["signals"]["groups"]] == [
            "ai",
            "discovery",
            "agents",
            "metadata",
            "trust",
        ]
        assert signals["content_signal"]["present"] is True
        assert signals["content_signal"]["detail"].startswith(
            "search=yes, ai-input=yes, ai-train=no (under User-agent: *)"
        )
        assert signals["content_signal"]["meaning"].startswith(
            "Your robots.txt tells AI systems they may"
        )
        assert (
            signals["llms_txt"]["present"] is True
            and "1 of 1 sampled links answer" in signals["llms_txt"]["detail"]
        )
        assert (
            signals["security_txt"]["present"] is True
            and "Expires: 2027-01-01" in signals["security_txt"]["detail"]
        )
        assert signals["agent_card"]["present"] is False and signals["agent_card"]["status"] == 404
        assert signals["rsl"]["present"] is False and signals["tdm"]["present"] is False
        assert signals["indexnow"]["present"] is None
        assert body["signals"]["requests"] >= 10
        assert body["suggested_security_txt"] is None
        assert (
            "The file already declares: search=yes, ai-input=yes, ai-train=no"
            in body["suggested_robots_txt"]
        )

    def test_a_root_disallowed_for_this_client_is_a_report_with_a_refusal(
        self, client: TestClient, closed_server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph import config
        from webgraph.fetch import robots

        monkeypatch.setattr(config, "REPORT_REQUEST_INTERVAL_SECONDS", 0.0)
        robots.forget()
        response = client.post("/api/site/report", json={"url": f"{closed_server}/article.html"})
        assert response.status_code == 200
        body = response.json()
        assert body["reachable"] is False and body["score"] is None and body["pages"] == []
        assert "robots.txt disallows /article.html for this client" in body["refusal"]

    def test_pages_is_bounded(self, client: TestClient) -> None:
        response = client.post(
            "/api/site/report", json={"url": "https://example.com/", "pages": 500}
        )
        assert response.status_code == 422


SMALL_SITE_PROSE = (
    "The quick brown fox jumped over the lazy dog and continued running through the field "
    "until it reached the far treeline where it finally stopped to rest a while. "
)


def _small_page(name: str) -> str:
    body = "".join(f"<p>{SMALL_SITE_PROSE}Paragraph {name} {i}.</p>" for i in range(5))
    return (
        f"<html><head><title>{name}</title></head><body>"
        '<nav><a href="/">home</a> <a href="/a.html">a</a> <a href="/b.html">b</a> '
        '<a href="/c.html">c</a></nav>'
        f"<main><h1>Page {name}</h1>{body}"
        '<p><a href="/circulars/notice.pdf">Notice (PDF)</a></p></main></body></html>'
    )


class _RecordingHandler(SimpleHTTPRequestHandler):
    """Serves a directory and remembers every path asked for, so a test can prove that a
    file the crawl counted was never requested."""

    requested: ClassVar[list[str]] = []

    def log_message(self, *args: object) -> None:
        return

    def do_GET(self) -> None:
        type(self).requested.append(self.path)
        super().do_GET()


@pytest.fixture
def small_site(tmp_path: Path) -> Iterator[tuple[str, list[str]]]:
    """Four linked pages and a PDF, on a local server that records what was fetched."""
    for name in ("index", "a", "b", "c"):
        (tmp_path / f"{name}.html").write_text(_small_page(name), encoding="utf-8")
    (tmp_path / "circulars").mkdir()
    (tmp_path / "circulars" / "notice.pdf").write_bytes(b"%PDF-1.4 not really")
    requested: list[str] = []
    handler = type("Handler", (_RecordingHandler,), {"requested": requested})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(tmp_path)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/", requested
    finally:
        httpd.shutdown()
        httpd.server_close()


class TestCrawlLimits:
    """A crawl has limits by default (#94): the request exposes them, the header reports
    what was applied, and the `done` event says which one ended the run."""

    @staticmethod
    def stream(client: TestClient, body: dict) -> list[dict]:
        import json

        with client.stream("POST", "/api/site/stream", json=body) as response:
            assert response.status_code == 200
            return [
                json.loads(line[len("data: ") :])
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]

    def test_the_request_defaults_are_the_engines_caps_not_zero(self) -> None:
        from webgraph import config as engine_config

        from webgraph_api.main import CrawlOptions, SiteRequest

        request = SiteRequest(url="https://example.com/")
        assert request.max_pages == engine_config.CRAWL_MAX_PAGES == 500
        assert request.max_seconds == engine_config.CRAWL_MAX_SECONDS == 3600
        assert "fetch_files" in CrawlOptions.model_fields
        assert "max_queue" in CrawlOptions.model_fields
        assert "host_interval_seconds" in CrawlOptions.model_fields

    def test_the_new_knobs_are_overridable_and_reported(self, client: TestClient) -> None:
        overridable = client.get("/api/config").json()["overridable"]["crawl"]
        assert {"fetch_files", "max_queue", "host_interval_seconds"} <= set(overridable)

    def test_done_says_the_page_cap_stopped_it(
        self, client: TestClient, small_site: tuple[str, list[str]]
    ) -> None:
        root, _requested = small_site
        events = self.stream(
            client,
            {
                "url": root,
                "max_pages": 2,
                "max_seconds": 120,
                "concurrency": 1,
                "complete": False,
                "crawl": {"host_interval_seconds": 0, "fetch_files": False, "max_queue": 50},
            },
        )
        header = events[0]
        assert header["type"] == "run"
        assert header["max_seconds"] == 120
        assert header["max_queue"] == 50
        assert header["fetch_files"] is False
        assert header["host_interval_seconds"] == 0
        done = events[-1]
        assert done["type"] == "done"
        assert done["pages_total"] == 2
        assert done["stopped_by"] == "pages"
        assert done["exhausted"] is False
        assert done["limits"] == {"max_pages": 2, "max_seconds": 120, "max_queue": 50, "max_depth": 12}

    def test_a_pdf_is_counted_and_cited_and_never_requested(
        self, client: TestClient, small_site: tuple[str, list[str]]
    ) -> None:
        root, requested = small_site
        events = self.stream(
            client,
            {
                "url": root,
                "max_pages": 0,
                "concurrency": 1,
                "complete": False,
                "crawl": {"host_interval_seconds": 0},
            },
        )
        done = events[-1]
        assert done["type"] == "done"
        assert done["stopped_by"] is None
        assert done["exhausted"] is True
        assert done["pages_ok"] == 4
        assert done["failed"] == 0
        assert done["skipped"]["pdf"] == 1
        [entry] = done["skipped_urls"]
        assert entry["url"] == f"{root}circulars/notice.pdf"
        assert entry["found_on"] == root
        assert entry["anchor"] == "Notice (PDF)"
        assert "/circulars/notice.pdf" not in requested, "the crawl fetched a PDF it would refuse"


def _watch_page(title: str, body: str, links: tuple[str, ...]) -> str:
    nav = "".join(f'<a href="{href}">{href}</a> ' for href in links)
    return (
        f"<html><head><title>{title}</title></head><body><nav>{nav}</nav>"
        f"<main>{body}</main><footer><p>Visitors: 1,204,551</p></footer></body></html>"
    )


WATCH_V1 = {
    "index.html": _watch_page(
        "College",
        f"<h1>Welcome</h1><p>{SMALL_SITE_PROSE}</p><p>Last updated: 12 Sep 2026</p>",
        ("/", "/notices.html"),
    ),
    "notices.html": _watch_page(
        "Notices",
        f"<h1>Notices</h1><p>{SMALL_SITE_PROSE}</p><h2>2026</h2><ul><li>Fee notification for the odd semester.</li></ul>",
        ("/", "/notices.html"),
    ),
}
WATCH_V2 = {
    "index.html": _watch_page(
        "College",
        f"<h1>Welcome</h1><p>{SMALL_SITE_PROSE}</p><p>Last updated: 13 Sep 2026</p>",
        ("/", "/notices.html"),
    ),
    "notices.html": _watch_page(
        "Notices",
        f"<h1>Notices</h1><p>{SMALL_SITE_PROSE}</p><h2>2026</h2><ul><li>Fee notification for the odd semester.</li>"
        "<li>Revised timetable for the laboratory sessions.</li></ul>",
        ("/", "/notices.html"),
    ),
}


@pytest.fixture
def watched_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Path]]:
    """A two-page site whose files the test rewrites between runs, and a temporary watch
    database. No browser: the analysis is told Playwright is absent."""
    from webgraph.fetch import robots

    import webgraph_api.main as api

    monkeypatch.setattr("webgraph.analyze.PLAYWRIGHT_AVAILABLE", False)
    monkeypatch.setattr(api, "WATCH_DB", tmp_path / "watch.sqlite3")
    robots.forget()
    root = tmp_path / "site"
    root.mkdir()
    for name, html in WATCH_V1.items():
        (root / name).write_text(html, encoding="utf-8")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(root)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/", root
    finally:
        httpd.shutdown()
        httpd.server_close()


class TestWatch:
    """`/api/watch`: create, run (SSE with `change` events), changes, feed."""

    WATCH_CONFIG: ClassVar[dict[str, object]] = {
        "complete": False,
        "concurrency": 1,
        "delay_seconds": 0,
        "host_interval_seconds": 0,
        "max_pages": 10,
    }

    @staticmethod
    def run(client: TestClient, watch_id: str) -> list[dict]:
        import json

        with client.stream("POST", f"/api/watch/{watch_id}/run") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            return [
                json.loads(line[len("data: ") :])
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]

    def test_create_lists_and_refuses_bad_input(
        self, client: TestClient, watched_site: tuple[str, Path]
    ) -> None:
        root, _ = watched_site
        created = client.post(
            "/api/watch", json={"url": root, "config": self.WATCH_CONFIG, "schedule_seconds": 3600}
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["root"] == root and len(body["id"]) == 12
        assert body["schedule_seconds"] == 3600 and body["runs"] == 0
        assert client.get(f"/api/watch/{body['id']}").json()["id"] == body["id"]
        assert [w["id"] for w in client.get("/api/watch").json()] == [body["id"]]
        assert client.post("/api/watch", json={"url": "ftp://x"}).status_code == 422
        assert (
            client.post(
                "/api/watch", json={"url": root, "config": {"strategy": "guess"}}
            ).status_code
            == 422
        )
        assert client.get("/api/watch/nope").status_code == 404
        assert client.post("/api/watch/nope/run").status_code == 404

    def test_a_run_streams_changes_and_done_carries_the_summary(
        self, client: TestClient, watched_site: tuple[str, Path]
    ) -> None:
        root, directory = watched_site
        watch_id = client.post(
            "/api/watch", json={"url": root, "config": self.WATCH_CONFIG}
        ).json()["id"]

        first = self.run(client, watch_id)
        assert (
            first[0]["type"] == "run"
            and first[0]["mode"] == "watch"
            and first[0]["watch_id"] == watch_id
        )
        assert first[1]["type"] == "watch" and first[1]["baseline"] is True
        assert first[-1]["type"] == "done" and first[-1]["baseline"] is True
        assert first[-1]["pages_ok"] == 2
        assert not any(e["type"] == "change" for e in first)

        for name, html in WATCH_V2.items():
            (directory / name).write_text(html, encoding="utf-8")
        second = self.run(client, watch_id)
        done = second[-1]
        assert done["type"] == "done"
        assert done["changes"] == {"added": 0, "removed": 0, "changed": 1}
        assert done["suppressed"] == 1, "the bumped 'last updated' line is not a change"
        assert done["stopped_by"] is None
        [change] = [e for e in second if e["type"] == "change"]
        assert change["url"] == f"{root}notices.html"
        assert change["kind"] == "changed"
        assert change["sections"][0]["heading"] == "2026"
        assert "Revised timetable" in change["sections"][0]["after"]

        listed = client.get(f"/api/watch/{watch_id}/changes").json()
        assert listed["watch"]["runs"] == 2 and listed["watch"]["changes"] == 1
        assert [c["url"] for c in listed["changes"]] == [f"{root}notices.html"]
        assert (
            client.get(f"/api/watch/{watch_id}/changes", params={"since": "2099-01-01"}).json()[
                "changes"
            ]
            == []
        )
        assert (
            client.get(f"/api/watch/{watch_id}/changes", params={"since": "yesterday"}).status_code
            == 422
        )

    def test_the_feed_is_rss_or_atom_and_well_formed(
        self, client: TestClient, watched_site: tuple[str, Path]
    ) -> None:
        from xml.etree import ElementTree as ET

        root, directory = watched_site
        watch_id = client.post(
            "/api/watch", json={"url": root, "config": self.WATCH_CONFIG}
        ).json()["id"]
        self.run(client, watch_id)
        for name, html in WATCH_V2.items():
            (directory / name).write_text(html, encoding="utf-8")
        self.run(client, watch_id)

        rss = client.get(f"/api/watch/{watch_id}/feed.xml")
        assert rss.status_code == 200
        assert rss.headers["content-type"].startswith("application/rss+xml")
        tree = ET.fromstring(rss.text)
        assert tree.tag == "rss"
        [item] = tree.findall("channel/item")
        assert item.findtext("link") == f"{root}notices.html"
        assert "2026" in (item.findtext("title") or "")

        atom = client.get(f"/api/watch/{watch_id}/feed.xml", params={"format": "atom"})
        assert atom.headers["content-type"].startswith("application/atom+xml")
        ns = {"a": "http://www.w3.org/2005/Atom"}
        feed = ET.fromstring(atom.text)
        assert feed.find("a:link[@rel='self']", ns) is not None
        assert len(feed.findall("a:entry", ns)) == 1
        assert (
            client.get(f"/api/watch/{watch_id}/feed.xml", params={"format": "pdf"}).status_code
            == 422
        )

    def test_the_hosts_page_cap_applies_to_a_watch(
        self, client: TestClient, watched_site: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import webgraph_api.main as api

        root, _ = watched_site
        monkeypatch.setattr(api, "PAGE_CAP", 1)
        watch_id = client.post(
            "/api/watch", json={"url": root, "config": self.WATCH_CONFIG}
        ).json()["id"]
        events = self.run(client, watch_id)
        assert events[0]["max_pages"] == 1
        assert events[-1]["pages_total"] == 1
        assert events[-1]["stopped_by"] == "pages"
