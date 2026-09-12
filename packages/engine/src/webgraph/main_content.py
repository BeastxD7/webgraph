"""Select the main content from an ordered block list.

Why this exists, and why it is opt-in
--------------------------------------
This engine's promise is that it does not lose anything, and everything else in it is built
to keep that promise: the union of two fetches, geometric reading order, orphaned container
text, shadow roots. Measured, the promise holds -- recall 0.953 on WCXB where the leading
system manages 0.890, and 0.9856 on Zyte's benchmark against a best-in-field 0.990.

The cost is precision. Every point of benchmark deficit is text the engine correctly
extracted and a main-content benchmark did not want: navigation, tag strips, related-article
rails, comment threads. WCXB 0.730 against 0.859; Zyte 0.647 against 0.970.

So this module does the opposite of the rest of the engine: it **throws content away on
purpose**. That is a different promise, and it gets a different entry point rather than
becoming the default. `Document.blocks` stays complete; a caller that wants an article asks
for one.

Why a contiguous run
--------------------
Measured on Zyte's 181 pages: an oracle that picks the best **contiguous run** of the
engine's own blocks scores **F1 0.968**, against 0.647 for keeping everything. The article
body is already present, already contiguous, already in the right order -- reading order saw
to that. Nothing needs to be found. A boundary needs to be drawn.

(An earlier figure of 0.945 was measured before `strip_landmarks` was applied first, and is
superseded. The ceiling is higher than it looked, so the headroom above the shipped 0.856 is
real rather than exhausted.)

That makes the problem a maximum-subarray one: give every block a value, positive for prose
and negative for chrome, and take the run whose total is greatest. Kadane's algorithm does it
in one pass, and the "contiguous" constraint is doing real work -- it is what stops a scoring
function from cherry-picking a paragraph out of the footer.

The scoring, and the thing that turned out not to be true
---------------------------------------------------------
Link density was chosen as the primary signal following Kohlschutter et al. (WSDM 2010),
whose central finding is that shallow text features -- above all the share of words inside
anchors -- separate boilerplate from content about as well as anything structural. It does
separate boilerplate from content, and it is why a navigation strip scores negative.

**But it does not separate at the boundary**, which is where this function actually has to
be right. Measured over the optimal runs on 181 Zyte pages, link density is **0.000 median on
both sides of the edge**. The block sitting just outside the run is *itself a paragraph* on
113 of 181 start edges and 126 of 171 end edges -- bylines, "Share this", photo captions,
related-article teasers. The real boundary is prose against prose.

What does separate is length (34 words median inside, 6 outside), and sentence-ness is the
best complement to it: requiring at least one sentence-terminating mark alongside a length
floor lifts boundary precision from 0.663 to 0.735. Six shallow reweights were swept --
sentence bonus, stopword gate, concave length reward, hysteresis -- and **none beat the
shipped form by more than 0.003**. The remaining gap to the 0.968 ceiling is structural, not
a missing feature, so the next gain will come from a different mechanism rather than a better
weight.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

from webgraph.types import Block, BlockKind

__all__ = [
    "MainContentConfig",
    "content_value",
    "link_density",
    "select_main_content",
    "word_count",
]

_MARKDOWN_LINK: Final[re.Pattern[str]] = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_WORD: Final[re.Pattern[str]] = re.compile(r"\S+")

_SCRIPTIO_CONTINUA: Final[re.Pattern[str]] = re.compile(
    "["
    "\u3040-\u30ff"    # hiragana, katakana
    "\u3400-\u4dbf"    # CJK unified ideographs extension A
    "\u4e00-\u9fff"    # CJK unified ideographs
    "\uf900-\ufaff"    # CJK compatibility ideographs
    "\uac00-\ud7af"    # hangul syllables
    "\u0e00-\u0e7f"    # thai
    "]"
)
"""Scripts written without spaces between words.

Splitting on whitespace counts an entire Chinese paragraph as **one word**, and every
threshold in this module is denominated in words. Measured on WebMainBench: **8.1% of pages
collapsed to a single block** under the selector, and **70% of those were CJK** -- a 48
character Chinese paragraph scored -12.0, identical to a nav link, so Kadane rejected the
whole page. `min_run_share` could not catch it either, being measured in the same broken
unit.

This is the same class of failure as the reading direction defaulting to left-to-right: an
assumption about English that is silently catastrophic elsewhere, and invisible to an
English corpus.
"""


def word_count(text: str) -> int:
    '''Words, counting each character of a space-less script as one.

    One CJK character carries roughly the information of one short English word, so counting
    them individually puts a Chinese paragraph on the same scale as an English one and lets a
    single `block_cost` serve both. Mixed text is handled by removing the space-less
    characters and splitting what remains, so a Japanese sentence quoting an English product
    name is counted correctly on both halves.
    '''
    dense = len(_SCRIPTIO_CONTINUA.findall(text))
    spaced = len(_WORD.findall(_SCRIPTIO_CONTINUA.sub(" ", text)))
    return dense + spaced


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


def link_density(block: Block) -> float:
    """Share of a block's words that sit inside a link, in [0, 1].

    Read from `rich_text`, which preserves inline Markdown; `text` has already flattened
    `[label](url)` to `label` and cannot answer this. A block with no `rich_text` had no
    inline markup worth recording, so its density is zero.
    """
    words = word_count(block.text)
    if not words:
        return 0.0
    rich = block.rich_text
    if not rich:
        return 0.0
    linked = sum(word_count(m.group(1)) for m in _MARKDOWN_LINK.finditer(rich))
    return min(linked / words, 1.0)


def content_value(block: Block, config: MainContentConfig) -> float:
    """How much this block is worth to a run, in words. Negative means it costs.

    Unlinked words are the currency. A fifty-word paragraph with no links is worth fifty; a
    fifty-word navigation strip that is all links is worth nothing and then pays the block
    cost, so it ends a run.
    """
    words = word_count(block.text)

    if block.kind is BlockKind.IMAGE:
        # An image contributes its alt text at most, and alt text on a product grid is a
        # list of filenames. It never anchors a run.
        return -config.block_cost

    density = 0.0 if (config.trust_main_links and block.in_main) else link_density(block)
    free = words * (1.0 - density)

    if block.kind is BlockKind.HEADING:
        return free + config.heading_bonus - config.block_cost

    if block.kind in (BlockKind.TABLE, BlockKind.CODE):
        # Never negative, so a table or a code block can never *end* a run.
        #
        # A `<pre>` on a page is deliberate; nobody decorates with code. But a short snippet
        # scores few words, went negative against the block cost, and Kadane then cut the run
        # at it. Measured on WebMainBench, turning the selector on cost **-0.126 code_edit**,
        # and 13 pages -- Stack Overflow, Rosalind, the GTK docs -- accounted for 99% of the
        # drop, 8 of them falling to 0.000. On those pages the code sits just outside the
        # densest prose, separated by the "share / edit / follow" chrome between them.
        #
        # Floored at zero rather than given a bonus: neutral means a code block extends a run
        # that has already started without being able to anchor a spurious one of its own, so
        # this cannot pull a stray snippet out of a footer.
        return max(max(free, words * config.structural_credit) - config.block_cost, 0.0)

    return free - config.block_cost


_INDEX: Final[re.Pattern[str]] = re.compile(r"\[\d+\]")


def _repeat_groups(blocks: Sequence[Block], config: MainContentConfig) -> list[int]:
    """Assign each block a group id: blocks inside repeated sibling containers share one; -1
    otherwise.

    A repeated container is an XPath prefix that ends in a positional index and occurs with
    at least `min_group_size` distinct indices -- `/main/ul/li[*]` when `li[1]`, `li[2]`,
    `li[3]`... each hold blocks. Every block under the container joins the group whatever its
    tag, which is what makes a card's title, price and blurb one thing: an earlier version
    keyed on the block's full path template, so the titles formed one group and the prices
    another, interleaved, and nothing ever merged.

    Candidates are tried from the innermost index outward and the first that qualifies
    wins, so a paragraph in `div[3]/p[2]` groups with its sibling paragraphs and not with
    every top-level `div[*]` on the page -- the coarser repetition would make the whole
    page one unit, which is the leak this must not cause.
    """
    if config.group_repeats == "off":
        return [-1] * len(blocks)
    only_main = config.group_repeats == "main"

    # Container prefix -> the distinct indices seen under it, and the blocks under it.
    positions: dict[str, set[str]] = {}
    members: dict[str, list[int]] = {}
    candidates: list[list[str]] = []
    for index, block in enumerate(blocks):
        own: list[str] = []
        if not (only_main and not block.in_main):
            for match in reversed(list(_INDEX.finditer(block.xpath))):
                prefix = block.xpath[: match.start()] + "[*]"
                own.append(prefix)
                positions.setdefault(prefix, set()).add(match.group(0))
                members.setdefault(prefix, []).append(index)
        candidates.append(own)

    total_words = sum(word_count(b.text) for b in blocks) or 1
    group_words = {
        prefix: sum(word_count(blocks[i].text) for i in indices)
        for prefix, indices in members.items()
    }

    def qualifies(prefix: str) -> bool:
        return (
            len(positions[prefix]) >= config.min_group_size
            and group_words[prefix] >= config.group_min_share * total_words
        )

    groups = [-1] * len(blocks)
    ids: dict[str, int] = {}
    for index, own in enumerate(candidates):
        for prefix in own:  # innermost first
            if qualifies(prefix):
                groups[index] = ids.setdefault(prefix, len(ids))
                break
    return groups


def select_main_content(
    blocks: Sequence[Block], *, config: MainContentConfig | None = None
) -> list[Block]:
    """Return the contiguous run of `blocks` that looks like the page's main content.

    Falls back to the whole list when no run is clearly better -- see `min_run_share`.
    """
    config = config or MainContentConfig()
    if len(blocks) < 2:
        return list(blocks)

    if config.adaptive_cost:
        mean_words = sum(word_count(b.text) for b in blocks) / len(blocks)
        cost = min(max(config.cost_ratio * mean_words, config.cost_floor), config.cost_ceiling)
        config = replace(config, block_cost=cost)

    values = [content_value(block, config) for block in blocks]

    # Units: consecutive blocks of one repeated group are scored together, paying the block
    # cost once -- see `MainContentConfig.group_repeats`. With grouping off every block is
    # its own unit and this is plain Kadane over blocks.
    groups = _repeat_groups(blocks, config)
    units: list[tuple[int, int, float]] = []  # (first block, last block + 1, value)
    index = 0
    while index < len(blocks):
        end = index + 1
        if groups[index] >= 0:
            while end < len(blocks) and groups[end] == groups[index]:
                end += 1
        if end - index == 1:
            units.append((index, end, values[index]))
        else:
            # The members keep their own scores -- link density still says what it says --
            # and the unit pays the block cost once instead of once per card.
            members = end - index
            units.append(
                (index, end, sum(values[index:end]) + (members - 1) * config.block_cost)
            )
        index = end

    # Kadane, tracking the winning bounds. Ties keep the earlier, longer run: an article
    # sits above the comments, and preferring the earlier span is the tie-break that says so.
    # Kadane, with a tolerance: the run restarts only once its accumulated deficit exceeds
    # `bridge`, rather than the instant the total dips below zero. See `MainContentConfig`.
    tolerance = -config.bridge * config.block_cost
    best_total = float("-inf")
    best_units = (0, len(units))
    running = 0.0
    start = 0
    for position, (_, _, value) in enumerate(units):
        if running < tolerance:
            running = value
            start = position
        else:
            running += value
        if running > best_total:
            best_total = running
            best_units = (start, position + 1)

    # Trim the boundaries back to content. A bridged run may open or close on the chrome it
    # was allowed to absorb, and a leading "share edit follow" is not the start of an article.
    first, last = best_units
    while first < last - 1 and units[first][2] <= 0:
        first += 1
    while last - 1 > first and units[last - 1][2] <= 0:
        last -= 1
    best = (units[first][0], units[last - 1][1])

    # A run worth nothing is not a run. When every block scores negative -- a sitemap, an
    # index, a link hub -- Kadane still returns something: the single least-negative block.
    # That is a meaningless fragment presented as an answer, and the share guard below does
    # not catch it, because on a page of uniformly tiny blocks one block is a respectable
    # share of the words. The page simply has no main content, and saying so by returning
    # everything is the honest result.
    if best_total <= 0:
        return list(blocks)

    selected = list(blocks[best[0] : best[1]])
    if not selected:
        return list(blocks)

    total_words = sum(word_count(b.text) for b in blocks)
    kept_words = sum(word_count(b.text) for b in selected)
    if total_words and kept_words < total_words * config.min_run_share:
        return list(blocks)

    return selected
