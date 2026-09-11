"""`select_content`: the one decision about what a page's content is.

Before this module the crawl removed landmarks and site chrome, the single-page API removed
landmarks only, and the main-content selector -- the step with the largest measured gain --
was called by benchmarks and nothing else. The same page asked for alone and asked for as
part of its site came back different, and the finished precision work was not shipped.

These tests pin the composition: the order the steps run in, that each step is reported,
and that the whole thing fails open rather than returning a fragment.
"""

from __future__ import annotations

from webgraph.boilerplate import MIN_PAGES, detect_site_chrome
from webgraph.content import select_content
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

    def test_main_content_runs_after_landmarks(self) -> None:
        selection = select_content(page("a"))
        texts = [b.text for b in selection.blocks]
        assert sum(1 for t in texts if t.startswith(PROSE)) == 5
        assert not any(t.startswith("Share Tweet Email") for t in texts)
        assert selection.main_content_removed > 0
        assert selection.methods == ("landmarks", "main-content")

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
        selection = select_content(pages[0], chrome=chrome)
        assert selection.methods == ("landmarks", "site-chrome", "main-content")

    def test_kept_and_total_account_for_every_block(self) -> None:
        blocks = page("a")
        selection = select_content(blocks)
        assert selection.total == len(blocks)
        removed = (
            selection.landmarks_removed
            + selection.chrome_removed
            + selection.main_content_removed
        )
        assert selection.kept + removed == selection.total
        assert selection.changed


class TestFailsOpen:
    """Every step returns what it was given when it would return nothing useful."""

    def test_an_all_navigation_page_comes_back_whole(self) -> None:
        blocks = [
            block(f"Section {i}", xpath=f"/html/body/div/a[{i}]", index=i,
                  rich=f"[Section {i}](/s{i})")
            for i in range(20)
        ]
        selection = select_content(blocks)
        assert selection.kept == len(blocks)
        assert not selection.changed
        assert selection.methods == ()

    def test_empty_input(self) -> None:
        selection = select_content([])
        assert selection.blocks == []
        assert selection.total == 0
        assert not selection.changed

    def test_nothing_is_invented(self) -> None:
        blocks = page("a")
        selection = select_content(blocks)
        assert all(b in blocks for b in selection.blocks)

    def test_order_is_preserved(self) -> None:
        selection = select_content(page("a"))
        indices = [b.dom_index for b in selection.blocks]
        assert indices == sorted(indices)
