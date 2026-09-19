"""Mathematics survives the page instead of being deleted by it.

`math` sat in `SKIP_TAGS`, so every equation on every page was removed before extraction
began. On a benchmark that costs a couple of points. On a scientific or financial page it
removes the thing the page is about, and a graph built from that output has the prose around a
result and not the result.
"""

from __future__ import annotations

from webgraph.dom.blocks import (
    SKIP_TAGS,
    normalize_math_delimiters,
    parse_html,
    replace_math_with_latex,
)
from webgraph.dom.math import latex_from_math, mathjax_source_latex, render_math
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

    tree = lxml_html.document_fromstring(f"<html><body><math {attrs}>{inner}</math></body></html>")
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
        assert (
            latex_from_math(math_of("<mi>q</mi>", 'alttext="\\alpha + \\beta"'))
            == r"\alpha + \beta"
        )

    def test_otherwise_the_markup_is_converted(self) -> None:
        element = math_of(
            "<mrow><msub><mi>R</mi><mn>1</mn></msub><mo>=</mo>"
            "<mfrac><mi>a</mi><mi>b</mi></mfrac></mrow>"
        )
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


class TestComplexStructures:
    """Real chemistry and physics notation, not just single operators: isotopes (a
    superscript mass number and a subscript atomic number, both preceding the element),
    matrices, enclosed expressions, and scripts nested inside other scripts."""

    def test_an_isotope_prescripts_both_the_mass_and_atomic_number(self) -> None:
        r"""Uranium-235, `{}_{92}^{235}U`: `<mprescripts/>` marks the boundary between the
        post-scripts (none here) and the pre-scripts (atomic number, mass number)."""
        markup = "<mmultiscripts><mi>U</mi><mprescripts/><mn>92</mn><mn>235</mn></mmultiscripts>"
        assert latex_from_math(math_of(markup)) == r"{}_{92}^{235}U"

    def test_an_isotope_with_only_the_mass_number_omits_the_missing_prescript(self) -> None:
        r"""Carbon-14 written without its atomic number: `<none/>` is MathML's placeholder
        for an absent script and must not become a stray empty `_{}`."""
        markup = "<mmultiscripts><mi>C</mi><mprescripts/><none/><mn>14</mn></mmultiscripts>"
        assert latex_from_math(math_of(markup)) == r"{}^{14}C"

    def test_a_tensor_index_is_a_plain_postscript_pair(self) -> None:
        markup = "<mmultiscripts><mi>T</mi><mi>i</mi><mi>j</mi></mmultiscripts>"
        assert latex_from_math(math_of(markup)) == "T_i^j"

    def test_a_scripted_exponent_nests_correctly(self) -> None:
        r"""`x^(2/3)`: an `<mfrac>` as the exponent of an `<msup>`. The recursive design
        converts the fraction first and the outer script wraps whatever it receives, so
        nesting needs no case of its own -- this proves it for the case most likely to
        break, a multi-character script that must be braced."""
        markup = "<msup><mi>x</mi><mfrac><mn>2</mn><mn>3</mn></mfrac></msup>"
        assert latex_from_math(math_of(markup)) == r"x^{\frac{2}{3}}"

    def test_a_two_by_two_matrix_from_mtable(self) -> None:
        markup = (
            "<mtable><mtr><mtd><mn>1</mn></mtd><mtd><mn>2</mn></mtd></mtr>"
            "<mtr><mtd><mn>3</mn></mtd><mtd><mn>4</mn></mtd></mtr></mtable>"
        )
        assert latex_from_math(math_of(markup)) == r"\begin{array}{c} 1 & 2 \\ 3 & 4 \end{array}"

    def test_menclose_radical_becomes_a_square_root(self) -> None:
        assert (
            latex_from_math(math_of('<menclose notation="radical"><mi>x</mi></menclose>'))
            == r"\sqrt{x}"
        )

    def test_menclose_box_becomes_boxed(self) -> None:
        markup = '<menclose notation="box"><mi>x</mi><mo>+</mo><mi>y</mi></menclose>'
        assert latex_from_math(math_of(markup)) == r"\boxed{x+y}"

    def test_menclose_with_no_plain_latex_equivalent_keeps_the_content(self) -> None:
        """`longdiv` has no plain-LaTeX equivalent without extra packages. The enclosure is
        not claimed -- nothing here says a box was drawn -- but the number under it is not
        silently deleted either."""
        assert (
            latex_from_math(math_of('<menclose notation="longdiv"><mn>123</mn></menclose>'))
            == "123"
        )


class TestVisualDuplicates:
    r"""MathJax v3 and KaTeX each keep a real `<math>` for screen readers *beside* a visible
    HTML/SVG rendering of the identical formula. Found live on tutorial.math.lamar.edu
    (17 Sep 2026): the rendered page's own text carried the derivative's limit definition
    twice -- once as the (already imperfect) visual rendering, once as a phantom
    `\underset{h\to0}{lim}...` reconstructed from the hidden copy, malformed in ways neither
    the page's author nor MathJax's own visual output ever produced (`f^'` for `f'`, a
    fraction with no bar). Replacing only the hidden `<math>` -- the naive fix -- leaves the
    visible half standing right next to it; these tests pin that both halves go together.
    """

    def test_mathjax_v3s_assistive_copy_replaces_its_whole_container(self) -> None:
        markup = (
            '<mjx-container class="MathJax" jax="CHTML">'
            '<mjx-math aria-hidden="true"><mjx-mi>GARBLED</mjx-mi></mjx-math>'
            "<mjx-assistive-mml><math><msup><mi>x</mi><mn>2</mn></msup></math></mjx-assistive-mml>"
            "</mjx-container>"
        )
        assert text_of(f"<p>See {markup} here.</p>") == "See $x^2$ here."

    def test_katexs_mathml_copy_replaces_its_whole_container(self) -> None:
        """KaTeX's hidden copy is read via the ordinary TeX-annotation cascade -- it is the
        *right* thing to prefer, being the author's real source -- so this also proves the
        cascade and the duplicate-container removal work together, not just in isolation."""
        markup = (
            '<span class="katex"><span class="katex-mathml"><math><semantics>'
            "<mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow>"
            '<annotation encoding="application/x-tex">x + 1</annotation>'
            "</semantics></math></span>"
            '<span class="katex-html" aria-hidden="true">GARBLED</span></span>'
        )
        assert text_of(f"<p>Consider {markup} and so on.</p>") == "Consider $x + 1$ and so on."

    def test_an_ordinary_math_element_is_unaffected(self) -> None:
        """No assistive wrapper, no ancestor walk needed -- the common case is untouched."""
        assert text_of("<p>Take <math><mi>x</mi></math> to be real.</p>") == "Take $x$ to be real."

    def test_a_lookalike_class_name_does_not_trigger_the_walk(self) -> None:
        """`katex-mathml` is matched as a whole class token, not a substring: a page's own,
        unrelated `my-katex-mathml-widget` class must not make an ordinary `<math>` lose a
        sibling it was never duplicating."""
        markup = (
            '<span class="my-katex-mathml-widget"><math><mi>x</mi></math></span> '
            "<span>KEEP ME</span>"
        )
        assert text_of(f"<p>{markup}</p>") == "$x$ KEEP ME"


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
        out = text_of(
            '<p>Before.</p><math display="block"><mrow><mi>E</mi><mo>=</mo>'
            "<mi>m</mi><msup><mi>c</mi><mn>2</mn></msup></mrow></math><p>After.</p>"
        )
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

        out = to_markdown(
            build_document(f"<html><body>{self.WIKI}</body></html>", "https://x.test/")
        )
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
            "<p><span><math></math></span>"
            '<img alt="{\\displaystyle z}" src="https://wikimedia.org/api/rest_v1/media/math/render/svg/z" width="40" height="40"></p>'
        )
        out = to_markdown(build_document(f"<html><body>{html}</body></html>", "https://x.test/"))
        assert "math/render/svg/z" in out


class TestMathSourceDelimiters:
    r"""A page's own \(...\)/\[...\] -- the plain-text convention MathJax and KaTeX both
    scan the DOM for -- read as prose full of odd backslash punctuation until this runs.
    Found live on tutorial.math.lamar.edu: a "Read a page" run showed every formula in the
    article twice, the raw \(...\) source once and the engine's own $...$ conversion once,
    because the two disagreed on delimiter and the union step had no way to know they were
    the same formula.
    """

    def test_inline_delimiters_become_dollars(self) -> None:
        assert text_of(r"<p>at \(x = a\) all required us</p>") == "at $x = a$ all required us"

    def test_display_delimiters_become_double_dollars(self) -> None:
        out = text_of(r"<p>\[\mathop {\lim }\limits_{x \to a}\]</p>")
        assert out == r"$$\mathop {\lim }\limits_{x \to a}$$"

    def test_a_formula_spanning_the_whole_paragraph_is_still_found(self) -> None:
        out = text_of(r"<p>\(f(x) = 2x\)</p>")
        assert out == "$f(x) = 2x$"

    def test_two_formulas_in_one_sentence_both_convert(self) -> None:
        out = text_of(r"<p>Compare \(a\) with \(b\).</p>")
        assert out == "Compare $a$ with $b$."

    def test_code_content_is_left_alone(self) -> None:
        r"""A shell escape or a regex example -- \(a|b\) -- is not a formula. `<pre>`/`<code>`
        keep their own SKIP_TAGS treatment untouched by this."""
        out = text_of(r"<pre><code>echo \(hello\)</code></pre>")
        assert r"\(hello\)" in out
        assert "$hello$" not in out

    def test_no_delimiters_means_no_change(self) -> None:
        assert (
            text_of("<p>Plain prose about (parentheses).</p>") == "Plain prose about (parentheses)."
        )

    def test_a_direct_call_reports_how_many(self) -> None:
        tree = parse_html(r"<html><body><p>\(a\)</p><p>\(b\)</p></body></html>")
        # parse_html already ran the rewrite once; re-running finds nothing left to do.
        assert normalize_math_delimiters(tree) == 0
        assert tree.xpath("//p")[0].text == "$a$"
        assert tree.xpath("//p")[1].text == "$b$"


class TestMathJaxSourceLatex:
    r"""MathJax v3's own `data-latex` attribute, read directly rather than reconstructed
    from the hidden assistive MathML -- see `_duplicate_visual_container` and
    `TestVisualDuplicates` above for why a hidden copy exists at all."""

    def container_of(self, inner: str):  # type: ignore[no-untyped-def]
        from lxml import html as lxml_html

        tree = lxml_html.document_fromstring(f"<html><body>{inner}</body></html>")
        return tree.xpath("//*[local-name()='mjx-container']")[0]

    def test_reads_the_sibling_mjx_maths_data_latex(self) -> None:
        container = self.container_of(
            '<mjx-container><mjx-math data-latex="x = a" aria-hidden="true">'
            "<mjx-mi>x</mjx-mi></mjx-math>"
            "<mjx-assistive-mml><math><mi>x</mi></math></mjx-assistive-mml>"
            "</mjx-container>"
        )
        assert mathjax_source_latex(container) == "x = a"

    def test_none_when_there_is_no_data_latex(self) -> None:
        """KaTeX's `.katex` wrapper has no `mjx-math` sibling at all; the caller falls back
        to `latex_from_math` reading its `<annotation>` instead."""
        from lxml import html as lxml_html

        tree = lxml_html.document_fromstring(
            '<html><body><span class="katex"><span class="katex-mathml"><math></math></span>'
            '<span class="katex-html"></span></span></body></html>'
        )
        container = tree.xpath("//*[@class='katex']")[0]
        assert mathjax_source_latex(container) is None

    def test_none_when_the_attribute_is_empty(self) -> None:
        container = self.container_of(
            '<mjx-container><mjx-math data-latex=""><mjx-mi>x</mjx-mi></mjx-math>'
            "<mjx-assistive-mml><math><mi>x</mi></math></mjx-assistive-mml></mjx-container>"
        )
        assert mathjax_source_latex(container) is None
