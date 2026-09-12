"""How this client speaks HTTP, and why each part of it is there.

Every assertion here traces to a measurement on Firecrawl's scrape-evals corpus, 1,000 live
URLs fetched on 2026-09-12, of which 143 answered 403 and 9 answered 429. The experiment that
produced these choices is recorded in `webgraph.fetch.static`'s docstring; these tests pin the
result so a well-meaning simplification cannot quietly undo it.
"""

from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from typing import ClassVar

import pytest

from webgraph.fetch.static import (
    DEFAULT_USER_AGENT,
    MAX_RETRY_WAIT_SECONDS,
    RETRY_STATUSES,
    FetchConfig,
    _headers,
    fetch_static,
)

BODY = b"<html><body><p>Served.</p></body></html>"


class Recorder(http.server.BaseHTTPRequestHandler):
    """Answers a scripted sequence of statuses and records what it was sent."""

    # Class-level on purpose: BaseHTTPRequestHandler is instantiated per request, so a
    # per-instance script could never span the two attempts a retry test needs to observe.
    script: ClassVar[list[tuple[int, dict[str, str]]]] = []
    seen: ClassVar[list[dict[str, str]]] = []

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        Recorder.seen.append({k.lower(): v for k, v in self.headers.items()})
        status, extra = (
            Recorder.script.pop(0) if Recorder.script else (200, {})
        )
        self.send_response(status)
        for key, value in extra.items():
            self.send_header(key, value)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)


@pytest.fixture
def server() -> Iterator[str]:
    Recorder.script = []
    Recorder.seen = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()
    httpd.server_close()


class TestUserAgent:
    def test_it_is_browser_shaped_and_still_names_the_crawler(self) -> None:
        """Both halves were measured. Of 143 URLs that refused this client, a bot-only string
        recovered 2 and a browser-shaped string carrying this suffix recovered 16. The suffix
        costs 17 further pages that a bare Chrome string would have taken, and keeps the
        crawler something a site owner can identify and contact."""
        assert DEFAULT_USER_AGENT.startswith("Mozilla/5.0")
        assert "Chrome/" in DEFAULT_USER_AGENT
        assert "webgraph/" in DEFAULT_USER_AGENT
        assert "github.com/webgraph" in DEFAULT_USER_AGENT

    def test_a_caller_can_override_it(self) -> None:
        sent = _headers(FetchConfig(user_agent="agreed-with-the-site/1.0"))
        assert sent["User-Agent"] == "agreed-with-the-site/1.0"


class TestHeaders:
    def test_a_navigation_looks_like_a_navigation(self) -> None:
        """`Sec-Fetch-Mode: navigate` is what says "a person opened a page". Without these a
        request is visibly a script asking for a document, and several CDNs answer it
        differently."""
        sent = _headers(FetchConfig())
        assert sent["Sec-Fetch-Mode"] == "navigate"
        assert sent["Sec-Fetch-Dest"] == "document"
        assert sent["Upgrade-Insecure-Requests"] == "1"

    def test_brotli_is_accepted(self) -> None:
        """Declining brotli cost bandwidth and marked the client. httpx decodes it."""
        assert "br" in _headers(FetchConfig())["Accept-Encoding"]

    def test_the_accept_header_is_a_browsers(self) -> None:
        """Four corpus URLs answered `406 Not Acceptable` to the previous one."""
        accept = _headers(FetchConfig())["Accept"]
        assert "image/webp" in accept
        assert accept.startswith("text/html")

    def test_extra_headers_win(self) -> None:
        sent = _headers(FetchConfig(extra_headers={"Accept-Language": "de-DE"}))
        assert sent["Accept-Language"] == "de-DE"

    def test_they_reach_the_server(self, server: str) -> None:
        fetch_static(server)
        assert Recorder.seen[0]["sec-fetch-mode"] == "navigate"
        assert "webgraph/" in Recorder.seen[0]["user-agent"]


class TestRetry:
    def test_a_429_is_retried_once(self, server: str) -> None:
        """Nine corpus URLs answered 429 and were recorded as failures with no second attempt
        ever made. That is a bug in the client, not a property of the web."""
        Recorder.script = [(429, {"Retry-After": "0"})]
        result = fetch_static(server)
        assert result.ok
        assert len(Recorder.seen) == 2

    def test_a_long_retry_after_is_not_waited_out(self, server: str) -> None:
        """A server asking for a minute is asking to be crawled later, not to have a thread
        held open for it."""
        Recorder.script = [(429, {"Retry-After": "600"})]
        result = fetch_static(server)
        assert not result.ok
        assert result.status == 429
        assert len(Recorder.seen) == 1
        assert MAX_RETRY_WAIT_SECONDS <= 30

    def test_a_403_is_not_retried(self, server: str) -> None:
        """A refusal is a decision. Asking again is just a second request nobody wanted."""
        Recorder.script = [(403, {})]
        result = fetch_static(server)
        assert not result.ok
        assert len(Recorder.seen) == 1

    def test_retries_can_be_turned_off(self, server: str) -> None:
        Recorder.script = [(429, {"Retry-After": "0"})]
        result = fetch_static(server, config=FetchConfig(retries=0))
        assert not result.ok
        assert len(Recorder.seen) == 1

    def test_the_retryable_set_is_transient_statuses_only(self) -> None:
        assert {429, 503} == RETRY_STATUSES
        assert 403 not in RETRY_STATUSES
        assert 404 not in RETRY_STATUSES


class TestProtocol:
    def test_http2_is_on_by_default(self) -> None:
        assert FetchConfig().http2 is True

    def test_a_plain_http_server_still_works(self, server: str) -> None:
        """HTTP/2 is negotiated, not required: h2c is not a thing httpx does over cleartext,
        so an HTTP/1.1 server must still answer normally."""
        result = fetch_static(server)
        assert result.ok
        assert "Served." in result.html
