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

__all__ = ["MATHML_NAMESPACE", "latex_from_math", "math_elements", "render_math"]

MATHML_NAMESPACE: Final[str] = "http://www.w3.org/1998/Math/MathML"

_TEX_ANNOTATION: Final[str] = (
    ".//*[local-name()='annotation'][@encoding='application/x-tex']"
    "|.//*[local-name()='annotation'][@encoding='TeX']"
)

_OPERATORS: Final[dict[str, str]] = {
    "−": "-", "×": r"\times", "÷": r"\div", "±": r"\pm",
    "≤": r"\leq", "≥": r"\geq", "≠": r"\neq", "≈": r"\approx",
    "∞": r"\infty", "∑": r"\sum", "∏": r"\prod", "∫": r"\int",
    "∂": r"\partial", "√": r"\sqrt", "→": r"\to", "⇒": r"\Rightarrow",
    "∈": r"\in", "∉": r"\notin", "⊆": r"\subseteq", "∪": r"\cup",
    "∩": r"\cap", "⋅": r"\cdot", "′": "'",
}
"""Unicode operators to their LaTeX spellings. A `<mo>` not listed is passed through, which
is right for `+`, `=`, brackets and anything this table has not met yet."""

_GREEK: Final[frozenset[str]] = frozenset(
    "αβγδεζηθικλμνξ"
    "πρστυφχψω"
    "ΓΔΘΛΞΠΣΦΨΩ"
)
_GREEK_NAMES: Final[dict[str, str]] = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "π": "pi", "ρ": "rho", "σ": "sigma",
    "τ": "tau", "υ": "upsilon", "φ": "phi", "χ": "chi",
    "ψ": "psi", "ω": "omega", "Γ": "Gamma", "Δ": "Delta",
    "Θ": "Theta", "Λ": "Lambda", "Ξ": "Xi", "Π": "Pi",
    "Σ": "Sigma", "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega",
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


def math_elements(root: HtmlElement) -> list[HtmlElement]:
    """Every `<math>` in the tree, namespaced or not."""
    return list(root.xpath("//*[local-name()='math']"))
