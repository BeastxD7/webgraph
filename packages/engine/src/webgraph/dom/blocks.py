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
    "SKIP_TAGS",
    "extract_blocks",
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
    return lxml_html.document_fromstring(html, parser=parser)


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
