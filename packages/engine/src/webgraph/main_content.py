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
from dataclasses import replace
from typing import Final

from webgraph.config import (
    MainContentConfig as MainContentConfig,
)
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
