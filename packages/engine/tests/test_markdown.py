"""Structure-preserving extraction and Markdown rendering.

Plain-text extraction silently destroys most of a page's meaning. Each test here pins one
kind of structure that must survive the trip out of the HTML.
"""

from __future__ import annotations

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
        out = md("<table><tr><td>a|b</td></tr></table>")
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

    def test_ordinary_links_in_headings_are_untouched(self) -> None:
        out = md('<h2><a href="/a">Section</a></h2>')
        assert "[Section](https://example.com/a)" in out
