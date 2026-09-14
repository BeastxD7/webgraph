"""Union-resolution tests.

These pin the completeness property: merging two representations of a page must never lose
content that either one had. Every case here is drawn from a failure measured against real
sites, so a regression reproduces a real-world data loss rather than a hypothetical one.
"""

from __future__ import annotations

import pytest

from webgraph.pipeline import build_document
from webgraph.resolve import Strategy, union_documents
from webgraph.types import Rect


def doc(body: str, *, geometry: dict[str, Rect] | None = None):
    return build_document(f"<html><body>{body}</body></html>", "https://example.com/", geometry=geometry)


class TestUnionKeepsEverything:
    def test_render_only_content_is_kept(self) -> None:
        """The ordinary hydration case: the render reveals content static never had."""
        static = doc("<p>Shared intro</p>")
        rendered = doc("<p>Shared intro</p><p>Hydrated content</p>")

        merged, only_static, only_rendered = union_documents(static, rendered)
        assert "Hydrated content" in merged.text
        assert only_rendered == 1
        assert only_static == 0

    def test_static_only_content_is_kept(self) -> None:
        """Measured on bbc.co.uk: a consent wall replaced the article on render.

        Choosing the rendered document would have discarded half the page.
        """
        static = doc("<p>Full article body</p><p>Second paragraph</p>")
        rendered = doc("<p>Accept cookies to continue</p>")

        merged, only_static, _only_rendered = union_documents(static, rendered)
        assert "Full article body" in merged.text
        assert "Second paragraph" in merged.text
        assert "Accept cookies to continue" in merged.text
        assert only_static == 2

    def test_both_sides_losing_content_is_survivable(self) -> None:
        """Measured on nuxt.com: 12 blocks unique to each side."""
        static = doc("<p>Common</p><p>Only in static</p>")
        rendered = doc("<p>Common</p><p>Only in rendered</p>")

        merged, only_static, only_rendered = union_documents(static, rendered)
        assert "Only in static" in merged.text
        assert "Only in rendered" in merged.text
        assert only_static == 1
        assert only_rendered == 1

    def test_no_duplication_of_shared_content(self) -> None:
        static = doc("<p>Identical</p>")
        rendered = doc("<p>Identical</p>")
        merged, only_static, only_rendered = union_documents(static, rendered)
        assert merged.text.count("Identical") == 1
        assert (only_static, only_rendered) == (0, 0)

    def test_whitespace_and_case_variants_are_one_block(self) -> None:
        """Hydration reflows whitespace; that must not read as new content."""
        static = doc("<p>Some   Content</p>")
        rendered = doc("<p>some content</p>")
        _merged, only_static, only_rendered = union_documents(static, rendered)
        assert (only_static, only_rendered) == (0, 0)

    def test_a_missing_space_is_not_new_content(self) -> None:
        """linear.app: the static page runs two inline spans together ("NewLoops →",
        "Karri·2min ago"); the rendered one knows the second span was laid out as its own
        line and breaks there. Same block, and the rendered spelling is the one kept."""
        static = doc("<p>NewLoops →</p><p>Linear created the issue on behalf of Karri·2min ago</p>")
        rendered = doc("<p>New Loops →</p><p>Linear created the issue on behalf of Karri · 2min ago</p>")
        merged, only_static, only_rendered = union_documents(static, rendered)
        assert (only_static, only_rendered) == (0, 0)
        assert [b.text for b in merged.blocks] == ["New Loops →", "Linear created the issue on behalf of Karri · 2min ago"]

    def test_a_static_block_that_runs_a_rendered_block_into_hidden_matter_is_dropped(self) -> None:
        """linear.app's <h1> holds the headline and a `display: none` mobile copy of it. The
        rendered fetch sees the copy is hidden and strips it; the static one cannot and
        emits "HeadlineHeadline". That is the dirtier copy of a block already there."""
        static = doc("<h1>The product development system for teams and agentsThe product development system for teams and agents</h1><p>Body of the page follows here.</p>")
        rendered = doc("<h1>The product development system for teams and agents</h1><p>Body of the page follows here.</p>")
        merged, only_static, only_rendered = union_documents(static, rendered)
        assert only_static == 0  # the jammed copy is not "content only the static page had"
        assert only_rendered == 1  # the clean headline is, as far as the keys can tell, new
        assert [b.text for b in merged.blocks if b.kind.value == "heading"] == ["The product development system for teams and agents"]

    def test_a_short_rendered_block_does_not_swallow_static_content(self) -> None:
        """"Menu" begins a lot of things; only a rendered block of some length counts."""
        static = doc("<p>Menu</p><p>Menu of the day: soup, bread and a long list of things.</p>")
        rendered = doc("<p>Menu</p>")
        _merged, only_static, _only_rendered = union_documents(static, rendered)
        assert only_static == 1


class TestUnionOrdering:
    def test_rendered_order_leads(self) -> None:
        """The rendered document's order is measured; the static document's is assumed."""
        static = doc("<p>Static extra</p>")
        rendered = doc("<p>First</p><p>Second</p>")
        merged, _, _ = union_documents(static, rendered)
        texts = [b.text for b in merged.blocks]
        assert texts[:2] == ["First", "Second"]
        assert texts[-1] == "Static extra"

    def test_a_static_only_block_lands_beside_its_neighbour(self) -> None:
        """Not at the end.

        Appending them all was measurably wrong: on lemonde.fr the static document
        contributes over two thousand blocks the rendered one lacks, and every one landed
        after the article instead of inside it. The anchor is a block both documents contain,
        which makes the placement observed rather than guessed.
        """
        static = doc("<p>Intro</p><p>Only in static</p><p>Outro</p>")
        rendered = doc("<p>Intro</p><p>Outro</p>")
        merged, _, _ = union_documents(static, rendered)
        texts = [b.text for b in merged.blocks]
        assert texts == ["Intro", "Only in static", "Outro"]

    def test_a_leading_static_only_block_leads(self) -> None:
        static = doc("<p>Before everything</p><p>Shared</p>")
        rendered = doc("<p>Shared</p>")
        merged, _, _ = union_documents(static, rendered)
        assert [b.text for b in merged.blocks] == ["Before everything", "Shared"]

    def test_with_nothing_shared_the_rendered_page_stays_on_top(self) -> None:
        """No common block means no observed adjacency, so the front is as arbitrary as the
        end -- and the rendered document is the authoritative one."""
        static = doc("<p>Static extra</p>")
        rendered = doc("<p>Rendered only</p>")
        merged, _, _ = union_documents(static, rendered)
        assert [b.text for b in merged.blocks] == ["Rendered only", "Static extra"]

    def test_the_merged_label_does_not_overclaim(self) -> None:
        """Copying the rendered document's method claimed geometry for a merge that was
        partly source order: lemonde.fr reported `geometric-anchored` with 7% measured."""
        from webgraph.types import ReadingOrderMethod

        static = doc("<p>Shared</p><p>Only in static</p>")
        rendered = doc("<p>Shared</p>")
        merged, only_static, _ = union_documents(static, rendered)
        assert only_static == 1
        assert merged.reading_order_method in {
            ReadingOrderMethod.GEOMETRIC_ANCHORED,
            ReadingOrderMethod.DOM_FALLBACK,
        }

    def test_appended_blocks_carry_no_geometry(self) -> None:
        """Static-only blocks have no measured position; inventing one would corrupt order."""
        static = doc("<p>Static extra</p>")
        rendered = doc("<p>Rendered</p>")
        merged, _, _ = union_documents(static, rendered)
        appended = [b for b in merged.blocks if b.text == "Static extra"]
        assert appended and appended[0].rect is None

    def test_dom_indices_stay_unique(self) -> None:
        static = doc("<p>A</p><p>B</p>")
        rendered = doc("<p>C</p><p>D</p>")
        merged, _, _ = union_documents(static, rendered)
        indices = [b.dom_index for b in merged.blocks]
        assert len(indices) == len(set(indices))


class TestPayloadUnion:
    def test_payloads_from_both_sides_are_merged(self) -> None:
        """A hydration payload can exist in one representation and not the other."""
        static = build_document(
            '<html><head><script type="application/ld+json">{"@type":"A"}</script></head>'
            "<body><p>x</p></body></html>",
            "https://example.com/",
        )
        rendered = build_document(
            '<html><head><script type="application/ld+json">{"@type":"B"}</script></head>'
            "<body><p>x</p></body></html>",
            "https://example.com/",
        )
        merged, _, _ = union_documents(static, rendered)
        types = {p.data.get("@type") for p in merged.structured_data}
        assert types == {"A", "B"}

    def test_identical_payloads_not_duplicated(self) -> None:
        html = (
            '<html><head><script type="application/ld+json">{"@type":"A"}</script></head>'
            "<body><p>x</p></body></html>"
        )
        static = build_document(html, "https://example.com/")
        rendered = build_document(html, "https://example.com/")
        merged, _, _ = union_documents(static, rendered)
        assert len(merged.structured_data) == 1


class TestStrategyEnum:
    def test_values_are_stable(self) -> None:
        """Serialised into API responses and reports; renaming breaks consumers."""
        assert Strategy.STATIC_ONLY.value == "static-only"
        assert Strategy.RENDERED_ONLY.value == "rendered-only"
        assert Strategy.UNION.value == "union"


class TestMissingPagesAreNeverExtracted:
    """A browser renders a server's 404 page happily, producing 'Not Found -- The requested
    URL was not found on this server' as though it were content.

    Measured on ionidea.com, whose relative links resolve into hundreds of URLs that do not
    exist: 9 such pages were being reported as successful extractions with ~35KB of error
    text between them.
    """

    def test_missing_statuses_cover_404_and_410(self) -> None:
        from webgraph.resolve import MISSING_STATUSES

        assert 404 in MISSING_STATUSES
        assert 410 in MISSING_STATUSES

    def test_blocked_and_transient_statuses_still_render(self) -> None:
        """403/429/5xx mean blocked or transient, not absent -- rendering often succeeds
        where a static fetch was refused. nextjs.org depends on this path."""
        from webgraph.resolve import MISSING_STATUSES

        for status in (403, 429, 500, 502, 503):
            assert status not in MISSING_STATUSES

    def test_error_carries_url_and_status(self) -> None:
        from webgraph.resolve import PageMissingError

        error = PageMissingError("https://example.com/gone", 404)
        assert error.status == 404
        assert error.url == "https://example.com/gone"
        assert "404" in str(error)


class TestWhatTheServerSaid:
    """A refusal quotes the server's own words. Its stylesheet is not among them."""

    def test_the_quote_skips_scripts_and_styles(self) -> None:
        from webgraph.resolve import _server_said

        html = (
            "<html><head><title>SEC.gov | Undeclared Automated Tool</title>"
            "<style>html {height: 100%} body {margin:0; padding:0;} #header {b}</style>"
            "<script>window.x = 1;</script></head><body><h1>Your Request Originates from "
            "an Undeclared Automated Tool</h1><p>Please declare your traffic.</p></body></html>"
        )
        said = _server_said(html)
        assert said.startswith("SEC.gov | Undeclared Automated Tool Your Request Originates")
        assert "height" not in said and "window" not in said

    def test_a_static_only_refusal_names_the_status_and_the_words(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`STATIC_ONLY` with nothing fetched used to say "HTTP 403" and no more; the
        two-path failure already said what the status means and what the server wrote."""
        from webgraph import resolve
        from webgraph.fetch.static import FetchResult

        wall = "<html><body><h1>Access denied: your request was refused</h1></body></html>"
        monkeypatch.setattr(
            resolve,
            "fetch_static",
            lambda url, config=None: FetchResult(  # noqa: ARG005
                url=url,
                requested_url=url,
                status=403,
                html=wall,
                content_type="text/html",
                elapsed_seconds=0.0,
                ok=False,
                error="HTTP 403",
            ),
        )
        with pytest.raises(ValueError) as caught:
            resolve.resolve_page("https://example.com/x", strategy=resolve.Strategy.STATIC_ONLY)
        message = str(caught.value)
        assert "HTTP 403" in message and "refused this client" in message
        assert "Access denied: your request was refused" in message


class TestBlockPages:
    """A wall served with a 200 is a failure, not a short page.

    Reddit's "You've been blocked by network security" used to come back as three blocks,
    typed `listing` at 86% confidence, with a green tick. Nothing downstream can tell a
    block page from a page once it has been accepted as one.
    """

    def test_a_short_page_saying_blocked_is_evidence(self) -> None:
        from webgraph.resolve import block_page_evidence

        text = (
            "You've been blocked by network security. If you think you've been blocked by "
            "mistake, file a ticket below and we'll look into it. File a ticket"
        )
        evidence = block_page_evidence(text)
        assert evidence is not None
        assert "blocked by network security" in evidence

    @pytest.mark.parametrize(
        "text",
        [
            "Just a moment... Enable JavaScript and cookies to continue",
            "Attention Required! | Cloudflare. Please complete the security check to access",
            "Access Denied. You don't have permission to access this resource. Ray ID: 8a1",
            "Pardon Our Interruption. As you were browsing something about your browser made us think you were a bot.",
        ],
    )
    def test_the_common_walls(self, text: str) -> None:
        from webgraph.resolve import block_page_evidence

        assert block_page_evidence(text) is not None

    def test_a_long_page_that_mentions_a_captcha_is_a_page(self) -> None:
        """An article about bot detection is thousands of characters long."""
        from webgraph.resolve import block_page_evidence

        article = ("How CAPTCHA and bot detection work. " * 60) + "Access denied is what users see."
        assert len(article) > 1_500
        assert block_page_evidence(article) is None

    def test_a_short_page_that_says_nothing_of_the_sort_is_a_page(self) -> None:
        from webgraph.resolve import block_page_evidence

        assert block_page_evidence("About Us. Coming soon.") is None
        assert block_page_evidence("") is None

    def test_resolve_raises_rather_than_returning_a_wall(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """End to end through `resolve_page`, with the fetch stubbed to serve a wall."""
        from webgraph import resolve as module
        from webgraph.fetch.static import FetchResult
        from webgraph.resolve import PageBlockedError, Strategy

        html = (
            "<html><head><title>Blocked</title></head><body><h1>You've been blocked by "
            "network security.</h1><p>If you think you've been blocked by mistake, file a "
            "ticket.</p></body></html>"
        )
        monkeypatch.setattr(
            module,
            "fetch_static",
            lambda url, config=None: FetchResult(  # noqa: ARG005  # noqa: ARG005
                url=url,
                requested_url=url,
                status=200,
                html=html,
                content_type="text/html",
                elapsed_seconds=0.01,
                ok=True,
            ),
        )
        with pytest.raises(PageBlockedError) as caught:
            module.resolve_page("https://www.reddit.com/r/x/", strategy=Strategy.STATIC_ONLY)
        assert "block page" in str(caught.value)
        assert "network security" in str(caught.value)


class TestChallengesAndEmptyPages:
    """A page that produced nothing is not a page that was extracted.

    Amazon's home page answers a plain fetch with HTTP 202 and two kilobytes of
    `window.awsWafCookie` -- a JavaScript challenge with no visible words. It came back as a
    successful extraction of zero blocks, typed `service` at 75% confidence, and the crawl
    reported "1 page ok" and stopped.
    """

    @staticmethod
    def stub(monkeypatch: pytest.MonkeyPatch, html: str, status: int = 200) -> None:
        from webgraph import resolve as module
        from webgraph.fetch.static import FetchResult

        monkeypatch.setattr(
            module,
            "fetch_static",
            lambda url, config=None: FetchResult(  # noqa: ARG005  # noqa: ARG005
                url=url,
                requested_url=url,
                status=status,
                html=html,
                content_type="text/html",
                elapsed_seconds=0.01,
                ok=True,
            ),
        )

    def test_an_aws_waf_challenge_is_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.resolve import PageBlockedError, Strategy, resolve_page

        html = (
            '<!DOCTYPE html><html><head><title></title><script type="text/javascript">'
            "window.awsWafCookieDomainList = []; window.gokuProps = {};</script></head>"
            "<body></body></html>"
        )
        self.stub(monkeypatch, html, status=202)
        with pytest.raises(PageBlockedError) as caught:
            resolve_page("https://www.amazon.in/", strategy=Strategy.STATIC_ONLY)
        assert "AWS WAF" in str(caught.value)

    def test_an_empty_response_is_refused_with_its_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.resolve import Strategy, resolve_page

        self.stub(monkeypatch, "<html><head></head><body><div></div></body></html>", status=202)
        with pytest.raises(ValueError, match="no readable text") as caught:
            resolve_page("https://x.test/empty", strategy=Strategy.STATIC_ONLY)
        assert "HTTP 202" in str(caught.value)

    def test_an_image_only_page_is_still_a_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No words is not the same as nothing: a gallery page is its pictures."""
        from webgraph.resolve import Strategy, resolve_page

        html = (
            '<html><body><img src="https://x.test/a.jpg" alt="" width="800" height="600">'
            '<img src="https://x.test/b.jpg" alt="" width="800" height="600"></body></html>'
        )
        self.stub(monkeypatch, html)
        resolved = resolve_page("https://x.test/gallery", strategy=Strategy.STATIC_ONLY)
        assert len(resolved.document.blocks) == 2

    def test_challenge_vendors_are_recognised(self) -> None:
        from webgraph.resolve import challenge_vendor

        assert challenge_vendor("<script src='/cdn-cgi/challenge-platform/h/b'></script>") == "Cloudflare"
        assert challenge_vendor("<script>var _pxhd='x'</script>") == "PerimeterX"
        assert challenge_vendor("<p>Hello</p>") is None


class TestAWallOnOneSide:
    """Cloudflare let a plain fetch of columbia.edu/~fdc/sample.html through and answered
    the browser with "Performing security verification … Ray ID". The union merged the
    wall's sentences into a 4,000-word page, where the block-page check could not see
    them. Each side is judged alone: the wall is left out and named, the page is the page.
    """

    PAGE = (
        "<html><body><h1>Sample page</h1><p>The first paragraph of a real page, long "
        "enough to be a paragraph.</p><p>And a second one, so the page has some words in "
        "it.</p></body></html>"
    )
    WALL = (
        "<html><body><h1>www.example.test</h1><p>Performing security verification</p>"
        "<p>This website uses a security service to protect against malicious bots. This "
        "page is displayed while the website verifies you are not a bot.</p>"
        "<p>Ray ID: a3afa223992eaf9e</p></body></html>"
    )

    @staticmethod
    def stub(monkeypatch: pytest.MonkeyPatch, *, static: str, rendered: str) -> None:
        from webgraph import resolve as module
        from webgraph.fetch.render import RenderResult
        from webgraph.fetch.static import FetchResult

        monkeypatch.setattr(module, "PLAYWRIGHT_AVAILABLE", True)
        monkeypatch.setattr(
            module,
            "fetch_static",
            lambda url, config=None: FetchResult(  # noqa: ARG005  # noqa: ARG005
                url=url,
                requested_url=url,
                status=200,
                html=static,
                content_type="text/html",
                elapsed_seconds=0.01,
                ok=True,
            ),
        )
        monkeypatch.setattr(
            module,
            "render_page",
            lambda url, config=None: RenderResult(  # noqa: ARG005
                url=url, html=rendered, rects={}, ok=True
            ),
        )

    def test_a_wall_served_to_the_browser_is_left_out_and_named(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph import resolve as module

        self.stub(monkeypatch, static=self.PAGE, rendered=self.WALL)
        resolved = module.resolve_page("https://www.example.test/sample.html")
        assert resolved.strategy is Strategy.STATIC_ONLY
        assert "Ray ID" not in resolved.document.text
        assert "first paragraph of a real page" in resolved.document.text
        assert resolved.render_error is not None
        assert "wall" in resolved.render_error and "Ray ID" in resolved.render_error

    def test_a_wall_served_to_the_plain_fetch_is_left_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph import resolve as module

        self.stub(monkeypatch, static=self.WALL, rendered=self.PAGE)
        resolved = module.resolve_page("https://www.example.test/sample.html")
        assert resolved.strategy is Strategy.RENDERED_ONLY
        assert "Ray ID" not in resolved.document.text
        assert "first paragraph of a real page" in resolved.document.text

    def test_walls_on_both_sides_still_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph import resolve as module
        from webgraph.resolve import PageBlockedError

        self.stub(monkeypatch, static=self.WALL, rendered=self.WALL)
        with pytest.raises(PageBlockedError):
            module.resolve_page("https://www.example.test/sample.html")

    def test_a_wall_beside_a_page_with_no_words_still_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """old.reddit.com: the browser gets the wall, the plain fetch a login redirect
        holding one empty image. Neither is the page; returning the image as the page
        would be a false output."""
        from webgraph import resolve as module
        from webgraph.resolve import PageBlockedError

        self.stub(
            monkeypatch,
            static="<html><body><img src='/logo.png' alt=''></body></html>",
            rendered=self.WALL,
        )
        with pytest.raises(PageBlockedError):
            module.resolve_page("https://www.example.test/sample.html")
        # The same redirect with its skip link (14 Sep, after the pre-CSS change made the
        # bare link a block): a few words are not a page either.
        self.stub(
            monkeypatch,
            static="<html><body><a href='#main'>Skip to main content</a><img src='/logo.png' alt=''></body></html>",
            rendered=self.WALL,
        )
        with pytest.raises(PageBlockedError):
            module.resolve_page("https://www.example.test/sample.html")

    def test_two_real_pages_still_merge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph import resolve as module

        self.stub(monkeypatch, static=self.PAGE, rendered=self.PAGE)
        resolved = module.resolve_page("https://www.example.test/sample.html")
        assert resolved.strategy is Strategy.UNION


class TestHiddenInRender:
    """A static-only block the browser laid out and hid is not something the render lost.

    php.net's manual TOC (`nav#trick`, ~100 links under `display: none`) was dropped from
    the rendered document by the renderer's own mark and put straight back by the union
    from the static one; cppreference's hover menus the same (103 and 128 blocks).
    """

    STATIC = (
        "<html><body><nav id='trick'><ul><li>Basic syntax</li><li>Types</li>"
        "<li>Variables and constants of the language</li></ul></nav>"
        "<main><h1>array_map</h1><p>Applies the callback to the elements of the given "
        "arrays.</p><p>Only in the static page: a paragraph the render unmounted.</p>"
        "</main></body></html>"
    )
    RENDERED = (
        "<html><body><nav id='trick' data-wg-hidden='display'><ul><li>Basic syntax</li>"
        "<li>Types</li><li>Variables and constants of the language</li></ul></nav>"
        "<main><h1>array_map</h1><p>Applies the callback to the elements of the given "
        "arrays.</p></main></body></html>"
    )

    def test_hidden_menu_items_stay_out_and_lost_content_stays_in(self) -> None:
        from webgraph.fetch.render import hidden_matter

        static_doc = build_document(self.STATIC, "https://x.test/")
        rendered_doc = build_document(self.RENDERED, "https://x.test/")
        assert not any("Basic syntax" in b.text for b in rendered_doc.blocks)
        hidden = hidden_matter(self.RENDERED)
        merged, only_static, _ = union_documents(static_doc, rendered_doc, hidden=hidden)
        texts = [b.text for b in merged.blocks]
        assert "Basic syntax" not in texts and "Types" not in texts
        assert "Variables and constants of the language" not in texts
        assert "Only in the static page: a paragraph the render unmounted." in texts
        assert only_static == 1

    def test_without_the_browser_view_nothing_changes(self) -> None:
        static_doc = build_document(self.STATIC, "https://x.test/")
        rendered_doc = build_document(self.RENDERED, "https://x.test/")
        merged, only_static, _ = union_documents(static_doc, rendered_doc)
        assert any("Basic syntax" in b.text for b in merged.blocks)
        assert only_static == 4

    def test_a_short_visible_word_is_not_matched_inside_hidden_text(self) -> None:
        from webgraph.fetch.render import hidden_matter

        hidden = hidden_matter(
            "<div data-wg-hidden='display'>Home and away, the long hidden sentence.</div>"
        )
        assert hidden.holds("homeandaway,thelonghiddensentence.", min_chars=12)
        assert hidden.holds("thelonghiddensentence", min_chars=12)  # past the guard, a substring
        assert not hidden.holds("home", min_chars=12)  # short, and not a hidden line of its own
        assert not hidden.holds("nothere", min_chars=12)


class TestLoginWalls:
    """A fetch redirected to a login page is a wall, named as one.

    old.reddit.com/r/programming/comments/1b2x1yq/ sends both fetches to
    `/login/?reason=lor2&dest=…`; www.linkedin.com/feed/ sends the plain fetch to
    `/uas/login?session_redirect=…` and the browser to `/login/?session_redirect=…`. Before
    this the reddit page was refused only because Cloudflare also walled the browser on the
    login page, and the linkedin one came back as twenty blocks of "Sign in", "Email or
    phone", "Password" with a green tick.
    """

    THREAD = "https://www.example.test/r/programming/comments/1b2x1yq/"
    LOGIN = "https://www.example.test/login/?reason=lor2&dest=https%3A%2F%2Fwww.example.test%2Fr%2Fprogramming%2Fcomments%2F1b2x1yq%2F"

    SHELL = "<html><body><a href='#main'>Skip to main content</a><img src='/logo.png' alt=''></body></html>"
    FORM = (
        "<html><body><h1>Sign in</h1><p>New here? Join now</p><form><label>Email or phone"
        "</label><input type='email'><label>Password</label><input type='password'>"
        "<button>Sign in</button></form><p>Forgot password?</p></body></html>"
    )
    WALL = TestAWallOnOneSide.WALL
    PAGE = TestAWallOnOneSide.PAGE
    LONG = "<html><body>" + "".join(f"<p>Paragraph {i} of a page with plenty of words in it.</p>" for i in range(40)) + "</body></html>"

    @staticmethod
    def stub(
        monkeypatch: pytest.MonkeyPatch,
        *,
        static: str,
        rendered: str,
        static_final: str | None = None,
        rendered_final: str | None = None,
    ) -> None:
        """Like `TestAWallOnOneSide.stub`, with each fetch able to end on another URL."""
        from webgraph import resolve as module
        from webgraph.fetch.render import RenderResult
        from webgraph.fetch.static import FetchResult

        monkeypatch.setattr(module, "PLAYWRIGHT_AVAILABLE", True)
        monkeypatch.setattr(
            module,
            "fetch_static",
            lambda url, config=None: FetchResult(  # noqa: ARG005  # noqa: ARG005
                url=static_final or url,
                requested_url=url,
                status=200,
                html=static,
                content_type="text/html",
                elapsed_seconds=0.01,
                ok=True,
            ),
        )
        monkeypatch.setattr(
            module,
            "render_page",
            lambda url, config=None: RenderResult(  # noqa: ARG005
                url=rendered_final or url, html=rendered, rects={}, ok=True
            ),
        )

    def test_a_login_redirect_on_both_sides_is_named_as_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """reddit's shape: the plain fetch lands on an empty login shell, the browser on
        Cloudflare's wall at the same login URL. The redirect is the cause and is what
        the error says; the wall is a consequence."""
        from webgraph import resolve as module
        from webgraph.resolve import PageBlockedError

        self.stub(monkeypatch, static=self.SHELL, rendered=self.WALL, static_final=self.LOGIN, rendered_final=self.LOGIN)
        with pytest.raises(PageBlockedError) as caught:
            module.resolve_page(self.THREAD)
        assert caught.value.kind == "login"
        assert caught.value.login_url == self.LOGIN
        assert f"redirected to a login page ({self.LOGIN})" in str(caught.value)
        assert caught.value.url == self.THREAD

    def test_a_password_field_marks_the_login_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """linkedin's shape: two different login URLs, each with a form."""
        from webgraph import resolve as module
        from webgraph.resolve import PageBlockedError

        feed = "https://www.example.test/feed/"
        plain = "https://www.example.test/uas/login?session_redirect=https%3A%2F%2Fwww.example.test%2Ffeed%2F"
        browser = "https://www.example.test/login/?session_redirect=https%3A%2F%2Fwww.example.test%2Ffeed%2F"
        self.stub(monkeypatch, static=self.FORM, rendered=self.FORM, static_final=plain, rendered_final=browser)
        with pytest.raises(PageBlockedError) as caught:
            module.resolve_page(feed)
        assert "redirected to a login page (" in str(caught.value)

    def test_the_static_only_path_refuses_it_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph import resolve as module
        from webgraph.resolve import PageBlockedError

        self.stub(monkeypatch, static=self.SHELL, rendered=self.PAGE, static_final=self.LOGIN)
        with pytest.raises(PageBlockedError) as caught:
            module.resolve_page(self.THREAD, strategy=Strategy.STATIC_ONLY)
        assert caught.value.kind == "login"

    def test_a_login_redirect_on_one_side_is_a_wall_on_that_side(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A site that sends the plain fetch to sign in and serves the browser the page:
        the login side is left out exactly as a bot wall would be, and the page is read
        from the other side."""
        from webgraph import resolve as module

        self.stub(monkeypatch, static=self.FORM, rendered=self.PAGE, static_final=self.LOGIN)
        resolved = module.resolve_page(self.THREAD)
        assert resolved.strategy is Strategy.RENDERED_ONLY
        assert "Password" not in resolved.document.text
        assert "first paragraph of a real page" in resolved.document.text

        self.stub(monkeypatch, static=self.PAGE, rendered=self.FORM, rendered_final=self.LOGIN)
        resolved = module.resolve_page(self.THREAD)
        assert resolved.strategy is Strategy.STATIC_ONLY
        assert resolved.render_error is not None
        assert "redirected to a login page" in resolved.render_error

    def test_a_login_redirect_beside_a_wall_still_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph import resolve as module
        from webgraph.resolve import PageBlockedError

        self.stub(monkeypatch, static=self.FORM, rendered=self.WALL, static_final=self.LOGIN)
        with pytest.raises(PageBlockedError):
            module.resolve_page(self.THREAD)

    def test_a_long_page_with_a_sign_in_box_is_a_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A shop's header carries a password field; nothing redirected anywhere."""
        from webgraph import resolve as module

        shop = self.LONG.replace("<body>", "<body><form><input type='password'></form>")
        self.stub(monkeypatch, static=shop, rendered=shop)
        assert module.resolve_page("https://shop.example.test/products/").strategy is Strategy.UNION

    def test_a_page_that_links_to_its_login_is_a_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """news.ycombinator.com: a "login" link on the front page, no redirect."""
        from webgraph import resolve as module

        front = self.LONG.replace("<body>", "<body><a href='/login?goto=news'>login</a>")
        self.stub(monkeypatch, static=front, rendered=front)
        assert module.resolve_page("https://news.example.test/").strategy is Strategy.UNION

    def test_a_login_page_asked_for_is_the_login_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Asking for /login and getting /login/ is not a wall: it is what was asked for."""
        from webgraph import resolve as module

        self.stub(
            monkeypatch,
            static=self.FORM,
            rendered=self.FORM,
            static_final="https://www.example.test/login/",
            rendered_final="https://www.example.test/login/",
        )
        assert module.resolve_page("https://www.example.test/login").strategy is Strategy.UNION

    def test_a_trailing_slash_is_not_a_redirect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """/docs/auth -> /docs/auth/ on a short page with a sign-in box: the same page."""
        from webgraph import resolve as module

        self.stub(
            monkeypatch,
            static=self.FORM,
            rendered=self.FORM,
            static_final="https://www.example.test/docs/auth/",
            rendered_final="https://www.example.test/docs/auth/",
        )
        assert module.resolve_page("http://example.test/docs/auth").strategy is Strategy.UNION

    def test_a_login_word_inside_a_path_segment_is_not_a_marker(self) -> None:
        """/blog/how-to-login is a post; /uas/login and /login/ are login pages."""
        from webgraph.resolve import _path_is_login

        assert not _path_is_login("/blog/how-to-login")
        assert not _path_is_login("/logins/")
        assert _path_is_login("/uas/login")
        assert _path_is_login("/login/")
        assert _path_is_login("/LOGIN")
        assert _path_is_login("/users/sign_in")
        assert _path_is_login("/wp-login.php")
        assert not _path_is_login("/session")
        assert _path_is_login("/session/new")

    def test_a_return_parameter_names_the_page_asked_for(self) -> None:
        """`?next=` at an unmarked path counts only when it names the requested page."""
        from webgraph.resolve import _returns_to

        asked = "https://www.example.test/r/programming/"
        assert _returns_to("https://www.example.test/accounts/?next=%2Fr%2Fprogramming%2F", asked)
        assert _returns_to("https://www.example.test/accounts/?returnUrl=https%3A%2F%2Fwww.example.test%2Fr%2Fprogramming", asked)
        assert _returns_to("https://www.example.test/accounts/?session_redirect=https://www.example.test/r/programming/", asked)
        assert not _returns_to("https://www.example.test/accounts/?next=%2Fsomewhere-else%2F", asked)
        assert not _returns_to("https://www.example.test/accounts/?utm_source=x", asked)

    def test_a_login_redirect_is_only_that_when_the_page_is_short_or_has_a_field(self) -> None:
        from webgraph.resolve import login_redirect

        asked = "https://www.example.test/feed/"
        short = build_document(self.SHELL, "https://www.example.test/login/?next=%2Ffeed%2F")
        assert login_redirect(short, asked) == "https://www.example.test/login/?next=%2Ffeed%2F"
        with_field = build_document(self.LONG.replace("<body>", "<body><input type='password'>"), "https://www.example.test/login/")
        assert login_redirect(with_field, asked) == "https://www.example.test/login/"
        long_without = build_document(self.LONG, "https://www.example.test/login/")
        assert login_redirect(long_without, asked) is None
        assert login_redirect(short, None) is None
