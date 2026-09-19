"""Single-page extraction as a sequence of stages, including when it goes wrong.

A streaming view that drifts from the batch one is worse than no streaming view, because it
is believed. So these tests pin two things: that the events describe what actually happened,
and that a failure is an ordinary event rather than an exception escaping into a half-written
response.
"""

from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest

from webgraph.page import stream_page
from webgraph.resolve import Strategy

ARTICLE = b"""<html><head><title>T</title>
<script type="application/ld+json">{"@type":"BlogPosting","headline":"A title"}</script>
</head><body><nav><a href="/">Home</a><a href="/a">About</a></nav>
<main><h1>A title</h1>
<p>The first paragraph of a real article, long enough to look like prose to any selector.</p>
<p>A second paragraph, also long enough that nothing here reads as navigation or chrome.</p>
<table><tr><th>City</th><th>People</th></tr><tr><td>Leeds</td><td>793000</td></tr></table>
</main><footer><a href="/t">Terms</a></footer></body></html>"""


class Server(http.server.BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, tuple[int, bytes]]] = {}

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        status, body = Server.routes.get(self.path, (404, b"<html><body>no</body></html>"))
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server() -> Iterator[str]:
    Server.routes = {
        "/article": (200, ARTICLE),
        "/gone": (404, b"<html><body><h1>Not Found</h1></body></html>"),
        "/broken": (500, b"<html><body>server error</body></html>"),
        "/empty": (200, b""),
    }
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def events(url: str) -> list[dict[str, Any]]:
    # STATIC_ONLY because a test must not depend on a browser being installed; the stage
    # sequence is the same either way, which is the thing under test.
    return list(stream_page(url, strategy=Strategy.STATIC_ONLY))


class TestTheHappyPath:
    def test_the_stages_arrive_in_order_and_end_with_done(self, server: str) -> None:
        stages = [e["stage"] for e in events(f"{server}/article")]
        assert stages[-1] == "done"
        # Each stage appears, and never after the one that follows it.
        for earlier, later in (("resolve", "parse"), ("parse", "classify"), ("classify", "select")):
            assert stages.index(earlier) < stages.index(later)

    def test_resolve_reports_what_each_fetch_contributed(self, server: str) -> None:
        resolve = next(e for e in events(f"{server}/article") if e["type"] == "resolve")
        assert resolve["static_chars"] > 0
        assert resolve["union_chars"] > 0
        assert 0.0 <= resolve["static_coverage"] <= 1.0

    def test_parse_reports_the_document_it_actually_built(self, server: str) -> None:
        parse = next(e for e in events(f"{server}/article") if e["type"] == "parse")
        assert parse["blocks"] > 0
        assert parse["words"] > 0
        assert parse["kinds"].get("paragraph", 0) >= 2
        assert "json-ld" in parse["payloads"]

    def test_select_accounts_for_every_block(self, server: str) -> None:
        select = next(e for e in events(f"{server}/article") if e["type"] == "select")
        assert select["kept"] + sum(select["removed"].values()) == select["total"]

    def test_done_carries_the_finished_document(self, server: str) -> None:
        done = next(e for e in events(f"{server}/article") if e["type"] == "done")
        assert "first paragraph" in done["text"]
        assert done["markdown"].strip()
        assert done["title"] == "A title"

    def test_content_is_empty_when_nothing_was_removed(self) -> None:
        """Emitting the content twice to say "identical" would double the payload."""
        from webgraph.content import select_content
        from webgraph.pipeline import build_document

        blocks = build_document(
            "<html><body><p>Only this.</p></body></html>", "https://x.test/"
        ).blocks
        assert not select_content(blocks).changed


class TestWhenItGoesWrong:
    """Every failure is an event. None of them is an exception reaching the caller."""

    def test_a_404_ends_the_stream_with_an_error(self, server: str) -> None:
        got = events(f"{server}/gone")
        assert got[-1]["type"] == "error"
        assert got[-1]["stage"] == "resolve"
        assert not any(e["type"] == "done" for e in got)

    def test_a_500_does_not_become_a_document(self, server: str) -> None:
        """A server error page renders perfectly well and must not be extracted as content."""
        got = events(f"{server}/broken")
        assert got[-1]["type"] == "error"

    def test_an_empty_body_is_an_error_not_an_empty_success(self, server: str) -> None:
        got = events(f"{server}/empty")
        assert got[-1]["type"] == "error"

    def test_an_unreachable_host_is_reported_not_raised(self) -> None:
        got = events("http://127.0.0.1:9/nothing")
        assert got[-1]["type"] == "error"
        assert got[-1]["message"]

    def test_a_refused_scheme_never_reaches_the_network(self) -> None:
        got = events("file:///etc/passwd")
        assert got[-1]["type"] == "error"

    def test_an_error_carries_an_elapsed_time(self, server: str) -> None:
        """A failure that took nine seconds and one that took nine milliseconds are different
        problems, and the caller can only tell them apart if the event says so."""
        got = events(f"{server}/gone")
        assert got[-1]["at"] >= 0.0


class TestTheClassifier:
    def test_it_reports_whether_a_model_was_available(self, server: str) -> None:
        """A page typed `unknown` because no model shipped and one typed `unknown` because
        the model declined are different facts."""
        classify = next(e for e in events(f"{server}/article") if e["type"] == "classify")
        assert isinstance(classify["available"], bool)

    def test_a_confident_type_comes_with_its_reasons(self, server: str) -> None:
        classify = next(e for e in events(f"{server}/article") if e["type"] == "classify")
        if classify["page_type"] != "unknown":
            assert classify["reasons"]
            assert all(0.0 < r["weight"] <= 1.0 for r in classify["reasons"])
            assert classify["runner_up"]["type"] != classify["page_type"]
