"""Mathematics survives the page instead of being deleted by it.

`math` sat in `SKIP_TAGS`, so every equation on every page was removed before extraction
began. On a benchmark that costs a couple of points. On a scientific or financial page it
removes the thing the page is about, and a graph built from that output has the prose around a
result and not the result.
"""

from __future__ import annotations

from webgraph.dom.blocks import SKIP_TAGS, parse_html, replace_math_with_latex
from webgraph.dom.math import latex_from_math, render_math
from webgraph.pipeline import build_document

BASE = "https://example.test/paper"


def text_of(body: str) -> str:
    return build_document(f"<html><body>{body}</body></html>", BASE).text.strip()


def math_of(inner: str, attrs: str = ""):  # type: ignore[no-untyped-def]
    """One `<math>` element, parsed *without* the engine's own rewrite.

    `parse_html` now converts mathematics as part of parsing, so asking it for a `<math>`
    element returns nothing -- by design. These tests exercise the converter directly and so
    need the raw tree.
    """
    from lxml import html as lxml_html

    tree = lxml_html.document_fromstring(
        f"<html><body><math {attrs}>{inner}</math></body></html>"
    )
    return tree.xpath("//*[local-name()='math']")[0]


class TestTheCascade:
    """Cheapest and most faithful source first. The author's own LaTeX beats anything a
    converter can reconstruct from presentation markup."""

    def test_a_tex_annotation_wins(self) -> None:
        element = math_of(
            "<semantics><mrow><mi>q</mi></mrow>"
            '<annotation encoding="application/x-tex">\\int_0^1 f(x)\\,dx</annotation></semantics>'
        )
        assert latex_from_math(element) == r"\int_0^1 f(x)\,dx"

    def test_alttext_is_next(self) -> None:
        assert latex_from_math(math_of("<mi>q</mi>", 'alttext="\\alpha + \\beta"')) == r"\alpha + \beta"

    def test_otherwise_the_markup_is_converted(self) -> None:
        element = math_of("<mrow><msub><mi>R</mi><mn>1</mn></msub><mo>=</mo>"
                          "<mfrac><mi>a</mi><mi>b</mi></mfrac></mrow>")
        assert latex_from_math(element) == r"R_1=\frac{a}{b}"


class TestConversion:
    def test_a_command_argument_is_always_braced(self) -> None:
        r"""`\sqrt` + `n` is `\sqrtn`, a different command and not a square root. A single
        character needs no braces as a superscript and always needs them as an argument."""
        assert latex_from_math(math_of("<msqrt><mi>n</mi></msqrt>")) == r"\sqrt{n}"
        assert latex_from_math(math_of("<mfrac><mi>a</mi><mi>b</mi></mfrac>")) == r"\frac{a}{b}"
        assert latex_from_math(math_of("<msup><mi>c</mi><mn>2</mn></msup>")) == "c^2"

    def test_greek_letters_get_their_command(self) -> None:
        assert latex_from_math(math_of("<mi>σ</mi>")) == r"\sigma"
        assert latex_from_math(math_of("<mi>Ω</mi>")) == r"\Omega"

    def test_operators_are_translated(self) -> None:
        assert latex_from_math(math_of("<mo>×</mo>")) == r"\times"
        assert latex_from_math(math_of("<mo>≤</mo>")) == r"\leq"

    def test_an_unknown_operator_passes_through(self) -> None:
        assert latex_from_math(math_of("<mo>=</mo>")) == "="

    def test_nothing_recoverable_yields_nothing(self) -> None:
        assert latex_from_math(math_of("")) == ""
        assert render_math(math_of("")) == ""


class TestDelimiters:
    def test_inline_maths_uses_single_dollars(self) -> None:
        assert render_math(math_of("<mi>x</mi>")) == "$x$"

    def test_display_maths_uses_double(self) -> None:
        assert render_math(math_of("<mi>x</mi>", 'display="block"')) == "$$x$$"


class TestInThePage:
    def test_math_is_no_longer_stripped(self) -> None:
        assert "math" not in SKIP_TAGS

    def test_an_inline_equation_stays_in_its_sentence(self) -> None:
        """A reader meets it mid-sentence and every corpus annotates it that way. Emitting it
        as a block of its own would split the sentence in two."""
        assert text_of("<p>Then <math><mi>x</mi></math> follows.</p>") == "Then $x$ follows."

    def test_a_display_equation_becomes_its_own_block(self) -> None:
        out = text_of('<p>Before.</p><math display="block"><mrow><mi>E</mi><mo>=</mo>'
                      "<mi>m</mi><msup><mi>c</mi><mn>2</mn></msup></mrow></math><p>After.</p>")
        assert out == "Before.\n\n$$E=mc^2$$\n\nAfter."

    def test_dropping_an_empty_equation_keeps_the_sentence(self) -> None:
        """lxml stores the text *following* an element on that element, so removing
        `<math></math>` from "Plain <math></math> sentence." deleted " sentence." with it."""
        assert text_of("<p>Plain <math></math> sentence.</p>") == "Plain sentence."

    def test_parsing_leaves_no_mathml_behind(self) -> None:
        """The rewrite happens during parsing, so nothing downstream can strip an equation
        by accident -- there is none left to strip."""
        root = parse_html("<html><body><p><math><mi>a</mi></math></p></body></html>")
        assert root.xpath("//*[local-name()='math']") == []
        assert replace_math_with_latex(root) == 0


class TestFallbackImages:
    """The picture of the formula that sits beside the formula.

    MediaWiki emits every equation twice: `<math>` for machines, and an `<img>` of the
    rendering for browsers without MathML, with the same LaTeX in its `alt`. Converting the
    first and keeping the second reported every formula twice -- 204 images of equations
    already in the text on one Wikipedia article.
    """

    WIKI = (
        '<p>Momentum: <span class="mwe-math-element">'
        '<span class="mwe-math-mathml-inline" style="display:none">'
        '<math><semantics><mi>x</mi><annotation encoding="application/x-tex">'
        "{\\displaystyle x}</annotation></semantics></math></span>"
        '<img class="mwe-math-fallback-image-inline" alt="{\\displaystyle x}" '
        'src="https://wikimedia.org/api/rest_v1/media/math/render/svg/abc"></span> is it.</p>'
    )

    def test_the_fallback_image_is_dropped(self) -> None:
        from webgraph.pipeline import build_document
        from webgraph.render_markdown import to_markdown

        out = to_markdown(build_document(f"<html><body>{self.WIKI}</body></html>", "https://x.test/"))
        assert "$" in out and "displaystyle x" in out
        assert "math/render" not in out
        assert "is it." in out

    def test_a_real_figure_beside_an_equation_survives(self) -> None:
        from webgraph.pipeline import build_document
        from webgraph.render_markdown import to_markdown

        html = (
            "<p><math><mi>y</mi></math>"
            '<img alt="Diagram of the apparatus" src="https://x.test/apparatus.png" width="400" height="300"></p>'
        )
        out = to_markdown(build_document(f"<html><body>{html}</body></html>", "https://x.test/"))
        assert "apparatus.png" in out

    def test_an_unconvertible_formula_keeps_its_picture(self) -> None:
        """When nothing can be read from the `<math>`, the image *is* the content."""
        from webgraph.pipeline import build_document
        from webgraph.render_markdown import to_markdown

        html = (
            '<p><span><math></math></span>'
            '<img alt="{\\displaystyle z}" src="https://wikimedia.org/api/rest_v1/media/math/render/svg/z" width="40" height="40"></p>'
        )
        out = to_markdown(build_document(f"<html><body>{html}</body></html>", "https://x.test/"))
        assert "math/render/svg/z" in out
