"""Structure-preserving block extraction.

Plain text extraction throws away most of what a page means. A heading becomes an
indistinguishable line, a table collapses into loose cells with no idea which column they
belonged to, links lose their targets, and images vanish entirely -- even though the alt
text and caption around an image are frequently the most information-dense text on a page.

This module classifies each block instead: heading (with level), list item (with nesting
and ordering), table (with rows), image (with source and alt), code (with language), quote.
Reading order then sequences those blocks exactly as before, and the Markdown renderer can
reproduce the document rather than a transcript of it.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urljoin

from lxml import etree
from lxml.html import HtmlElement

from webgraph.dom.blocks import SKIP_TAGS, normalize_text
from webgraph.types import Block, BlockKind

__all__ = ["extract_rich_blocks"]

_HEADINGS: Final[frozenset[str]] = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})

_TEXT_CONTAINERS: Final[frozenset[str]] = frozenset({
    "p", "div", "section", "article", "main", "aside", "header", "footer", "nav",
    "li", "dt", "dd", "caption", "figcaption", "summary", "details",
    "address", "label", "button", "legend",
})

_ATOMIC: Final[frozenset[str]] = frozenset({"table", "pre", "blockquote", "img", "figure"})
"""Handled whole. Descending into them would shatter the structure being preserved."""

_MIN_IMAGE_DIMENSION: Final[int] = 32
"""Images declared smaller than this are tracking pixels and spacers, not content."""


_INLINE_EMPHASIS: Final[frozenset[str]] = frozenset({"strong", "b"})
_INLINE_ITALIC: Final[frozenset[str]] = frozenset({"em", "i"})


def _inline_markdown(element: HtmlElement, base: str) -> str:
    """Render a block's inline content as Markdown, preserving link targets.

    Plain `text_content()` throws away every `href`. Measured against trafilatura on
    danluu.com, that lost **201 links on a single page** -- for an engine whose job is rich
    extraction, the URL is often the most useful part of the sentence.

    Only inline constructs are handled here; block structure is the caller's concern.
    """
    parts: list[str] = [element.text or ""]

    for child in element:
        tag = child.tag if isinstance(child.tag, str) else ""
        inner = _inline_markdown(child, base) if len(child) else normalize_text(child.text_content())

        if tag == "a":
            href = _absolute(child.get("href"), base)
            label = inner or normalize_text(child.text_content())
            # A link with no text contributes nothing a reader can use.
            parts.append(f"[{label}]({href})" if href and label else label)
        elif tag in _INLINE_EMPHASIS and inner:
            parts.append(f"**{inner}**")
        elif tag in _INLINE_ITALIC and inner:
            parts.append(f"*{inner}*")
        elif tag == "code" and inner:
            parts.append(f"`{inner}`")
        elif tag == "br":
            parts.append(" ")
        else:
            parts.append(inner)

        parts.append(child.tail or "")

    return normalize_text("".join(parts))


def _absolute(url: str | None, base: str) -> str | None:
    if not url or not url.strip():
        return None
    candidate = url.strip()
    if candidate.startswith(("data:", "blob:")):
        return None
    return urljoin(base, candidate)


def _image_block(element: HtmlElement, base: str, index: int, tree: object) -> Block | None:
    """Build an image block, skipping spacers and tracking pixels.

    Prefers `srcset`'s first candidate when `src` is a placeholder, which is how lazy-loading
    markup usually hides the real image from a naive reader.
    """
    src = _absolute(element.get("src"), base)
    if not src:
        for attribute in ("data-src", "data-lazy-src", "data-original"):
            src = _absolute(element.get(attribute), base)
            if src:
                break
    if not src:
        srcset = element.get("srcset") or ""
        first = srcset.split(",")[0].strip().split(" ")[0] if srcset else ""
        src = _absolute(first, base)
    if not src:
        return None

    for dimension in ("width", "height"):
        raw = element.get(dimension)
        if raw and raw.isdigit() and int(raw) < _MIN_IMAGE_DIMENSION:
            return None

    alt = normalize_text(element.get("alt")) or ""
    title = normalize_text(element.get("title"))

    return Block(
        text=alt or title or "",
        tag="img",
        xpath=tree.getpath(element),  # type: ignore[attr-defined]
        dom_index=index,
        kind=BlockKind.IMAGE,
        href=src,
        alt=alt or title or None,
    )


def _table_block(element: HtmlElement, index: int, tree: object) -> Block | None:
    """Build a table block preserving its rows.

    A table flattened into text loses the association between a value and its column, which
    is exactly the information a pricing or spec table exists to convey.
    """
    rows: list[tuple[str, ...]] = []
    for row in element.xpath(".//tr"):
        cells = [
            normalize_text(cell.text_content())
            for cell in row.xpath("./th|./td")
        ]
        if any(cells):
            rows.append(tuple(cells))

    if not rows:
        return None

    caption = element.xpath("./caption")
    summary = normalize_text(caption[0].text_content()) if caption else ""
    flattened = " | ".join(" ".join(r) for r in rows[:3])

    return Block(
        text=summary or flattened,
        tag="table",
        xpath=tree.getpath(element),  # type: ignore[attr-defined]
        dom_index=index,
        kind=BlockKind.TABLE,
        rows=tuple(rows),
    )


def _code_language(element: HtmlElement) -> str | None:
    for node in (element, *element.xpath(".//code")):
        classes = (node.get("class") or "").split()
        for value in classes:
            for prefix in ("language-", "lang-", "highlight-"):
                if value.startswith(prefix):
                    return value[len(prefix):]
    return None


_NESTED_CONTAINERS: Final[frozenset[str]] = frozenset({"ul", "ol", "table", "dl"})


def _own_text(element: HtmlElement) -> str:
    """Text belonging to this element, excluding nested lists and tables.

    Needed because a list item that contains a sub-list would otherwise be skipped by the
    innermost-block rule and its own label lost entirely -- `<li>outer<ul><li>inner</li>
    </ul></li>` dropped "outer" completely. Its own text is real content and must survive.
    """
    parts: list[str] = [element.text or ""]
    for child in element:
        tag = child.tag
        if isinstance(tag, str) and tag in _NESTED_CONTAINERS:
            parts.append(child.tail or "")
            continue
        parts.append(child.text_content())
        parts.append(child.tail or "")
    return normalize_text("".join(parts))


def _list_context(element: HtmlElement) -> tuple[bool, int]:
    """Return (ordered, nesting level) for a list item."""
    ordered = False
    level = 0
    parent = element.getparent()
    while parent is not None:
        tag = parent.tag
        if isinstance(tag, str) and tag in {"ul", "ol"}:
            level += 1
            if level == 1:
                ordered = tag == "ol"
        parent = parent.getparent()
    return ordered, max(level, 1)


def extract_rich_blocks(
    root: HtmlElement, base_url: str, *, min_chars: int = 1
) -> list[Block]:
    """Extract blocks with their structure intact, in document order."""
    etree.strip_elements(root, *SKIP_TAGS, with_tail=False)
    etree.strip_elements(root, etree.Comment, with_tail=False)

    tree = root.getroottree()
    blocks: list[Block] = []
    index = 0
    consumed: set[HtmlElement] = set()

    for element in root.iter():
        tag = element.tag
        if not isinstance(tag, str) or element in consumed:
            continue

        block: Block | None = None

        if tag == "img":
            block = _image_block(element, base_url, index, tree)

        elif tag == "table":
            block = _table_block(element, index, tree)
            consumed.update(element.iterdescendants())

        elif tag == "pre":
            text = element.text_content().strip("\n")
            if text.strip():
                block = Block(
                    text=text,
                    tag=tag,
                    xpath=tree.getpath(element),
                    dom_index=index,
                    kind=BlockKind.CODE,
                    language=_code_language(element),
                )
            consumed.update(element.iterdescendants())

        elif tag == "blockquote":
            text = normalize_text(element.text_content())
            if text:
                block = Block(
                    text=text,
                    tag=tag,
                    xpath=tree.getpath(element),
                    dom_index=index,
                    kind=BlockKind.QUOTE,
                )
            consumed.update(element.iterdescendants())

        elif tag in _HEADINGS:
            text = normalize_text(element.text_content())
            if text:
                rich = _inline_markdown(element, base_url)
                block = Block(
                    text=text,
                    tag=tag,
                    xpath=tree.getpath(element),
                    dom_index=index,
                    kind=BlockKind.HEADING,
                    level=int(tag[1]),
                    rich_text=rich if rich != text else None,
                )

        elif tag == "figcaption":
            text = normalize_text(element.text_content())
            if text:
                block = Block(
                    text=text,
                    tag=tag,
                    xpath=tree.getpath(element),
                    dom_index=index,
                    kind=BlockKind.FIGURE_CAPTION,
                )

        elif tag in _TEXT_CONTAINERS:
            # Innermost rule: only emit when no descendant is itself a block, so a wrapper
            # div never swallows a whole column.
            has_block_descendant = any(
                isinstance(d.tag, str)
                and (d.tag in _TEXT_CONTAINERS or d.tag in _HEADINGS or d.tag in _ATOMIC)
                and normalize_text(d.text_content())
                for d in element.iterdescendants()
            )
            # A list item wrapping a sub-list still owns its label; take that rather than
            # skipping the element and losing the text.
            text = _own_text(element) if has_block_descendant else normalize_text(
                element.text_content()
            )
            if text and (not has_block_descendant or tag in {"li", "dd", "dt"}):
                ordered, level = _list_context(element) if tag == "li" else (False, 0)
                rich = _inline_markdown(element, base_url)
                block = Block(
                    text=text,
                    tag=tag,
                    xpath=tree.getpath(element),
                    dom_index=index,
                    kind=BlockKind.LIST_ITEM if tag == "li" else BlockKind.PARAGRAPH,
                    level=level,
                    ordered=ordered,
                    rich_text=rich if rich != text else None,
                )

        if block is None:
            continue
        if block.kind is not BlockKind.IMAGE and len(block.text) < min_chars:
            continue

        blocks.append(block)
        index += 1

    return blocks
