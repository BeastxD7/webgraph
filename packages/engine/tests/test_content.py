"""`select_content`: the one decision about what a page's content is.

Before this module the crawl removed landmarks and site chrome, the single-page API removed
landmarks only, and the main-content selector -- the step with the largest measured gain --
was called by benchmarks and nothing else. The same page asked for alone and asked for as
part of its site came back different, and the finished precision work was not shipped.

These tests pin the composition: the order the steps run in, that each step is reported,
and that the whole thing fails open rather than returning a fragment.

The last step is the contiguous boundary of `select_main_content` by default;
`model=SHIPPED_MODEL` asks for the trained per-block classifier instead. Both are exercised
here, because both ship. The boundary step is the default despite scoring lower on WCXB:
see `select_content`'s docstring for the WebMainBench result that decided it.
"""

from __future__ import annotations

import pytest

from webgraph.boilerplate import MIN_PAGES, detect_site_chrome
from webgraph.content import SHIPPED_MODEL, select_content
from webgraph.main_content import MainContentConfig
from webgraph.types import Block, BlockKind

PROSE = (
    "The quick brown fox jumped over the lazy dog and continued running through the "
    "field until it reached the far treeline where it finally stopped to rest a while."
)


def block(
    text: str,
    *,
    xpath: str,
    index: int,
    kind: BlockKind = BlockKind.PARAGRAPH,
    rich: str | None = None,
) -> Block:
    return Block(text=text, tag="p", xpath=xpath, dom_index=index, kind=kind, rich_text=rich)


def page(unique: str) -> list[Block]:
    """A page with a `<nav>`, a repeated footer line, a byline strip, and an article."""
    return [
        block(
            "Home About Pricing",
            xpath="/html/body/nav/a",
            index=0,
            rich="[Home](/) [About](/a) [Pricing](/p)",
        ),
        # Varies per page so the cross-page chrome detector cannot claim it; it is the
        # selector's to remove, which is what the method-order test relies on.
        block(f"Share Tweet Email {unique}", xpath="/html/body/div/p[1]", index=1,
              rich=f"[Share](/s) [Tweet](/t) [Email](/e) {unique}"),
        *[
            block(f"{PROSE} {unique} {i}.", xpath=f"/html/body/div/article/p[{i}]", index=2 + i)
            for i in range(1, 6)
        ],
        block("Copyright Example Corp. All rights reserved.", xpath="/html/body/div/p[9]", index=9),
        block("Terms Privacy", xpath="/html/body/footer/p", index=10,
              rich="[Terms](/t) [Privacy](/p)"),
    ]


class TestComposition:
    def test_landmarks_go_first_and_are_reported(self) -> None:
        selection = select_content(page("a"), main_content=False)
        texts = [b.text for b in selection.blocks]
        assert "Home About Pricing" not in texts
        assert "Terms Privacy" not in texts
        assert selection.landmarks_removed == 2
        assert selection.methods == ("landmarks",)

    def test_the_boundary_step_runs_after_landmarks_and_is_the_default(self) -> None:
        selection = select_content(page("a"))
        texts = [b.text for b in selection.blocks]
        assert sum(1 for t in texts if t.startswith(PROSE)) == 5
        assert not any(t.startswith("Share Tweet Email") for t in texts)
        assert selection.main_content_removed > 0
        assert selection.methods == ("landmarks", "main-content")

    def test_the_model_runs_after_landmarks_when_asked_for(self) -> None:
        selection = select_content(page("a"), model=SHIPPED_MODEL)
        texts = [b.text for b in selection.blocks]
        assert sum(1 for t in texts if t.startswith(PROSE)) == 5
        assert not any(t.startswith("Share Tweet Email") for t in texts)
        assert selection.block_model_removed > 0
        assert selection.main_content_removed == 0
        assert selection.methods == ("landmarks", "block-model")

    def test_site_chrome_is_applied_when_supplied(self) -> None:
        pages = [page(str(i)) for i in range(MIN_PAGES)]
        chrome = detect_site_chrome(pages)
        assert chrome.active
        selection = select_content(pages[0], chrome=chrome, main_content=False)
        texts = [b.text for b in selection.blocks]
        assert "Copyright Example Corp. All rights reserved." not in texts
        assert selection.chrome_removed >= 1
        assert "site-chrome" in selection.methods

    def test_method_order_is_the_run_order(self) -> None:
        pages = [page(str(i)) for i in range(MIN_PAGES)]
        chrome = detect_site_chrome(pages)
        assert select_content(pages[0], chrome=chrome).methods == (
            "landmarks", "site-chrome", "main-content",
        )
        assert select_content(pages[0], chrome=chrome, model=SHIPPED_MODEL).methods == (
            "landmarks", "site-chrome", "block-model",
        )

    def test_a_config_selects_the_boundary_step_it_configures(self) -> None:
        """`config` is `select_main_content`'s. Defaulting to the model while accepting one
        would make the argument a silent no-op -- a caller's tuning quietly discarded."""
        selection = select_content(page("a"), config=MainContentConfig(group_repeats="all"))
        assert selection.methods == ("landmarks", "main-content")
        assert selection.block_model_removed == 0

    def test_asking_for_both_is_a_contradiction(self) -> None:
        with pytest.raises(ValueError, match="one or the other"):
            select_content(page("a"), model=SHIPPED_MODEL, config=MainContentConfig())

    def test_the_two_last_steps_are_mutually_exclusive(self) -> None:
        """Whichever draws the line, exactly one of them does, and the other reports zero."""
        for kw in ({}, {"model": SHIPPED_MODEL}):
            selection = select_content(page("a"), **kw)  # type: ignore[arg-type]
            assert bool(selection.block_model_removed) != bool(selection.main_content_removed)

    def test_kept_and_total_account_for_every_block(self) -> None:
        blocks = page("a")
        for kw in ({}, {"model": SHIPPED_MODEL}):
            selection = select_content(blocks, **kw)  # type: ignore[arg-type]
            assert selection.total == len(blocks)
            removed = (
                selection.landmarks_removed
                + selection.chrome_removed
                + selection.main_content_removed
                + selection.block_model_removed
            )
            assert selection.kept + removed == selection.total
            assert selection.changed


class TestFailsOpen:
    """Every step returns what it was given when it would return nothing useful."""

    @staticmethod
    def _all_navigation() -> list[Block]:
        return [
            block(f"Section {i}", xpath=f"/html/body/div/a[{i}]", index=i,
                  rich=f"[Section {i}](/s{i})")
            for i in range(20)
        ]

    def test_the_boundary_step_returns_an_all_navigation_page_whole(self) -> None:
        """Nothing on the page is prose, so there is no run to draw a boundary around."""
        selection = select_content(self._all_navigation())
        assert selection.kept == 20
        assert not selection.changed
        assert selection.methods == ()

    def test_the_model_keeps_most_of_an_all_navigation_page(self) -> None:
        """The model scores each link on its own and is less sure than the boundary step is.

        Worth stating rather than hiding: on a page with no content at all the two disagree.
        The guarantee both keep is the one that matters -- a non-empty input never comes back
        empty or as a sliver, and no block is invented or reordered.
        """
        blocks = self._all_navigation()
        selection = select_content(blocks, model=SHIPPED_MODEL)
        assert selection.kept >= 15
        assert all(b in blocks for b in selection.blocks)

    def test_empty_input(self) -> None:
        selection = select_content([])
        assert selection.blocks == []
        assert selection.total == 0
        assert not selection.changed

    def test_nothing_is_invented(self) -> None:
        blocks = page("a")
        for kw in ({}, {"model": SHIPPED_MODEL}):
            selection = select_content(blocks, **kw)  # type: ignore[arg-type]
            assert all(b in blocks for b in selection.blocks)

    def test_order_is_preserved(self) -> None:
        for kw in ({}, {"model": SHIPPED_MODEL}):
            selection = select_content(page("a"), **kw)  # type: ignore[arg-type]
            indices = [b.dom_index for b in selection.blocks]
            assert indices == sorted(indices)

    def test_a_non_empty_page_never_comes_back_empty(self) -> None:
        for blocks in (page("a"), self._all_navigation(), [block("Hi", xpath="/p", index=0)]):
            assert select_content(blocks).blocks
            assert select_content(blocks, model=SHIPPED_MODEL).blocks


class TestTitleProtection:
    """The boundary step must never cut the block that is the page's title.

    On a Hacker News thread the title line is a link followed by "143 points by ...", the
    least prose-like thing on the page, and the boundary started at the first comment.
    """

    @staticmethod
    def thread() -> list[Block]:
        from webgraph.pipeline import build_document

        comments = "".join(
            f'<div class="comment"><p>{"A considered reply about monetary policy and GPUs. " * 6}</p></div>'
            for _ in range(12)
        )
        html = (
            "<html><head><title>Nvidia is the central bank of AI | Hacker News</title></head><body>"
            '<table><tr><td><a href="/">Hacker News</a> new | past | comments</td></tr>'
            '<tr><td><a href="https://e.com/x">Nvidia is the central bank of AI</a> (e.com)</td></tr>'
            "<tr><td>143 points by someone 2 hours ago | hide | 135 comments</td></tr></table>"
            f"{comments}</body></html>"
        )
        return list(build_document(html, "https://news.ycombinator.com/item?id=1").blocks)

    def test_the_title_survives_the_boundary(self) -> None:
        blocks = self.thread()
        without = select_content(blocks)
        with_title = select_content(blocks, title="Nvidia is the central bank of AI | Hacker News")
        texts = [b.text for b in with_title.blocks]
        assert any("Nvidia is the central bank of AI" in t for t in texts)
        # The protection only does something when the boundary actually cut the title.
        if not any("Nvidia is the central bank" in b.text for b in without.blocks):
            assert with_title.title_restored

    def test_it_lands_in_place_not_at_the_end(self) -> None:
        blocks = self.thread()
        result = select_content(blocks, title="Nvidia is the central bank of AI | Hacker News")
        texts = [b.text for b in result.blocks]
        title_at = next(i for i, t in enumerate(texts) if "central bank" in t)
        assert title_at == 0

    def test_nothing_is_restored_when_the_title_is_already_kept(self) -> None:
        from webgraph.pipeline import build_document

        html = (
            "<html><head><title>On Effects | Blog</title></head><body>"
            f"<article><h1>On Effects</h1><p>{'Prose about effects. ' * 80}</p></article>"
            "</body></html>"
        )
        blocks = list(build_document(html, "https://x.test/p").blocks)
        result = select_content(blocks, title="On Effects | Blog")
        # Whether the boundary kept the heading or cut it and it was put back, there is
        # exactly one of it -- never a second copy.
        assert sum(1 for b in result.blocks if b.text == "On Effects") == 1
        # And once it is in, asking again restores nothing.
        again = select_content(result.blocks, main_content=False, title="On Effects | Blog")
        assert again.title_restored is False

    def test_a_short_or_absent_title_does_nothing(self) -> None:
        blocks = self.thread()
        assert select_content(blocks, title="").title_restored is False
        assert select_content(blocks, title="Home").title_restored is False


class TestTitleBlockChoice:
    """jpost.com: <title> "Son of former German president stabbed ... - Breaking News - The
    Jerusalem Post". The first block containing a piece of it was the "BREAKING NEWS" kicker
    above the headline; the headline itself came second."""

    def test_heading_beats_a_kicker_that_matches_the_site_suffix(self) -> None:
        from webgraph.content import _title_block

        blocks = [
            Block(text="BREAKING NEWS", tag="p", xpath="/html/body/p[1]", dom_index=0),
            Block(
                text="Son of former German president stabbed to death in Berlin", tag="h1",
                xpath="/html/body/h1[1]", dom_index=1, kind=BlockKind.HEADING, level=1,
            ),
        ]
        chosen = _title_block(blocks, "Son of former German president stabbed to death in Berlin - Breaking News - The Jerusalem Post")
        assert chosen is not None and chosen.kind is BlockKind.HEADING
