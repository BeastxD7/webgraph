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

from webgraph.blockmodel import BlockModel, default_model, select_by_model
from webgraph.boilerplate import SiteChrome, scope_to_main, strip_landmarks, strip_site_chrome
from webgraph.main_content import MainContentConfig, select_main_content
from webgraph.types import Block

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

    Never returns an empty list for a non-empty input: each step falls open to what it was
    given when it would remove everything, and `select_main_content` refuses to return a
    fragment (see `MainContentConfig.min_run_share`).
    """
    total = len(blocks)
    kept = strip_landmarks(list(blocks))
    landmarks_removed = total - len(kept)

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
    if resolved is not None and main_content:
        before = len(kept)
        kept = select_by_model(kept, resolved)
        block_model_removed = before - len(kept)
    elif main_content:
        before = len(kept)
        kept = select_main_content(kept, config=config)
        main_content_removed = before - len(kept)

    return ContentSelection(
        blocks=kept,
        total=total,
        landmarks_removed=landmarks_removed,
        main_scoped_removed=main_scoped_removed,
        chrome_removed=chrome_removed,
        main_content_removed=main_content_removed,
        block_model_removed=block_model_removed,
    )
