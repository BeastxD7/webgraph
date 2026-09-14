"""robots.txt for a single page.

The crawl has honoured robots.txt from the start; a single page never did, so a caller
reading one URL through `/api/text` fetched pages the site had asked automated clients not
to read. Stack Overflow's file is `User-agent: * / Disallow: /` (14 Sep 2026), The Sun's
too. The owner's decision for such sites is the honest one: say the site disallows this
client here, name the file and the rule, and offer the paths that are sanctioned -- the
site's API where one is known, or the HTML the caller already has. Not a disguise.

Two details measured while building this: `urllib.robotparser` matches a User-Agent by its
first `/`-split token, so the engine's browser-shaped agent was `mozilla` to every
robots.txt and a `User-agent: webgraph` rule never applied -- the crawl had the same bug;
and a robots.txt that cannot be fetched means *allow*, by convention, but stays recorded.
"""

from __future__ import annotations

import pytest

from webgraph.fetch.static import FetchConfig, FetchResult

PAGE = "<html><body><h1>The page</h1><p>Enough words to be a page of its own here.</p></body></html>"


def _result(url: str, html: str, status: int = 200) -> FetchResult:
    return FetchResult(
        url=url,
        requested_url=url,
        status=status,
        html=html,
        content_type="text/html",
        elapsed_seconds=0.01,
        ok=status < 400,
        error=None if status < 400 else f"HTTP {status}",
    )


def serve(monkeypatch: pytest.MonkeyPatch, robots: str | None, page: str = PAGE) -> list[str]:
    """A host with the given robots.txt (None = 404) and one page. Records fetched URLs."""
    from webgraph import resolve
    from webgraph.fetch import robots as robots_module

    fetched: list[str] = []

    def fetch(url: str, *, config: FetchConfig | None = None) -> FetchResult:  # noqa: ARG001
        fetched.append(url)
        if url.endswith("/robots.txt"):
            return _result(url, robots or "", 200 if robots is not None else 404)
        return _result(url, page)

    monkeypatch.setattr(resolve, "fetch_static", fetch)
    monkeypatch.setattr(robots_module, "fetch_static", fetch)
    robots_module.forget()
    return fetched


class TestASinglePageHonoursRobots:
    def test_a_disallowed_page_is_refused_with_the_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.resolve import PageDisallowedError, Strategy, resolve_page

        fetched = serve(monkeypatch, "User-agent: *\nDisallow: /\n")
        with pytest.raises(PageDisallowedError) as caught:
            resolve_page("https://stackoverflow.com/questions/1/x", strategy=Strategy.STATIC_ONLY)
        message = str(caught.value)
        assert "https://stackoverflow.com/robots.txt" in message
        assert "Disallow: /" in message and "User-agent: *" in message
        assert "api.stackexchange.com" in message, "the sanctioned path is named"
        assert "html" in message.lower(), "and so is supplying the HTML"
        assert fetched == ["https://stackoverflow.com/robots.txt"], "the page itself was never fetched"

    def test_an_allowed_page_reads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.resolve import Strategy, resolve_page

        fetched = serve(monkeypatch, "User-agent: *\nDisallow: /private/\n")
        resolved = resolve_page("https://example.com/public/page", strategy=Strategy.STATIC_ONLY)
        assert "The page" in resolved.document.text
        assert fetched == ["https://example.com/robots.txt", "https://example.com/public/page"]

    def test_no_robots_file_means_allow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.resolve import Strategy, resolve_page

        serve(monkeypatch, None)
        resolved = resolve_page("https://example.com/page", strategy=Strategy.STATIC_ONLY)
        assert "The page" in resolved.document.text

    def test_the_file_is_fetched_once_per_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.resolve import Strategy, resolve_page

        fetched = serve(monkeypatch, "User-agent: *\nDisallow: /private/\n")
        resolve_page("https://example.com/a", strategy=Strategy.STATIC_ONLY)
        resolve_page("https://example.com/b", strategy=Strategy.STATIC_ONLY)
        assert fetched.count("https://example.com/robots.txt") == 1

    def test_the_caller_can_decline_the_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The crawl has had `respect_robots` since the start; a single page gets the same
        switch, off by explicit request only."""
        from webgraph.resolve import Strategy, resolve_page

        fetched = serve(monkeypatch, "User-agent: *\nDisallow: /\n")
        resolved = resolve_page(
            "https://example.com/page",
            strategy=Strategy.STATIC_ONLY,
            fetch_config=FetchConfig(respect_robots=False),
        )
        assert "The page" in resolved.document.text
        assert "https://example.com/robots.txt" not in fetched

    def test_the_rule_for_this_client_by_name_applies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`User-agent: webgraph` must match this client. Its User-Agent starts with
        `Mozilla/5.0`, which `urllib.robotparser` reads as the client's name."""
        from webgraph.resolve import PageDisallowedError, Strategy, resolve_page

        serve(monkeypatch, "User-agent: webgraph\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
        with pytest.raises(PageDisallowedError) as caught:
            resolve_page("https://example.com/page", strategy=Strategy.STATIC_ONLY)
        assert "User-agent: webgraph" in str(caught.value)

    def test_a_rule_for_another_client_does_not_apply(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.resolve import Strategy, resolve_page

        serve(monkeypatch, "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
        resolved = resolve_page("https://example.com/page", strategy=Strategy.STATIC_ONLY)
        assert "The page" in resolved.document.text

    def test_the_disallowed_error_is_a_value_error(self) -> None:
        """Every "could not resolve" handler treats a ValueError as the failure it is."""
        from webgraph.resolve import PageDisallowedError

        assert issubclass(PageDisallowedError, ValueError)


class TestTheCrawlNamesItselfToRobots:
    def test_allows_matches_the_client_by_its_own_name(self) -> None:
        from urllib.robotparser import RobotFileParser

        from webgraph.crawl.discovery import RobotsPolicy

        parser = RobotFileParser()
        parser.parse(["User-agent: webgraph", "Disallow: /", "", "User-agent: *", "Allow: /"])
        policy = RobotsPolicy(origin="https://example.com", parser=parser, fetched=True)
        assert policy.allows("https://example.com/page") is False
        assert policy.allows("https://example.com/page", FetchConfig().user_agent) is False


class TestTheRuleThatApplied:
    """The refusal quotes the group and the rule that matched, from the file itself."""

    @pytest.mark.parametrize(
        ("robots", "url", "expected"),
        [
            ("User-agent: *\nDisallow: /\n", "https://x.test/a", ("User-agent: *", "Disallow: /")),
            (
                "User-agent: *\nDisallow: /private/\nDisallow: /a/\n",
                "https://x.test/a/b",
                ("User-agent: *", "Disallow: /a/"),
            ),
            (
                "User-agent: webgraph\nDisallow: /docs\n\nUser-agent: *\nAllow: /\n",
                "https://x.test/docs/1",
                ("User-agent: webgraph", "Disallow: /docs"),
            ),
        ],
    )
    def test_names_the_group_and_the_rule(
        self, robots: str, url: str, expected: tuple[str, str]
    ) -> None:
        from webgraph.fetch.robots import rule_that_applied

        assert rule_that_applied(robots, url) == expected
