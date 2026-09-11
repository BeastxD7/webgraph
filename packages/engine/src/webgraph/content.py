"""The one place that decides what a page's *content* is, as opposed to its *text*.

`Document.blocks` is complete by construction and stays that way: the union of two fetches,
geometric reading order, orphaned container text, shadow roots. Everything downstream that
wants "the page" reads it. But most consumers want the *article*, the *product*, the *docs
page* -- the part a reader came for -- and three separate mechanisms existed to find it:

1. `strip_landmarks` drops `<nav>`, `<header>`, `<footer>`, `<aside>` the page declared.
2. `strip_site_chrome` drops blocks repeated across a site's pages, once enough pages exist.
3. `select_main_content` draws a boundary around the densest run of prose (measured: +0.065
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

from webgraph.boilerplate import SiteChrome, strip_landmarks, strip_site_chrome
from webgraph.main_content import MainContentConfig, select_main_content
from webgraph.types import Block

__all__ = ["ContentSelection", "select_content"]


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
    chrome_removed: int = 0
    main_content_removed: int = 0

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
        if self.chrome_removed:
            names.append("site-chrome")
        if self.main_content_removed:
            names.append("main-content")
        return tuple(names)


def select_content(
    blocks: Sequence[Block],
    *,
    chrome: SiteChrome | None = None,
    main_content: bool = True,
    config: MainContentConfig | None = None,
) -> ContentSelection:
    """Reduce a complete block list to the page's content.

    `chrome` is the cross-page profile a crawl has built, or None for a page seen alone.
    `main_content=False` stops after the structural steps -- for a caller that wants
    navigation and footers gone but every paragraph kept, such as a sitemap or an index page
    whose "content" is the list of links.

    Never returns an empty list for a non-empty input: each step falls open to what it was
    given when it would remove everything, and `select_main_content` refuses to return a
    fragment (see `MainContentConfig.min_run_share`).
    """
    total = len(blocks)
    kept = strip_landmarks(list(blocks))
    landmarks_removed = total - len(kept)

    chrome_removed = 0
    if chrome is not None and chrome.active:
        before = len(kept)
        kept = strip_site_chrome(kept, chrome)
        chrome_removed = before - len(kept)

    main_content_removed = 0
    if main_content:
        before = len(kept)
        kept = select_main_content(kept, config=config)
        main_content_removed = before - len(kept)

    return ContentSelection(
        blocks=kept,
        total=total,
        landmarks_removed=landmarks_removed,
        chrome_removed=chrome_removed,
        main_content_removed=main_content_removed,
    )
