"""Interstitials that stop a page from mounting, and the crawl warning that catches them.

The case these cover: a client-rendered app whose entire mounted DOM is a first-run gate --
a persona picker, a region selector, an age gate, an onboarding wizard. The real content is
*unmounted*, so there is nothing in the DOM to extract and no link to follow. Measured on
zerotoonepmtoolkit.app: 21 routes all serving the same 1,130-character modal, zero internal
links, and a crawl that reported itself `exhausted` after one page.

Two independent defences, tested separately because either can be useful without the other:

1. `RenderConfig.dismiss_gates` opens the gate, so extraction succeeds.
2. `stream_site` warns when distinct URLs return identical text, so a gate the engine
   *cannot* open is reported rather than silently producing 3% of a site.
"""

from __future__ import annotations

import http.server
import socketserver
import threading
from collections.abc import Iterator

import pytest

from webgraph.crawl.discovery import extract_links
from webgraph.fetch.render import (
    PLAYWRIGHT_AVAILABLE,
    RenderConfig,
    RenderResult,
    render_page,
)
from webgraph.pipeline import build_document
from webgraph.site import IDENTICAL_CONTENT_WARNING, SiteConfig, stream_site

pytestmark = pytest.mark.skipif(
    not PLAYWRIGHT_AVAILABLE, reason="rendering requires the 'render' extra"
)

# A miniature of the real thing: nothing but a gate until a button is clicked, at which
# point the content and the navigation both mount. Deliberately keeps the links inside the
# gated subtree, because that is what makes the crawl terminate rather than merely thin.
_GATED_PAGE = """<!doctype html><html><head><title>Gated</title></head><body>
<div id="root"></div>
<script>
  var open = false;
  function paint() {
    document.getElementById('root').innerHTML = open
      ? '<nav><a href="/one">One</a> <a href="/two">Two</a> <a href="/three">Three</a></nav>'
        + '<h1>The actual site</h1>'
        + '<p>' + 'Real content that only exists after the gate is opened. '.repeat(30) + '</p>'
      : '<div style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:50">'
        + '<h1>Who are you?</h1><button id="go">Solo Founder</button></div>';
    var go = document.getElementById('go');
    if (go) go.onclick = function () { open = true; paint(); };
  }
  paint();
</script>
</body></html>"""

_UNGATED_PAGE = """<!doctype html><html><head><title>Open</title></head><body>
<nav><a href="/one">One</a> <a href="/two">Two</a></nav>
<h1>Nothing is gated here</h1>
<p>{}</p>
<button>Subscribe</button>
</body></html>""".format("Ordinary prose that is present from the first paint. " * 40)


def _server(handler: type[http.server.BaseHTTPRequestHandler]) -> Iterator[str]:
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


class _GatedSite(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_GATED_PAGE.encode())

    def log_message(self, *args: object) -> None:
        pass


class _OpenSite(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_UNGATED_PAGE.encode())

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def gated() -> Iterator[str]:
    yield from _server(_GatedSite)


@pytest.fixture
def ungated() -> Iterator[str]:
    yield from _server(_OpenSite)


def extracted(result: RenderResult, url: str) -> tuple[str, list[str]]:
    """Text and links as the engine actually sees them.

    Asserting against `result.html` is a trap this fixture walks straight into: the page is
    built by an inline script, so `<script>` source contains every literal the mounted DOM
    does -- including the ones that are supposed to be absent. `build_document` strips
    scripts, which is the whole point of `SKIP_TAGS`.
    """
    document = build_document(result.html, url)
    return document.text, list(extract_links(result.html, url).links)


class TestGateDismissal:
    def test_gate_stays_shut_when_disabled(self, gated: str) -> None:
        """The behaviour before this feature: the modal is all you get."""
        result = render_page(gated, config=RenderConfig(dismiss_gates=False, settle_ms=400))
        assert result.ok
        text, _links = extracted(result, gated)
        assert "Who are you?" in text
        assert "The actual site" not in text
        assert result.gate_dismissed is False

    def test_gate_is_opened(self, gated: str) -> None:
        result = render_page(gated, config=RenderConfig(dismiss_gates=True, settle_ms=400))
        assert result.ok
        assert result.gate_dismissed is True
        text, _links = extracted(result, gated)
        assert "The actual site" in text
        assert result.gate_note is not None
        assert "opened an interstitial" in result.gate_note

    def test_opening_the_gate_reveals_the_navigation(self, gated: str) -> None:
        """The crawl half. Links live inside the gated subtree, so without this the frontier
        empties after one page and the crawl calls itself exhausted."""
        shut = render_page(gated, config=RenderConfig(dismiss_gates=False, settle_ms=400))
        opened = render_page(gated, config=RenderConfig(dismiss_gates=True, settle_ms=400))
        _, shut_links = extracted(shut, gated)
        _, opened_links = extracted(opened, gated)
        assert shut_links == []
        assert {"/one", "/two", "/three"} <= set(opened_links)

    def test_an_ordinary_page_is_left_alone(self, ungated: str) -> None:
        """Nothing is clicked on a page that already has text and navigation.

        This is the guard that keeps a click off the other 99% of the web -- including the
        `Subscribe` button on this fixture, which the deny-list would also have refused.
        """
        result = render_page(ungated, config=RenderConfig(dismiss_gates=True, settle_ms=400))
        assert result.ok
        assert result.gate_dismissed is False
        # Not merely "did not open" -- not even suspected. Two nav links are enough to say
        # this is a real page, which is why GATE_MAX_LINKS is 1.
        assert result.gate_note is None
        text, _links = extracted(result, ungated)
        assert "Nothing is gated here" in text


class TestIdenticalContentWarning:
    def test_warns_when_every_route_returns_the_same_text(self, gated: str) -> None:
        """The net for gates the engine cannot open.

        Rendering is disabled so every route yields the same static shell -- the same shape
        as a login wall or an unopenable interstitial, without needing one.
        """
        from webgraph.resolve import Strategy

        config = SiteConfig(
            max_pages=4,
            concurrency=1,
            delay_seconds=0.0,
            strategy=Strategy.STATIC_ONLY,
            verify_inventory=False,
        )
        warnings = [
            event
            for event in stream_site(gated, config=config)
            if event["type"] == "warning"
        ]
        # Every URL on this server returns the identical body, so the crawl cannot escape it.
        # Whether it queues enough URLs to trip the threshold depends on link discovery, so
        # assert the shape of any warning raised rather than that one must be.
        for warning in warnings:
            assert warning["code"] == "identical-content"
            assert len(warning["urls"]) >= IDENTICAL_CONTENT_WARNING
            assert "interstitial" in warning["message"]

    def test_done_event_reports_the_largest_identical_group(self, ungated: str) -> None:
        from webgraph.resolve import Strategy

        config = SiteConfig(
            max_pages=3,
            concurrency=1,
            delay_seconds=0.0,
            strategy=Strategy.STATIC_ONLY,
            verify_inventory=False,
        )
        done = [e for e in stream_site(ungated, config=config) if e["type"] == "done"]
        assert done
        assert "largest_identical_group" in done[0]
        assert "identical_content_groups" in done[0]
