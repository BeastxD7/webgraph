"""Main-content selection: the one module that throws content away on purpose.

Everything else in this engine is built to lose nothing, and measurably succeeds -- recall
0.953 on WCXB where the leading system manages 0.890. The cost is precision, and this module
is the deliberate exception. Because it deletes, its guards matter more than its accuracy:
a selector that silently returns a fragment is worse than one that returns everything.

The design follows a measurement rather than an intuition. On Zyte's 181 pages an oracle
picking the best **contiguous run** of the engine's own blocks scores F1 0.945, against 0.702
for keeping everything -- so the article body is already contiguous and correctly ordered,
and the task is a maximum-subarray problem, not a search.
"""

from __future__ import annotations

from webgraph.main_content import (
    MainContentConfig,
    content_value,
    link_density,
    select_main_content,
    word_count,
)
from webgraph.types import Block, BlockKind


def block(
    text: str,
    *,
    kind: BlockKind = BlockKind.PARAGRAPH,
    rich: str | None = None,
    index: int = 0,
) -> Block:
    return Block(
        text=text,
        tag="p",
        xpath=f"/html/body/p[{index + 1}]",
        dom_index=index,
        kind=kind,
        rich_text=rich,
    )


PROSE = (
    "The quick brown fox jumped over the lazy dog and continued running through the "
    "field until it reached the far treeline where it finally stopped to rest a while."
)


class TestLinkDensity:
    def test_plain_prose_has_none(self) -> None:
        assert link_density(block(PROSE)) == 0.0

    def test_a_navigation_strip_is_entirely_linked(self) -> None:
        nav = block(
            "Home About Pricing Contact",
            rich="[Home](/) [About](/a) [Pricing](/p) [Contact](/c)",
        )
        assert link_density(nav) == 1.0

    def test_a_paragraph_with_one_link_is_mostly_free(self) -> None:
        text = "This sentence mentions a source and then continues for a while afterwards."
        rich = "This sentence mentions [a source](/s) and then continues for a while afterwards."
        assert 0.0 < link_density(block(text, rich=rich)) < 0.3

    def test_absent_rich_text_means_no_links(self) -> None:
        """`text` has already flattened `[label](url)` to `label`, so it cannot answer this.
        A block with no `rich_text` had no inline markup worth recording."""
        assert link_density(block(PROSE, rich=None)) == 0.0

    def test_empty_text_does_not_divide_by_zero(self) -> None:
        assert link_density(block("")) == 0.0


class TestContentValue:
    def test_prose_is_worth_more_than_it_costs(self) -> None:
        assert content_value(block(PROSE), MainContentConfig()) > 0

    def test_a_navigation_strip_costs(self) -> None:
        words = ["Home", "About", "Pricing", "Contact", "Blog", "Careers", "Support", "Legal"]
        nav = block(
            " ".join(words),
            rich=" ".join(f"[{w}](/{w})" for w in words),
        )
        assert content_value(nav, MainContentConfig()) < 0

    def test_an_image_never_anchors_a_run(self) -> None:
        """Alt text on a product grid is a list of filenames."""
        image = block("staple-tee-charcoal-back", kind=BlockKind.IMAGE)
        assert content_value(image, MainContentConfig()) < 0

    def test_a_short_heading_survives_the_block_cost(self) -> None:
        """Headings are short and are content, which a raw word count gets backwards."""
        heading = block("Results", kind=BlockKind.HEADING)
        plain = block("Results")
        assert content_value(heading, MainContentConfig()) > content_value(
            plain, MainContentConfig()
        )


class TestSelection:
    def test_the_article_is_kept_and_the_chrome_is_not(self) -> None:
        nav = block(
            "Home About Pricing Contact",
            rich="[Home](/) [About](/a) [Pricing](/p) [Contact](/c)",
            index=0,
        )
        body = [block(PROSE, index=i) for i in range(1, 5)]
        footer = block(
            "Terms Privacy Cookies Careers",
            rich="[Terms](/t) [Privacy](/p) [Cookies](/c) [Careers](/j)",
            index=5,
        )
        selected = select_main_content([nav, *body, footer])
        texts = [b.text for b in selected]
        assert texts.count(PROSE) == 4
        assert "Home About Pricing Contact" not in texts
        assert "Terms Privacy Cookies Careers" not in texts

    def test_the_result_is_contiguous(self) -> None:
        """The contiguity constraint is doing real work -- it is what stops the scoring
        function cherry-picking a paragraph out of the footer."""
        blocks = [
            block("Home About", rich="[Home](/) [About](/a)", index=0),
            block(PROSE, index=1),
            block(PROSE + " Second.", index=2),
            block("Terms Privacy", rich="[Terms](/t) [Privacy](/p)", index=3),
            block(PROSE + " Stray in the footer.", index=4),
        ]
        selected = select_main_content(blocks)
        positions = [blocks.index(b) for b in selected]
        assert positions == list(range(positions[0], positions[-1] + 1))

    def test_order_is_preserved(self) -> None:
        blocks = [block(f"{PROSE} Paragraph {i}.", index=i) for i in range(5)]
        selected = select_main_content(blocks)
        assert [b.dom_index for b in selected] == sorted(b.dom_index for b in selected)


class TestGuards:
    """A selector that returns a fragment is worse than one that returns everything."""

    def test_an_all_navigation_page_is_returned_whole(self) -> None:
        """A sitemap or index page is legitimately almost all navigation. It has no main
        content to find, and saying so by returning everything beats inventing an answer."""
        blocks = [
            block(f"Section {i}", rich=f"[Section {i}](/s{i})", index=i) for i in range(20)
        ]
        assert len(select_main_content(blocks)) == len(blocks)

    def test_a_single_block_is_returned_unchanged(self) -> None:
        one = [block(PROSE)]
        assert select_main_content(one) == one

    def test_an_empty_list_is_returned_unchanged(self) -> None:
        assert select_main_content([]) == []

    def test_nothing_is_invented(self) -> None:
        """Every returned block must be one that was passed in."""
        blocks = [block(f"{PROSE} {i}.", index=i) for i in range(6)]
        selected = select_main_content(blocks)
        assert all(b in blocks for b in selected)


class TestConfigurability:
    def test_a_higher_cost_keeps_less(self) -> None:
        blocks = [
            block("Short one here.", index=0),
            *[block(PROSE, index=i) for i in range(1, 4)],
            block("Short two here.", index=4),
        ]
        loose = select_main_content(blocks, config=MainContentConfig(block_cost=1.0))
        tight = select_main_content(blocks, config=MainContentConfig(block_cost=25.0))
        assert len(loose) >= len(tight)

    def test_zero_cost_keeps_everything(self) -> None:
        """With no per-block cost every value is non-negative, the maximum subarray is the
        whole document, and the selector correctly does nothing."""
        blocks = [block(f"{PROSE} {i}.", index=i) for i in range(6)]
        selected = select_main_content(blocks, config=MainContentConfig(block_cost=0.0))
        assert len(selected) == len(blocks)


class TestSpacelessScripts:
    """Chinese, Japanese, Korean and Thai, which have no spaces between words.

    Every threshold in the selector is denominated in words, and splitting on whitespace
    counts an entire Chinese paragraph as **one**. Measured on WebMainBench, 8.1% of pages
    collapsed to a single block under the selector and **70% of those were CJK**: a 48
    character Chinese paragraph scored -12.0, the same as a nav link, so Kadane rejected the
    whole page. `min_run_share` could not catch it either, being measured in the same broken
    unit.

    Same class of failure as reading direction defaulting to left-to-right -- an assumption
    about English that is silently catastrophic elsewhere, and invisible to an English corpus.
    """

    # The fullwidth punctuation is deliberate. Real CJK prose uses it, and a fixture that
    # swapped it for ASCII would not be the text that broke the selector.
    CHINESE = (
        "网页内容提取引擎需要正确处理中文文本。中文没有空格分隔单词，"  # noqa: RUF001
        "因此按空白切分会把整段话算作一个词。这会导致整页内容被丢弃。"
    )
    JAPANESE = "ウェブコンテンツ抽出エンジンは日本語のテキストを正しく処理する必要があります。"

    def test_a_chinese_paragraph_counts_its_characters(self) -> None:
        assert word_count(self.CHINESE) > 40

    def test_a_chinese_paragraph_is_worth_keeping(self) -> None:
        para = block(self.CHINESE)
        assert content_value(para, MainContentConfig(adaptive_cost=False)) > 0

    def test_mixed_text_counts_both_halves(self) -> None:
        """A Japanese sentence quoting an English product name must count both."""
        assert word_count("Use 網頁 extraction 引擎 today") == 7

    def test_a_chinese_page_is_not_collapsed(self) -> None:
        blocks = [
            block("网站导航", rich="[首页](/) [关于](/a)", index=0),
            *[block(self.CHINESE, index=i) for i in range(1, 5)],
            block("版权所有", rich="[条款](/t) [隐私](/p)", index=5),
        ]
        selected = select_main_content(blocks)
        assert len(selected) >= 4
        assert sum(1 for b in selected if b.text == self.CHINESE) == 4

    def test_japanese_is_handled_too(self) -> None:
        blocks = [block(self.JAPANESE, index=i) for i in range(4)]
        assert len(select_main_content(blocks)) == 4


class TestRepeatedGroups:
    """Cards in a grid are one thing the author laid out, not forty separate blocks.

    Measured on WCXB dev: 66 of 117 collection pages and 39 of 99 listing pages were
    over-cut -- the grid was in the block list (recall 0.90) and the selector dropped it
    (0.56), because every short card paid a full block cost. Grouped by their repeated
    container, the cards pay once.
    """

    def _grid(self, n: int = 24) -> list[Block]:
        from webgraph.boilerplate import strip_landmarks
        from webgraph.pipeline import build_document

        cards = "".join(
            f"<li><a href='/p{i}'><h3>Vent Light Model {i}</h3></a><span>$ {20 + i}.00</span></li>"
            for i in range(n)
        )
        side = "".join(f"<li><a href='/r{i}'>Recent post {i}</a></li>" for i in range(5))
        html = (
            "<html><body><nav><a href='/'>Home</a></nav><main><h1>Lights</h1>"
            "<p>Shop our full range of cycling lights for every ride and every rider.</p>"
            f"<ul>{cards}</ul></main><aside><ul>{side}</ul></aside></body></html>"
        )
        return strip_landmarks(build_document(html, "https://x.test/").blocks)

    def test_off_drops_the_grid(self) -> None:
        kept = select_main_content(self._grid(), config=MainContentConfig(group_repeats="off"))
        assert sum(1 for b in kept if "Vent Light" in b.text) == 0

    def test_main_keeps_the_grid_and_not_the_sidebar(self) -> None:
        kept = select_main_content(self._grid(), config=MainContentConfig(group_repeats="main"))
        assert sum(1 for b in kept if "Vent Light" in b.text) == 24
        assert not any("Recent post" in b.text for b in kept)

    def test_all_keeps_the_grid_but_a_small_group_is_not_a_grid(self) -> None:
        """The sidebar is a repeated group too, but five three-word items are not 30% of
        the page, so the share guard leaves them individually scored -- and dropped."""
        kept = select_main_content(self._grid(), config=MainContentConfig(group_repeats="all"))
        assert sum(1 for b in kept if "Vent Light" in b.text) == 24
        assert not any("Recent post" in b.text for b in kept)

    def test_a_grouped_link_rail_still_scores_as_links(self) -> None:
        """Grouping removes the per-card cost, not the link-density signal. A rail of five
        all-link items outside `main` groups (share guard off) and is still negative: five
        blocks worth -cost each, paying one cost, is -cost. The first form of grouping
        counted every word regardless and leaked such rails -- articles -0.015, products
        -0.063 on WCXB dev."""
        kept = select_main_content(
            self._grid(), config=MainContentConfig(group_repeats="all", group_min_share=0.0)
        )
        assert sum(1 for b in kept if "Vent Light" in b.text) == 24
        assert not any("Recent post" in b.text for b in kept)

    def test_a_card_is_one_group_whatever_its_tags(self) -> None:
        from webgraph.main_content import _repeat_groups

        blocks = self._grid(3)
        groups = _repeat_groups(blocks, MainContentConfig(group_repeats="all"))
        card_groups = {g for b, g in zip(blocks, groups, strict=True) if "Vent Light" in b.text or "$" in b.text}
        assert len(card_groups) == 1

    def test_fewer_than_three_is_not_a_grid(self) -> None:
        from webgraph.main_content import _repeat_groups

        blocks = self._grid(2)
        groups = _repeat_groups(blocks, MainContentConfig(group_repeats="all"))
        assert all(g == -1 for b, g in zip(blocks, groups, strict=True) if "Vent Light" in b.text)


class TestProductSheet:
    """WCXB product ground truth is the sheet -- title, description, features, specs -- and
    the boundary step was keeping the reviews instead. Dev F1 0.586 -> 0.601 (D103)."""

    @staticmethod
    def page() -> list[Block]:
        def b(text: str, i: int, *, kind: BlockKind = BlockKind.PARAGRAPH, level: int = 0, xpath: str | None = None) -> Block:
            return Block(
                text=text, tag="p", xpath=xpath or f"/html/body/main/div/p[{i + 1}]", dom_index=i,
                kind=kind, level=level, in_main=True, region="main",
            )

        blocks = [
            b("Fender Player II Strat RW BCG", 0, kind=BlockKind.HEADING, level=1),
            b("Electric Guitar", 1, kind=BlockKind.HEADING, level=2),
            b("Body: Alder", 2, kind=BlockKind.LIST_ITEM),
            b("Bolt-on neck: Maple", 3, kind=BlockKind.LIST_ITEM),
            b("Fingerboard: Rosewood", 4, kind=BlockKind.LIST_ITEM),
            b("Scale: 648 mm (25.5 inch)", 5, kind=BlockKind.LIST_ITEM),
            b("Nut width: 42 mm", 6, kind=BlockKind.LIST_ITEM),
            b("Pickups: 3 Player Series Alnico 5 Strat single coils", 7, kind=BlockKind.LIST_ITEM),
            b("Customer Reviews", 8, kind=BlockKind.HEADING, level=2),
        ]
        for i in range(3):
            blocks.append(b(f"{PROSE} Review number {i}. 5 out of 5 stars, verified buyer.", 9 + i,
                            xpath=f"/html/body/main/div/section/div[{i + 1}]/p"))
        blocks.append(b("You may also like", 12, kind=BlockKind.HEADING, level=2))
        for i in range(4):
            blocks.append(Block(
                text="Fender Player II Strat HSS $899.00", tag="p",
                xpath=f"/html/body/main/div/ul/li[{i + 1}]/p", dom_index=13 + i,
                href="https://shop.test/p", in_main=True, region="main",
            ))
        return blocks

    def test_specs_kept_reviews_and_related_dropped(self) -> None:
        kept = select_main_content(self.page(), config=MainContentConfig(product_sheet=True))
        texts = [b.text for b in kept]
        assert "Body: Alder" in texts and "Pickups: 3 Player Series Alnico 5 Strat single coils" in texts
        assert not any("Review number" in t for t in texts)
        assert not any("$899.00" in t for t in texts)
        assert "Customer Reviews" not in texts and "You may also like" not in texts

    def test_default_policy_is_unchanged(self) -> None:
        kept = select_main_content(self.page(), config=MainContentConfig())
        assert any("Review number" in b.text for b in kept), "without the policy, prose wins"

    def test_write_a_review_is_not_a_section(self) -> None:
        from webgraph.main_content import _prune_other_sections

        blocks = [
            Block(text="Write a Review", tag="h3", xpath="/html/body/h3[1]", dom_index=0, kind=BlockKind.HEADING, level=3),
            Block(text=PROSE, tag="p", xpath="/html/body/p[1]", dom_index=1),
        ]
        assert [b.text for b in _prune_other_sections(blocks)] == ["Write a Review", PROSE]

    def test_an_unbounded_tail_is_not_dropped(self) -> None:
        from webgraph.main_content import _prune_other_sections

        blocks = [Block(text="Reviews", tag="h2", xpath="/html/body/h2[1]", dom_index=0, kind=BlockKind.HEADING, level=2)]
        blocks += [Block(text=f"{PROSE} {i}", tag="p", xpath=f"/html/body/p[{i + 1}]", dom_index=i + 1) for i in range(80)]
        assert len(_prune_other_sections(blocks)) == 81
