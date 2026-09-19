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
from typing import TYPE_CHECKING, Final

from webgraph import config
from webgraph.dom.blocks import is_rtl_document, parse_html
from webgraph.dom.markup_stats import markup_stats
from webgraph.dom.reading_order import OrderingConfig, order_blocks
from webgraph.dom.rich import extract_rich_blocks
from webgraph.profile.fingerprint import profile_page
from webgraph.profile.technology import RuntimeEvidence
from webgraph.structured.payloads import extract_payloads
from webgraph.types import STRUCTURE_ONLY, Block, BlockKind, Document, Rect

if TYPE_CHECKING:
    from lxml.html import HtmlElement

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
    include_hidden_text: bool = False,
) -> Document:
    """Parse `html` into a `Document` with blocks in reading order.

    `include_hidden_text` keeps the text a browser holds but a sighted reader never sees
    -- screen-reader-only labels, skip links, wiki edit controls. Off by default: they are
    labels for controls, not content. See `dom.blocks.strip_permalinks`.

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
    blocks = extract_rich_blocks(
        block_tree, url, min_chars=min_block_chars, include_hidden_text=include_hidden_text
    )

    if geometry:
        blocks = _attach_geometry(blocks, geometry)
        # A rule the browser gave no box -- `hr { height: 0; border: 0 }`, a stylesheet's
        # way of removing one -- is not a line the reader sees, and an unmeasured block
        # would also turn the page's reading order from measured into anchored. A frame
        # the browser gave no box is a beacon: Shopify mounts its web-pixel sandboxes as
        # 0x0 `<iframe>`s (six on an allbirds.com product page, each a "media not
        # transcribed" line), the measured form of the 1x1 rule in `_media_block`.
        blocks = [b for b in blocks if b.rect is not None or b.kind not in _NEEDS_A_BOX]

    ordered, method = order_blocks(list(blocks), rtl=rtl, config=ordering)
    ordered = _deduplicate(ordered)
    ordered = _drop_restated_wholes(ordered)

    text = "\n\n".join(b.text for b in ordered if b.text.strip())
    profile = profile_page(
        payload_tree,
        html,
        text_length=len(text),
        headers=headers,
        runtime=runtime,
        url=url,
    )

    title, description = _head_text(payload_tree)
    # Counted on the payload parse, which still has the whole tree; block extraction strips
    # the copy it is given. The router reads these on crawled pages whose HTML is gone.
    markup = markup_stats(payload_tree)

    return Document(
        url=url,
        html=html,
        title=title,
        description=description,
        markup=markup,
        blocks=tuple(ordered),
        reading_order_method=method,
        profile=profile,
        structured_data=payloads,
        content_hash=content_hash_of(text),
    )


def _head_text(root: HtmlElement) -> tuple[str, str]:
    """The page's own name and summary, from `<head>`.

    Read before block extraction strips the tree, and folded to single spaces. The
    description prefers `<meta name="description">` and falls back to Open Graph: the former
    is written for search results and the latter for share cards, and when both exist the
    former is the one an author meant as the summary.
    """
    title = " ".join(root.xpath("string(//title)").split())
    description = ""
    for xpath in (
        "//meta[@name='description']/@content",
        "//meta[@property='og:description']/@content",
        "//meta[@name='twitter:description']/@content",
    ):
        for value in root.xpath(xpath):
            text = " ".join(str(value).split())
            if text:
                description = text
                break
        if description:
            break
    return title, description


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
    keep. **Unless the later copy is the real one.** A page's `<h1>` is also the current
    item in its own sidebar, and the sidebar is read first, so keeping the first occurrence
    kept a navigation list item and dropped the page's title. Measured on docs.python.org:
    every module page lost its heading this way. When the later copy is a heading and the
    earlier is not, or sits in the main content while the earlier sits in navigation, the
    later copy stays where it is and the earlier one goes.

    **A page that says something twice is not a duplicate of itself.** Two copies the
    browser drew in two places were already kept; two copies nobody measured -- a static
    fetch, a page whose browser fetch was refused -- were not, so columbia.edu/~fdc/sample.html,
    which shows one demo table four times with four border styles, came out with one, and a
    heading a page repeats on purpose came out once. What tells a repeat from a hidden
    twin without a measurement is its company: a hidden layout copies a *run* -- the
    mobile grid beside the desktop grid, the second navigation beside the first -- so a
    repeated block whose neighbour also repeats the earlier copy's neighbour is a layout
    copy and goes, while a repeated block standing among different neighbours is the
    page repeating itself and stays. A run is any two adjacent repeats of two adjacent
    blocks; a repeat straight after its earlier copy, with nothing between, is the two
    readings of one line (static and rendered, "Karri·2min ago" / "Karri · 2min ago")
    and goes. Only a table or a code block is judged this way -- see `_substantial` for
    the measurement that keeps repeated text under the old rule.
    """
    seen: dict[tuple[str, str | None], int] = {}
    kept: list[Block | None] = []
    # For the run test: each input index's key, and the input index of the first block
    # with that key -- over *every* block, dropped ones included, since a twin run's
    # text neighbours are dropped before its table is judged.
    keys: list[str] = []
    first_at: dict[str, int] = {}
    # Unmeasured structural repeats, decided once every neighbour is known:
    # (position in `kept`, input index, input index of the first copy).
    pending: list[tuple[int, int, int]] = []

    for index, block in enumerate(blocks):
        # Whitespace is dropped from the key, not normalised: the same words with a
        # missing space between two inline spans are the same block -- see `resolve._key`.
        text = "".join(block.text.split()).casefold()
        keys.append(text)
        first_at.setdefault(text, index)
        if not text:
            kept.append(block)
            continue

        key = (text, block.href)
        previous = seen.get(key)
        if previous is None:
            seen[key] = len(kept)
            kept.append(block)
            continue

        earlier = kept[previous]
        if earlier is None:
            continue
        # Two copies the browser drew in two different places are two things. A product
        # grid says "$100" under six cards and "Men's Tree Runner NZ" over three; the
        # duplicate rule is for hidden twins -- the mobile layout beside the desktop one --
        # and a hidden twin has no rectangle. Measured on allbirds.com: 15 of 26 prices and
        # half the product names were being dropped as repeats.
        if (
            block.rect is not None
            and earlier.rect is not None
            and (block.rect.x, block.rect.y) != (earlier.rect.x, earlier.rect.y)
        ):
            seen[key] = len(kept)
            kept.append(block)
            continue
        if _outranks(block, earlier):
            # The later copy is the page's own; the earlier was its echo in the chrome.
            kept[previous] = None
            seen[key] = len(kept)
            kept.append(block)
        elif block.rect is not None and earlier.rect is None:
            # A later copy that was measured wins over an earlier one that was not -- and
            # it wins *where it was drawn*. Moving it up into the unmeasured copy's slot
            # put python.org's whole footer column ("Applications", "Quotes", "Help")
            # inside the header, because the header's hidden dropdown lists the same
            # links; the reader meets those words at the foot of the page, not the top.
            kept[previous] = None
            seen[key] = len(kept)
            kept.append(block)
        elif block.rect is None and earlier.rect is None and _substantial(block):
            # Neither copy measured: kept for now, decided below by its neighbours.
            pending.append((len(kept), index, first_at[text]))
            kept.append(block)

    for position, index, first in pending:
        if index == first + 1 or _in_repeated_run(keys, first_at, index, first):
            kept[position] = None

    return [block for block in kept if block is not None]


def _substantial(block: Block) -> bool:
    """A repeat worth judging by its neighbours: a table or a code block. Repeated *text*
    on a page nobody measured is a hidden layout copy far more often than the page
    repeating itself -- measured on WCXB and Zyte, keeping repeated prose and headings by
    the neighbour rule cost 0.0017 and 0.003 overall, with businessinsider.com (the
    article three times over, interleaved with different furniture) at 0.998 -> 0.471 --
    so text goes as before, however long. A demo table shown four ways, a code sample
    shown before and after, are structure a page repeats on purpose."""
    return block.kind in _STRUCTURAL_REPEATS


def _in_repeated_run(keys: list[str], first_at: dict[str, int], index: int, first: int) -> bool:
    """Whether the repeat at input `index` sits in a run that repeats the run around its
    first copy at `first`: the block before it is a repeat of the block before the first
    copy, or the block after it a repeat of the block after. Hidden layouts copy runs; a
    page repeating one thing does not. Judged on the input sequence, dropped blocks
    included, since a twin run's text neighbours are dropped before its table is judged."""

    def repeats(a: int, b: int) -> bool:
        if not (0 <= a < len(keys) and 0 <= b < len(keys)):
            return False
        return bool(keys[a]) and keys[a] == keys[b] and first_at[keys[a]] == b

    return repeats(index - 1, first - 1) or repeats(index + 1, first + 1)


_STRUCTURAL_REPEATS: Final[frozenset[BlockKind]] = frozenset({BlockKind.TABLE, BlockKind.CODE})


_RESTATED_SHINGLE: Final[int] = 6


def _drop_restated_wholes(blocks: list[Block]) -> list[Block]:
    """Drop a long block that restates what several other blocks already say.

    businessinsider.de carries the article twice: as paragraphs, and again as one
    1,571-word run of text inside a microdata `articleBody` div. Exact-text dedup cannot
    see it -- the whole is equal to no single paragraph -- so the article was emitted
    twice and precision halved. A block of `PIPELINE_RESTATED_MIN_WORDS` or more whose six-word
    shingles are `PIPELINE_RESTATED_SHARE` already present in the *other* blocks is the restated
    whole, and the paragraphs, which carry the structure, are kept instead.

    The coverage has to be spread: no single other block may supply more than
    `PIPELINE_RESTATED_SINGLE_MAX` of it. Two blocks that nearly repeat each other are content --
    react.dev shows the same component three times as the tutorial builds it, stripe.com's
    API reference shows a request and its response, a pricing page has two plan tables --
    and only the whole-stitched-from-parts shape is the duplicate.
    """
    long_ones = [
        i for i, b in enumerate(blocks) if len(b.text.split()) >= config.PIPELINE_RESTATED_MIN_WORDS
    ]
    if not long_ones:
        return blocks
    shingles = [_shingles(b.text) if len(b.text.split()) >= 4 else set() for b in blocks]
    drop: set[int] = set()
    for i in long_ones:
        own = shingles[i]
        if not own:
            continue
        others: set[tuple[str, ...]] = set()
        single = 0
        for j, sh in enumerate(shingles):
            if j != i and j not in drop:
                others |= sh
                single = max(single, len(own & sh))
        if (
            len(own & others) / len(own) >= config.PIPELINE_RESTATED_SHARE
            and single / len(own) < config.PIPELINE_RESTATED_SINGLE_MAX
        ):
            drop.add(i)
    return [b for i, b in enumerate(blocks) if i not in drop] if drop else blocks


def _shingles(text: str) -> set[tuple[str, ...]]:
    tokens = text.lower().split()
    n = _RESTATED_SHINGLE
    return {tuple(tokens[k : k + n]) for k in range(max(0, len(tokens) - n + 1))}


_CHROME_REGIONS: frozenset[str] = frozenset({"nav", "header", "footer", "aside"})


def _outranks(later: Block, earlier: Block) -> bool:
    """Whether a repeated block is the page's own copy rather than the chrome's echo."""
    if later.kind is BlockKind.HEADING and earlier.kind is not BlockKind.HEADING:
        return True
    later_chrome = (later.region or "") in _CHROME_REGIONS
    earlier_chrome = (earlier.region or "") in _CHROME_REGIONS
    return (later.in_main or not later_chrome) and earlier_chrome and not later_chrome


_NEEDS_A_BOX = STRUCTURE_ONLY | {BlockKind.MEDIA}
"""Kinds that are nothing without a box on a measured page: a rule and an embedded frame."""


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
