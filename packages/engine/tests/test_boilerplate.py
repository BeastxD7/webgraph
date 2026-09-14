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


    def test_camel_case_cookie_wrapper_is_consent(self) -> None:
        """qburst.com hand-rolls its dialog as `cookieWrapper` > `cookiePolicy` > `cookieText`;
        with the nav lists beside it gone, its 200 words were bridged into the page."""
        from webgraph.pipeline import build_document

        html = (
            '<html><body><header><div class="cookieWrapper cookieWrapperCommon"><div class="cookiePolicy">'
            "<p>This website uses cookies.</p><p>Cookies are small text files that allow us to create the best browsing experience.</p>"
            "</div></div></header><main><h1>Quality Engineering</h1>"
            + "".join(f"<p>Offering {i}: we deliver comprehensive functional testing to validate every feature you ship.</p>" for i in range(6))
            + "</main></body></html>"
        )
        document = build_document(html, "https://qburst.test/services")
        assert [b.widget for b in document.blocks if "small text files" in b.text] == ["consent"]
        assert all(b.widget is None for b in document.blocks if b.text.startswith("Offering"))

    def test_a_cookie_policy_page_is_not_a_dialog(self) -> None:
        """A page that is nothing but its `cookie-policy` container is the policy itself."""
        from webgraph.pipeline import build_document

        html = (
            '<html><body><div id="cookie-policy"><h1>Cookie policy</h1>'
            + "".join(f"<p>Section {i}: we use cookies to remember your preferences, to measure traffic and to keep you signed in.</p>" for i in range(8))
            + "</div></body></html>"
        )
        document = build_document(html, "https://site.test/cookies")
        assert all(b.widget is None for b in document.blocks)

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

    def test_the_stripped_thread_is_kept_aside_as_comments(self) -> None:
        """The thread leaves the article and arrives in `ContentSelection.comments`, in page
        order, so the API can return it as `comments_markdown`: the discussion under a story
        is what a reader of a Slashdot page came for, and two of WCEB's eight corpora count
        it as content."""
        from webgraph.content import select_content
        from webgraph.pipeline import build_document

        document = build_document(self.story(), "https://news.test/story")
        selection = select_content(list(document.blocks), model=None, title="Story")
        replies = [b.text for b in selection.comments if b.text.startswith("Reply")]
        assert replies == [f"Reply {i}: a paragraph of opinion long enough to read like the article itself." for i in range(6)]
        assert all(b.widget == "comments" for b in selection.comments)
        assert not any(b.text.startswith("Reply") for b in selection.blocks)

    def test_a_forum_keeps_its_thread_and_reports_no_comments(self) -> None:
        """A thread that is most of the page under the forum policy stays in the content, so
        nothing is set aside."""
        from webgraph.content import select_content
        from webgraph.pagetype import policy_for
        from webgraph.pipeline import build_document

        replies = "".join(
            f'<li class="comment"><p>Reply {i}: a paragraph of opinion long enough to read like the opening post itself, and then some.</p></li>'
            for i in range(40)
        )
        html = f'<html><body><main><article><h1>Thread</h1><p>The opening post asks a question in two sentences. It is short.</p></article><section id="comments"><ol class="comment-list">{replies}</ol></section></main></body></html>'
        document = build_document(html, "https://forum.test/t/1")
        selection = select_content(list(document.blocks), model=None, config=policy_for("forum"), title="Thread")
        assert selection.comments == ()
        assert sum(1 for b in selection.blocks if b.text.startswith("Reply")) == 40

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

        # A thread: a short opening post and a long tail of replies in `.comment`s. Under
        # the forum policy the replies hold most of the page and are the content; under
        # the article policy they are the comments under a story and go.
        replies = "".join(
            f'<li class="comment"><p>Reply {i}: a paragraph of opinion long enough to read like the article itself, and a little more.</p></li>'
            for i in range(14)
        )
        opening = (
            "<p>The opening post asks a question at some length, describing the setup, what was tried, and what happened instead.</p>"
            "<p>It runs to a few sentences because the author wanted to be thorough, which is more than most opening posts manage.</p>"
            "<p>Still, it is a fraction of the thread beneath it, which is where the answer eventually turns up, several pages down.</p>"
        )
        html = f'<html><body><main><article><h1>Thread</h1>{opening}</article><ol class="comment-list">{replies}</ol></main></body></html>'
        document = build_document(html, "https://forum.test/t/1")
        forum = select_content(list(document.blocks), model=None, config=policy_for("forum"), main_content=False).blocks
        article = select_content(list(document.blocks), model=None, config=policy_for("article"), main_content=False).blocks
        assert any("Reply" in b.text for b in forum)
        assert not any("Reply" in b.text for b in article)

    def test_forum_drops_minor_comments_under_answers(self) -> None:
        """Stack Exchange: the answers are the content and the one-line comments under each
        are asides; they hold a small share of the page and go under the forum policy too."""
        from webgraph.content import select_content
        from webgraph.pagetype import policy_for
        from webgraph.pipeline import build_document

        answers = "".join(
            f"<div class='answer'><p>Answer {i}: You can use AutoHotkey to move the keyboard focus to the file pane; bind a hotkey and send a space to the DirectUIHWND control, which works on every Explorer window.</p>"
            f"<ul class='comments-list'><li class='comment'><span>Now tell me how you really feel {i}.</span></li></ul></div>"
            for i in range(5)
        )
        html = f"<html><body><main><h1>Keyboard shortcut to focus the file pane?</h1>{answers}</main></body></html>"
        document = build_document(html, "https://superuser.test/questions/1")
        kept = select_content(list(document.blocks), model=None, config=policy_for("forum"), main_content=False).blocks
        assert sum(1 for b in kept if b.text.startswith("Answer ")) == 5
        assert not any("really feel" in b.text for b in kept)


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


class TestMainScopeByScript:
    """asahi.com: a Japanese article behind a mega-menu. A whitespace split counted every
    Japanese block as one word, so the <main> held nothing against the menu; and the menu
    outweighed the article, which a 50% share guard never allowed."""

    def test_a_japanese_main_behind_a_mega_menu_is_scoped(self) -> None:
        from webgraph.boilerplate import scope_to_main
        from webgraph.pipeline import build_document

        menu = "".join(f"<li><a href='/s/{i}'>メニュー項目{i}のリンクテキスト</a></li>" for i in range(120))
        body = "".join(
            f"<p>第{i}段落。川崎市にある小田急線・柿生駅から徒歩十五分ほどの閑静な住宅街にある分譲マンションは、全十九戸で築三十年ほどを迎える。"
            "このマンションでは三年前に一度、将来の建て替えを検討したが、費用の試算に住民は驚いた。</p>"
            for i in range(6)
        )
        html = f"<html><body><header><ul>{menu}</ul></header><main><h1>建て替えなんて絶対無理</h1>{body}</main></body></html>"
        document = build_document(html, "https://news.test/articles/1.html")
        scoped = scope_to_main(list(document.blocks))
        assert all(b.in_main for b in scoped)
        assert not any("メニュー項目" in b.text for b in scoped)
        assert len(scoped) >= 7


class TestCommentsGuardIsProse:
    """A short news story with a thread under it loses the thread; a page whose only prose
    is the thread keeps it. Counting every remaining word could not tell them apart -- a
    nav strip and a footer are words too -- so the guard counts sentences."""

    @staticmethod
    def page(story_paragraphs: int) -> str:
        story = "".join(
            "<p>The council voted on Tuesday to approve the new bridge after a debate that ran late into the evening.</p>"
            for _ in range(story_paragraphs)
        )
        thread = "".join(
            f'<li class="comment"><p>Reply {i}: a long paragraph of opinion that reads exactly like the article above it does.</p></li>'
            for i in range(8)
        )
        return (
            "<html><body><p>Home | News | Sport | Weather | Login | Subscribe | Search | Newsletter | Contact | About | Terms | Privacy</p>"
            f"<main><h1>Council approves bridge</h1>{story}<ol class='comment-list'>{thread}</ol></main>"
            "<p>Guidelines | FAQ | Lists | API | Security | Legal | Apply | Contact | Search | Jobs | Help | Press</p></body></html>"
        )

    def test_a_short_story_loses_its_thread(self) -> None:
        from webgraph.boilerplate import strip_comments
        from webgraph.pipeline import build_document

        blocks = list(build_document(self.page(story_paragraphs=4), "https://news.test/a").blocks)
        kept = strip_comments(blocks)
        assert not any("Reply" in b.text for b in kept)

    def test_a_page_with_no_prose_but_its_thread_keeps_it(self) -> None:
        from webgraph.boilerplate import strip_comments
        from webgraph.pipeline import build_document

        blocks = list(build_document(self.page(story_paragraphs=0), "https://news.test/a").blocks)
        kept = strip_comments(blocks)
        assert any("Reply" in b.text for b in kept)


class TestRails:
    """indiapost.com: a "Breaking News" ticker of ten headline-plus-blurb items above the
    article, each long enough to score as prose, and the boundary step ran across them."""

    def test_named_ticker_is_stripped(self) -> None:
        from webgraph.boilerplate import strip_landmarks
        from webgraph.pipeline import build_document

        items = "".join(
            f"<li><a href='/n/{i}'>Headline number {i} about something else</a> CITY: The first sentence of that other story, long enough to look like prose.</li>"
            for i in range(10)
        )
        body = "".join(f"<p>Paragraph {i} of the actual article, long enough to be read as prose on its own, and then some more words.</p>" for i in range(24))
        html = f'<html><body><div class="breaking-news"><b>Breaking News</b><ul>{items}</ul></div><article><h1>Deportees return home</h1>{body}</article></body></html>'
        document = build_document(html, "https://news.test/story")
        assert sum(1 for b in document.blocks if b.widget == "rail") >= 10
        kept = strip_landmarks(list(document.blocks))
        assert not any("Headline number" in b.text for b in kept)
        assert sum(1 for b in kept if b.text.startswith("Paragraph")) == 24

    def test_related_alone_is_not_a_rail(self) -> None:
        from webgraph.pipeline import build_document

        html = '<html><body><main><div class="related-info"><p>The related information here is part of the article itself.</p></div></main></body></html>'
        document = build_document(html, "https://news.test/story")
        assert all(b.widget is None for b in document.blocks)


    def test_a_rail_name_around_the_headline_or_article_body_is_not_a_rail(self) -> None:
        """jpost.com: the headline row and the story row are both `g-row-breaking-news`,
        named after the section like the ticker beside them; the story says what it is
        with `itemprop="articleBody"`. The page scored 0.00 on the Zyte benchmark."""
        from webgraph.pipeline import build_document

        ticker = "".join(f'<div class="breaking-news-link-container"><a href="/b/{i}">Ticker headline {i} about something else</a></div>' for i in range(12))
        html = (
            '<html><body><div class="g-row-breaking-news"><h1>Son of former president stabbed to death</h1><p>By STAFF</p></div>'
            '<div class="g-row-breaking-news"><div class="article-inner-content-breaking-news" itemprop="articleBody">'
            "The son of the former president was stabbed to death, while another man was critically injured trying to stop the assailant, the broadcaster reported on Wednesday. "
            "The stabbing occurred during a presentation at the clinic where he worked as a chief physician.</div></div>"
            f'<div class="break-news breaking-news-lst">{ticker}</div></body></html>'
        )
        document = build_document(html, "https://news.test/Breaking-News/story")
        widgets = {b.text[:12]: b.widget for b in document.blocks}
        assert widgets["Son of forme"] is None
        assert widgets["By STAFF"] is None
        assert widgets["The son of t"] is None
        assert widgets["Ticker headl"] == "rail"

    def test_named_footer_and_nav_are_chrome(self) -> None:
        """Before HTML5 a page named its landmarks instead of marking them: jpost.com's
        400-word footer is `div.footer-wrap`, and with nothing to strip it outscored a
        one-paragraph story."""
        from webgraph.boilerplate import strip_landmarks
        from webgraph.pipeline import build_document

        html = (
            '<html><body><div id="nav"><ul><li><a href="/">Home</a></li><li><a href="/news">News</a></li><li><a href="/sport">Sport</a></li></ul></div>'
            "<div id='content'><h1>Story</h1><p>The body of the story, a single paragraph of news copy long enough to be read as prose by anyone.</p>"
            "<p>A second paragraph follows, with the detail of who said what to whom and when, as news copy does.</p>"
            "<p>A third paragraph closes the story with the reaction of the authorities and what happens next week.</p></div>"
            '<div class="all-screen-footer-wrap"><div class="footer-wrap"><p>The customer service center can be contacted with any questions or requests by telephone, fax or email at the addresses below.</p>'
            "<p>Copyright 2019 Inc. All rights reserved. Terms of Use. Privacy Policy. Designed by us.</p></div></div></body></html>"
        )
        document = build_document(html, "https://news.test/story")
        kept = strip_landmarks(list(document.blocks))
        texts = [b.text for b in kept]
        assert texts[0] == "Story"
        assert len(texts) == 4
        assert not any("Copyright" in t or "customer service" in t or t == "Home" for t in texts)

    def test_a_named_footer_that_is_most_of_the_page_stays(self) -> None:
        """The share guard on rails applies: a `#footer` holding the page is the page."""
        from webgraph.pipeline import build_document

        html = (
            '<html><body><p>Intro.</p><div id="footer">'
            + "".join(f"<p>Paragraph {i} of the only text on this page, long enough to count as its content on any reading.</p>" for i in range(10))
            + "</div></body></html>"
        )
        document = build_document(html, "https://odd.test/")
        assert all(b.widget is None for b in document.blocks)

class TestPostFurniture:
    """forum.nationstates.net (phpBB) and every XenForo board: under each post a signature,
    beside it a user card -- rank, post count, join date. The annotators keep the post and
    the byline and leave the furniture; so does the engine now."""

    def test_signature_and_user_card_are_stripped_and_the_post_kept(self) -> None:
        from webgraph.boilerplate import strip_landmarks
        from webgraph.pipeline import build_document

        posts = "".join(
            f'<div class="post"><dl class="postprofile"><dt>User {i}</dt><dd>Senator</dd><dd>Posts: 4032</dd><dd>Founded: Dec 11, 2021</dd></dl>'
            f'<div class="postbody"><p class="author">by User {i} » Tue Aug 27, 2019</p>'
            f"<div class=\"content\"><p>Post {i}: the season is one of the wildest in football history, with minnows qualifying everywhere and chaos on the world scene.</p></div>"
            f'<div class="signature">NS local megafan {i}. This nation does not reflect my politics. Member of The Glitches.</div></div></div>'
            for i in range(6)
        )
        html = f"<html><body><main>{posts}</main></body></html>"
        document = build_document(html, "https://forum.test/viewtopic.php?t=1")
        kept = strip_landmarks(list(document.blocks))
        texts = [b.text for b in kept]
        assert sum(1 for t in texts if t.startswith("Post ")) == 6
        assert any(t.startswith("by User 3") for t in texts)
        assert not any("megafan" in t for t in texts)
        assert not any(t.startswith("Posts: 4032") for t in texts)

    def test_xenforo_message_body_is_not_furniture(self) -> None:
        from webgraph.pipeline import build_document

        html = (
            '<html><body><main><article class="message"><div class="message-cell message-cell--user"><div class="message-user">'
            '<h4 class="message-name">alice</h4><div class="message-userExtras"><dl><dt>Messages</dt><dd>1,204</dd></dl></div></div></div>'
            '<div class="message-cell message-cell--main"><div class="message-userContent"><article class="message-body">'
            "<div class=\"bbWrapper\">The message body itself, which is the content of the thread and must survive whatever the user cell is called.</div>"
            "</article></div></div></article></main></body></html>"
        )
        document = build_document(html, "https://forum.test/threads/1/")
        body = [b for b in document.blocks if b.text.startswith("The message body")]
        assert body and body[0].widget is None
        assert any(b.widget == "post-furniture" for b in document.blocks if "1,204" in b.text or b.text == "Messages")
