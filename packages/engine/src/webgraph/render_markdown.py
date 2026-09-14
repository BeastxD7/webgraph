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
_CURRENCY_DOLLAR: Final[re.Pattern[str]] = re.compile(r"(?<!\\)\$(?=\d)")
"""A `$` that begins an amount of money: not already escaped, and followed by a digit.

Escaped **always**, not under `escape_text`, because this one is not cosmetic. Every Markdown
dialect that carries mathematics -- which is every dialect a model reads this output in --
delimits it with `$...$`, so an unescaped currency amount silently becomes a formula, and a
*pair* of them silently becomes a formula containing all the prose between them. Measured on
WebMainBench: 18 of 200 pages containing no mathematics at all were scored as emitting
formulas, because of sentences like "spends $29.8 billion … a surplus of $344 million".

**The digit lookahead is the whole rule, and it was measured rather than guessed.** An
earlier version escaped every `$`, which fixed the false positives and broke the true ones:
the formula column's page count fell from 282 to 130 and its mean fell with it, because real
mathematics was being escaped out of existence too. In the corpus's own ground truth an
escaped dollar is followed by a digit 953 times out of 1,221, while a bare one is followed by
a space (2,743), a backslash beginning a LaTeX command (1,189), or another `$` opening display
maths (921). Money is written `$29.8`; mathematics is written `$\frac…`, `$ x`, or `$$`.

The engine's plain-text output is left alone: it is not Markdown and nothing there is a
delimiter."""

_MATH_SPAN: Final[re.Pattern[str]] = re.compile(r"(?<!\\)\$([^$\n]{1,200})(?<!\\)\$")
"""A candidate `$...$` on one line: what the rest of the toolchain would read as mathematics."""

_MATH_SIGNAL: Final[re.Pattern[str]] = re.compile(r"[\\^_{}]")
"""What separates `$0.07^{7}$` from `$0.07`.

The digit lookahead alone is not enough, because mathematics may also begin with a digit.
Measured: 275 of the ground truth's bare dollars are followed by one. Escaping those broke
real equations -- a page whose ground truth is the single formula `0.07` came back from this
engine as a formula containing the sentence in front of it, because the opening delimiter of
`$0.07^{7}$` had been escaped and the closing one then paired with something far away.

A backslash, a caret, an underscore or a brace inside the span is LaTeX and nothing else.
Prices do not contain them."""


def _escape_currency(text: str) -> str:
    """Escape dollars that begin an amount of money, leaving mathematics intact.

    Spans that read as LaTeX are located first and passed through untouched; escaping runs
    only on the text between them.
    """
    spans = [m.span() for m in _MATH_SPAN.finditer(text) if _MATH_SIGNAL.search(m.group(1))]
    if not spans:
        return _CURRENCY_DOLLAR.sub(r"\\$", text)
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        out.append(_CURRENCY_DOLLAR.sub(r"\\$", text[cursor:start]))
        out.append(text[start:end])
        cursor = end
    out.append(_CURRENCY_DOLLAR.sub(r"\\$", text[cursor:]))
    return "".join(out)


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
    escaped = _ESCAPE.sub(r"\\\1", value) if options.escape_text else value
    return _escape_currency(escaped)


def _body(block: Block, options: MarkdownOptions) -> str:
    """Prefer the inline-Markdown rendering, which keeps link targets.

    Escaping is skipped for the rich form: it already contains deliberate Markdown syntax,
    and escaping would turn `[label](url)` into literal brackets.
    """
    if block.rich_text and options.include_links:
        # Still escape `$`: the rich form carries deliberate *link* syntax, never deliberate
        # math delimiters, so a dollar in it is currency and has to say so.
        return _escape_currency(block.rich_text)
    return _text(block.text, options)


def _render_table(block: Block) -> str:
    """Render a table as pipes when pipes can say what it says, and as its own markup when
    they cannot.

    Pipe syntax has no way to express a merged cell. Rendering `<td colspan="3">` as pipes
    drops the merge and shifts every value beneath it into the wrong column, which corrupts
    the data rather than merely reformatting it. Markdown allows inline HTML, so a table that
    nests or spans keeps its own structure (`Block.table_html`, already cleaned down to the
    table tags and the two span attributes) and a plain grid renders as pipes, which is what
    a reader actually wants to look at.

    This is the rule MinerU-HTML uses, arrived at independently and for the same reason, and
    it is measurable: on WebMainBench's pages whose ground truth holds an HTML table, a pipe
    rendering caps at 0.445 where the table's own markup reaches 1.000.

    Ragged rows are padded rather than dropped, in the pipe path: dropping a short row loses
    its values, and padding keeps them and keeps the Markdown valid.
    """
    if block.table_html:
        return block.table_html
    if not block.rows:
        return ""

    width = max(len(row) for row in block.rows)
    padded = [list(row) + [""] * (width - len(row)) for row in block.rows]

    def line(cells: list[str]) -> str:
        cleaned = (_escape_currency(_TABLE_PIPE.sub(r"\\|", c)) for c in cells)
        return "| " + " | ".join(cleaned) + " |"

    header, *body = padded
    out = [line(header), "| " + " | ".join("---" for _ in range(width)) + " |"]
    out.extend(line(row) for row in body)
    return "\n".join(out)


def _render_block(block: Block, options: MarkdownOptions) -> str | None:
    rendered = _render_plain(block, options)
    if rendered is None or not block.quoted:
        return rendered
    # Inside a blockquote that held structure: every line of the block is quoted, once per
    # level, so a table or a list keeps its shape inside the quote.
    prefix = "> " * block.quoted
    return "\n".join(prefix + line for line in rendered.split("\n"))


def _render_plain(block: Block, options: MarkdownOptions) -> str | None:
    kind = block.kind

    if kind is BlockKind.HEADING:
        level = min(max(block.level + options.heading_offset, 1), 6)
        return f"{'#' * level} {_ONE_LINE.sub(' ', _body(block, options))}"

    if kind is BlockKind.IMAGE:
        if not options.include_images or not block.href:
            return None
        alt = _text(block.alt or "", options)
        return f"![{alt}]({block.href})"

    if kind is BlockKind.MEDIA:
        # Rendered as an italic aside rather than a link or an image: it is a note *about*
        # the document, not content in it, and a reader -- or a model building notes -- should
        # not mistake the placeholder for something that was transcribed.
        return f"*{block.text}*"

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
        continuation = "\n" + indent + " " * (len(marker) + 1)
        return f"{indent}{marker} {_ONE_LINE.sub(continuation, _body(block, options))}"

    if kind is BlockKind.FIGURE_CAPTION:
        return f"*{_ONE_LINE.sub(' ', _text(block.text, options))}*"

    if kind is BlockKind.PARAGRAPH and block.level:
        # A paragraph inside a list item after its first: indented under the bullet, as
        # CommonMark wants a continuation paragraph.
        indent = "  " * max(block.level - 1, 0) + "   "
        return "\n".join(indent + line for line in _hard_breaks(_body(block, options)).split("\n"))
    return _hard_breaks(_body(block, options))


_ONE_LINE = re.compile(r"\s*\n+\s*")
_SINGLE_NEWLINE = re.compile(r"(?<!\n)\n(?!\n)")


def _hard_breaks(text: str) -> str:
    """A line break inside a paragraph -- a `<br>` -- is a Markdown hard break (a backslash
    at the line's end); a blank line -- `<br><br>` -- is left as the paragraph break it is."""
    return _SINGLE_NEWLINE.sub("\\\n", text)


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
