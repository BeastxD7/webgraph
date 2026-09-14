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
    """A page with a `<nav>`, a repeated footer line, a byline strip, and the body in a
    plain `<section>` -- not an `<article>`, so that `scope_to_article` stays out of these
    composition tests and each step's own work is visible in `methods`."""
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
            block(f"{PROSE} {unique} {i}.", xpath=f"/html/body/div/section/p[{i}]", index=2 + i)
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


class TestLeadRestoration:
    """docs.python.org/3/library/functools.html: the boundary began at the fourth paragraph,
    the title was put back alone, and the sentence that says what the page is about --
    between the title and the run -- stayed lost."""

    def test_the_prose_between_title_and_body_comes_back_with_the_title(self) -> None:
        title = "functools — Higher-order functions and operations on callable objects"
        blocks = [
            Block(text=title, tag="h1", xpath="/html/body/main/h1", dom_index=0, kind=BlockKind.HEADING, level=1, in_main=True, region="main"),
            Block(text="Source code: Lib/functools.py", tag="p", xpath="/html/body/main/p[1]", dom_index=1, in_main=True, region="main"),
            Block(text="The functools module is for higher-order functions: functions that act on or return other functions.", tag="p", xpath="/html/body/main/p[2]", dom_index=2, in_main=True, region="main"),
            Block(text="@functools.cache(user_function)", tag="p", xpath="/html/body/main/p[3]", dom_index=3, in_main=True, region="main"),
        ]
        for i in range(4, 12):
            blocks.append(Block(text=f"{PROSE} Paragraph {i}.", tag="p", xpath=f"/html/body/main/p[{i}]", dom_index=i, in_main=True, region="main"))
        result = select_content(blocks, title=f"{title} — Python 3.14 documentation")
        texts = [b.text for b in result.blocks]
        assert texts[0] == title
        assert "Source code: Lib/functools.py" in texts
        assert any(t.startswith("The functools module is for") for t in texts)

    def test_a_menu_under_the_title_is_not_a_lead(self) -> None:
        title = "Guide to shelving units"
        blocks = [Block(text=title, tag="h1", xpath="/html/body/h1", dom_index=0, kind=BlockKind.HEADING, level=1)]
        blocks += [Block(text=f"Menu item {i}", tag="li", xpath=f"/html/body/ul/li[{i}]", dom_index=i, kind=BlockKind.LIST_ITEM) for i in range(1, 9)]
        blocks += [Block(text=f"{PROSE} Paragraph {i}.", tag="p", xpath=f"/html/body/p[{i}]", dom_index=10 + i) for i in range(6)]
        result = select_content(blocks, title=title)
        texts = [b.text for b in result.blocks]
        assert texts[0] == title
        assert not any(t.startswith("Menu item") for t in texts)


class TestArticleScope:
    """cbsnews.com: the story is 493 words in one <article>; the "More World" river beneath
    it is twenty small <article> teasers. The dominant article is the content's extent."""

    @staticmethod
    def news() -> list[Block]:
        blocks = [Block(text="Share this Tweet Email", tag="p", xpath="/html/body/div/p[1]", dom_index=0)]
        for i in range(1, 9):
            blocks.append(Block(text=f"{PROSE} Story paragraph {i}.", tag="p", xpath=f"/html/body/div/article/p[{i}]", dom_index=i))
        for j in range(1, 7):
            blocks.append(Block(text=f"Teaser headline {j}", tag="h3", xpath=f"/html/body/div/section/article[{j}]/h3", dom_index=20 + 2 * j, kind=BlockKind.HEADING, level=3))
            blocks.append(Block(text=f"A one-sentence blurb about teaser {j} that reads exactly like news copy does.", tag="p", xpath=f"/html/body/div/section/article[{j}]/p", dom_index=21 + 2 * j))
        return blocks

    def test_dominant_article_scopes_the_page(self) -> None:
        from webgraph.boilerplate import scope_to_article

        scoped = scope_to_article(self.news())
        assert all(b.xpath.startswith("/html/body/div/article/") for b in scoped)
        assert len(scoped) == 8
        selection = select_content(self.news())
        assert "article-element" in selection.methods
        assert not any("Teaser" in b.text for b in selection.blocks)

    def test_a_thread_of_equal_posts_is_not_scoped(self) -> None:
        from webgraph.boilerplate import scope_to_article

        posts = [Block(text=f"{PROSE} Post {i}.", tag="p", xpath=f"/html/body/main/article[{i}]/p", dom_index=i) for i in range(1, 6)]
        assert scope_to_article(posts) == posts

    def test_forum_policy_leaves_it_off(self) -> None:
        from webgraph.pagetype import policy_for

        assert policy_for("forum").scope_article is False
        assert policy_for("article").scope_article is True


class TestArticleBodyScope:
    """thesun.co.uk, and most news CMSs: no <article> around the story, but a `div.article__content`
    (or `itemprop="articleBody"`, `entry-content`, `story-body`) holding it and nothing else;
    the "Most read" rail and the related-story cards sit beside it in the same column. The
    body element is the author's third statement, read after <main> and <article>."""

    @staticmethod
    def page(body_attr: str = 'class="article__content"') -> str:
        story = "".join(f"<p>{PROSE} Story paragraph {i}.</p>" for i in range(1, 9))
        cards = "".join(
            f"<div class='card'><h3>Teaser headline {j}</h3><p>A one-sentence blurb about teaser {j} that reads exactly like news copy does.</p></div>"
            for j in range(1, 7)
        )
        return (
            "<html><head><title>Hunter diagnosed with plague | The Sun</title></head><body><div class='col'>"
            "<h1>Hunter diagnosed with plague</h1><p class='byline'>By A Reporter, 20 Nov 2019</p>"
            f"<div {body_attr}>{story}</div><div class='more'>{cards}</div></div></body></html>"
        )

    def test_blocks_carry_the_body_they_sit_in(self) -> None:
        from webgraph.pipeline import build_document

        blocks = build_document(self.page(), "https://news.test/story").blocks
        bodies = {b.text[:6]: b.body_of for b in blocks}
        assert bodies["Hunter"] is None and bodies["By A R"] is None
        assert bodies[PROSE[:6]] == "/html/body/div/div[1]"
        assert bodies["Teaser"] is None

    def test_the_dominant_body_scopes_the_page_and_the_title_comes_back(self) -> None:
        from webgraph.pipeline import build_document

        document = build_document(self.page(), "https://news.test/story")
        selection = select_content(list(document.blocks), model=None, title=document.title or "")
        texts = [b.text for b in selection.blocks]
        assert "article-body" in selection.methods
        assert texts[0] == "Hunter diagnosed with plague"
        assert texts[1] == "By A Reporter, 20 Nov 2019"
        assert sum(1 for t in texts if "Story paragraph" in t) == 8
        assert not any("Teaser" in t for t in texts)

    def test_itemprop_article_body_is_a_body(self) -> None:
        from webgraph.pipeline import build_document

        blocks = build_document(self.page('itemprop="articleBody"'), "https://news.test/story").blocks
        assert all(b.body_of for b in blocks if "Story paragraph" in b.text)

    def test_two_bodies_of_equal_weight_do_not_scope(self) -> None:
        """A page of several `entry-content` posts (a blog index, a forum theme) is not scoped
        to one of them: the dominance test that guards <article> guards this too."""
        from webgraph.boilerplate import scope_to_article_body
        from webgraph.pipeline import build_document

        posts = "".join(
            "<div class='entry-content'>" + "".join(f"<p>{PROSE} Post {i} paragraph {k}.</p>" for k in range(3)) + "</div>"
            for i in range(4)
        )
        blocks = list(build_document(f"<html><body>{posts}</body></html>", "https://blog.test/").blocks)
        assert scope_to_article_body(blocks) == blocks
