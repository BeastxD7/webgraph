"""Assemble a `Document` from raw HTML.

Stage order here is deliberate and load-bearing:

1. **Payloads first.** Structured data lives in `<script>` tags, and block extraction
   strips those from the tree. Reading payloads after block extraction silently returns
   nothing -- so block extraction works on a *copy* of the parsed tree, and the original
   stays intact for the payload and profile passes. A copy rather than a second parse:
   lxml copies a 2 MB page's tree in 15 ms and parses it in 37 ms, and the copy is exact
   where a re-parse merely agrees.
2. **Blocks**, from the copy.
3. **Geometry**, attached by XPath when a render supplied it.
4. **Reading order**, which needs the geometry to do better than source order.
5. **Deduplication**, after ordering so "first" means first *read*. A single DOM often
   carries two renderings of one page -- a mobile layout and a desktop layout -- and emits
   every paragraph twice.
6. **Content hash**, computed over reading-ordered text rather than raw HTML, so that
   cosmetic markup churn (build hashes, analytics tokens, reordered attributes) does not
   read as a content change. This is the gate that stops needless re-extraction.
"""

from __future__ import annotations

import copy
import hashlib

from webgraph.dom.blocks import is_rtl_document, parse_html
from webgraph.dom.reading_order import OrderingConfig, order_blocks
from webgraph.dom.rich import extract_rich_blocks
from webgraph.profile.fingerprint import profile_page
from webgraph.profile.technology import RuntimeEvidence
from webgraph.structured.payloads import extract_payloads
from webgraph.types import Block, Document, Rect

__all__ = ["build_document", "content_hash_of"]


def content_hash_of(text: str) -> str:
    """Stable hash of page content.

    Computed over extracted text, never raw HTML: two fetches of an unchanged page differ
    in build hashes, CSRF tokens and analytics identifiers, all of which would defeat the
    gate if hashed.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_document(
    html: str,
    url: str,
    *,
    geometry: dict[str, Rect] | None = None,
    rtl: bool | None = None,
    ordering: OrderingConfig | None = None,
    min_block_chars: int = 1,
    headers: dict[str, str] | None = None,
    runtime: RuntimeEvidence | None = None,
) -> Document:
    """Parse `html` into a `Document` with blocks in reading order.

    `geometry` maps XPath to bounding box, as produced by a rendered fetch. Without it the
    document falls back to DOM order and says so via `reading_order_method`.

    `rtl` defaults to `None`, meaning **detect it from the document**. It used to default to
    `False`, and every caller except the CLI left it there -- so `resolve_page`, the path the
    API and every crawl actually use, ordered every Arabic, Hebrew and Persian page
    left-to-right. On a multi-column RTL page that reads the columns backwards while
    reporting `geometric-xy-cut`, which is the failure this engine least tolerates. Pass an
    explicit bool to override the detection.
    """
    payload_tree = parse_html(html)
    payloads = extract_payloads(payload_tree, html)

    # Detected on the payload parse, which still has the whole tree. Block extraction strips
    # elements from the tree it is given, and `<body dir>` would survive that -- but reading
    # the direction before anything is removed keeps the two independent.
    if rtl is None:
        rtl = is_rtl_document(payload_tree)

    # Block extraction strips <script>/<style> from the tree it is given, and the profile
    # pass below still needs them. Copy rather than parse again -- see the module docstring.
    block_tree = copy.deepcopy(payload_tree)
    blocks = extract_rich_blocks(block_tree, url, min_chars=min_block_chars)

    if geometry:
        blocks = _attach_geometry(blocks, geometry)

    ordered, method = order_blocks(list(blocks), rtl=rtl, config=ordering)
    ordered = _deduplicate(ordered)

    text = "\n\n".join(b.text for b in ordered if b.text.strip())
    profile = profile_page(
        payload_tree,
        html,
        text_length=len(text),
        headers=headers,
        runtime=runtime,
        url=url,
    )

    return Document(
        url=url,
        html=html,
        blocks=tuple(ordered),
        reading_order_method=method,
        profile=profile,
        structured_data=payloads,
        content_hash=content_hash_of(text),
    )


def _deduplicate(blocks: list[Block]) -> list[Block]:
    """Drop blocks repeating text an earlier block already carried.

    Measured on WCXB (2,008 pages, 1,613 domains): **28.8% of emitted blocks repeat text
    already emitted**, and removing the repeats is worth +5.2 F1 on product and collection
    pages -- more than any other single change available, and it needs no new signal.

    The cause is usually one DOM carrying two renderings of the same page. `ascolour.com`
    emits every paragraph twice, from sibling `section[3]/section…` and `section[3]/div…`
    subtrees: the mobile layout and the desktop layout, one of which a browser hides. A
    reader sees each paragraph once and so should a consumer.

    Identity is `(text, href)`. The `href` is what protects images: two different pictures
    legitimately share alt text -- `photo` on a gallery of them -- and they stay distinct
    because their sources differ, while two references to the *same* image collapse.

    `kind` is deliberately **not** part of the key, having been so at first. Including it let
    one sentence survive twice under two labels: pudding.cool emits "Some of my favorite
    projects: wonky rhythms, flipbook and human terrain" as both a `list-item` and a
    `paragraph`, from two renderings of the same navigation. A reader sees it once. Which tag
    a duplicate happens to wear is not a reason to keep it.

    **The measured copy wins.** When a repeat carries a rectangle and the first occurrence
    does not, the rendered one is kept: a block the browser laid out is the one actually on
    the page, and the unmeasured twin is the hidden layout. Keeping the first blindly would
    discard the geometry that reading order depends on.

    This runs after ordering, so "first" means first in reading order rather than first in
    source -- on a page where the two differ, the one a reader reaches first is the one to
    keep.
    """
    seen: dict[tuple[str, str | None], int] = {}
    kept: list[Block] = []

    for block in blocks:
        text = " ".join(block.text.split()).casefold()
        if not text:
            kept.append(block)
            continue

        key = (text, block.href)
        previous = seen.get(key)
        if previous is None:
            seen[key] = len(kept)
            kept.append(block)
            continue

        # A later copy that was measured replaces an earlier one that was not.
        if block.rect is not None and kept[previous].rect is None:
            kept[previous] = block

    return kept


def _attach_geometry(blocks: list[Block], geometry: dict[str, Rect]) -> list[Block]:
    """Bind measured rectangles to blocks by XPath.

    Blocks with no measurement keep `rect=None`, which forces the whole document to DOM
    order -- mixing measured and assumed positions produces an ordering that is neither.
    """
    return [
        block.model_copy(update={"rect": geometry[block.xpath]})
        if block.xpath in geometry
        else block
        for block in blocks
    ]
