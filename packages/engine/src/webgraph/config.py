"""Every knob in one place.

This file holds the configuration a person running webgraph might change: how pages are
fetched and rendered, when a response is refused as a wall, how far a crawl goes, how the
content boundary is drawn, how confident the router must be, and the thresholds behind the
site chrome detector and the knowledge graph. The engine's *protocols* -- marker attribute
names, model formats, feature lists -- are not configuration and stay with the code that
speaks them.

Every module that uses one of these imports it from here and re-exports it under its old
name, so `from webgraph.fetch.static import FetchConfig` still works. The definitions
moved; nothing else did.

The values are not defaults picked to look reasonable. Nearly all of them were set by
measurement -- the docstring beside each says which, and against what -- and a change here
should be measured the same way before it ships. The benchmarks under `benchmark/` are how.

Environment variables are read in one place too, `Settings.from_env()`, so that the list of
things a deployment can set is this list and not a grep.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

# ---------------------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------------------

_BROWSER_PREFIX: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


DEFAULT_USER_AGENT: Final[str] = (
    f"{_BROWSER_PREFIX} webgraph/0.1 (+https://github.com/webgraph/webgraph)"
)
"""Browser-shaped, and still identifiable.

The shape is load-bearing: many servers reject anything that does not parse as a browser,
and on the scrape-evals corpus that rejection costs 14 of 143 blocked pages. The suffix is
also load-bearing, and is the reason this is not simply a Chrome string: a site owner reading
their logs can see exactly what this is and where to complain. A crawler that cannot be
identified or contacted is indistinguishable from an abusive one, and the 17 further pages a
bare spoof would recover do not buy that back.

`FetchConfig.user_agent` overrides it, for a caller whose agreement with a site says to."""


RETRY_STATUSES: Final[frozenset[int]] = frozenset({429, 503})
"""Statuses that mean *later*, not *no*. Retried once, honouring `Retry-After`.

Nine URLs in the scrape-evals corpus answered 429 and were recorded as failures without a
second attempt ever being made, which is a bug in the client rather than a property of the
web. A single retry is deliberate: a crawler that retries hard on 429 is the reason the 429
was sent."""


MAX_RETRY_WAIT_SECONDS: Final[float] = 5.0
"""Longest `Retry-After` worth honouring inline. A server asking for a minute is asking to be
crawled later, not to have a thread held open for it."""


_MAX_RESPONSE_BYTES: Final[int] = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FetchConfig:
    timeout_seconds: float = 20.0
    max_redirects: int = 5
    max_bytes: int = _MAX_RESPONSE_BYTES
    user_agent: str = DEFAULT_USER_AGENT
    extra_headers: dict[str, str] = field(default_factory=dict)
    http2: bool = True
    """Negotiate HTTP/2 when the server offers it. Falls back to HTTP/1.1 automatically."""

    retries: int = 1
    """Extra attempts for a `RETRY_STATUSES` answer or a transport error. One by default:
    enough for a server that said *later*, not enough to be the reason it said so."""


# ---------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------

GATE_MAX_TEXT: Final[int] = 4000
"""Below this much text, together with almost no internal links, a page may be a gate.

Generous on purpose. The check is a *trigger for looking*, not a verdict: nothing is kept
unless a click measurably improves the page, so a false trigger costs one guarded click and
changes no output."""


GATE_MAX_LINKS: Final[int] = 1
"""Internal links above which the page is treated as real navigation, not a gate.

One, not two, and the difference is not cosmetic. At two, a small site's ordinary page --
2,161 characters and two nav links, in `test_gates.py`'s ungated fixture -- was reported as
looking gated. Nothing was clicked, because the accept test still refused it, but the engine
was describing a perfectly normal page as suspicious.

The measured gate has **zero** internal links, because its navigation lives in the subtree
that never mounted. Allowing one covers a gate that still renders a logo linking home."""


GATE_MIN_GAIN: Final[float] = 1.5
"""How much better the page must get before a click is kept.

A gate that opens reveals the whole site, so the real signal is large -- 1,137 characters to
2,344 with 0 links becoming 21 on the measured case. Requiring a decisive improvement keeps
this from accepting a click that merely opened a tooltip."""


MAX_RECORDED_REQUESTS: Final[int] = 400
"""Requests kept for fingerprinting. Only distinct hosts and paths carry information, and
an asset-heavy page can issue thousands."""


MIN_SALVAGED_TEXT: Final[int] = 200
"""Visible characters a timed-out document must hold to count as a page.

Not a tuning knob so much as the line between "slow" and "nothing". A real page that merely
lost its adverts still has its article; a server error rendered as a document has a sentence.
"""


@dataclass(frozen=True, slots=True)
class RenderConfig:
    timeout_ms: int = 30_000
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "load"
    """`load`, not `networkidle`.

    `networkidle` waits for 500ms of no network activity, which **never happens** on sites
    with analytics beacons, polling, websockets or video preloading. Measured against 24 real
    sites it timed out on 5 of them (21%) -- Shopify, Squarespace, Stripe, python.org and
    Figma -- losing those pages entirely. `load` plus an explicit settle is slightly earlier
    but actually fires."""

    viewport_width: int = 1440
    viewport_height: int = 900
    """Width matters for reading order -- a narrow viewport collapses a multi-column layout
    into one column, which changes the correct answer."""

    settle_ms: int = 900
    """Pause after load to let hydration and layout settle before measuring.

    Carries the weight that `networkidle` used to: most client-side frameworks finish
    hydrating within a few hundred milliseconds of `load`, and measuring before that captures
    the pre-hydration layout."""

    dismiss_gates: bool = True
    """Open a first-run interstitial that is blocking the page from mounting.

    On by default, on the same asymmetric-cost reasoning that biases `_needs_render` toward
    rendering: a gate left closed loses essentially the whole site -- 97% of the text and
    *every* internal link on the measured case -- while a wrongly-suspected gate costs one
    guarded click and is discarded unless it measurably improves the page.

    This is the one place the engine clicks anything, and `fetch/js/reveal.js`'s reasons for
    refusing to click still stand, so the click is fenced in four ways: it only happens on a
    page that has almost no text *and* almost no internal links; candidates inside a `<form>`
    or carrying a real `href` are never chosen; labels reading as a transaction, refusal or
    sign-out are excluded; and the result is thrown away unless the page gets decisively
    better. A click that navigates off-origin is reverted.
    """

    reveal_collapsed: bool = False
    """Open `<details>` and ARIA disclosure panels before measuring.

    Reaches content the page hides until someone interacts, without clicking anything -- see
    `fetch/js/reveal.js` for why clicking is the wrong tool. Off until measured; see MEMORY.md.
    """

    user_agent: str | None = None
    headless: bool = True
    reuse_browser: bool = True
    """Reuse the calling thread's browser rather than launching one per page.

    Launch is a fixed cost per page -- see `fetch/browser.py` for why the reuse is
    thread-local. Disable it to isolate a page that crashes the browser."""

    block_resources: tuple[str, ...] = ("image", "media", "font")
    """Skipped to cut bandwidth and time. Fonts are blocked deliberately: metrics shift
    slightly without them, but not enough to change column structure."""


# ---------------------------------------------------------------------------------------
# Resolving a page
# ---------------------------------------------------------------------------------------

MISSING_STATUSES: Final[frozenset[int]] = frozenset({404, 410})
"""Statuses meaning the page does not exist. Never render these.

A browser renders a server's 404 page perfectly happily, producing "Not Found -- The
requested URL was not found on this server" as though it were content. Measured on
ionidea.com, whose relative links resolve into hundreds of URLs that do not exist: without
this gate every one of them yielded a document.

Deliberately excludes 403/429/5xx. Those usually mean *blocked* or *transient*, not
*absent* -- and rendering frequently succeeds where a static fetch was refused."""


class Strategy(StrEnum):
    STATIC_ONLY = "static-only"
    """Cheap path. Used when rendering is unavailable or explicitly disabled."""

    RENDERED_ONLY = "rendered-only"
    """The browser's document alone. Reported when the static fetch failed or returned
    nothing usable; requestable when the static HTML is known to be a decoy."""

    UNION = "union"
    """Both representations obtained and merged. The completeness path."""


BLOCKING_STATUSES: Final[dict[int, str]] = {
    401: "the page requires a sign-in",
    403: "the site refused this client",
    429: "the site is rate-limiting this client",
    451: "the page is blocked for legal reasons",
    503: "the site said it was too busy, which is also how several of them refuse bots",
}
"""Statuses that mean something a person can act on, said in words.

`HTTP 503` is accurate and tells a reader nothing. Whether a page is dead, gated, or refusing
us decides what to do next, and the status alone does not distinguish them -- so the reason is
spelled out and, where the server explained itself, quoted."""


MAX_BLOCK_PAGE_CHARS: Final[int] = 1_500
"""A block page is a sentence and a button. Above this a page is presumed to be a page."""


# ---------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------

MAX_DOCUMENT_BYTES: Final[int] = 32 * 1024 * 1024
"""Refuse documents larger than this before parsing.

Needed because `huge_tree` (below) disables libxml2's built-in resource guards, and a
crawler's input is untrusted by definition. Bounding size up front is the safe way to buy
unlimited nesting depth.
"""


NOSCRIPT_SHELL_MAX_WORDS: Final[int] = 150
"""A page with fewer visible words than this outside `<noscript>` is a shell."""


NOSCRIPT_CONTENT_MIN_WORDS: Final[int] = 100
"""And its `<noscript>` must hold at least this many words to count as the content."""


# ---------------------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------------------

LONG_CELL_CHARS: Final[int] = 200
"""A cell holding more text than this is prose, not a value.

This is what replaced the tag test, and it is the signal that actually separates the two
cases. A layout cell holds an article; a data cell holds a number or a short label. Tag
identity cannot tell those apart because both use `<p>`; length can."""


MIN_GRID: Final[int] = 2
"""A data table needs at least this many rows *and* columns.

A table exists to cross-reference a row against a column. One row, or one column, has nothing
to cross-reference, so it is a layout device wearing table markup. Measured on WebMainBench:
of the tables the engine emitted where the annotators saw none, most were exactly this -- a
1x1 cell reading "Home", a 1x2 "Rate this" widget, a 1x4 auto-refresh control strip, a 6x1
list of tool names."""


MIN_FILLED_SHARE: Final[float] = 0.4
"""And enough of its cells must hold something. A 5x3 grid with two non-empty cells is a
layout scaffold, not a sparse dataset."""


MAX_EMPTY_ROW_SHARE: Final[float] = 0.2
"""Above this share of entirely empty rows, the table is being used for spacing.

The clearest signal of the lot, and the one that catches the tables the others miss. A table
of data does not have blank rows *between its records*; a page laid out in table markup does,
because an empty `<tr>` was how you made a gap before CSS. Measured on the Hacker News front
page: 92 rows, **31 of them entirely empty**, no header anywhere, row widths of 0, 2 and 3.
Every other test here passed it as data, and it is a list of 30 stories."""


# ---------------------------------------------------------------------------------------
# Reading order
# ---------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class OrderingConfig:
    """Tuning for cut detection.

    Gap thresholds are expressed as multiples of the median block height rather than as
    absolute pixels, so the same config works on a dense sidebar and an airy landing page.
    """

    min_row_gap_ratio: float = 0.6
    """A vertical whitespace band must exceed this multiple of median block height to count
    as a row separator. Below it, the gap is ordinary line spacing."""

    min_col_gap_ratio: float = 1.0
    """A horizontal whitespace band must exceed this multiple of median block height to
    count as a column gutter. Set higher than the row threshold because inline spacing
    between words and inline elements is common and must not be read as a column break."""

    min_absolute_gap: float = 8.0
    """Floor in CSS pixels, guarding against degenerate tiny-text pages."""

    max_depth: int = 24
    """Recursion guard. Deeply nested cuts past this point are ordered positionally."""

    min_measured_share: float = 0.3
    """Share of blocks that must carry geometry before it is allowed to lead the ordering.

    Set by measurement, having first been guessed at 0.5. Method: take pages the browser
    measured almost completely, treat their full-geometry order as ground truth, blind a
    share of blocks, and score the anchored result by how often a pair of blocks keeps its
    correct relative order.

    Blinding in **clustered runs**, because that is the shape of the real thing -- a
    collapsed section, or the blocks that exist only in the static half of a union fetch.
    Random blinding is a materially easier problem and overstates how well this works.

    ```
    share measured   90%   75%   60%   50%   40%   30%   20%   10%
    clustered       1.00  0.97  0.97  0.98  0.92  0.92  0.88  0.91
    random          0.99  0.99  0.98  0.98  0.97  0.96  0.96  0.94
    source order    0.89  <- what falling back produces
    ```

    Anchoring beats the fallback down to about 30% and loses below roughly 25%. The crossover
    is noisy over six pages, so the threshold sits on the conservative side of it.

    The guessed 0.5 was costing real accuracy: a union document merges static-only blocks,
    which by construction carry no rectangle, so its measured share is always lower than the
    rendered document's. Four sites in a robustness sweep -- lemonde.fr, shopify.com,
    ar.wikipedia and aljazeera -- sat between 0.34 and 0.47 and read in source order.
    """


# ---------------------------------------------------------------------------------------
# Content selection
# ---------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MainContentConfig:
    """Tuning for the selector. Every value here was swept, not chosen."""

    adaptive_cost: bool = True
    """Scale `block_cost` to the page's own mean block length instead of using a constant.

    A fixed cost cannot serve every kind of page, and the measurement is unambiguous. Swept
    per page type on WCXB dev, the optimum is: article 11, collection 13, forum 7, product 7,
    documentation 5, service 3, listing 3. **Article is the outlier** -- six of the seven
    types want 3 to 7 -- and 13 was chosen on Zyte, which is 181 article pages. At 13 the
    selector is not merely suboptimal elsewhere, it is *worse than not running*: -0.099 F1 on
    listing, -0.070 on service.

    A per-type constant is the obvious fix and is the wrong one: the small types' optima flip
    between splits (collection 13 on dev, 3 on test), so a lookup table would be fitting
    noise. What generalises is the ratio. Cost tracks the mean block length of the page in
    front of you:

        cost = clamp(0.70 * mean_block_words, 5.0, 18.0)

    ```
                        WCXB dev   WCXB test   WCXB all     Zyte
    no selector           0.6471      0.6823     0.6560   0.6471
    fixed cost 13         0.6814      0.7015     0.6865   0.8751
    adaptive              0.7133      0.7447     0.7213   0.8564
    ```

    **+0.035 WCXB, -0.019 Zyte** -- and the trade is not close. Adaptive wins on **all seven**
    page types and on dev and test independently, turning the service and documentation
    regressions into +0.051 and +0.043. Zyte recall rises 0.921 -> 0.960. The 0.019 given up
    is on 181 article pages of one type; the 0.035 gained is across 2,008 pages of seven.

    Note that Song et al.'s own normalisation -- dividing by the page total -- does *not*
    work here: per-page optimal cost correlates only weakly with page length (Spearman
    +0.229), and it scores 0.6981 on WCXB dev against the constant's 0.6814. The mean block
    length is the denominator that carries the signal, not the page length."""

    cost_ratio: float = 0.70
    """Multiple of mean block words used as the per-block cost when `adaptive_cost` is set.

    Flat over 0.65-0.80, and 0.70 is the maximum on WCXB dev **and** test independently. The
    Zyte column was deliberately not used to break the tie -- it jitters by +/-0.008 across
    that range on 181 pages, which is noise being asked to decide a parameter."""

    cost_floor: float = 5.0
    """Lower clamp. A page of very short blocks would otherwise set a cost near zero, and a
    zero cost keeps everything."""

    cost_ceiling: float = 18.0
    """Upper clamp. A page of very long blocks would otherwise set a cost that rejects real
    paragraphs."""

    block_cost: float = 13.0
    """Fixed per-block cost, used when `adaptive_cost` is False.

    Words a block must be worth before it pays for its own place in the run.

    This is what makes the run stop. Without a per-block cost every block has a
    non-negative value, the maximum subarray is the whole document, and the selector does
    nothing. It is expressed in words so it scales with nothing -- a block carrying fewer
    than this many unlinked words is chrome unless something else redeems it.

    Swept on Zyte's 181-page article benchmark (`benchmark/article_extraction`), with
    `strip_landmarks` applied first:

    ```
    cost      F1       P       R            cost      F1       P       R
       3   0.7137  0.5638  0.9720             13   0.8816  0.8492  0.9166  <- adopted
       6   0.7987  0.6749  0.9781             14   0.8700  0.8490  0.8922
      10   0.8556  0.7800  0.9475             15   0.8695  0.8516  0.8882
      11   0.8721  0.8194  0.9321             17   0.8690  0.8675  0.8706
      12   0.8730  0.8318  0.9186             20   0.8308  0.8556  0.8074
                                              30   0.6655  0.8013  0.5690
    ```

    13 is the peak, but read the shape rather than the maximum: 11 through 17 all sit near
    0.87, so this is a **plateau with one spike**, and a spike over 181 pages is as likely to
    be sampling noise as signal. What actually distinguishes points on the plateau is the
    precision/recall split -- cost 11 gives R 0.9321, cost 17 gives R 0.8706, for the same F1.
    The low end is therefore the principled choice for this engine regardless of which point
    peaks: equal F1, more recall, and recall is the promise the rest of the engine keeps.

    That reasoning was sound and the constant still did not generalise: swept per page type on
    WCXB it is worse than not running at all on listing and service. See `adaptive_cost`,
    which supersedes it. This value is retained for reproducing the article-only numbers and
    for callers who genuinely want a fixed cost."""

    heading_bonus: float = 4.0
    """Headings are short and are content, which the raw word count gets backwards. They also
    mark where an article starts, so a run that opens on one is usually right.

    Swept at `block_cost=15`: 0 -> 0.8683, 4 -> **0.8695**, 8 -> 0.8691, 16 -> 0.8596,
    30 -> 0.8055. Nearly flat between 0 and 8, so this is a plateau rather than a peak and
    the exact value is not load-bearing."""

    structural_credit: float = 0.5
    """Share of a table's or code block's words credited even when they look link-dense.

    On documentation pages the table *is* the content, and `benchmark/content_quality`
    already recorded that dropping tables and code loses real text on exactly the page type
    where they matter most.

    **Measured as inert, and kept only pending a corpus that can see it.** Swept 0.0, 0.25,
    0.5, 0.75, 1.0 on Zyte at cost=14: F1 0.8700 at *every* value, to four decimals. Zyte is
    181 news and blog articles, which carry essentially no tables or code, so the branch
    never binds there and the sweep measured nothing. That is a statement about the corpus,
    not evidence that the parameter works -- it is unvalidated either way. WCXB's
    documentation type (91 dev pages) and WebMainBench's table/code metrics are the
    instruments that could actually settle it."""

    bridge: float = 0.0
    """How much accumulated cost a run may absorb before it restarts, as a multiple of
    `block_cost`. **Zero -- measured, and it does not work.**

    The reasoning was good. Plain Kadane restarts the moment the running total goes negative,
    so any single chrome block ends the run. On a Stack Overflow answer the sequence is prose,
    `share edit follow`, code, `answered Jan 5`, more prose, and a three-word link strip pays
    a full `block_cost` -- so the run is shredded and the code block is left outside it. That
    is a real mechanism, and it is why turning the selector on cost **-0.126 code_edit** on
    WebMainBench, with 13 pages accounting for 99% of the drop.

    Letting the run absorb a bounded deficit was the obvious fix. Swept on Zyte:

    ```
    bridge    F1        P        R
      0.0   0.8725   0.7953   0.9661   <- off, and best
      1.0   0.8675   0.7854   0.9688
      2.0   0.8635   0.7798   0.9674
      3.0   0.8606   0.7739   0.9691
    ```

    Monotonically worse. Bridging buys a little recall and loses more precision, because a
    run permitted to cross chrome crosses *all* of it -- including the boundary between an
    article and the comments beneath it.

    A noise-proportional cost (`free - alpha*linked - beta`, so a three-word nav strip costs
    three rather than thirteen) was the other candidate and is also worse: the best of five
    settings reached 0.8679, still below the flat form's 0.8725.

    Kept at zero rather than deleted, because both ideas are ones someone will have again and
    the argument against them should be a table rather than an opinion."""

    trust_main_links: bool = True
    """Inside a `main` landmark, count linked words as content rather than as chrome.

    Link density is the selector's primary boilerplate signal, and on articles it is right:
    a run of links is navigation. On the page types where the *content is a list of links* it
    is structurally wrong, and no threshold fixes it. Measured on WCXB dev, the share of
    ground-truth words that sit inside `<a>`:

    ```
    article 0.11   documentation 0.16   forum 0.13   product 0.19
    service 0.20   collection 0.40      listing 0.49
    ```

    Half of a listing page's ground truth is link text -- the item titles -- which the
    scoring function valued at zero and then charged the block cost for. The page's own
    `<main>` is the signal that says those links are content: navigation lives in `<nav>`,
    and a link grid inside `<main>` is what the author put there for the reader.

    **Measured twice, with opposite verdicts, and the second is the one that counts.** The
    first WCXB dev run said -0.003 overall (listing +0.052, article -0.008, product -0.018,
    collection -0.020) and it was declined. That run was taken on top of the wrapper
    duplication bug (`_orphan_text`, see `dom/rich.py`), which was doubling the word count
    of a third of the articles; with that fixed the same flag reads:

    ```
                    off      on
    overall        0.803   0.810
    article        0.919   0.920
    documentation  0.884   0.906
    service        0.768   0.777
    forum          0.730   0.733
    collection     0.530   0.555
    listing        0.527   0.558
    product        0.587   0.589
    ```

    Every type improves. An experiment measured on top of a bug measures the bug."""

    group_repeats: str = "off"
    """Score repeated sibling items -- the cards of a product grid, the rows of a listing,
    the posts of a thread -- as **one unit** that pays the block cost once.

    `"off"`, `"main"` (only groups inside a `main` landmark) or `"all"`.

    Why: on WCXB dev, 66 of 117 collection pages and 39 of 99 listing pages are *over-cut* --
    the block list holds the grid (recall 0.90 before the selector) and the selector drops it
    (0.56 after). Each card is a short block, so each pays a full block cost and the run
    cannot survive a grid of forty of them. But forty cards that share one XPath template --
    `.../ul/li[n]/div/h3` -- are one thing the author laid out, not forty. Grouped, the grid
    is a single unit worth its total words minus one cost, and the run carries it.

    The risk is the sidebar: "Recent posts" is also a repeated group. `"main"` limits the
    treatment to groups the page itself places in its main content. Both settings are
    measured on WCXB dev before either ships; see the table in MEMORY.md."""

    min_group_size: int = 3
    """Fewer repeated siblings than this is not a grid."""

    group_min_share: float = 0.3
    """A repeated group is scored as one unit only when it carries at least this share of
    the page's words. A grid that *is* the page -- a collection, a listing -- clears it; a
    related-products rail or a comment list beside an article does not, and its items stay
    individually scored. Measured: with no share guard, grouping cost articles -0.015 and
    products -0.063 on WCXB dev while lifting listings +0.054."""

    min_run_share: float = 0.02
    """Refuse to return less than this share of the document's words.

    The same fail-open rule the chrome detector follows: when the selector would gut a page,
    the original is more useful than a fragment. A page that is genuinely almost all
    navigation -- a sitemap, an index -- has no main content to find, and saying so by
    returning everything is better than inventing an answer."""


# ---------------------------------------------------------------------------------------
# Site chrome
# ---------------------------------------------------------------------------------------

DEFAULT_THRESHOLD: Final[float] = 0.9
"""Share of pages a block must appear on to count as chrome. See module docstring for why
this is not worth tuning."""


MIN_PAGES: Final[int] = 6
"""Below this, repetition is not evidence of anything."""


MAX_REMOVAL: Final[float] = 0.5
"""Refuse to treat more than this share of a page as chrome.

Guards against a near-duplicate corpus. Crawling docs.pytest.org reached its version
archive -- `/en/8.2.x/`, `/en/8.1.x/`, ... -- which are near-identical pages. Their *shared
real content* then looks exactly like chrome, and detection removed 60.3% of every page.
On diverse corpora the figure is 9-37%, so a cap at 50% separates the two cases without
touching the healthy one.

When the cap trips, the page is returned untouched: a wrong removal is silent data loss,
while a missed removal is merely noise the caller can still see.
"""


SLOT_PRESENCE: Final[float] = 0.6
"""Share of pages a template slot must appear on before its variance is judged.

Lower than the text threshold on purpose: a slot only qualifies as chrome if it *also* never
varies, which is a much stronger condition than text repetition and needs less corroboration.
"""


MIN_LANDMARK_CHARS: Final[int] = 200
"""Refuse to leave less than this much text. A sitemap or index page is legitimately almost
all navigation, and returning nothing for it helps nobody.

An **absolute** floor, having first been a 5% ratio -- and the ratio was the wrong instrument,
because it lets the size of a page's footer decide whether its body is trustworthy. Measured
on WCXB, `allbirds.com` carries its entire Terms of Service and Privacy Policy in accordions
inside `<footer>`: 120,021 characters of chrome against 1,020 characters of product page.
`strip_landmarks` identified all of it correctly, the remainder came to 0.85% of the page,
the ratio guard fired, and the function returned **everything** -- precision 0.008 on that
page. The guard meant to prevent returning nothing instead forced returning 118x too much.

A thousand characters of real content is a good extraction whatever proportion of the
document it happens to be. The failure the guard exists for is a remainder near zero, and an
absolute floor names that directly. Fires on 7 of 1,497 WCXB dev pages, 4 of them product."""


MAIN_MIN_WORDS: Final[int] = 100


MAIN_MIN_SHARE: Final[float] = 0.5
"""`scope_to_main` only trusts a `<main>` that holds at least this many words *and* this
share of the page's words. Both guards are measured, not chosen.

A page declares `<main>` and then renders its content somewhere else more often than one
would hope: measured on WCXB dev, 1,000 of 1,476 pages carry `<main>` or `role="main"`, and
on 21 of them the landmark is **empty** -- a JavaScript mount point -- with the content in
the static HTML around it. Trusting those would lose the page. With the guard set at half
the page's words and 100 words:

```
guard                    scoped   mean recall of ground truth inside main   <0.5 recall
none (any <main>)          989      0.960                                     21
>=100 words                979      0.964                                     17
>=100 words, >=50% share   870      0.971                                      6
```

The six that remain are collection pages whose product grid sits beside, not inside, the
landmark. The share test is what removes the empty-mount-point case: an empty `<main>`
holds 0% of the words. The word floor catches the near-empty one."""


# ---------------------------------------------------------------------------------------
# Page type
# ---------------------------------------------------------------------------------------

DEFAULT_MIN_CONFIDENCE: Final[float] = 0.5
"""Below this the router says `unknown` rather than guessing.

Measured on its out-of-fold predictions over 1,497 labelled pages, the model is well
calibrated in the one way that matters here: above 0.5 it is right 86% of the time, and
below 0.5 it is right **44%** of the time -- a coin toss weighted the wrong way. It used to
commit at any confidence, which is how a Hacker News page became `documentation` at 24% and
a Shopify product page became `article` at 39%, each then handed the schema for a type it
was not. The floor costs 5.5% of pages their type; every consumer already treats `unknown`
as "use the default", which is the right answer for a page nobody can read confidently."""


# ---------------------------------------------------------------------------------------
# Crawling
# ---------------------------------------------------------------------------------------

MAX_SITEMAP_DOCUMENTS: Final[int] = 20
"""Sitemap indexes can nest into thousands of files. Bounded so discovery cannot itself
become the crawl."""


MAX_ANCHOR_CHARS: Final[int] = 160
"""Anchor text longer than this is a card or a whole paragraph wrapped in a link, not a
label."""


IDENTICAL_CONTENT_WARNING: Final[int] = 3
"""Distinct URLs yielding byte-identical extracted text before a warning is raised.

A gate that blocks the page from mounting -- a persona or region picker, an age gate, an
onboarding wizard -- serves the same interstitial on every route. Every other signal stays
green while this happens: the fetch succeeds, the render succeeds, geometry binds, the
profiler reports "static content looks complete". Measured on zerotoonepmtoolkit.app, whose
21 routes returned byte-identical 1,130-character output and whose crawl then reported itself
`exhausted` after one page.

The engine now opens such gates (see `RenderConfig.dismiss_gates`), so this is the net that
catches the ones it cannot open. Three is enough: two identical pages happen (a redirect
pair, a duplicated route), three is a pattern.
"""


@dataclass(frozen=True, slots=True)
class SiteConfig:
    max_pages: int = 0
    """0 means unbounded: crawl until the frontier is exhausted."""
    concurrency: int = 4
    delay_seconds: float = 0.3
    verify_inventory: bool = True
    """Check each advertised URL before crawling it. Costs one cheap request per URL and
    prevents a stale sitemap from consuming the whole page budget on 404s."""

    follow_links: bool = True
    """Discover routes by following links in addition to reading the sitemap. Both run
    always -- a sitemap is frequently stale, incomplete, or both."""

    discovery_limit: int = 400
    """Ceiling on URLs harvested by link-following before verification."""

    discovery_depth: int = 12
    """Link depth ceiling. High by default -- a deep site is still a finite one, and the
    page budget is the real bound."""

    sitemap_limit: int = 50000
    respect_robots: bool = True

    remove_chrome: bool = True
    """Emit `content_markdown` -- the page with landmarks, site chrome and boilerplate
    removed -- alongside the full Markdown. See `webgraph.content`.

    Landmarks apply from the first page. Cross-page chrome needs several pages to exist
    before it can say anything and is applied from then on. Costs nothing at crawl time --
    it is computed from blocks already extracted."""

    main_content: bool = True
    """Also draw the main-content boundary (`webgraph.main_content`) when producing
    `content_markdown`. Off, the structural steps alone run: for a crawl whose pages are
    link hubs by design, where the list of links *is* the content."""

    strategy: Strategy | None = None
    """Overrides the strategy Stage 0 recommends. Leave unset to use the measured verdict."""

    fetch: FetchConfig = field(default_factory=FetchConfig)
    render: RenderConfig = field(default_factory=RenderConfig)


# ---------------------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------------------

MAX_SECTION_CHARS: Final[int] = 6_000
"""A section longer than this is split.

Some pages have one heading and twenty thousand characters under it. Left whole, such a
section either swallows a context budget or is dropped entirely -- both of which lose the
paragraph that mattered. Splitting on paragraph boundaries keeps the pieces readable and
keeps their order.
"""


MIN_SECTION_CHARS: Final[int] = 40
"""Below this a section is a stray label, not content."""


MIN_NAME_CHARS: Final[int] = 4
"""Below this a name cannot establish identity. "API", "CLI", "Env"."""


MAX_NAME_CHARS: Final[int] = 60
"""Above this the anchor text is a sentence, not a name."""


MAX_NAME_PAGE_SHARE: Final[float] = 0.6
"""A name appearing on more than this share of pages is not discriminating.

Every page of the Flask documentation says "Flask". Linking every section on the site to one
entity produces a hub that connects everything to everything, which is the same as
connecting nothing.
"""


MIN_CODE_USES: Final[int] = 2
"""Times a heading's text must also appear as inline code before the heading counts as a
definition. `Environment` is a class because the site writes it in backticks; `Installation`
is a section because it never does."""


MIN_ANCHOR_AGREEMENT: Final[int] = 2
"""Distinct source pages that must use an anchor before it counts as the site's name for a
target. One page's phrasing is a phrasing; two pages agreeing is a name."""


CHARS_PER_TOKEN: Final[float] = 4.0
"""Rough conversion for budgeting. Deliberately approximate: the budget is a guard rail, and
tokenising precisely would tie the engine to one model's vocabulary."""


B: Final[float] = 0.75


HEADING_UBIQUITY: Final[float] = 0.5
"""Share of pages a heading must appear on before it is useless for identifying one."""


DEDUP_PREFIX_CHARS: Final[int] = 300
"""Characters of a section's opening used to recognise a near-duplicate."""


PAGE_EVIDENCE_WEIGHT: Final[float] = 0.0
"""How much of its page's total score a section inherits.

Zero: the sweep in `apply_page_evidence` found it neutral at best and harmful on the buckets
with room to improve. The parameter stays so the measurement can be repeated.
"""


FEEDBACK_DISCOUNT: Final[float] = 0.5
"""How much a section found through anchor feedback is worth, against one that matched the
question directly. Feedback should add, never displace."""


MENTION_WEIGHT: Final[float] = 0.25
"""Weight of a shared-entity edge, relative to a link.

Set by sweep, not by intuition. Entities derived from anchor consensus produce many
mentions, and at the 0.7 that structural edges get they cost recall: measured -0.7 points
on average across three sites, because a section that merely names the same subject is much
weaker evidence than a link someone chose to write. The value of these edges is between
sites, where link edges are sparse, so the weight is set to be harmless within one.
"""


HEADING_WEIGHT: Final[int] = 3
"""A heading term is worth three body terms. Headings are the author's own summary of the
section, and a query matching one is a much stronger signal than a passing mention."""


# ---------------------------------------------------------------------------------------
# Technology profiling
# ---------------------------------------------------------------------------------------

MAX_SCRIPTS: Final[int] = 4


MAX_TOTAL_BYTES: Final[int] = 3_000_000


# ---------------------------------------------------------------------------------------
# Run traces
# ---------------------------------------------------------------------------------------

_MAX_VALUE_CHARS: Final[int] = 2_000
"""Longest string kept in a trace. A page's Markdown belongs in the result, not in the record
of the run that produced it -- a trace that carries the whole corpus twice is not a trace."""


# ---------------------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Settings:
    """What a deployment can set from the outside. Read once, by `from_env`.

    Every variable is prefixed `WEBGRAPH_`. Zero means "no cap" for the caps.
    """

    max_pages: int = 0
    """`WEBGRAPH_MAX_PAGES`: hard ceiling on pages per crawl, whatever a client asks for."""

    max_concurrency: int = 0
    """`WEBGRAPH_MAX_CONCURRENCY`: ceiling on parallel fetches within one crawl."""

    max_concurrent_renders: int = 2
    """`WEBGRAPH_MAX_CONCURRENT_RENDERS`: browser pages open at once across the API."""

    max_concurrent_crawls: int = 3
    """`WEBGRAPH_MAX_CONCURRENT_CRAWLS`: crawls the API runs at once; the rest queue."""

    max_browsers: int = 6
    """`WEBGRAPH_MAX_BROWSERS`: live browsers across the whole process, roughly 150 MB
    resident each. Six suits a laptop with 16 GB; a 2 GB container cannot hold six, and the
    failure mode is the kernel killing the process, so the cap belongs where the memory
    budget is known."""

    trace_dir: Path | None = None
    """`WEBGRAPH_TRACE_DIR`: where run traces are written. The system temp directory when
    unset -- a trace is diagnostic, and a server that fills a disk with them by default has
    replaced one problem with another."""

    trace_file: Path | None = None
    """`WEBGRAPH_TRACE`: a single trace file for library and CLI use, when set."""

    graph_dir: Path | None = None
    """`WEBGRAPH_GRAPH_DIR`: where crawled graphs are kept between requests."""

    allowed_origins: tuple[str, ...] = ()
    """`WEBGRAPH_ALLOWED_ORIGINS`: browser origins the API answers, comma-separated. Never
    `*` -- this service fetches arbitrary URLs on the caller's behalf."""

    chromium_args: str = ""
    """`WEBGRAPH_CHROMIUM_ARGS`: extra flags for the browser, shell-split."""

    @classmethod
    def from_env(cls, environ: os._Environ[str] | dict[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ

        def integer(name: str, default: int) -> int:
            raw = env.get(name, "").strip()
            return int(raw) if raw else default

        def path(name: str) -> Path | None:
            raw = env.get(name, "").strip()
            return Path(raw) if raw else None

        origins = tuple(o.strip() for o in env.get("WEBGRAPH_ALLOWED_ORIGINS", "").split(",") if o.strip())
        return cls(
            max_pages=integer("WEBGRAPH_MAX_PAGES", 0),
            max_concurrency=integer("WEBGRAPH_MAX_CONCURRENCY", 0),
            max_concurrent_renders=integer("WEBGRAPH_MAX_CONCURRENT_RENDERS", 2),
            max_concurrent_crawls=integer("WEBGRAPH_MAX_CONCURRENT_CRAWLS", 3),
            max_browsers=integer("WEBGRAPH_MAX_BROWSERS", 6),
            trace_dir=path("WEBGRAPH_TRACE_DIR"),
            trace_file=path("WEBGRAPH_TRACE"),
            graph_dir=path("WEBGRAPH_GRAPH_DIR"),
            allowed_origins=origins,
            chromium_args=env.get("WEBGRAPH_CHROMIUM_ARGS", ""),
        )


SETTINGS: Final[Settings] = Settings.from_env()
"""The process's settings, read once at import. Tests that need different values build a
`Settings` of their own or monkeypatch the module-level names that consume this one."""
