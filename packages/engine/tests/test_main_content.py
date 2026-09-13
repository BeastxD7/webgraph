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
        from webgraph.main_content import _OTHER_SECTION, _prune_other_sections

        blocks = [
            Block(text="Write a Review", tag="h3", xpath="/html/body/h3[1]", dom_index=0, kind=BlockKind.HEADING, level=3),
            Block(text=PROSE, tag="p", xpath="/html/body/p[1]", dom_index=1),
        ]
        assert [b.text for b in _prune_other_sections(blocks, _OTHER_SECTION)] == ["Write a Review", PROSE]

    def test_a_long_review_section_is_dropped_whole(self) -> None:
        """rei.com: ninety blocks of reviews under one "Customer Reviews" heading. The old
        60-block bound left them all in place."""
        from webgraph.main_content import _OTHER_SECTION, _prune_other_sections

        blocks = [Block(text="Customer Reviews", tag="h2", xpath="/html/body/h2[1]", dom_index=0, kind=BlockKind.HEADING, level=2)]
        blocks += [Block(text=f"{PROSE} Review {i}", tag="p", xpath=f"/html/body/p[{i + 1}]", dom_index=i + 1) for i in range(90)]
        blocks.append(Block(text="Specifications", tag="h2", xpath="/html/body/h2[2]", dom_index=100, kind=BlockKind.HEADING, level=2))
        blocks.append(Block(text="Weight: 1 lb. 13 oz.", tag="p", xpath="/html/body/p[200]", dom_index=101))
        pruned = _prune_other_sections(blocks, _OTHER_SECTION)
        assert [b.text for b in pruned] == ["Specifications", "Weight: 1 lb. 13 oz."]

    def test_an_unbounded_tail_is_not_dropped(self) -> None:
        from webgraph.main_content import _OTHER_SECTION, _prune_other_sections

        blocks = [Block(text="Reviews", tag="h2", xpath="/html/body/h2[1]", dom_index=0, kind=BlockKind.HEADING, level=2)]
        blocks += [Block(text=f"{PROSE} {i}", tag="p", xpath=f"/html/body/p[{i + 1}]", dom_index=i + 1) for i in range(300)]
        assert len(_prune_other_sections(blocks, _OTHER_SECTION)) == 301


class TestRivers:
    """cbsnews.com: a "Trending News" box dropped between the third and fourth paragraphs,
    and a "More World" river of teasers under the article. The box is teasers until the
    prose resumes; the river runs to the next heading."""

    @staticmethod
    def article() -> list[Block]:
        def b(text: str, i: int, *, kind: BlockKind = BlockKind.PARAGRAPH, level: int = 0) -> Block:
            return Block(text=text, tag="p", xpath=f"/html/body/p[{i + 1}]", dom_index=i, kind=kind, level=level)

        blocks = [b("Video shows dramatic rescue", 0, kind=BlockKind.HEADING, level=1)]
        blocks += [b(f"{PROSE} Paragraph {i}.", 1 + i) for i in range(3)]
        blocks.append(b("Trending News", 4, kind=BlockKind.HEADING, level=2))
        blocks.append(b("White teen accused of plotting deadly attack", 5, kind=BlockKind.LIST_ITEM))
        blocks.append(b("Woman risks her life to save a koala", 6, kind=BlockKind.LIST_ITEM))
        blocks += [b(f"{PROSE} Paragraph {i}.", 7 + i) for i in range(3, 6)]
        blocks.append(b("Most Read", 10, kind=BlockKind.HEADING, level=2))
        for i in range(4):
            blocks.append(b(f"Teaser headline {i}", 11 + 2 * i, kind=BlockKind.HEADING, level=3))
            blocks.append(b(f"A one-sentence blurb about teaser {i} that reads like news.", 12 + 2 * i))
        return blocks

    def test_inline_box_ends_where_the_prose_resumes(self) -> None:
        kept = select_main_content(self.article(), config=MainContentConfig(prune_rivers=True))
        texts = [b.text for b in kept]
        assert sum(1 for t in texts if t.startswith(PROSE)) == 6, "all six paragraphs survive"
        assert "Trending News" not in texts and not any("koala" in t for t in texts)
        assert not any("Teaser headline" in t for t in texts)

    def test_the_pruner_alone_keeps_every_paragraph(self) -> None:
        from webgraph.main_content import _RIVER_SECTION, _prune_other_sections

        pruned = _prune_other_sections(self.article(), _RIVER_SECTION)
        texts = [b.text for b in pruned]
        assert sum(1 for t in texts if t.startswith(PROSE)) == 6
        assert "Most Read" not in texts and "Trending News" not in texts
        assert texts[0] == "Video shows dramatic rescue"


class TestSpecSheetFallback:
    """lttlabs.com: a review that is a spec sheet -- forty two-word lines and no prose -- never
    forms a run the boundary step can believe in, and it kept three blocks of it. Product and
    collection pages refuse a run under a quarter of the page and return everything that
    survived the structural steps."""

    @staticmethod
    def sheet() -> list[Block]:
        rows = [
            ("Height", "3.2 cm"), ("Width Max", "31.0 cm"), ("Depth", "12.0 cm"), ("Weight", "653 g"),
            ("Switches", "Gateron G Pro Brown"), ("Keycaps", "ABS double-shot"), ("Connection", "USB Type-C, Bluetooth 5.1"),
            ("Battery", "4000 mAh"), ("Backlight", "White LED"), ("Layout", "75% ANSI"), ("Hot-swap", "Yes"), ("Case", "Aluminium frame"),
        ]
        blocks = [Block(text="Keychron K2 Wireless Mechanical Keyboard (Version 2)", tag="h1", xpath="/html/body/main/h1", dom_index=0, kind=BlockKind.HEADING, level=1, in_main=True)]
        for i, (k, v) in enumerate(rows, 1):
            blocks.append(Block(text=k, tag="p", xpath=f"/html/body/main/div[{i}]/p[1]", dom_index=2 * i - 1, in_main=True))
            blocks.append(Block(text=v, tag="p", xpath=f"/html/body/main/div[{i}]/p[2]", dom_index=2 * i, in_main=True))
        blocks.append(Block(text="Purchases made through these links may provide compensation to the site that runs this review.", tag="p", xpath="/html/body/main/p[99]", dom_index=99, in_main=True))
        return blocks

    def test_product_policy_returns_the_whole_sheet(self) -> None:
        from webgraph.pagetype import policy_for

        kept = select_main_content(self.sheet(), config=policy_for("product"))
        assert len(kept) == len(self.sheet())

    def test_default_policy_keeps_a_sliver(self) -> None:
        kept = select_main_content(self.sheet(), config=MainContentConfig())
        assert len(kept) < len(self.sheet()) // 2


class TestRepeatedQuotes:
    """forum.nationstates.net: every reply quotes the post it answers. The quote says nothing
    the thread has not said, and the annotators leave it out."""

    @staticmethod
    def thread() -> list[Block]:
        post = f"{PROSE} The season is one of the wildest in football history, with minnows everywhere."
        return [
            Block(text=post, tag="p", xpath="/html/body/div[1]/p", dom_index=0),
            Block(text=f"{PROSE} A second post that is its own words entirely, about fixtures.", tag="p", xpath="/html/body/div[2]/p", dom_index=1),
            Block(text=f"Outer Armatonisdaristan wrote: {post}", tag="blockquote", xpath="/html/body/div[3]/blockquote", dom_index=2, kind=BlockKind.QUOTE),
            Block(text="Dutch eredivisie fixtures are out, and the schedule is brutal for the small clubs this year.", tag="blockquote", xpath="/html/body/div[3]/blockquote[2]", dom_index=3, kind=BlockKind.QUOTE),
            Block(text=f"{PROSE} A reply that answers the quoted post with new words of its own.", tag="p", xpath="/html/body/div[3]/p", dom_index=4),
        ]

    def test_a_quote_of_an_earlier_post_is_dropped_and_an_original_one_kept(self) -> None:
        from webgraph.main_content import _drop_quoted_repeats

        kept = _drop_quoted_repeats(self.thread())
        texts = [b.text for b in kept]
        assert not any(t.startswith("Outer Armatonisdaristan wrote") for t in texts)
        assert any(t.startswith("Dutch eredivisie") for t in texts)
        assert len(kept) == 4

    def test_off_by_config(self) -> None:
        kept = select_main_content(self.thread(), config=MainContentConfig(drop_repeated_quotes=False))
        assert any(b.text.startswith("Outer Armatonisdaristan wrote") for b in kept)


class TestGridInstances:
    """eBay's similar-items carousel: each card is one `li[n]`, and inside it the picture,
    the title and the price sit at different depths with their own indices. Keyed on each
    block's innermost index, every block was its own instance and no instance was ever
    priced *and* pictured; keyed on the group's `li[*]` template, the cards are cards."""

    @staticmethod
    def page() -> list[Block]:
        def b(text: str, xpath: str, i: int, **kw: object) -> Block:
            return Block(text=text, tag="p", xpath=xpath, dom_index=i, in_main=True, **kw)  # type: ignore[arg-type]

        blocks = [
            b("Next 3 pack ladies top black, white & green size 6", "/html/body/main/h1", 0, kind=BlockKind.HEADING, level=1),
            b("Condition: not specified", "/html/body/main/div[1]/p[1]", 1),
            b("Delivery: Varies", "/html/body/main/div[1]/p[2]", 2),
            b("Seller assumes all responsibility for this listing. The item ships from the UK within three working days.", "/html/body/main/div[1]/p[3]", 3),
        ]
        i = 10
        for n in range(1, 7):
            base = f"/html/body/main/ul/li[{n}]/div/section/div[1]"
            card = [
                b("", f"{base}/div/div[1]/div/img", i, kind=BlockKind.IMAGE),
                b(f"Next Blouse Top Size {n} Womens Green Black White Casual", f"{base}/div/div[2]/div/h3", i + 1, kind=BlockKind.HEADING, level=3),
                b(f"${10 + n}.40", f"{base}/div/div[2]/div/div[1]/div[2]", i + 2),
                b(f"+ ${20 + n}.69 delivery", f"{base}/div/div[2]/div/div[2]", i + 3),
            ]
            blocks.extend(card)
            i += 4
        return blocks

    def test_cards_are_recognised_as_one_grid_and_pruned(self) -> None:
        from webgraph.main_content import _prune_product

        pruned = _prune_product(self.page(), MainContentConfig(product_sheet=True))
        texts = [b.text for b in pruned]
        assert not any("Next Blouse Top" in t for t in texts)
        assert "Condition: not specified" in texts and texts[0].startswith("Next 3 pack")
