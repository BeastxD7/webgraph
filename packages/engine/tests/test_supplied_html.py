"""Bring your own HTML: `resolve_supplied` reads a page the caller already has.

Some sites refuse every automated fetch -- stackoverflow.com behind a Cloudflare challenge,
nyc.gov behind Akamai, anything behind a login. The engine does not disguise the client;
a caller who has the page in their own browser hands its HTML over and gets the same
`text` / `markdown`. Two properties are pinned here: the path fetches **nothing** (a
supplied frameset must not make this process fetch frame URLs), and a supplied wall is
refused the way a fetched one is -- never a false output.
"""

from __future__ import annotations

import contextlib

import pytest

from webgraph import config
from webgraph.page import stream_page
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.resolve import PageBlockedError, Strategy, resolve_page, resolve_supplied

PAGE = (
    "<html><head><title>Sample page</title></head><body><nav><a href='/'>Home</a></nav>"
    "<h1>Sample page</h1><p>The first paragraph of a real page, long enough to be a "
    "paragraph, with <a href='/next'>a relative link</a>.</p>"
    "<p>And a second one, so the page has some words in it.</p>"
    "<img src='/pic.png' alt='a picture'></body></html>"
)

CLOUDFLARE_BLOCK = """<!doctype html><html><head><title>Attention Required! | Cloudflare</title></head>
<body><h1>Sorry, you have been blocked</h1>
<p>You are unable to access example.com</p>
<h2>Why have I been blocked?</h2>
<p>This website is using a security service to protect itself from online attacks.</p>
<p>Cloudflare Ray ID: 8c1d2e3f4a5b6c7d</p></body></html>"""

CHALLENGE = (
    "<html><head><script>window._cf_chl_opt={cvId:'3'};</script></head>"
    "<body><div id='challenge-platform'></div></body></html>"
)

THREAD = "https://www.example.test/r/programming/comments/1b2x1yq/"
LOGIN = (
    "https://www.example.test/login/?reason=lor2"
    "&dest=https%3A%2F%2Fwww.example.test%2Fr%2Fprogramming%2Fcomments%2F1b2x1yq%2F"
)
LOGIN_FORM = (
    "<html><head><title>Sign in</title>{declared}</head><body><h1>Sign in</h1>"
    "<p>New here? Join now</p><form><label>Email or phone</label><input type='email'>"
    "<label>Password</label><input type='password'><button>Sign in</button></form>"
    "<p>Forgot password?</p></body></html>"
)

FRAMESET = (
    "<html><head><title>Alice</title></head>"
    "<frameset rows='50,*'><frame src='/toc.html' name='toc'>"
    "<frame src='http://internal.example.test/secret' name='text'></frameset>"
    "<noframes><body><p>This page uses frames.</p></body></noframes></html>"
)


class TestASuppliedPageReads:
    def test_text_markdown_and_strategy(self) -> None:
        resolved = resolve_supplied(PAGE, "https://www.example.test/dir/page.html")
        assert resolved.strategy is Strategy.SUPPLIED
        assert "first paragraph of a real page" in resolved.document.text
        markdown = to_markdown(resolved.document, options=MarkdownOptions())
        assert "# Sample page" in markdown
        # `url` is the base for links and images, as it is on a fetched page.
        assert "https://www.example.test/next" in markdown
        assert any(b.href == "https://www.example.test/pic.png" for b in resolved.document.blocks)

    def test_the_result_says_what_it_is(self) -> None:
        """One representation, unmeasured: the counts say so, and the note names the two
        caveats a reader has to know about -- source order, hidden matter."""
        resolved = resolve_supplied(PAGE, "https://www.example.test/page")
        chars = len(resolved.document.text)
        assert resolved.static_chars == chars == resolved.union_chars
        assert resolved.rendered_chars == 0
        assert resolved.static_coverage == 1.0
        assert resolved.render_error is not None
        assert resolved.render_error.startswith("HTML supplied by the caller")
        assert "source order" in resolved.render_error
        assert resolved.document.url == "https://www.example.test/page"
        # Nothing observed: no browser ran, so the runtime evidence is the empty default.
        assert not resolved.runtime.versions and not resolved.runtime.requests

    def test_resolve_page_does_not_accept_the_strategy(self) -> None:
        """Every other value names how to fetch. This one would have fallen through to the
        union branch and fetched both ways while reporting neither."""
        with pytest.raises(ValueError, match="resolve_supplied"):
            resolve_page("https://www.example.test/", strategy=Strategy.SUPPLIED)


class TestASuppliedWallIsRefused:
    def test_a_pasted_cloudflare_block_page(self) -> None:
        with pytest.raises(PageBlockedError) as caught:
            resolve_supplied(CLOUDFLARE_BLOCK, "https://www.example.test/page")
        assert caught.value.kind == "block"
        assert "block page" in str(caught.value)
        assert "you have been blocked" in str(caught.value).lower()

    def test_a_pasted_challenge_script(self) -> None:
        with pytest.raises(PageBlockedError) as caught:
            resolve_supplied(CHALLENGE, "https://www.example.test/page")
        assert caught.value.kind == "challenge"
        assert caught.value.challenge == "Cloudflare"

    def test_a_pasted_login_page_that_declares_itself(self) -> None:
        """A supplied document never redirected, so the one place it can say where it is
        is its own canonical. linkedin's shape: a sign-in form declaring itself at a
        login URL, handed over with the URL it was meant to guard."""
        declared = f"<link rel='canonical' href='{LOGIN}'>"
        with pytest.raises(PageBlockedError) as caught:
            resolve_supplied(LOGIN_FORM.format(declared=declared), THREAD)
        assert caught.value.kind == "login"
        assert caught.value.login_url == LOGIN
        assert caught.value.url == THREAD
        assert f"redirected to a login page ({LOGIN})" in str(caught.value)

    def test_og_url_counts_as_a_declaration_too(self) -> None:
        declared = f"<meta property='og:url' content='{LOGIN}'>"
        with pytest.raises(PageBlockedError) as caught:
            resolve_supplied(LOGIN_FORM.format(declared=declared), THREAD)
        assert caught.value.kind == "login"

    def test_a_login_form_declaring_nothing_is_judged_on_its_words(self) -> None:
        """No declaration, no redirect to judge: a short page with a password field is
        still a page, as it is when fetched at its own address."""
        resolved = resolve_supplied(LOGIN_FORM.format(declared=""), THREAD)
        assert resolved.strategy is Strategy.SUPPLIED
        assert "Password" in resolved.document.text

    def test_a_page_declaring_itself_is_not_a_redirect(self) -> None:
        declared = "<link rel='canonical' href='https://www.example.test/dir/page.html'>"
        html = PAGE.replace("<head>", f"<head>{declared}")
        resolved = resolve_supplied(html, "https://www.example.test/dir/page.html")
        assert resolved.strategy is Strategy.SUPPLIED

    def test_an_empty_document_is_refused_not_returned(self) -> None:
        with pytest.raises(ValueError, match="no readable text"):
            resolve_supplied("<html><body><div></div></body></html>", "https://www.example.test/")


class TestNothingIsFetched:
    def test_a_supplied_frameset_does_not_fetch_its_frames(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caller who can name frame URLs in pasted HTML must not be naming URLs for this
        process to fetch from inside its network. The frameset is parsed as the markup it
        is; whether that reads as a page or is refused as empty is not the point here."""
        from webgraph import resolve as module

        def never(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("resolve_supplied fetched")

        monkeypatch.setattr(module, "fetch_static", never)
        monkeypatch.setattr(module, "render_page", never)
        with contextlib.suppress(ValueError):
            resolve_supplied(FRAMESET, "https://www.example.test/alice.html")

    def test_an_ordinary_page_does_not_fetch_either(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph import resolve as module

        def never(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("resolve_supplied fetched")

        monkeypatch.setattr(module, "fetch_static", never)
        monkeypatch.setattr(module, "render_page", never)
        resolved = resolve_supplied(PAGE, "http://nope.invalid/page")
        assert resolved.strategy is Strategy.SUPPLIED


class TestSize:
    def test_oversize_html_is_refused_with_the_limit_named(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "FETCH_MAX_BYTES", 1_000)
        big = "<html><body><p>" + "words " * 400 + "</p></body></html>"
        with pytest.raises(ValueError) as caught:
            resolve_supplied(big, "https://www.example.test/")
        message = str(caught.value)
        assert "over the 1,000-byte limit" in message
        assert "supplied HTML" in message

    def test_empty_html_is_refused(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            resolve_supplied("   ", "https://www.example.test/")


class TestTheStream:
    def test_stream_page_reads_supplied_html(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph import resolve as module

        def never(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("stream_page fetched")

        monkeypatch.setattr(module, "fetch_static", never)
        monkeypatch.setattr(module, "render_page", never)

        got = list(stream_page("http://nope.invalid/page", html=PAGE))
        assert not [e for e in got if e["type"] == "error"]
        first = got[0]
        assert first["type"] == "stage" and first["stage"] == "resolve"
        assert first["message"] == "Reading the HTML supplied by the caller"
        resolve = next(e for e in got if e["type"] == "resolve")
        assert resolve["strategy"] == "supplied"
        assert resolve["rendered_chars"] == 0
        assert resolve["render_error"].startswith("HTML supplied by the caller")
        done = got[-1]
        assert done["type"] == "done"
        assert "first paragraph of a real page" in done["text"]
        assert done["markdown"]

    def test_a_supplied_wall_ends_the_stream_with_an_error(self) -> None:
        got = list(stream_page("https://www.example.test/page", html=CLOUDFLARE_BLOCK))
        assert got[-1]["type"] == "error"
        assert got[-1]["stage"] == "resolve"
        assert "block page" in got[-1]["message"]
