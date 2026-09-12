"""Block extraction tests.

The cases that matter are the ones where naive extraction produces plausible-looking
garbage: script bodies leaking into text, sentences lost after inline elements, and
wrapper divs swallowing whole columns.
"""

from __future__ import annotations

import pytest

from webgraph.dom.blocks import extract_blocks, normalize_text, parse_html
from webgraph.dom.rich import flowed_text


def blocks_of(html: str) -> list[str]:
    return [b.text for b in extract_blocks(parse_html(html))]


class TestNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("  hello   world  ", "hello world"),
            ("line\n\nbreak", "line break"),
            ("tabs\there", "tabs here"),
            ("", ""),
            (None, ""),
            ("\u00a0nbsp\u00a0", "nbsp"),
        ],
    )
    def test_collapses_whitespace(self, raw: str | None, expected: str) -> None:
        assert normalize_text(raw) == expected


class TestGranularity:
    def test_inline_markup_stays_in_one_block(self) -> None:
        html = "<html><body><p>Hello <a href='#'>link</a> world</p></body></html>"
        assert blocks_of(html) == ["Hello link world"]

    def test_innermost_block_wins(self) -> None:
        """A wrapper div must not swallow its children into one block."""
        html = """
        <html><body><div><div><p>first</p><p>second</p></div></div></body></html>
        """
        assert blocks_of(html) == ["first", "second"]

    def test_div_with_direct_text_is_a_block(self) -> None:
        """Utility-class sites put text straight in divs with no <p> in sight."""
        html = "<html><body><div class='x'>bare text</div></body></html>"
        assert blocks_of(html) == ["bare text"]

    def test_headings_lists_and_cells(self) -> None:
        html = """
        <html><body>
          <h1>Title</h1>
          <ul><li>one</li><li>two</li></ul>
          <table><tr><td>cell a</td><td>cell b</td></tr></table>
        </body></html>
        """
        assert blocks_of(html) == ["Title", "one", "two", "cell a", "cell b"]


class TestNoiseRemoval:
    def test_script_body_never_leaks_into_text(self) -> None:
        html = """
        <html><body><div><script>var secret = 'do not extract';</script>Real content</div></body></html>
        """
        result = blocks_of(html)
        assert result == ["Real content"]
        assert not any("secret" in b for b in result)

    def test_style_body_never_leaks(self) -> None:
        html = "<html><body><div><style>.a{color:red}</style>Visible</div></body></html>"
        assert blocks_of(html) == ["Visible"]

    def test_tail_text_after_script_is_preserved(self) -> None:
        """The sentence following an inline script must survive its removal."""
        html = "<html><body><p>before <script>x=1</script> after</p></body></html>"
        assert blocks_of(html) == ["before after"]

    def test_comments_removed(self) -> None:
        html = "<html><body><p>kept<!-- dropped --></p></body></html>"
        assert blocks_of(html) == ["kept"]

    def test_noscript_removed(self) -> None:
        html = "<html><body><noscript>enable js</noscript><p>content</p></body></html>"
        assert blocks_of(html) == ["content"]


class TestProvenance:
    def test_dom_index_is_source_order(self) -> None:
        html = "<html><body><p>a</p><p>b</p><p>c</p></body></html>"
        blocks = extract_blocks(parse_html(html))
        assert [b.dom_index for b in blocks] == [0, 1, 2]

    def test_xpath_round_trips_to_the_source_element(self) -> None:
        html = "<html><body><div><p>target</p></div></body></html>"
        root = parse_html(html)
        blocks = extract_blocks(root)
        assert len(blocks) == 1
        found = root.getroottree().xpath(blocks[0].xpath)
        assert found and found[0].text_content().strip() == "target"

    def test_tag_recorded(self) -> None:
        html = "<html><body><h2>heading</h2></body></html>"
        assert extract_blocks(parse_html(html))[0].tag == "h2"

    def test_blocks_have_no_geometry_from_static_html(self) -> None:
        """Static parsing yields no rects, which is what forces DOM_FALLBACK ordering."""
        blocks = extract_blocks(parse_html("<html><body><p>x</p></body></html>"))
        assert all(b.rect is None for b in blocks)


class TestEdgeCases:
    def test_empty_elements_skipped(self) -> None:
        html = "<html><body><p></p><p>   </p><p>real</p></body></html>"
        assert blocks_of(html) == ["real"]

    def test_min_chars_filter(self) -> None:
        html = "<html><body><p>a</p><p>longer text</p></body></html>"
        blocks = extract_blocks(parse_html(html), min_chars=5)
        assert [b.text for b in blocks] == ["longer text"]

    def test_malformed_html_is_tolerated(self) -> None:
        html = "<html><body><p>unclosed<div>nested wrong</p></body>"
        assert blocks_of(html)

    def test_empty_document_raises(self) -> None:
        with pytest.raises(ValueError, match="empty HTML"):
            parse_html("   ")

    def test_deeply_nested_wrappers(self) -> None:
        """Guards the O(n) descendant computation against pathological nesting."""
        depth = 300
        html = "<html><body>" + "<div>" * depth + "deep" + "</div>" * depth + "</body></html>"
        assert blocks_of(html) == ["deep"]


class TestParserLimits:
    """libxml2's default HTML parser caps nesting at 255 and drops content past it silently."""

    @pytest.mark.parametrize("depth", [300, 800])
    def test_deep_nesting_beyond_libxml_default_limit(self, depth: int) -> None:
        html = "<html><body>" + "<div>" * depth + "deep" + "</div>" * depth + "</body></html>"
        assert blocks_of(html) == ["deep"]

    def test_oversized_document_is_refused(self) -> None:
        html = "<html><body><p>" + ("x" * 2000) + "</p></body></html>"
        with pytest.raises(ValueError, match="exceeding"):
            parse_html(html, max_bytes=1000)

    def test_xhtml_encoding_declaration_does_not_kill_the_page(self) -> None:
        """XHTML served as HTML carries `<?xml … encoding="utf-8"?>`, and lxml raises
        `ValueError: Unicode strings with encoding declaration are not supported` on a `str`
        that has one. The whole document was lost, not a fragment. Found on WCEB."""
        html = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" '
            '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Body text survives.</p></body></html>'
        )
        assert blocks_of(html) == ["Body text survives."]

    def test_a_page_without_a_declaration_is_untouched(self) -> None:
        assert blocks_of("<html><body><p>Plain page.</p></body></html>") == ["Plain page."]


class TestFlowedText:
    """Line boundaries the browser laid out, honoured when flattening an element to text.

    lxml's `text_content()` concatenates descendants with nothing between them. A navigation
    of `<a>Mac</a><a>iPad</a><a>iPhone</a>` therefore arrived as `MaciPadiPhone` -- the words
    destroyed, not merely unwanted. Measured on apple.com/airpods-pro, whose entire nav came
    out as `AppleStoreShopShop the LatestMaciPadiPhoneApple Watch...`.

    A separator cannot go between every pair of elements: inline siblings genuinely do run
    together, and splitting `<b>bold</b><i>italic</i>` into `bold italic` would be the same
    corruption in the other direction. Only the computed `display` separates the two cases,
    so the renderer stamps `data-wg-brk` on block-level boxes and this reads the stamp.
    """

    def test_block_level_siblings_are_separated(self) -> None:
        html = (
            '<html><body><nav data-wg-brk="1">'
            '<a data-wg-brk="1">Mac</a><a data-wg-brk="1">iPad</a>'
            '<a data-wg-brk="1">iPhone</a></nav></body></html>'
        )
        nav = parse_html(html).xpath("//nav")[0]
        assert normalize_text(flowed_text(nav)) == "Mac iPad iPhone"

    def test_inline_siblings_are_not_separated(self) -> None:
        """`<b>bold</b><i>italic</i>` really does render as `bolditalic`."""
        html = "<html><body><p><b>bold</b><i>italic</i></p></body></html>"
        para = parse_html(html).xpath("//p")[0]
        assert normalize_text(flowed_text(para)) == "bolditalic"

    def test_a_static_page_is_unchanged(self) -> None:
        """No renderer, no marks, no layout claims -- identical to `text_content()`.

        This is what keeps the change confined to rendered fetches: a page nobody laid out
        gets no assertions about where its lines break.
        """
        html = "<html><body><div><span>one</span><span>two</span> three</div></body></html>"
        div = parse_html(html).xpath("//div")[0]
        assert normalize_text(flowed_text(div)) == normalize_text(div.text_content())

    def test_tail_text_survives(self) -> None:
        html = '<html><body><p>before <b data-wg-brk="1">middle</b> after</p></body></html>'
        para = parse_html(html).xpath("//p")[0]
        assert normalize_text(flowed_text(para)) == "before middle after"

    def test_nested_marks_are_honoured(self) -> None:
        html = (
            '<html><body><div><section data-wg-brk="1"><span>a</span>'
            '<span data-wg-brk="1">b</span></section></div></body></html>'
        )
        div = parse_html(html).xpath("//div")[0]
        assert normalize_text(flowed_text(div)) == "a b"
