"""Cross-page boilerplate detection.

Measured on real crawls: 37% of all text on books.toscrape.com is site chrome, 8.8% on
docs.pytest.org. The tests below pin the behaviour that makes that safe to act on.
"""

from __future__ import annotations

from webgraph.boilerplate import (
    DEFAULT_THRESHOLD,
    MIN_PAGES,
    detect_boilerplate,
    detect_site_chrome,
    strip_boilerplate,
    strip_site_chrome,
)
from webgraph.types import Block, BlockKind


def block(text: str, kind: BlockKind = BlockKind.PARAGRAPH, level: int = 0) -> Block:
    return Block(text=text, tag="p", xpath="/p", dom_index=0, kind=kind, level=level)


def page(*texts: str) -> list[Block]:
    return [block(t) for t in texts]


NAV = ["Home", "Products", "About", "Contact"]


def site(unique_per_page: list[str]) -> list[list[Block]]:
    return [page(*NAV, text) for text in unique_per_page]


class TestDetection:
    def test_finds_repeated_chrome(self) -> None:
        profile = detect_boilerplate(site([f"article {i}" for i in range(10)]))
        assert profile.active
        for nav in NAV:
            assert nav.casefold() in profile.keys

    def test_unique_content_is_never_chrome(self) -> None:
        profile = detect_boilerplate(site([f"article {i}" for i in range(10)]))
        assert "article 3" not in profile.keys

    def test_too_few_pages_yields_nothing(self) -> None:
        """Repetition across three pages is not evidence."""
        profile = detect_boilerplate(site(["a", "b", "c"]))
        assert not profile.active
        assert profile.keys == frozenset()

    def test_repeats_within_one_page_do_not_inflate(self) -> None:
        """A footer link appearing three times on one page is still one page's worth."""
        pages = [page("dup", "dup", "dup", f"unique {i}") for i in range(MIN_PAGES + 2)]
        pages[0] = page("dup", "dup", "dup", "unique 0")
        profile = detect_boilerplate([page("only here", "only here", f"u{i}") if i == 0
                                      else page(f"u{i}") for i in range(MIN_PAGES + 2)])
        assert "only here" not in profile.keys

    def test_threshold_is_insensitive_in_the_middle(self) -> None:
        """50%, 70% and 90% agreed exactly on both measured sites -- chrome is all-or-none."""
        pages = site([f"a{i}" for i in range(20)])
        keys = {detect_boilerplate(pages, threshold=t).keys for t in (0.5, 0.7, 0.9)}
        assert len(keys) == 1

    def test_default_threshold_is_the_conservative_end(self) -> None:
        assert DEFAULT_THRESHOLD >= 0.9


class TestStripping:
    def test_removes_chrome_keeps_content(self) -> None:
        pages = site([f"article {i}" for i in range(10)])
        profile = detect_boilerplate(pages)
        kept = strip_boilerplate(pages[0], profile)
        assert [b.text for b in kept] == ["article 0"]

    def test_inactive_profile_changes_nothing(self) -> None:
        pages = site(["a", "b", "c"])
        profile = detect_boilerplate(pages)
        assert strip_boilerplate(pages[0], profile) == pages[0]

    def test_page_own_leading_heading_survives(self) -> None:
        """A category page titled 'Travel' beside a sidebar link 'Travel' must keep its
        title -- it is the only line identifying the page."""
        pages = [
            [block("Travel", BlockKind.HEADING, 1), *page(*NAV), block(f"body {i}")]
            for i in range(10)
        ]
        pages[0] = [block("Travel", BlockKind.HEADING, 1), *page(*NAV), block("unique body")]
        profile = detect_boilerplate(pages)
        kept = strip_boilerplate(pages[0], profile)
        assert kept[0].text == "Travel"
        assert kept[0].kind is BlockKind.HEADING

    def test_page_that_is_all_chrome_is_left_alone(self) -> None:
        """A sitemap or index page is mostly navigation; an empty document is worse."""
        pages = [page(*NAV, f"x{i}") for i in range(10)]
        profile = detect_boilerplate(pages)
        all_nav = page(*NAV)
        assert strip_boilerplate(all_nav, profile) == all_nav


class TestTemplateDifferencing:
    """Slot-variance detection: a template position that never varies is chrome.

    Stronger than text repetition -- it will not drop a page's unique content merely because
    the same words appear elsewhere on the site. Measured mean F across four sites:
    raw 0.725 -> 0.760, with recall unchanged on every one.
    """

    def _pages(self, n: int = 10) -> list[list[Block]]:
        pages = []
        for i in range(n):
            pages.append([
                Block(text="Site Name", tag="div", xpath="/html/body/header/div[1]",
                      dom_index=0),
                Block(text=f"Article {i}", tag="h1", xpath="/html/body/main/h1",
                      dom_index=1, kind=BlockKind.HEADING, level=1),
                Block(text=f"Body text for article {i}", tag="p",
                      xpath="/html/body/main/p[1]", dom_index=2),
            ])
        return pages

    def test_static_slot_is_chrome(self) -> None:
        chrome = detect_site_chrome(self._pages())
        assert "/html/body/header/div[1]" in chrome.slots

    def test_varying_slot_is_not_chrome(self) -> None:
        """The <h1> recurs on every page but holds different text -- that is a content slot."""
        chrome = detect_site_chrome(self._pages())
        assert "/html/body/main/h1" not in chrome.slots
        assert "/html/body/main/p[1]" not in chrome.slots

    def test_stripping_keeps_content_removes_chrome(self) -> None:
        pages = self._pages()
        chrome = detect_site_chrome(pages)
        kept = [b.text for b in strip_site_chrome(pages[0], chrome)]
        assert "Site Name" not in kept
        assert "Article 0" in kept
        assert "Body text for article 0" in kept

    def test_too_few_pages_is_inactive(self) -> None:
        chrome = detect_site_chrome(self._pages(3))
        assert not chrome.active
        assert strip_site_chrome(self._pages(3)[0], chrome) == self._pages(3)[0]


class TestNearDuplicateGuard:
    """Near-identical pages make shared *content* look like chrome.

    Crawling docs.pytest.org reached its version archive (/en/8.2.x/, /en/8.1.x/, ...).
    Detection removed 60.3% of every page -- their shared real content. Diverse corpora sit
    at 9-37%, so a 50% cap separates the cases.
    """

    def test_identical_pages_are_left_alone(self) -> None:
        same = [
            Block(text=f"shared paragraph {j}", tag="p", xpath=f"/html/body/p[{j}]", dom_index=j)
            for j in range(10)
        ]
        pages = [list(same) for _ in range(10)]
        chrome = detect_site_chrome(pages)
        kept = strip_site_chrome(pages[0], chrome)
        assert len(kept) == len(pages[0]), "near-duplicate corpus must not be gutted"

    def test_healthy_corpus_still_strips(self) -> None:
        pages = [
            [Block(text="Nav", tag="div", xpath="/html/body/nav", dom_index=0),
             Block(text=f"unique article body number {i} with plenty of distinct words here",
                   tag="p", xpath="/html/body/main/p", dom_index=1)]
            for i in range(10)
        ]
        chrome = detect_site_chrome(pages)
        kept = strip_site_chrome(pages[0], chrome)
        assert [b.text for b in kept] == [pages[0][1].text]
