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
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Final

from webgraph import config
from webgraph.fetch import robots
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
from webgraph.types import STRUCTURE_ONLY, Block, BlockKind, Document, ReadingOrderMethod

MISSING_STATUSES = config.MISSING_STATUSES
BLOCKING_STATUSES = config.BLOCKING_STATUSES
MAX_BLOCK_PAGE_CHARS = config.MAX_BLOCK_PAGE_CHARS
MIN_PAGE_BESIDE_WALL_WORDS = config.MIN_PAGE_BESIDE_WALL_WORDS
LOGIN_PATH_MARKERS = config.LOGIN_PATH_MARKERS
LOGIN_RETURN_PARAMS = config.LOGIN_RETURN_PARAMS
MAX_LOGIN_PAGE_WORDS = config.MAX_LOGIN_PAGE_WORDS

__all__ = [
    "MISSING_STATUSES",
    "SUPPLIED_RENDER_NOTE",
    "PageBlockedError",
    "PageDisallowedError",
    "PageMissingError",
    "ResolvedPage",
    "Strategy",
    "block_page_evidence",
    "challenge_vendor",
    "declaration_demanded",
    "login_redirect",
    "resolve_page",
    "resolve_supplied",
    "union_documents",
    "wall_evidence",
]


class Strategy(StrEnum):
    STATIC_ONLY = "static-only"
    """Cheap path. Used when rendering is unavailable or explicitly disabled."""

    RENDERED_ONLY = "rendered-only"
    """The browser's document alone. Reported when the static fetch failed or returned
    nothing usable; requestable when the static HTML is known to be a decoy."""

    UNION = "union"
    """Both representations obtained and merged. The completeness path."""

    SUPPLIED = "supplied"
    """Nothing fetched: the caller handed over the HTML (`resolve_supplied`). For the sites
    that refuse every automated fetch -- Stack Overflow behind a Cloudflare challenge,
    nyc.gov behind Akamai, anything behind a login -- a reader who already has the page in
    their own browser can have it read without the engine pretending to be that browser.
    Not a value `resolve_page` accepts: there is no fetch for it to describe."""


class PageMissingError(Exception):
    """Raised when a URL does not exist. Distinct from a transport failure."""

    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"HTTP {status}: page does not exist")
        self.url = url
        self.status = status


class PageDisallowedError(ValueError):
    """The site's robots.txt asks automated clients not to read this page, and this client
    is one. A `ValueError` like every other "could not resolve"; its own type because the
    fix is not on the engine's side -- the message says what the site offers instead."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"could not resolve {url}: {reason}")
        self.url = url
        self.reason = reason


class PageShellError(ValueError):
    """The response was a JavaScript shell: markup with no readable text until a browser
    runs it, and the request did not render.

    A `ValueError` like every other "could not resolve", carrying the shell's `document` for
    the one caller that can use it: fact extraction reads a hydration payload
    (`__NEXT_DATA__`, JSON-LD) that is complete in the shell, and a browser adds nothing.
    """

    def __init__(
        self, document: Document, *, status: int | None = None, rendered: bool = False
    ) -> None:
        said = f"HTTP {status}, " if status else ""
        if rendered:
            # The browser ran and the page still has no words. That is not a shell waiting
            # for JavaScript -- it is what the site chose to show an automated browser:
            # usually a bot check with no text, sometimes a page that never draws without a
            # signed-in session. Saying "rendering was not used" here was untrue (amazon.in,
            # 17 Sep 2026).
            super().__init__(
                f"could not resolve {document.url}: a browser rendered the page and it still "
                f"has no readable text ({said}{len(document.html):,} bytes of markup); the "
                "site is serving an empty page to automated browsers -- most often a silent "
                "bot check -- and nothing of it can be read honestly"
            )
        else:
            super().__init__(
                f"could not resolve {document.url}: the page is a JavaScript shell with no "
                f"readable text until a browser runs it ({said}{len(document.html):,} bytes of "
                "markup); rendering was not used for this request"
            )
        self.document = document
        self.rendered = rendered


class PageBlockedError(ValueError):
    """The server answered, but with a wall instead of the page.

    A subclass of ValueError so that every existing "could not resolve" handler treats it
    as the failure it is. It exists as its own type because it is the one failure that used
    to be reported as success: Reddit's "You've been blocked by network security" came back
    as three blocks, typed `listing` at 86% confidence, with a green tick.
    """

    def __init__(
        self,
        url: str,
        evidence: str,
        *,
        challenge: str | None = None,
        login_url: str | None = None,
        undeclared: bool = False,
        declared_as: str | None = None,
    ) -> None:
        if undeclared and declared_as:
            message = (
                f"could not resolve {url}: the site admits automated clients only when they "
                f'declare who runs them, and kept refusing this one declared as "{declared_as}"; '
                f'it said: "{evidence}"'
            )
        elif undeclared:
            message = (
                f"could not resolve {url}: the site admits automated clients only when they "
                "declare who runs them -- a User-Agent naming an operator and a contact "
                "address -- and this deployment has nothing to declare; set "
                "WEBGRAPH_CONTACT='Name contact@example.com' and the site is asked again "
                f'in the form it documents. It said: "{evidence}"'
            )
        elif login_url:
            message = (
                f"could not resolve {url}: redirected to a login page ({login_url}); the page "
                "requires a sign-in and nothing of it was served"
            )
        elif challenge:
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
        self.login_url = login_url
        self.undeclared = undeclared

    @property
    def kind(self) -> str:
        """Which wall this was: `login` (a redirect to a sign-in page), `challenge` (a
        bot-management script), `undeclared` (the site admits automated clients that say
        who runs them, and this one could not) or `block` (a page saying the client was
        refused)."""
        if self.login_url:
            return "login"
        if self.undeclared:
            return "undeclared"
        return "challenge" if self.challenge else "block"


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


_DECLARE_PHRASES: Final[re.Pattern[str]] = re.compile(
    r"(undeclared automated tool|declare your traffic|declare your (?:automated )?(?:client|tool)"
    r"|updat(?:e|ing) your user[- ]agent to include)",
    re.IGNORECASE,
)


def declaration_demanded(html: str) -> str | None:
    """The server's words when it refused an *undeclared* automated client and said how to
    be admitted, or None for any other answer.

    Not a wall in the sense of the others: the site is not refusing automation, it is
    asking who is automating. sec.gov, 14 Sep 2026: HTTP 403, "Your Request Originates
    from an Undeclared Automated Tool … Please declare your traffic by updating your user
    agent to include company specific information." Quoted from the page's own text, so a
    reader of the refusal sees the demand as the site wrote it.
    """
    said = _server_said(html, limit=1_500)
    if not said:
        return None
    # The sentence that made the demand, not the page's first 200 characters: the title
    # says "Undeclared Automated Tool", the instruction is a paragraph further down, and
    # the instruction is the sentence worth quoting when both are there.
    matches = list(_DECLARE_PHRASES.finditer(said))
    if not matches:
        return None
    match = next((m for m in matches if "undeclared" not in m.group(0).lower()), matches[0])
    start = max(said.rfind(". ", 0, match.start()) + 1, 0)
    end = said.find(". ", match.end())
    sentence = said[start : end + 1 if end != -1 else None].strip()
    return sentence[:200]


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
    static_error: str | None = None
    """Why the plain fetch contributed nothing, when it did not: an HTTP error, a wall it was
    served and that was left out, a body that was not a page. None when the plain fetch
    gave the page or part of it. The counterpart of `render_error`, for the side a reader
    without a browser is on -- the site report reads it to say "the plain fetch was walled"
    rather than "0 characters"."""
    static_words: int = 0
    rendered_words: int = 0
    union_words: int = 0
    """The same three measurements in words (`str.split`). Characters are what the
    completeness claim is made in; words are what a person is told -- "41 words without
    JavaScript, 1,312 with it" reads, "228 of 19,000 characters" has to be explained."""
    identity_declared: bool = False
    """The site asked automated clients to say who runs them, and this fetch did (see
    `FetchConfig.declared`). False for the ordinary fetch every other page gets."""

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


def _words(text: str) -> int:
    return len(text.split())


_RUN_IN_MIN_CHARS: Final[int] = 20
_HIDDEN_MIN_CHARS: Final[int] = 12

_CHROME_REGIONS: Final[frozenset[str]] = frozenset({"nav", "header", "footer", "aside"})
_GATE_MIN_CHARS: Final[int] = 2_000
_GATE_RATIO: Final[float] = 1.5
"""When *one* hidden element holds more of the page's own prose than the whole visible
render -- at least `_GATE_MIN_CHARS`, more than `_GATE_RATIO` times what was shown -- the
browser was shown a gate, not a page with a hidden menu: a country picker, a consent
dialog, an age check, drawn over a page whose body it sets `display: none`. Behind a
gate the static page is the page, and the union keeps it whole."""


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

    candidates = {k for k in static_keys - rendered_keys if not runs_into_rendered(k)}
    behind = {k for k in candidates if hidden_in_render(k)}
    # A gate is *one* hidden element holding more than the whole visible render, and what
    # it holds is the page's own prose -- not a standalone link, not a block inside a
    # `nav`, `header`, `footer` or `aside` landmark. Many small hidden elements are menus
    # and collapsed sections, and stay hidden; one vast hidden footer of template text
    # (allbirds.com's 88,000 characters of cart and size-guide copy) is chrome, and stays
    # hidden too.
    prose_of = {
        _key(b): b.href is None and b.region not in _CHROME_REGIONS
        for b in static_doc.blocks
        if b.text.strip()
    }
    hidden_chars = sum(len(k) for k in behind if prose_of.get(k, True))
    visible = len(rendered_doc.text)
    gated = (
        hidden is not None
        and hidden.largest >= _GATE_MIN_CHARS
        and hidden.largest > _GATE_RATIO * visible
        and hidden_chars >= _GATE_MIN_CHARS
        and hidden_chars > _GATE_RATIO * visible
    )
    # A gate hides the page; a hidden menu hides a menu. Behind a gate, the render's hiding
    # is not a judgement about the content and the static page is kept whole.
    only_static = candidates if gated else candidates - behind

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

    # The merged document carries one markup, and the crawl reads its links from it. The
    # rendered one leads, as everywhere above -- except when the render came back with no
    # blocks at all, which a WebGL page in a headless browser does (bhavyadhanwani.dev's
    # /projects rendered as an empty `<body>`): then its markup is an empty shell, and a
    # crawl that read links from it would find none while the plain fetch's page had them.
    # An empty render also has no title and no description worth keeping over the static
    # page's.
    empty_render = not any(b.text.strip() for b in rendered_doc.blocks)
    update: dict[str, Any] = {
        "blocks": tuple(merged),
        "structured_data": tuple(payloads),
        "reading_order_method": method,
    }
    if empty_render and static_doc.blocks:
        update["html"] = static_doc.html
        update["title"] = rendered_doc.title or static_doc.title
        update["description"] = rendered_doc.description or static_doc.description
        update["markup"] = static_doc.markup
    if gated:
        update["gated"] = (
            f"the browser was shown a gate that hid the page: {hidden_chars:,} characters "
            f"behind it, {len(rendered_doc.text):,} in front; the plain fetch's page was kept"
        )
    document = rendered_doc.model_copy(update=update)
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
    static_result: FetchResult,
    fetch_config: FetchConfig | None,
    include_hidden_text: bool,
    depth: int = 0,
    rtl: bool | None = None,
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
            nested = _compose_frameset(result, fetch_config, include_hidden_text, depth + 1, rtl)
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
        parts.append(
            f'<section data-frame="{source}">{(body.text or "") if body is not None else ""}{inner}</section>'
        )
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
    return build_document(
        html,
        static_result.url,
        headers=static_result.headers,
        include_hidden_text=include_hidden_text,
        rtl=rtl,
    )


_SCRIPT_OR_STYLE: Final[re.Pattern[str]] = re.compile(
    r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)


def _server_said(html: str, limit: int = 140) -> str:
    """The server's own words, when it bothered to write any. Quoted, never paraphrased.

    Without its stylesheet: a block page's first 140 characters were its title and then
    `html {height: 100%} body {margin:0 …`, which is not what it said."""
    text = _RUNS.sub(" ", _TAGS.sub(" ", _SCRIPT_OR_STYLE.sub(" ", html))).strip()
    return text[:limit].strip() if len(text) >= 20 else ""


_PASSWORD_FIELD: Final[re.Pattern[str]] = re.compile(
    r"<input\b[^>]*\btype\s*=\s*[\"']?password\b", re.IGNORECASE
)


def _same_page(requested: str, final: str) -> bool:
    """Whether two URLs name the same page: a trailing slash, `www.`, the scheme, letter
    case in the host and a fragment are not a redirect to anywhere else."""
    from urllib.parse import urlsplit

    def key(url: str) -> tuple[str, str, str]:
        parts = urlsplit(url.strip())
        host = parts.netloc.lower().removeprefix("www.")
        path = parts.path.rstrip("/") or "/"
        return host, path, parts.query

    return key(requested) == key(final)


def _path_is_login(path: str) -> bool:
    """Whether a URL path holds one of `LOGIN_PATH_MARKERS` as whole segments."""
    padded = "/" + path.strip("/").lower() + "/"
    return any(f"{marker.lower()}/" in padded for marker in LOGIN_PATH_MARKERS)


def _returns_to(final: str, requested: str) -> bool:
    """Whether `final` carries a return-to parameter (`dest=`, `next=`, `session_redirect=`)
    naming the page that was asked for: the sign of a login page that will send the reader
    back once they sign in."""
    from urllib.parse import parse_qsl, urlsplit

    asked = urlsplit(requested)
    asked_path = asked.path.rstrip("/") or "/"
    for name, value in parse_qsl(urlsplit(final).query, keep_blank_values=False):
        if name.lower().replace("_", "").replace("-", "") not in LOGIN_RETURN_PARAMS:
            continue
        value = value.strip()
        if not value:
            continue
        if _same_page(requested, value):
            return True
        # A path-only value: `next=/r/programming/` against the requested path.
        if value.startswith("/") and (value.split("?")[0].rstrip("/") or "/") == asked_path:
            return True
    return False


def login_redirect(document: Document, requested_url: str | None) -> str | None:
    """The login page a fetch was redirected to, or None when it was not.

    Three things have to be true at once. The fetch ended somewhere other than where it
    was sent -- a real redirect, not a trailing slash or `www.` -- and not at a login URL
    the caller asked for. The final URL says it is a login page: a `LOGIN_PATH_MARKERS`
    segment in its path (`/login/`, `/uas/login`), or a `LOGIN_RETURN_PARAMS` parameter
    naming the page that was asked for (`?dest=https://old.reddit.com/r/…`). And the
    document is a login page rather than a page with a login on it: it holds a password
    field, or has fewer than `MAX_LOGIN_PAGE_WORDS` words. old.reddit.com's login shell
    has 4 words and no field until React runs; linkedin.com's has 52 and two fields; a
    shop whose header carries a sign-in box has neither shortage.
    """
    if not requested_url:
        return None
    from urllib.parse import urlsplit

    final = document.url
    if _same_page(requested_url, final):
        return None
    if _path_is_login(urlsplit(requested_url).path):
        return None
    if not (_path_is_login(urlsplit(final).path) or _returns_to(final, requested_url)):
        return None
    if len(document.text.split()) >= MAX_LOGIN_PAGE_WORDS and not _PASSWORD_FIELD.search(
        document.html
    ):
        return None
    return final


def wall_evidence(document: Document, *, requested_url: str | None = None) -> str | None:
    """What gives this document away as a wall rather than a page, or None for a page.

    The three shapes `_refuse_block_page` refuses, as a question rather than an exception:
    a redirect to a login page (judged against `requested_url`, when given), a wall with
    words, or an empty document whose markup carries a bot-management vendor's script.
    Asked of each side of a union separately -- see `resolve_page`.
    """
    login = login_redirect(document, requested_url)
    if login is not None:
        return f"redirected to a login page ({login})"
    evidence = block_page_evidence(document.text)
    if evidence is not None:
        return evidence
    if document.text.strip() or any(_is_structure(b) for b in document.blocks):
        return None
    vendor = challenge_vendor(document.html)
    return f"{vendor} bot challenge" if vendor is not None else None


def _is_structure(block: Block) -> bool:
    """Whether a text-less block is evidence of a page: an image, a table, a placeholder.
    A rule is not -- a challenge page can draw one."""
    return block.kind is not BlockKind.PARAGRAPH and block.kind not in STRUCTURE_ONLY


def _is_a_page(document: Document) -> bool:
    """Whether a document can stand in for the page beside a wall: at least
    `MIN_PAGE_BESIDE_WALL_WORDS` words of its own."""
    return len(document.text.split()) >= MIN_PAGE_BESIDE_WALL_WORDS


def _refuse_block_page(
    document: Document,
    *,
    status: int | None = None,
    requested_url: str | None = None,
    rendered: bool = False,
) -> None:
    """Raise rather than return a wall -- or nothing -- as if it were the page.

    Three shapes. A redirect to a login page is caught by where the fetch ended
    (`login_redirect`), and is judged first: old.reddit.com sends a thread's reader to
    `/login/?dest=…` and Cloudflare then walls the browser on that login page, and the
    redirect is the cause, the wall a consequence. A wall with words ("You've been
    blocked") is caught by its words. A JavaScript challenge has no words: the document is
    empty, and the only evidence is the vendor's script in the markup. An empty document
    with no such script is still not a page, and is refused as what it is -- a response
    that produced no readable text -- rather than returned as a success of zero blocks.
    """
    login = login_redirect(document, requested_url)
    if login is not None:
        raise PageBlockedError(requested_url or document.url, login, login_url=login)
    evidence = block_page_evidence(document.text)
    if evidence is not None:
        raise PageBlockedError(document.url, evidence)
    if document.text.strip() or any(_is_structure(b) for b in document.blocks):
        return
    vendor = challenge_vendor(document.html)
    if vendor is not None:
        raise PageBlockedError(document.url, vendor, challenge=vendor)
    if document.profile.requires_render or rendered:
        raise PageShellError(document, status=status, rendered=rendered)
    said = f"HTTP {status}, " if status else ""
    raise ValueError(
        f"could not resolve {document.url}: the response produced no readable text "
        f"({said}{len(document.html):,} bytes of markup, none of it visible)"
    )


def _static_failure(static: FetchResult) -> str:
    """Why the plain fetch gave no document, for `ResolvedPage.static_error`: the status
    and what it means, the transport error, or the fact that the body was not a page."""
    if static.status in BLOCKING_STATUSES:
        said = _server_said(static.html)
        quoted = f'; it said: "{said}"' if said else ""
        return f"HTTP {static.status} -- {BLOCKING_STATUSES[static.status]}{quoted}"
    if static.error:
        return static.error
    if not static.is_html:
        return f"the response was {static.content_type or 'not HTML'}, not a page"
    return "the response held no markup that could be read as a page"


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
    rtl: bool | None = None,
) -> ResolvedPage:
    """Resolve a page as completely as possible.

    `include_hidden_text` is passed to `build_document`: keep screen-reader-only labels and
    wiki edit controls rather than stripping them. `rtl` likewise: `None` detects the
    reading direction from the document, a bool forces it.

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
    if strategy is Strategy.SUPPLIED:
        # Every other value names how to fetch; this one names a page that was never
        # fetched. Left unchecked it fell through to the union branch, and a crawl
        # configured with `CRAWL_STRATEGY = "supplied"` would have fetched both ways and
        # reported it as something else.
        raise ValueError(
            f"could not resolve {url}: strategy {Strategy.SUPPLIED.value!r} means the caller "
            "supplies the HTML -- use resolve_supplied(html, url)"
        )
    # The site's own rule first. A page robots.txt disallows for this client is not
    # fetched at all -- reading it and then refusing would be the request the site asked
    # not to receive. `FetchConfig.respect_robots=False` is the caller's explicit override,
    # as `SiteConfig.respect_robots` has always been for the crawl.
    if (fetch_config or FetchConfig()).respect_robots:
        reason = robots.allowed(url, fetch_config=fetch_config)
        if reason is not None:
            raise PageDisallowedError(url, reason)

    static_result = fetch_static(url, config=fetch_config)

    # Gate on status before anything else. A 404 page renders perfectly well, and without
    # this the engine extracts server error pages as though they were content.
    if static_result.status in MISSING_STATUSES:
        raise PageMissingError(url, static_result.status)

    # A site that refused an undeclared automated client and said so is asked again as a
    # declared one -- once, in the form it documents, with the deployment's own contact --
    # and both fetches then speak as that client. With nothing to declare, the demand is
    # the refusal: naming the setting beats a "HTTP 403" nobody can act on. The contact
    # goes only to a site that asked; the first knock is the ordinary one everywhere.
    demand = declaration_demanded(static_result.html) if not static_result.ok else None
    declared = False
    if demand is not None:
        plain = fetch_config or FetchConfig()
        if not plain.contact:
            raise PageBlockedError(url, demand, undeclared=True)
        fetch_config = plain.declared()
        render_config = replace(render_config or RenderConfig(), user_agent=fetch_config.user_agent)
        static_result = fetch_static(url, config=fetch_config)
        if static_result.status in MISSING_STATUSES:
            raise PageMissingError(url, static_result.status)
        still = declaration_demanded(static_result.html) if not static_result.ok else None
        if still is not None:
            raise PageBlockedError(url, still, undeclared=True, declared_as=fetch_config.user_agent)
        declared = True

    resolved = _resolve_fetched(
        url,
        static_result,
        strategy=strategy,
        fetch_config=fetch_config,
        render_config=render_config,
        include_hidden_text=include_hidden_text,
        rtl=rtl,
    )
    return replace(resolved, identity_declared=True) if declared else resolved


def _resolve_fetched(
    url: str,
    static_result: FetchResult,
    *,
    strategy: Strategy | None,
    fetch_config: FetchConfig | None,
    render_config: RenderConfig | None,
    include_hidden_text: bool,
    rtl: bool | None,
) -> ResolvedPage:
    """`resolve_page` from the static fetch onward. See there for what the strategies mean."""

    # A frameset is a page made of other pages. Neither fetch sees its words -- the static
    # markup holds only the frame elements and a `<noframes>` apology, and a browser renders
    # each frame as a separate document the collector does not enter -- so the frames are
    # fetched and read in the order the frameset lays them out. See `_compose_frameset`.
    if static_result.ok and static_result.is_html and _FRAME.search(static_result.html):
        composed = _compose_frameset(static_result, fetch_config, include_hidden_text, rtl=rtl)
        if composed is not None:
            _refuse_block_page(composed, status=static_result.status, requested_url=url)
            chars = len(composed.text)
            words = _words(composed.text)
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
                static_words=words,
                union_words=words,
            )

    static_doc: Document | None = None

    if static_result.ok and static_result.is_html and static_result.html.strip():
        try:
            static_doc = build_document(
                static_result.html,
                static_result.url,
                headers=static_result.headers,
                include_hidden_text=include_hidden_text,
                rtl=rtl,
            )
        except ValueError:
            static_doc = None

    if strategy is Strategy.STATIC_ONLY:
        if static_doc is None:
            # The same words the two-path failure uses: the status, what it means, and what
            # the server said -- "HTTP 403" alone told a caller nothing about the wall.
            raise ValueError(_both_failed(url, static_result, None))
        _refuse_block_page(static_doc, status=static_result.status, requested_url=url)
        chars = len(static_doc.text)
        words = _words(static_doc.text)
        return ResolvedPage(
            url=static_doc.url,
            document=static_doc,
            strategy=Strategy.STATIC_ONLY,
            static_chars=chars,
            rendered_chars=0,
            union_chars=chars,
            blocks_only_in_static=0,
            blocks_only_in_rendered=0,
            static_words=words,
            union_words=words,
        )

    # Everything that is not STATIC_ONLY renders. There is deliberately no profile check
    # here: `requires_render` catches the empty shell, which is the case that needs no
    # catching, and cannot see the 68% page -- see the module docstring.
    if not PLAYWRIGHT_AVAILABLE:
        if static_doc is None:
            raise ValueError(_both_failed(url, static_result, "rendering not installed"))
        _refuse_block_page(static_doc, requested_url=url)
        chars = len(static_doc.text)
        words = _words(static_doc.text)
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
            static_words=words,
            union_words=words,
        )

    rendered = render_page(url, config=render_config)

    # A browser that was answered with a server error navigated fine and measured a page
    # of "No server is available to handle this request" -- flipkart.com/mobiles, 15 Sep
    # 2026, while the plain fetch seconds earlier had the listing. `ok` means the render
    # ran; the status says whether a page was served. A 5xx render is a failed side.
    if rendered.ok and rendered.status is not None and rendered.status >= 500:
        said = BLOCKING_STATUSES.get(rendered.status, "the server answered with an error")
        rendered = replace(rendered, ok=False, error=f"HTTP {rendered.status} -- {said}")

    if not rendered.ok:
        if static_doc is None:
            # Both paths failed and they usually failed for *different* reasons. Reporting
            # only the second leaves a caller unable to tell "the site refused us" from "the
            # browser could not start", which are different problems with different fixes.
            raise ValueError(_both_failed(url, static_result, rendered.error))
        _refuse_block_page(static_doc, requested_url=url)
        chars = len(static_doc.text)
        words = _words(static_doc.text)
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
            static_words=words,
            union_words=words,
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
        rtl=rtl,
    )

    if static_doc is None or strategy is Strategy.RENDERED_ONLY:
        _refuse_block_page(rendered_doc, requested_url=url, rendered=True)
        chars = len(rendered_doc.text)
        words = _words(rendered_doc.text)
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
            static_error=None if static_doc is not None else _static_failure(static_result),
            static_words=_words(static_doc.text) if static_doc is not None else 0,
            rendered_words=words,
            union_words=words,
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
    # falls through to the merge, which is refused as the wall it contains. A redirect
    # to a login page is a wall in the same sense (`login_redirect`): a site that sends
    # the plain fetch to sign in and serves the browser the page is read from the browser.
    static_wall = wall_evidence(static_doc, requested_url=url)
    rendered_wall = wall_evidence(rendered_doc, requested_url=url)
    if rendered_wall is not None and static_wall is None and _is_a_page(static_doc):
        chars = len(static_doc.text)
        words = _words(static_doc.text)
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
            static_words=words,
            union_words=words,
        )
    if static_wall is not None and rendered_wall is None and _is_a_page(rendered_doc):
        chars = len(rendered_doc.text)
        words = _words(rendered_doc.text)
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
            static_error=f'the plain fetch was served a wall, left out: "{static_wall}"',
            rendered_words=words,
            union_words=words,
        )

    merged, only_static, only_rendered = union_documents(
        static_doc, rendered_doc, hidden=hidden_matter(rendered.html)
    )
    _refuse_block_page(merged, requested_url=url, rendered=True)

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
        static_words=_words(static_doc.text),
        rendered_words=_words(rendered_doc.text),
        union_words=_words(merged.text),
    )


_DECLARED_URL_XPATHS: Final[tuple[str, ...]] = (
    "//link[@rel='canonical']/@href",
    "//meta[@property='og:url']/@content",
)


def _declared_url(html: str, base_url: str) -> str | None:
    """Where the markup says its page lives: `<link rel="canonical">`, else `og:url`.

    Absolute against `base_url`; None when the page declares nothing. This is the only
    trace of a redirect a supplied document can carry -- see `resolve_supplied`.
    """
    from urllib.parse import urljoin, urlsplit

    from lxml import html as lxml_html

    try:
        root = lxml_html.fromstring(html)
    except (ValueError, TypeError):
        return None
    for xpath in _DECLARED_URL_XPATHS:
        found = root.xpath(xpath)
        if not isinstance(found, list):
            continue
        for value in found:
            declared = urljoin(base_url, str(value).strip())
            parts = urlsplit(declared)
            if parts.scheme in ("http", "https") and parts.netloc:
                return declared
    return None


SUPPLIED_RENDER_NOTE: Final[str] = (
    "HTML supplied by the caller; not fetched or rendered -- reading order is source order, "
    "and what the browser would have hidden may appear"
)
"""`ResolvedPage.render_error` on every supplied page. Not a failure: it says what the
result is -- one representation, unmeasured -- so a caller showing a completeness claim
knows which one it is looking at, the same way `"rendering not available"` does."""


def resolve_supplied(
    html: str,
    url: str,
    *,
    include_hidden_text: bool = False,
    rtl: bool | None = None,
) -> ResolvedPage:
    """Resolve a page from HTML the caller already has, fetching nothing.

    Why this exists
    ---------------
    Some sites refuse every automated fetch: stackoverflow.com answers both the plain
    fetch and the browser with a Cloudflare challenge, nyc.gov with Akamai's, and a login
    wall serves nothing of the page to anyone not signed in. The engine will not disguise
    the client to get past them -- that is the owner's decision, and a disguise is a
    contest the engine would lose to the next rule change anyway. What a caller *can* do
    is hand over the page they already have: their own logged-in browser's document, an
    extension's copy, a saved file. This reads it exactly as a fetched page is read and
    returns the same `text` / `markdown`, marked `Strategy.SUPPLIED`.

    What it does not do
    -------------------
    **No network, ever.** `url` is the page's address for making links and images
    absolute and for the wall check below; it is not fetched, and neither is anything the
    markup names. A supplied `<frameset>` in particular is parsed as the markup it is --
    `_compose_frameset`, which fetches each frame, is not called, because a caller who can
    name frame URLs in pasted HTML would otherwise be naming URLs for this process to fetch
    from inside its network. No render either: the reading order is source order and says
    so (`reading_order_method`), and text a browser would have hidden -- a `display: none`
    menu, a collapsed section -- may appear. `render_error` carries that caveat verbatim.

    Never a false output
    --------------------
    The HTML is judged by `_refuse_block_page` like a fetched document: a pasted Cloudflare
    "Sorry, you have been blocked", a challenge script with no words, a page with no text
    at all, are refused with the same `PageBlockedError` / `ValueError` a fetch of them
    raises. A login page is the one wall that needs an extra step. A fetch is caught
    redirecting to one (`login_redirect` compares where it ended with where it was sent);
    a supplied document never went anywhere, so the one place it can say where it really
    is is its own `<link rel="canonical">` or `og:url`. When that declared address differs
    from `url`, the login conditions are applied with it as the final URL. Measured
    2026-09-14: www.linkedin.com/login carries `<link rel="canonical"
    href="https://www.linkedin.com/login">` and the same `og:url`, so a paste of it with
    `url` set to the feed it was guarding is refused as a login redirect, not returned as
    twenty blocks of "Email or phone". A page declaring nothing, or declaring itself, is
    judged on its words.

    Size: `html` larger than `config.FETCH_MAX_BYTES` is refused -- the same limit a fetch
    applies, because a body above it is not a page whichever way it arrived.
    """
    size = len(html.encode("utf-8", errors="replace"))
    if size > config.FETCH_MAX_BYTES:
        raise ValueError(
            f"could not read the supplied HTML for {url}: {size:,} bytes is over the "
            f"{config.FETCH_MAX_BYTES:,}-byte limit a fetched page is held to"
        )
    if not html.strip():
        raise ValueError(f"could not read the supplied HTML for {url}: it is empty")

    document = build_document(html, url, include_hidden_text=include_hidden_text, rtl=rtl)

    declared = _declared_url(html, url)
    if declared is not None:
        # `login_redirect` treats a declaration of `url` itself, `www.` or a trailing slash
        # as no redirect at all, the same as it does for a fetch.
        login = login_redirect(document.model_copy(update={"url": declared}), url)
        if login is not None:
            raise PageBlockedError(url, login, login_url=login)
    _refuse_block_page(document, requested_url=url)

    chars = len(document.text)
    words = _words(document.text)
    return ResolvedPage(
        url=document.url,
        document=document,
        strategy=Strategy.SUPPLIED,
        static_chars=chars,
        rendered_chars=0,
        union_chars=chars,
        blocks_only_in_static=0,
        blocks_only_in_rendered=0,
        render_error=SUPPLIED_RENDER_NOTE,
        static_words=words,
        union_words=words,
    )
