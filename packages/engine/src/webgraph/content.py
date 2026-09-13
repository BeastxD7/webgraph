"""The one place that decides what a page's *content* is, as opposed to its *text*.

`Document.blocks` is complete by construction and stays that way: the union of two fetches,
geometric reading order, orphaned container text, shadow roots. Everything downstream that
wants "the page" reads it. But most consumers want the *article*, the *product*, the *docs
page* -- the part a reader came for -- and three separate mechanisms existed to find it:

1. `strip_landmarks` drops the `<nav>` and `<footer>` the page declared.
2. `scope_to_main` keeps only the `<main>` landmark, when the page declares a trustworthy one.
3. `strip_site_chrome` drops blocks repeated across a site's pages, once enough pages exist.
4. `select_main_content` draws a boundary around the densest run of prose (measured: +0.065
   F1 across seven page types on WCXB, +0.225 on Zyte's articles).

Before this module, the crawl applied 1 and 2, the single-page API applied only 1, and the
third -- the one with the largest measured gain -- was applied by nothing except benchmarks.
Finished work that no product path called. Two entry points to "the content" that disagreed
with each other is also a bug in its own right: the same page asked for once and asked for
as part of its site should not come back different.

`select_content` is now that decision, in order, with one result type that says which steps
fired. Both the API and the crawl call it. The order is load-bearing: landmarks and chrome
are removed *before* the selector runs, because the selector's per-block cost adapts to the
page's mean block length, and a page still carrying its navigation has a shorter mean.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from webgraph import config
from webgraph.blockmodel import BlockModel, default_model, select_by_model
from webgraph.boilerplate import (
    SiteChrome,
    scope_to_main,
    strip_comments,
    strip_landmarks,
    strip_site_chrome,
)
from webgraph.main_content import MainContentConfig, select_main_content
from webgraph.types import Block, BlockKind

__all__ = ["SHIPPED_MODEL", "ContentSelection", "select_content"]


class _ShippedModel:
    """`select_content(model=SHIPPED_MODEL)`: use the model the engine ships.

    Not the default. A plain `None` cannot express "the shipped one" because `None` already
    means "no model, run the boundary step", and a caller needs to be able to say both.
    """

    def __repr__(self) -> str:
        return "SHIPPED_MODEL"


SHIPPED_MODEL: Final = _ShippedModel()


@dataclass(frozen=True, slots=True)
class ContentSelection:
    """What was kept, and which steps removed something.

    A consumer that only wants the blocks reads `blocks`. One that reports on the
    extraction -- the API's response, the crawl's page event -- reads the flags, so that
    "this page's content is 40% of its text" comes with the reason.
    """

    blocks: list[Block]
    total: int
    """How many blocks the document had before anything was removed."""

    landmarks_removed: int = 0
    main_scoped_removed: int = 0
    chrome_removed: int = 0
    main_content_removed: int = 0
    block_model_removed: int = 0
    title_restored: bool = False
    """Whether the boundary step cut the page's own title and it was put back."""
    """Blocks the trained per-block model dropped, when `select_content` was given one.
    Mutually exclusive with `main_content_removed`: the model replaces the boundary step."""

    @property
    def kept(self) -> int:
        return len(self.blocks)

    @property
    def changed(self) -> bool:
        """Whether any step removed anything. When False the content *is* the document, and
        a consumer need not emit it twice."""
        return self.kept != self.total

    @property
    def methods(self) -> tuple[str, ...]:
        """The steps that removed something, in the order they ran. Stable names, since the
        API reports them."""
        names: list[str] = []
        if self.landmarks_removed:
            names.append("landmarks")
        if self.main_scoped_removed:
            names.append("main-landmark")
        if self.chrome_removed:
            names.append("site-chrome")
        if self.main_content_removed:
            names.append("main-content")
        if self.block_model_removed:
            names.append("block-model")
        return tuple(names)


def select_content(
    blocks: Sequence[Block],
    *,
    chrome: SiteChrome | None = None,
    main_content: bool = True,
    config: MainContentConfig | None = None,
    model: BlockModel | _ShippedModel | None = None,
    title: str = "",
) -> ContentSelection:
    """Reduce a complete block list to the page's content.

    `chrome` is the cross-page profile a crawl has built, or None for a page seen alone.
    `main_content=False` stops after the structural steps -- for a caller that wants
    navigation and footers gone but every paragraph kept, such as a sitemap or an index page
    whose "content" is the list of links.

    `model` decides how the last step draws the line. The default, `None`, is the contiguous
    boundary of `select_main_content`. `SHIPPED_MODEL` asks for the trained per-block
    classifier in `webgraph.blockmodel`, and a `BlockModel` uses that one.

    `config` configures the boundary step only. Passing one selects that step, because a
    config the model cannot read would otherwise be silently dropped; passing a `config` and
    a model together is a contradiction and raises.

    **Why the boundary step is still the default, given that the model scores higher.**
    Out of fold on WCXB dev the model is better on six of seven page types and +0.029
    overall (0.810 -> 0.839), and on Zyte it holds (0.895 -> 0.897). Both of those score a
    bag of words. On WebMainBench, which scores Markdown by edit distance and grades tables
    and code in their own columns, the model is **worse**: 0.622 -> 0.586 overall, and worse
    on every page slice including prose-only pages with no table or code in them.

    Looking at the pages rather than the means, it fails two ways a word-bag metric cannot
    charge it for. It drops most of some long documents -- one 13,591-character recipe the
    boundary step extracts at 0.996 comes back as 1,715 characters -- and it keeps comment
    and navigation furniture ("Add your comments...", "User Name Required", a font-size
    control) that the boundary step's contiguity excludes. Missing words cost a little
    recall and the discarded chrome buys precision back, so word-F1 nets out positive; an
    edit distance sees both immediately.

    So the model is real work with a real gain on one kind of metric, and it is not yet
    something to put in front of every user by default. `benchmark/train/README.md` has the
    numbers on both sides.

    `title` is the document's `<title>`. When given, the block that carries it is never
    removed by the last step. The boundary is drawn around prose density, and a page's title
    line is often the least prose-like thing on it -- on a Hacker News thread it is a link
    followed by "143 points by ...", and the boundary started at the first comment, cutting
    the one line that says what the thread is about. The structural steps are unaffected:
    a title inside a `<nav>` is the site's name, not the page's.

    Never returns an empty list for a non-empty input: each step falls open to what it was
    given when it would remove everything, and `select_main_content` refuses to return a
    fragment (see `MainContentConfig.min_run_share`).
    """
    total = len(blocks)
    kept = strip_landmarks(list(blocks))
    landmarks_removed = total - len(kept)

    if (config is None or config.strip_comments) and main_content:
        before = len(kept)
        kept = strip_comments(kept)
        landmarks_removed += before - len(kept)

    before = len(kept)
    kept = scope_to_main(kept)
    main_scoped_removed = before - len(kept)

    chrome_removed = 0
    if chrome is not None and chrome.active:
        before = len(kept)
        kept = strip_site_chrome(kept, chrome)
        chrome_removed = before - len(kept)

    # `config` configures the boundary step and means nothing to the model, so asking for
    # both is a contradiction rather than a precedence question. It raises instead of
    # silently dropping one, which is the kind of bug nothing catches.
    if config is not None and model is not None:
        raise ValueError(
            "select_content: `config` configures `select_main_content` and `model` replaces "
            "it; pass one or the other"
        )
    resolved = default_model() if isinstance(model, _ShippedModel) else model

    main_content_removed = 0
    block_model_removed = 0
    title_restored = False
    structural = kept
    if resolved is not None and main_content:
        before = len(kept)
        kept = select_by_model(kept, resolved)
        block_model_removed = before - len(kept)
    elif main_content:
        before = len(kept)
        kept = select_main_content(kept, config=config)
        main_content_removed = before - len(kept)
    if main_content and title:
        kept, title_restored = _restore_title(structural, kept, title)
        restored = 1 if title_restored else 0
        if title_restored:
            kept, lead = _restore_lead(structural, kept)
            restored += lead
        if resolved is not None:
            block_model_removed -= restored
        else:
            main_content_removed -= restored

    return ContentSelection(
        blocks=kept,
        total=total,
        landmarks_removed=landmarks_removed,
        main_scoped_removed=main_scoped_removed,
        chrome_removed=chrome_removed,
        main_content_removed=main_content_removed,
        block_model_removed=block_model_removed,
        title_restored=title_restored,
    )


_LEAD_MAX_BLOCKS: Final[int] = config.CONTENT_LEAD_MAX_BLOCKS
_LEAD_MAX_LIST_SHARE: Final[float] = config.CONTENT_LEAD_MAX_LIST_SHARE


def _restore_lead(candidates: list[Block], kept: list[Block]) -> tuple[list[Block], int]:
    """Put back what sits between a restored title and the body it was cut from.

    `_restore_title` puts the title back alone, which leaves a hole: the boundary step that
    cut the title also cut everything between it and the first dense paragraph, and that
    is the lead -- the byline, the standfirst, the source line, the opening sentence.
    Measured on docs.python.org/3/library/functools.html: the run began at the fourth
    paragraph, so "The functools module is for higher-order functions..." -- the sentence
    that says what the page is about -- was missing while the title above it was restored.

    The gap between the title and the run is restored whole when it is short and made of
    prose, not a list: a menu that happens to sit under the title is the one thing that
    lives there and is not lead, and it announces itself by being list items.
    """
    kept_ids = {id(block) for block in kept}
    positions = [i for i, block in enumerate(candidates) if id(block) in kept_ids]
    if len(positions) < 2:
        return kept, 0
    title_at = positions[0]
    body_at = positions[1]
    gap = candidates[title_at + 1 : body_at]
    if not gap or len(gap) > _LEAD_MAX_BLOCKS:
        return kept, 0
    lists = sum(1 for block in gap if block.kind is BlockKind.LIST_ITEM)
    if lists / len(gap) > _LEAD_MAX_LIST_SHARE:
        return kept, 0
    kept_ids.update(id(block) for block in gap)
    return [block for block in candidates if id(block) in kept_ids], len(gap)


def _fold(text: str) -> str:
    return " ".join(text.lower().split())


def _title_core(title: str) -> str:
    """The page's own name out of its `<title>`: the part before the site separator."""
    wanted = _fold(title)
    # "Nvidia is the central bank of AI | Hacker News": the part before the separator is
    # the page's name; the part after is the site's. The block on the page carries the
    # former, usually with something else attached ("(economist.com)"), so the comparison
    # is against the core, not the whole.
    core = wanted
    for separator in (" | ", " - ", " \u2013 ", " \u2014 ", " :: ", " \u00b7 "):
        if separator in core:
            head, _, tail = core.rpartition(separator)
            if len(head) >= 8 and len(tail.split()) <= 5:
                core = head
            break
    return core if len(core) >= 8 else ""


def _title_matches(block: Block, core: str) -> bool:
    text = _fold(block.text)
    return 8 <= len(text) <= 300 and (core in text or text in core)


def _title_block(blocks: Sequence[Block], title: str) -> Block | None:
    """The block that carries the page's title: the heading when there is one, else the
    longest match. jpost.com's title is "... - Breaking News - The Jerusalem Post", and the
    first block containing a piece of it was the "BREAKING NEWS" kicker, not the headline."""
    core = _title_core(title)
    if not core:
        return None
    matches = [block for block in blocks if _title_matches(block, core)]
    if not matches:
        return None
    return max(matches, key=lambda block: (block.kind is BlockKind.HEADING, len(block.text)))


def _restore_title(
    candidates: list[Block], kept: list[Block], title: str
) -> tuple[list[Block], bool]:
    """Put the page's title block back if the last step cut it, keeping document order.

    The title block is a candidate whose text the `<title>` contains, or which contains the
    `<title>` with its site suffix removed. Both directions, because a `<title>` is usually
    "Page title | Site" and the block is usually just "Page title" -- but on some sites the
    block is the longer of the two.
    """
    core = _title_core(title)
    if not core:
        return kept, False

    # If the content already carries the title, nothing was cut. Restoring a second copy
    # from a breadcrumb or a "you are here" strip would add the very chrome the earlier
    # steps removed.
    if any(_title_matches(block, core) for block in kept):
        return kept, False
    kept_ids = {id(block) for block in kept}
    cut = _title_block([block for block in candidates if id(block) not in kept_ids], title)
    if cut is None:
        return kept, False
    # Rebuilt from `candidates` so the block lands where it was, in whatever order the
    # document is in -- geometric or DOM. Sorting by `dom_index` would undo a geometric
    # ordering for every block, not just this one.
    kept_ids.add(id(cut))
    return [block for block in candidates if id(block) in kept_ids], True
