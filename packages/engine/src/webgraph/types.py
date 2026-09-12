"""Core value types shared across the extraction pipeline.

Every piece of extracted content carries provenance. This is not optional bookkeeping:
it is what lets a downstream consumer cite a fact, decide which of two conflicting
values to trust, and refuse to let a low-confidence modality overwrite a high-confidence
one (see MEMORY.md D7).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Modality(StrEnum):
    """How the content reached us.

    Ordered loosely by trustworthiness. `TEXT` and `DOM_JSON` are read directly from
    markup and are exact; everything below them is inferred and can be wrong in ways
    that are invisible without the source.
    """

    DOM_JSON = "dom-json"
    """Structured data lifted verbatim from the page (JSON-LD, __NEXT_DATA__, RSC flight)."""

    TEXT = "text"
    """Text nodes read from the rendered or parsed DOM."""

    # Only modalities something constructs are listed. `ocr`, `chart`, `image` and two video
    # modalities were declared for three sessions and produced by nothing; an enum value that
    # appears in the API schema is a claim about capability, and these were false ones. Add a
    # modality in the same change that adds the extractor producing it.


class Extractor(StrEnum):
    """Which mechanism produced the value.

    Used for cost accounting and for the escalation ladder: a value from a cheaper
    extractor should never be re-derived by a more expensive one without cause.
    """

    STRUCTURED_DATA = "structured-data"
    """Zero-cost path: the page handed us the data. Always preferred."""

    LLM = "llm"
    """A language model reading the page text. Not yet built: it is the planned path that
    turns each page into notes, entities and relationships for the graph, and it is declared
    here so `Fact.outranks` already knows where it sits. `selector`, `ensemble` and `vlm`
    were declared alongside it, had no plan, and were removed."""


class Verification(StrEnum):
    """Whether a value is trustworthy enough to trigger an alert or a downstream write."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    """Excluded from change alerts. A visually-inferred number misread twice in a row
    is exactly the phantom alert that drives users away (PRD v3 3.3). Nothing produces it
    yet; the model path will, and the field exists so that path cannot forget to."""


class ReadingOrderMethod(StrEnum):
    """How the block sequence was determined. Recorded so consumers know the confidence.

    `DOM_FALLBACK` means we had no geometry and assumed source order equals visual order.
    That assumption is wrong on any page using CSS reordering (MEMORY.md D10).

    `GEOMETRIC_ANCHORED` means most blocks were measured and the rest -- collapsed
    `<details>`, panels behind a disclosure, anything with zero height -- were placed next to
    their DOM neighbours. Distinct from `GEOMETRIC_XY_CUT` because it is a weaker claim, and
    this engine's rule is that a weaker claim gets a different name rather than the same one.
    """

    GEOMETRIC_XY_CUT = "geometric-xy-cut"
    GEOMETRIC_ANCHORED = "geometric-anchored"
    DOM_FALLBACK = "dom-fallback"
    SINGLE_BLOCK = "single-block"


class Rect(BaseModel):
    """Axis-aligned bounding box in CSS pixels, page-relative (not viewport-relative)."""

    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return self.width * self.height

    def overlaps_x(self, other: Rect, tolerance: float = 0.0) -> bool:
        """True when the two rects share horizontal extent (i.e. sit in the same column band)."""
        return self.x < other.right + tolerance and other.x < self.right + tolerance

    def overlaps_y(self, other: Rect, tolerance: float = 0.0) -> bool:
        """True when the two rects share vertical extent (i.e. sit on the same row band)."""
        return self.y < other.bottom + tolerance and other.y < self.bottom + tolerance


class BlockKind(StrEnum):
    """What a block *is*, so structure survives extraction.

    Text-only extraction discards the difference between a heading and a paragraph, drops
    images entirely, and flattens a table into loose cells. Keeping the kind is what allows
    faithful Markdown output rather than a wall of sentences.
    """

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list-item"
    TABLE = "table"
    IMAGE = "image"
    CODE = "code"
    QUOTE = "quote"
    FIGURE_CAPTION = "figure-caption"

    MEDIA = "media"
    """A video, audio player or embed that is present on the page but not transcribed.

    Carries no content of its own -- the point is that something *was* there. `SKIP_TAGS`
    strips `<video>`, `<audio>` and `<iframe>` before extraction, so a YouTube embed used to
    vanish without trace and a reader of the output could not tell whether a page had one.
    A downstream consumer building notes or a knowledge graph needs to know the difference
    between "this page has no video" and "this page has a video nobody transcribed", and
    only the second one is worth coming back to.

    `href` is the media source, `alt` its title where the markup gives one, and `text` a
    sentence saying plainly that it was not transcribed."""


class Block(BaseModel):
    """A contiguous run of text with its position in the document.

    A block is the unit of reading order. Splitting too finely (per word) makes ordering
    noisy; too coarsely (per section) hides column structure. Element-level granularity
    for text-bearing elements is the working compromise.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    tag: str
    """Lowercased HTML tag name, e.g. `p`, `h2`, `li`."""

    xpath: str
    """Absolute XPath to the source element. The provenance anchor -- lets a consumer
    re-find this exact node on a later crawl, and is the key a selector cache is built on."""

    dom_index: int
    """Position in document source order. Preserved so DOM order stays recoverable even
    after geometric reordering, and so the two can be compared to detect CSS reordering."""

    rect: Rect | None = None
    """Absent for static (non-rendered) parses. Its absence forces DOM_FALLBACK ordering."""

    depth: int = 0

    kind: BlockKind = BlockKind.PARAGRAPH
    level: int = 0
    """Heading level (1-6), or list nesting depth. Zero when not applicable."""

    href: str | None = None
    """Absolute URL: an image's source, or a standalone link's target."""

    alt: str | None = None
    ordered: bool = False
    """True for numbered list items."""

    rows: tuple[tuple[str, ...], ...] = ()
    """Table cells, first row treated as the header."""

    table_html: str | None = None
    """The table's own markup, cleaned, for a table whose structure Markdown cannot express.

    Present only when the table nests another table or carries a `colspan`/`rowspan` greater
    than one. A pipe table has no way to say that one cell spans three columns, so rendering
    such a table as pipes silently discards the merge and every value beneath it shifts into
    the wrong column. Markdown allows inline HTML, so the honest rendering is the table's own
    markup; a simple grid still renders as pipes, which is what a reader wants to see.

    Cleaned, not raw: only `colspan` and `rowspan` survive, and only table tags plus `sub`
    and `sup`. Everything else on a real page's table -- style attributes, tracking ids,
    translation-tool bookkeeping -- is noise that would land in the output verbatim."""

    language: str | None = None
    """Code-block language, when the markup declares one."""

    region: str | None = None
    """The innermost landmark this block sits in -- `main`, `nav`, `header`, `footer` or
    `aside` -- read from the element's ancestors by tag *or* ARIA role (`role="main"`,
    `navigation`, `banner`, `contentinfo`, `complementary`). None outside any landmark.

    The XPath cannot carry this: `role="main"` on a `<div>` is invisible in
    `/html/body/div[2]/div`, and measured on WCXB dev 178 of 1,476 pages declare their main
    content that way and no other. The page's own statement of what is what is the
    strongest structural signal there is, and it was being read from the tag name only."""

    widget: str | None = None
    """The interactive panel this block sits in, when its markup names one: `filter` for a
    faceted-search panel (an ancestor whose class or id says filter/facet/refine, or a
    fieldset of checkboxes), `consent` for a cookie-consent dialog (OneTrust, Cookiebot,
    Didomi, TrustArc, Sourcepoint, or a hand-rolled `cookie-banner`). Filters are the one kind of chrome that lives *inside* `main`
    on a collection page and is link-dense by design, so no density rule can find it; the
    markup names it, and this records the name. None elsewhere."""

    float_of: str | None = None
    """XPath of the outermost floated ancestor, when the renderer measured one. Everything
    sharing a value sits in one float -- a thumbnail and its caption, an infobox -- and is
    read as one thing rather than zipped line by line with the text wrapping around it."""

    in_main: bool = False
    """Whether any ancestor is a `main` landmark. Distinct from `region`, because a `<nav>`
    inside `<main>` -- an in-page table of contents -- is both inside the main content and
    navigation, and the two questions have different answers."""

    rich_text: str | None = None
    """Inline Markdown for this block: links, emphasis and inline code preserved.

    Deliberately separate from `text`. Deduplication, the content hash and reading order all
    key on the plain form, and folding Markdown syntax into it would change every hash and
    make two renderings of the same sentence look like different content."""

    def with_text(self, text: str) -> Block:
        return self.model_copy(update={"text": text})


class Provenance(BaseModel):
    """Where a value came from and how much to trust it."""

    model_config = ConfigDict(frozen=True)

    source_url: str
    extractor: Extractor
    modality: Modality
    confidence: float = Field(ge=0.0, le=1.0)
    verification: Verification = Verification.VERIFIED
    source_xpath: str | None = None
    source_span: tuple[int, int] | None = None
    """Character offsets into the block text, when the value is a substring of it."""

    extracted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    note: str | None = None


class Fact(BaseModel):
    """A single extracted value, addressed by its path within the target schema."""

    model_config = ConfigDict(frozen=True)

    path: str
    """Dotted path into the user's JSON Schema, e.g. `plans.0.price_amount`."""

    value: Any
    provenance: Provenance

    def outranks(self, other: Fact) -> bool:
        """Whether this fact should win a conflict against `other`.

        Ordering rule (D7): a structured-data value always beats an inferred one,
        regardless of confidence, because the former is read verbatim from the page
        and the latter is a guess. Within the same extractor tier, higher confidence wins.
        """
        rank = {
            Extractor.STRUCTURED_DATA: 1,
            Extractor.LLM: 0,
        }
        mine = rank[self.provenance.extractor]
        theirs = rank[other.provenance.extractor]
        if mine != theirs:
            return mine > theirs
        return self.provenance.confidence > other.provenance.confidence


class MarkupStats(BaseModel):
    """What the markup is made of, counted once at build time.

    The router reads these. They are the signals a page's authors left in the DOM without
    meaning to -- how many `<input>`s, whether a `rel="next"` exists, how often the words
    "card", "price", "reply" or "pricing" appear in class names -- and, measured out of
    fold on 1,497 labelled pages, they are worth 2.9 points of accuracy and 4.2 of macro-F1
    over the block-level features alone.

    Kept on the Document rather than recomputed because the crawl drops the HTML once links
    are read, and a router that needs the markup would be a router that cannot run on a
    crawled page. A few dozen floats survive; two megabytes of HTML do not.
    """

    model_config = ConfigDict(frozen=True)

    elements: int = 0
    """Element count, the denominator for every rate below."""

    class_tokens: int = 0
    """Distinct tokens across every `class` attribute."""

    class_hits: dict[str, float] = Field(default_factory=dict)
    """Per-bucket hits per 100 elements: `card`, `grid`, `product`, `post`, `service`,
    `forum`, `docs`, `filter`, `nav`. The bucket vocabularies live in `webgraph.pagetype`."""

    tag_counts: dict[str, int] = Field(default_factory=dict)
    """Counts for the tags the router asks about."""

    rel_next: bool = False
    itemprop_count: int = 0
    data_attr_share: float = 0.0
    """Elements carrying any `data-*` attribute, per 100 elements."""

    generator: str = ""
    """`<meta name="generator">`, as written: "MediaWiki 1.45.0-wmf.20", "WordPress 6.6".
    The platform saying what it is, which is a better witness than any statistic."""

    body_classes: tuple[str, ...] = ()
    """The `<body>` element's class tokens, lowercased, first 40. Platforms state the page's
    kind here -- MediaWiki's `ns-0` is the main namespace, WordPress's `single-post`."""


class StackProfile(BaseModel):
    """Stage 0 output: what the site is built with, and therefore how to read it.

    Accuracy here is an open question (MEMORY.md Q2) -- no external evidence supports
    any particular fingerprinting approach, so this is measured locally rather than trusted.
    """

    model_config = ConfigDict(frozen=True)

    frameworks: tuple[str, ...] = ()
    has_next_data: bool = False
    has_rsc_flight: bool = False
    has_nuxt_payload: bool = False
    has_json_ld: bool = False
    has_microdata: bool = False
    requires_render: bool = False
    """True when the static HTML carries too little text to be the real content."""

    signals: tuple[str, ...] = ()
    """Human-readable reasons for the above, for debugging misroutes."""

    technologies: tuple[dict[str, Any], ...] = ()
    """Detected technologies with category and version, across markup and response headers.
    Stored as plain dicts so the profile stays serialisable without importing the detector."""


class PayloadSource(StrEnum):
    """Where a structured payload was found. Ordered by how reliably it maps to page content."""

    JSON_LD = "json-ld"
    MICRODATA = "microdata"
    OPEN_GRAPH = "open-graph"
    NEXT_DATA = "next-data"
    RSC_FLIGHT = "rsc-flight"
    NUXT = "nuxt"
    INITIAL_STATE = "initial-state"


class StructuredPayload(BaseModel):
    """Machine-readable data the page handed us directly, before any schema mapping.

    This is the zero-cost extraction path: no model call, no selector, no inference.
    When a payload answers the schema, nothing downstream needs to run.
    """

    model_config = ConfigDict(frozen=True)

    source: PayloadSource
    data: Any
    xpath: str | None = None
    note: str | None = None


_NOT_TEXT: frozenset[BlockKind] = frozenset({BlockKind.IMAGE, BlockKind.MEDIA})
"""Block kinds whose `text` is not page text: alt text and placeholders."""


def blocks_text(blocks: Iterable[Block]) -> str:
    """The plain text of `blocks` in their order -- `Document.text`, for any block list.

    The benchmark runners join through this too, so a variant differs from the shipped
    text only by which blocks survive, never by how they are joined.
    """
    return "\n\n".join(b.text for b in blocks if b.text.strip() and b.kind not in _NOT_TEXT)


class Document(BaseModel):
    """A fetched and parsed page, ready for extraction."""

    model_config = ConfigDict(frozen=True)

    url: str
    html: str = ""
    """The markup this document was built from. Empty on documents a crawl has finished
    with: the crawler reads it once, for links, and then drops it, because it is the largest
    field by an order of magnitude and nothing downstream of link extraction needs it. A
    document built directly by `build_document` always carries it."""

    blocks: tuple[Block, ...]
    """In reading order -- see `reading_order_method` for how that was established."""

    title: str = ""
    """The `<title>` element's text, whitespace-folded. Empty when the page has none.

    Captured at build time because it lives in `<head>`, which block extraction never
    visits, and because the crawl drops `html` once links are read. Two things depend on
    it: the router, for which the page's own name is evidence about its type, and content
    selection, which must never cut the block that *is* the title."""

    description: str = ""
    """`<meta name="description">`, or the Open Graph description when that is absent."""

    markup: MarkupStats = Field(default_factory=MarkupStats)
    """Counts over the markup, for the router. See `MarkupStats`."""

    reading_order_method: ReadingOrderMethod
    profile: StackProfile
    structured_data: tuple[StructuredPayload, ...] = ()
    """Raw payloads from the zero-cost path, before any schema mapping."""

    content_hash: str = ""
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def text(self) -> str:
        """Full document text in reading order: what a reader reads.

        Image alt text and media placeholders are not in it. An image block's `text` is its
        alt -- kept so the Markdown can carry it -- and a `[Media not transcribed.]`
        placeholder is a note from this engine, not a sentence from the page. Measured on
        WCXB dev, ikea.com's bookcase category emitted 613 words of alt text ("A tall, white
        BILLY bookshelf with multiple shelves, suitable for...") that no reader saw as
        text and no annotator marked.
        """
        return blocks_text(self.blocks)

    @property
    def dom_order_differs(self) -> bool:
        """True when geometric reading order diverged from source order.

        This is the signal that the page uses CSS reordering, and therefore that a
        naive DOM walk would have produced jumbled output.
        """
        return [b.dom_index for b in self.blocks] != sorted(b.dom_index for b in self.blocks)
