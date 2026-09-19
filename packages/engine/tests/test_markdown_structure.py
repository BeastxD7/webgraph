"""Structure a reader sees that the Markdown was dropping or flattening.

Found by a census of 25 old and plain pages against Chromium's own text: `<hr>` vanished
(6 of 14 sites), `<dl>` came out as loose paragraphs (cl.cam.ac.uk's Unicode FAQ, php.net's
parameter lists), a table's own markup fused the words on either side of a `<br>` or a `<p>`
inside a cell, and an inline `<svg>` diagram's labels -- a quarter of sqlite.org/lang.html --
were not there at all. Each test pins one of those shapes.
"""

from __future__ import annotations

import pytest

from webgraph.blockmodel import default_model, select_by_model
from webgraph.content import select_content
from webgraph.dom.blocks import parse_html
from webgraph.dom.rich import extract_rich_blocks, preserved_table_html
from webgraph.main_content import MainContentConfig, select_main_content
from webgraph.pagetype import FEATURE_NAMES, page_features
from webgraph.pipeline import build_document
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.types import Block, ReadingOrderMethod, Rect

BASE = "https://example.com/page"


def document(body: str):
    return build_document(f"<html><body>{body}</body></html>", BASE)


def md(body: str) -> str:
    return to_markdown(document(body), options=MarkdownOptions())


def blocks(body: str) -> list[Block]:
    return extract_rich_blocks(parse_html(f"<html><body>{body}</body></html>"), BASE)


PROSE = (
    "This paragraph is the article: it says enough words in a row, in sentences, that the "
    "boundary step counts it as prose and keeps it. "
)


class TestHorizontalRule:
    def test_hr_is_a_rule_in_the_markdown(self) -> None:
        out = md("<p>Before the line.</p><hr><p>After the line.</p>")
        assert out == "Before the line.\n\n---\n\nAfter the line.\n"

    def test_hr_splits_a_containers_own_text_where_it_sits(self) -> None:
        """`<div>a<hr>b</div>`: the rule is between the two runs, not after both."""
        out = md("<div>Opening words of the section.<hr>Closing words of the section.</div>")
        assert out == "Opening words of the section.\n\n---\n\nClosing words of the section.\n"

    def test_rule_is_a_block_with_no_text(self) -> None:
        doc = document("<p>x</p><hr><p>y</p>")
        assert [str(b.kind) for b in doc.blocks] == ["paragraph", "rule", "paragraph"]
        assert doc.text == "x\n\ny"

    def test_many_rules_survive_deduplication(self) -> None:
        out = md("<p>one</p><hr><p>two</p><hr><p>three</p><hr><p>four</p>")
        assert out.count("\n---\n") == 3

    def test_hidden_hr_is_not_a_line_the_reader_sees(self) -> None:
        found = blocks('<p>x</p><hr data-wg-hidden="display"><p>y</p>')
        assert [str(b.kind) for b in found] == ["paragraph", "paragraph"]

    def test_unmeasured_hr_on_a_rendered_page_is_dropped_and_order_stays_measured(self) -> None:
        """`hr { height: 0; border: 0 }` is a stylesheet removing the rule: no box, no line."""
        html = "<html><body><p>first paragraph</p><hr><p>second paragraph</p></body></html>"
        plain = build_document(html, BASE)
        geometry = {
            b.xpath: Rect(x=0, y=float(i * 40), width=600, height=30)
            for i, b in enumerate(plain.blocks)
            if b.text
        }
        doc = build_document(html, BASE, geometry=geometry)
        assert [b.text for b in doc.blocks] == ["first paragraph", "second paragraph"]
        assert doc.reading_order_method is ReadingOrderMethod.GEOMETRIC_XY_CUT

    def test_rule_is_never_content_on_its_own_and_never_an_edge(self) -> None:
        body = (
            "<hr><nav><p>Home</p><p>About</p></nav><hr>"
            + "".join(f"<p>{PROSE}Paragraph {i}.</p><hr>" for i in range(4))
            + "<p>Tags</p><p>Share</p><hr>"
        )
        doc = document(body)
        kept = select_main_content(list(doc.blocks), config=MainContentConfig())
        kinds = [str(b.kind) for b in kept]
        assert kinds[0] == "paragraph" and kinds[-1] == "paragraph"
        assert kinds.count("rule") == 3  # the three between the four kept paragraphs
        assert all(b.text.startswith(PROSE) for b in kept if str(b.kind) == "paragraph")

    def test_a_page_of_only_rules_selects_nothing(self) -> None:
        doc = document("<hr><hr>")
        assert [str(b.kind) for b in doc.blocks] == ["rule", "rule"]
        assert select_main_content(list(doc.blocks), config=MainContentConfig()) == []

    def test_a_page_of_rules_and_a_link_list_selects_no_rule(self) -> None:
        doc = document("<hr><p><a href='/a'>one</a></p><hr><p><a href='/b'>two</a></p><hr>")
        kept = select_main_content(list(doc.blocks), config=MainContentConfig())
        # No run is worth anything, so the whole page comes back -- rules included, in
        # place -- rather than a rule on its own.
        assert [str(b.kind) for b in kept] == [str(b.kind) for b in doc.blocks]

    def test_rules_change_neither_the_selection_nor_the_routing_features(self) -> None:
        with_rules = "".join(f"<p>{PROSE}Paragraph {i}.</p><hr>" for i in range(3)) + (
            "<p>Tags</p><hr><p>Share</p><hr><p>Footer</p>"
        )
        without = with_rules.replace("<hr>", "")
        a, b = document(with_rules), document(without)
        differing = {
            FEATURE_NAMES[i]
            for i, (x, y) in enumerate(zip(page_features(a), page_features(b), strict=True))
            if x != y
        }
        # `log_elements` counts the markup's elements, `<hr>` among them, and always did;
        # every feature read from the blocks is the same.
        assert differing <= {"log_elements"}
        kept_a = [x.text for x in select_main_content(list(a.blocks)) if x.text]
        kept_b = [x.text for x in select_main_content(list(b.blocks))]
        assert kept_a == kept_b

    def test_rules_do_not_count_against_the_lead_under_a_restored_title(self) -> None:
        """l-camera-forum.com: the byline and post header sit between the title and the
        first post, with rules between them; counted as blocks, the gap was too long to
        restore and the lead was lost."""
        lead = "".join(f"<p>Lead line {i}</p>" for i in range(11))
        body = "".join(f"<p>{PROSE}Paragraph {i}.</p>" for i in range(4))
        plain = f"<h1>The Title</h1>{lead}{body}<p>Tags</p><p>Share</p>"
        ruled = f"<h1>The Title</h1><hr>{lead.replace('Lead line 5</p>', 'Lead line 5</p><hr>')}{body}<p>Tags</p><p>Share</p>"
        html = "<html><head><title>The Title</title></head><body>{}</body></html>"
        a = build_document(html.format(plain), BASE)
        b = build_document(html.format(ruled), BASE)
        kept_a = [x.text for x in select_content(list(a.blocks), title=a.title).blocks]
        kept_b = [x.text for x in select_content(list(b.blocks), title=b.title).blocks if x.text]
        assert "Lead line 5" in kept_a
        assert kept_a == kept_b

    def test_the_block_model_scores_around_a_rule(self) -> None:
        model = default_model()
        if model is None:
            pytest.skip("no shipped block model")
        doc = document("".join(f"<p>{PROSE}Paragraph {i}.</p><hr>" for i in range(3)))
        kept = select_by_model(list(doc.blocks), model)
        assert kept and all(str(b.kind) in {"paragraph", "rule"} for b in kept)
        if len(kept) < len(doc.blocks):
            assert str(kept[0].kind) == "paragraph" and str(kept[-1].kind) == "paragraph"


class TestDefinitionLists:
    def test_term_then_definition(self) -> None:
        out = md(
            "<dl><dt>Level 1</dt><dd>Combining characters are not supported.</dd>"
            "<dt>Level 2</dt><dd>A fixed list of combining characters is allowed.</dd></dl>"
        )
        assert out == (
            "**Level 1**\n: Combining characters are not supported.\n\n"
            "**Level 2**\n: A fixed list of combining characters is allowed.\n"
        )

    def test_a_definitions_paragraphs_are_kept_under_it(self) -> None:
        """php.net: `<dt><code>callback</code></dt><dd><p>…</p><p>…</p></dd>`."""
        out = md(
            "<dl><dt><code>callback</code></dt>"
            "<dd><p>A callable to run for each element.</p>"
            "<p>null can be passed to perform a zip operation.</p></dd></dl>"
        )
        assert out == (
            "**`callback`**\n: A callable to run for each element.\n\n"
            "  null can be passed to perform a zip operation.\n"
        )

    def test_a_list_inside_a_definition_is_indented_under_it(self) -> None:
        out = md("<dl><dt>Options</dt><dd>Any of:<ul><li>alpha</li><li>beta</li></ul></dd></dl>")
        assert out == "**Options**\n: Any of:\n\n  - alpha\n  - beta\n"

    def test_a_term_already_in_bold_is_not_bolded_twice(self) -> None:
        out = md("<dl><dt><strong>Stupid:</strong></dt><dd>HELP! Video doesn't work.</dd></dl>")
        assert out == "**Stupid:**\n: HELP! Video doesn't work.\n"

    def test_line_breaks_inside_a_definition_stay_in_it(self) -> None:
        out = md("<dl><dt>Address</dt><dd>1 Main St<br>Springfield</dd></dl>")
        assert out == "**Address**\n: 1 Main St\\\n  Springfield\n"

    def test_the_plain_text_carries_no_markers(self) -> None:
        doc = document("<dl><dt>Term</dt><dd>Definition of the term.</dd></dl>")
        assert doc.text == "Term\n\nDefinition of the term."
        assert [b.tag for b in doc.blocks] == ["dt", "dd"]


class TestPreservedTableMarkup:
    def test_words_on_either_side_of_a_break_stay_apart(self) -> None:
        """A table with a merged cell keeps its own markup; unwrapping `<br>`, `<p>` and
        `<li>` inside its cells fused the words around them."""
        table = parse_html(
            "<html><body><table><tr><th colspan='2'>Head</th></tr>"
            "<tr><td>Revision 3.10<br>21 May 2014</td>"
            "<td><p>New section.</p><p>URL fixes.</p><ul><li>one</li><li>two</li></ul></td></tr>"
            "</table></body></html>"
        ).xpath("//table")[0]
        assert preserved_table_html(table, BASE) == (
            '<table><tr><th colspan="2">Head</th></tr>'
            "<tr><td>Revision 3.10<br>21 May 2014</td>"
            "<td>New section.<br>URL fixes.<br>one<br>two</td></tr></table>"
        )

    def test_images_in_cells_are_kept_and_pixels_are_not(self) -> None:
        table = parse_html(
            "<html><body><table><tr><th colspan='2'>Head</th></tr>"
            "<tr><td><img src='/pic.png' alt='A picture'><img src='/px.gif' width='1' height='1'></td>"
            "<td><a href='/x'>link</a></td></tr></table></body></html>"
        ).xpath("//table")[0]
        assert preserved_table_html(table, BASE) == (
            '<table><tr><th colspan="2">Head</th></tr>'
            '<tr><td><img src="https://example.com/pic.png" alt="A picture"></td>'
            '<td><a href="https://example.com/x">link</a></td></tr></table>'
        )

    def test_images_and_links_in_cells_follow_the_rendering_switches(self) -> None:
        body = (
            "<table><tr><th colspan='2'>Head</th></tr>"
            "<tr><td><img src='/pic.png' alt='A picture'></td><td><a href='/x'>link</a></td></tr></table>"
        )
        doc = document(body)
        plain = to_markdown(doc, options=MarkdownOptions(include_images=False, include_links=False))
        assert "<img" not in plain and "<a " not in plain and "<td>link</td>" in plain
        full = to_markdown(doc, options=MarkdownOptions())
        assert "<img" in full and "<a href=" in full

    def test_the_markdown_carries_the_cleaned_markup(self) -> None:
        out = md(
            "<table><tr><th colspan='3'>Revision History</th></tr>"
            "<tr><td>Revision 3.10</td><td>21 May 2014</td><td>esr</td></tr>"
            "<tr><td colspan='3'><p>New section</p><p>on Stack Overflow.</p></td></tr></table>"
        )
        assert '<td colspan="3">New section<br>on Stack Overflow.</td>' in out


class TestScriptedFormulas:
    """Chemical formulas, exponents and ions written with plain `<sup>`/`<sub>`, the way
    almost every page writes them (MathML is for the minority that ship an equation editor).
    A single Markdown character set carries these portably -- cm² reads correctly in a
    terminal, a search index or a table cell, not only where HTML renders -- and a formula
    with no exact Unicode form is kept as the literal tag rather than losing its meaning.
    """

    def test_a_unit_squared_survives_in_prose(self) -> None:
        out = md(f"<p>{PROSE}The area is 25 cm<sup>2</sup>, measured twice.</p>")
        assert "25 cm²" in out
        assert "<sup>" not in out

    def test_a_chemical_formula_survives_in_prose(self) -> None:
        out = md(f"<p>{PROSE}The formula for water is H<sub>2</sub>O, always.</p>")
        assert "H₂O" in out
        assert "<sub>" not in out

    def test_a_polyatomic_ion_combines_a_subscript_and_a_superscript(self) -> None:
        out = md(f"<p>{PROSE}The sulfate ion is SO<sub>4</sub><sup>2-</sup> in solution.</p>")
        assert "SO₄²⁻" in out

    def test_a_real_minus_sign_maps_the_same_as_a_hyphen(self) -> None:
        """A page can write the ion's charge with U+2212 MINUS SIGN instead of a hyphen;
        both must produce the same superscript glyph."""
        out = md(f"<p>{PROSE}Chloride is Cl<sup>−</sup> here.</p>")
        assert "Cl⁻" in out

    def test_an_exponent_with_no_unicode_form_keeps_its_tag(self) -> None:
        """`n` has a true Unicode superscript; `k` does not. Guessing that `x^k` means
        anything in particular is exactly what this must not do -- the tag is kept, intact,
        as valid inline HTML inside the Markdown, rather than silently dropped to `xk`."""
        out = md(f"<p>{PROSE}The general term is x<sup>k</sup> for arbitrary k.</p>")
        assert "<sup>k</sup>" in out
        assert "xk" not in out

    def test_an_isotope_mass_number_survives_before_the_element(self) -> None:
        out = md(f"<p>{PROSE}The isotope <sup>235</sup>U undergoes fission readily.</p>")
        assert "²³⁵U" in out

    def test_a_balanced_reaction_equation_survives_whole(self) -> None:
        """Every part of a real equation at once: two formulas, an arrow, a coefficient --
        the shape a page actually uses, not one isolated tag."""
        out = md(
            f"<p>{PROSE}The equation is 2H<sub>2</sub> + O<sub>2</sub> → 2H<sub>2</sub>O overall.</p>"
        )
        assert "2H₂ + O₂ → 2H₂O" in out

    def test_a_formula_in_an_ordinary_table_cell_survives(self) -> None:
        out = md(
            "<table><tr><th>Compound</th><th>Formula</th></tr>"
            "<tr><td>Water</td><td>H<sub>2</sub>O</td></tr>"
            "<tr><td>Carbon dioxide</td><td>CO<sub>2</sub></td></tr></table>"
        )
        assert "H₂O" in out
        assert "CO₂" in out

    def test_a_polyatomic_formula_with_three_separate_subscripts_survives(self) -> None:
        """Aluminium sulfate, Al₂(SO₄)₃: three independent subscripts in one run of text,
        none of them nested in the others -- the ordinary case for an inorganic formula."""
        out = md(
            f"<p>{PROSE}Aluminium sulfate is Al<sub>2</sub>(SO<sub>4</sub>)<sub>3</sub>, a salt.</p>"
        )
        assert "Al₂(SO₄)₃" in out

    def test_a_footnote_superscript_keeps_its_link(self) -> None:
        """A citation mark is often a link inside a `<sup>`; the link must survive even
        though `1` alone has a Unicode superscript and the link does not."""
        out = md(f'<p>{PROSE}This claim needs a source<sup><a href="#fn1">1</a></sup>.</p>')
        assert "<sup>[1](https://example.com/page#fn1)</sup>" in out

    def test_a_script_nested_inside_another_script_does_not_crash(self) -> None:
        """Doubly-scripted markup (a subscript inside a superscript) is rare and not worth
        a bespoke rule, but it must degrade to something legible, never an exception or
        silently dropped text."""
        out = md(f"<p>{PROSE}The term is x<sup>2<sub>n</sub></sup> in the expansion.</p>")
        assert "2" in out and "n" in out

    def test_a_formula_in_a_preserved_complex_table_keeps_the_raw_tag(self) -> None:
        """A table complex enough to keep its own markup (a merged cell, here) preserves
        `<sup>`/`<sub>` literally -- `preserved_table_html`'s own allowlist -- rather than
        going through the Unicode conversion `_cell_rich` uses for a plain pipe table."""
        table = parse_html(
            "<html><body><table><tr><th colspan='2'>Compound</th></tr>"
            "<tr><td>Water</td><td>H<sub>2</sub>O</td></tr></table></body></html>"
        ).xpath("//table")[0]
        assert "<sub>2</sub>" in preserved_table_html(table, BASE)


class TestInlineSvg:
    DIAGRAM = (
        "<div class='imgcontainer'><svg viewBox='0 0 10 10'>"
        "<path d='M0 0'/><text x='1' y='1'>EXPLAIN</text><text x='2' y='1'>QUERY</text>"
        "<text x='3' y='1'>PLAN</text><text x='1' y='2'>alter-table-stmt</text></svg></div>"
    )

    def test_a_diagrams_labels_are_read_in_document_order(self) -> None:
        out = md("<p><b>sql-stmt:</b></p>" + self.DIAGRAM + "<p>Each statement.</p>")
        assert out == (
            "**sql-stmt:**\n\nEXPLAIN · QUERY · PLAN · alter-table-stmt\n\nEach statement.\n"
        )

    def test_the_labels_are_page_text(self) -> None:
        doc = document(self.DIAGRAM)
        assert doc.text == "EXPLAIN · QUERY · PLAN · alter-table-stmt"
        assert doc.blocks[0].tag == "svg"

    def test_two_labels_are_a_diagram(self) -> None:
        """sqlite's smallest railroad diagram: `sql-stmt` and `;`."""
        assert (
            md("<div><svg><text>sql-stmt</text><path/><text>;</text></svg></div>")
            == "sql-stmt · ;\n"
        )

    def test_an_icon_emits_nothing(self) -> None:
        assert md("<button><svg><title>Menu</title><path d='M0 0'/></svg></button>") == "\n"
        assert md("<a href='/s'><svg><text>Search</text></svg></a>") == "\n"

    def test_an_icon_inside_a_sentence_leaves_the_sentence_whole(self) -> None:
        assert md("<p>Click <svg><text>Search</text></svg> to begin.</p>") == "Click to begin.\n"

    def test_a_diagram_beside_a_containers_text_is_not_read_twice(self) -> None:
        out = md("<div>Diagram:" + self.DIAGRAM + "as above.</div>")
        assert out.count("EXPLAIN") == 1
        assert out == "Diagram:\n\nEXPLAIN · QUERY · PLAN · alter-table-stmt\n\nas above.\n"

    def test_a_hidden_diagram_is_not_read(self) -> None:
        hidden = self.DIAGRAM.replace("<svg ", '<svg data-wg-hidden="display" ')
        assert md("<p>Text.</p>" + hidden) == "Text.\n"
