"""Mathematics on a page, turned back into something a reader or a model can use.

Why this module exists
----------------------
`math` sat in `SKIP_TAGS`, so **every equation on every page was deleted before extraction
began**. On a benchmark that costs a couple of points; on a corpus of scientific or financial
pages it removes the thing the page is about, and a graph built from that output has the prose
around a result and not the result.

What is emitted
---------------
LaTeX, wrapped in `$...$` inline or `$$...$$` for a display equation. That is what the rest of
the toolchain already expects: it is how Markdown carries mathematics, how the corpora
annotate it, and what a model reads without being told anything.

How the LaTeX is obtained, cheapest first
-----------------------------------------
1. **`<annotation encoding="application/x-tex">`** -- MathJax and KaTeX embed the author's
   original source here. When present it is exact and nothing else can improve on it.
2. **`@alttext`** -- what the author wrote, kept for screen readers.
3. **Converting the MathML itself.** Only reached when the page shipped presentation MathML
   with no source, which is where `<mfrac>`, `<msup>` and friends have to be walked.

Deliberately not attempted: semantic reconstruction. `<mi>x</mi>` becomes `x`, not a guess
about what `x` means.
"""

from __future__ import annotations

import re
from typing import Final

from lxml.html import HtmlElement

__all__ = [
    "MATHML_NAMESPACE",
    "latex_from_math",
    "math_elements",
    "mathjax_source_latex",
    "render_math",
]

MATHML_NAMESPACE: Final[str] = "http://www.w3.org/1998/Math/MathML"

_TEX_ANNOTATION: Final[str] = (
    ".//*[local-name()='annotation'][@encoding='application/x-tex']"
    "|.//*[local-name()='annotation'][@encoding='TeX']"
)

_OPERATORS: Final[dict[str, str]] = {
    "−": "-",
    "×": r"\times",
    "÷": r"\div",
    "±": r"\pm",
    "≤": r"\leq",
    "≥": r"\geq",
    "≠": r"\neq",
    "≈": r"\approx",
    "∞": r"\infty",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "∂": r"\partial",
    "√": r"\sqrt",
    "→": r"\to",
    "⇒": r"\Rightarrow",
    "∈": r"\in",
    "∉": r"\notin",
    "⊆": r"\subseteq",
    "∪": r"\cup",
    "∩": r"\cap",
    "⋅": r"\cdot",
    "′": "'",
}
"""Unicode operators to their LaTeX spellings. A `<mo>` not listed is passed through, which
is right for `+`, `=`, brackets and anything this table has not met yet."""

_GREEK: Final[frozenset[str]] = frozenset("αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ")
_GREEK_NAMES: Final[dict[str, str]] = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "ζ": "zeta",
    "η": "eta",
    "θ": "theta",
    "ι": "iota",
    "κ": "kappa",
    "λ": "lambda",
    "μ": "mu",
    "ν": "nu",
    "ξ": "xi",
    "π": "pi",
    "ρ": "rho",
    "σ": "sigma",
    "τ": "tau",
    "υ": "upsilon",
    "φ": "phi",
    "χ": "chi",
    "ψ": "psi",
    "ω": "omega",
    "Γ": "Gamma",
    "Δ": "Delta",
    "Θ": "Theta",
    "Λ": "Lambda",
    "Ξ": "Xi",
    "Π": "Pi",
    "Σ": "Sigma",
    "Φ": "Phi",
    "Ψ": "Psi",
    "Ω": "Omega",
}

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
_MAX_NODES: Final[int] = 4_000
"""Untrusted input: refuse to walk an unbounded tree."""


def _local(element: HtmlElement) -> str:
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _text(element: HtmlElement) -> str:
    return _WHITESPACE.sub(" ", (element.text or "")).strip()


def _token(value: str) -> str:
    """One identifier or number as LaTeX. Greek letters get their command spelling."""
    if len(value) == 1 and value in _GREEK:
        return "\\" + _GREEK_NAMES[value]
    return value


def _arg(value: str) -> str:
    """A command's argument. **Always** braced, even for a single character.

    `\\sqrt` + `n` is `\\sqrtn`, which is a different command and not a square root, and
    `\\frac` + `a` + `b` is `\\fracab`, which is nothing at all. A command argument is the one
    place the braces are never optional.
    """
    return "{" + value + "}"


def _script(value: str) -> str:
    """A super- or subscript, where a single character needs no braces: `x^2`, not `x^{2}`."""
    return value if len(value) == 1 else "{" + value + "}"


def _convert(element: HtmlElement, budget: list[int]) -> str:
    """One MathML node to LaTeX. `budget` is a one-element list used as a node counter."""
    budget[0] -= 1
    if budget[0] <= 0:
        return ""
    name = _local(element)
    children = [c for c in element if isinstance(c.tag, str)]
    parts = [_convert(child, budget) for child in children]

    if name in {"mi", "mn"}:
        return _token(_text(element))
    if name == "mo":
        raw = _text(element)
        return _OPERATORS.get(raw, raw)
    if name == "mtext":
        body = _text(element)
        return rf"\text{{{body}}}" if body else ""
    if name == "mspace":
        return r"\,"
    if name == "mfrac" and len(parts) == 2:
        return rf"\frac{_arg(parts[0])}{_arg(parts[1])}"
    if name == "msqrt":
        return rf"\sqrt{_arg(''.join(parts))}"
    if name == "mroot" and len(parts) == 2:
        return rf"\sqrt[{parts[1]}]{_arg(parts[0])}"
    if name == "msup" and len(parts) == 2:
        return f"{_script(parts[0])}^{_script(parts[1])}"
    if name == "msub" and len(parts) == 2:
        return f"{_script(parts[0])}_{_script(parts[1])}"
    if name == "msubsup" and len(parts) == 3:
        return f"{_script(parts[0])}_{_script(parts[1])}^{_script(parts[2])}"
    if name == "munder" and len(parts) == 2:
        return rf"\underset{_arg(parts[1])}{_arg(parts[0])}"
    if name == "mover" and len(parts) == 2:
        return rf"\overset{_arg(parts[1])}{_arg(parts[0])}"
    if name == "munderover" and len(parts) == 3:
        return f"{_script(parts[0])}_{_script(parts[1])}^{_script(parts[2])}"
    if name == "mtd":
        return "".join(parts)
    if name == "mtr":
        return " & ".join(parts)
    if name == "mtable":
        body = r" \\ ".join(p for p in parts if p)
        return rf"\begin{{array}}{{c}} {body} \end{{array}}" if body else ""
    if name == "mfenced":
        opener = element.get("open", "(")
        closer = element.get("close", ")")
        return rf"\left{opener} {' , '.join(parts)} \right{closer}"
    if name == "menclose":
        body = "".join(parts)
        if not body:
            return ""
        notation = (element.get("notation") or "box").strip().lower()
        if "radical" in notation:
            return rf"\sqrt{_arg(body)}"
        if "box" in notation or "circle" in notation:
            return rf"\boxed{_arg(body)}"
        # longdiv, the diagonal/vertical/horizontal strikes, actuarial, phasorangle,
        # madruwb: no plain-LaTeX equivalent without extra packages. The enclosure is not
        # claimed -- there is no `\notembox` in this output -- but the content under it is
        # not lost either.
        return body
    if name == "mmultiscripts" and children:
        # General pre- and post-scripts: nuclear notation (mass number and atomic number
        # both preceding the element, `<mprescripts/>` marks the boundary) and multi-index
        # tensors. `<none/>` is MathML's placeholder for a script that is absent; it has no
        # text and no children, so it already converts to "" through the generic fallback
        # below and needs no special case here.
        rest = children[1:]
        rest_parts = parts[1:]
        split = next((i for i, c in enumerate(rest) if _local(c) == "mprescripts"), None)
        pre_parts = rest_parts[split + 1 :] if split is not None else []
        post_parts = rest_parts[:split] if split is not None else rest_parts

        def _pairs(values: list[str]) -> list[tuple[str, str]]:
            return [(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]

        prefix = ""
        for sub, sup in _pairs(pre_parts):
            piece = (f"_{_script(sub)}" if sub else "") + (f"^{_script(sup)}" if sup else "")
            if piece:
                prefix += "{}" + piece
        suffix = "".join(
            (f"_{_script(sub)}" if sub else "") + (f"^{_script(sup)}" if sup else "")
            for sub, sup in _pairs(post_parts)
        )
        return f"{prefix}{parts[0]}{suffix}"
    # mrow, mstyle, semantics, math, mpadded, mphantom and anything unmet: pass through.
    if name in {"annotation", "annotation-xml"}:
        return ""
    return "".join(parts)


def latex_from_math(element: HtmlElement) -> str:
    """LaTeX for one `<math>` element, by the cascade in this module's docstring."""
    annotated = element.xpath(_TEX_ANNOTATION)
    if annotated:
        source = _WHITESPACE.sub(" ", (annotated[0].text or "")).strip()
        if source:
            return source

    alt = (element.get("alttext") or "").strip()
    if alt:
        return _WHITESPACE.sub(" ", alt)

    return _WHITESPACE.sub(" ", _convert(element, [_MAX_NODES])).strip()


def render_math(element: HtmlElement) -> str:
    """One `<math>` element as delimited LaTeX, or "" when nothing could be recovered."""
    latex = latex_from_math(element)
    if not latex:
        return ""
    display = (element.get("display") or "").lower() == "block"
    return f"$${latex}$$" if display else f"${latex}$"


_ASSISTIVE_WRAPPERS: Final[frozenset[str]] = frozenset({"mjx-assistive-mml"})
"""MathJax v3's own tag for its hidden, screen-reader-only copy of a formula: the *same*
formula rendered twice, once as CHTML/SVG for sighted users (marked `aria-hidden="true"`,
the opposite of what it looks like) and once as this real `<math>` tree, clipped to a 1px
box for assistive technology. It is walked up to `_OUTER_DUPLICATE_TAGS` below rather than
detected by computed style, because `replace_math_with_latex` runs on parsed markup before
any browser has rendered it -- there is no style to compute yet."""

_OUTER_DUPLICATE_TAGS: Final[frozenset[str]] = frozenset({"mjx-container"})
"""The element that holds *both* halves of a MathJax v3 equation. Replacing only the
hidden `<math>` with its LaTeX -- the naive fix -- would leave the CHTML/SVG half sitting
right next to it: every formula twice, the second copy a wall of `<mjx-c>` glyph spans a
reader never sees as anything but the properly typeset equation. Replacing this ancestor
instead removes both at once."""

_MAX_ANCESTOR_WALK: Final[int] = 8
"""How far up from a `<math>` element to look for an assistive wrapper or its container.
Untrusted markup: a bound, not a belief that six levels is architecturally significant."""


def _duplicate_visual_container(element: HtmlElement) -> HtmlElement | None:
    """The ancestor to replace instead of `element`, when converting it would otherwise
    leave a visual duplicate of the same formula sitting beside the result.

    Two vendors, the same shape: MathJax v3's `<mjx-assistive-mml>` and KaTeX's
    `class="katex-mathml"` each hold a real, hidden `<math>` next to a visible sibling that
    renders the identical formula in HTML/SVG for sighted users. Reading the hidden copy is
    right -- it is the more faithful source, the same reason the TeX `<annotation>` cascade
    in `latex_from_math` is read before falling back to walking presentation markup -- but
    only if the visible half goes with it; otherwise the page gains a second, uglier
    rendering of a formula it already had.
    """
    node = element
    assistive = False
    for _ in range(_MAX_ANCESTOR_WALK):
        node = node.getparent()
        if node is None:
            return None
        name = _local(node)
        classes = (node.get("class") or "").split()
        if name in _ASSISTIVE_WRAPPERS or "katex-mathml" in classes:
            assistive = True
            continue
        if assistive and (name in _OUTER_DUPLICATE_TAGS or "katex" in classes):
            return node
    return None


def mathjax_source_latex(container: HtmlElement) -> str | None:
    r"""The author's own TeX, read directly off MathJax v3's markup, when the container
    `_duplicate_visual_container` found is one of its own.

    MathJax v3 keeps the exact source it parsed as `data-latex` on the visible `<mjx-math>`
    sibling of `<mjx-assistive-mml>` -- not a reconstruction from the hidden MathML tree,
    the original characters the author wrote (confirmed live on tutorial.math.lamar.edu:
    `data-latex="x = a"` for exactly that formula, spacing and all). Reading it is both
    more faithful than walking the MathML -- the same reason an `<annotation>` is read
    before presentation markup -- and, because the page's own static HTML already carries
    that identical source between its own `\(...\)` delimiters, it is what lets the static
    and rendered halves of a union agree on one piece of text for the same formula instead
    of disagreeing and keeping both (`normalize_math_delimiters` puts the static side into
    the same `$...$` form). A container with no such sibling -- KaTeX, or a MathJax build
    without `data-latex` -- returns None and the caller falls back to converting `element`.
    """
    for child in container:
        if _local(child) == "mjx-math":
            latex = child.get("data-latex")
            if latex:
                return str(latex)
            break
    return None


def math_elements(root: HtmlElement) -> list[HtmlElement]:
    """Every `<math>` in the tree, namespaced or not."""
    return list(root.xpath("//*[local-name()='math']"))
