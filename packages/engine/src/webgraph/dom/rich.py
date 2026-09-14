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

import copy
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from urllib.parse import urljoin

from lxml import etree
from lxml.html import HtmlElement

from webgraph import config
from webgraph.dom.blocks import LINE_BREAK, SKIP_TAGS, normalize_text, strip_permalinks
from webgraph.markers import BREAK_ATTRIBUTE, FLOAT_ATTRIBUTE, HIDDEN_ATTRIBUTE
from webgraph.types import Block, BlockKind

LONG_CELL_CHARS = config.LONG_CELL_CHARS
MIN_GRID = config.MIN_GRID
MIN_FILLED_SHARE = config.MIN_FILLED_SHARE
MAX_EMPTY_ROW_SHARE = config.MAX_EMPTY_ROW_SHARE

__all__ = ["extract_rich_blocks"]

_HEADINGS: Final[frozenset[str]] = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})

_TEXT_CONTAINERS: Final[frozenset[str]] = frozenset({
    "p", "div", "section", "article", "main", "aside", "header", "footer", "nav",
    "li", "dt", "dd", "caption", "figcaption", "summary", "details",
    "address", "label", "button", "legend",
    # `td` and `th` are here for the *layout* table only. A data table's cells are consumed
    # whole by `_table_block`, so they never reach this path. A layout table's cells do, and
    # without these two a cell holding bare text -- `<td>About us</td>` -- produced no block
    # and its text was lost outright. Found by a test written for the shape rule that sends
    # more tables down the layout path than used to go there.
    "td", "th",
    # The page itself, and the block wrappers of pre-CSS HTML. textfiles.com closes with
    # `<CENTER><FONT>TEXTFILES.COM has been online for nearly 25 years…</FONT></CENTER>`
    # straight under `<body>`; with neither element a container the sentence, and the
    # donation line under it, were lost outright. `body` here means bare text between a
    # page's blocks is read as the orphan run it is; a `<div>` wrapper always was.
    "body", "center", "form", "fieldset",
    # A `<blockquote>` that holds structure; the leaf case is caught before this branch.
    "blockquote",
})

_ATOMIC: Final[frozenset[str]] = frozenset({"table", "pre", "blockquote", "img", "figure"})
"""Handled whole. Descending into them would shatter the structure being preserved."""

_MIN_IMAGE_DIMENSION: Final[int] = 32
"""Images declared smaller than this are tracking pixels and spacers, not content."""


_INLINE_EMPHASIS: Final[frozenset[str]] = frozenset({"strong", "b"})
_INLINE_ITALIC: Final[frozenset[str]] = frozenset({"em", "i"})

_BLOCK_BY_DEFAULT: Final[frozenset[str]] = frozenset({
    "p", "div", "section", "article", "main", "aside", "header", "footer", "nav",
    "ul", "ol", "li", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption",
    "blockquote", "pre", "figure", "figcaption", "form", "fieldset", "legend",
    "address", "hr", "br", "details", "summary",
})
"""Elements a browser lays out as their own box unless a stylesheet says otherwise.

`flowed_text` reads the renderer's mark for this, which is exact -- and absent on a static
fetch, where the old behaviour fell all the way back to `text_content()` and glued
`<div>Example 1 of 5:</div><div>Connecting to a chat server</div>` into one word. Found on
react.dev headings and in every multi-paragraph Hacker News comment (`fun.)The real`). A
stylesheet can make a `<div>` inline, but a `<div>` that is not is the overwhelmingly common
case, and a spurious space costs a reader far less than two words fused into one."""


def _breaks_line(child: HtmlElement) -> bool:
    """Whether a separator belongs before `child`: the browser said so, or its tag says so."""
    tag = child.tag
    return isinstance(tag, str) and (
        child.get(BREAK_ATTRIBUTE) is not None or tag in _BLOCK_BY_DEFAULT
    )


def _inline_markdown(
    element: HtmlElement, base: str, *, orphan_only: bool = False, _final: bool = True
) -> str:
    """Render a block's inline content as Markdown, preserving link targets.

    Plain `text_content()` throws away every `href`. Measured against trafilatura on
    danluu.com, that lost **201 links on a single page** -- for an engine whose job is rich
    extraction, the URL is often the most useful part of the sentence.

    Only inline constructs are handled here; block structure is the caller's concern -- and
    that is what `orphan_only` is for. A container that holds block children (a `<div>` with
    `<p>`s in it, an `<li>` with a nested `<ul>`) gets its *text* from `_orphan_text`, which
    correctly skips those children because they become blocks of their own. Its *rich text*
    used to be rendered from the whole subtree regardless, so the Markdown carried every
    child paragraph glued together, and then carried each of them again as its own block.
    Measured on a Hacker News post: the body appeared twice, once fused into a single
    paragraph. With `orphan_only`, the rich rendering follows the same rule as the text.
    """
    parts: list[str] = [element.text or ""]

    for child in element:
        tag = child.tag if isinstance(child.tag, str) else ""
        if orphan_only and tag in _CARRIED_ELSEWHERE:
            # It becomes a block of its own; only the text after it belongs here.
            parts.append(child.tail or "")
            continue
        parts.append(_inline_child(child, base, orphan_only=orphan_only))
        parts.append(child.tail or "")

    joined = "".join(parts)
    return normalize_text(joined) if _final else joined


def _inline_child(child: HtmlElement, base: str, *, orphan_only: bool) -> str:
    """One inline child as Markdown, without its tail; un-normalised, edges intact."""
    tag = child.tag if isinstance(child.tag, str) else ""
    parts: list[str] = []
    if tag == "br":
        parts.append(LINE_BREAK)
    elif _breaks_line(child):
        parts.append(" ")
    # The child's text with its edge whitespace intact. Normalising here, per child,
    # is what fused `<span>: </span>Connecting` into `:Connecting` -- the space that
    # separated two words lived at the end of the span, and stripping each child
    # deleted it before the parent ever saw it. Whitespace at a child's edges belongs to
    # the run of text, not to the child; only the whole is normalised, at the end.
    raw = (
        _inline_markdown(child, base, orphan_only=orphan_only, _final=False)
        if len(child)
        else flowed_text(child)
    )
    inner = normalize_text(raw)
    lead = " " if raw[:1].isspace() else ""
    trail = " " if raw[-1:].isspace() else ""

    if tag == "a":
        href = _absolute(child.get("href"), base)
        label = inner or normalize_text(flowed_text(child))
        # A link with no text contributes nothing a reader can use. A `javascript:`
        # target is not a destination either -- it is a toggle, and `[[-]](javascript:
        # void(0))` on every Hacker News comment is noise nobody can follow.
        usable = href and label and not href.lower().startswith("javascript:")
        parts.append(f"{lead}[{label}]({href}){trail}" if usable else f"{lead}{label}{trail}")
    elif tag in _INLINE_EMPHASIS and inner:
        parts.append(f"{lead}**{inner}**{trail}")
    elif tag in _INLINE_ITALIC and inner:
        parts.append(f"{lead}*{inner}*{trail}")
    elif tag == "code" and inner:
        parts.append(f"{lead}`{inner}`{trail}")
    elif tag == "br":
        parts.append(" ")
    else:
        parts.append(raw)
    return "".join(parts)


def flowed_text(element: HtmlElement) -> str:
    """`text_content()`, but honouring the line boxes the browser actually laid out.

    lxml concatenates descendant text with nothing between it, so a navigation of
    `<a>Mac</a><a>iPad</a><a>iPhone</a>` becomes `MaciPadiPhone`. Measured on
    apple.com/airpods-pro, the entire nav arrived as
    `AppleStoreShopShop the LatestMaciPadiPhoneApple Watch...`. That is text corruption rather
    than noise: the words are destroyed, and no downstream consumer can recover them.

    Inserting a separator between every pair of elements is the obvious fix and is wrong in
    the other direction -- inline siblings genuinely do run together, and `<b>bold</b>`
    followed by `<i>italic</i>` really does render as `bolditalic`. What separates the two
    cases is the computed `display`, which only a browser knows, so the browser marks it and
    this function reads the mark. Same principle as reading order: measure the page, do not
    reason about the markup.
    """
    parts: list[str] = [element.text or ""]
    for child in element:
        # BREAK_ATTRIBUTE is stamped by the renderer (`fetch/js/collect.js`) on elements the
        # browser laid out as their own box. Absent on a static fetch, so this branch never
        # fires and the function behaves exactly as `text_content()` did -- a page nobody
        # rendered gets no layout claims. A `<br>` is the one break the markup itself
        # declares, and it is a line break rather than a space: an address, a verse, and the
        # `<br><br>`-separated paragraphs of pre-CSS pages keep their lines (textfiles.com).
        if child.tag == "br":
            parts.append(LINE_BREAK)
        elif _breaks_line(child):
            parts.append(" ")
        parts.append(flowed_text(child))
        parts.append(child.tail or "")
    return "".join(parts)



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
        link=_image_link(element, base),
    )


def _image_link(element: HtmlElement, base: str) -> str | None:
    """The target of the link wrapping an image, when the image is what the link is.

    spacejam.com/1996 is twelve `<a href><img></a>` planets and the Common Lisp
    HyperSpec's navigation is eleven of them; the images were kept and every href was
    dropped, because a link's target only survived through the text it wrapped and these
    wrap none. Only an `<a>` within two levels and holding no text of its own counts: a
    link around a paragraph with a picture in it belongs to the paragraph.
    """
    parent = element.getparent()
    for _ in range(2):
        if parent is None or not isinstance(parent.tag, str):
            return None
        if parent.tag == "a":
            if normalize_text(parent.text_content()):
                return None
            href = _absolute(parent.get("href"), base)
            return None if not href or href.lower().startswith("javascript:") else href
        parent = parent.getparent()
    return None


MEDIA_TAGS: Final[frozenset[str]] = frozenset({"video", "audio", "iframe", "embed", "object"})
"""Embedded media, kept as a placeholder rather than stripped in silence.

These are all in `SKIP_TAGS`, which is right for their *text* -- an `<iframe>`'s content is a
separate document and a `<video>`'s children are `<source>` elements, so nothing readable is
lost by removing them. What was lost is the fact that they existed. A YouTube embed vanished
without trace, and nothing downstream could tell "this page has no video" from "this page has
a video nobody transcribed". Only the second is worth returning to.
"""

_MEDIA_CHILDREN: Final[frozenset[str]] = frozenset({"source", "track"})
"""Children of a media element that carry the information the placeholder needs.

Also in `SKIP_TAGS`, and stripping them before `_media_block` runs is why a `<video>` with a
perfectly good `<track kind="captions">` first reported no subtitles at all. They are kept
through the strip and then consumed as descendants of their parent, so they never become
blocks of their own."""

_MEDIA_LABEL: Final[dict[str, str]] = {
    "video": "video",
    "audio": "audio",
    "iframe": "embedded frame",
    "embed": "embedded object",
    "object": "embedded object",
}

_MIN_EMBED_DIMENSION: Final[int] = 32
"""Iframes smaller than this are tracking and analytics beacons, not media."""


def _media_block(
    element: HtmlElement, base: str, index: int, tree: object
) -> Block | None:
    """Describe an embed that is present on the page but not transcribed.

    The text is written to be read by whatever comes next -- a person skimming the Markdown,
    or a model building notes and entities. It says what the thing is, names it if the markup
    does, and states plainly that its content was not extracted, so an absence is never
    mistaken for a page that simply had no video.

    Subtitle tracks are called out specifically. A `<track kind="captions">` is a transcript
    already sitting in the markup, at a URL anyone can fetch. This engine does not fetch it
    today, and recording where it is costs nothing and makes that a later decision rather
    than a lost one.
    """
    tag = element.tag
    if not isinstance(tag, str):
        return None

    src = _absolute(element.get("src"), base) or _absolute(element.get("data"), base)
    if not src:
        # Descendant axis, not `find("source")`. libxml2 does not know `<source>` is a void
        # element, so it nests whatever follows *inside* it -- a `<video>` with a `<source>`
        # and two `<track>`s parses as source(track, track), and a child-axis query finds
        # exactly one of the three.
        sources = element.xpath(".//source[@src]")
        if sources:
            src = _absolute(sources[0].get("src"), base)

    # A 1x1 iframe is a beacon. Judge only when the markup declares a size; an undeclared
    # one is sized by CSS and could be anything.
    for dimension in ("width", "height"):
        raw = (element.get(dimension) or "").strip()
        if raw.isdigit() and int(raw) < _MIN_EMBED_DIMENSION:
            return None

    label = _MEDIA_LABEL.get(tag, "embedded media")
    title = (
        normalize_text(element.get("title"))
        or normalize_text(element.get("aria-label"))
        or normalize_text(element.get("alt"))
    )

    tracks = [
        _absolute(track.get("src"), base) for track in element.xpath(".//track[@src]")
    ]
    captions = [t for t in tracks if t]

    described = f'{label} "{title}"' if title else label
    where = f" at {src}" if src else ""
    sentence = f"[{described}{where}. Media not transcribed.]"
    if captions:
        sentence = (
            f"[{described}{where}. Media not transcribed; "
            f"{len(captions)} subtitle track(s) available: {', '.join(captions[:3])}]"
        )

    return Block(
        text=sentence,
        tag=tag,
        xpath=tree.getpath(element),  # type: ignore[attr-defined]
        dom_index=index,
        kind=BlockKind.MEDIA,
        href=src,
        alt=title or None,
    )


_PAGE_LEVEL_TAGS: Final[frozenset[str]] = frozenset(
    {"table", "form", "section", "article", "h1", "h2", "h3"}
)
"""Tags that appear in a cell only when the cell is holding a *page*.

`div` and `p` were in this set and had to come out. They are the single most common way a
CMS wraps a value -- `<td><p>12.4</p></td>` is what every WYSIWYG editor emits -- so counting
them as layout evidence threw away real data tables. Measured on WebMainBench: a 17-row,
111-cell table of numbers was classified as layout and flattened to paragraphs because each
cell wrapped its number in a `<p>`. Zero tables were extracted from that page."""

def _is_page_like(cell: HtmlElement) -> bool:
    """Whether this cell is holding a page rather than a value."""
    if any(node.tag in _PAGE_LEVEL_TAGS for node in cell.iter() if node is not cell):
        return True
    if len(cell.xpath(".//p")) >= 2:
        return True
    return len(normalize_text(cell.text_content())) >= LONG_CELL_CHARS


def is_layout_table(element: HtmlElement) -> bool:
    """Whether a `<table>` is being used to lay out a page rather than to hold data.

    Legacy sites still build whole pages out of nested tables. Treating those as data
    collapses the entire page into one block: Hacker News extracted as **one** block of 3,720
    characters with no headings, no links and no reading order -- the worst possible output,
    produced silently.

    Two signals, both structural:

    - a cell holding a *page*: another `<table>`, a `<form>`, a heading, or simply more than
      `LONG_CELL_CHARS` of prose. A pricing table holds numbers; a layout table holds an
      article. Note what is **not** a signal: a `<p>` or a `<div>` wrapping a value, which is
      how most content management systems emit an ordinary data cell.
    - a shape that cannot hold data: one row, one column, blank rows used as spacing, or a
      grid whose cells are mostly empty. A table exists to cross-reference a row against a
      column, and there is nothing to cross-reference in a single line of cells -- nor in a
      record separated from the next by an empty `<tr>`, which is how gaps were made before
      CSS and is never how data is written.
    - the absence of every marker a data table normally carries -- `<th>`, `<thead>`,
      `<caption>` -- combined with enough rows that its author would have used one.

    Deliberately conservative in the ambiguous direction: a table with headers is treated as
    data even if its cells are busy, because flattening a real data table loses the mapping
    from a value to its column, which is the whole reason to keep tables at all.
    """
    # This table's OWN header cells, never a nested table's. `.//th` descends, so a layout
    # table whose cell happens to contain a real data table matched here and short-circuited
    # to "this is data" -- leaving the `.//table` check below unreachable for exactly the
    # nesting it was written to catch.
    if element.xpath("./caption|./thead") or element.xpath(_OWN_HEADER_CELLS_XPATH):
        return False

    if element.xpath(".//table"):
        return True

    cells = element.xpath(".//td")
    if not cells:
        return False

    if _is_degenerate(element):
        return True

    return sum(1 for cell in cells if _is_page_like(cell)) * 2 >= len(cells)


def _is_degenerate(element: HtmlElement) -> bool:
    """Whether this table's *shape* rules out its being a table of data."""
    rows = [row for section in _OWN_ROW_SECTIONS for row in element.xpath(section)]
    if len(rows) < MIN_GRID:
        return True
    widths = [len(row.xpath("./td|./th")) for row in rows]
    if max(widths, default=0) < MIN_GRID:
        return True
    blank = sum(1 for row in rows if not normalize_text(row.text_content()))
    if blank > len(rows) * MAX_EMPTY_ROW_SHARE:
        return True

    total = sum(widths)
    filled = sum(
        1
        for row in rows
        for cell in row.xpath("./td|./th")
        if normalize_text(cell.text_content())
    )
    return bool(total) and filled < total * MIN_FILLED_SHARE


_OWN_ROW_SECTIONS: Final[tuple[str, ...]] = ("./thead/tr", "./tr", "./tbody/tr", "./tfoot/tr")
"""Row containers of *this* table, in rendering order, queried one at a time.

Not a single `./thead/tr|./tr|./tbody/tr|./tfoot/tr` union. lxml returns a union in
**document** order, and `<tfoot>` is legal -- and common -- before `<tbody>`, so the union
puts the footer rows in the middle of the table. Concatenating the four results in order
is what a browser does.

Child axes throughout, so a nested table's rows are never lifted into this one. The previous
`.//tr` descended, which is half of why a nested table came out duplicated.
"""

_OWN_ROWS_XPATH: Final[str] = "|".join(_OWN_ROW_SECTIONS)

_OWN_HEADER_CELLS_XPATH: Final[str] = "|".join(f"{section}/th" for section in _OWN_ROW_SECTIONS)
"""This table's own `<th>` cells.

Built per-alternative on purpose. `_OWN_ROWS_XPATH + "/th"` looks equivalent and is not:
`|` has lower precedence than `/`, so the suffix binds only to the final alternative and the
expression degenerates to "any direct row, or a tfoot header cell" -- which matched every
ordinary table and broke layout-table detection outright.
"""

_MAX_SPAN: Final[int] = 1000
"""Ceiling on a single `colspan`/`rowspan`. Untrusted input: `colspan="99999999"` is a
memory-exhaustion primitive otherwise."""


def _span(cell: HtmlElement, attribute: str) -> int:
    raw = (cell.get(attribute) or "").strip()
    if not raw.isdigit():
        return 1
    return max(1, min(int(raw), _MAX_SPAN))


def _cell_text(cell: HtmlElement) -> str:
    """A cell's own text, excluding any table nested inside it.

    `text_content()` swallows the nested table, producing `Inner HInner V` -- both duplicated
    into the outer table and run together without a separator. The nested table is emitted as
    its own block instead, so its content is not lost by being left out here.
    """
    parts: list[str] = [cell.text or ""]
    for child in cell:
        if isinstance(child.tag, str) and child.tag == "table":
            parts.append(child.tail or "")
            continue
        # The same line-box rule as `flowed_text`, which the loop here bypasses for the
        # cell itself: `<td>a<br>b</td>` and `<td><span>x</span><div>y</div></td>` were
        # `ab` and `xy`. A cell is one row of a grid, so the break is a space here rather
        # than a newline; the rows of a *layout* table never reach this function.
        if child.tag == "br" or _breaks_line(child):
            parts.append(" ")
        parts.append(flowed_text(child))
        parts.append(child.tail or "")
    return normalize_text("".join(parts).replace(LINE_BREAK, " "))


def _cell_rich(cell: HtmlElement, base: str) -> str:
    """A cell's inline Markdown: `_cell_text` with its links and emphasis kept.

    craigslist.org/about/best/all is a table of `<td><a href>title</a></td>`; the links
    are the whole point of the page and every one was dropped, because a pipe table was
    rendered from the plain cell text. A pipe in a link is escaped by the renderer.
    """
    parts: list[str] = [cell.text or ""]
    for child in cell:
        if isinstance(child.tag, str) and child.tag == "table":
            parts.append(child.tail or "")
            continue
        parts.append(_inline_child(child, base, orphan_only=False))
        parts.append(child.tail or "")
    return normalize_text("".join(parts).replace(LINE_BREAK, " "))


def _expanded_rows(
    element: HtmlElement, render: Callable[[HtmlElement], str] = _cell_text
) -> list[list[str]]:
    """The table as a rectangular grid, with `rowspan` and `colspan` resolved.

    Ignoring spans does not merely lose formatting, it **misaligns every value**. A header
    of `<th rowspan=2>Region</th><th colspan=2>2025</th>` over `<th>Q1</th><th>Q2</th>`
    produced rows `('Region','2025')`, `('Q1','Q2')`, `('EU','10','20')` -- so the renderer
    took `Region | 2025` as the header, demoted the real column labels to a body row, and put
    every number under the wrong heading. A spec or pricing table is the main reason to keep
    tables at all, and that output is confidently wrong rather than incomplete.

    The algorithm is the one pandas uses in `io/html.py`: carry each spanning cell forward
    with its column index and remaining row count, emitting it before the next cell that
    would occupy that column. Adopted rather than depended on -- pandas is 15 MB and coerces
    `'10'` to an int, and this engine needs the string for hashing and the search index.
    """
    source_rows: list[HtmlElement] = []
    for section in _OWN_ROW_SECTIONS:
        source_rows.extend(element.xpath(section))

    grid: list[list[str]] = []
    carried: list[tuple[int, str, int]] = []

    for row in source_rows:
        line: list[str] = []
        next_carried: list[tuple[int, str, int]] = []
        column = 0

        for cell in row.xpath("./th|./td"):
            # Anything held over from an earlier row occupies its column first.
            while carried and carried[0][0] <= column:
                held_column, held_text, held_rows = carried.pop(0)
                line.append(held_text)
                if held_rows > 1:
                    next_carried.append((held_column, held_text, held_rows - 1))
                column += 1

            text = render(cell)
            rows_spanned = _span(cell, "rowspan")
            for _ in range(_span(cell, "colspan")):
                line.append(text)
                if rows_spanned > 1:
                    next_carried.append((column, text, rows_spanned - 1))
                column += 1

        for held_column, held_text, held_rows in carried:
            line.append(held_text)
            if held_rows > 1:
                next_carried.append((held_column, held_text, held_rows - 1))

        grid.append(line)
        carried = sorted(next_carried)

    # A rowspan may reach past the last written row; those cells are still content.
    while carried:
        line = []
        next_carried = []
        for held_column, held_text, held_rows in carried:
            line.append(held_text)
            if held_rows > 1:
                next_carried.append((held_column, held_text, held_rows - 1))
        grid.append(line)
        carried = sorted(next_carried)

    return grid


def _header_depth(element: HtmlElement) -> int:
    """How many leading rows are header rows.

    `<thead>` when the table declares one, otherwise the run of leading rows made entirely of
    `<th>`. Needed because span expansion turns a two-level header into two grid rows, and
    `render_markdown` treats row 0 as the header -- so without collapsing them the real
    column labels would still render as a body row.
    """
    head = element.xpath("./thead/tr")
    if head:
        return len(head)

    depth = 0
    for section in _OWN_ROW_SECTIONS[1:]:
        for row in element.xpath(section):
            cells = row.xpath("./th|./td")
            if not cells or any(c.tag != "th" for c in cells):
                return depth
            depth += 1
    return depth


def _collapse_header(grid: list[list[str]], depth: int) -> list[tuple[str, ...]]:
    """Join a multi-row header into one label per column.

    `Region / Region` and `2025 / Q1` become `Region` and `2025 Q1`. Repeats are dropped
    rather than doubled, which is what a `rowspan` header produces once expanded.
    """
    if depth < 2 or depth > len(grid):
        return [tuple(row) for row in grid]

    width = max(len(row) for row in grid[:depth])
    joined: list[str] = []
    for column in range(width):
        seen: list[str] = []
        for row in grid[:depth]:
            value = row[column] if column < len(row) else ""
            if value and value not in seen:
                seen.append(value)
        joined.append(" ".join(seen))
    return [tuple(joined), *(tuple(row) for row in grid[depth:])]


_TABLE_TAGS: Final[frozenset[str]] = frozenset(
    {"table", "tr", "td", "th", "thead", "tbody", "tfoot", "caption", "sub", "sup", "a"}
)
"""Tags kept when preserving a table's own markup.

`sub` and `sup` because a chemical formula or a footnote marker in a cell is content, not
presentation. `a` because a link in a cell is often the *point* of the cell: verified on
Hacker News, whose front page is a table of 30 rows in which the destination of each row is
the single most important fact, and which came back with all 30 stories and **zero links**
before this. A cell's link target is not something any other field can carry."""

_TABLE_ATTRS: Final[frozenset[str]] = frozenset({"colspan", "rowspan", "href"})
"""Attributes kept: the two that carry a merge, and the one that carries a destination.

Everything else -- styles, widths, tracking ids, translation-tool bookkeeping -- is noise
that would otherwise be emitted verbatim into the output."""

_MAX_PRESERVED_TABLE_BYTES: Final[int] = 200_000
"""Refuse to inline a table larger than this. Untrusted input, and a runaway table would
otherwise dominate a page's output."""


def is_complex_table(element: HtmlElement) -> bool:
    """Whether Markdown's pipe syntax can express this table at all.

    It cannot, when a cell spans more than one row or column, or when a table nests inside
    another. Pipes have no way to say "this cell covers three columns", so rendering such a
    table as pipes drops the merge and shifts every value under it into the wrong column --
    which is not a formatting loss but a data-corruption one.
    """
    if element.xpath(".//table"):
        return True
    for cell in element.xpath(".//td|.//th"):
        for name in ("colspan", "rowspan"):
            raw = (cell.get(name) or "").strip()
            # `colspan="50%"` appears on real pages; anything unparseable is not a span.
            if raw.isdigit() and int(raw) > 1:
                return True
    return False


def preserved_table_html(element: HtmlElement, base_url: str = "") -> str | None:
    """The table's own markup with everything but structure removed, or None if too large.

    Link targets are made absolute here. A preserved table travels without the page it came
    from, so a bare `item?id=123` in it points nowhere.
    """
    copied = copy.deepcopy(element)
    for node in copied.iter():
        if not isinstance(node.tag, str):
            continue
        if node.tag not in _TABLE_TAGS and node is not copied:
            node.tag = "span"  # unwrapped below by `strip_tags`, keeping the text
        href = node.get("href") if node.tag == "a" else None
        for name in list(node.attrib):
            if name not in _TABLE_ATTRS:
                del node.attrib[name]
        if href is not None:
            if base_url:
                node.set("href", urljoin(base_url, href))
        elif node.tag == "a":
            # An anchor with no destination is a span wearing a link's clothes.
            node.tag = "span"
    etree.strip_tags(copied, "span")
    markup = etree.tostring(copied, encoding="unicode", method="html").strip()
    markup = _COLLAPSE_SPACE.sub(" ", markup)
    return None if len(markup) > _MAX_PRESERVED_TABLE_BYTES else markup


_COLLAPSE_SPACE: Final[re.Pattern[str]] = re.compile(r"\s+")


def _table_block(
    element: HtmlElement, index: int, tree: object, base_url: str = ""
) -> Block | None:
    """Build a table block preserving its rows.

    A table flattened into text loses the association between a value and its column, which
    is exactly the information a pricing or spec table exists to convey.
    """
    grid = [row for row in _expanded_rows(element) if any(cell for cell in row)]
    rows = _collapse_header(grid, _header_depth(element)) if grid else []

    if not rows:
        return None

    # The same grid with each cell's links and emphasis, for the Markdown; kept only
    # when it differs, so a plain grid carries nothing twice.
    rich_grid = [row for row in _expanded_rows(element, lambda c: _cell_rich(c, base_url)) if any(cell for cell in row)]
    rich_rows = _collapse_header(rich_grid, _header_depth(element)) if rich_grid else []
    if len(rich_rows) != len(rows) or rich_rows == rows:
        rich_rows = []

    caption = element.xpath("./caption")
    summary = normalize_text(flowed_text(caption[0])) if caption else ""
    preserved = preserved_table_html(element, base_url) if is_complex_table(element) else None

    # Every row, not a preview, and the caption in addition to them rather than instead.
    #
    # `text` is not a display field: it is what the content hash, deduplication, the search
    # index and reading order all key on. An earlier version put the first three rows here,
    # and a caption alone when there was one, so a specification table contributed almost
    # nothing to any of them while rendering perfectly in the Markdown. The Markdown was
    # right and the text was quietly missing most of the page.
    flattened = "\n".join(" | ".join(row) for row in rows)
    text = f"{summary}\n{flattened}" if summary else flattened

    return Block(
        text=text,
        tag="table",
        xpath=tree.getpath(element),  # type: ignore[attr-defined]
        dom_index=index,
        kind=BlockKind.TABLE,
        rows=tuple(rows),
        rich_rows=tuple(rich_rows),
        table_html=preserved,
    )


def _code_language(element: HtmlElement) -> str | None:
    """The language a code block declares, in any of the spellings sites use.

    `language-js` (highlight.js, Prism, CommonMark renderers), `lang-js`, `highlight-js`,
    MDN's `brush: js` (two class tokens, SyntaxHighlighter's legacy form), and the
    `data-language` / `data-lang` attributes Docusaurus and Shiki emit.
    """
    for node in (element, *element.xpath(".//code")):
        for attribute in ("data-language", "data-lang"):
            declared = (node.get(attribute) or "").strip().lower()
            if declared:
                return declared
        classes = [str(token) for token in (node.get("class") or "").split()]
        for index, value in enumerate(classes):
            for prefix in ("language-", "lang-", "highlight-"):
                if value.startswith(prefix) and len(value) > len(prefix):
                    return value[len(prefix):]
            if value == "brush:" and index + 1 < len(classes):
                return str(classes[index + 1]).rstrip(";")
    return None


def _has_class(element: HtmlElement, name: str) -> bool:
    return name in (element.get("class") or "").split()


def _first_with_class(element: HtmlElement, name: str) -> HtmlElement | None:
    for node in element.iterdescendants():
        if isinstance(node.tag, str) and _has_class(node, name):
            return node
    return None


_EDITOR_CLASSES: Final[frozenset[str]] = frozenset({"cm-editor", "CodeMirror", "monaco-editor", "ace_editor"})
_EDITOR_LANGUAGE_ATTRIBUTES: Final[tuple[str, ...]] = ("data-language", "data-lang", "data-mode-id", "language")
_EDITOR_ANCESTOR_DEPTH: Final[int] = 4
_STYLE_TOP: Final[re.Pattern[str]] = re.compile(r"(?:^|;)\s*top\s*:\s*(-?[\d.]+)px")


def _is_editor(element: HtmlElement) -> bool:
    """Whether this element is the root of a browser-side code editor's DOM."""
    return not _EDITOR_CLASSES.isdisjoint((element.get("class") or "").split())


def _editor_lines(element: HtmlElement) -> tuple[list[HtmlElement], str | None] | None:
    """The line elements of a code editor's DOM, in line order, and the language it
    declares -- or None when this element is not an editor (see `_is_editor`).

    A browser-side code editor draws its document as one element per line beside a gutter
    of line numbers, and everything else in it is machinery: measuring layers, a cursor, a
    hidden textarea, an `aria-live` announcer. Only the line elements are read:

    - CodeMirror 6: `.cm-editor` … `.cm-content > .cm-line`; the language is
      `data-language` on the content element (the language package sets it).
    - CodeMirror 5: `.CodeMirror` … `.CodeMirror-code` … `.CodeMirror-line` (a `<pre>` each);
      `.CodeMirror-measure` holds a sample line for measuring and is not the document.
    - Monaco: `.monaco-editor[data-mode-id]` … `.view-lines > .view-line`, virtualised and
      emitted in render order, so the lines are put back in order by their `top`.
    - Ace: `.ace_editor` … `.ace_text-layer > .ace_line`.
    """
    if _has_class(element, "cm-editor"):
        content = _first_with_class(element, "cm-content")
        if content is None:
            return [], None
        lines = [n for n in content.iterdescendants() if isinstance(n.tag, str) and _has_class(n, "cm-line")]
        return lines, (content.get("data-language") or "").strip().lower() or None
    if _has_class(element, "CodeMirror"):
        code = _first_with_class(element, "CodeMirror-code")
        if code is None:
            return [], None
        return [n for n in code.iterdescendants() if isinstance(n.tag, str) and _has_class(n, "CodeMirror-line")], None
    if _has_class(element, "monaco-editor"):
        view = _first_with_class(element, "view-lines")
        if view is None:
            return [], None
        lines = [n for n in view if isinstance(n.tag, str) and _has_class(n, "view-line")]

        def top(line: HtmlElement) -> float:
            match = _STYLE_TOP.search(line.get("style") or "")
            return float(match.group(1)) if match else 0.0

        return sorted(lines, key=top), (element.get("data-mode-id") or "").strip().lower() or None
    if _has_class(element, "ace_editor"):
        layer = _first_with_class(element, "ace_text-layer")
        if layer is None:
            return [], None
        return [n for n in layer.iterdescendants() if isinstance(n.tag, str) and _has_class(n, "ace_line")], None
    return None


def _editor_block(element: HtmlElement, index: int, tree: object) -> Block | None:
    """One code block for a code editor's DOM: its lines in order, gutters left out.

    MDN's `<interactive-example>` mounts a CodeMirror 6 editor for each tab of the demo,
    and developer.mozilla.org/…/Element/table came out as one paragraph per gutter number
    and one per line -- `1`, `<table>`, `2`, `<caption>`, … -- with the CSS tab's lines
    scattered among them. The editor's text is code, whitespace and all, and is emitted
    the way a `<pre>` is: verbatim lines joined by newlines, `kind=code`, with the language
    the widget declares (`data-language` on the content, Monaco's `data-mode-id`, a
    `language=` attribute on the host element, or a `language-*` class nearby).
    """
    found = _editor_lines(element)
    if found is None:
        return None
    lines, language = found
    text = "\n".join(line.text_content().replace("\xa0", " ").rstrip() for line in lines).strip("\n")
    if not text.strip():
        return None
    if language is None:
        for depth, node in enumerate((element, *element.iterancestors())):
            if depth > _EDITOR_ANCESTOR_DEPTH:
                break
            for attribute in _EDITOR_LANGUAGE_ATTRIBUTES:
                declared = (node.get(attribute) or "").strip().lower()
                if declared:
                    language = declared
                    break
            if language is not None:
                break
    if language is None:
        language = _code_language(element)
    return Block(
        text=text,
        tag=element.tag,
        xpath=tree.getpath(element),  # type: ignore[attr-defined]
        dom_index=index,
        kind=BlockKind.CODE,
        language=language,
    )


_MIN_EDITOR_WINDOW_CHARS: Final[int] = 20


def _code_key(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip("\n").splitlines())


def _complete_editor_windows(blocks: list[Block], editors: set[str], hidden_code: set[str]) -> list[Block]:
    """Give an editor block the whole document it shows a window onto, once.

    CodeMirror 6 and Monaco draw only the lines in view: MDN's `<table>` demo editor holds
    30 of its 40 lines, and a reader scrolls to the rest. The page carries the whole source
    beside it, in the `<pre class="interactive-example">` the widget was built from, which
    the browser hides. When a *hidden* code block in the document (`hidden_code`) begins
    with everything the editor shows, that block is the editor's document: the editor block
    takes its text and the twin is dropped, so the source appears once, whole, where the
    editor is. A visible code block saying the same is on the page in its own right -- a
    listing under a playground -- and stays (a page's deliberate repeats stay; see the
    repeated-block rule in `pipeline`). An editor showing something no hidden block holds
    is left as it is.
    """
    if not editors or not hidden_code:
        return blocks
    keys = {id(b): _code_key(b.text) for b in blocks if b.kind is BlockKind.CODE}
    adopted: dict[int, Block] = {}
    dropped: set[int] = set()
    for block in blocks:
        if block.xpath not in editors or block.kind is not BlockKind.CODE:
            continue
        shown = keys[id(block)]
        if len(shown) < _MIN_EDITOR_WINDOW_CHARS:
            continue
        for other in blocks:
            if (
                other is block
                or other.kind is not BlockKind.CODE
                or other.xpath not in hidden_code
                or id(other) in dropped
                or not keys[id(other)].startswith(shown)
            ):
                continue
            adopted[id(block)] = block.model_copy(
                update={"text": other.text, "language": block.language or other.language}
            )
            dropped.add(id(other))
            break
    if not dropped:
        return blocks
    return [adopted.get(id(b), b) for b in blocks if id(b) not in dropped]


_NESTED_CONTAINERS: Final[frozenset[str]] = frozenset({"ul", "ol", "table", "dl"})


def _own_text(element: HtmlElement) -> str:
    """Text belonging to this element that no other block will carry. Alias of
    `_orphan_text`, kept because list items and definition terms read better under this name:
    a `<li>` whose label sits beside a nested list keeps the label and nothing else."""
    return _orphan_text(element)


_CARRIED_ELSEWHERE: Final[frozenset[str]] = (
    _TEXT_CONTAINERS | _HEADINGS | _ATOMIC | _NESTED_CONTAINERS
)
"""Tags whose text some *other* block will emit: block containers, headings, atomic
elements, and the list and table containers whose items are blocks of their own."""


def _orphan_text(element: HtmlElement) -> str:
    """Text belonging to this element that no other block will carry.

    The innermost-block rule skips any container holding a block descendant, on the sound
    reasoning that a wrapper `<div>` must not swallow the column beneath it. What it missed
    is that such a container can *also* hold text of its own -- and that text was then
    emitted by nobody.

    The markup that does this is ordinary, not exotic:

        <div>Opening sentence.<br><br>
          <div><img><span>Caption</span></div>
        <br><br>Closing sentence.</div>

    Both sentences are the article. Measured on Zyte's article-extraction benchmark, **8 of
    181 pages lose more than 10% of their body this way and 4 lose essentially all of it** --
    MacRumors, AppleInsider, IGN and jaraguadosul, all `<br>`-separated 2019 article markup.

    **The walk is recursive, and the first version was not.** It looked at direct children
    only: a child that was itself a block contributed its tail, and any other child
    contributed its *whole subtree text*. So one non-block wrapper between the container and
    its paragraphs -- a `<span>`, a `<ul>`, a custom element like `<bsx-section>` -- handed
    the entire article back as one block, alongside the paragraph blocks already emitted
    from inside it. Measured on WCXB dev: on tires.bridgestone.com a 1,372-word `<section>`
    block sat beside its own 24 paragraphs; on proserveit.com a 2,728-word `<div>` beside
    its 85; on ama.org four `<ul>`s were re-emitted whole beside their 33 items. Word counts
    doubled, precision halved to 0.48-0.49 with recall at 1.00, and the exact-text
    deduplicator could not see it because a container's text is never *equal* to any one
    child's. Now every descendant is visited, block-bearing subtrees are skipped wherever
    they sit, and only text nothing else carries is kept.
    """
    parts: list[str] = [element.text or ""]
    _orphan_parts(element, parts)
    return normalize_text("".join(parts))


@dataclass(slots=True)
class _OrphanRun:
    """One stretch of a container's own text, with where it sits among the child blocks.

    `before` is the block-bearing child the run precedes -- the block is emitted just ahead
    of it -- or None for text after the last one, emitted when the container closes.
    `anchor` is the first element in the run: its measured rectangle stands for the run,
    since a text node has none of its own. A run with no element at all stays unmeasured
    and takes its place from document order, which the emit point now gets right.
    """

    text: str
    rich: str
    before: HtmlElement | None
    anchor: HtmlElement | None
    ordinal: int


def _paragraphs(text: str, rich: str) -> list[tuple[str, str]]:
    """Split a block's text at the blank lines `<br><br>` left in it, keeping the rich
    form in step when it splits the same way (it carries the same breaks) and falling back
    to the plain text for the pieces when it does not."""
    if "\n\n" not in text:
        return [(text, rich)]
    texts = text.split("\n\n")
    riches = rich.split("\n\n")
    if len(riches) != len(texts):
        return [(piece, piece) for piece in texts]
    return list(zip(texts, riches, strict=True))


def _orphan_runs(element: HtmlElement, base: str) -> list[_OrphanRun]:
    """`_orphan_text`, split at each child block and kept in its place.

    The one-block version carried all of a container's own text as a single block that sat
    at the container's top and wore the container's rectangle. On a Discourse post the
    caption of the ninth image -- an `<em>` the author wrote between two paragraphs -- was
    read as the first line of the post, ahead of the opening sentence, because the cooked
    `<div>` it was orphaned in spans the whole post. Same on any `<br>`-separated article
    whose last sentence follows an embedded figure. Here each stretch between block
    children is its own block, emitted where the reader meets it and measured by its first
    element.

    Splitting happens at every block the walk meets, however deep it sits under inline
    wrappers. AppleInsider's 2019 reviews put the whole `<br><br>`-separated article inside
    one `<span>` with the `<h2>`s between the paragraphs; splitting at the container's
    direct children only made the article one run placed after its last heading, so every
    section heading came out ahead of every paragraph. A wrapper that holds a block is
    walked into and its text joins the runs on either side of that block.
    """
    runs: list[_OrphanRun] = []
    text_parts: list[str] = [element.text or ""]
    rich_parts: list[str] = [element.text or ""]
    anchor: HtmlElement | None = None

    def close(before: HtmlElement | None) -> None:
        text = normalize_text("".join(text_parts))
        if text:
            rich = normalize_text("".join(rich_parts))
            # A `<br><br>` inside the run is a paragraph break -- the paragraphs of a
            # pre-CSS page, of a forum post, of an email pasted into a `<div>` -- and each
            # becomes a block of its own, as it would have with `<p>` tags.
            for n, (piece, piece_rich) in enumerate(_paragraphs(text, rich)):
                runs.append(_OrphanRun(piece, piece_rich, before, anchor if n == 0 else None, len(runs)))

    def walk(parent: HtmlElement) -> None:
        nonlocal text_parts, rich_parts, anchor
        for child in parent:
            tag = child.tag
            if not isinstance(tag, str):
                text_parts.append(child.tail or "")
                rich_parts.append(child.tail or "")
                continue
            if tag in _CARRIED_ELSEWHERE:
                close(child)
                text_parts = [child.tail or ""]
                rich_parts = [child.tail or ""]
                anchor = None
                continue
            if _holds_a_block(child):
                # An inline wrapper around blocks: its text belongs to the runs around
                # them, so the walk goes through it rather than around it.
                if tag == "br":
                    text_parts.append(LINE_BREAK)
                    rich_parts.append(LINE_BREAK)
                elif _breaks_line(child):
                    text_parts.append(" ")
                    rich_parts.append(" ")
                text_parts.append(child.text or "")
                rich_parts.append(child.text or "")
                walk(child)
                text_parts.append(child.tail or "")
                rich_parts.append(child.tail or "")
                continue
            if anchor is None and tag != "br":
                # A `<br>` has no box to measure; the first element that does stands for
                # the run.
                anchor = child
            if tag == "br":
                text_parts.append(LINE_BREAK)
            elif _breaks_line(child):
                text_parts.append(" ")
            text_parts.append(child.text or "")
            _orphan_parts(child, text_parts)
            text_parts.append(child.tail or "")
            rich_parts.append(_inline_child(child, base, orphan_only=True))
            rich_parts.append(child.tail or "")

    walk(element)
    close(None)
    return runs


def _holds_a_block(element: HtmlElement) -> bool:
    """Whether some descendant is a block another emitter carries."""
    return any(
        isinstance(d.tag, str) and d.tag in _CARRIED_ELSEWHERE for d in element.iterdescendants()
    )


def _innermost_first(
    held: list[tuple[HtmlElement, _OrphanRun]],
) -> list[tuple[HtmlElement, _OrphanRun]]:
    """Trailing runs keyed on one last descendant, inner container's first: an inner
    container registered after the outer one it sits in, and its trailing text comes
    before the outer container's. Each container's own runs keep their order -- the
    paragraphs a `<br><br>` split one run into are not a nesting."""
    order = list(dict.fromkeys(container for container, _ in held))[::-1]
    return [pair for container in order for pair in held if pair[0] is container]


def _orphan_parts(element: HtmlElement, parts: list[str]) -> None:
    for child in element:
        tag = child.tag
        if not isinstance(tag, str):
            parts.append(child.tail or "")
            continue
        if tag in _CARRIED_ELSEWHERE:
            # It gets its own block(s); only the text after it is orphaned.
            parts.append(child.tail or "")
            continue
        # Same line-box rule as `flowed_text`: a `<br>` is a line break, and a separator
        # goes where the browser drew one or where the tag says the browser would have.
        if tag == "br":
            parts.append(LINE_BREAK)
        elif _breaks_line(child):
            parts.append(" ")
        parts.append(child.text or "")
        _orphan_parts(child, parts)
        parts.append(child.tail or "")


def _item_of(element: HtmlElement) -> tuple[HtmlElement | None, bool]:
    """The `<li>` this block is the body of, and whether it is the item's first block.

    `<li><p>Try to find an answer by searching the Web.</p></li>` (catb.org, tldp.org,
    every DocBook and Sphinx page) put the paragraph out as a paragraph and the item as
    nothing, so the list lost its bullets, its numbering and its item boundaries. Only a
    paragraph or div directly inside an item counts; an item that says something itself
    keeps that as its label, as before, and its paragraphs are continuations.
    """
    parent = element.getparent()
    if parent is None or parent.tag != "li" or element.tag not in {"p", "div"}:
        return None, False
    if (parent.text or "").strip():
        return parent, False  # the item's own text is its label; this is a continuation
    for sibling in parent:
        if not isinstance(sibling.tag, str):
            continue
        if sibling is element:
            return parent, True
        if sibling.tag in _TEXT_CONTAINERS or sibling.tag in _HEADINGS or sibling.tag in _ATOMIC:
            return parent, False
        if (sibling.tail or "").strip() or normalize_text(flowed_text(sibling)):
            return None, False
    return None, False


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


_QUOTE_STRUCTURE: Final[frozenset[str]] = frozenset(
    {"table", "ul", "ol", "dl", "pre", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
)


def _quote_has_structure(quote: HtmlElement) -> bool:
    """Whether a `<blockquote>` holds blocks rather than a run of text: any structural
    element, or two or more paragraphs / divs with text of their own."""
    paragraphs = 0
    for node in quote.iterdescendants():
        if not isinstance(node.tag, str):
            continue
        if node.tag in _QUOTE_STRUCTURE:
            return True
        if node.tag in ("p", "div") and normalize_text(node.text_content()):
            paragraphs += 1
            if paragraphs >= 2:
                return True
    return False


def _drop_closed_dialogs(root: HtmlElement) -> None:
    """Remove a dialog that is closed: a `<dialog>` without `open`, or an element with
    `role="dialog"` / `role="alertdialog"` that is hidden -- by the renderer's measure, by
    `aria-hidden="true"`, or by the `hidden` attribute.

    A closed modal is not on the page and is not "collapsed content" a reader can open in
    the sense an accordion is: it is a different screen. karnataka.gov.in carries nine
    Bootstrap modals -- Privacy Policy, Terms and Conditions, Help, Screen Reader Access,
    Site Map -- 2,100 words in `.modal.fade` divs with `display: none`, three times the
    words the page shows, and every one of them reached the content. An open dialog (a
    cookie prompt the renderer found showing, a `<dialog open>`) stays and is judged like
    anything else.
    """
    doomed: list[HtmlElement] = []
    for element in root.iter("dialog", "div", "section", "aside", "form"):
        tag = element.tag if isinstance(element.tag, str) else ""
        role = (element.get("role") or "").strip().lower()
        if tag == "dialog":
            closed = element.get("open") is None
        elif role in ("dialog", "alertdialog"):
            closed = (
                element.get(HIDDEN_ATTRIBUTE) in _ABSENT_KINDS
                or (element.get("aria-hidden") or "").strip().lower() == "true"
                or element.get("hidden") is not None
            )
        else:
            continue
        if closed:
            doomed.append(element)
    for element in doomed:
        parent = element.getparent()
        if parent is None or any(a in doomed for a in element.iterancestors()):
            continue
        _carry_tail(parent, element)
        parent.remove(element)


_UNSHOWN_KINDS: Final[frozenset[str]] = frozenset({"display", "visibility"})
_OPENER_ATTRIBUTES: Final[tuple[str, ...]] = (
    "aria-controls", "aria-owns", "data-target", "data-bs-target", "data-toggle-target",
    "data-tab", "data-panel", "for",
)
_REACHABLE_ROLES: Final[frozenset[str]] = frozenset({"tabpanel", "region", "menu", "listbox", "tree"})
_REGION_TAGS: Final[frozenset[str]] = frozenset({"html", "body", "main", "article"})
_REGION_ROLES: Final[frozenset[str]] = frozenset({"main", "document"})


def _drop_unreachable_hidden(root: HtmlElement) -> None:
    """Remove hidden content that nothing on the page opens.

    A collapsed accordion tray, an inactive tab, a "Show more" body: hidden by the
    renderer's measure, and content, because a control on the page opens it -- the control
    names it by id (`aria-controls`, `data-bs-target`, `href="#id"`), or the panel says
    what it is (`role="tabpanel"`), or it sits in a `<details>`. Those stay, unmeasured,
    where the source puts them.

    Hidden content that no control reaches is a different thing: the source a news
    ticker reads from, a widget for another breakpoint, a template. karnataka.gov.in
    hides a 3,144-word "Recent Govt Announcements" div beside a 726-word page and nothing
    opens it; every word reached the content. Only the renderer's own marks count -- a
    static fetch marks nothing and nothing happens -- and only `display`/`visibility`
    hiding: opacity is an animation's starting state, and a tray clipped by a collapsed
    `overflow: hidden` ancestor is in the flow of the page and is left alone.
    """
    referenced: set[str] = set()
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        for attribute in _OPENER_ATTRIBUTES:
            value = element.get(attribute)
            if value:
                referenced.update(v.lstrip("#") for v in value.split())
        href = element.get("href") or ""
        if href.startswith("#") and len(href) > 1:
            referenced.add(href[1:])

    def reachable(container: HtmlElement) -> bool:
        for node in container.iter():
            if not isinstance(node.tag, str):
                continue
            if node.get("id") in referenced:
                return True
            if (node.get("role") or "").strip().lower() in _REACHABLE_ROLES:
                return True
        for ancestor in container.iterancestors():
            if ancestor.tag == "details" or (ancestor.get("role") or "").strip().lower() in _REACHABLE_ROLES:
                return True
            # A reference to the page's main region does not open a tray inside it: MDN's
            # skip link `href="#content"` names `<main id="content">`, an ancestor of
            # everything, and made every hidden copy under it "reachable".
            if ancestor.get("id") in referenced and ancestor.tag not in _REGION_TAGS and (
                ancestor.get("role") or ""
            ).strip().lower() not in _REGION_ROLES:
                return True
        return False

    # A page with a code editor keeps its hidden source listings: the editor draws only
    # the lines in view, and the hidden `<pre>` it was built from is the whole document,
    # which `_complete_editor_windows` gives back to the editor's block (MDN's "Try it").
    has_editor = any(_is_editor(e) for e in root.iter() if isinstance(e.tag, str))

    doomed: list[HtmlElement] = []
    for element in root.xpath(f"//*[@{HIDDEN_ATTRIBUTE}]"):
        if element.get(HIDDEN_ATTRIBUTE) not in _UNSHOWN_KINDS:
            continue
        if any(a.get(HIDDEN_ATTRIBUTE) in _UNSHOWN_KINDS for a in element.iterancestors()):
            continue  # the outermost hidden container decides
        if not element.text_content().strip():
            continue
        if reachable(element):
            continue
        if has_editor and (element.tag == "pre" or element.find(".//pre") is not None):
            continue
        doomed.append(element)
    for element in doomed:
        parent = element.getparent()
        if parent is not None:
            _carry_tail(parent, element)
            parent.remove(element)


def _drop_clipped(root: HtmlElement) -> None:
    """Remove the elements the renderer measured as screen-reader-only -- clipped to a 1px
    box -- whatever their class is called. The same text the `SR_ONLY_CLASSES` rule removes
    on a static fetch, found by measurement on a rendered one; `include_hidden_text` keeps
    both. Nothing is marked on a static fetch and nothing happens."""
    for element in root.xpath(f"//*[@{HIDDEN_ATTRIBUTE}='clipped']"):
        parent = element.getparent()
        if parent is None:
            continue
        _carry_tail(parent, element)
        parent.remove(element)


def _drop_hidden_twins(root: HtmlElement) -> None:
    """Remove a hidden element whose visible sibling says the same thing.

    Responsive markup renders one label twice -- `<span class="md:hidden">NEW</span>
    <span class="hidden md:block">NEW</span>` -- and the browser shows one. Both are inline,
    so they share a block, and the block read "NEW NEW". Only a hidden element with a
    *visible* sibling carrying the same text goes; a hidden element saying something of its
    own (a collapsed panel, a tab) is content and stays, unmeasured, where source order puts
    it. On a static fetch nothing is marked and nothing happens.
    """
    # Pass one: a parent whose hidden children, taken together, say exactly what its other
    # children say. linear.app's <h1> holds the headline three ways -- four `show-mobile`
    # spans (display none on a laptop), two `hide-mobile` spans (opacity 0 until the
    # entrance animation runs), and a clipped copy -- and no single hidden span has a
    # single visible twin. Compared without whitespace, since the copies differ in where
    # the lines break; `opacity` counts as showing, since content faded in by a scroll
    # animation is content.
    for parent in root.xpath(f"//*[*[@{HIDDEN_ATTRIBUTE}]]"):
        hidden_children = [
            child
            for child in parent
            if isinstance(child.tag, str) and child.get(HIDDEN_ATTRIBUTE) in _ABSENT_KINDS
        ]
        if not hidden_children:
            continue
        hidden_text = "".join("".join(c.text_content().split()) for c in hidden_children)
        shown_text = "".join(
            "".join(c.text_content().split())
            for c in parent
            if isinstance(c.tag, str) and c.get(HIDDEN_ATTRIBUTE) not in _ABSENT_KINDS
        ) + "".join((parent.text or "").split())
        if hidden_text and hidden_text == shown_text:
            for child in hidden_children:
                _carry_tail(parent, child)
                parent.remove(child)

    # Pass two: one hidden element beside one visible sibling saying the same thing.
    for hidden in root.xpath(f"//*[@{HIDDEN_ATTRIBUTE}]"):
        parent = hidden.getparent()
        if parent is None:
            continue
        text = "".join(hidden.text_content().split())
        if not text:
            continue
        twin = any(
            sibling is not hidden
            and isinstance(sibling.tag, str)
            and sibling.get(HIDDEN_ATTRIBUTE) is None
            and "".join(sibling.text_content().split()) == text
            for sibling in parent
        )
        if twin:
            _carry_tail(parent, hidden)
            parent.remove(hidden)


_ABSENT_KINDS: Final[frozenset[str]] = frozenset({"display", "visibility", "overflow"})
"""The ways of hiding that mean "not on the page": `display: none`, `visibility: hidden`
and `overflow` (clipped out entirely by an `overflow: hidden` ancestor -- a collapsed
accordion tray). `opacity` is not one -- a scroll animation starts its text at opacity 0
-- and `clipped` is handled by `_drop_clipped` before this runs."""


def _carry_tail(parent: HtmlElement, element: HtmlElement) -> None:
    tail = element.tail
    if not tail:
        return
    previous = element.getprevious()
    if previous is not None:
        previous.tail = (previous.tail or "") + tail
    else:
        parent.text = (parent.text or "") + tail


def _is_hidden(element: HtmlElement) -> bool:
    """Whether the renderer found this element, or an ancestor, not on the page."""
    return any(
        node.get(HIDDEN_ATTRIBUTE) in _ABSENT_KINDS for node in (element, *element.iterancestors())
    )


def _is_control(button: HtmlElement) -> bool:
    """Whether a standalone `<button>` is a control the reader cannot even see.

    A button the browser is not showing -- sphinx-copybutton's "Copy", drawn at opacity 0
    until the code block is hovered -- is never content; it came out as a one-word paragraph
    between "For example:" and the example on every docs.python.org page. A *visible*
    button stays, however short: its label can be the only text an interstitial has (the
    gate probe reads "Solo Founder" off exactly such a button), and an accordion's question
    is often a button and nothing else.
    """
    return button.get(HIDDEN_ATTRIBUTE) is not None


_MAX_CODE_HEADER_WORDS: Final[int] = 4


def _is_code_header(element: HtmlElement, text: str) -> bool:
    """Whether this is the strip above a code block: a language label and a copy button.

    MDN renders every example as `<div class="example-header"><span>js</span>
    <button>Copy</button></div><pre>...`, and "js Copy" arrived as a paragraph before each
    of the eleven examples on Array.prototype.reduce(). The strip is the element directly
    before a `<pre>` with no more than a few words in it; a caption or a sentence
    introducing the code is longer, and stays.
    """
    if not 0 < len(text.split()) <= _MAX_CODE_HEADER_WORDS:
        return False
    following = element.getnext()
    while following is not None and not isinstance(following.tag, str):
        following = following.getnext()
    return following is not None and following.tag == "pre"


def _last_descendant(element: HtmlElement) -> HtmlElement:
    """The element `root.iter()` visits last inside `element` -- `element` itself if none."""
    last = element
    for last in element.iterdescendants():  # noqa: B007 -- the final value is the point
        pass
    return last


def extract_rich_blocks(
    root: HtmlElement, base_url: str, *, min_chars: int = 1, include_hidden_text: bool = False
) -> list[Block]:
    """Extract blocks with their structure intact, in document order.

    `include_hidden_text` keeps screen-reader-only labels and wiki edit controls -- see
    `strip_permalinks`."""
    # Media survives this strip so it can become a placeholder; see `MEDIA_TAGS`. Its own
    # children (`<source>`, `<track>`) are read by `_media_block` and never emitted.
    keep = MEDIA_TAGS | _MEDIA_CHILDREN
    etree.strip_elements(root, *(t for t in SKIP_TAGS if t not in keep), with_tail=False)
    etree.strip_elements(root, etree.Comment, with_tail=False)
    strip_permalinks(root, keep_hidden_text=include_hidden_text)
    if not include_hidden_text:
        _drop_clipped(root)
    _drop_closed_dialogs(root)
    _drop_hidden_twins(root)
    _drop_unreachable_hidden(root)

    tree = root.getroottree()
    blocks: list[Block] = []
    index = 0
    consumed: set[HtmlElement] = set()
    landmark_cache: dict[HtmlElement, tuple[str | None, bool]] = {}
    float_cache: dict[HtmlElement, HtmlElement | None] = {}
    body_cache: dict[HtmlElement, HtmlElement | None] = {}
    widget_cache: dict[HtmlElement, str | None] = {}
    editors: set[str] = set()
    hidden_code: set[str] = set()
    body_words = len(root.text_content().split())
    # A container's own text, held until the walk reaches the child block it precedes (or
    # the container's last descendant, for text after every child), so the block lands
    # where the reader meets it. See `_orphan_runs`.
    held_before: dict[HtmlElement, list[tuple[HtmlElement, _OrphanRun]]] = {}
    held_after: dict[HtmlElement, list[tuple[HtmlElement, _OrphanRun]]] = {}

    def admit(block: Block, element: HtmlElement) -> None:
        nonlocal index
        if block.kind not in (BlockKind.IMAGE, BlockKind.MEDIA) and len(block.text) < min_chars:
            return
        region, in_main = _landmarks_of(element, landmark_cache)
        if region is not None or in_main:
            block = block.model_copy(update={"region": region, "in_main": in_main})
        floated = _float_of(element, float_cache)
        if floated is not None:
            block = block.model_copy(update={"float_of": tree.getpath(floated)})
        body = _body_of(element, body_cache)
        if body is not None:
            block = block.model_copy(update={"body_of": tree.getpath(body)})
        depth = sum(1 for a in element.iterancestors() if a.tag == "blockquote")
        if element.tag == "blockquote" and block.kind is not BlockKind.QUOTE:
            depth += 1  # the quote's own text between its blocks, read as an orphan run
        if depth:
            block = block.model_copy(update={"quoted": depth})
        widget = _widget_of(element, widget_cache, body_words)
        if widget is not None:
            block = block.model_copy(update={"widget": widget})
        blocks.append(block)
        index += 1

    def admit_orphans(held: list[tuple[HtmlElement, _OrphanRun]]) -> None:
        for container, run in held:
            source = run.anchor if run.anchor is not None else container
            xpath = (
                tree.getpath(run.anchor)
                if run.anchor is not None
                else f"{tree.getpath(container)}/text()[{run.ordinal + 1}]"
            )
            admit(
                Block(
                    text=run.text,
                    tag=container.tag,
                    xpath=xpath,
                    dom_index=index,
                    kind=BlockKind.PARAGRAPH,
                    rich_text=run.rich if run.rich != run.text else None,
                ),
                source,
            )

    previous: HtmlElement | None = None
    for element in root.iter():
        # The previous element is complete once the walk moves on, whatever branch it took.
        if previous is not None and previous in held_after:
            # Innermost first: an inner container registered after the outer one it sits
            # in, and its trailing text comes before the outer container's.
            admit_orphans(_innermost_first(held_after.pop(previous)))
        previous = element
        tag = element.tag
        if not isinstance(tag, str):
            continue
        if element in held_before:
            admit_orphans(held_before.pop(element))
        if element in consumed:
            continue

        block: Block | None = None

        if tag in MEDIA_TAGS:
            block = _media_block(element, base_url, index, tree)
            consumed.update(element.iterdescendants())

        elif tag == "img":
            block = _image_block(element, base_url, index, tree)

        elif tag == "table":
            if is_layout_table(element):
                # Not a table of data but a page built out of one. Fall through and treat it
                # as an ordinary container so its real content is extracted.
                continue
            block = _table_block(element, index, tree, base_url)
            # Consume this table's own descendants, but leave any nested table -- and
            # everything under it -- for its own turn in this loop. A nested data table is a
            # table, and emitting it separately is how its rows survive; `_cell_text` has
            # already kept its text out of the containing cell, so nothing is duplicated and
            # nothing is lost.
            nested: set[HtmlElement] = set()
            for inner in element.xpath(".//table"):
                nested.add(inner)
                nested.update(inner.iterdescendants())
            consumed.update(d for d in element.iterdescendants() if d not in nested)

        elif _is_editor(element):
            # A code editor's DOM (CodeMirror, Monaco, Ace) is one code block: its lines,
            # not its gutter, cursor and measuring layers. Judged before `<pre>` because
            # CodeMirror 5 draws each line as a `<pre>` of its own.
            block = _editor_block(element, index, tree)
            if block is not None:
                editors.add(block.xpath)
            consumed.update(element.iterdescendants())

        elif tag == "pre":
            # Verbatim, deliberately: `flowed_text` would insert separators at the block
            # boundaries a syntax highlighter creates, and a code block's whitespace is its
            # meaning. This is the one place `text_content()` is still the right call.
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
                if _is_hidden(element):
                    hidden_code.add(block.xpath)
            consumed.update(element.iterdescendants())

        elif tag == "blockquote" and not _quote_has_structure(element):
            # A quote made of blocks -- a table, a list, code, several paragraphs -- takes
            # the container branch below instead: it is walked into, its own text between
            # the blocks read as orphan runs, and each block inside carries `quoted` so the
            # Markdown can prefix it. Flattening it to one line lost the table's rows;
            # skipping it lost a XenForo post, whose body *is* a `<blockquote>` (spigotmc).
            text = normalize_text(flowed_text(element))
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
            text = normalize_text(flowed_text(element))
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
            text = normalize_text(flowed_text(element))
            if text:
                block = Block(
                    text=text,
                    tag=tag,
                    xpath=tree.getpath(element),
                    dom_index=index,
                    kind=BlockKind.FIGURE_CAPTION,
                )

        elif tag in _TEXT_CONTAINERS:
            if _is_code_header(element, normalize_text(flowed_text(element))):
                # The strip above a code block -- language label, copy button -- with
                # everything in it, however the button is nested.
                consumed.update(element.iterdescendants())
                continue
            # Innermost rule: only emit when no descendant is itself a block, so a wrapper
            # div never swallows a whole column.
            has_block_descendant = any(
                isinstance(d.tag, str)
                and (d.tag in _TEXT_CONTAINERS or d.tag in _HEADINGS or d.tag in _ATOMIC)
                and normalize_text(flowed_text(d))
                for d in element.iterdescendants()
            )
            # A container holding a block descendant is skipped so a wrapper does not swallow
            # the column beneath it -- but its own text is still content, and used to be lost
            # outright. A list item keeps its label via `_own_text`; every other container
            # keeps whatever text no child block will carry, via `_orphan_text`.
            if not has_block_descendant:
                text = normalize_text(flowed_text(element))
            elif tag in {"li", "dd", "dt"}:
                text = _own_text(element)
            else:
                text = ""
                for run in _orphan_runs(element, base_url):
                    if run.before is not None:
                        held_before.setdefault(run.before, []).append((element, run))
                    else:
                        last = _last_descendant(element)
                        held_after.setdefault(last, []).append((element, run))
            if text and tag == "button" and _is_control(element):
                text = ""
            if text:
                rich = _inline_markdown(element, base_url, orphan_only=has_block_descendant)
                item, first = _item_of(element)
                if tag == "li":
                    ordered, level = _list_context(element)
                    kind = BlockKind.LIST_ITEM
                elif item is not None:
                    # DocBook, Sphinx and every wiki write `<li><p>…</p></li>`; the item's
                    # first paragraph *is* the item, and the ones after it are its
                    # continuation, indented under the bullet in the Markdown.
                    ordered, level = _list_context(item)
                    kind = BlockKind.LIST_ITEM if first else BlockKind.PARAGRAPH
                else:
                    ordered, level, kind = False, 0, BlockKind.PARAGRAPH
                # A `<br><br>` is a paragraph break: the paragraphs of a pre-CSS page, of a
                # forum post, of an email pasted into a `<div>`. Each becomes a block of its
                # own, as it would have with `<p>` tags; a list item stays one item.
                pieces = _paragraphs(text, rich) if kind is BlockKind.PARAGRAPH else [(text, rich)]
                for piece_text, piece_rich in pieces[:-1]:
                    admit(
                        Block(
                            text=piece_text,
                            tag=tag,
                            xpath=tree.getpath(element),
                            dom_index=index,
                            kind=kind,
                            level=level,
                            ordered=ordered,
                            rich_text=piece_rich if piece_rich != piece_text else None,
                        ),
                        element,
                    )
                text, rich = pieces[-1]
                block = Block(
                    text=text,
                    tag=tag,
                    xpath=tree.getpath(element),
                    dom_index=index,
                    kind=kind,
                    level=level,
                    ordered=ordered,
                    rich_text=rich if rich != text else None,
                )

        if block is not None:
            admit(block, element)
    if previous is not None and previous in held_after:
        admit_orphans(_innermost_first(held_after.pop(previous)))

    return _complete_editor_windows(blocks, editors, hidden_code)


_LANDMARK_TAGS: Final[dict[str, str]] = {
    "main": "main", "nav": "nav", "header": "header", "footer": "footer", "aside": "aside",
}
_LANDMARK_ROLES: Final[dict[str, str]] = {
    "main": "main",
    "navigation": "nav",
    "banner": "header",
    "contentinfo": "footer",
    "complementary": "aside",
}


def _landmark_of_element(element: HtmlElement) -> str | None:
    """The landmark this element *is*, by tag or ARIA role; None if it is neither.

    An `<aside>` that is a callout is not a landmark. Starlight (Astro's docs, and the
    many sites built on it) renders every Note, Tip and Caution as
    `<aside aria-label="Tip" class="starlight-aside starlight-aside--tip">`, and
    stripping asides -- right for a sidebar of teasers -- took every tip out of the
    Astro documentation. A callout says what it is, in its label or its class names.
    """
    tag = element.tag if isinstance(element.tag, str) else ""
    role = (element.get("role") or "").strip().lower()
    if role in _LANDMARK_ROLES:
        return _LANDMARK_ROLES[role]
    if tag == "aside" and _is_callout(element):
        return None
    return _LANDMARK_TAGS.get(tag)


_CALLOUT_WORDS: Final[frozenset[str]] = frozenset({
    "note", "notes", "tip", "tips", "caution", "danger", "warning", "info", "important",
    "hint", "admonition", "callout", "alert", "success", "example", "aside--note",
    "aside--tip", "aside--caution", "aside--danger",
})
_CALLOUT_LABEL: Final[re.Pattern[str]] = re.compile(
    r"^(?:note|tip|caution|danger|warning|info|important|hint|example|see also)\b", re.I
)


def _is_callout(aside: HtmlElement) -> bool:
    label = (aside.get("aria-label") or "").strip()
    if label and _CALLOUT_LABEL.match(label):
        return True
    names = f"{aside.get('class') or ''} {aside.get('id') or ''}".lower()
    return bool(_CALLOUT_WORDS & set(_TOKEN_SPLIT.split(names)))


_FILTER_TOKENS: Final[frozenset[str]] = frozenset({
    "filter", "filters", "facet", "facets", "faceted", "refine", "refinement", "refinements",
    "filterbar", "filternav", "filtersidebar",
})
_TOKEN_SPLIT: Final[re.Pattern[str]] = re.compile(r"[\s_\-:/.]+")
_RAIL_COMPOUNDS: Final[frozenset[str]] = frozenset({
    # Two-part names that are unambiguous as a whole.
    "breaking-news", "news-ticker", "most-read", "most-popular", "most-viewed", "popular-posts",
    "related-posts", "related-articles", "related-stories", "related-news", "related-content",
    "recent-posts", "latest-news", "latest-posts", "trending-now", "trending-posts",
    "share-bar", "social-share", "share-buttons", "sharing-buttons", "newsletter-signup",
    "newsletter-form", "ad-slot", "ad-container", "ad-wrapper", "ad-unit", "read-next",
    "you-may-like", "also-read", "more-stories", "promo-box", "sticky-ad", "top-stories",
})
_RAIL_TOKENS: Final[frozenset[str]] = frozenset({
    # Single tokens that name a rail and nothing else.
    "ticker", "newsticker", "marquee", "outbrain", "taboola", "sharedaddy", "yarpp",
    "jp-relatedposts", "crp_related", "breadcrumb", "breadcrumbs", "skyscraper", "adsbygoogle",
    "mgid", "revcontent", "zergnet", "sharethis", "addthis",
    # The landmarks a page built before HTML5 names instead of marking: `<div id="footer">`,
    # `<div class="nav">`. jpost.com (2019) still puts its 400-word footer in
    # `div.footer-wrap`, and with no <footer> to strip it outscored a one-paragraph story.
    "footer", "site-footer", "page-footer", "global-footer", "main-footer", "footer-wrap",
    "footer-wrapper", "footer-container", "footer-inner", "colophon",
    "nav", "navbar", "main-nav", "mainnav", "site-nav", "primary-nav", "top-nav", "topnav",
    "navigation", "main-navigation", "site-navigation", "primary-navigation", "main-menu",
    "mainmenu", "mega-menu", "megamenu",
})
_RAIL_ATTR_SPLIT: Final[re.Pattern[str]] = re.compile(r"\s+")
_POST_FURNITURE: Final[frozenset[str]] = frozenset({
    # Forum software's per-post furniture: the signature under a post and the user card
    # beside it. phpBB, XenForo, Invision, MyBB and Discourse each name them; the post body
    # itself is never named this way.
    "signature", "post-signature", "message-signature", "signature-view", "signature-content",
    "signature-content-wrapper", "signature-collapsed", "postsignature",
    "message-user", "message-userdetails", "message-userextras", "message-userbanner",
    "user-info", "userinfo", "messagecard__user-info", "postprofile",
    "post-profile", "author-info", "authorinfo", "memberinfo", "member-info", "extrauserinfo",
    "messageuserinfo", "ipsentry__profile-row", "user-title", "usertitle", "reputation-score",
    "post-count", "postcount", "messagecard__post-count",
})


def _names_post_furniture(element: HtmlElement) -> bool:
    names = f"{element.get('class') or ''} {element.get('id') or ''}".lower().strip()
    if not names:
        return False
    return any(token in _POST_FURNITURE for token in _RAIL_ATTR_SPLIT.split(names))


def _holds_the_article(element: HtmlElement) -> bool:
    """Whether the page's `<h1>` or its `itemprop="articleBody"` sits inside this element. A
    rail never holds either: jpost.com's headline and story rows are both
    `g-row-breaking-news`, named after their section like the `breaking-news-lst` ticker
    beside them that is one; the story itself is `article-inner-content-breaking-news`
    and says what it is in its microdata."""
    if next(element.iter("h1"), None) is not None:
        return True
    return any("articlebody" in (e.get("itemprop") or "").lower() for e in element.iter("div", "section", "article", "p"))


def _names_rail(element: HtmlElement) -> bool:
    """Whether this element's class or id names a rail of other things: a news ticker, a
    most-read list, a share bar, an ad slot, a recommendation widget. The vocabulary is
    the one boilerplate detectors have used since Readability's `unlikelyCandidates`,
    kept to names that mean one thing; `sidebar` and `related` on their own are not in it
    because themes use them for the article column and for content."""
    names = f"{element.get('class') or ''} {element.get('id') or ''}".lower().strip()
    if not names:
        return False
    for token in _RAIL_ATTR_SPLIT.split(names):
        if token in _RAIL_TOKENS or token in _RAIL_COMPOUNDS:
            return True
        # `sidebar-most-read`, `widget_related-posts`: a compound inside a longer token.
        for compound in _RAIL_COMPOUNDS:
            if compound in token and (token == compound or not token.replace(compound, "x").isalnum()):
                return True
    return False


_CONSENT_MARKERS: Final[re.Pattern[str]] = re.compile(
    # Vendors' own container names, then the generic ones sites hand-roll.
    r"(?:^|[\s_\-])(?:onetrust|ot-sdk|optanon|cybotcookiebotdialog|cookiebot|qc-cmp2|didomi|"
    r"truste|sp_message|cookieconsent|cc-window|cookie-?(?:banner|notice|consent|bar|popup|"
    r"modal|dialog|law|policy-banner|settings|policy|wrapper|wrap|box|container|overlay|"
    r"message|msg|alert|prompt|disclaimer|info)|consent-?(?:banner|manager|modal|dialog|popup|"
    r"notice|overlay)|gdpr-?(?:banner|consent|modal|popup|notice)|privacy-?(?:banner|manager))"
    r"(?:$|[\s_\-])",
    re.I,
)


_COMMENT_WORDS: Final[frozenset[str]] = frozenset({"comment", "comments"})
_COMMENT_COMPOUNDS: Final[frozenset[str]] = frozenset({
    "commentlist", "commentlisting", "commentbox", "commentwrap", "commentsection",
    "commentsarea", "disqus_thread", "wpdiscuz", "commento", "isso-thread", "remark42",
})
_NOT_A_COMMENT_SECTION: Final[frozenset[str]] = frozenset({
    # Parts that make a token a flag, a count or a piece of one comment rather than the
    # section: Squarespace stamps `has-comments` on the article itself.
    "has", "enabled", "disabled", "count", "counts", "open", "closed", "no", "with",
    "toggle", "icon", "link", "meta", "author", "date", "reply", "message", "notification",
    "nonce", "privacy", "field", "recent", "button", "btn", "label", "input", "js",
})


def _names_comments(element: HtmlElement) -> bool:
    """Whether this element's class or id says it is the comments section.

    A token whose parts include the word `comment(s)` and no part that makes it a flag or
    a piece (`comments`, `comments-area`, `comment-list`, `wpd-comment`; not
    `has-comments`, `comment-count`, `comment-author`), or a run-together spelling
    (`commentlisting`, `disqus_thread`).
    """
    names = f"{element.get('class') or ''} {element.get('id') or ''}".lower()
    if "comment" not in names and "disqus" not in names and "wpdiscuz" not in names:
        return False
    for token in names.split():
        if token in _COMMENT_COMPOUNDS:
            return True
        parts = set(_TOKEN_SPLIT.split(token))
        if _COMMENT_WORDS & parts and not (_NOT_A_COMMENT_SECTION & parts):
            return True
    return False


def _names_consent(element: HtmlElement) -> bool:
    """Whether this element's own class or id says it is a cookie-consent dialog."""
    names = f"{element.get('class') or ''} {element.get('id') or ''}".strip()
    return bool(names) and _CONSENT_MARKERS.search(names) is not None


def _names_filter(element: HtmlElement) -> bool:
    """Whether this element's own class, id or ARIA label says it is a filter panel."""
    names = " ".join(
        element.get(attribute) or "" for attribute in ("class", "id", "aria-label", "data-testid")
    ).lower()
    if not names:
        return False
    return any(token in _FILTER_TOKENS for token in _TOKEN_SPLIT.split(names))


def _widget_of(
    element: HtmlElement, cache: dict[HtmlElement, str | None], body_words: int
) -> str | None:
    """The named interactive panel around this element, memoised; None when there is none.

    Only `filter` today. A faceted-search panel on a collection page is the boilerplate no
    density rule can see: it sits inside `main`, it is made of links and checkboxes like
    the grid beside it, and on newegg.com it is 3,000 words of "ASUS" and "394 mm" around
    a 650-word grid. Its authors name it, on the panel or on the fieldsets inside it, and
    that name is read here.

    A name is not enough on its own: headphones.com wraps its whole grid in a
    `collection-filters-and-products` div. A panel that holds more than
    `_MAX_WIDGET_SHARE` of the page's words is the page, not a panel, whatever it is
    called; and a `<fieldset>` counts only when it holds checkboxes.
    """
    if element in cache:
        return cache[element]
    parent = element.getparent()
    above = _widget_of(parent, cache, body_words) if parent is not None else None
    own: str | None = None
    if above is None:
        tag = element.tag if isinstance(element.tag, str) else ""
        if tag in _FURNITURE_TAGS and _names_post_furniture(element):
            words = len(element.text_content().split())
            if words <= _MAX_WIDGET_SHARE * body_words:
                cache[element] = "post-furniture"
                return "post-furniture"
        if tag in _RAIL_TAGS and _names_rail(element) and not _holds_the_article(element):
            words = len(element.text_content().split())
            if words <= _MAX_WIDGET_SHARE * body_words:
                cache[element] = "rail"
                return "rail"
        if tag in _WIDGET_TAGS and _names_consent(element):
            # A cookie-consent dialog. OneTrust's preference centre is 2,000 words of
            # "Strictly Necessary Cookies" and "We and our 644 partners", in the DOM of 12%
            # of WCXB dev and chosen as the main content of a GameFAQs thread (P 0.03).
            # qburst.com hand-rolls one as `cookieWrapper` / `cookiePolicy`. A page that is
            # nothing but its "cookie policy" is the cookie policy page, and is kept.
            words = len(element.text_content().split())
            if words <= _MAX_COMMENTS_SHARE * body_words:
                cache[element] = "consent"
                return "consent"
        if tag in _COMMENT_TAGS and _names_comments(element):
            # The comments under an article. Whether they are content is the page type's
            # call (a forum thread *is* comments), so they are marked here and the content
            # step decides. The share guard is loose: on a Slashdot story the thread is
            # nine tenths of the page and is still not the story; only a page that is
            # nothing but its "comments" keeps them regardless of policy.
            words = len(element.text_content().split())
            if words <= _MAX_COMMENTS_SHARE * body_words:
                cache[element] = "comments"
                return "comments"
        named = tag in _WIDGET_TAGS and (
            _names_filter(element)
            or (tag == "fieldset" and bool(element.xpath('.//input[@type="checkbox"]')))
        )
        if named and element.xpath(".//input | .//select"):
            # A filter is operated: it has controls. brother-usa.com builds its FAQ
            # accordion from a component called `facet-row` / `filters`; it has none.
            words = len(element.text_content().split())
            if words <= _MAX_WIDGET_SHARE * body_words:
                own = "filter"
    result = above if above is not None else own
    cache[element] = result
    return result


_FURNITURE_TAGS: Final[frozenset[str]] = frozenset({"div", "section", "aside", "ul", "dl", "td", "span", "p", "footer", "header"})
_RAIL_TAGS: Final[frozenset[str]] = frozenset({"div", "section", "aside", "ul", "ol", "nav", "footer", "header", "table"})
_COMMENT_TAGS: Final[frozenset[str]] = frozenset(
    {"div", "section", "aside", "article", "ol", "ul", "li", "form", "footer", "table", "tbody", "tr", "td"}
)
_WIDGET_TAGS: Final[frozenset[str]] = frozenset(
    {"div", "section", "aside", "form", "fieldset", "nav", "ul", "details"}
)
_MAX_WIDGET_SHARE: Final[float] = 0.4
_MAX_COMMENTS_SHARE: Final[float] = 0.92


_BODY_NAMES: Final[frozenset[str]] = frozenset({
    # What a CMS calls the element holding the story and nothing else. The list is the
    # core of trafilatura's BODY_XPATH and Readability's positive patterns, kept to names
    # that mean the body: not `content`, `text` or `entry` alone, which themes hang on
    # whole columns.
    "entry-content", "entry-body", "entrycontent", "post-content", "post_content",
    "postcontent", "post-body", "post_body", "postbody", "post-entry", "post-text",
    "post_text", "posttext", "post-bodycopy", "article-body", "article__body",
    "articlebody", "article-content", "article__content", "articlecontent", "article-text",
    "articletext", "article__text", "story-body", "story__body", "storybody",
    "story-content", "storycontent", "story-text", "storytext", "content-body",
    "content__body", "body-copy", "bodycopy", "field-body", "fulltext", "td-post-content",
    "news-body", "news-content", "news-text", "blog-content", "blog-post-content",
})
_BODY_TAGS: Final[frozenset[str]] = frozenset({"div", "section", "article", "main"})


def _names_body(element: HtmlElement) -> bool:
    tag = element.tag if isinstance(element.tag, str) else ""
    if tag not in _BODY_TAGS:
        return False
    if "articlebody" in (element.get("itemprop") or "").lower():
        return True
    names = f"{element.get('class') or ''} {element.get('id') or ''}".lower().strip()
    return bool(names) and any(token in _BODY_NAMES for token in _RAIL_ATTR_SPLIT.split(names))


def _body_of(
    element: HtmlElement, cache: dict[HtmlElement, HtmlElement | None]
) -> HtmlElement | None:
    """The outermost ancestor-or-self that names itself the article body; None if none.

    Outermost, so a `div.entry-content` wrapping `div.post-body` is one body, not two
    halves that split its words between them when the content step asks which body
    dominates the page."""
    if element in cache:
        return cache[element]
    parent = element.getparent()
    above = _body_of(parent, cache) if parent is not None else None
    result = above if above is not None else (element if _names_body(element) else None)
    cache[element] = result
    return result


def _float_of(
    element: HtmlElement, cache: dict[HtmlElement, HtmlElement | None]
) -> HtmlElement | None:
    """The outermost floated ancestor-or-self, memoised; None when nothing above floats.

    Outermost, so that a float inside a float -- an image floated within a floated
    infobox -- is one thing, not two. Absent on a static fetch, where nothing is marked."""
    if element in cache:
        return cache[element]
    parent = element.getparent()
    above = _float_of(parent, cache) if parent is not None else None
    own = element if element.get(FLOAT_ATTRIBUTE) is not None else None
    result = above if above is not None else own
    cache[element] = result
    return result


def _landmarks_of(
    element: HtmlElement, cache: dict[HtmlElement, tuple[str | None, bool]]
) -> tuple[str | None, bool]:
    """(innermost landmark region, whether any ancestor is main), memoised per element.

    Walks up once per distinct ancestor; a page with thousands of blocks shares a handful of
    ancestor chains, so the memo makes this linear in practice.
    """
    hit = cache.get(element)
    if hit is not None:
        return hit
    own = _landmark_of_element(element)
    parent = element.getparent()
    if parent is None:
        result: tuple[str | None, bool] = (own, own == "main")
    else:
        parent_region, parent_main = _landmarks_of(parent, cache)
        result = (own if own is not None else parent_region, parent_main or own == "main")
    cache[element] = result
    return result
