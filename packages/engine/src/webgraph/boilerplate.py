"""Identify site chrome from cross-page repetition.

The idea
--------
A block of text appearing on nearly every page of a site is navigation, footer, cookie
banner or legal strip -- not content. A single-page extractor cannot know this. A whole-site
crawler gets it for free, as a by-product of having crawled.

This matters downstream more than it looks. Feed 100 pages to an index or a model and the
same navigation arrives 100 times; on short pages it outweighs the actual content.

Measured effect, static crawl, 40 pages each:

| site                 | text removed |
|----------------------|--------------|
| books.toscrape.com   | 37.0%        |
| docs.pytest.org      |  8.8%        |

Why the threshold is not tunable (and does not need to be)
----------------------------------------------------------
Thresholds of 50%, 70% and 90% produced *identical* block sets on both sites. Site chrome
appears on essentially every page or on none, so there is no meaningful middle. The default
is therefore the conservative end: only blocks on >=90% of pages are removed. Lowering it
buys nothing and risks content.

Two protections against removing real content
---------------------------------------------
1. **A page's own leading heading is never removed.** On a category page titled "Travel",
   the sidebar link "Travel" makes the page's own title look repeated. Dropping it would
   delete the one line identifying the page.
2. **Nothing is removed from a site with too few pages** to make repetition meaningful.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from webgraph import config
from webgraph.main_content import link_density, word_count
from webgraph.types import Block, BlockKind

DEFAULT_THRESHOLD = config.CHROME_THRESHOLD
MIN_PAGES = config.CHROME_MIN_PAGES
MAX_REMOVAL = config.CHROME_MAX_REMOVAL
SLOT_PRESENCE = config.CHROME_SLOT_PRESENCE
MIN_LANDMARK_CHARS = config.CHROME_MIN_LANDMARK_CHARS
MAIN_MIN_WORDS = config.CHROME_MAIN_MIN_WORDS
MAIN_MIN_SHARE = config.CHROME_MAIN_MIN_SHARE

__all__ = [
    "BoilerplateProfile",
    "SiteChrome",
    "detect_boilerplate",
    "detect_site_chrome",
    "scope_to_main",
    "strip_boilerplate",
    "strip_landmarks",
    "strip_site_chrome",
]

LANDMARK_XPATH: Final[re.Pattern[str]] = re.compile(r"/(?:nav|footer)(?:\[|/|$)")
"""Blocks inside `<nav>` or `<footer>`.

These are the page's own statement about what is navigation, which makes excluding them
structural rather than heuristic -- the same principle the technology rules follow.

It also works where cross-page detection cannot. Chrome detection needs six pages before
repetition means anything; a landmark is declared on the first one. MDN's CSS reference
sidebar is a single `<nav>` holding several hundred links, and no amount of statistics over a
twelve-page sample removed it.

Measured over 13 pages against a majority vote of trafilatura, readability and jusText:

| variant | P | R | F |
|---|---|---|---|
| raw | 0.658 | 0.990 | 0.740 |
| without `nav` and `footer` | **0.727** | **0.990** | **0.811** |
| also without `aside` and `header` | 0.736 | 0.986 | 0.815 |

`nav` and `footer` only: seven points of F for **no recall at all**. Adding `aside` and
`header` bought 0.4 more points of F and cost 0.4 of recall on those thirteen pages, and
`aside` was left in on the grounds that sites put real material in one.

On MDN alone: precision 0.066 -> 0.584, recall unchanged at 1.000.

**`aside` is stripped now, re-measured on 1,497 labelled pages (WCXB dev) instead of
thirteen.** mspoweruser.com puts its "Deals" river -- twenty teaser headlines and blurbs --
in an `<aside>` inside `<main>`, and the boundary step kept it, because a teaser blurb is a
sentence and scores like one. Per type, F1 with `aside` kept -> stripped:

    article 0.9180 -> 0.9188   forum 0.7431 -> 0.7559   service 0.7994 -> 0.7998
    documentation 0.9237 (same)   collection 0.5845 -> 0.5857   listing 0.6607 -> 0.6632
    product 0.6015 -> 0.5972

The one loss is one page (gymshark.com, a size guide whose removal moved the run), and
every other type gains. `header` stays: a page's `<header>` carries its own title and
byline, and `_restore_title` depends on finding them.
"""


def strip_landmarks(blocks: Sequence[Block], *, title_block: Block | None = None) -> list[Block]:
    """Drop blocks inside `<nav>`, `<footer>` and `<aside>`, and inside named panels.

    Unlike cross-page detection this needs a single page, so it applies from the first result
    of a crawl rather than the sixth.

    `title_block` is the block carrying the page's own title (`content._title_block`). An
    `<aside>` that holds it is not complementary, whatever the markup calls it: it is the
    page's subject. allbirds.com puts a product's whole buy box -- the `<h1>`, the price,
    the colour, the sizes -- in an `<aside>`, and stripping it left "final sale*" and "Add
    to Cart" as the product. The blocks under that one `<aside>` element are kept; every
    other aside on the page is stripped as before.
    """
    # A dropdown's choices go first and unconditionally: the fail-open guards below exist
    # so a page whose landmarks hold everything is not gutted, and a 200-country selector
    # beside a two-line page would ride through them and then win the boundary step on
    # sheer word count -- glossier.com's failure, back by another door.
    without_selects = [block for block in blocks if block.widget != "select"]
    if without_selects:
        blocks = without_selects
    kept_aside = _aside_of(title_block) if title_block is not None else None
    if kept_aside is not None:
        # The page's subject, so the later steps read it as main: the boundary step gives
        # spec lines (`$16`, `Color: Onyx`) their credit only inside main.
        blocks = [
            block.model_copy(update={"region": "main", "in_main": True})
            if block.xpath.startswith(kept_aside)
            else block
            for block in blocks
        ]
    kept = [
        block
        for block in blocks
        if block.region not in STRIPPED_REGIONS
        and block.widget not in STRIPPED_WIDGETS
        # The innermost landmark wins over the path. protiviti.com's markup leaves a
        # <nav> and an <li> unclosed, so the parser nests the whole <main> inside them
        # and every path on the page runs through `/nav/`; the blocks are still in main.
        and not (LANDMARK_XPATH.search(block.xpath) and not block.in_main)
    ]
    if not kept:
        return list(blocks)

    if sum(len(b.text) for b in kept) < MIN_LANDMARK_CHARS:
        return list(blocks)
    return kept


_ASIDE_STEP: Final[re.Pattern[str]] = re.compile(r"^(.*/aside(?:\[\d+\])?)(?:/|$)")


def _aside_of(block: Block) -> str | None:
    """The XPath of the innermost `<aside>` the block sits in, with a trailing slash so a
    prefix test matches its descendants and not a sibling `aside[10]`; None when the block
    is in no aside."""
    if block.region != "aside":
        return None
    match = _ASIDE_STEP.match(block.xpath)
    return match.group(1) + "/" if match else None


STRIPPED_REGIONS: Final[frozenset[str]] = frozenset({"nav", "footer", "aside"})
"""Landmark regions `strip_landmarks` removes: the two `LANDMARK_XPATH` names, reached also
through `role="navigation"` and `role="contentinfo"` which the XPath cannot see, and
`aside` / `role="complementary"` -- see the module docstring for the measurement."""

STRIPPED_WIDGETS: Final[frozenset[str]] = frozenset({"filter", "consent", "rail", "post-furniture"})
"""Named panels `strip_landmarks` removes with the landmarks: a faceted-search filter is
navigation over the catalogue and a cookie dialog is nobody's content, whatever element
either is built from. A dropdown's choices (`select`) are removed before these, ahead of
the fail-open guards -- see the top of `strip_landmarks`. See `Block.widget`."""


def strip_comments(blocks: Sequence[Block], *, max_share: float = 1.0) -> list[Block]:
    """Drop the comments section (`Block.widget == "comments"`) -- unless the comments are
    the page.

    Under a Slashdot story the thread is not the story. On a Hacker News comment page, a
    GitHub issue or a Q&A thread the router did not recognise as a forum, the "comments"
    are everything the page has to say, and what is left without them is a login link and
    a footer. So the section goes only when what remains is a piece of writing in its own
    right: at least `MIN_COMMENT_HOST_WORDS` words outside it.
    """
    kept = [block for block in blocks if block.widget != "comments"]
    if len(kept) == len(blocks):
        return list(blocks)
    if max_share < 1.0:
        # A forum keeps its "comments" when they are the thread and drops them when they
        # are the asides under the answers: the share of the page's words they hold tells
        # the two apart (Stack Exchange comments are a tenth; a Reddit thread is most).
        total = sum(word_count(b.text) for b in blocks) or 1
        inside = sum(word_count(b.text) for b in blocks if b.widget == "comments")
        if inside > max_share * total:
            return list(blocks)
    # Prose outside the comments, not words: what a Hacker News item or a GitHub issue has
    # left is a nav strip, labels and a footer -- link text and one-line metadata -- while
    # even a short news story has a few sentences. Counting every word put the bar at 250
    # and cost short articles their precision (Zyte 0.928 -> 0.923); counting prose puts
    # it at 60 and separates the two cleanly.
    prose = sum(
        word_count(b.text)
        for b in kept
        if b.kind in _PROSE_KINDS
        and word_count(b.text) >= _PROSE_BLOCK_WORDS
        and link_density(b) < 0.5
    )
    if prose < MIN_COMMENT_HOST_WORDS:
        return list(blocks)
    return kept


MIN_COMMENT_HOST_WORDS: Final[int] = config.CHROME_MIN_COMMENT_HOST_WORDS
_PROSE_KINDS: Final[frozenset[BlockKind]] = frozenset({BlockKind.PARAGRAPH, BlockKind.QUOTE})
_PROSE_BLOCK_WORDS: Final[int] = 15


def scope_to_main(blocks: Sequence[Block]) -> list[Block]:
    """Keep only blocks inside the page's `main` landmark, when the page has a trustworthy one.

    The strongest structural statement a page makes is `<main>` (or `role="main"`): the
    author saying "this is the content". Everything outside it -- sidebars, related-article
    rails, newsletter boxes, cookie notices -- is outside by the author's own declaration.
    Returns the input unchanged when there is no main landmark or it fails the guard above.
    """
    inside = [block for block in blocks if block.in_main]
    if not inside:
        return list(blocks)
    # `word_count`, not a whitespace split: a Japanese article is one "word" per block to
    # `split()`, and asahi.com's <main> then held nothing against its mega-menu.
    inside_words = sum(word_count(b.text) for b in inside)
    total_words = sum(word_count(b.text) for b in blocks)
    if inside_words < MAIN_MIN_WORDS or inside_words < MAIN_MIN_SHARE * total_words:
        return list(blocks)
    return inside


_ARTICLE_STEP: Final[re.Pattern[str]] = re.compile(r"^(.*?/article(?:\[\d+\])?)(?:/|$)")


def scope_to_article(blocks: Sequence[Block]) -> list[Block]:
    """Keep only the blocks inside the page's dominant `<article>`, when there is one.

    `scope_to_main` reads the author's strongest statement; this reads the second. A news
    page is one `<article>` holding the story and, around it, teasers that are often
    `<article>` elements themselves (cbsnews.com: the story is 493 words in one article
    element and the "More World" river beneath it is twenty small ones). The dominant
    article is the one holding the most words, and it is trusted when it holds at least
    `ARTICLE_MIN_WORDS`, at least `ARTICLE_MIN_SHARE` of the page's words, and
    `ARTICLE_DOMINANCE` times the next largest -- a forum thread of equal-sized posts, each
    an `<article>`, never qualifies. Returns the input unchanged otherwise.
    """
    words: dict[str, int] = {}
    total = 0
    for block in blocks:
        n = word_count(block.text)
        total += n
        match = _ARTICLE_STEP.match(block.xpath)
        if match:
            words[match.group(1)] = words.get(match.group(1), 0) + n
    if not words or not total:
        return list(blocks)
    ranked = sorted(words.items(), key=lambda kv: -kv[1])
    top, top_words = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if top_words < ARTICLE_MIN_WORDS or top_words < ARTICLE_MIN_SHARE * total:
        return list(blocks)
    if runner_up and top_words < ARTICLE_DOMINANCE * runner_up:
        return list(blocks)
    prefix = top + "/"
    inside = [block for block in blocks if block.xpath == top or block.xpath.startswith(prefix)]
    return inside or list(blocks)


def scope_to_article_body(blocks: Sequence[Block]) -> list[Block]:
    """Keep only the blocks inside the page's dominant declared article body, when there is
    one -- see `Block.body_of`.

    The third statement after `<main>` and `<article>`, under the same three tests as the
    `<article>` (`ARTICLE_MIN_WORDS`, `ARTICLE_MIN_SHARE`, `ARTICLE_DOMINANCE`). Unlike
    an `<article>`, a body element leaves the headline and byline outside; the content
    step restores them from the blocks this removed. Returns the input unchanged when no
    body qualifies.
    """
    words: dict[str, int] = {}
    total = 0
    for block in blocks:
        n = word_count(block.text)
        total += n
        if block.body_of is not None:
            words[block.body_of] = words.get(block.body_of, 0) + n
    if not words or not total:
        return list(blocks)
    ranked = sorted(words.items(), key=lambda kv: -kv[1])
    top, top_words = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if top_words < ARTICLE_MIN_WORDS or top_words < ARTICLE_MIN_SHARE * total:
        return list(blocks)
    if runner_up and top_words < ARTICLE_DOMINANCE * runner_up:
        return list(blocks)
    inside = [block for block in blocks if block.body_of == top]
    return inside or list(blocks)


ARTICLE_MIN_WORDS: Final[int] = config.CHROME_ARTICLE_MIN_WORDS
ARTICLE_MIN_SHARE: Final[float] = config.CHROME_ARTICLE_MIN_SHARE
ARTICLE_DOMINANCE: Final[float] = config.CHROME_ARTICLE_DOMINANCE


def _key(block: Block) -> str:
    return " ".join(block.text.split()).casefold()


@dataclass(frozen=True, slots=True)
class BoilerplateProfile:
    """What repeats across a site."""

    keys: frozenset[str] = field(default_factory=frozenset)
    page_count: int = 0
    threshold: float = DEFAULT_THRESHOLD

    @property
    def active(self) -> bool:
        return bool(self.keys) and self.page_count >= MIN_PAGES

    def is_boilerplate(self, block: Block) -> bool:
        return _key(block) in self.keys


def detect_boilerplate(
    pages: Iterable[Sequence[Block]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> BoilerplateProfile:
    """Find blocks repeated across `pages`.

    A block counts once per page regardless of how often it appears on that page, so a
    footer link repeated three times in one page does not inflate its score.
    """
    counts: Counter[str] = Counter()
    total = 0

    for blocks in pages:
        total += 1
        for key in {_key(b) for b in blocks if b.text.strip()}:
            counts[key] += 1

    if total < MIN_PAGES:
        return BoilerplateProfile(page_count=total, threshold=threshold)

    cutoff = max(2, int(total * threshold))
    return BoilerplateProfile(
        keys=frozenset(k for k, c in counts.items() if c >= cutoff),
        page_count=total,
        threshold=threshold,
    )


def strip_boilerplate(blocks: Sequence[Block], profile: BoilerplateProfile) -> list[Block]:
    """Remove site chrome from one page, preserving its own leading heading.

    The heading guard exists because a page's title frequently also appears in the site
    navigation -- a category page called "Travel" beside a sidebar link "Travel". Removing it
    would delete the only line that identifies the page.
    """
    if not profile.active:
        return list(blocks)

    kept: list[Block] = []
    heading_kept = False

    for block in blocks:
        if not profile.is_boilerplate(block):
            kept.append(block)
            continue

        is_leading_heading = (
            block.kind is BlockKind.HEADING and block.level <= 2 and not heading_kept and not kept
        )
        if is_leading_heading:
            kept.append(block)
            heading_kept = True

    # Refuse to gut a page. If chrome detection would remove almost everything, the page is
    # probably mostly navigation (a sitemap, an index) and the original is more useful than
    # an empty document.
    original = sum(len(b.text) for b in blocks)
    remaining = sum(len(b.text) for b in kept)
    if original and remaining / original < 0.05:
        return list(blocks)

    return kept


# ---------------------------------------------------------------------------
# Template differencing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SiteChrome:
    """Site chrome identified two ways, because they catch different things.

    **Repeated text** finds a footer line that moves position between templates.
    **Static slots** find a template position that always holds the same value -- and,
    crucially, will not drop a page's unique content merely because the same words happen to
    appear elsewhere on the site.

    Measured against a majority vote of trafilatura/readability/justext, mean F across four
    sites: raw 0.684 -> 0.745 with this applied, with recall unchanged at 0.90-0.995.

    Slot identity is the **exact** XPath. An earlier version stripped positional indices to
    collapse equivalent slots across pages; that over-collapsed, putting many distinct blocks
    in one slot which then held many texts and never qualified as static. It scored +0.006 --
    effectively nothing. With exact paths the same idea reached F=0.950 on docs.pytest.org.
    """

    text: BoilerplateProfile = field(default_factory=BoilerplateProfile)
    slots: frozenset[str] = field(default_factory=frozenset)
    page_count: int = 0

    @property
    def active(self) -> bool:
        return self.page_count >= MIN_PAGES and bool(self.text.keys or self.slots)

    def is_chrome(self, block: Block) -> bool:
        return block.xpath in self.slots or self.text.is_boilerplate(block)


def detect_site_chrome(
    pages: Iterable[Sequence[Block]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    slot_presence: float = SLOT_PRESENCE,
) -> SiteChrome:
    """Identify chrome from cross-page repetition and template-slot variance."""
    materialised = [list(p) for p in pages]
    total = len(materialised)

    text_profile = detect_boilerplate(materialised, threshold=threshold)

    if total < MIN_PAGES:
        return SiteChrome(text=text_profile, page_count=total)

    present: Counter[str] = Counter()
    values: dict[str, set[str]] = {}
    for blocks in materialised:
        per_page: dict[str, set[str]] = {}
        for block in blocks:
            if not block.text.strip():
                continue
            per_page.setdefault(block.xpath, set()).add(_key(block))
        for xpath, texts in per_page.items():
            present[xpath] += 1
            values.setdefault(xpath, set()).update(texts)

    cutoff = max(2, int(total * slot_presence))
    static = frozenset(
        xpath
        for xpath, count in present.items()
        if count >= cutoff and len(values.get(xpath, set())) <= 1
    )

    return SiteChrome(text=text_profile, slots=static, page_count=total)


def strip_site_chrome(blocks: Sequence[Block], chrome: SiteChrome) -> list[Block]:
    """Remove chrome from one page. Same two guards as `strip_boilerplate`."""
    if not chrome.active:
        return list(blocks)

    kept: list[Block] = []
    for block in blocks:
        if not chrome.is_chrome(block):
            kept.append(block)
            continue
        # A page's own leading heading survives even when it looks repeated: on a category
        # page titled "Travel" the sidebar link "Travel" would otherwise delete the title.
        if block.kind is BlockKind.HEADING and block.level <= 2 and not kept:
            kept.append(block)

    original = sum(len(b.text) for b in blocks)
    remaining = sum(len(b.text) for b in kept)
    if original and (remaining / original) < (1.0 - MAX_REMOVAL):
        # Too much would go. Either the page is mostly navigation, or the corpus is
        # near-duplicate and shared content is masquerading as chrome. Leave it alone.
        return list(blocks)
    return kept
