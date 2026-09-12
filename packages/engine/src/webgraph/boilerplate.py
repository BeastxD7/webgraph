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
`header` buys 0.4 more points of F and costs 0.4 of recall, the wrong trade for an engine
whose stated job is not to lose content -- plenty of sites put real material in an `<aside>`.

On MDN alone: precision 0.066 -> 0.584, recall unchanged at 1.000.
"""

def strip_landmarks(blocks: Sequence[Block]) -> list[Block]:
    """Drop blocks inside `<nav>` and `<footer>`.

    Unlike cross-page detection this needs a single page, so it applies from the first result
    of a crawl rather than the sixth.
    """
    kept = [
        block
        for block in blocks
        if block.region not in STRIPPED_REGIONS
        and block.widget not in STRIPPED_WIDGETS
        and not LANDMARK_XPATH.search(block.xpath)
    ]
    if not kept:
        return list(blocks)

    if sum(len(b.text) for b in kept) < MIN_LANDMARK_CHARS:
        return list(blocks)
    return kept


STRIPPED_REGIONS: Final[frozenset[str]] = frozenset({"nav", "footer"})
STRIPPED_WIDGETS: Final[frozenset[str]] = frozenset({"filter"})
"""Named panels `strip_landmarks` removes with the landmarks: a faceted-search filter is
navigation over the catalogue, whatever element it is built from. See `Block.widget`."""
"""Landmark regions `strip_landmarks` removes -- the same two as `LANDMARK_XPATH`, now also
reached through `role="navigation"` and `role="contentinfo"`, which the XPath cannot see."""

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
    inside_words = sum(len(b.text.split()) for b in inside)
    total_words = sum(len(b.text.split()) for b in blocks)
    if inside_words < MAIN_MIN_WORDS or inside_words < MAIN_MIN_SHARE * total_words:
        return list(blocks)
    return inside


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


def strip_boilerplate(
    blocks: Sequence[Block], profile: BoilerplateProfile
) -> list[Block]:
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
            block.kind is BlockKind.HEADING
            and block.level <= 2
            and not heading_kept
            and not kept
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
