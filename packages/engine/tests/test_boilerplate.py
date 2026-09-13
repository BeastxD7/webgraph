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


class TestLandmarks:
    """`<nav>` and `<footer>` are the page's own statement about what is navigation.

    Excluding them is structural rather than statistical, which is what makes it work on the
    first page of a crawl instead of the sixth. Measured over 13 pages against a majority
    vote of trafilatura, readability and jusText: F 0.740 -> 0.811 with recall unchanged at
    0.990. On MDN alone, precision 0.066 -> 0.584.
    """

    @staticmethod
    def blocks_of(html: str):
        from webgraph.pipeline import build_document

        return list(build_document(f"<html><body>{html}</body></html>", "https://e.com/").blocks)

    def test_navigation_is_dropped(self) -> None:
        from webgraph.boilerplate import strip_landmarks

        blocks = self.blocks_of(
            "<nav><a href='/a'>Alpha</a> <a href='/b'>Beta</a></nav>"
            "<main><p>" + "Real article content here. " * 12 + "</p></main>"
        )
        kept = strip_landmarks(blocks)
        assert all("Alpha" not in b.text for b in kept)
        assert any("Real article content" in b.text for b in kept)

    def test_footers_are_dropped(self) -> None:
        from webgraph.boilerplate import strip_landmarks

        blocks = self.blocks_of(
            "<main><p>" + "Body text of the page. " * 12 + "</p></main>"
            "<footer><p>Copyright 2026 Example Inc.</p></footer>"
        )
        assert all("Copyright" not in b.text for b in strip_landmarks(blocks))

    def test_a_page_with_no_landmarks_is_untouched(self) -> None:
        """danluu.com has no `<nav>`, and measured identically before and after."""
        from webgraph.boilerplate import strip_landmarks

        blocks = self.blocks_of("<p>" + "Just an essay, no chrome at all. " * 12 + "</p>")
        assert len(strip_landmarks(blocks)) == len(blocks)

    def test_an_all_navigation_page_is_not_gutted(self) -> None:
        """A sitemap or index page is legitimately almost all navigation, and returning
        nothing for it helps nobody."""
        from webgraph.boilerplate import strip_landmarks

        blocks = self.blocks_of(
            "<nav>" + "".join(f"<a href='/p{i}'>Page number {i}</a>" for i in range(40))
            + "</nav><p>x</p>"
        )
        assert len(strip_landmarks(blocks)) == len(blocks)

    def test_aside_and_header_are_kept(self) -> None:
        """Excluding them buys 0.4 points of F and costs 0.4 of recall -- the wrong trade for
        an engine whose job is not to lose content. Plenty of sites put real material in an
        `<aside>`."""
        from webgraph.boilerplate import strip_landmarks

        blocks = self.blocks_of(
            "<aside><p>" + "A sidebar note that is real content. " * 8 + "</p></aside>"
            "<main><p>" + "Main body. " * 12 + "</p></main>"
        )
        assert any("sidebar note" in b.text for b in strip_landmarks(blocks))


class TestFilterWidgets:
    """A faceted-search panel is navigation over the catalogue: inside `main`, link-dense
    like the grid beside it, named by its authors. newegg.com: 3,000 words of "ASUS" and
    "394 mm" around a 650-word grid."""

    def test_named_filter_panel_with_controls_is_stripped(self) -> None:
        from webgraph.pipeline import build_document

        facets = "".join(
            f'<li><label><input type="checkbox">Brand {i}</label> <span>({i * 7})</span></li>' for i in range(6)
        )
        cards = "".join(f"<li><a href='/p/{i}'>Graphics Card {i} 16GB GDDR6</a><span>$ {400 + i}.99</span></li>" for i in range(8))
        html = (
            "<html><body><main><h1>GPUs</h1>"
            f'<div class="product-filters"><h3>Brand</h3><ul>{facets}</ul></div>'
            f"<ul class='grid'>{cards}</ul></main></body></html>"
        )
        document = build_document(html, "https://shop.test/gpus")
        marked = [b for b in document.blocks if b.widget == "filter"]
        assert marked and all("Brand" in b.text or "(" in b.text for b in marked)
        from webgraph.boilerplate import strip_landmarks

        kept = strip_landmarks(list(document.blocks))
        assert not any(b.widget for b in kept)
        assert any("Graphics Card 3" in b.text for b in kept)

    def test_a_named_panel_without_controls_is_left_alone(self) -> None:
        from webgraph.pipeline import build_document

        html = (
            '<html><body><main><div class="facet-row filters"><h5>What should I look for?</h5>'
            "<p>Focus on ease of use, a good manual and a few built-in stitches.</p></div></main></body></html>"
        )
        document = build_document(html, "https://shop.test/faq")
        assert not any(b.widget for b in document.blocks)


class TestConsentDialogs:
    """OneTrust's preference centre is 2,000 words of "Strictly Necessary Cookies" in the
    DOM of 12% of WCXB dev, and it was chosen as the main content of a GameFAQs thread."""

    def test_vendor_consent_dialog_is_stripped(self) -> None:
        from webgraph.boilerplate import strip_landmarks
        from webgraph.pipeline import build_document

        html = (
            "<html><body><main><h1>Thread</h1><p>No YT stream link this time. The VOD goes up in an hour.</p>"
            + "".join(f"<p>Reply number {i}: I think the timing is unusual and it will kick ass, honestly.</p>" for i in range(8))
            + "</main>"
            '<div id="onetrust-consent-sdk"><div id="onetrust-pc-sdk"><h2>We Care About Your Privacy</h2>'
            "<p>We and our 644 partners store and access personal data, like browsing data or unique identifiers.</p>"
            "<h3>Strictly Necessary Cookies</h3><p>These cookies are necessary for the website to function.</p>"
            "</div></div></body></html>"
        )
        document = build_document(html, "https://forum.test/t/1")
        assert [b.widget for b in document.blocks if "partners" in b.text] == ["consent"]
        kept = strip_landmarks(list(document.blocks))
        assert all(b.widget is None for b in kept)
        assert any("VOD" in b.text for b in kept)

    def test_hand_rolled_cookie_banner_is_stripped_and_prose_is_not(self) -> None:
        from webgraph.pipeline import build_document

        html = (
            '<html><body><div class="cookie-banner"><p>This site uses cookies to improve your experience.</p></div>'
            '<article><p class="policy-text">Our cookie policy explains how we bake them.</p></article></body></html>'
        )
        document = build_document(html, "https://bakery.test/")
        widgets = {b.text[:9]: b.widget for b in document.blocks}
        assert widgets["This site"] == "consent"
        assert widgets["Our cooki"] is None


class TestAsideStripped:
    """mspoweruser.com: a "Deals" river of twenty teasers in an `<aside>` inside `<main>`,
    kept by the boundary step because a teaser blurb scores like a sentence. Measured on
    WCXB dev, stripping `aside` gains on six of seven page types."""

    def test_aside_inside_main_is_stripped(self) -> None:
        from webgraph.boilerplate import strip_landmarks
        from webgraph.pipeline import build_document

        body = "".join(f"<p>Paragraph {i} of the article, with enough words to count as prose here.</p>" for i in range(8))
        deals = "".join(f"<h3>Deal Alert {i}: gadget {i} discounted</h3><p>Amazon is offering gadget {i} at a discount today.</p>" for i in range(6))
        html = f"<html><body><main><article><h1>Title</h1>{body}</article><aside>{deals}</aside></main></body></html>"
        document = build_document(html, "https://news.test/story")
        kept = strip_landmarks(list(document.blocks))
        assert not any("Deal Alert" in b.text for b in kept)
        assert sum(1 for b in kept if b.text.startswith("Paragraph")) == 8


class TestComments:
    """Slashdot: a 412-word summary and 6,000 words of thread beneath it, annotated as an
    article whose content is the summary. Comments are stripped for every page type but
    forums (where they are the content) and products (where the product prune decides)."""

    @staticmethod
    def story() -> str:
        sentence = "long enough to read as prose on its own, with clauses that run on a little further than they need to"
        body = "".join(f"<p>Paragraph {i} of the story, {sentence}, {sentence}.</p>" for i in range(8))
        comments = "".join(
            f'<li class="comment"><p>Reply {i}: a paragraph of opinion long enough to read like the article itself.</p></li>'
            for i in range(6)
        )
        return f'<html><body><main><article><h1>Story</h1>{body}</article><section id="comments"><h2>Comments</h2><ol class="comment-list">{comments}</ol></section></main></body></html>'

    def test_comments_are_marked_and_stripped_for_articles(self) -> None:
        from webgraph.content import select_content
        from webgraph.pipeline import build_document

        document = build_document(self.story(), "https://news.test/story")
        assert sum(1 for b in document.blocks if b.widget == "comments") >= 6
        kept = select_content(list(document.blocks), model=None, title="Story").blocks
        assert not any("Reply" in b.text for b in kept)
        assert sum(1 for b in kept if b.text.startswith("Paragraph")) == 8

    def test_a_page_that_is_its_comments_keeps_them(self) -> None:
        """A Hacker News comment page: a login link, two comments, a footer. Without the
        comments there is nothing, whatever the router called the page."""
        from webgraph.boilerplate import strip_comments
        from webgraph.pipeline import build_document

        comments = "".join(
            f'<tr class="comment"><td><p>Comment {i}: IA works the same way as much of the internet, they allow uploads and answer DMCA claims.</p></td></tr>'
            for i in range(3)
        )
        html = f'<html><body><a href="/login">login</a><table class="comment-tree">{comments}</table><p>Guidelines | FAQ | Lists | API | Security | Legal | Apply to YC | Contact</p></body></html>'
        document = build_document(html, "https://news.test/item?id=1")
        assert any(b.widget == "comments" for b in document.blocks)
        assert len(strip_comments(list(document.blocks))) == len(document.blocks)

    def test_forum_policy_keeps_them(self) -> None:
        from webgraph.content import select_content
        from webgraph.pagetype import policy_for
        from webgraph.pipeline import build_document

        document = build_document(self.story(), "https://forum.test/t/1")
        forum = select_content(list(document.blocks), model=None, config=policy_for("forum"), main_content=False).blocks
        article = select_content(list(document.blocks), model=None, config=policy_for("article"), main_content=False).blocks
        assert any("Reply" in b.text for b in forum)
        assert not any("Reply" in b.text for b in article)


class TestInnermostLandmarkWins:
    """protiviti.com leaves a <nav> and an <li> unclosed, so the parser nests the whole
    <main> inside them and every path on the page runs through `/nav/`. The blocks are in
    main all the same, and main is the innermost landmark."""

    def test_main_nested_under_an_unclosed_nav_is_kept(self) -> None:
        from webgraph.boilerplate import strip_landmarks
        from webgraph.pipeline import build_document

        body = "".join(f"<p>Paragraph {i} of the service description, long enough to be prose.</p>" for i in range(8))
        html = (
            "<html><body><header><nav><ul><li><a href='/'>Home</a>"
            f"<main><article><h1>Data and Analytics Services</h1>{body}</article></main>"
            "</li></ul></nav></header></body></html>"
        )
        document = build_document(html, "https://consult.test/services")
        assert any("/nav/" in b.xpath for b in document.blocks if b.text.startswith("Paragraph"))
        kept = strip_landmarks(list(document.blocks))
        assert sum(1 for b in kept if b.text.startswith("Paragraph")) == 8
        assert not any(b.text == "Home" for b in kept)


class TestCalloutAsides:
    """Starlight renders every Note and Tip as `<aside aria-label="Tip">`. A callout is the
    article's own words; a sidebar of teasers is not, and only the latter is a landmark."""

    def test_labelled_callout_is_kept(self) -> None:
        from webgraph.boilerplate import strip_landmarks
        from webgraph.pipeline import build_document

        body = "".join(f"<p>Paragraph {i} of the guide, long enough to read as prose on its own.</p>" for i in range(6))
        html = (
            f"<html><body><main><article><h1>Markdown</h1>{body}"
            '<aside aria-label="Tip" class="starlight-aside starlight-aside--tip"><p>Tip</p>'
            "<p>For additional functionality, add the MDX integration to write your content using MDX.</p></aside>"
            "</article><aside class=\"right-sidebar-container\"><h2>On this page</h2><ul><li>Markdown</li><li>MDX</li></ul></aside></main></body></html>"
        )
        document = build_document(html, "https://docs.test/guides/markdown/")
        kept = strip_landmarks(list(document.blocks))
        assert any("MDX integration" in b.text for b in kept)
        assert not any(b.text == "On this page" for b in kept)
