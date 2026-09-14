"""Complete-content page resolution: fetch both ways, keep everything.

Why this module exists
----------------------
Measured against 24 real sites, two things turned out to be true at once:

1. **You cannot predict partial content loss.** Heuristics catch the catastrophic cases --
   a page with zero text is obviously a shell -- but they cannot catch `angular.dev` at 68%
   or `notion.com` at 82%. A page holding 2,078 characters carries no signal that another
   969 appear after hydration. There is nothing left to tune.

2. **Rendering is not a strict upgrade.** `bbc.co.uk/news` yields 19,908 characters
   statically and 9,279 rendered, because a consent wall replaces the article. Choosing the
   rendered document would have thrown away half the page.

Together those rule out picking a side. If the requirement is to lose nothing, the only
sound strategy is to obtain both representations and **union** them, then report how much
each contributed so the completeness claim is a measurement rather than an assertion.

Cost note
---------
`UNION` costs one extra fetch plus a browser render. That is the price of completeness and
it is charged deliberately. `STATIC_ONLY` remains available for bulk crawling where the
budget matters more than the last few percent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from webgraph import config
from webgraph.fetch.render import (
    PLAYWRIGHT_AVAILABLE,
    HiddenMatter,
    RenderConfig,
    RenderResult,
    geometry_by_xpath,
    hidden_matter,
    render_page,
)
from webgraph.fetch.static import FetchConfig, FetchResult, fetch_static
from webgraph.pipeline import build_document
from webgraph.profile.technology import RuntimeEvidence
from webgraph.types import Block, BlockKind, Document, ReadingOrderMethod

MISSING_STATUSES = config.MISSING_STATUSES
BLOCKING_STATUSES = config.BLOCKING_STATUSES
MAX_BLOCK_PAGE_CHARS = config.MAX_BLOCK_PAGE_CHARS
MIN_PAGE_BESIDE_WALL_WORDS = config.MIN_PAGE_BESIDE_WALL_WORDS

__all__ = [
    "MISSING_STATUSES",
    "PageBlockedError",
    "PageMissingError",
    "ResolvedPage",
    "Strategy",
    "block_page_evidence",
    "challenge_vendor",
    "resolve_page",
    "union_documents",
]


class Strategy(StrEnum):
    STATIC_ONLY = "static-only"
    """Cheap path. Used when rendering is unavailable or explicitly disabled."""

    RENDERED_ONLY = "rendered-only"
    """The browser's document alone. Reported when the static fetch failed or returned
    nothing usable; requestable when the static HTML is known to be a decoy."""

    UNION = "union"
    """Both representations obtained and merged. The completeness path."""

class PageMissingError(Exception):
    """Raised when a URL does not exist. Distinct from a transport failure."""

    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"HTTP {status}: page does not exist")
        self.url = url
        self.status = status

class PageBlockedError(ValueError):
    """The server answered, but with a wall instead of the page.

    A subclass of ValueError so that every existing "could not resolve" handler treats it
    as the failure it is. It exists as its own type because it is the one failure that used
    to be reported as success: Reddit's "You've been blocked by network security" came back
    as three blocks, typed `listing` at 86% confidence, with a green tick.
    """

    def __init__(self, url: str, evidence: str, *, challenge: str | None = None) -> None:
        if challenge:
            message = (
                f"could not resolve {url}: the site answered with a {challenge} bot challenge "
                "-- a script a browser must run before the page is served -- and no page"
            )
        else:
            message = (
                f"could not resolve {url}: the site served a block page instead of the "
                f'content; it said: "{evidence}"'
            )
        super().__init__(message)
        self.url = url
        self.evidence = evidence
        self.challenge = challenge


_BLOCK_PAGE_PHRASES: Final[re.Pattern[str]] = re.compile(
    r"(you(?:'ve| have) been blocked|access denied|access to this page has been denied"
    r"|verify (?:that )?you are (?:not a robot|a human|human)|are you a robot"
    r"|unusual traffic from your|enable javascript and cookies|just a moment\.\.\."
    r"|attention required!|blocked by network security|checking your browser"
    r"|complete the security check|security check to access|bot detection|pardon our interruption"
    r"|request blocked|automated access to|please enable cookies|ray id:)",
    re.IGNORECASE,
)
"""How CDNs and bot-management products phrase a refusal. Only consulted on a page too short
to be anything else; a real article *about* Cloudflare is thousands of characters long."""

_CHALLENGE_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("awswafcookie", "AWS WAF"),
    ("awswaf", "AWS WAF"),
    ("gokuprops", "AWS WAF"),
    ("cf-chl", "Cloudflare"),
    ("__cf_chl", "Cloudflare"),
    ("challenge-platform", "Cloudflare"),
    ("_incapsula_resource", "Imperva Incapsula"),
    ("datadome", "DataDome"),
    ("_pxhd", "PerimeterX"),
    ("px-captcha", "PerimeterX"),
    ("distil_r_", "Distil"),
    ("akam/13", "Akamai Bot Manager"),
    ("bm-verify", "Akamai Bot Manager"),
    ("kasada", "Kasada"),
    ("geo.captcha-delivery", "DataDome"),
)
"""Fingerprints of a JavaScript bot challenge, in the markup rather than the text.

A challenge page has no visible words at all -- it is a `<script>` that sets a cookie and
reloads -- so the phrase test above never fires on it. Amazon's is HTTP 202 with two
kilobytes of `window.awsWafCookie`, and it used to come back as a successful extraction
of zero blocks, typed `service` at 75% confidence."""


def challenge_vendor(html: str) -> str | None:
    """Which bot-management product wrote this markup, if one did."""
    lowered = html.lower()
    for marker, vendor in _CHALLENGE_MARKERS:
        if marker in lowered:
            return vendor
    return None


def block_page_evidence(text: str) -> str | None:
    """The phrase that gives a block page away, or None for a page that is one.

    Two conditions, both required: the page is short, and it says one of the things a wall
    says. Either alone is wrong -- short pages exist, and long pages mention captchas -- but
    a short page whose text is "verify you are human" is not a short page about verifying
    humans.
    """
    flat = _WHITESPACE.sub(" ", text).strip()
    if not flat or len(flat) > MAX_BLOCK_PAGE_CHARS:
        return None
    match = _BLOCK_PAGE_PHRASES.search(flat)
    if match is None:
        return None
    start = max(0, match.start() - 40)
    return flat[start : match.end() + 60].strip()


_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ResolvedPage:
    """A page resolved as completely as the configured strategy allows."""

    url: str
    document: Document
    strategy: Strategy

    static_chars: int
    rendered_chars: int
    union_chars: int

    blocks_only_in_static: int
    blocks_only_in_rendered: int
    render_error: str | None = None

    runtime: RuntimeEvidence = field(default_factory=RuntimeEvidence)
    """What the browser observed, kept so a caller can add to it.

    Site analysis augments this with the page's bundle source, which is too expensive to
    fetch per page but worth fetching once per site."""

    @property
    def static_coverage(self) -> float:
        """Share of the final content the static fetch alone would have given you.

        Clamped to 1.0. The raw ratio can exceed it because the union deduplicates repeated
        blocks: a page that renders the same navigation three times contributes those
        characters three times to `static_chars` but once to the union. The clamp keeps the
        number readable as "how much would I have had", which is the question it answers.
        """
        return min(self.static_chars / self.union_chars, 1.0) if self.union_chars else 0.0

    @property
    def rendered_coverage(self) -> float:
        """Share of the final content a render alone would have given you. Clamped to 1.0."""
        return min(self.rendered_chars / self.union_chars, 1.0) if self.union_chars else 0.0

    @property
    def render_added_content(self) -> bool:
        return self.blocks_only_in_rendered > 0

    @property
    def render_lost_content(self) -> bool:
        """True when the rendered page dropped content the static HTML had.

        Consent walls, paywalls and lazy-unmounted sections all cause this. It is the reason
        the rendered document cannot simply replace the static one.
        """
        return self.blocks_only_in_static > 0

    def summary(self) -> str:
        return (
            f"{self.strategy.value}: {self.union_chars} chars "
            f"(static {self.static_coverage:.0%}, rendered {self.rendered_coverage:.0%}, "
            f"+{self.blocks_only_in_rendered} render-only blocks, "
            f"+{self.blocks_only_in_static} static-only blocks)"
        )


_RUN_IN_MIN_CHARS: Final[int] = 20
_HIDDEN_MIN_CHARS: Final[int] = 12


def _key(block: Block) -> str:
    """Identity for deduplication: normalised text.

    Text rather than XPath, because the two representations of a page rarely agree on
    structure -- hydration rewrites the tree -- but the words themselves are stable.

    Whitespace is dropped altogether, not normalised. The two representations disagree
    about spaces as well as structure: a rendered block knows a `<span>` was laid out as a
    line of its own and breaks there, the static one runs it into the next -- linear.app's
    "New Loops →" and "NewLoops →", "Karri · 2min ago" and "Karri·2min ago" -- and with
    spaces in the key both spellings survived the union.
    """
    return _WHITESPACE.sub("", block.text).casefold()


def union_documents(
    static_doc: Document, rendered_doc: Document, *, hidden: HiddenMatter | None = None
) -> tuple[Document, int, int]:
    """Merge two representations of one page, losing nothing.

    The rendered document leads, because its reading order is measured rather than assumed.
    The question is what to do with blocks that exist only in the static one -- they carry no
    geometry, since the browser never laid them out.

    An earlier version appended them all at the end, reasoning that guessing a position would
    corrupt the ordering the render was performed to get right. That is true of guessing, and
    the ordering it produced was still wrong: on `lemonde.fr` the static document contributes
    over two thousand blocks that the rendered one lacks, and every one of them landed after
    the article instead of inside it.

    They are now placed by **observed adjacency**, not by guesswork. A static-only block is
    inserted after the nearest preceding block that appears in *both* documents. That is the
    same principle as anchoring unmeasured blocks within one document, and it is sound across
    two different DOM trees because the anchor is a block both trees actually contain.

    The merged document is relabelled to match. Copying the rendered document's
    `reading_order_method` claimed geometry for a merge that was partly source order --
    `lemonde.fr` reported `geometric-anchored` with 7% of its blocks measured.

    A repeated anchor is the subtle case. Identity here is normalised text, so a phrase that
    appears twice in the rendered document is one key with two positions. The run belongs at
    one of them -- the last, which is the one nearest the content -- and emitting it at both
    duplicates the content outright. Both halves of that were wrong before they were
    measured; see the comment on `last_occurrence` for the numbers.

    `hidden` is what the browser laid out and hid (`fetch.render.hidden_matter`). A
    static-only block found in it is not something the render lost; it is something the
    render *hid*, and it stays out. php.net's manual TOC -- `nav#trick`, a hundred links
    under `display: none` -- was dropped from the rendered document by the renderer's own
    mark and put straight back by this merge from the static one; same for cppreference's
    hover menus (103 and 128 static-only blocks, every one of them invisible). A hidden
    line is matched exactly, however short; a block spanning several hidden nodes is
    matched as a substring only past `_HIDDEN_MIN_CHARS`, because "home" is in every menu.

    Returns (merged document, blocks only in static, blocks only in rendered).
    """
    static_keys = {_key(b) for b in static_doc.blocks if b.text.strip()}
    rendered_keys = {_key(b) for b in rendered_doc.blocks if b.text.strip()}

    only_rendered = rendered_keys - static_keys

    # Static-only blocks, grouped by the shared block they follow. `None` means they precede
    # every shared block and belong at the front.
    following: dict[str | None, list[Block]] = {}
    anchor: str | None = None
    emitted: set[str] = set()
    # A static-only block that begins or ends with the whole text of a rendered block is
    # the same block with hidden matter run into it -- a headline followed by its own
    # `display: none` mobile copy, which only the rendered fetch can see and strip -- and
    # it is the dirtier copy of something already there, not something only the static
    # page had. Short rendered keys are excluded from the test: "menu" begins a lot of
    # things.
    long_rendered = tuple(k for k in rendered_keys if len(k) >= _RUN_IN_MIN_CHARS)

    def runs_into_rendered(key: str) -> bool:
        return any(key.startswith(k) or key.endswith(k) for k in long_rendered)

    def hidden_in_render(key: str) -> bool:
        return hidden is not None and hidden.holds(key, min_chars=_HIDDEN_MIN_CHARS)

    only_static = {
        k
        for k in static_keys - rendered_keys
        if not runs_into_rendered(k) and not hidden_in_render(k)
    }

    for block in static_doc.blocks:
        key = _key(block)
        if not key:
            continue
        if key in rendered_keys:
            anchor = key
            continue
        if key in emitted or key not in only_static:
            continue
        emitted.add(key)
        following.setdefault(anchor, []).append(block)

    next_index = max((b.dom_index for b in rendered_doc.blocks), default=-1) + 1

    def adopt(block: Block) -> Block:
        nonlocal next_index
        adopted = block.model_copy(update={"dom_index": next_index, "rect": None})
        next_index += 1
        return adopted

    # Blocks before the first shared one lead, but only when something *is* shared. With no
    # common block there is no observed adjacency anywhere, and the front is as arbitrary a
    # choice as the end -- so they go to the end, which at least keeps the rendered page,
    # the authoritative one, at the top.
    anchored_to_front = bool(rendered_keys & static_keys)
    leading = following.pop(None, []) if anchored_to_front else []

    # An anchor key can occur many times in the rendered document -- "Sport" as a nav link
    # and again as a section heading -- and the run must be emitted exactly once, at exactly
    # one of them.
    #
    # Emitting at every occurrence, which is what an unguarded lookup in the loop below does,
    # physically duplicates content. Measured across 39 real pages: **14 of them** carried
    # 3,113 excess blocks, corriere.it merging to 3,831 blocks against 1,626 expected (+136%)
    # with one static-only block copied **201 times**. That inflates the character counts,
    # changes `content_hash` -- the gate that decides whether a page needs re-extracting --
    # and feeds the same paragraph to the index and the graph over and over.
    #
    # The *last* occurrence, not the first. The anchor was chosen by walking the static
    # document for the nearest preceding shared block, so the occurrence meant is the one
    # closest to the content, not a nav link near the top. Measured on the pages where anchor
    # keys repeat, placement accuracy against the rendered order: **0.50-0.65 anchoring to
    # the first occurrence, 0.88-1.00 anchoring to the last.** Where anchor keys are unique
    # the two are identical by construction.
    last_occurrence: dict[str, int] = {}
    for index, block in enumerate(rendered_doc.blocks):
        key = _key(block)
        if key:
            last_occurrence[key] = index

    merged: list[Block] = [adopt(b) for b in leading]
    for index, block in enumerate(rendered_doc.blocks):
        merged.append(block)
        key = _key(block)
        if key and last_occurrence.get(key) == index:
            merged.extend(adopt(extra) for extra in following.get(key, ()))
    if not anchored_to_front:
        merged.extend(adopt(b) for b in following.get(None, ()))

    # Structured payloads are unioned too: a hydration payload can be present in one
    # representation and absent from the other.
    payloads = list(rendered_doc.structured_data)
    known = {repr(p.data) for p in payloads}
    for payload in static_doc.structured_data:
        if repr(payload.data) not in known:
            payloads.append(payload)
            known.add(repr(payload.data))

    method = rendered_doc.reading_order_method
    if only_static and method is not ReadingOrderMethod.DOM_FALLBACK:
        # Part of this document was positioned by adjacency rather than measured. That is a
        # weaker claim than the rendered document alone could make, and it gets the weaker name.
        method = ReadingOrderMethod.GEOMETRIC_ANCHORED

    document = rendered_doc.model_copy(
        update={
            "blocks": tuple(merged),
            "structured_data": tuple(payloads),
            "reading_order_method": method,
        }
    )
    return document, len(only_static), len(only_rendered)


def runtime_evidence(rendered: RenderResult) -> RuntimeEvidence:
    """Repackage what the browser observed into the shape the fingerprinter consumes."""
    return RuntimeEvidence(
        versions=dict(rendered.globals),
        custom_globals=rendered.custom_globals,
        requests=rendered.requests,
        cookies=dict(rendered.cookies),
    )


_TAGS: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
_RUNS: Final[re.Pattern[str]] = re.compile(r"\s+")


_FRAME: Final[re.Pattern[str]] = re.compile(r"<frame\b[^>]*\bsrc\s*=", re.I)
_MAX_FRAMES: Final[int] = 8
_MAX_FRAME_DEPTH: Final[int] = 2


def _frame_sources(html: str, base_url: str) -> list[str]:
    """The `<frame src>` addresses of a frameset page, in source order, absolute, same host."""
    from urllib.parse import urljoin, urlsplit

    from lxml import html as lxml_html

    try:
        root = lxml_html.fromstring(html)
    except (ValueError, TypeError):
        return []
    host = urlsplit(base_url).netloc
    sources: list[str] = []
    for frame in root.iter("frame"):
        src = (frame.get("src") or "").strip()
        if not src or src.lower().startswith(("javascript:", "about:")):
            continue
        absolute = urljoin(base_url, src)
        parts = urlsplit(absolute)
        if parts.scheme in ("http", "https") and parts.netloc == host and absolute not in sources:
            sources.append(absolute)
        if len(sources) >= _MAX_FRAMES:
            break
    return sources


def _compose_frameset(
    static_result: FetchResult, fetch_config: FetchConfig | None, include_hidden_text: bool, depth: int = 0
) -> Document | None:
    """Read a frameset page as the document a reader sees: its frames, in order.

    cs.cmu.edu/~rgs/alice-table.html (1994) is `<frameset rows="50,*">` with a table of
    contents frame over a text frame and a `<noframes>` body for browsers without them.
    The engine refused it as "a JavaScript shell with no readable text": the top document
    has no words, and the browser's document is the frameset, not the frames.

    Each frame is fetched statically (frames predate the JavaScript that would need a
    render), its links made absolute against its own address, and its `<body>` inlined into
    one document in frameset order under `<section data-frame="...">`; the `<noframes>`
    body stands in only when no frame could be fetched. Nested framesets recurse to `_MAX_FRAME_DEPTH`;
    at most `_MAX_FRAMES` frames are read; only same-host frames are followed. Returns
    None when no frame could be read, so the caller's ordinary refusal applies.
    """
    from lxml import etree
    from lxml import html as lxml_html

    sources = _frame_sources(static_result.html, static_result.url)
    if not sources:
        return None
    parts: list[str] = []
    for source in sources:
        result = fetch_static(source, config=fetch_config)
        if not (result.ok and result.is_html and result.html.strip()):
            continue
        if depth + 1 < _MAX_FRAME_DEPTH and _FRAME.search(result.html):
            nested = _compose_frameset(result, fetch_config, include_hidden_text, depth + 1)
            if nested is not None:
                parts.append(f'<section data-frame="{source}">{nested.html}</section>')
            continue
        try:
            root = lxml_html.document_fromstring(result.html)
        except (ValueError, TypeError):
            continue
        if isinstance(root, lxml_html.HtmlElement):
            root.make_links_absolute(result.url)
        body = root.find("body")
        inner = (
            "".join(etree.tostring(child, encoding="unicode") for child in body)
            if body is not None
            else etree.tostring(root, encoding="unicode")
        )
        parts.append(f'<section data-frame="{source}">{(body.text or "") if body is not None else ""}{inner}</section>')
    fetched = len(parts)
    try:
        top = lxml_html.fromstring(static_result.html)
        noframes = top.find(".//noframes")
        # `<noframes>` is what a browser without frames shows *instead* of the frames:
        # on cs.cmu.edu/~rgs it repeats the title frame and adds a second table of
        # contents that no frame-capable browser draws. It stands in only when no frame
        # could be fetched; a reader of a frameset sees the frames.
        if noframes is not None and not fetched:
            # Browsers parse `<noframes>` as raw text, and so does lxml on most pages: its
            # markup arrives as a string and is parsed here; on the pages where it arrived as
            # elements those are used.
            if len(noframes):
                inner = "".join(etree.tostring(child, encoding="unicode") for child in noframes)
            else:
                inner = noframes.text or ""
            parts.append(f'<section data-frame="noframes">{inner}</section>')
        title = top.findtext(".//title") or ""
    except (ValueError, TypeError):
        title = ""
    if not parts:
        return None
    html = f"<html><head><title>{title}</title></head><body>{''.join(parts)}</body></html>"
    return build_document(html, static_result.url, headers=static_result.headers, include_hidden_text=include_hidden_text)


def _server_said(html: str, limit: int = 140) -> str:
    """The server's own words, when it bothered to write any. Quoted, never paraphrased."""
    text = _RUNS.sub(" ", _TAGS.sub(" ", html)).strip()
    return text[:limit].strip() if len(text) >= 20 else ""


def wall_evidence(document: Document) -> str | None:
    """What gives this document away as a wall rather than a page, or None for a page.

    The two shapes `_refuse_block_page` refuses, as a question rather than an exception:
    a wall with words, or an empty document whose markup carries a bot-management
    vendor's script. Asked of each side of a union separately -- see `resolve_page`.
    """
    evidence = block_page_evidence(document.text)
    if evidence is not None:
        return evidence
    if document.text.strip() or any(b.kind is not BlockKind.PARAGRAPH for b in document.blocks):
        return None
    vendor = challenge_vendor(document.html)
    return f"{vendor} bot challenge" if vendor is not None else None


def _is_a_page(document: Document) -> bool:
    """Whether a document can stand in for the page beside a wall: at least
    `MIN_PAGE_BESIDE_WALL_WORDS` words of its own."""
    return len(document.text.split()) >= MIN_PAGE_BESIDE_WALL_WORDS


def _refuse_block_page(document: Document, *, status: int | None = None) -> None:
    """Raise rather than return a wall -- or nothing -- as if it were the page.

    Two shapes. A wall with words ("You've been blocked") is caught by its words. A
    JavaScript challenge has no words: the document is empty, and the only evidence is the
    vendor's script in the markup. An empty document with no such script is still not a
    page, and is refused as what it is -- a response that produced no readable text --
    rather than returned as a success of zero blocks.
    """
    evidence = block_page_evidence(document.text)
    if evidence is not None:
        raise PageBlockedError(document.url, evidence)
    if document.text.strip() or any(b.kind is not BlockKind.PARAGRAPH for b in document.blocks):
        return
    vendor = challenge_vendor(document.html)
    if vendor is not None:
        raise PageBlockedError(document.url, vendor, challenge=vendor)
    said = f"HTTP {status}, " if status else ""
    if document.profile.requires_render:
        raise ValueError(
            f"could not resolve {document.url}: the page is a JavaScript shell with no "
            f"readable text until a browser runs it ({said}{len(document.html):,} bytes of "
            "markup); rendering was not used for this request"
        )
    raise ValueError(
        f"could not resolve {document.url}: the response produced no readable text "
        f"({said}{len(document.html):,} bytes of markup, none of it visible)"
    )


def _both_failed(url: str, static: FetchResult, render_error: str | None) -> str:
    """One message covering both paths, because both were tried and both have something to say."""
    parts: list[str] = []
    if static.status in BLOCKING_STATUSES:
        parts.append(f"HTTP {static.status} -- {BLOCKING_STATUSES[static.status]}")
        if said := _server_said(static.html):
            parts.append(f'it said: "{said}"')
    elif static.error:
        parts.append(f"plain fetch: {static.error}")
    if render_error:
        parts.append(f"browser: {render_error.splitlines()[0][:120]}")
    return f"could not resolve {url}: " + "; ".join(parts or ["no reason reported"])


def resolve_page(
    url: str,
    *,
    strategy: Strategy | None = None,
    fetch_config: FetchConfig | None = None,
    render_config: RenderConfig | None = None,
    include_hidden_text: bool = False,
) -> ResolvedPage:
    """Resolve a page as completely as possible.

    `include_hidden_text` is passed to `build_document`: keep screen-reader-only labels and
    wiki edit controls rather than stripping them.

    `strategy` means exactly what it says, and unset means **complete**:

    - `None` or `UNION`: fetch both ways and merge. This is the default because the module
      docstring's measurement stands -- partial content loss cannot be predicted from the
      static HTML, so there is no per-page heuristic that could safely skip the render. An
      earlier version of this docstring promised one ("render whenever the profiler is not
      confident"); the code never did that, and the promise was withdrawn rather than the
      code changed. The per-*site* version of that decision does exist and is measured, not
      predicted: `analyze_site` fetches the root both ways and recommends `STATIC_ONLY` only
      when the comparison found the static HTML complete.
    - `STATIC_ONLY`: never render, even when the static HTML is visibly a shell. The caller
      chose budget over completeness and the profile says so via `requires_render`.
    - `RENDERED_ONLY`: the browser's document alone, falling back to static only when the
      render fails. For pages whose static HTML is known to be a decoy -- a consent
      interstitial served to non-browsers -- that the union would otherwise merge in.

    Rendering silently degrades to `STATIC_ONLY` when Playwright is not installed or the
    render fails; `render_error` on the result says which.
    """
    static_result = fetch_static(url, config=fetch_config)

    # Gate on status before anything else. A 404 page renders perfectly well, and without
    # this the engine extracts server error pages as though they were content.
    if static_result.status in MISSING_STATUSES:
        raise PageMissingError(url, static_result.status)

    # A frameset is a page made of other pages. Neither fetch sees its words -- the static
    # markup holds only the frame elements and a `<noframes>` apology, and a browser renders
    # each frame as a separate document the collector does not enter -- so the frames are
    # fetched and read in the order the frameset lays them out. See `_compose_frameset`.
    if static_result.ok and static_result.is_html and _FRAME.search(static_result.html):
        composed = _compose_frameset(static_result, fetch_config, include_hidden_text)
        if composed is not None:
            _refuse_block_page(composed, status=static_result.status)
            chars = len(composed.text)
            return ResolvedPage(
                url=composed.url,
                document=composed,
                strategy=Strategy.STATIC_ONLY,
                static_chars=chars,
                rendered_chars=0,
                union_chars=chars,
                blocks_only_in_static=0,
                blocks_only_in_rendered=0,
                render_error="frameset: frames read statically, in frameset order",
            )

    static_doc: Document | None = None

    if static_result.ok and static_result.is_html and static_result.html.strip():
        try:
            static_doc = build_document(
                static_result.html,
                static_result.url,
                headers=static_result.headers,
                include_hidden_text=include_hidden_text,
            )
        except ValueError:
            static_doc = None

    if strategy is Strategy.STATIC_ONLY:
        if static_doc is None:
            raise ValueError(f"static fetch produced no document for {url}: {static_result.error}")
        _refuse_block_page(static_doc, status=static_result.status)
        chars = len(static_doc.text)
        return ResolvedPage(
            url=static_doc.url,
            document=static_doc,
            strategy=Strategy.STATIC_ONLY,
            static_chars=chars,
            rendered_chars=0,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
        )

    # Everything that is not STATIC_ONLY renders. There is deliberately no profile check
    # here: `requires_render` catches the empty shell, which is the case that needs no
    # catching, and cannot see the 68% page -- see the module docstring.
    if not PLAYWRIGHT_AVAILABLE:
        if static_doc is None:
            raise ValueError(_both_failed(url, static_result, "rendering not installed"))
        _refuse_block_page(static_doc)
        chars = len(static_doc.text)
        return ResolvedPage(
            url=static_doc.url,
            document=static_doc,
            strategy=Strategy.STATIC_ONLY,
            static_chars=chars,
            rendered_chars=0,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
            render_error="rendering not available",
        )

    rendered = render_page(url, config=render_config)

    if not rendered.ok:
        if static_doc is None:
            # Both paths failed and they usually failed for *different* reasons. Reporting
            # only the second leaves a caller unable to tell "the site refused us" from "the
            # browser could not start", which are different problems with different fixes.
            raise ValueError(_both_failed(url, static_result, rendered.error))
        _refuse_block_page(static_doc)
        chars = len(static_doc.text)
        return ResolvedPage(
            url=static_doc.url,
            document=static_doc,
            strategy=Strategy.STATIC_ONLY,
            static_chars=chars,
            rendered_chars=0,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
            render_error=rendered.error,
        )

    geometry = geometry_by_xpath(rendered.html, rendered.rects)
    observed = runtime_evidence(rendered)
    rendered_doc = build_document(
        rendered.html,
        rendered.url or url,
        geometry=geometry,
        headers=static_result.headers,
        runtime=observed,
        include_hidden_text=include_hidden_text,
    )

    if static_doc is None or strategy is Strategy.RENDERED_ONLY:
        _refuse_block_page(rendered_doc)
        chars = len(rendered_doc.text)
        return ResolvedPage(
            url=rendered_doc.url,
            document=rendered_doc,
            strategy=Strategy.RENDERED_ONLY,
            # What the static fetch held is still reported when it was obtained: a caller
            # asking for the browser's view alone is entitled to know what it declined.
            static_chars=len(static_doc.text) if static_doc is not None else 0,
            rendered_chars=chars,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
            runtime=observed,
        )

    # A wall on one side only is that side's failure, not part of the page. Cloudflare
    # let a plain fetch of columbia.edu/~fdc/sample.html through and answered the browser
    # with "Performing security verification … Ray ID"; merged, the union carried the
    # wall's sentences into the page's Markdown, and the block-page check could not see
    # them inside a 4,000-word document. Each side is judged alone: the side that is a
    # wall is left out and named, the other is the page. Both walls still raise.
    # The other side has to be a page with words of its own: old.reddit.com answers the
    # browser with a wall and the plain fetch with a login redirect holding one empty
    # image and a "Skip to main content" link, and that is not the page either -- it
    # falls through to the merge, which is refused as the wall it contains.
    static_wall = wall_evidence(static_doc)
    rendered_wall = wall_evidence(rendered_doc)
    if rendered_wall is not None and static_wall is None and _is_a_page(static_doc):
        chars = len(static_doc.text)
        return ResolvedPage(
            url=static_doc.url,
            document=static_doc,
            strategy=Strategy.STATIC_ONLY,
            static_chars=chars,
            rendered_chars=0,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
            render_error=f'the browser was served a wall, left out: "{rendered_wall}"',
            runtime=observed,
        )
    if static_wall is not None and rendered_wall is None and _is_a_page(rendered_doc):
        chars = len(rendered_doc.text)
        return ResolvedPage(
            url=rendered_doc.url,
            document=rendered_doc,
            strategy=Strategy.RENDERED_ONLY,
            static_chars=0,
            rendered_chars=chars,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
            runtime=observed,
        )

    merged, only_static, only_rendered = union_documents(
        static_doc, rendered_doc, hidden=hidden_matter(rendered.html)
    )
    _refuse_block_page(merged)

    return ResolvedPage(
        url=merged.url,
        document=merged,
        strategy=Strategy.UNION,
        static_chars=len(static_doc.text),
        rendered_chars=len(rendered_doc.text),
        union_chars=len(merged.text),
        blocks_only_in_static=only_static,
        blocks_only_in_rendered=only_rendered,
        runtime=observed,
    )
