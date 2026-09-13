"""End-to-end pipeline tests.

The critical case is the stage-ordering one: block extraction strips `<script>` tags, so a
pipeline that extracts payloads afterwards returns nothing while looking perfectly healthy.
"""

from __future__ import annotations

from webgraph.pipeline import build_document, content_hash_of
from webgraph.types import PayloadSource, ReadingOrderMethod, Rect

SAMPLE = """
<html><head>
  <title>Pricing</title>
  <script type="application/ld+json">
  {"@type":"Product","name":"Pro plan","offers":{"@type":"Offer","price":"49"}}
  </script>
  <meta property="og:title" content="Pricing">
</head><body>
  <h1>Plans</h1>
  <div><p>The Pro plan costs $49 per month.</p></div>
  <script>window.__INITIAL_STATE__ = {"plan":"pro"};</script>
</body></html>
"""


class TestStageOrdering:
    def test_payloads_survive_block_extraction(self) -> None:
        """Regression: block extraction strips <script>, which would erase every payload."""
        doc = build_document(SAMPLE, "https://example.com/pricing")
        sources = {p.source for p in doc.structured_data}
        assert PayloadSource.JSON_LD in sources
        assert PayloadSource.INITIAL_STATE in sources
        assert PayloadSource.OPEN_GRAPH in sources

    def test_script_content_absent_from_text(self) -> None:
        doc = build_document(SAMPLE, "https://example.com/pricing")
        assert "__INITIAL_STATE__" not in doc.text
        assert "application/ld+json" not in doc.text

    def test_blocks_and_payloads_both_populated(self) -> None:
        doc = build_document(SAMPLE, "https://example.com/pricing")
        assert doc.blocks
        assert doc.structured_data


class TestReadingOrderIntegration:
    def test_static_html_reports_dom_fallback(self) -> None:
        doc = build_document(SAMPLE, "https://example.com/")
        assert doc.reading_order_method is ReadingOrderMethod.DOM_FALLBACK
        assert doc.dom_order_differs is False

    def test_geometry_enables_geometric_ordering(self) -> None:
        html = """
        <html><body>
          <p id="a">left one</p><p id="b">right one</p>
          <p id="c">left two</p><p id="d">right two</p>
        </body></html>
        """
        doc_plain = build_document(html, "https://example.com/")
        xpaths = [b.xpath for b in doc_plain.blocks]

        # Two columns: a/c on the left, b/d on the right.
        geometry = {
            xpaths[0]: Rect(x=0, y=0, width=300, height=20),
            xpaths[1]: Rect(x=400, y=0, width=300, height=20),
            xpaths[2]: Rect(x=0, y=40, width=300, height=20),
            xpaths[3]: Rect(x=400, y=40, width=300, height=20),
        }
        doc = build_document(html, "https://example.com/", geometry=geometry)

        assert doc.reading_order_method is ReadingOrderMethod.GEOMETRIC_XY_CUT
        assert [b.text for b in doc.blocks] == [
            "left one", "left two", "right one", "right two",
        ]
        assert doc.dom_order_differs is True

    def test_sparse_geometry_still_falls_back(self) -> None:
        """Below `min_measured_share` the document falls back and says so.

        Two measured blocks out of ten is 20%, and measurement put the crossover against
        source order at roughly 25-30% -- see `OrderingConfig.min_measured_share`.
        """
        body = "".join(f"<p>paragraph number {index} with some words</p>" for index in range(10))
        html = f"<html><body>{body}</body></html>"
        plain = build_document(html, "https://example.com/")
        partial = {
            block.xpath: Rect(x=0, y=float(index * 40), width=600, height=30)
            for index, block in enumerate(plain.blocks[:2])
        }
        doc = build_document(html, "https://example.com/", geometry=partial)
        assert doc.reading_order_method is ReadingOrderMethod.DOM_FALLBACK

    def test_mostly_measured_geometry_is_used_and_labelled(self) -> None:
        """Collapsed content leaves gaps in the measurements; abandoning geometry over them
        downgraded essentially every real documentation page."""
        doc_plain = build_document(SAMPLE, "https://example.com/")
        geometry = {
            block.xpath: Rect(x=0, y=float(index * 40), width=600, height=30)
            for index, block in enumerate(doc_plain.blocks[:-1])
        }
        doc = build_document(SAMPLE, "https://example.com/", geometry=geometry)
        assert doc.reading_order_method is ReadingOrderMethod.GEOMETRIC_ANCHORED
        assert len(doc.blocks) == len(doc_plain.blocks)


class TestContentHash:
    def test_stable_across_identical_input(self) -> None:
        a = build_document(SAMPLE, "https://example.com/")
        b = build_document(SAMPLE, "https://example.com/")
        assert a.content_hash == b.content_hash

    def test_ignores_non_content_markup_churn(self) -> None:
        """Build hashes and analytics tokens change on every deploy; content does not."""
        base = "<html><body><p>Stable content</p>{}</body></html>"
        a = build_document(base.format('<script src="/a.b1c2d3.js"></script>'), "u")
        b = build_document(base.format('<script src="/a.9z8y7x.js"></script>'), "u")
        assert a.content_hash == b.content_hash

    def test_changes_when_text_changes(self) -> None:
        a = build_document("<html><body><p>Price is 49</p></body></html>", "u")
        b = build_document("<html><body><p>Price is 59</p></body></html>", "u")
        assert a.content_hash != b.content_hash

    def test_hash_of_empty_text(self) -> None:
        assert content_hash_of("") == content_hash_of("")


class TestProfileIntegration:
    def test_detects_json_ld_and_frameworks(self) -> None:
        doc = build_document(SAMPLE, "https://example.com/")
        assert doc.profile.has_json_ld is True

    def test_next_js_shell_requires_render_despite_payload(self) -> None:
        """A hydration payload does NOT mean the page is readable without a browser.

        Regression test for a measured failure: `nextjs.org` ships a `__NEXT_DATA__`
        payload and *zero* visible text. An earlier version treated the payload as proof a
        render was unnecessary and returned 0% of the page's content. The payload describes
        the page; the readable text still only exists after hydration.
        """
        html = """
        <html><body><div id="__next"></div>
        <script id="__NEXT_DATA__" type="application/json">{"props":{"a":1}}</script>
        </body></html>
        """
        doc = build_document(html, "https://example.com/")
        assert doc.profile.has_next_data is True
        assert doc.profile.requires_render is True
        assert "next.js" in doc.profile.frameworks

    def test_empty_page_always_requires_render(self) -> None:
        """Zero text is never 'complete' -- it is a bot challenge, a stub, or an app shell."""
        doc = build_document("<html><body><div>.</div></body></html>", "https://example.com/")
        assert doc.profile.requires_render is True

    def test_empty_spa_shell_requires_render(self) -> None:
        html = '<html><body><div id="root"></div><script src="/bundle.js"></script></body></html>'
        doc = build_document(html, "https://example.com/")
        assert doc.profile.requires_render is True

    def test_content_rich_page_does_not_require_render(self) -> None:
        body = "".join(f"<p>Paragraph number {i} with a reasonable amount of text.</p>" for i in range(20))
        doc = build_document(f"<html><body>{body}</body></html>", "https://example.com/")
        assert doc.profile.requires_render is False


class TestDocumentText:
    def test_text_is_reading_ordered(self) -> None:
        doc = build_document(SAMPLE, "https://example.com/")
        assert doc.text.startswith("Plans")
        assert "Pro plan costs $49" in doc.text


class TestDuplicateResolution:
    def test_the_heading_survives_its_own_echo_in_the_sidebar(self) -> None:
        """docs.python.org: the <h1> is also the current item in the sidebar, which is read
        first. Keeping the first occurrence kept the list item and lost the page's title."""
        from webgraph.pipeline import build_document

        html = (
            "<html><body>"
            '<nav><ul><li><a href="#m">itertools — Functions creating iterators</a></li>'
            "<li><a href='#r'>Recipes</a></li></ul></nav>"
            "<main><h1>itertools — Functions creating iterators</h1><p>This module implements "
            "a number of iterator building blocks.</p></main></body></html>"
        )
        blocks = build_document(html, "https://docs.python.org/3/library/itertools.html").blocks
        heading = [b for b in blocks if b.text.startswith("itertools —")]
        assert len(heading) == 1
        assert heading[0].tag == "h1"
        # And it sits where the page put it: before its own first paragraph, not in the nav.
        texts = [b.text for b in blocks]
        assert texts.index(heading[0].text) < texts.index("This module implements a number of iterator building blocks.")
        assert texts.index("Recipes") < texts.index(heading[0].text)

    def test_two_plain_copies_still_keep_the_first(self) -> None:
        """The general rule is unchanged: the copy a reader reaches first stays."""
        from webgraph.pipeline import build_document

        html = "<html><body><p>Same words here.</p><section><p>Same words here.</p></section></body></html>"
        blocks = build_document(html, "https://x.test/").blocks
        assert [b.text for b in blocks].count("Same words here.") == 1

    def test_a_measured_later_copy_wins_where_it_was_drawn(self) -> None:
        """python.org: the header's hidden dropdown lists the same links as the footer
        columns. The measured footer copy must win -- and win *in the footer*, not move up
        into the dropdown's slot, which read the whole footer inside the header."""
        from webgraph.pipeline import build_document

        html = (
            "<html><body>"
            "<div id='nav'><p>Intro line of the page header.</p><ul id='dropdown'><li>Applications</li><li>Quotes</li><li>Help</li></ul></div>"
            "<main><p>The body of the page, which is long enough to be measured as prose.</p></main>"
            "<div id='foot'><ul><li>Applications</li><li>Quotes</li><li>Help</li></ul></div>"
            "</body></html>"
        )
        geometry = {
            "/html/body/div[1]/p": Rect(x=0, y=0, width=800, height=20),
            "/html/body/main/p": Rect(x=0, y=100, width=800, height=40),
            "/html/body/div[2]/ul/li[1]": Rect(x=0, y=900, width=200, height=20),
            "/html/body/div[2]/ul/li[2]": Rect(x=0, y=920, width=200, height=20),
            "/html/body/div[2]/ul/li[3]": Rect(x=0, y=940, width=200, height=20),
        }
        blocks = build_document(html, "https://python.test/", geometry=geometry).blocks
        texts = [b.text for b in blocks]
        assert texts.count("Applications") == 1
        assert texts.index("The body of the page, which is long enough to be measured as prose.") < texts.index("Applications")
        assert [b.rect is not None for b in blocks if b.text == "Applications"] == [True]
