"""End-to-end reading-order tests against a real browser.

Synthetic geometry proves the algorithm; these prove the *chain* -- that Chromium's
measurements survive marker stamping, HTML serialisation, lxml parsing, and XPath rekeying
without losing the correspondence between element and rectangle.

Every fixture is a layout where DOM order and visual order genuinely disagree, so a
regression to a plain tree walk fails here loudly.

Marked `render`; deselect with `-m 'not render'` where no browser is available.
"""

from __future__ import annotations

import pathlib

import pytest

from webgraph.fetch.render import (
    PLAYWRIGHT_AVAILABLE,
    RenderConfig,
    geometry_by_xpath,
    render_page,
)
from webgraph.pipeline import build_document
from webgraph.types import Document, ReadingOrderMethod

pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="playwright not installed"),
]

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CONFIG = RenderConfig(wait_until="load", settle_ms=150)


def render_fixture(name: str) -> tuple[Document, Document]:
    """Return (geometric document, DOM-order document) for the same fixture."""
    url = (FIXTURES / f"{name}.html").resolve().as_uri()
    result = render_page(url, config=CONFIG)
    assert result.ok, f"render failed: {result.error}"
    assert result.rects, "browser returned no geometry"

    geometry = geometry_by_xpath(result.html, result.rects)
    assert geometry, "marker ids did not rekey to XPaths"

    return (
        build_document(result.html, url, geometry=geometry),
        build_document(result.html, url),
    )


def firsts(document: Document) -> list[str]:
    return [b.text.split()[0] for b in document.blocks if b.text.strip()]


class TestFlexOrderReversal:
    """`order:` on flex children detaches visual sequence from source sequence."""

    def test_visual_order_recovered(self) -> None:
        geometric, dom = render_fixture("flex_order")
        assert firsts(geometric) == ["ALPHA", "BETA", "GAMMA"]
        assert firsts(dom) == ["GAMMA", "ALPHA", "BETA"], "fixture no longer discriminates"
        assert geometric.reading_order_method is ReadingOrderMethod.GEOMETRIC_XY_CUT
        assert geometric.dom_order_differs is True


class TestRowReverseColumns:
    """`flex-direction: row-reverse` puts the right-hand column first in source."""

    def test_header_columns_footer(self) -> None:
        geometric, dom = render_fixture("two_column")
        assert firsts(geometric) == [
            "HEADER",
            "LEFT",
            "LEFT",
            "LEFT",
            "RIGHT",
            "RIGHT",
            "RIGHT",
            "FOOTER",
        ]
        assert firsts(dom)[1] == "RIGHT", "fixture no longer discriminates"

    def test_spanning_elements_bracket_the_columns(self) -> None:
        geometric, _ = render_fixture("two_column")
        order = firsts(geometric)
        assert order[0] == "HEADER"
        assert order[-1] == "FOOTER"


class TestGridPlacement:
    """Explicit `grid-column` / `grid-row` placement reorders relative to source."""

    def test_reads_rows_left_to_right(self) -> None:
        geometric, dom = render_fixture("grid_placement")
        assert firsts(geometric) == ["A1", "B1", "A2", "B2"]
        assert firsts(dom) == ["B1", "A1", "B2", "A2"], "fixture no longer discriminates"


class TestCssMultiColumn:
    """`column-count` flows text into columns; source order already matches reading order.

    The value of this case is that geometry must *not* make it worse -- a column-aware
    algorithm that interleaved here would be actively harmful.
    """

    def test_columns_read_down_then_across(self) -> None:
        geometric, dom = render_fixture("css_columns")
        assert firsts(geometric) == ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX"]
        assert firsts(geometric) == firsts(dom)


class TestGeometryPlumbing:
    def test_marker_attributes_rekey_to_xpaths(self) -> None:
        url = (FIXTURES / "two_column.html").resolve().as_uri()
        result = render_page(url, config=CONFIG)
        geometry = geometry_by_xpath(result.html, result.rects)
        assert all(path.startswith("/html") for path in geometry)

    def test_every_block_receives_geometry(self) -> None:
        geometric, _ = render_fixture("two_column")
        assert all(b.rect is not None for b in geometric.blocks)

    def test_hidden_elements_are_not_measured(self) -> None:
        """display:none elements have no box and must be excluded, not measured as zero-area."""
        url = (FIXTURES / "flex_order.html").resolve().as_uri()
        result = render_page(url, config=CONFIG)
        assert all(r.width > 0 and r.height > 0 for r in result.rects.values())


class TestRenderFailure:
    def test_unreachable_url_degrades_gracefully(self) -> None:
        result = render_page("http://127.0.0.1:9/nothing", config=RenderConfig(timeout_ms=3000))
        assert result.ok is False
        assert result.error

    def test_attachment_is_reported_as_a_download_not_a_driver_error(self) -> None:
        """A URL that answers with a file must degrade to a sentence, not a Playwright trace.

        Chromium turns a `Content-Disposition: attachment` navigation into a download, and
        `page.goto` then raises "Download is starting" -- which reads, to anyone holding the
        report, like the browser broke. It did not; the address is simply not a page. Real
        sites do this: amazon.in answers some blocked requests with an attachment.
        """
        import http.server
        import threading

        class Attachment(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = b"id,name\n1,thing\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Disposition", 'attachment; filename="export.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:  # noqa: ARG002
                return

        server = http.server.HTTPServer(("127.0.0.1", 0), Attachment)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/export.csv"
            result = render_page(url, config=RenderConfig(timeout_ms=10_000))
        finally:
            server.shutdown()
            server.server_close()

        assert result.ok is False
        assert result.error == "the server returned a file download rather than a page"

    def test_a_server_that_never_answers_is_reported_as_a_timeout_not_a_refusal(self) -> None:
        """A navigation that times out before the first byte leaves the page on
        `about:blank`. Checking that against the host policy reported every such timeout as
        "refusing non-HTTP scheme: about" -- a security refusal that never happened.
        """
        import http.server
        import threading
        import time

        class Silent(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                time.sleep(4)  # longer than the render timeout below; never answers in time

            def log_message(self, *args: object) -> None:  # noqa: ARG002
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Silent)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/slow"
            result = render_page(url, config=RenderConfig(timeout_ms=1500))
        finally:
            server.shutdown()
            server.server_close()

        assert result.ok is False
        assert result.error is not None
        assert "about" not in result.error.lower() or "never started" in result.error
        assert "never started" in result.error

    def test_the_result_reports_where_the_browser_landed(self) -> None:
        """A short link redirects to the real host, and every relative link on the page
        resolves against the real host. Reporting the requested address resolved them all
        against the short-link domain, the crawl's scope rejected every one, and a whole-site
        crawl of Amazon through amzn.in discovered exactly one page."""
        import http.server
        import threading

        class Redirecting(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/short":
                    self.send_response(302)
                    self.send_header("Location", "/real/page")
                    self.end_headers()
                    return
                body = b"<html><body><h1>Landed</h1><a href='/other'>other</a></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:  # noqa: ARG002
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirecting)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            result = render_page(f"{base}/short", config=RenderConfig(timeout_ms=10_000))
        finally:
            server.shutdown()
            server.server_close()

        assert result.ok
        assert result.url == f"{base}/real/page"


class TestHiddenBoxes:
    """apple.com/iphone, read in Chrome beside the engine.

    A collapsed accordion tray is `overflow: hidden` at height 0 and its paragraph keeps a
    natural box underneath the *next* item's heading, so an order by boxes zips trays with
    headings. A hero faded in by an entrance animation is opacity 0 at load and used to go
    unmeasured, so it was slotted by source position instead of where it sits. A copy of a
    heading clipped to a 1px box is screen-reader-only whatever its class is called.
    """

    def test_collapsed_trays_follow_their_headings(self) -> None:
        geometric, _ = render_fixture("hidden_boxes")
        texts = [b.text for b in geometric.blocks]
        assert (
            texts.index("Item two")
            < texts.index("Tray two is collapsed; this paragraph has a box under item three.")
            < texts.index("Item three")
        )
        assert texts.index("Item three") < texts.index("Tray three is collapsed as well.")

    def test_a_faded_hero_is_measured_where_it_sits(self) -> None:
        geometric, _ = render_fixture("hidden_boxes")
        texts = [b.text for b in geometric.blocks]
        assert texts[:4] == [
            "First hero, faded in later",
            "Tagline of the first hero.",
            "Second hero, visible at load",
            "Tagline of the second hero.",
        ]
        faded = next(b for b in geometric.blocks if b.text == "First hero, faded in later")
        assert faded.rect is not None

    def test_a_clipped_copy_of_a_heading_is_dropped(self) -> None:
        geometric, _ = render_fixture("hidden_boxes")
        assert [b.text for b in geometric.blocks if b.text.startswith("Significant")] == [
            "Significant others"
        ]


class TestRevealCollapsed:
    """`reveal.js` opens tab panels and named panels without a click, and never a menu."""

    HTML = """<!doctype html><html><body>
    <nav><button data-bs-target="#menu" aria-expanded="false">Menu</button>
      <div id="menu" style="display:none"><a href="/a">Alpha link</a><a href="/b">Beta link</a></div></nav>
    <main>
      <div role="tablist">
        <button role="tab" aria-selected="true" aria-controls="p1">Details</button>
        <button role="tab" aria-selected="false" aria-controls="p2">Delivery</button>
      </div>
      <div role="tabpanel" id="p1"><p>The details panel is the one showing when the page loads.</p></div>
      <div role="tabpanel" id="p2" hidden><p>Delivery takes three to five working days across the country.</p></div>
      <a href="#faq" class="toggle">Frequently asked questions</a>
      <div id="faq" style="display:none"><p>Returns are accepted within thirty days of delivery.</p></div>
      <a href="#visible">Jump to the visible section</a>
      <section id="visible"><p>A visible section that a link merely jumps to.</p></section>
    </main></body></html>"""

    def test_panels_open_and_the_menu_stays_shut(self, tmp_path: pathlib.Path) -> None:
        page = tmp_path / "tabs.html"
        page.write_text(self.HTML, encoding="utf-8")
        result = render_page(
            page.as_uri(),
            config=RenderConfig(wait_until="load", settle_ms=150, reveal_collapsed=True),
        )
        assert result.ok, result.error
        html = result.html
        assert html.count('data-wg-revealed="1"') == 2  # the Delivery tab panel and #faq
        # Opened: the browser laid them out, so they carry a box and no hidden mark.
        document = build_document(
            html, page.as_uri(), geometry=geometry_by_xpath(html, result.rects)
        )
        texts = [b.text for b in document.blocks]
        assert "Delivery takes three to five working days across the country." in texts
        assert "Returns are accepted within thirty days of delivery." in texts
        # The menu under <nav> is left alone: still display:none, not stamped. (The parser
        # may still keep it as a reachable tray -- a button names it -- but unmeasured.)
        assert 'id="menu" style="display:none"' in html
        menu = next(b for b in document.blocks if "Alpha link" in b.text)
        assert menu.rect is None
