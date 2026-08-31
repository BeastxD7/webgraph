"""Assemble a `Document` from raw HTML.

Stage order here is deliberate and load-bearing:

1. **Payloads first.** Structured data lives in `<script>` tags, and block extraction
   strips those from the tree. Reading payloads after block extraction silently returns
   nothing -- so the two run against separate parses of the same source.
2. **Blocks**, from a clean parse.
3. **Geometry**, attached by XPath when a render supplied it.
4. **Reading order**, which needs the geometry to do better than source order.
5. **Content hash**, computed over reading-ordered text rather than raw HTML, so that
   cosmetic markup churn (build hashes, analytics tokens, reordered attributes) does not
   read as a content change. This is the gate that stops needless re-extraction.
"""

from __future__ import annotations

import hashlib

from webgraph.dom.blocks import parse_html
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
    rtl: bool = False,
    ordering: OrderingConfig | None = None,
    min_block_chars: int = 1,
    headers: dict[str, str] | None = None,
    runtime: RuntimeEvidence | None = None,
) -> Document:
    """Parse `html` into a `Document` with blocks in reading order.

    `geometry` maps XPath to bounding box, as produced by a rendered fetch. Without it the
    document falls back to DOM order and says so via `reading_order_method`.
    """
    payload_tree = parse_html(html)
    payloads = extract_payloads(payload_tree, html)

    # Second parse: extract_blocks strips <script>/<style> from the tree it is given.
    block_tree = parse_html(html)
    blocks = extract_rich_blocks(block_tree, url, min_chars=min_block_chars)

    if geometry:
        blocks = _attach_geometry(blocks, geometry)

    ordered, method = order_blocks(list(blocks), rtl=rtl, config=ordering)

    text = "\n\n".join(b.text for b in ordered if b.text.strip())
    profile = profile_page(
        payload_tree,
        html,
        text_length=len(text),
        headers=headers,
        runtime=runtime,
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
