"""Structure-preserving extraction and Markdown rendering.

Plain-text extraction silently destroys most of a page's meaning. Each test here pins one
kind of structure that must survive the trip out of the HTML.
"""

from __future__ import annotations

import pytest

from webgraph.dom.blocks import parse_html
from webgraph.dom.rich import extract_rich_blocks
from webgraph.pipeline import build_document
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.types import BlockKind

BASE = "https://example.com/page"


def blocks(body: str):
    return extract_rich_blocks(parse_html(f"<html><body>{body}</body></html>"), BASE)


def md(body: str, **kwargs: bool) -> str:
    document = build_document(f"<html><body>{body}</body></html>", BASE)
    return to_markdown(document, options=MarkdownOptions(**kwargs))  # type: ignore[arg-type]


class TestHeadings:
    def test_levels_preserved(self) -> None:
        out = md("<h1>Title</h1><h3>Sub</h3>")
        assert "# Title" in out
        assert "### Sub" in out

    def test_heading_kind_recorded(self) -> None:
        found = blocks("<h2>Heading</h2>")
        assert found[0].kind is BlockKind.HEADING
        assert found[0].level == 2

    def test_heading_offset(self) -> None:
        assert "## Title" in md("<h1>Title</h1>", heading_offset=1)


class TestImages:
    def test_image_becomes_markdown_with_absolute_url(self) -> None:
        """Images were previously dropped entirely."""
        out = md('<img src="/logo.png" alt="Company logo">')
        assert "![Company logo](https://example.com/logo.png)" in out

    def test_relative_paths_resolved(self) -> None:
        out = md('<img src="../img/a.png" alt="A">')
        assert "https://example.com/img/a.png" in out

    def test_lazy_loaded_src_recovered(self) -> None:
        """Lazy-loading markup hides the real image behind data attributes."""
        out = md('<img data-src="/real.png" alt="Real">')
        assert "https://example.com/real.png" in out

    def test_srcset_fallback(self) -> None:
        out = md('<img srcset="/small.png 480w, /big.png 1024w" alt="S">')
        assert "https://example.com/small.png" in out

    def test_tracking_pixels_skipped(self) -> None:
        out = md('<img src="/pixel.gif" width="1" height="1" alt="">')
        assert "pixel.gif" not in out

    def test_data_uris_skipped(self) -> None:
        out = md('<img src="data:image/gif;base64,R0lGOD" alt="inline">')
        assert "data:image" not in out

    def test_images_can_be_disabled(self) -> None:
        out = md('<img src="/logo.png" alt="Logo">', include_images=False)
        assert "logo.png" not in out


class TestTables:
    HTML = """
    <table>
      <tr><th>Plan</th><th>Price</th></tr>
      <tr><td>Pro</td><td>49</td></tr>
      <tr><td>Team</td><td>99</td></tr>
    </table>
    """

    def test_table_renders_as_markdown_table(self) -> None:
        """A flattened table loses which column a value belonged to."""
        out = md(self.HTML)
        assert "| Plan | Price |" in out
        assert "| --- | --- |" in out
        assert "| Pro | 49 |" in out

    def test_rows_captured_on_block(self) -> None:
        found = [b for b in blocks(self.HTML) if b.kind is BlockKind.TABLE]
        assert found[0].rows[0] == ("Plan", "Price")
        assert len(found[0].rows) == 3

    def test_ragged_rows_padded_not_dropped(self) -> None:
        out = md("<table><tr><th>A</th><th>B</th></tr><tr><td>only</td></tr></table>")
        assert "| only |  |" in out

    def test_pipes_in_cells_escaped(self) -> None:
        # A real 2x2 grid: a single cell is a layout device, not a table, and is unwrapped
        # before any of this runs.
        out = md("<table><tr><td>a|b</td><td>c</td></tr><tr><td>d</td><td>e</td></tr></table>")
        assert r"a\|b" in out

    def test_empty_table_emits_nothing(self) -> None:
        assert "|" not in md("<table></table>")


class TestListsAndCode:
    def test_unordered_list(self) -> None:
        out = md("<ul><li>one</li><li>two</li></ul>")
        assert "- one" in out
        assert "- two" in out

    def test_ordered_list(self) -> None:
        out = md("<ol><li>first</li></ol>")
        assert "1. first" in out

    def test_nested_list_indented(self) -> None:
        out = md("<ul><li>outer<ul><li>inner</li></ul></li></ul>")
        assert "  - inner" in out

    def test_code_block_fenced(self) -> None:
        out = md("<pre><code>x = 1</code></pre>")
        assert "```" in out
        assert "x = 1" in out

    def test_code_language_detected(self) -> None:
        out = md('<pre><code class="language-python">x = 1</code></pre>')
        assert "```python" in out

    def test_code_whitespace_preserved(self) -> None:
        """Indentation is semantic in code; normalising it would corrupt the sample."""
        out = md("<pre><code>def f():\n    return 1</code></pre>")
        assert "    return 1" in out

    def test_blockquote(self) -> None:
        assert "> quoted" in md("<blockquote>quoted</blockquote>")

    def test_figcaption_emphasised(self) -> None:
        assert "*A caption*" in md("<figure><figcaption>A caption</figcaption></figure>")


class TestDocumentIntegration:
    def test_reading_order_respected(self) -> None:
        out = md("<h1>First</h1><p>Body</p><h2>Second</h2>")
        assert out.index("# First") < out.index("Body") < out.index("## Second")

    def test_front_matter(self) -> None:
        out = md("<p>x</p>", front_matter=True)
        assert out.startswith("---")
        assert "url: https://example.com/page" in out

    def test_scripts_never_leak(self) -> None:
        out = md("<script>var secret=1</script><p>Real</p>")
        assert "secret" not in out
        assert "Real" in out

    def test_full_page_shape(self) -> None:
        out = md(
            "<h1>Doc</h1><p>Intro</p><ul><li>a</li></ul>"
            '<img src="/i.png" alt="I"><table><tr><th>H</th></tr></table>'
        )
        for expected in ["# Doc", "Intro", "- a", "![I](https://example.com/i.png)", "| H |"]:
            assert expected in out


class TestInlineLinks:
    """Measured against trafilatura: the engine emitted **0** inline links on danluu.com
    where trafilatura emitted 201. Every `href` was being discarded by `text_content()`."""

    def test_link_target_preserved(self) -> None:
        out = md('<p>See <a href="/docs">the docs</a> for more.</p>')
        assert "[the docs](https://example.com/docs)" in out

    def test_relative_href_made_absolute(self) -> None:
        out = md('<p><a href="../about">About</a></p>')
        assert "(https://example.com/about)" in out

    def test_emphasis_and_code_preserved(self) -> None:
        out = md("<p>A <strong>bold</strong> and <em>italic</em> and <code>x=1</code></p>")
        assert "**bold**" in out
        assert "*italic*" in out
        assert "`x=1`" in out

    def test_link_inside_heading(self) -> None:
        out = md('<h2><a href="/a">Section</a></h2>')
        assert out.startswith("## [Section](https://example.com/a)")

    def test_link_inside_list_item(self) -> None:
        out = md('<ul><li><a href="/x">Item</a></li></ul>')
        assert "- [Item](https://example.com/x)" in out

    def test_links_can_be_disabled(self) -> None:
        out = md('<p>See <a href="/docs">the docs</a>.</p>', include_links=False)
        assert "](" not in out
        assert "the docs" in out

    def test_anchor_without_text_contributes_nothing_broken(self) -> None:
        out = md('<p>Text <a href="/x"></a> more</p>')
        assert "[]" not in out

    def test_plain_text_field_stays_plain(self) -> None:
        """Dedup, hashing and reading order key on `text`; Markdown syntax must not leak in."""
        from webgraph.pipeline import build_document

        doc = build_document(
            '<html><body><p>See <a href="/d">docs</a></p></body></html>', BASE
        )
        assert doc.blocks[0].text == "See docs"
        assert "](" not in doc.text


class TestPermalinkAnchors:
    """Documentation generators attach a permalink anchor to every heading.

    Left in place it reaches the reader as `Testimonials¶`, the index as a junk token, and
    the Markdown as a stray glyph on every heading of a documentation site. It is matched on
    the class rather than the character, because stripping a trailing `¶` or `#` from every
    heading would also mutilate the ones that legitimately end in one.
    """

    def test_sphinx_pilcrow_removed(self) -> None:
        out = md('<h1>Testimonials<a class="headerlink" href="#t">¶</a></h1>')
        assert "# Testimonials" in out
        assert "¶" not in out

    def test_docusaurus_hash_link_removed(self) -> None:
        out = md('<h2>Install<a class="hash-link" aria-hidden="true" href="#i">#</a></h2>')
        assert out.strip().startswith("## Install")
        assert "Install#" not in out

    def test_a_heading_that_really_ends_in_a_hash_survives(self) -> None:
        assert "# The C# language" in md("<h1>The C# language</h1>")

    def test_mediawiki_edit_section_removed(self) -> None:
        out = md(
            '<div class="mw-heading mw-heading2"><h2 id="History">History</h2>'
            '<span class="mw-editsection"><span class="mw-editsection-bracket">[</span>'
            '<a href="/w/index.php?action=edit&section=1">edit</a>'
            '<span class="mw-editsection-divider"> | </span>'
            '<a href="/w/index.php?action=edit&section=1">edit source</a>'
            '<span class="mw-editsection-bracket">]</span></span></div>'
            "<p>The first computers were people who computed.</p>"
        )
        assert "## History" in out
        assert "edit source" not in out

    def test_ordinary_links_in_headings_are_untouched(self) -> None:
        out = md('<h2><a href="/a">Section</a></h2>')
        assert "[Section](https://example.com/a)" in out


class TestTableText:
    """`Block.text` is not a display field.

    The content hash, deduplication, the search index and reading order all key on it. An
    earlier version put only the first three rows there, and a caption *instead of* the rows
    when a table had one -- so a specification table contributed almost nothing to any of
    them while rendering perfectly in the Markdown.

    Measured on Wikipedia's table-heavy pages, that was **45-47% of the page** absent from
    the text while present in the Markdown.
    """

    WIDE = (
        "<table>"
        "<tr><th>City</th><th>Population</th></tr>"
        "<tr><td>Sheffield</td><td>556000</td></tr>"
        "<tr><td>Leeds</td><td>793000</td></tr>"
        "<tr><td>Bristol</td><td>472000</td></tr>"
        "<tr><td>Cardiff</td><td>362000</td></tr>"
        "</table>"
    )

    def test_every_row_reaches_the_text(self) -> None:
        found = [b for b in blocks(self.WIDE) if b.kind is BlockKind.TABLE]
        assert "Cardiff" in found[0].text
        assert "362000" in found[0].text

    def test_a_caption_adds_to_the_rows_rather_than_replacing_them(self) -> None:
        html = self.WIDE.replace("<table>", "<table><caption>UK cities</caption>")
        found = [b for b in blocks(html) if b.kind is BlockKind.TABLE]
        assert "UK cities" in found[0].text
        assert "Cardiff" in found[0].text

    def test_rows_are_still_kept_structurally(self) -> None:
        """The flattened text is in addition to the rows, not instead of them."""
        found = [b for b in blocks(self.WIDE) if b.kind is BlockKind.TABLE]
        assert found[0].rows[0] == ("City", "Population")
        assert len(found[0].rows) == 5


class TestLayoutTables:
    """Legacy sites build whole pages out of nested tables.

    Treating those as data collapsed the page into one block: Hacker News extracted as a
    single block of 3,720 characters with no headings, no links and no reading order -- the
    worst possible output, produced silently.
    """

    def test_a_table_containing_a_table_is_layout(self) -> None:
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        root = parse_html("<html><body><table><tr><td><table><tr><td>x</td></tr>"
                          "</table></td></tr></table></body></html>")
        assert is_layout_table(root.xpath("//table")[0])

    def test_a_table_with_headers_is_data_even_when_its_cells_are_busy(self) -> None:
        """Flattening a real data table loses the mapping from a value to its column, which
        is the whole reason to keep tables."""
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        root = parse_html(
            "<html><body><table><tr><th>Plan</th></tr>"
            "<tr><td><div><p>Pro</p></div></td></tr></table></body></html>"
        )
        assert not is_layout_table(root.xpath("//table")[0])

    def test_a_plain_data_table_is_not_layout(self) -> None:
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        root = parse_html(
            "<html><body><table><tr><td>Sheffield</td><td>556000</td></tr>"
            "<tr><td>Leeds</td><td>793000</td></tr></table></body></html>"
        )
        assert not is_layout_table(root.xpath("//table")[0])

    def test_a_paragraph_in_a_cell_does_not_make_a_table_layout(self) -> None:
        """The bug this rule had for its whole life.

        `<td><p>12.4</p></td>` is what every content management system emits for an ordinary
        value, and `p` used to count as evidence of layout. Measured on WebMainBench: a
        17-row, 111-cell table of numbers -- headers carried by `rowspan`, no `<th>` anywhere,
        every cell wrapping its number in a `<p>` -- was called layout and flattened. The page
        yielded **zero** tables and 294 loose blocks where it should have yielded two tables.
        """
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        cells = "".join(f"<td><p>{n}</p></td>" for n in range(6))
        rows = "".join(f"<tr>{cells}</tr>" for _ in range(17))
        root = parse_html(f"<html><body><table><tbody>{rows}</tbody></table></body></html>")
        assert not is_layout_table(root.xpath("//table")[0])

    def test_a_div_in_a_cell_does_not_either(self) -> None:
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        cells = "".join(f"<td><div>{n}</div></td>" for n in range(4))
        rows = "".join(f"<tr>{cells}</tr>" for _ in range(8))
        root = parse_html(f"<html><body><table>{rows}</table></body></html>")
        assert not is_layout_table(root.xpath("//table")[0])

    def test_a_cell_holding_an_article_still_reads_as_layout(self) -> None:
        """The replacement signal: length, not tag. A cell with 200+ characters of prose is
        holding a page, however it is marked up."""
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import LONG_CELL_CHARS, is_layout_table

        prose = "The widget is a fastener used in cabinetry and shelving. " * 6
        assert len(prose) > LONG_CELL_CHARS
        root = parse_html(
            f"<html><body><table><tr><td><p>{prose}</p></td>"
            f"<td><p>{prose}</p></td></tr></table></body></html>"
        )
        assert is_layout_table(root.xpath("//table")[0])

    def test_two_paragraphs_in_one_cell_reads_as_layout(self) -> None:
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        cell = "<td><p>First paragraph.</p><p>Second paragraph.</p></td>"
        root = parse_html(f"<html><body><table><tr>{cell}{cell}</tr></table></body></html>")
        assert is_layout_table(root.xpath("//table")[0])

    def test_a_single_row_is_not_a_table(self) -> None:
        """A table cross-references a row against a column. One row has nothing to cross-
        reference, so it is a layout device wearing table markup. Measured on WebMainBench:
        of 38 tables the engine emitted where the annotators saw none, most were this shape --
        a 1x2 "Rate this" widget, a 1x4 auto-refresh strip, a 1x1 cell reading "Home"."""
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        root = parse_html("<html><body><table><tr><td>Home</td><td>About</td>"
                          "</tr></table></body></html>")
        assert is_layout_table(root.xpath("//table")[0])

    def test_a_single_column_is_not_a_table_either(self) -> None:
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        rows = "".join(f"<tr><td>Tool {i}</td></tr>" for i in range(6))
        root = parse_html(f"<html><body><table>{rows}</table></body></html>")
        assert is_layout_table(root.xpath("//table")[0])

    def test_a_mostly_empty_grid_is_a_scaffold(self) -> None:
        """A 5x3 grid holding two values is a layout scaffold, not a sparse dataset."""
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        rows = "<tr><td>Headline here</td><td></td><td></td></tr>" + "".join(
            "<tr><td></td><td></td><td></td></tr>" for _ in range(4)
        )
        root = parse_html(f"<html><body><table>{rows}</table></body></html>")
        assert is_layout_table(root.xpath("//table")[0])

    def test_its_content_is_still_extracted(self) -> None:
        """The point of calling it layout is to read it as a page, never to discard it."""
        out = md("<table><tr><td>Home</td><td>About us</td></tr></table>")
        assert "Home" in out
        assert "About us" in out

    def test_a_two_by_two_grid_is_a_table(self) -> None:
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        root = parse_html("<html><body><table><tr><td>Leeds</td><td>793000</td></tr>"
                          "<tr><td>Sheffield</td><td>556000</td></tr></table></body></html>")
        assert not is_layout_table(root.xpath("//table")[0])

    def test_a_header_still_overrides_the_shape_test(self) -> None:
        """A declared header is the page saying "this is data", and it is trusted over any
        inference this module makes from shape."""
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        root = parse_html("<html><body><table><tr><th>Plan</th></tr>"
                          "<tr><td>Pro</td></tr></table></body></html>")
        assert not is_layout_table(root.xpath("//table")[0])

    def test_a_page_laid_out_in_tables_is_extracted_as_content(self) -> None:
        html = (
            "<table><tr><td>"
            "<h1>Widgets</h1><p>" + "The widget is a fastener. " * 8 + "</p>"
            "<table><tr><td><a href='/a'>Alpha</a></td></tr></table>"
            "</td></tr></table>"
        )
        found = blocks(html)
        kinds = {b.kind for b in found}
        assert BlockKind.HEADING in kinds
        assert any("fastener" in b.text for b in found)


class TestTableSpans:
    """`rowspan` and `colspan`, which were ignored entirely until they were measured.

    Ignoring them does not lose formatting, it **misaligns every value**. The header
    `<th rowspan=2>Region</th><th colspan=2>2025</th>` over `<th>Q1</th><th>Q2</th>` used to
    yield rows `('Region','2025')`, `('Q1','Q2')`, `('EU','10','20')` -- so the renderer took
    `Region | 2025` as the header, demoted the real column labels to a body row, and put
    every number under the wrong heading.

    `table-stitcher` was evaluated for this and rejected: it repairs tables fragmented across
    *PDF page breaks*, keys on page numbers, and its own README states `TableMeta` is
    "intentionally lossy -- it reduces a rich table (with rowspan, colspan, multi-row
    headers...) into a pandas DataFrame". The expansion here follows pandas' algorithm
    without the 15 MB dependency, and without its coercion of `'10'` to an int -- this engine
    needs the string for the content hash and the search index.
    """

    SPANNED = (
        "<table>"
        '<tr><th rowspan="2">Region</th><th colspan="2">2025</th></tr>'
        "<tr><th>Q1</th><th>Q2</th></tr>"
        "<tr><td>EU</td><td>10</td><td>20</td></tr>"
        "</table>"
    )

    def test_spans_expand_into_a_rectangular_grid(self) -> None:
        table = next(b for b in blocks(self.SPANNED) if b.kind is BlockKind.TABLE)
        assert table.rows == (("Region", "2025 Q1", "2025 Q2"), ("EU", "10", "20"))

    def test_values_land_under_the_right_heading(self) -> None:
        table = next(b for b in blocks(self.SPANNED) if b.kind is BlockKind.TABLE)
        header, body = table.rows[0], table.rows[1]
        assert dict(zip(header, body, strict=True)) == {
            "Region": "EU",
            "2025 Q1": "10",
            "2025 Q2": "20",
        }

    def test_values_stay_strings(self) -> None:
        """Numbers must not be coerced. The content hash and the index key on the text."""
        table = next(b for b in blocks(self.SPANNED) if b.kind is BlockKind.TABLE)
        assert all(isinstance(cell, str) for row in table.rows for cell in row)

    def test_a_rowspan_reaching_past_the_last_row_is_kept(self) -> None:
        html = (
            "<table><tr><td rowspan='3'>held</td><td>a</td></tr>"
            "<tr><td>b</td></tr></table>"
        )
        table = next(b for b in blocks(html) if b.kind is BlockKind.TABLE)
        assert sum(row.count("held") for row in table.rows) == 3

    def test_an_absurd_span_is_bounded(self) -> None:
        """Untrusted input: `colspan="99999999"` is otherwise a memory-exhaustion primitive."""
        from webgraph.dom.rich import _MAX_SPAN

        html = ('<table><tr><td colspan="99999999">x</td><td>y</td></tr>'
                "<tr><td>a</td><td>b</td></tr></table>")
        table = next(b for b in blocks(html) if b.kind is BlockKind.TABLE)
        # The cap bounds each span, so the row is that plus its remaining real cells --
        # bounded, which is the property that matters, rather than exactly the cap.
        assert len(table.rows[0]) <= _MAX_SPAN + 10

    def test_footer_written_before_the_body_still_renders_last(self) -> None:
        """lxml returns an XPath union in document order, so a single
        `./tr|./thead/tr|./tbody/tr|./tfoot/tr` puts a leading `<tfoot>` in the middle."""
        html = (
            "<table><thead><tr><th>H</th></tr></thead>"
            "<tfoot><tr><td>F</td></tr></tfoot>"
            "<tbody><tr><td>B</td></tr></tbody></table>"
        )
        table = next(b for b in blocks(html) if b.kind is BlockKind.TABLE)
        assert [row[0] for row in table.rows] == ["H", "B", "F"]


class TestNestedDataTables:
    """A data table inside a data table, which used to be hoisted *and* duplicated."""

    NESTED = (
        "<table><thead><tr><th>Outer A</th><th>Outer B</th></tr></thead><tbody>"
        "<tr><td>one</td><td>"
        "<table><thead><tr><th>Inner H</th></tr></thead>"
        "<tbody><tr><td>Inner V</td></tr></tbody></table>"
        "</td></tr>"
        "<tr><td>two</td><td>x</td></tr></tbody></table>"
    )

    def test_inner_rows_are_not_lifted_into_the_outer_table(self) -> None:
        outer = next(b for b in blocks(self.NESTED) if b.kind is BlockKind.TABLE)
        assert all("Inner" not in cell for row in outer.rows for cell in row)

    def test_the_inner_table_becomes_its_own_block(self) -> None:
        tables = [b for b in blocks(self.NESTED) if b.kind is BlockKind.TABLE]
        assert len(tables) == 2
        assert tables[1].rows == (("Inner H",), ("Inner V",))

    def test_inner_text_appears_exactly_once(self) -> None:
        """It used to appear three times: hoisted as two rows, and run together without a
        separator inside the containing cell as `Inner HInner V`."""
        rendered = "\n".join(
            " ".join(cell for row in b.rows for cell in row)
            for b in blocks(self.NESTED)
            if b.kind is BlockKind.TABLE
        )
        assert rendered.count("Inner V") == 1
        assert "Inner HInner V" not in rendered


class TestMediaPlaceholders:
    """Embedded media, kept as a note rather than stripped in silence.

    `SKIP_TAGS` removes `<video>`, `<audio>` and `<iframe>`, which is right for their text --
    an iframe's content is a separate document and a video's children are `<source>` tags.
    What was lost is that they existed at all: a YouTube embed vanished without trace, and
    nothing downstream could tell "this page has no video" from "this page has a video nobody
    transcribed". Only the second is worth returning to, which matters for a consumer building
    notes or a knowledge graph.
    """

    def test_an_iframe_becomes_a_placeholder(self) -> None:
        html = (
            '<iframe src="https://www.youtube.com/embed/abc" '
            'title="Product demo" width="560" height="315"></iframe>'
        )
        media = [b for b in blocks(html) if b.kind is BlockKind.MEDIA]
        assert len(media) == 1
        assert "Product demo" in media[0].text
        assert "not transcribed" in media[0].text
        assert media[0].href == "https://www.youtube.com/embed/abc"

    def test_a_video_source_is_resolved(self) -> None:
        html = (
            '<video title="Tour">'
            '<source src="/media/tour.mp4" type="video/mp4"></video>'
        )
        media = next(b for b in blocks(html) if b.kind is BlockKind.MEDIA)
        assert media.href == "https://example.com/media/tour.mp4"

    def test_subtitle_tracks_are_reported(self) -> None:
        """A `<track kind="captions">` is a transcript already in the markup. The engine does
        not fetch it, and recording where it is makes that a later decision, not a lost one.

        Uses the descendant axis deliberately: libxml2 does not know `<source>` is void, so it
        nests the tracks *inside* it and a child-axis query finds none of them.
        """
        html = (
            '<video title="Tour"><source src="/t.mp4">'
            '<track kind="captions" src="/t-en.vtt" srclang="en">'
            '<track kind="subtitles" src="/t-fr.vtt" srclang="fr"></video>'
        )
        media = next(b for b in blocks(html) if b.kind is BlockKind.MEDIA)
        assert "2 subtitle track(s)" in media.text
        assert "t-en.vtt" in media.text

    def test_a_tracking_beacon_is_not_media(self) -> None:
        """A 1x1 iframe is analytics. Judged only when the markup declares a size -- an
        undeclared one is sized by CSS and could be anything."""
        html = '<iframe src="https://a.example/px" width="1" height="1"></iframe>'
        assert not [b for b in blocks(html) if b.kind is BlockKind.MEDIA]

    def test_the_placeholder_renders_as_an_aside(self) -> None:
        """Italic, not a link or an image: it is a note *about* the document rather than
        content in it, and must not be mistaken for something that was transcribed."""
        html = '<p>Before.</p><video src="/v.mp4" title="Demo"></video>'
        rendered = md(html)
        assert "*[video" in rendered
        assert "not transcribed" in rendered

    def test_surrounding_prose_is_untouched(self) -> None:
        html = (
            "<p>Before the video.</p>"
            '<video src="/v.mp4"></video>'
            "<p>After the video.</p>"
        )
        texts = [b.text for b in blocks(html)]
        assert "Before the video." in texts
        assert "After the video." in texts


class TestDollarEscaping:
    """A literal `$` must not be readable as a maths delimiter.

    Every Markdown dialect that carries mathematics delimits it with `$...$`, so an
    unescaped currency amount silently becomes a formula -- and a *pair* of them in one
    paragraph silently becomes a formula wrapping the prose between them. Measured on
    WebMainBench: 18 of 200 pages containing no mathematics at all were scored as emitting
    formulas for exactly this reason. The corpus's own ground truth escapes them, 1,249
    times across 165 pages.
    """

    def test_currency_is_escaped(self) -> None:
        out = md("<p>It spends $29.8 billion, a surplus of $344 million.</p>")
        assert r"\$29.8" in out
        assert r"\$344" in out

    def test_a_pair_no_longer_reads_as_one_formula(self) -> None:
        """The failure shape, as the metric sees it: between two bare dollars lies prose,
        and a maths-aware reader takes all of it as a formula."""
        import re

        out = md("<p>from $5 to $10 per unit</p>")
        assert not re.search(r"(?<!\\)\$(.*?)(?<!\\)\$", out)

    def test_an_already_escaped_dollar_is_not_escaped_twice(self) -> None:
        assert r"\\$" not in md(r"<p>costs \$5 today</p>")

    def test_real_mathematics_is_left_alone(self) -> None:
        """The rule the first version of this got wrong. Escaping *every* dollar removed the
        false formulas and the true ones together: the corpus's formula column lost 152 of
        its 282 pages. Money is written `$29.8`; mathematics is written `$\frac…` or `$ x`."""
        for body, keep in (
            (r"<p>Let $\frac{a}{b}$ be the ratio.</p>", r"$\frac{a}{b}$"),
            ("<p>where $ x $ is the input</p>", "$ x $"),
            ("<p>display $$y = mx + c$$ here</p>", "$$y = mx + c$$"),
        ):
            assert keep in md(body), body

    def test_the_two_cases_can_share_a_paragraph(self) -> None:
        out = md(r"<p>It costs $5 when $\alpha$ is small.</p>")
        assert r"\$5" in out
        assert r"$\alpha$" in out

    def test_it_applies_inside_a_table(self) -> None:
        out = md("<table><tr><th>Item</th><th>Price</th></tr>"
                 "<tr><td>Widget</td><td>$5.00</td></tr></table>")
        assert r"\$5.00" in out

    def test_it_applies_inside_a_link(self) -> None:
        out = md('<p><a href="/b">Buy</a> for $9 today</p>')
        assert r"\$9" in out
        assert "[Buy](" in out

    def test_plain_text_output_is_untouched(self) -> None:
        """`document.text` is not Markdown and nothing in it is a delimiter."""
        document = build_document("<html><body><p>It costs $5</p></body></html>", BASE)
        assert document.text == "It costs $5"

    def test_mathematics_may_also_begin_with_a_digit(self) -> None:
        r"""The cost of the digit lookahead, and the reason it is not the whole rule.

        `$0.07^{7}$` is mathematics. Escaping its opening delimiter left the closing one to
        pair with something far away, and a page whose ground truth is the single formula
        `0.07` came back as a formula containing the sentence in front of it. A backslash,
        caret, underscore or brace inside the span is LaTeX; prices have none of them.
        """
        assert "$0.07^{7}$" in md("<p>then $0.07^{7}$ follows</p>")
        assert r"$lpha_1$" in md(r"<p>and $lpha_1$ too</p>")

    def test_a_price_and_an_equation_in_one_sentence(self) -> None:
        out = md(r"<p>costs $5 when $lpha$ is small</p>")
        assert r"\$5" in out
        assert r"$lpha$" in out

    def test_a_span_with_no_latex_in_it_is_still_money(self) -> None:
        """Two prices in a sentence have nothing mathematical between them, so both escape."""
        out = md("<p>spends $29.8 billion and $344 million more</p>")
        assert out.count(r"\$") == 2


class TestComplexTablesKeepTheirMarkup:
    """Pipe syntax cannot express a merged cell, so a table that merges keeps its own markup.

    This is not a formatting preference. `<td colspan="3">` rendered as pipes drops the merge
    and shifts every value beneath it into the wrong column, which corrupts the data. Markdown
    permits inline HTML, so the honest rendering of a spanning table is the table. Measured on
    WebMainBench: on pages whose ground truth holds an HTML table, a pipe rendering caps at
    0.445 where the table's own markup reaches 1.000.
    """

    def test_a_plain_grid_still_renders_as_pipes(self) -> None:
        """The common case, and the one a reader actually wants to look at."""
        out = md("<table><tr><th>City</th><th>Pop</th></tr>"
                 "<tr><td>Leeds</td><td>793000</td></tr></table>")
        assert "| City | Pop |" in out
        assert "| --- | --- |" in out
        assert "<table" not in out

    def test_a_colspan_keeps_the_markup(self) -> None:
        out = md("<table><tr><td>Region</td><td colspan=\"2\">2025</td></tr>"
                 "<tr><td>EU</td><td>10</td><td>20</td></tr></table>")
        assert "<table" in out
        assert 'colspan="2"' in out

    def test_a_rowspan_keeps_the_markup(self) -> None:
        out = md("<table><tr><td rowspan=\"2\">Region</td><td>Q1</td></tr>"
                 "<tr><td>Q2</td></tr></table>")
        assert 'rowspan="2"' in out

    def test_a_nested_table_keeps_the_markup(self) -> None:
        """Whichever of the two it is, a pipe grid cannot hold a table inside a cell."""
        out = md("<table><tr><th>a</th></tr><tr><td><table><tr><td>x</td></tr>"
                 "</table></td></tr></table>")
        assert out.count("<table") >= 1

    def test_only_structure_survives(self) -> None:
        """Real tables carry styles, widths, tracking ids and translation bookkeeping. None
        of it is content, and all of it would otherwise land in the output verbatim."""
        out = md('<table style="width:0px" width="0" data-anno-uid="anno-7" class="tbl">'
                 '<tr><td colspan="2" style="color:red" id="c1">x</td></tr>'
                 '<tr><td>a</td><td>b</td></tr></table>')
        assert 'colspan="2"' in out
        for noise in ("style=", "data-anno-uid", "width=", "class=", "id="):
            assert noise not in out, noise

    def test_a_percentage_colspan_is_not_a_span(self) -> None:
        """`colspan="50%"` appears on real pages. It is not a span and must not force the
        markup path for a table pipes can express perfectly well."""
        out = md('<table><tr><th>a</th><th>b</th></tr>'
                 '<tr><td colspan="50%">x</td><td>y</td></tr></table>')
        assert "<table" not in out
        assert "| a | b |" in out

    def test_span_of_one_is_not_a_span(self) -> None:
        out = md('<table><tr><th>a</th></tr><tr><td colspan="1" rowspan="1">x</td></tr></table>')
        assert "<table" not in out

    def test_the_rows_are_still_available_to_everything_else(self) -> None:
        """`table_html` is a rendering concern. The grid still feeds the content hash,
        deduplication, reading order and the search index, so it must survive alongside."""
        found = blocks('<table><tr><td rowspan="2">Region</td><td>Q1</td></tr>'
                       "<tr><td>Q2</td></tr></table>")
        table = next(b for b in found if b.kind is BlockKind.TABLE)
        assert table.table_html is not None
        assert table.rows
        assert "Region" in table.text


class TestLinksInsideAPreservedTable:
    """A cell's link target is often the point of the cell, and nothing else can carry it.

    Verified against Hacker News, whose front page is a table of 30 rows where the
    destination of each row is the single most important fact on the page. Preserving the
    table's markup without `<a href>` returned all 30 stories and **zero links** -- text that
    reads correctly and is useless to anything that wanted the articles.
    """

    HN = (
        '<table><tbody>'
        '<tr><td>1.</td><td><a href="/vote?id=1">up</a></td>'
        '<td><a href="https://example.org/post">A story</a> '
        '(<a href="/from?site=example.org">example.org</a>)</td></tr>'
        '<tr><td colspan="2"></td>'
        '<td>244 points by <a href="/user?id=alice">alice</a> | '
        '<a href="/item?id=1">40 comments</a></td></tr>'
        "</tbody></table>"
    )

    def test_the_markup_is_preserved_because_of_the_colspan(self) -> None:
        assert "<table" in md(self.HN)

    def test_link_targets_survive(self) -> None:
        out = md(self.HN)
        assert 'href="https://example.org/post"' in out
        assert "A story" in out

    def test_relative_targets_are_made_absolute(self) -> None:
        """A preserved table travels without the page it came from, so `/user?id=alice`
        in it points nowhere."""
        out = md(self.HN)
        assert f'href="{BASE.rsplit("/", 1)[0]}/user?id=alice"' in out or "example.com/user?id=alice" in out

    def test_noise_attributes_still_go(self) -> None:
        out = md('<table><tr><td colspan="2" class="x" style="color:red">'
                 '<a href="/a" class="storylink" onclick="x()">t</a></td></tr>'
                 "<tr><td>a</td><td>b</td></tr></table>")
        assert 'colspan="2"' in out
        assert "href=" in out
        for noise in ("class=", "style=", "onclick="):
            assert noise not in out, noise

    def test_an_anchor_with_no_destination_is_not_a_link(self) -> None:
        out = md('<table><tr><td colspan="2"><a name="top">x</a></td></tr>'
                 "<tr><td>a</td><td>b</td></tr></table>")
        assert "<a" not in out
        assert "x" in out


class TestBlockBoundaries:
    """Words on either side of a block boundary stay two words.

    Every fixture here is a shape found on a live page during a hands-on test of the
    product, not an invented one. The common cause was rendering a container's rich text
    from its whole subtree while its plain text correctly skipped the block children -- so
    the Markdown carried every child glued together, and then carried each child again.
    """

    def test_a_heading_with_a_block_child_keeps_the_space(self) -> None:
        """react.dev: `<h4><div>Example 1 of 5<span>: </span></div>Connecting ...</h4>`.

        The separating space lived at the end of the span, and normalising each child on its
        own deleted it before the parent ever saw it.
        """
        out = md('<h4><div>Example 1 of 5<span>: </span></div>Connecting to a chat server</h4>')
        assert "Example 1 of 5: Connecting to a chat server" in out
        assert "5:Connecting" not in out

    def test_paragraphs_inside_a_container_are_not_fused(self) -> None:
        """Hacker News: a comment is bare text followed by `<p>` siblings in one div."""
        out = md(
            '<div class="commtext">worth around $5trn.<p>Note that the Fed has more.</p>'
            "<p>The real comparison is different.</p></div>"
        )
        assert "trn.Note" not in out
        assert "more.The" not in out

    def test_a_container_does_not_repeat_its_children(self) -> None:
        """Hacker News post body: emitted once fused, then once per paragraph."""
        out = md(
            '<div class="toptext">Hey community!<p>But here is the twist.</p>'
            "<p>I believe in open source.</p></div>"
        )
        assert out.count("But here is the twist") == 1
        assert out.count("I believe in open source") == 1
        assert "Hey community!" in out

    def test_a_nested_list_is_not_crammed_into_its_parent_item(self) -> None:
        """react.dev table of contents: the last item had sub-items, and they arrived glued
        onto it as `[Troubleshooting](#t)[My Effect runs twice](#a)[...]`, then again as
        their own items."""
        out = md(
            '<ul><li><a href="#t">Troubleshooting</a><ul>'
            '<li><a href="#a">My Effect runs twice</a></li>'
            '<li><a href="#b">My Effect runs after every render</a></li>'
            "</ul></li></ul>"
        )
        assert "Troubleshooting](https://example.com/page#t)[My Effect" not in out
        assert out.count("My Effect runs twice") == 1

    def test_default_block_tags_separate_even_without_a_render(self) -> None:
        """On a static fetch no browser has marked the line boxes, so the tag has to."""
        out = md("<div><div>First line</div><div>Second line</div></div>")
        assert "First line" in out and "Second line" in out
        assert "lineSecond" not in out

    def test_inline_siblings_still_run_together(self) -> None:
        """`<b>bold</b><i>italic</i>` genuinely renders as one word; that must not change."""
        out = md("<p>ab<b>cd</b><i>ef</i>gh</p>")
        assert "ab**cd***ef*gh" in out

    def test_a_javascript_link_keeps_its_text_and_loses_its_target(self) -> None:
        """`[[-]](javascript:void(0))` on every Hacker News comment is a toggle, not a link."""
        out = md('<p><a href="javascript:void(0)">[-]</a> Real <a href="/x">link</a></p>')
        assert "javascript:" not in out
        assert "[-]" in out
        assert "[link](https://example.com/x)" in out


class TestCodeLanguage:
    @pytest.mark.parametrize(
        ("html", "language"),
        [
            ('<pre class="language-python"><code>x = 1</code></pre>', "python"),
            ('<pre><code class="lang-ts">let x</code></pre>', "ts"),
            ('<pre class="brush: js notranslate"><code>let x</code></pre>', "js"),
            ('<pre data-language="rust"><code>let x;</code></pre>', "rust"),
            ("<pre><code>plain</code></pre>", None),
        ],
    )
    def test_every_spelling_a_site_uses(self, html: str, language: str | None) -> None:
        """MDN writes `brush: js`; Prism writes `language-js`; Shiki writes `data-language`."""
        code = [b for b in blocks(html) if b.kind is BlockKind.CODE]
        assert code and code[0].language == language


class TestHiddenTwins:
    """Responsive markup renders one label twice; the browser shows one, and so must we."""

    def test_hidden_twin_of_a_visible_sibling_is_dropped(self) -> None:
        html = (
            '<main><p><span class="md:hidden">NEW</span>'
            '<span class="hidden md:block" data-wg-hidden="1">NEW</span> arrivals</p></main>'
        )
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == ["NEW arrivals"]

    def test_hidden_element_with_its_own_words_stays(self) -> None:
        html = (
            '<main><p>Summary</p>'
            '<div data-wg-hidden="1"><p>Collapsed body only the disclosure shows.</p></div></main>'
        )
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == ["Summary", "Collapsed body only the disclosure shows."]

    def test_unmarked_static_fetch_is_untouched(self) -> None:
        html = '<main><p><span>NEW</span> <span>NEW</span></p></main>'
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == ["NEW NEW"]


class TestOrphanRuns:
    """A container's own text is emitted where it sits among the child blocks."""

    def test_text_between_child_blocks_keeps_its_place(self) -> None:
        html = (
            "<main><div>"
            "<p>Opening sentence of the post.</p>"
            "<p>Second paragraph of the post.</p>"
            "<em>Caption under the second paragraph.</em><br>"
            "<p>Third paragraph of the post.</p>"
            "Closing words after everything."
            "</div></main>"
        )
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == [
            "Opening sentence of the post.",
            "Second paragraph of the post.",
            "Caption under the second paragraph.",
            "Third paragraph of the post.",
            "Closing words after everything.",
        ]
        caption = blocks[2]
        assert caption.xpath.endswith("/div/em"), "measured by the element that carries it"
        assert caption.rich_text == "*Caption under the second paragraph.*"
        assert blocks[4].xpath.endswith("/div/text()[2]"), "bare text has no element to borrow"

    def test_leading_text_precedes_the_first_child_block(self) -> None:
        html = "<main><div>Lead-in words.<p>Body paragraph here.</p></div></main>"
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == ["Lead-in words.", "Body paragraph here."]

    def test_trailing_text_after_a_nested_subtree(self) -> None:
        html = (
            "<main><div><div><p>Inner paragraph.</p><span>deep <b>tail</b></span></div>"
            "Outer closing line.</div></main>"
        )
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == ["Inner paragraph.", "deep tail", "Outer closing line."]


class TestButtons:
    def test_hidden_copy_button_is_not_a_paragraph(self) -> None:
        html = (
            '<main><p>For example:</p><div><button data-wg-hidden="opacity">Copy</button>'
            "<pre>x = 1</pre></div></main>"
        )
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == ["For example:", "x = 1"]

    def test_visible_button_stays_however_short(self) -> None:
        html = "<main><p>Intro paragraph.</p><button>Show more</button></main>"
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == ["Intro paragraph.", "Show more"]

    def test_accordion_question_in_a_button_is_kept(self) -> None:
        html = (
            "<main><div><button>How long does shipping take to reach me?</button>"
            "<div><p>Three to five days.</p></div></div></main>"
        )
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == [
            "How long does shipping take to reach me?",
            "Three to five days.",
        ]
