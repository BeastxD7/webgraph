"""The site report: what a site shows people, what it shows machines, how ready it is for
agents -- from the measurements the engine already makes (`webgraph.report`).

Network-free. One fake host (`serve`) answers every seam the report fetches through --
the plain fetch, the browser, robots.txt, sitemaps, the well-known files, the dead-link
HEADs -- from a map of paths, and the pacing interval is zero. The engine never fetches as another bot,
so the bots table is tested as a *reading* of robots.txt: the group that names the bot,
combined groups, `*`, crawl-delay, and the longest-match rule at the root.
"""

from __future__ import annotations

from datetime import date

import pytest

from webgraph.fetch.static import FetchConfig, FetchResult

Served = dict[str, tuple[int, str] | tuple[int, str, str] | tuple[int, str, str, dict[str, str]]]
"""path -> (status, body[, content-type[, response headers]])."""

PAGE_WORDS = (
    "Enough words here to be a page of its own, with a second sentence so nothing is refused."
)

ROOT = (
    "<html lang='en'><head><title>Acme College | Home</title>"
    "<meta name='description' content='A college that teaches things.'>"
    "<link rel='canonical' href='https://acme.test/'>"
    '<script type="application/ld+json">{"@type":"Organization","name":"Acme"}</script>'
    "</head><body><h1>Acme College</h1>"
    f"<p>{PAGE_WORDS}</p>"
    "<nav><a href='/admissions/'>Admissions</a> <a href='/admissions/fees'>Fees</a> "
    "<a href='/about'>About</a> <a href='/blog/post-1'>Blog</a> <a href='/missing'>Gone</a></nav>"
    "</body></html>"
)
ADMISSIONS = (
    "<html><head><title>Admissions | Acme College</title></head><body><h1>Admissions</h1>"
    f"<p>{PAGE_WORDS}</p><a href='/'>Home</a></body></html>"
)
ABOUT = (
    f"<html><head><title>About</title></head><body><h1>About</h1><p>{PAGE_WORDS}</p></body></html>"
)
BLOG = f"<html><head><title>Post 1 - Acme</title></head><body><h1>Post 1</h1><p>{PAGE_WORDS}</p></body></html>"


def _result(
    url: str,
    status: int,
    body: str,
    content_type: str = "text/html",
    headers: dict[str, str] | None = None,
) -> FetchResult:
    return FetchResult(
        url=url,
        requested_url=url,
        status=status,
        html=body,
        content_type=content_type,
        elapsed_seconds=0.01,
        ok=status < 400,
        error=None if status < 400 else f"HTTP {status}",
        headers={"content-type": content_type, **(headers or {})},
    )


def serve(
    monkeypatch: pytest.MonkeyPatch,
    served: Served,
    *,
    rendered: dict[str, str] | None = None,
    render_ok: bool = True,
) -> list[str]:
    """One host answering from `served` (path -> (status, body[, content-type])) on every
    seam. `rendered` overrides the browser's document per path; `render_ok=False` makes
    every render fail. Returns the list of URLs the plain fetch was asked for."""
    from urllib.parse import urlsplit

    from webgraph import analyze, config, resolve
    from webgraph.crawl import discovery
    from webgraph.fetch import robots as robots_module
    from webgraph.fetch.render import RenderResult
    from webgraph.report import build, pages, signals

    fetched: list[str] = []

    def lookup(url: str) -> FetchResult:
        path = urlsplit(url).path or "/"
        entry = served.get(path)
        if entry is None:
            return _result(url, 404, "<html><body>not found</body></html>")
        status, body = entry[0], entry[1]
        content_type = entry[2] if len(entry) >= 3 else "text/html"
        headers = entry[3] if len(entry) == 4 else None
        return _result(url, status, body, content_type, headers)

    def fetch(url: str, *, config: FetchConfig | None = None) -> FetchResult:  # noqa: ARG001
        fetched.append(url)
        return lookup(url)

    def fetch_capped(url: str, *, config: FetchConfig, cap: int = 0) -> FetchResult:  # noqa: ARG001
        fetched.append(url)
        return lookup(url)

    def render(url: str, config: object = None) -> RenderResult:  # noqa: ARG001
        if not render_ok:
            return RenderResult(url=url, html="", rects={}, ok=False, error="browser did not start")
        path = urlsplit(url).path or "/"
        if rendered and path in rendered:
            return RenderResult(url=url, html=rendered[path], rects={}, ok=True, status=200)
        result = lookup(url)
        return RenderResult(url=url, html=result.html, rects={}, ok=result.ok, status=result.status)

    for module in (resolve, robots_module, discovery):
        monkeypatch.setattr(module, "fetch_static", fetch)
    monkeypatch.setattr(signals, "fetch_capped", fetch_capped)
    monkeypatch.setattr(resolve, "render_page", render)
    for module in (resolve, analyze, build):
        monkeypatch.setattr(module, "PLAYWRIGHT_AVAILABLE", True)
    monkeypatch.setattr(config, "REPORT_REQUEST_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(pages.LinkChecker, "status_of", lambda _self, url: lookup(url).status)
    robots_module.forget()
    return fetched


BASIC: Served = {
    "/": (200, ROOT),
    "/admissions/": (200, ADMISSIONS),
    "/admissions/fees": (200, ADMISSIONS),
    "/about": (200, ABOUT),
    "/blog/post-1": (200, BLOG),
}


class TestReadingRobotsPerBot:
    def test_a_named_group_governs_the_bot_and_the_wildcard_the_rest(self) -> None:
        from webgraph.report.bots import BOTS, policy_for_bot

        robots = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nDisallow: /private/\n"
        by = {b.token: policy_for_bot(robots, b) for b in BOTS}
        assert by["GPTBot"].access == "blocked" and by["GPTBot"].via == "named"
        assert by["GPTBot"].lines == ("Disallow: /",)
        assert by["ClaudeBot"].access == "partly" and by["ClaudeBot"].via == "wildcard"
        assert by["ClaudeBot"].disallowed == 1 and by["ClaudeBot"].content_paths == ("/private/",)
        # Every other bot follows `*`: GPTBot is the only one blocked.
        assert [t for t, b in by.items() if b.access == "blocked"] == ["GPTBot"]
        assert all(b.via == "wildcard" for t, b in by.items() if t != "GPTBot")

    def test_administrative_disallows_leave_a_bot_allowed(self) -> None:
        """`Disallow: /wp-admin/` is housekeeping on nearly every WordPress site. Measured on
        vtu.ac.in: the first version called all fifteen bots "restricted" for it."""
        from webgraph.report.bots import BOTS, is_administrative, policy_for_bot

        robots = "User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\nDisallow: /*?\nDisallow: /search/\n"
        policies = [policy_for_bot(robots, b) for b in BOTS]
        assert all(p.access == "allowed" for p in policies)
        assert all(p.disallowed == 3 and p.content_paths == () for p in policies)
        assert (
            is_administrative("/cgi-bin/")
            and is_administrative("/login")
            and is_administrative("/?s=")
        )
        assert not is_administrative("/news/") and not is_administrative("/wp-content/uploads/")

    def test_content_disallows_are_partly_restricted_with_the_paths(self) -> None:
        from webgraph.report.bots import BOTS, policy_for_bot

        robots = "User-agent: *\nDisallow: /wp-admin/\nDisallow: /news/\nDisallow: /reports/\nDisallow: /drafts/\n"
        bot = policy_for_bot(robots, BOTS[0])
        assert bot.access == "partly"
        assert bot.disallowed == 4 and bot.content_paths == ("/news/", "/reports/", "/drafts/")

    def test_matching_is_the_whole_token_not_a_substring(self) -> None:
        """`Googlebot-Image` in the file is not a rule for Googlebot, and `gptbot` is GPTBot."""
        from webgraph.report.bots import BOTS, policy_for_bot

        robots = "User-agent: Googlebot-Image\nDisallow: /\n\nUser-agent: gptbot/1.0\nDisallow: /\n"
        by = {b.token: policy_for_bot(robots, b) for b in BOTS}
        assert by["Googlebot"].via == "none" and by["Googlebot"].access == "allowed"
        assert by["GPTBot"].via == "named" and by["GPTBot"].access == "blocked"

    def test_every_group_naming_the_bot_is_combined(self) -> None:
        from webgraph.report.bots import BOTS, policy_for_bot

        robots = (
            "User-agent: ClaudeBot\nDisallow: /drafts/\n\n"
            "User-agent: ClaudeBot\nUser-agent: CCBot\nDisallow: /private/\nCrawl-delay: 5\n"
        )
        claude = policy_for_bot(robots, next(b for b in BOTS if b.token == "ClaudeBot"))
        assert claude.disallowed == 2 and claude.access == "partly"
        assert claude.crawl_delay == 5.0
        assert claude.lines == ("Disallow: /drafts/", "Disallow: /private/", "Crawl-delay: 5")

    def test_the_longest_match_decides_the_root_and_allow_wins_a_tie(self) -> None:
        from webgraph.report.bots import BOTS, policy_for_bot

        bot = next(b for b in BOTS if b.token == "PerplexityBot")
        assert (
            policy_for_bot("User-agent: PerplexityBot\nDisallow: /\nAllow: /\n", bot).access
            == "allowed"
        )
        assert policy_for_bot("User-agent: PerplexityBot\nDisallow: /$\n", bot).access == "blocked"
        assert policy_for_bot("User-agent: PerplexityBot\nDisallow: /*\n", bot).access == "blocked"
        assert policy_for_bot("User-agent: PerplexityBot\nDisallow:\n", bot).access == "allowed"
        # `?` is literal in a robots pattern, not a one-character wildcard: `/*?` must not match `/`.
        assert policy_for_bot("User-agent: PerplexityBot\nDisallow: /*?\n", bot).access == "allowed"

    def test_no_file_is_allowed_and_unmentioned_for_every_bot(self) -> None:
        from webgraph.report.bots import BOTS, declared_policies

        policies = declared_policies(None)
        assert len(policies) == len(BOTS)
        assert all(p.access == "allowed" and p.via == "none" and not p.mentioned for p in policies)

    def test_parse_groups_is_the_one_parser(self) -> None:
        """`group_for_client` reads the same groups the bots table does."""
        from webgraph.crawl.discovery import group_for_client, parse_groups

        robots = "User-agent: webgraph\nDisallow: /x\n\nUser-agent: *\nAllow: /\n"
        groups = parse_groups(robots)
        assert [g.agents for g in groups] == [("webgraph",), ("*",)]
        chosen = group_for_client(robots)
        assert chosen is not None and chosen.label == "webgraph"


class TestResolvedPageCarriesWordsAndTheStaticSide:
    """The report says "41 words without JavaScript and 1,312 with it"; the resolver used
    to count characters only, and said nothing about why the plain fetch gave nothing."""

    def test_a_union_counts_words_on_both_sides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.resolve import Strategy, resolve_page

        static = "<html><body><p>Four words in static.</p></body></html>"
        rendered = "<html><body><p>Four words in static.</p><p>And five more words rendered here.</p></body></html>"
        serve(monkeypatch, {"/": (200, static)}, rendered={"/": rendered})
        resolved = resolve_page("https://acme.test/")
        assert resolved.strategy is Strategy.UNION
        assert resolved.static_words == 4
        assert resolved.rendered_words == 10
        assert resolved.union_words == 10
        assert resolved.static_error is None

    def test_a_plain_fetch_that_failed_says_why(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.resolve import Strategy, resolve_page

        page = f"<html><body><h1>Served to the browser</h1><p>{PAGE_WORDS}</p></body></html>"
        serve(
            monkeypatch, {"/": (403, "<html><body>Forbidden</body></html>")}, rendered={"/": page}
        )
        resolved = resolve_page("https://acme.test/")
        assert resolved.strategy is Strategy.RENDERED_ONLY
        assert resolved.static_error is not None and "HTTP 403" in resolved.static_error
        assert resolved.static_words == 0 and resolved.rendered_words > 0

    def test_a_plain_fetch_served_a_wall_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.resolve import resolve_page

        wall = "<html><body><p>Sorry, you have been blocked. Ray ID: abc</p></body></html>"
        page = f"<html><body><h1>The page</h1><p>{PAGE_WORDS}</p></body></html>"
        serve(monkeypatch, {"/": (200, wall)}, rendered={"/": page})
        resolved = resolve_page("https://acme.test/")
        assert resolved.static_error is not None
        assert "served a wall" in resolved.static_error and "blocked" in resolved.static_error


class TestTheReport:
    def test_the_root_and_one_page_per_section_are_sampled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        serve(monkeypatch, BASIC)
        report = build_site_report("https://acme.test/", pages=4)
        assert report.reachable and report.score is not None
        paths = [p.requested_url.replace("https://acme.test", "") for p in report.pages]
        # One per section first: admissions, about, blog -- not /admissions/fees before /about.
        assert paths == ["/", "/admissions/", "/about", "/blog/post-1"]
        assert [p.section for p in report.pages] == ["/", "admissions", "about", "blog"]

    def test_readability_is_the_engines_numbers_per_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A shell of 3 words that renders to 30 is reported as 3 / 30 and scores below a
        page whose words are all in the HTML."""
        from webgraph.report import build_site_report

        shell = "<html><head><title>Pricing</title></head><body><div id='app'>Loading pricing plans</div></body></html>"
        full = (
            "<html><head><title>Pricing</title></head><body><div id='app'>Loading pricing plans</div>"
            "<h1>Plans</h1><p>Starter costs ten a month and includes one seat and one project for anyone starting out.</p>"
            "<p>Team costs forty a month and includes ten seats and unlimited projects.</p></body></html>"
        )
        root = ROOT.replace("<a href='/about'>About</a>", "<a href='/pricing'>Pricing</a>")
        served = {**BASIC, "/": (200, root), "/pricing": (200, shell)}
        serve(monkeypatch, served, rendered={"/pricing": full})
        report = build_site_report("https://acme.test/", pages=3)
        pricing = next(p for p in report.pages if p.section == "pricing")
        assert pricing.static_words == 3
        assert pricing.rendered_words > 25
        assert pricing.static_coverage < 0.2
        assert report.score is not None
        readable = next(s for s in report.score.subscores if s.key == "readable_without_js")
        assert readable.measured and readable.score is not None
        assert readable.score < readable.weight
        assert "/pricing" in readable.evidence and "3 words without JavaScript" in readable.evidence
        assert readable.recommendation is not None and "Server-render" in readable.recommendation
        assert readable.source == pricing.url

    def test_readability_is_unmeasured_when_nothing_rendered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No render means static equals union by construction; that is not 100%."""
        from webgraph.report import build_site_report

        serve(monkeypatch, BASIC, render_ok=False)
        report = build_site_report("https://acme.test/", pages=2)
        assert report.score is not None
        readable = next(s for s in report.score.subscores if s.key == "readable_without_js")
        assert not readable.measured and readable.score is None
        assert report.score.measured_weight == 100 - readable.weight

    def test_weights_sum_to_one_hundred_and_a_clean_site_scores_high(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report
        from webgraph.report.score import WEIGHTS

        assert sum(WEIGHTS.values()) == 100
        sitemap = (
            '<?xml version="1.0"?><urlset><url><loc>https://acme.test/</loc></url>'
            "<url><loc>https://acme.test/admissions/</loc></url><url><loc>https://acme.test/about</loc></url>"
            "<url><loc>https://acme.test/blog/post-1</loc></url></urlset>"
        )
        served = {
            **BASIC,
            "/robots.txt": (
                200,
                "User-agent: *\nAllow: /\nSitemap: https://acme.test/sitemap.xml\n",
                "text/plain",
            ),
            "/sitemap.xml": (200, sitemap, "application/xml"),
            "/llms.txt": (
                200,
                "# Acme\n\n> A college.\n\n## Pages\n- [Home](https://acme.test/)\n",
                "text/plain",
            ),
        }
        served["/"] = (200, ROOT.replace("<a href='/missing'>Gone</a>", ""))
        serve(monkeypatch, served)
        report = build_site_report("https://acme.test/", pages=4)
        assert report.score is not None
        by = {s.key: s for s in report.score.subscores}
        assert by["robots_ai_bots"].score == by["robots_ai_bots"].weight
        assert by["no_walls"].score == by["no_walls"].weight
        assert by["sitemap"].score == by["sitemap"].weight
        assert by["llms_txt"].score == by["llms_txt"].weight
        assert by["no_hidden_content"].score == by["no_hidden_content"].weight
        assert by["dead_links"].score == by["dead_links"].weight
        assert report.score.total >= 90
        assert report.llms_txt is not None and report.llms_txt.found
        assert (
            report.llms_txt.sections == 1
            and report.llms_txt.links == 1
            and report.llms_txt.title == "Acme"
        )

    def test_a_catch_all_html_answer_is_not_an_llms_txt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        served = {**BASIC, "/llms.txt": (200, "<html><body><h1>Not found</h1></body></html>")}
        serve(monkeypatch, served)
        report = build_site_report("https://acme.test/", pages=1)
        assert report.llms_txt is not None and not report.llms_txt.found

    def test_blocked_bots_lower_the_robots_score_without_a_recommendation_to_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        robots = "User-agent: GPTBot\nUser-agent: ClaudeBot\nUser-agent: CCBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
        serve(monkeypatch, {**BASIC, "/robots.txt": (200, robots, "text/plain")})
        report = build_site_report("https://acme.test/", pages=1)
        assert report.robots is not None
        blocked = [b.token for b in report.robots.bots if b.access == "blocked"]
        assert blocked == ["GPTBot", "ClaudeBot", "CCBot"]
        assert report.score is not None
        sub = next(s for s in report.score.subscores if s.key == "robots_ai_bots")
        assert sub.score == pytest.approx(sub.weight * (1 - 3 / 15))
        assert "GPTBot" in sub.evidence
        assert sub.recommendation is not None and "legitimate" in sub.recommendation

    def test_dead_links_are_counted_once_and_rate_limited_by_the_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        serve(monkeypatch, BASIC)
        report = build_site_report("https://acme.test/", pages=1)
        root = report.pages[0]
        assert root.links_checked == 5
        assert [d.url for d in root.dead_links] == ["https://acme.test/missing"]
        assert root.dead_links[0].status == 404
        assert report.score is not None
        dead = next(s for s in report.score.subscores if s.key == "dead_links")
        assert dead.score == pytest.approx(dead.weight * 0.8)
        assert "https://acme.test/missing -> 404" in dead.evidence

    def test_the_suggested_robots_txt_keeps_the_existing_file_verbatim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        existing = "# Acme's rules\nUser-agent: *\nDisallow: /private/\nCrawl-delay: 2\n"
        serve(monkeypatch, {**BASIC, "/robots.txt": (200, existing, "text/plain")})
        report = build_site_report("https://acme.test/", pages=1, today=date(2026, 9, 16))
        suggestion = report.suggested_robots_txt
        assert suggestion is not None and suggestion.startswith(existing)
        added = suggestion[len(existing) :]
        assert all(line.startswith("#") or not line.strip() for line in added.splitlines()), (
            "every added line is a comment"
        )
        assert "# User-agent: GPTBot\n# Allow: /" in added, "variant A allows"
        assert "# User-agent: GPTBot\n# Disallow: /" in added, (
            "variant B disallows training crawlers"
        )
        assert "# User-agent: OAI-SearchBot\n# Disallow: /" not in added, (
            "search bots are never disallowed"
        )
        assert "Sitemap: https://acme.test/sitemap.xml" in added

    def test_the_llms_txt_draft_follows_llmstxt_org(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.report import build_site_report

        serve(monkeypatch, BASIC)
        report = build_site_report("https://acme.test/", pages=3)
        draft = report.suggested_llms_txt
        assert draft is not None
        lines = draft.splitlines()
        assert lines[0] == "# Acme College"
        assert lines[2] == "> A college that teaches things."
        assert "## Pages" in lines and "## Admissions" in lines and "## About" in lines
        assert "- [Home](https://acme.test/): A college that teaches things." in lines
        assert "- [Admissions](https://acme.test/admissions/)" in lines
        assert "Optional" in report.llms_txt_note and "97%" in report.llms_txt_note

    def test_a_walled_root_ends_the_report_without_a_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        wall = "<html><body><p>Sorry, you have been blocked. Ray ID: abc</p></body></html>"
        serve(monkeypatch, {"/": (200, wall)})
        report = build_site_report("https://acme.test/")
        assert not report.reachable
        assert report.score is None and report.pages == ()
        assert report.refusal is not None and "block page" in report.refusal
        assert report.measured is not None and report.measured.pages_sampled == 0

    def test_a_root_disallowed_for_this_client_ends_the_report(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        fetched = serve(
            monkeypatch,
            {**BASIC, "/robots.txt": (200, "User-agent: *\nDisallow: /\n", "text/plain")},
        )
        report = build_site_report("https://acme.test/")
        assert not report.reachable and report.score is None
        assert (
            report.refusal is not None
            and "robots.txt disallows / for this client" in report.refusal
        )
        assert "https://acme.test/" not in fetched, "the root was never fetched"

    def test_a_page_that_cannot_be_read_is_a_row_not_an_abort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        wall = "<html><body><p>Sorry, you have been blocked. Ray ID: abc</p></body></html>"
        serve(monkeypatch, {**BASIC, "/about": (200, wall)})
        report = build_site_report("https://acme.test/", pages=3)
        about = next(p for p in report.pages if p.section == "about")
        assert about.error is not None and about.wall == "both"
        assert report.score is not None
        walls = next(s for s in report.score.subscores if s.key == "no_walls")
        assert walls.score is not None and walls.score < walls.weight
        assert any(f.kind == "unreadable_page" for f in report.findings)

    def test_the_footer_says_how_it_was_measured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.report import build_site_report

        serve(monkeypatch, BASIC)
        report = build_site_report("https://acme.test/", pages=2)
        assert report.measured is not None
        assert report.measured.pages_sampled == 2 and report.measured.pages_requested == 2
        assert "webgraph" in report.measured.user_agent
        assert "never impersonates" in report.measured.statement
        payload = report.as_dict()
        assert payload["measured"]["statement"] == report.measured.statement
        assert (
            isinstance(payload["pages"], list) and payload["score"]["total"] == report.score.total
        )  # type: ignore[union-attr]


OFFSCREEN_LINKS = "".join(f"<a href='https://spam{i}.example/slot'>slot {i}</a> " for i in range(8))
INJECTED_STATIC = (
    "<html><head><title>Acme</title></head><body><h1>Acme</h1>"
    f"<p>{PAGE_WORDS}</p>"
    f"<div style='position:absolute; left:-20914565266523px'>{OFFSCREEN_LINKS}</div>"
    "<a href='/about'>About</a></body></html>"
)
INJECTED_RENDERED = (
    "<html><head><title>Acme</title></head><body><h1>Acme</h1>"
    f"<p>{PAGE_WORDS}</p>"
    f"<div data-wg-hidden='offscreen' style='position:absolute; left:-20914565266523px'>{OFFSCREEN_LINKS}</div>"
    "<a href='/about'>About</a></body></html>"
)


class TestInjectedLinks:
    def test_offscreen_links_to_many_hosts_are_a_likely_injection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        serve(
            monkeypatch,
            {"/": (200, INJECTED_STATIC), "/about": (200, ABOUT)},
            rendered={"/": INJECTED_RENDERED},
        )
        report = build_site_report("https://acme.test/", pages=1)
        root = report.pages[0]
        assert root.hidden_links == 8 and root.offscreen_links == 8
        assert root.hidden_external_hosts == 8 and root.offscreen_external_hosts == 8
        assert root.hidden_words["offscreen"] == 16
        assert {h.host for h in root.hidden_hosts} == {f"spam{i}.example" for i in range(8)}
        finding = next(f for f in report.findings if f.kind == "injected_links")
        assert finding.severity == "high" and "Likely SEO-spam injection" in finding.title
        assert "spam0.example (1)" in finding.detail
        assert report.score is not None
        hidden = next(s for s in report.score.subscores if s.key == "no_hidden_content")
        assert hidden.score == 0

    def test_the_static_style_is_read_when_the_browser_never_measured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A plain fetch has no marks; `left: -2e13px` in the markup is the same evidence."""
        from webgraph.report import build_site_report

        serve(monkeypatch, {"/": (200, INJECTED_STATIC)}, render_ok=False)
        report = build_site_report("https://acme.test/", pages=1)
        assert report.pages[0].offscreen_external_hosts == 8
        assert any(f.kind == "injected_links" for f in report.findings)

    def test_below_the_host_threshold_it_is_reported_not_judged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        few = "".join(f"<a href='https://partner{i}.example/'>p{i}</a> " for i in range(2))
        page = INJECTED_STATIC.replace(OFFSCREEN_LINKS, few)
        serve(monkeypatch, {"/": (200, page)}, render_ok=False)
        report = build_site_report("https://acme.test/", pages=1)
        assert report.pages[0].offscreen_external_hosts == 2
        kinds = {f.kind for f in report.findings}
        assert "injected_links" not in kinds and "hidden_external_links" in kinds
        assert report.score is not None
        hidden = next(s for s in report.score.subscores if s.key == "no_hidden_content")
        assert hidden.score == 5

    def test_a_hidden_menu_to_the_sites_own_hosts_is_not_external(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """vtu.ac.in's menus link to report.vtu.ac.in, iqac.vtu.ac.in: the site's own."""
        from webgraph.report import build_site_report

        own = "".join(f"<a href='https://svc{i}.acme.ac.in/'>s{i}</a> " for i in range(8))
        page = INJECTED_STATIC.replace(OFFSCREEN_LINKS, own)
        serve(monkeypatch, {"/": (200, page)}, render_ok=False)
        report = build_site_report("https://www.acme.ac.in/", pages=1)
        assert report.pages[0].hidden_links == 8
        assert report.pages[0].hidden_external_hosts == 0
        assert not any(
            f.kind in ("injected_links", "hidden_external_links") for f in report.findings
        )

    def test_a_dropdown_menu_of_foreign_hosts_is_not_a_verdict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """vtu.ac.in's `display: none` menus link to 187 affiliated colleges. A dropdown is
        hidden the way every dropdown is; the injection is what is parked off the page."""
        from webgraph.report import build_site_report

        menu = "".join(f"<a href='https://college{i}.example/'>c{i}</a> " for i in range(20))
        rendered = INJECTED_RENDERED.replace(
            f"<div data-wg-hidden='offscreen' style='position:absolute; left:-20914565266523px'>{OFFSCREEN_LINKS}</div>",
            f"<ul data-wg-hidden='display'>{menu}</ul>",
        )
        static = INJECTED_STATIC.replace(
            f"<div style='position:absolute; left:-20914565266523px'>{OFFSCREEN_LINKS}</div>",
            f"<ul>{menu}</ul>",
        )
        serve(monkeypatch, {"/": (200, static)}, rendered={"/": rendered})
        report = build_site_report("https://acme.test/", pages=1)
        root = report.pages[0]
        assert root.hidden_links == 20 and root.hidden_external_hosts == 20
        assert root.offscreen_links == 0 and root.offscreen_external_hosts == 0
        assert not any(
            f.kind in ("injected_links", "hidden_external_links") for f in report.findings
        )
        assert report.score is not None
        hidden = next(s for s in report.score.subscores if s.key == "no_hidden_content")
        assert hidden.score == hidden.weight
        assert "dropdown" in hidden.evidence

    def test_one_injection_across_pages_is_one_finding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from webgraph.report import build_site_report

        about = INJECTED_STATIC.replace("<title>Acme</title>", "<title>About</title>")
        serve(
            monkeypatch,
            {"/": (200, INJECTED_STATIC), "/about": (200, about)},
            rendered={"/": INJECTED_RENDERED, "/about": INJECTED_RENDERED},
        )
        report = build_site_report("https://acme.test/", pages=2)
        injected = [f for f in report.findings if f.kind == "injected_links"]
        assert len(injected) == 1
        assert "2 of 2 sampled pages" in injected[0].detail
        assert "spam0.example (2)" in injected[0].detail


class TestStackAge:
    def test_a_known_branch_is_dated_and_flagged_when_old(self) -> None:
        from webgraph.report.score import integrity_findings
        from webgraph.report.stack import stack_entries

        techs = (
            {"name": "WordPress", "category": "CMS", "version": "5.1.1"},
            {"name": "Next.js", "category": "JavaScript frameworks", "version": "16.1.2"},
            {"name": "jQuery", "category": "JavaScript libraries", "version": "1.12.4"},
        )
        entries = stack_entries(techs, today=date(2026, 9, 16))
        wordpress, nextjs, jquery = entries
        assert wordpress.released == date(2019, 2, 21) and wordpress.age_years == 7.6
        assert nextjs.released == date(2025, 10, 22) and nextjs.age_years == 0.9
        assert jquery.released is None and jquery.age_years is None, (
            "not in the table: version only"
        )
        findings = integrity_findings([], entries)
        assert [f.kind for f in findings] == ["outdated_stack"]
        assert "WordPress 5.1.1 is 7.6 years old" in findings[0].title
        assert "2019-02-21" in findings[0].detail


class TestCli:
    def test_the_summary_prints_the_score_the_bots_and_the_files(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from webgraph.cli import main

        serve(
            monkeypatch,
            {**BASIC, "/robots.txt": (200, "User-agent: GPTBot\nDisallow: /\n", "text/plain")},
        )
        assert main(["report", "https://acme.test/", "--pages", "2"]) == 0
        out = capsys.readouterr().out
        assert "AI-READINESS" in out and "/100" in out
        assert "GPTBot               blocked            named" in out
        assert "ClaudeBot            allowed            not mentioned" in out
        assert "SUGGESTED robots.txt" in out and "# User-agent: GPTBot\n# Allow: /" in out
        assert "SUGGESTED llms.txt" in out and "# Acme College" in out
        assert "never impersonates" in out

    def test_json_is_the_whole_report(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import json

        from webgraph.cli import main

        serve(monkeypatch, BASIC)
        assert main(["report", "https://acme.test/", "--pages", "1", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["reachable"] is True and payload["score"]["total"] > 0
        assert len(payload["pages"]) == 1 and len(payload["robots"]["bots"]) == 15

    def test_a_refusal_exits_non_zero_and_says_why(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from webgraph.cli import main

        serve(
            monkeypatch,
            {**BASIC, "/robots.txt": (200, "User-agent: *\nDisallow: /\n", "text/plain")},
        )
        assert main(["report", "https://acme.test/"]) == 1
        out = capsys.readouterr().out
        assert "NO REPORT" in out and "robots.txt disallows" in out
