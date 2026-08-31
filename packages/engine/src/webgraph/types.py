"""Core value types shared across the extraction pipeline.

Every piece of extracted content carries provenance. This is not optional bookkeeping:
it is what lets a downstream consumer cite a fact, decide which of two conflicting
values to trust, and refuse to let a low-confidence modality overwrite a high-confidence
one (see MEMORY.md D7).
"""

from __future__ import annotations

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

    OCR = "ocr"
    IMAGE = "image"
    CHART = "chart"
    VIDEO_TRANSCRIPT = "video-transcript"
    VIDEO_FRAME = "video-frame"


class Extractor(StrEnum):
    """Which mechanism produced the value.

    Used for cost accounting and for the escalation ladder: a value from a cheaper
    extractor should never be re-derived by a more expensive one without cause.
    """

    STRUCTURED_DATA = "structured-data"
    """Zero-cost path: the page handed us the data. Always preferred."""

    SELECTOR = "selector"
    """Cached XPath replay. Zero model cost, but can silently rot -- see D5."""

    LLM = "llm"
    VLM = "vlm"
    ENSEMBLE = "ensemble"


class Verification(StrEnum):
    """Whether a value is trustworthy enough to trigger an alert or a downstream write."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    """Excluded from change alerts. A visually-inferred number misread twice in a row
    is exactly the phantom alert that drives users away (PRD v3 3.3)."""


class ReadingOrderMethod(StrEnum):
    """How the block sequence was determined. Recorded so consumers know the confidence.

    `DOM_FALLBACK` means we had no geometry and assumed source order equals visual order.
    That assumption is wrong on any page using CSS reordering (MEMORY.md D10).
    """

    GEOMETRIC_XY_CUT = "geometric-xy-cut"
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

    language: str | None = None
    """Code-block language, when the markup declares one."""

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
            Extractor.STRUCTURED_DATA: 4,
            Extractor.SELECTOR: 3,
            Extractor.ENSEMBLE: 2,
            Extractor.LLM: 1,
            Extractor.VLM: 0,
        }
        mine = rank[self.provenance.extractor]
        theirs = rank[other.provenance.extractor]
        if mine != theirs:
            return mine > theirs
        return self.provenance.confidence > other.provenance.confidence


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


class Document(BaseModel):
    """A fetched and parsed page, ready for extraction."""

    model_config = ConfigDict(frozen=True)

    url: str
    html: str
    blocks: tuple[Block, ...]
    """In reading order -- see `reading_order_method` for how that was established."""

    reading_order_method: ReadingOrderMethod
    profile: StackProfile
    structured_data: tuple[StructuredPayload, ...] = ()
    """Raw payloads from the zero-cost path, before any schema mapping."""

    content_hash: str = ""
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def text(self) -> str:
        """Full document text in reading order."""
        return "\n\n".join(b.text for b in self.blocks if b.text.strip())

    @property
    def dom_order_differs(self) -> bool:
        """True when geometric reading order diverged from source order.

        This is the signal that the page uses CSS reordering, and therefore that a
        naive DOM walk would have produced jumbled output.
        """
        return [b.dom_index for b in self.blocks] != sorted(b.dom_index for b in self.blocks)
