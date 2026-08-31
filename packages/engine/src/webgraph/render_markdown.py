"""Render extracted blocks as Markdown.

Markdown rather than plain text because it is the format that survives the trip: headings
stay headings, images keep their source and alt text, tables keep their columns, and code
keeps its fences. It is also what downstream consumers -- a model, a search index, a
document store -- can actually use, whereas a wall of sentences forces them to re-infer the
structure the page already had.

Blocks arrive in *reading order*, so the Markdown reflects how a person reads the page
rather than how the HTML happened to be authored.
"""

from __future__ import annotations

import re
from typing import Final

from webgraph.types import Block, BlockKind, Document

__all__ = ["MarkdownOptions", "to_markdown"]

_ESCAPE: Final[re.Pattern[str]] = re.compile(r"([\\`*_\[\]])")
_TABLE_PIPE: Final[re.Pattern[str]] = re.compile(r"\|")


class MarkdownOptions:
    """Rendering switches.

    `include_images` is on by default: on many pages the alt text and caption around an
    image carry information available nowhere else in the markup.
    """

    def __init__(
        self,
        *,
        include_images: bool = True,
        include_tables: bool = True,
        include_links: bool = True,
        heading_offset: int = 0,
        escape_text: bool = False,
        front_matter: bool = False,
    ) -> None:
        self.include_images = include_images
        self.include_tables = include_tables
        self.include_links = include_links
        self.heading_offset = heading_offset
        self.escape_text = escape_text
        self.front_matter = front_matter


def _text(value: str, options: MarkdownOptions) -> str:
    return _ESCAPE.sub(r"\\\1", value) if options.escape_text else value


def _body(block: Block, options: MarkdownOptions) -> str:
    """Prefer the inline-Markdown rendering, which keeps link targets.

    Escaping is skipped for the rich form: it already contains deliberate Markdown syntax,
    and escaping would turn `[label](url)` into literal brackets.
    """
    if block.rich_text and options.include_links:
        return block.rich_text
    return _text(block.text, options)


def _render_table(block: Block) -> str:
    """Render a table, padding ragged rows rather than dropping them.

    Real tables have merged cells and inconsistent row lengths. Dropping short rows loses
    data; padding keeps every value and keeps the Markdown valid.
    """
    if not block.rows:
        return ""

    width = max(len(row) for row in block.rows)
    padded = [list(row) + [""] * (width - len(row)) for row in block.rows]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(_TABLE_PIPE.sub(r"\\|", c) for c in cells) + " |"

    header, *body = padded
    out = [line(header), "| " + " | ".join("---" for _ in range(width)) + " |"]
    out.extend(line(row) for row in body)
    return "\n".join(out)


def _render_block(block: Block, options: MarkdownOptions) -> str | None:
    kind = block.kind

    if kind is BlockKind.HEADING:
        level = min(max(block.level + options.heading_offset, 1), 6)
        return f"{'#' * level} {_body(block, options)}"

    if kind is BlockKind.IMAGE:
        if not options.include_images or not block.href:
            return None
        alt = _text(block.alt or "", options)
        return f"![{alt}]({block.href})"

    if kind is BlockKind.TABLE:
        if not options.include_tables:
            return None
        return _render_table(block) or None

    if kind is BlockKind.CODE:
        language = block.language or ""
        return f"```{language}\n{block.text}\n```"

    if kind is BlockKind.QUOTE:
        return "\n".join(f"> {line}" for line in block.text.splitlines() or [""])

    if kind is BlockKind.LIST_ITEM:
        indent = "  " * max(block.level - 1, 0)
        marker = "1." if block.ordered else "-"
        return f"{indent}{marker} {_body(block, options)}"

    if kind is BlockKind.FIGURE_CAPTION:
        return f"*{_text(block.text, options)}*"

    return _body(block, options)


def to_markdown(document: Document, *, options: MarkdownOptions | None = None) -> str:
    """Render a document's blocks as Markdown, in reading order."""
    options = options or MarkdownOptions()

    parts: list[str] = []

    if options.front_matter:
        parts.append(
            "\n".join(
                [
                    "---",
                    f"url: {document.url}",
                    f"content_hash: {document.content_hash}",
                    f"reading_order: {document.reading_order_method.value}",
                    f"blocks: {len(document.blocks)}",
                    "---",
                ]
            )
        )

    previous_list = False
    for block in document.blocks:
        rendered = _render_block(block, options)
        if rendered is None or not rendered.strip():
            continue

        is_list = block.kind is BlockKind.LIST_ITEM
        # Consecutive list items form one list; a blank line between them would split it.
        if parts and not (is_list and previous_list):
            parts.append("")
        parts.append(rendered)
        previous_list = is_list

    return "\n".join(parts).strip() + "\n"
