"""Turn parsed HTML into the text blocks that reading order operates on.

Granularity is the whole design question here. Per-word blocks make ordering noisy and
expensive; per-section blocks hide the column structure that reading order needs to see.
We emit one block per *innermost block-level element that contains text* -- which lands on
paragraphs, headings, list items and table cells, and keeps inline markup (`<a>`, `<em>`,
`<strong>`) inside its parent rather than shattering a sentence across blocks.
"""

from __future__ import annotations

import re
from typing import Final

from lxml import etree
from lxml import html as lxml_html
from lxml.html import HtmlElement

from webgraph.types import Block

__all__ = [
    "BLOCK_TAGS",
    "PERMALINK_CLASSES",
    "RTL_LANGUAGES",
    "RTL_SCRIPTS",
    "SHADOW_TEMPLATE_ATTRIBUTE",
    "SKIP_TAGS",
    "extract_blocks",
    "flatten_shadow_roots",
    "is_rtl_document",
    "normalize_text",
    "parse_html",
    "strip_permalinks",
]

BLOCK_TAGS: Final[frozenset[str]] = frozenset({
    "p", "div", "section", "article", "main", "aside", "header", "footer", "nav",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "dt", "dd", "td", "th", "caption",
    "blockquote", "pre", "figcaption", "figure", "summary", "details",
    "address", "label", "button", "legend", "fieldset", "form",
})
"""Block-level containers. Inline tags are deliberately absent so that `<p>a <a>b</a> c</p>`
stays one block instead of three."""

SKIP_TAGS: Final[tuple[str, ...]] = (
    "script", "style", "noscript", "template", "svg", "math",
    "iframe", "object", "embed", "audio", "video", "source", "track", "param",
)
"""Stripped from the tree before extraction. Their text is never page content -- leaving a
`<script>` in place makes an ancestor's `text_content()` return JavaScript source.

`canvas` is deliberately *not* stripped: it has no readable text either way, but its
presence is a signal the profiler uses to flag that a vision path is required."""

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    """Collapse runs of whitespace and trim. HTML whitespace is not semantic."""
    if not value:
        return ""
    return _WHITESPACE.sub(" ", value).strip()


MAX_DOCUMENT_BYTES: Final[int] = 32 * 1024 * 1024
"""Refuse documents larger than this before parsing.

Needed because `huge_tree` (below) disables libxml2's built-in resource guards, and a
crawler's input is untrusted by definition. Bounding size up front is the safe way to buy
unlimited nesting depth.
"""


def parse_html(html: str, *, max_bytes: int = MAX_DOCUMENT_BYTES) -> HtmlElement:
    """Parse a document, tolerating the malformed markup that real pages ship.

    Uses `huge_tree=True` because libxml2's default HTML parser caps nesting at 255 levels
    and, past that, **silently discards the content** -- `text_content()` returns an empty
    string with no error raised. Utility-class frameworks nest wrapper `<div>`s deeply
    enough to hit this, so the default would lose whole pages invisibly.
    """
    if not html.strip():
        raise ValueError("cannot parse empty HTML")

    size = len(html.encode("utf-8", errors="ignore"))
    if size > max_bytes:
        raise ValueError(f"document is {size} bytes, exceeding the {max_bytes} byte limit")

    parser = lxml_html.HTMLParser(huge_tree=True, recover=True)
    root = lxml_html.document_fromstring(html, parser=parser)
    # Shadow content arrives as `<template shadowrootmode>` and must be unwrapped before
    # anything strips `<template>`. Every consumer of a parsed page wants this, so it
    # happens here rather than at each call site.
    flatten_shadow_roots(root)
    return root


SHADOW_TEMPLATE_ATTRIBUTE: Final[str] = "shadowrootmode"
"""Marks a `<template>` that is a serialised shadow root, not an inert template.

`Element.getHTML({serializableShadowRoots: true})` emits open shadow roots as
`<template shadowrootmode="open">`. That is the standard declarative-shadow-DOM form, and
it is how the browser hands us content that `outerHTML` silently omits.
"""


def flatten_shadow_roots(root: HtmlElement) -> int:
    """Unwrap serialised shadow roots so their content is ordinary markup. Returns the count.

    Necessary because `template` is in `SKIP_TAGS`: a serialised shadow root would otherwise
    be stripped along with the inert templates it is syntactically identical to, and the
    content would be lost exactly as it was before the browser was asked for it.

    Only templates carrying `shadowrootmode` are unwrapped. A genuine inert `<template>` is
    markup the page has *not* rendered, and it stays stripped -- flattening those would
    invent content, which is the opposite failure but a failure all the same.
    """
    flattened = 0
    # Deepest first, so a shadow root nested inside another is unwrapped before its parent
    # moves. Materialised because the tree is mutated during the walk.
    templates = list(root.iter("template"))
    for template in reversed(templates):
        if template.get(SHADOW_TEMPLATE_ATTRIBUTE) is None:
            continue
        parent = template.getparent()
        if parent is None:
            continue
        index = parent.index(template)
        # The host's own light-DOM children stay where they are; the shadow content is
        # spliced in ahead of them, which is where the browser paints it.
        for offset, child in enumerate(list(template)):
            parent.insert(index + offset, child)
        text = (template.text or "").strip()
        if text:
            previous = template.getprevious()
            if previous is not None:
                previous.tail = (previous.tail or "") + " " + text
            else:
                parent.text = (parent.text or "") + " " + text
        if template.tail:
            previous = template.getprevious()
            if previous is not None:
                previous.tail = (previous.tail or "") + template.tail
            else:
                parent.text = (parent.text or "") + template.tail
        parent.remove(template)
        flattened += 1
    return flattened


PERMALINK_CLASSES: Final[tuple[str, ...]] = (
    "headerlink",
    "hash-link",
    "anchor-link",
    "header-anchor",
    "heading-link",
    "permalink",
)
"""Class names documentation generators use for the anchor beside a heading.

Sphinx emits `<a class="headerlink">¶</a>`, MkDocs Material the same, Docusaurus
`<a class="hash-link" aria-hidden="true">#</a>`. It is a control, not part of the heading,
and left in place it reaches the reader as `Testimonials¶`, the index as a junk token, and
the Markdown as a stray glyph on every heading of a documentation site.

Matched on the class, not on the character. Stripping a trailing `¶` or `#` from every
heading would also mutilate the ones that legitimately end in one.
"""


def strip_permalinks(root: HtmlElement) -> None:
    """Drop the permalink anchors documentation generators attach to headings."""
    permalinks = set(PERMALINK_CLASSES)
    for anchor in root.xpath(".//a[@class]"):
        if not set((anchor.get("class") or "").lower().split()) & permalinks:
            continue
        parent = anchor.getparent()
        if parent is None:
            continue
        # Keep the tail: a permalink is often followed by whitespace separating the heading
        # from what comes after it.
        if anchor.tail:
            previous = anchor.getprevious()
            if previous is not None:
                previous.tail = (previous.tail or "") + anchor.tail
            else:
                parent.text = (parent.text or "") + anchor.tail
        parent.remove(anchor)


RTL_LANGUAGES: Final[frozenset[str]] = frozenset({
    "ar",    # Arabic
    "arc",   # Aramaic
    "ckb",   # Sorani Kurdish
    "dv",    # Divehi
    "fa",    # Persian
    "he",    # Hebrew
    "iw",    # Hebrew, deprecated code still emitted by older systems
    "ji",    # Yiddish, deprecated code
    "ks",    # Kashmiri
    "ku",    # Kurdish
    "nqo",   # N'Ko
    "prs",   # Dari
    "ps",    # Pashto
    "sd",    # Sindhi
    "syr",   # Syriac
    "ug",    # Uyghur
    "ur",    # Urdu
    "yi",    # Yiddish
})
"""Primary language subtags written right-to-left."""

RTL_SCRIPTS: Final[frozenset[str]] = frozenset({
    "arab", "hebr", "thaa", "syrc", "nkoo", "adlm", "rohg", "yezi", "mand", "samr",
})
"""Script subtags written right-to-left, for tags like `az-Arab` or `pa-Arab`, where the
language is written in more than one script and only the script settles the direction."""


def is_rtl_document(root: HtmlElement) -> bool:
    """Whether this document reads right to left.

    Reading order needs this. `order_blocks` reverses column order when `rtl` is set, so on
    a multi-column Arabic or Hebrew page getting it wrong does not degrade the output -- it
    reads the columns backwards, and reports `geometric-xy-cut` while doing so. Confidently
    wrong is the worst failure this engine has.

    Two sources, in order of authority:

    1. **`dir` on `<html>` or `<body>`.** The page's own declaration, and it wins outright --
       including when it says `ltr` on a page whose language is usually RTL, which is a
       deliberate choice by its author (a Hebrew-language site presenting code or tabular
       data left-to-right).
    2. **`lang` on `<html>`.** Needed because the attribute is frequently absent:
       `ynet.co.il` carries **no `dir` anywhere** in either representation, and is RTL only
       via CSS. Its `lang="he"` is the sole signal in the markup.

    Deliberately *not* a character-frequency heuristic. A page that merely quotes Arabic --
    a dictionary entry, a news article about the region, this engine's own test fixtures --
    would flip the reading order of the whole document. The cost of a false positive is a
    silently reversed page, so only a declaration counts.
    """
    for element in (root, *root.xpath("//body")):
        declared = (element.get("dir") or "").strip().lower()
        if declared in ("rtl", "ltr"):
            return declared == "rtl"

    tag = (root.get("lang") or root.get("xml:lang") or "").strip().lower()
    if not tag:
        return False

    parts = tag.replace("_", "-").split("-")
    if parts[0] in RTL_LANGUAGES:
        return True
    return any(part in RTL_SCRIPTS for part in parts[1:])


def _strip_noise(root: HtmlElement) -> None:
    """Remove non-content elements, keeping their tail text.

    `with_tail=False` is load-bearing: it preserves the text that *follows* the element.
    Dropping it would silently lose the sentence after an inline `<script>`, which is
    common in ad-laden markup.
    """
    etree.strip_elements(root, *SKIP_TAGS, with_tail=False)
    etree.strip_elements(root, etree.Comment, with_tail=False)
    strip_permalinks(root)


def _text_maps(
    root: HtmlElement,
) -> tuple[dict[HtmlElement, bool], dict[HtmlElement, bool]]:
    """Compute, for every element, whether it holds text and whether a block descendant does.

    Both are built in one reverse-document-order pass. The naive form -- calling
    `text_content()` on every descendant of every candidate -- is quadratic, and pathological
    on the deeply nested wrapper `<div>`s that utility-class frameworks emit.
    """
    has_text: dict[HtmlElement, bool] = {}
    has_block_descendant: dict[HtmlElement, bool] = {}

    for element in reversed(list(root.iter())):
        if not isinstance(element.tag, str):
            has_text[element] = False
            has_block_descendant[element] = False
            continue

        own = bool(normalize_text(element.text))
        from_children = any(
            has_text.get(child, False) or bool(normalize_text(child.tail))
            for child in element
        )
        has_text[element] = own or from_children

        has_block_descendant[element] = any(
            (
                isinstance(child.tag, str)
                and child.tag in BLOCK_TAGS
                and has_text.get(child, False)
            )
            or has_block_descendant.get(child, False)
            for child in element
        )

    return has_text, has_block_descendant


def extract_blocks(root: HtmlElement, *, min_chars: int = 1) -> list[Block]:
    """Collect text blocks in document order.

    `dom_index` records that source order, which is what makes CSS reordering detectable
    later: if the geometric order disagrees with it, the page reordered its own content.
    """
    _strip_noise(root)
    has_text, has_block_descendant = _text_maps(root)

    tree = root.getroottree()
    blocks: list[Block] = []
    index = 0

    for element in root.iter():
        if not isinstance(element.tag, str) or element.tag not in BLOCK_TAGS:
            continue
        if not has_text.get(element, False):
            continue
        if has_block_descendant.get(element, False):
            continue

        text = normalize_text(element.text_content())
        if len(text) < min_chars:
            continue

        blocks.append(
            Block(
                text=text,
                tag=element.tag,
                xpath=tree.getpath(element),
                dom_index=index,
                depth=_depth_of(element),
            )
        )
        index += 1

    return blocks


def _depth_of(element: HtmlElement) -> int:
    depth = 0
    parent = element.getparent()
    while parent is not None:
        depth += 1
        parent = parent.getparent()
    return depth
