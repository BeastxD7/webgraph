"""A frameset page is a page made of other pages, and is read as one.

cs.cmu.edu/~rgs/alice-table.html (1994): `<frameset rows="50,*">` with a table-of-contents
frame over a text frame and a `<noframes>` body. Neither fetch saw a word -- the static
markup holds the frame elements, and a browser renders each frame as a separate document --
and the engine refused the page as "a JavaScript shell with no readable text".
"""

from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from typing import ClassVar

import pytest

from webgraph.resolve import Strategy, resolve_page

TOP = b"""<HTML><HEAD><TITLE>Alice's Adventures (frames)</TITLE></HEAD>
<frameset rows="50,*">
<frame src="alice-finfo.html">
<frame src="alice-ftitle.html" name="alice-main">
</frameset>
<noframes><BODY><H1>Alice's Adventures in Wonderland</H1>
<p>NOTE: This is a hypertext formatted version of the Project Gutenberg edition, for browsers without frames.</p>
</BODY></noframes></HTML>"""

INFO = b"""<html><body><b><a href="alice-ftitle.html">Contents</a></b> | <b>Chapters:</b>
<a href="alice-I.html">1</a> | <a href="alice-II.html">2</a></body></html>"""

TITLE = b"""<html><body><h1>Alice's Adventures in Wonderland</h1><h2>Lewis Carroll</h2>
<p>Alice was beginning to get very tired of sitting by her sister on the bank, and of having nothing to do.</p>
<p>So she was considering in her own mind whether the pleasure of making a daisy-chain would be worth the trouble.</p>
</body></html>"""


class Server(http.server.BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, bytes]] = {}

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        body = Server.routes.get(self.path)
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", "text/html")
        payload = body if body is not None else b"<html><body>no</body></html>"
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def server() -> Iterator[str]:
    Server.routes = {"/rgs/alice-table.html": TOP, "/rgs/alice-finfo.html": INFO, "/rgs/alice-ftitle.html": TITLE}
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


class TestFramesets:
    def test_the_frames_are_read_in_frameset_order_without_noframes(self, server: str) -> None:
        """The `<noframes>` body is what a browser without frames shows instead of them;
        with the frames fetched it is not on the page (on cs.cmu.edu it repeated the
        title frame and added a second table of contents)."""
        resolved = resolve_page(f"{server}/rgs/alice-table.html", strategy=Strategy.STATIC_ONLY)
        texts = [b.text for b in resolved.document.blocks]
        assert texts[0].startswith("Contents")  # the top frame first
        assert "Alice was beginning to get very tired of sitting by her sister on the bank, and of having nothing to do." in texts
        assert texts.index("Alice's Adventures in Wonderland") < texts.index("Alice was beginning to get very tired of sitting by her sister on the bank, and of having nothing to do.")
        assert not any(t.startswith("NOTE: This is a hypertext") for t in texts)  # noframes not shown
        assert resolved.render_error and resolved.render_error.startswith("frameset")

    def test_noframes_stands_in_when_no_frame_can_be_fetched(self, server: str) -> None:
        Server.routes = {"/rgs/alice-table.html": TOP}
        try:
            resolved = resolve_page(f"{server}/rgs/alice-table.html", strategy=Strategy.STATIC_ONLY)
        finally:
            Server.routes = {"/rgs/alice-table.html": TOP, "/rgs/alice-finfo.html": INFO, "/rgs/alice-ftitle.html": TITLE}
        texts = [b.text for b in resolved.document.blocks]
        assert any(t.startswith("NOTE: This is a hypertext") for t in texts)

    def test_frame_links_resolve_against_the_frame(self, server: str) -> None:
        resolved = resolve_page(f"{server}/rgs/alice-table.html", strategy=Strategy.STATIC_ONLY)
        hrefs = [b.href for b in resolved.document.blocks if b.href]
        links = [b.rich_text for b in resolved.document.blocks if b.rich_text and "alice-I.html" in b.rich_text]
        assert links and f"{server}/rgs/alice-I.html" in links[0]
        assert not any(h and h.startswith("alice-") for h in hrefs)
