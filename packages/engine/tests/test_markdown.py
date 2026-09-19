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

    def test_a_link_that_is_only_an_image_keeps_its_target(self) -> None:
        """spacejam.com/1996: twelve `<a href><img></a>` planets, every href dropped. A
        link with words of its own belongs to the words; a `javascript:` target is not
        a destination."""
        out = md('<a href="/jam.htm"><img src="/planet.gif" alt="Jam"></a>')
        assert "[![Jam](https://example.com/planet.gif)](https://example.com/jam.htm)" in out
        out = md('<p><a href="/t"><img src="/i.png" alt="i"> with words</a></p>')
        assert "[with words](https://example.com/t)" in out and "[![i]" not in out
        out = md('<a href="javascript:void(0)"><img src="/j.png" alt="j"></a>')
        assert "![j](https://example.com/j.png)" in out and "[![j]" not in out

    def test_relative_paths_resolved(self) -> None:
        out = md('<img src="../img/a.png" alt="A">')
        assert "https://example.com/img/a.png" in out

    def test_lazy_loaded_src_recovered(self) -> None:
        """Lazy-loading markup hides the real image behind data attributes."""
        out = md('<img data-src="/real.png" alt="Real">')
        assert "https://example.com/real.png" in out

    def test_srcset_gives_the_largest(self) -> None:
        """`src` is the smallest of the set, the fallback for browsers that never read it;
        the page's image is the largest. Widths, densities, and a bare candidate as 1x."""
        out = md('<img srcset="/small.png 480w, /big.png 1024w" alt="S">')
        assert "https://example.com/big.png" in out and "small.png" not in out
        out = md('<img src="/one.png" srcset="/one.png, /two.png 2x, /three.png 3x" alt="D">')
        assert "https://example.com/three.png" in out
        out = md('<img src="/fallback.png" srcset="/w800.png 800w, /w400.png 400w" alt="W">')
        assert "https://example.com/w800.png" in out and "fallback.png" not in out

    def test_a_lazy_srcset_is_read_too(self) -> None:
        out = md('<img data-srcset="/l1.png 1x, /l2.png 2x" alt="L">')
        assert "https://example.com/l2.png" in out

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

    def test_a_link_in_a_cell_is_a_link(self) -> None:
        """craigslist.org/about/best/all is a table of `<td><a href>title</a></td>` -- the
        links are the page -- and every one was dropped; `Block.rich_rows` carries the
        cells' inline Markdown, a pipe inside is escaped, a plain grid carries nothing twice."""
        out = md(
            "<table><tr><th>Title</th><th>Where</th></tr>"
            '<tr><td><a href="/x/1">Free Guinea Pig Lawn Trimming</a></td><td><b>SF</b> bay | area</td></tr></table>'
        )
        assert (
            "| [Free Guinea Pig Lawn Trimming](https://example.com/x/1) | **SF** bay \\| area |"
            in out
        )
        document = build_document(self.HTML, "https://example.com/")
        assert document.blocks[0].rich_rows == ()
        # With links off the plain cells render: WebMainBench scores that way, and #68
        # put `[text](href)` into every cell regardless (table_edit 0.390 -> 0.338).
        linked = build_document(
            '<table><tr><th>T</th></tr><tr><td><a href="/x/1">Title</a></td></tr></table>',
            "https://example.com/",
        )
        assert "| Title |" in to_markdown(linked, options=MarkdownOptions(include_links=False))

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

        doc = build_document('<html><body><p>See <a href="/d">docs</a></p></body></html>', BASE)
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

    def test_an_old_mediawiki_editsection_is_a_control(self) -> None:
        """cppreference.com: `<span class="editsection noprint">[edit]</span>` beside every
        heading and table row, 56 on the `std::vector` page."""
        out = md(
            '<h3>Member functions<span class="editsection noprint plainlinks">[<a href="/w/x">edit</a>]</span></h3><p>Body text here.</p>'
        )
        assert "### Member functions" in out and "edit" not in out

    def test_a_glyph_only_fragment_anchor_is_a_permalink_whatever_its_class(self) -> None:
        """php.net's `<a class="genanchor" href="#…"> ¶</a>` is added by a script, so the
        rendered heading read "Description ¶" beside the static "Description" and the union
        kept both. The glyph and the fragment href are the thing itself."""
        out = md('<h3 class="title">Description<a class="genanchor" href="#refsect1"> ¶</a></h3>')
        assert "### Description" in out and "¶" not in out
        out = md('<p>See <a href="#top">back to top</a> and note <a href="#n1">1</a>.</p>')
        assert "[back to top]" in out and "[1]" in out

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

        root = parse_html(
            "<html><body><table><tr><td><table><tr><td>x</td></tr>"
            "</table></td></tr></table></body></html>"
        )
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

        root = parse_html(
            "<html><body><table><tr><td>Home</td><td>About</td></tr></table></body></html>"
        )
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

        root = parse_html(
            "<html><body><table><tr><td>Leeds</td><td>793000</td></tr>"
            "<tr><td>Sheffield</td><td>556000</td></tr></table></body></html>"
        )
        assert not is_layout_table(root.xpath("//table")[0])

    def test_a_header_still_overrides_the_shape_test(self) -> None:
        """A declared header is the page saying "this is data", and it is trusted over any
        inference this module makes from shape."""
        from webgraph.dom.blocks import parse_html
        from webgraph.dom.rich import is_layout_table

        root = parse_html(
            "<html><body><table><tr><th>Plan</th></tr><tr><td>Pro</td></tr></table></body></html>"
        )
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
        html = "<table><tr><td rowspan='3'>held</td><td>a</td></tr><tr><td>b</td></tr></table>"
        table = next(b for b in blocks(html) if b.kind is BlockKind.TABLE)
        assert sum(row.count("held") for row in table.rows) == 3

    def test_an_absurd_span_is_bounded(self) -> None:
        """Untrusted input: `colspan="99999999"` is otherwise a memory-exhaustion primitive."""
        from webgraph.dom.rich import _MAX_SPAN

        html = (
            '<table><tr><td colspan="99999999">x</td><td>y</td></tr>'
            "<tr><td>a</td><td>b</td></tr></table>"
        )
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
        html = '<video title="Tour"><source src="/media/tour.mp4" type="video/mp4"></video>'
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

    def test_a_frame_the_browser_gave_no_box_is_not_media(self) -> None:
        """The measured form of the beacon rule: Shopify mounts its web-pixel sandboxes as
        0x0 iframes with no declared size (six on an allbirds.com product page), and the
        browser reports no box for them. A frame with a box stays."""
        from webgraph.pipeline import build_document
        from webgraph.types import Rect

        html = (
            "<html><body><p>The page's one paragraph, long enough to be measured.</p>"
            '<iframe src="https://shop.example/web-pixels/sandbox"></iframe>'
            '<iframe src="https://www.youtube.com/embed/abc" title="Demo"></iframe>'
            "</body></html>"
        )
        geometry = {
            "/html/body/p": Rect(x=0, y=0, width=800, height=20),
            "/html/body/iframe[2]": Rect(x=0, y=40, width=560, height=315),
        }
        doc = build_document(html, "https://example.com/", geometry=geometry)
        media = [b for b in doc.blocks if b.kind is BlockKind.MEDIA]
        assert [m.href for m in media] == ["https://www.youtube.com/embed/abc"]
        # Unmeasured, both are kept: a static parse has no box for anything.
        static = build_document(html, "https://example.com/")
        assert len([b for b in static.blocks if b.kind is BlockKind.MEDIA]) == 2

    def test_a_frame_the_browser_hid_is_not_media(self) -> None:
        html = (
            '<iframe src="https://a.example/player" title="Player" width="560" height="315" '
            "data-wg-hidden='display'></iframe>"
        )
        assert not [b for b in blocks(html) if b.kind is BlockKind.MEDIA]

    def test_the_placeholder_renders_as_an_aside(self) -> None:
        """Italic, not a link or an image: it is a note *about* the document rather than
        content in it, and must not be mistaken for something that was transcribed."""
        html = '<p>Before.</p><video src="/v.mp4" title="Demo"></video>'
        rendered = md(html)
        assert "*[video" in rendered
        assert "not transcribed" in rendered

    def test_surrounding_prose_is_untouched(self) -> None:
        html = '<p>Before the video.</p><video src="/v.mp4"></video><p>After the video.</p>'
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
        out = md(
            "<table><tr><th>Item</th><th>Price</th></tr>"
            "<tr><td>Widget</td><td>$5.00</td></tr></table>"
        )
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


class TestLeadingGreaterThan:
    """A `>` opening a line must not be readable as a blockquote it never was.

    Reported live: a paragraph beginning with a literal `>` (source text, or an `&gt;`
    entity -- lxml decodes both to the same character) rendered as a bare `>` at the start
    of a Markdown line, which every downstream reader, including the web app's own preview,
    takes as a blockquote marker.
    """

    def test_a_leading_angle_bracket_is_escaped(self) -> None:
        out = md("<p>&gt; 90% pass on the first try</p>")
        assert out.startswith(r"\> 90%")

    def test_a_literal_leading_bracket_is_escaped_the_same_way(self) -> None:
        out = md("<p>> 90% pass on the first try</p>")
        assert out.startswith(r"\> 90%")

    def test_a_mid_line_angle_bracket_is_left_alone(self) -> None:
        """Unambiguous in Markdown: only a line-opening `>` is the blockquote marker."""
        out = md("<p>a &gt; b, always</p>")
        assert "a > b, always" in out
        assert r"\>" not in out

    def test_a_real_blockquote_is_unaffected(self) -> None:
        """The engine's own `> ` prefix for an actual quoted block is not double-escaped."""
        out = md("<blockquote><p>as measured</p></blockquote>")
        assert out.strip() == "> as measured"

    def test_it_applies_inside_a_list_item(self) -> None:
        out = md("<ul><li>&gt; 5 remaining</li></ul>")
        assert r"- \> 5 remaining" in out

    def test_it_applies_inside_a_heading(self) -> None:
        out = md("<h2>&gt; average</h2>")
        assert out.strip() == r"## \> average"

    def test_it_applies_to_the_rich_inline_form_too(self) -> None:
        out = md('<p>&gt; see <a href="/b">details</a></p>')
        assert out.startswith(r"\> see")
        assert "[details](" in out


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
        out = md(
            "<table><tr><th>City</th><th>Pop</th></tr>"
            "<tr><td>Leeds</td><td>793000</td></tr></table>"
        )
        assert "| City | Pop |" in out
        assert "| --- | --- |" in out
        assert "<table" not in out

    def test_a_colspan_keeps_the_markup(self) -> None:
        out = md(
            '<table><tr><td>Region</td><td colspan="2">2025</td></tr>'
            "<tr><td>EU</td><td>10</td><td>20</td></tr></table>"
        )
        assert "<table" in out
        assert 'colspan="2"' in out

    def test_a_rowspan_keeps_the_markup(self) -> None:
        out = md(
            '<table><tr><td rowspan="2">Region</td><td>Q1</td></tr><tr><td>Q2</td></tr></table>'
        )
        assert 'rowspan="2"' in out

    def test_a_nested_table_keeps_the_markup(self) -> None:
        """Whichever of the two it is, a pipe grid cannot hold a table inside a cell."""
        out = md(
            "<table><tr><th>a</th></tr><tr><td><table><tr><td>x</td></tr></table></td></tr></table>"
        )
        assert out.count("<table") >= 1

    def test_only_structure_survives(self) -> None:
        """Real tables carry styles, widths, tracking ids and translation bookkeeping. None
        of it is content, and all of it would otherwise land in the output verbatim."""
        out = md(
            '<table style="width:0px" width="0" data-anno-uid="anno-7" class="tbl">'
            '<tr><td colspan="2" style="color:red" id="c1">x</td></tr>'
            "<tr><td>a</td><td>b</td></tr></table>"
        )
        assert 'colspan="2"' in out
        for noise in ("style=", "data-anno-uid", "width=", "class=", "id="):
            assert noise not in out, noise

    def test_a_percentage_colspan_is_not_a_span(self) -> None:
        """`colspan="50%"` appears on real pages. It is not a span and must not force the
        markup path for a table pipes can express perfectly well."""
        out = md(
            "<table><tr><th>a</th><th>b</th></tr>"
            '<tr><td colspan="50%">x</td><td>y</td></tr></table>'
        )
        assert "<table" not in out
        assert "| a | b |" in out

    def test_span_of_one_is_not_a_span(self) -> None:
        out = md('<table><tr><th>a</th></tr><tr><td colspan="1" rowspan="1">x</td></tr></table>')
        assert "<table" not in out

    def test_the_rows_are_still_available_to_everything_else(self) -> None:
        """`table_html` is a rendering concern. The grid still feeds the content hash,
        deduplication, reading order and the search index, so it must survive alongside."""
        found = blocks(
            '<table><tr><td rowspan="2">Region</td><td>Q1</td></tr><tr><td>Q2</td></tr></table>'
        )
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
        "<table><tbody>"
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
        assert (
            f'href="{BASE.rsplit("/", 1)[0]}/user?id=alice"' in out
            or "example.com/user?id=alice" in out
        )

    def test_noise_attributes_still_go(self) -> None:
        out = md(
            '<table><tr><td colspan="2" class="x" style="color:red">'
            '<a href="/a" class="storylink" onclick="x()">t</a></td></tr>'
            "<tr><td>a</td><td>b</td></tr></table>"
        )
        assert 'colspan="2"' in out
        assert "href=" in out
        for noise in ("class=", "style=", "onclick="):
            assert noise not in out, noise

    def test_an_anchor_with_no_destination_is_not_a_link(self) -> None:
        out = md(
            '<table><tr><td colspan="2"><a name="top">x</a></td></tr>'
            "<tr><td>a</td><td>b</td></tr></table>"
        )
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
        out = md("<h4><div>Example 1 of 5<span>: </span></div>Connecting to a chat server</h4>")
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
            "<main><p>Summary</p>"
            '<div data-wg-hidden="1"><p>Collapsed body only the disclosure shows.</p></div></main>'
        )
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == ["Summary", "Collapsed body only the disclosure shows."]

    def test_unmarked_static_fetch_is_untouched(self) -> None:
        html = "<main><p><span>NEW</span> <span>NEW</span></p></main>"
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == ["NEW NEW"]

    def test_a_group_of_hidden_siblings_saying_what_the_visible_ones_say_is_dropped(self) -> None:
        """linear.app's <h1>: four `show-mobile` spans (display none on a laptop) and two
        `hide-mobile` spans (opacity 0 until the entrance animation) carry the same headline
        with different line breaks. No hidden span has a single visible twin; together they
        do. Opacity 0 counts as shown: a scroll animation starts its text there."""
        html = (
            "<main><h1><span>"
            '<span data-wg-hidden="display">The product</span><span data-wg-hidden="display"> </span>'
            '<span data-wg-hidden="display">development</span><span data-wg-hidden="display"> </span>'
            '<span data-wg-hidden="display">system for teams</span><span data-wg-hidden="display"> and agents</span>'
            '<span data-wg-hidden="opacity">The product development</span> '
            '<span data-wg-hidden="opacity">system for teams and agents</span>'
            "</span></h1><p>Purpose-built for planning.</p></main>"
        )
        blocks = extract_rich_blocks(parse_html(html), "https://example.com/")
        assert [b.text for b in blocks] == [
            "The product development system for teams and agents",
            "Purpose-built for planning.",
        ]

    def test_a_clipped_copy_is_screen_reader_only_whatever_its_class(self) -> None:
        """The renderer marks a 1px, overflow-hidden box `clipped`; the CSS-module class
        (`Fzcv4W_visuallyHidden`) is one the name rule cannot know."""
        html = (
            "<main><h1><span>The product development system</span>"
            '<span class="Fzcv4W_visuallyHidden" data-wg-hidden="clipped">The product development system</span></h1>'
            "<p>Body.</p></main>"
        )
        assert [b.text for b in extract_rich_blocks(parse_html(html), "https://x.test/")] == [
            "The product development system",
            "Body.",
        ]
        kept = extract_rich_blocks(parse_html(html), "https://x.test/", include_hidden_text=True)
        assert kept[0].text.startswith("The product development system")


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


class TestScreenReaderOnly:
    """ikea.com: every variant swatch carries `<span class="sr-only">Option: BILLY, Bookcase,
    dark brown oak effect...</span>` -- 1,214 words on one category page that no sighted
    reader sees. Measured on WCXB dev, stripping them: collection +0.017, product +0.003."""

    def test_sr_only_labels_are_stripped(self) -> None:
        html = (
            '<main><p><a href="/p/1"><span class="sr-only">Option: BILLY, Bookcase, white</span>'
            '<img src="/b.jpg" alt="A tall white bookcase"></a> <span>$59.99</span></p>'
            '<p><span class="visually-hidden">Skip to main content</span>Real sentence here.</p></main>'
        )
        blocks = extract_rich_blocks(parse_html(html), "https://shop.test/")
        texts = [b.text for b in blocks if b.kind is not BlockKind.IMAGE]
        assert texts == ["$59.99", "Real sentence here."]

    def test_a_screen_reader_only_headline_is_kept(self) -> None:
        html = '<main><h1 class="sr-only">The complete guide to shelving units</h1><p>Body text of the guide.</p></main>'
        blocks = extract_rich_blocks(parse_html(html), "https://shop.test/")
        assert [b.text for b in blocks] == [
            "The complete guide to shelving units",
            "Body text of the guide.",
        ]

    def test_include_hidden_text_keeps_the_labels_and_the_edit_controls(self) -> None:
        """A caller that wants every string in the DOM asks for it; the default stays. The
        permalink glyph goes either way: it is a control's glyph, not text."""
        html = (
            '<main><p><a href="/p/1"><span class="sr-only">Option: BILLY, Bookcase, white</span>'
            '<img src="/b.jpg" alt=""></a> <span>$59.99</span></p>'
            '<h2>Delivery <span class="mw-editsection">[edit]</span><a class="headerlink" href="#d">¶</a></h2>'
            '<p><span class="visually-hidden">Skip to main content</span> Real sentence here.</p></main>'
        )
        kept = extract_rich_blocks(parse_html(html), "https://shop.test/", include_hidden_text=True)
        texts = [b.text for b in kept if b.kind is not BlockKind.IMAGE]
        assert texts == [
            "Option: BILLY, Bookcase, white $59.99",
            "Delivery [edit]",
            "Skip to main content Real sentence here.",
        ]
        default = extract_rich_blocks(parse_html(html), "https://shop.test/")
        assert [b.text for b in default if b.kind is not BlockKind.IMAGE] == [
            "$59.99",
            "Delivery",
            "Real sentence here.",
        ]

    def test_the_flag_reaches_build_document(self) -> None:
        html = (
            '<main><p><span class="sr-only">Opens in a new window</span> Read the guide.</p></main>'
        )
        assert build_document(html, "https://x.test/").text == "Read the guide."
        assert (
            build_document(html, "https://x.test/", include_hidden_text=True).text
            == "Opens in a new window Read the guide."
        )


class TestClosedDialogs:
    """karnataka.gov.in: nine Bootstrap modals (Privacy Policy, Terms, Help, Site Map…) in
    `.modal.fade` divs at `display: none` -- 2,100 words, three times what the page shows --
    all of it in the content. A closed dialog is a different screen, not collapsed content."""

    def test_closed_dialogs_go_open_ones_stay(self) -> None:
        html = (
            "<main><p>The page itself says this.</p>"
            '<div role="dialog" data-wg-hidden="display"><h2>Privacy Policy</h2><p>Thanks for visiting the website of the Government.</p></div>'
            '<div role="dialog" aria-hidden="true"><p>Terms and conditions of this website apply to every visitor.</p></div>'
            '<div role="alertdialog" hidden><p>Your session is about to expire.</p></div>'
            "<dialog><p>A dialog element that is not open.</p></dialog>"
            "<dialog open><p>A dialog element that is open, and on the page.</p></dialog>"
            '<div role="dialog"><p>A dialog the renderer found showing: a cookie prompt.</p></div>'
            "</main>"
        )
        texts = [b.text for b in extract_rich_blocks(parse_html(html), "https://gov.test/")]
        assert texts == [
            "The page itself says this.",
            "A dialog element that is open, and on the page.",
            "A dialog the renderer found showing: a cookie prompt.",
        ]


class TestUnreachableHidden:
    """karnataka.gov.in hides a 3,144-word "Recent Govt Announcements" div beside a 726-word
    page and nothing opens it. Hidden content stays only when a control on the page reaches
    it -- by id, by `role="tabpanel"`, or inside `<details>`."""

    def test_hidden_content_nothing_opens_is_dropped(self) -> None:
        html = (
            "<main><p>Visible words on the page.</p>"
            '<div data-wg-hidden="display"><p>Recent announcements that no button, tab or link opens.</p></div>'
            "</main>"
        )
        texts = [b.text for b in extract_rich_blocks(parse_html(html), "https://gov.test/")]
        assert texts == ["Visible words on the page."]

    def test_hidden_content_a_control_opens_stays(self) -> None:
        html = (
            "<main><p>Visible words on the page.</p>"
            '<button aria-controls="faq1" aria-expanded="false">How do I apply?</button>'
            '<div id="faq1" data-wg-hidden="display"><p>Apply online with your passport number.</p></div>'
            '<a href="#more">Show more</a><div id="more" data-wg-hidden="display"><p>The rest of the notice.</p></div>'
            '<div role="tabpanel" data-wg-hidden="display"><p>An inactive tab panel.</p></div>'
            '<details><summary>Fees</summary><div data-wg-hidden="display"><p>Fees are listed here.</p></div></details>'
            "</main>"
        )
        texts = [b.text for b in extract_rich_blocks(parse_html(html), "https://gov.test/")]
        assert "Apply online with your passport number." in texts
        assert "The rest of the notice." in texts
        assert "An inactive tab panel." in texts
        assert "Fees are listed here." in texts

    def test_a_skip_link_to_main_opens_nothing_inside_it(self) -> None:
        """MDN: `<a href="#content">Skip to main content</a>` names `<main id="content">`,
        an ancestor of everything, and made every hidden copy under it "reachable" -- the
        demo source four times over. A reference to a region is not a control for a tray
        inside it; a reference to the tray itself still is."""
        html = (
            '<a href="#content">Skip to main content</a><main id="content"><p>Visible words on the page.</p>'
            '<div data-wg-hidden="display"><p>A hidden copy nothing opens.</p></div>'
            '<a href="#faq">FAQ</a><div id="faq" data-wg-hidden="display"><p>Opened by its own link.</p></div>'
            "</main>"
        )
        texts = [b.text for b in extract_rich_blocks(parse_html(html), "https://mdn.test/")]
        assert "A hidden copy nothing opens." not in texts
        assert "Opened by its own link." in texts
        assert "Visible words on the page." in texts

    def test_a_static_fetch_is_untouched(self) -> None:
        """No renderer, no marks, no decision: a static page keeps its hidden panels."""
        html = '<main><p>Visible.</p><div style="display:none"><p>Hidden by a style the static parser does not read.</p></div></main>'
        texts = [b.text for b in extract_rich_blocks(parse_html(html), "https://gov.test/")]
        assert texts == ["Visible.", "Hidden by a style the static parser does not read."]


class TestPreCssPages:
    """textfiles.com, erikdemaine.org/foldcut: pages written before CSS, where text sits
    straight under `<body>` or inside `<center>` and `<font>` with no `<p>` or `<div>`, and
    paragraphs are separated by `<br><br>`. 21% of textfiles.com's words were lost outright
    and every `<br>` read as a space."""

    def test_text_in_body_center_and_font_is_read(self) -> None:
        html = (
            "<html><body>Bare words in the body.<table><tr><td>cell</td></tr></table>"
            "<CENTER><FONT FACE=Courier>TEXTFILES.COM has been online for nearly 25 years with no ads.<br>"
            "If you feel like donating: <a href='https://paypal.me/x'>Paypal</a>.</FONT></CENTER>"
            "And a trailing line.</body></html>"
        )
        texts = [b.text for b in build_document(html, "http://old.test/").blocks]
        assert texts == [
            "Bare words in the body.",
            "cell",
            "TEXTFILES.COM has been online for nearly 25 years with no ads.\nIf you feel like donating: Paypal.",
            "And a trailing line.",
        ]

    def test_br_is_a_line_break_and_br_br_a_paragraph(self) -> None:
        html = (
            "<html><body><p>12 Elm Street<br>Springfield<br>Illinois</p>"
            "<div>First paragraph of an old page.<br><br>Second paragraph after a blank line.</div>"
            "<p>A source\n   newline is\n a space.</p></body></html>"
        )
        document = build_document(html, "http://old.test/")
        assert [b.text for b in document.blocks] == [
            "12 Elm Street\nSpringfield\nIllinois",
            "First paragraph of an old page.",
            "Second paragraph after a blank line.",
            "A source newline is a space.",
        ]
        markdown = to_markdown(document, options=MarkdownOptions())
        assert "12 Elm Street\\\nSpringfield\\\nIllinois" in markdown
        assert "First paragraph of an old page.\n\nSecond paragraph after a blank line." in markdown
        assert "A source newline is a space." in markdown

    def test_split_paragraphs_keep_their_order_and_their_headings(self) -> None:
        """AppleInsider (Zyte 65bf3048) wraps a `<br><br>`-separated review in one `<span>`
        with `<h2>`s between the paragraphs. Splitting only at the container's direct
        children put every heading ahead of every paragraph, and the innermost-first
        flush of trailing runs reversed the paragraphs (0.983 -> 0.934 on the board)."""
        html = (
            "<html><body><div><span>Intro para.<br><br>Second para.<h2>Head</h2>"
            "Third para.<br><br>Fourth.</span></div>"
            "<div>a<div>inner<p>P</p>inner tail one<br><br>inner tail two</div>"
            "outer tail one<br><br>outer tail two</div></body></html>"
        )
        document = build_document(html, "http://old.test/")
        assert [b.text for b in document.blocks] == [
            "Intro para.",
            "Second para.",
            "Head",
            "Third para.",
            "Fourth.",
            "a",
            "inner",
            "P",
            "inner tail one",
            "inner tail two",
            "outer tail one",
            "outer tail two",
        ]

    def test_a_list_items_first_paragraph_is_the_item(self) -> None:
        """DocBook / Sphinx / wiki markup: `<li><p>…</p></li>`. catb.org's "How To Ask
        Questions" lost every bullet and number of its eight lists; tldp.org's HOWTO index
        came out as a hundred bare paragraphs."""
        html = (
            "<html><body><ol><li><p>Search the Web first.</p><p>Then the archives.</p></li>"
            "<li><p>Read the manual.</p><ul><li><p>Nested item.</p></li></ul></li>"
            "<li>Label <p>and a paragraph after it</p></li></ol></body></html>"
        )
        document = build_document(html, "http://old.test/")
        assert [(b.kind.value, b.level, b.ordered, b.text) for b in document.blocks] == [
            ("list-item", 1, True, "Search the Web first."),
            ("paragraph", 1, True, "Then the archives."),
            ("list-item", 1, True, "Read the manual."),
            ("list-item", 2, False, "Nested item."),
            ("list-item", 1, True, "Label"),
            ("paragraph", 1, True, "and a paragraph after it"),
        ]
        markdown = to_markdown(document, options=MarkdownOptions())
        assert (
            "1. Search the Web first.\n\n   Then the archives.\n\n1. Read the manual." in markdown
        )
        assert "  - Nested item." in markdown
        assert "1. Label\n\n   and a paragraph after it" in markdown

    def test_a_blockquote_holding_a_table_keeps_the_table(self) -> None:
        """columbia.edu/~fdc/sample.html indents its demo tables with `<blockquote>`; the
        table came out as one line of quoted words. A quote made of blocks is walked into
        and each block is quoted in the Markdown."""
        html = (
            "<html><body><p>A simple table:</p>"
            "<blockquote><table><tr><th>Heading A</th><th>Heading B</th></tr><tr><td>Cell 1A</td><td>Cell 1B</td></tr></table></blockquote>"
            "<blockquote>A short quoted line only.</blockquote>"
            "<blockquote><p>First quoted paragraph.</p><ul><li>a quoted item</li></ul></blockquote></body></html>"
        )
        document = build_document(html, "http://old.test/")
        kinds = [(b.kind.value, b.quoted) for b in document.blocks]
        assert kinds == [
            ("paragraph", 0),
            ("table", 1),
            ("quote", 0),
            ("paragraph", 1),
            ("list-item", 1),
        ]
        markdown = to_markdown(document, options=MarkdownOptions())
        assert "> | Heading A | Heading B |\n> | --- | --- |\n> | Cell 1A | Cell 1B |" in markdown
        assert "> A short quoted line only." in markdown
        assert "> - a quoted item" in markdown

    def test_a_data_table_cell_keeps_its_words_apart(self) -> None:
        """`<td>a<br>b</td>` was `ab` and `<td><span>x</span><div>y</div></td>` was `xy`;
        a cell is one row of a grid, so the break is a space, not a newline."""
        html = (
            "<html><body><table><tr><th>H1</th><th>H2</th></tr>"
            "<tr><td>a<br>b</td><td>c<br><br>d</td></tr>"
            "<tr><td><span>x</span><div>y</div></td><td>e</td></tr></table></body></html>"
        )
        document = build_document(html, "http://old.test/")
        assert document.blocks[0].rows == (("H1", "H2"), ("a b", "c d"), ("x y", "e"))
        markdown = to_markdown(document, options=MarkdownOptions())
        assert "| a b | c d |\n| x y | e |" in markdown

    def test_headings_and_captions_stay_on_one_line(self) -> None:
        html = "<html><body><h2>Chapter<br>One</h2><figure><img src='/a.jpg' alt='x'><figcaption>Seen<br>here</figcaption></figure><ul><li>first<br>line two</li></ul></body></html>"
        markdown = to_markdown(build_document(html, "http://old.test/"), options=MarkdownOptions())
        assert "## Chapter One" in markdown
        assert "*Seen here*" in markdown
        assert "- first\n  line two" in markdown


class TestDocumentText:
    def test_alt_text_and_placeholders_are_not_text(self) -> None:
        html = (
            '<main><p>First sentence of the page.</p><img src="/a.jpg" alt="A tall white bookcase with shelves">'
            '<iframe src="https://example.com/embed"></iframe><p>Second sentence.</p></main>'
        )
        document = build_document(html, "https://shop.test/")
        assert document.text == "First sentence of the page.\n\nSecond sentence."
        assert any(b.kind is BlockKind.IMAGE for b in document.blocks), "the image is still a block"


class TestCodeHeaders:
    """MDN: `<div class="example-header"><span>js</span><button>Copy</button></div><pre>` --
    "js Copy" before every one of the eleven examples on Array.prototype.reduce()."""

    def test_language_and_copy_strip_is_dropped(self) -> None:
        html = (
            "<main><p>The callback is invoked four times:</p>"
            '<div class="code-example"><div class="example-header"><span>js</span><button>Copy</button></div>'
            "<pre><code>const array = [1, 2, 3, 4];</code></pre></div></main>"
        )
        blocks = extract_rich_blocks(parse_html(html), "https://docs.test/")
        assert [b.text for b in blocks] == [
            "The callback is invoked four times:",
            "const array = [1, 2, 3, 4];",
        ]

    def test_a_sentence_before_code_is_kept(self) -> None:
        html = "<main><p>Here we reduce the same array with an initial value of ten passed in:</p><pre>x</pre></main>"
        blocks = extract_rich_blocks(parse_html(html), "https://docs.test/")
        assert len(blocks) == 2

    def test_a_short_lead_in_before_code_is_prose(self) -> None:
        """perldoc.perl.org/perlre: "is made equivalent to", "For example, this program",
        "will output the following:" -- each a `<p>` of four words or fewer directly before
        a `<pre>`, and each was dropped as if it were MDN's language-and-copy strip. Sixty
        words of the page. A paragraph is prose whatever its length; the strip is a
        container with a control in it, or a bare language label."""
        html = (
            "<main><pre><code>m{ a }x;</code></pre><p>is made equivalent to</p>"
            "<pre><code>m{ b }x;</code></pre><p>For example, this program</p>"
            "<pre><code>#!perl -l</code></pre><p>will output the following:</p>"
            "<pre><code>hello</code></pre><div>Thus</div><pre><code>x</code></pre></main>"
        )
        blocks = extract_rich_blocks(parse_html(html), "https://docs.test/")
        assert [b.text for b in blocks] == [
            "m{ a }x;",
            "is made equivalent to",
            "m{ b }x;",
            "For example, this program",
            "#!perl -l",
            "will output the following:",
            "hello",
            "Thus",
            "x",
        ]

    def test_a_bare_language_label_before_code_is_still_a_strip(self) -> None:
        """No button, but the label is the block's own language: a strip, not a sentence."""
        html = (
            '<main><div class="header"><span>js</span></div><pre class="language-js">x</pre>'
            '<div>Copy</div><pre>y</pre><div>Python</div><pre><code class="language-python">z</code></pre></main>'
        )
        blocks = extract_rich_blocks(parse_html(html), "https://docs.test/")
        assert [b.text for b in blocks] == ["x", "y", "z"]

    def test_phpbbs_code_select_all_is_a_strip(self) -> None:
        """forums.debian.net: `<p>Code: <a href="#">Select all</a></p>` above every `<pre>`
        -- a paragraph, but one holding a control that goes nowhere. WebMainBench's truth
        for that page has no "Code: Select all"."""
        html = (
            '<main><div class="codebox"><p>Code: <a href="#" onclick="selectCode(this)">Select all</a></p>'
            "<pre><code>apt install foo</code></pre></div></main>"
        )
        blocks = extract_rich_blocks(parse_html(html), "https://forum.test/")
        assert [b.text for b in blocks] == ["apt install foo"]

    def test_a_word_that_is_not_a_label_stays_even_in_a_div(self) -> None:
        html = "<main><div>Output</div><pre>x</pre><div>Example:</div><pre>y</pre></main>"
        blocks = extract_rich_blocks(parse_html(html), "https://docs.test/")
        assert [b.text for b in blocks] == ["Output", "x", "Example:", "y"]


class TestNotALanguage:
    def test_a_highlighters_undefined_is_no_language(self) -> None:
        """highlight.js labels a block it could not classify `language-undefined`, and
        perldoc's fences came out as ```undefined -- a word the page never showed."""
        from webgraph.render_markdown import MarkdownOptions, to_markdown

        for token in ("undefined", "none", "plaintext", "text", "nohighlight"):
            html = f'<main><pre><code class="hljs language-{token}">m{{ a }}x;</code></pre></main>'
            document = build_document(html, "https://docs.test/")
            assert document.blocks[0].language is None, token
            assert "```\n" in to_markdown(document, options=MarkdownOptions())

    def test_a_declared_language_still_counts(self) -> None:
        html = '<main><pre><code class="hljs language-perl">m{ a }x;</code></pre></main>'
        assert build_document(html, "https://docs.test/").blocks[0].language == "perl"


class TestCodeEditors:
    """A browser-side code editor's DOM is one code block: its lines, not its gutter.

    developer.mozilla.org/en-US/docs/Web/HTML/Element/table mounts a CodeMirror 6 editor
    per tab of its "Try it" demo, and the whole-page Markdown carried one paragraph per
    gutter number and one per line -- `1`, `<table>`, `2`, `<caption>`, … -- with the
    other tab's lines scattered among them.
    """

    CM6 = (
        '<mdn-play-editor language="html"><div class="editor"><div class="cm-editor">'
        '<div class="cm-announced" aria-live="polite"></div>'
        '<div class="cm-scroller"><div class="cm-gutters" aria-hidden="true">'
        '<div class="cm-gutter cm-lineNumbers">'
        '<div class="cm-gutterElement" data-wg-hidden="visibility">99</div>'
        '<div class="cm-gutterElement">1</div><div class="cm-gutterElement">2</div>'
        '<div class="cm-gutterElement">3</div></div></div>'
        '<div class="cm-content" contenteditable="true" role="textbox" data-language="html">'
        '<div class="cm-line"><span class="cm-matchingBracket">&lt;</span><span>table</span>&gt;</div>'
        '<div class="cm-line">  &lt;<span>caption</span>&gt;Course 2021&lt;/caption&gt;</div>'
        '<div class="cm-line">&lt;/<span>table</span>&gt;</div></div>'
        '<div class="cm-layer cm-cursorLayer"><div class="cm-cursor"></div></div>'
        "</div></div></div></mdn-play-editor>"
    )

    def test_codemirror_6_is_one_code_block_without_its_gutter(self) -> None:
        found = blocks(f"<p>Try it</p>{self.CM6}<p>After</p>")
        assert [b.text for b in found] == [
            "Try it",
            "<table>\n  <caption>Course 2021</caption>\n</table>",
            "After",
        ]
        assert found[1].kind is BlockKind.CODE
        assert found[1].language == "html"

    def test_the_language_comes_from_the_host_when_the_content_has_none(self) -> None:
        found = blocks(self.CM6.replace(' data-language="html"', ""))
        assert found[0].language == "html"  # `<mdn-play-editor language="html">`

    def test_codemirror_5_lines_are_pres_and_still_one_block(self) -> None:
        html = (
            '<div class="CodeMirror cm-s-default"><div class="CodeMirror-scroll">'
            '<div class="CodeMirror-sizer"><div><div class="CodeMirror-lines"><div role="presentation">'
            '<div class="CodeMirror-measure"><pre class="CodeMirror-line-like">xxxxxxxxxx</pre></div>'
            '<div class="CodeMirror-code">'
            '<div><pre class="CodeMirror-line"><span>def f():</span></pre></div>'
            '<div><pre class="CodeMirror-line"><span>    return 1</span></pre></div>'
            "</div></div></div></div></div>"
            '<div class="CodeMirror-gutters"><div class="CodeMirror-gutter CodeMirror-linenumbers">'
            '<div class="CodeMirror-linenumber">1</div><div class="CodeMirror-linenumber">2</div>'
            "</div></div></div></div>"
        )
        found = blocks(html)
        assert [b.text for b in found] == ["def f():\n    return 1"]
        assert found[0].kind is BlockKind.CODE

    def test_monaco_lines_are_put_back_in_order(self) -> None:
        """Monaco virtualises and emits lines in render order; `top` says which is which."""
        html = (
            '<div class="monaco-editor" data-mode-id="typescript"><div class="overflow-guard">'
            '<div class="margin"><div class="line-numbers">1</div><div class="line-numbers">2</div></div>'
            '<div class="lines-content"><div class="view-lines">'
            '<div class="view-line" style="top:19px;height:19px;"><span>&nbsp;&nbsp;return&nbsp;x;</span></div>'
            '<div class="view-line" style="top:0px;height:19px;"><span>function&nbsp;f()&nbsp;{</span></div>'
            '<div class="view-line" style="top:38px;height:19px;"><span>}</span></div>'
            "</div></div></div></div>"
        )
        found = blocks(html)
        assert [b.text for b in found] == ["function f() {\n  return x;\n}"]
        assert found[0].language == "typescript"

    def test_ace_lines(self) -> None:
        html = (
            '<div class="ace_editor ace-tm"><div class="ace_gutter"><div class="ace_gutter-cell">1</div></div>'
            '<div class="ace_scroller"><div class="ace_content"><div class="ace_text-layer">'
            '<div class="ace_line_group"><div class="ace_line"><span>SELECT 1;</span></div></div>'
            '<div class="ace_line"><span>SELECT 2;</span></div>'
            "</div></div></div></div>"
        )
        assert [b.text for b in blocks(html)] == ["SELECT 1;\nSELECT 2;"]

    def test_an_editor_window_takes_the_whole_document_the_page_holds(self) -> None:
        """CodeMirror draws only the lines in view: MDN's editor holds 30 of 40 lines,
        while the hidden `<pre>` it was built from holds all 40. The editor block takes
        the whole text and the twin is dropped -- once, where the editor is."""
        full = "<table>\n  <caption>Course 2021</caption>\n</table>\n<p>more</p>\n<p>and more</p>"
        # MDN's shape: the hidden `<pre>` sits in `<main id="content">`, which the skip
        # link names, so `_drop_unreachable_hidden` keeps it (as it keeps everything hidden
        # under a referenced ancestor).
        html = (
            '<a href="#content">Skip to main content</a><main id="content">'
            f"<p>Try it</p>{self.CM6}<h4>Output</h4>"
            '<pre class="brush: html interactive-example" data-wg-hidden="display">'
            f"<code>{full.replace('<', '&lt;')}</code></pre>"
            "<p>After</p></main>"
        )
        found = blocks(html)
        assert [b.text for b in found] == [
            "Skip to main content",
            "Try it",
            full,
            "Output",
            "After",
        ]
        assert found[2].kind is BlockKind.CODE and found[2].language == "html"

    def test_a_visible_listing_beside_an_editor_is_its_own_block(self) -> None:
        """A listing the reader sees under a playground is on the page in its own right:
        only a hidden twin is the editor's document (a page's deliberate repeats stay)."""
        full = "<table>\n  <caption>Course 2021</caption>\n</table>\n<p>more</p>"
        html = f"{self.CM6}<pre><code>{full.replace('<', '&lt;')}</code></pre>"
        found = blocks(html)
        assert [b.text for b in found] == [
            "<table>\n  <caption>Course 2021</caption>\n</table>",
            full,
        ]

    def test_an_editor_showing_something_of_its_own_keeps_it(self) -> None:
        html = f"{self.CM6}<pre><code>&lt;div&gt;unrelated&lt;/div&gt;</code></pre>"
        assert [b.text for b in blocks(html)] == [
            "<table>\n  <caption>Course 2021</caption>\n</table>",
            "<div>unrelated</div>",
        ]

    def test_an_empty_editor_is_nothing(self) -> None:
        html = '<div class="cm-editor"><div class="cm-scroller"><div class="cm-content"></div></div></div>'
        assert blocks(html) == []


class TestOffscreen:
    """Text pushed off the page is not on the page.

    vtu.ac.in (15 Sep 2026): every page carries ~60 injected gambling links, each in
    `<div style="position:absolute; left:-20914565266523px">` -- twenty trillion pixels
    to the left, where no reader can scroll. The browser still reports a box for them, the
    collector read "has a box" as "visible", and the whole-page Markdown opened with sixty
    lines of spam before "About VTU". A box lying entirely at negative page coordinates is
    hidden the way `display: none` is (`offscreen`); on a plain fetch the inline style that
    puts it there is the same signal.
    """

    def test_a_box_the_renderer_put_off_the_page_is_dropped(self) -> None:
        found = blocks(
            '<main><div data-wg-hidden="offscreen"><a href="https://x.test/">situs slot</a></div>'
            "<h1>About VTU</h1><p>VTU is one of the largest technological universities.</p></main>"
        )
        assert [b.text for b in found] == [
            "About VTU",
            "VTU is one of the largest technological universities.",
        ]

    def test_an_inline_style_that_pushes_text_off_the_page_is_dropped_statically(self) -> None:
        html = (
            '<main><div style="position: absolute; left: -20914565266523px; top: 0px;">'
            '<a href="https://x.test/">TERMINAL4D</a></div>'
            '<div style="position:absolute;top:-9999px"><a href="https://x.test/">sudirman168</a></div>'
            '<p style="text-indent:-9999px">Hidden by indent</p>'
            "<h1>About VTU</h1><p>VTU is one of the largest technological universities.</p></main>"
        )
        text = build_document(f"<html><body>{html}</body></html>", BASE).text
        assert "TERMINAL4D" not in text and "sudirman168" not in text and "indent" not in text
        assert "About VTU" in text

    def test_a_small_negative_offset_is_still_on_the_page(self) -> None:
        """`left: -20px` is a design nudge, not a hiding place; and a negative offset without
        `position` does nothing at all."""
        html = (
            '<main><p style="position:relative; left:-20px">Nudged heading text</p>'
            '<p style="left:-9999px">No position, so this is where it looks</p>'
            '<p style="position:absolute; left:-9999px">Gone</p></main>'
        )
        text = build_document(f"<html><body>{html}</body></html>", BASE).text
        assert "Nudged heading text" in text
        assert "No position" in text
        assert "Gone" not in text

    def test_include_hidden_text_keeps_offscreen_text(self) -> None:
        """Off-screen positioning is also the oldest screen-reader-only technique; a caller
        who asked for every string in the DOM gets it."""
        html = (
            '<main><span style="position:absolute; left:-9999px">Skip to content</span>'
            "<p>Body text of the page.</p></main>"
        )
        document = build_document(
            f"<html><body>{html}</body></html>", BASE, include_hidden_text=True
        )
        assert "Skip to content" in document.text

    def test_offscreen_matter_stays_hidden_through_the_union(self) -> None:
        """The static fetch holds the spam without any marker; the union must not put back
        what the browser hid. `hidden_matter` reports `offscreen` like `display`."""
        from webgraph.fetch.render import hidden_matter

        rendered = (
            '<html><body><div data-wg-hidden="offscreen"><a href="https://x.test/">situs slot</a></div>'
            "<p>Body text of the page.</p></body></html>"
        )
        assert hidden_matter(rendered).holds("situsslot", min_chars=0)
