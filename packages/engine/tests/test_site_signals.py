"""What a site declares to machines (`webgraph.report.signals`): the parsers for each
signal, a fixture site that publishes all of them, a bare site that publishes none, the
soft-404 hazard, and the suggested files. Network-free through `test_site_report.serve`.
"""

from __future__ import annotations

from datetime import date

import pytest

from test_site_report import BASIC, PAGE_WORDS, ROOT, Served, _result, serve
from webgraph.report import SiteReport
from webgraph.report.signals import Signal

# ---------------------------------------------------------------------------------------
# A site that publishes everything
# ---------------------------------------------------------------------------------------

ROBOTS_ALL = (
    "User-agent: *\n"
    "Content-Signal: search=yes, ai-input=yes, ai-train=no\n"
    "Content-Usage: train-ai=n\n"
    "Allow: /\n"
    "License: https://acme.test/rsl.xml\n"
    "Sitemap: https://acme.test/sitemap.xml\n"
)

ROOT_ALL = (
    "<html lang='en'><head><title>Acme College | Home</title>"
    "<meta name='description' content='A college that teaches things.'>"
    "<meta name='robots' content='index, max-snippet:160, max-image-preview:large, noai, noimageai'>"
    "<meta name='tdm-reservation' content='1'><meta name='tdm-policy' content='https://acme.test/tdm.json'>"
    "<meta property='og:title' content='Acme'><meta property='og:image' content='https://acme.test/i.png'>"
    "<meta name='twitter:card' content='summary'>"
    "<link rel='canonical' href='https://acme.test/'>"
    "<link rel='alternate' hreflang='en' href='https://acme.test/'>"
    "<link rel='alternate' hreflang='fr' href='https://acme.test/fr/'>"
    "<link rel='alternate' type='application/rss+xml' href='/feed.xml'>"
    "<link rel='alternate' type='application/feed+json' href='/feed.json'>"
    "<link rel='alternate' type='text/markdown' href='/index.md'>"
    "<link rel='describedby' href='/llms.txt'>"
    "<link rel='license' type='application/rsl+xml' href='/rsl.xml'>"
    "<link rel='manifest' href='/site.webmanifest'>"
    '<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"Acme"},'
    '{"@type":"WebSite","potentialAction":{"@type":"SearchAction"}}]}</script>'
    '<script type="speculationrules">{"prerender":[{"where":{"href_matches":"/*"}}]}</script>'
    "</head><body><h1>Acme College</h1>"
    f"<p>{PAGE_WORDS}</p>"
    "<nav><a href='/admissions/'>Admissions</a> <a href='/about'>About</a></nav>"
    "</body></html>"
)

LLMS = (
    "# Acme College\n\n> A college.\n\n## Pages\n- [Home](https://acme.test/): the root\n"
    "- [Admissions](https://acme.test/admissions/): how to apply\n- [Gone](https://acme.test/missing): removed\n"
    "\n## Docs\n- [About](/about)\n"
)
AGENT_CARD = (
    '{"name":"Acme Agent","description":"Answers about Acme","url":"https://acme.test/a2a",'
    '"protocolVersion":"1.0","capabilities":{"streaming":false},"skills":[{"id":"apply","name":"Apply"},{"id":"fees","name":"Fees"}]}'
)
AGENTS_JSON = '{"$schema":"https://agentprotocol.ai/schemas/agents.json","siteInfo":{"name":"Acme"},"capabilities":[{"name":"GetLLMContext"}]}'
MCP_JSON = '{"mcpServers":{"acme":{"name":"Acme MCP","transport":{"type":"http","url":"https://acme.test/mcp"}}}}'
TDMREP = '[{"location":"/","tdm-reservation":1,"tdm-policy":"https://acme.test/tdm.json"},{"location":"/open/","tdm-reservation":0}]'
RSL = '<?xml version="1.0"?><rsl xmlns="https://rslstandard.org/rsl"><content url="/"><license><permits type="usage">search</permits></license></content></rsl>'
SECURITY = "Contact: mailto:security@acme.test\nExpires: 2027-01-01T00:00:00.000Z\nPolicy: https://acme.test/security\n"
MANIFEST = '{"name":"Acme College","short_name":"Acme","display":"standalone","icons":[{"src":"/i.png","sizes":"192x192"}]}'
SITEMAP = '<?xml version="1.0"?><urlset><url><loc>https://acme.test/</loc></url><url><loc>https://acme.test/about</loc></url></urlset>'

ROOT_HEADERS = {
    "x-robots-tag": "noarchive",
    "link": '</rsl.xml>; rel="license"; type="application/rsl+xml", </.well-known/api-catalog>; rel="api-catalog", '
    '</.well-known/webmcp.json>; rel="service-desc"',
    "tdm-reservation": "1",
    "content-usage": "train-ai=n",
}

EVERYTHING: Served = {
    **BASIC,
    "/": (200, ROOT_ALL, "text/html", ROOT_HEADERS),
    "/robots.txt": (200, ROBOTS_ALL, "text/plain"),
    "/sitemap.xml": (200, SITEMAP, "application/xml"),
    "/llms.txt": (200, LLMS, "text/plain"),
    "/llms-full.txt": (200, "# Acme College\n\nEverything.\n", "text/plain"),
    "/ai.txt": (200, "User-Agent: *\nDisallow: *.jpg\n", "text/plain"),
    "/rsl.xml": (200, RSL, "application/rsl+xml"),
    "/.well-known/tdmrep.json": (200, TDMREP, "application/json"),
    "/.well-known/security.txt": (200, SECURITY, "text/plain"),
    "/.well-known/agent-card.json": (200, AGENT_CARD, "application/json"),
    "/.well-known/agents.json": (200, AGENTS_JSON, "application/json"),
    "/.well-known/mcp.json": (200, MCP_JSON, "application/json"),
    "/humans.txt": (200, "Built by people.\n", "text/plain"),
    "/site.webmanifest": (200, MANIFEST, "application/manifest+json"),
}


def _by_key(report: SiteReport) -> dict[str, Signal]:
    assert report.signals is not None
    return {s.key: s for s in report.signals.signals}


# ---------------------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------------------


class TestContentSignalLines:
    def test_the_line_is_read_with_its_group_and_values(self) -> None:
        from webgraph.report.signals import parse_content_signals

        found = parse_content_signals(
            "User-Agent: *\nContent-Signal: search=yes, ai-input=yes, ai-train=no\n\nAllow: /api/og/*\nDisallow: /api/\n"
        )
        assert len(found) == 1
        assert found[0].agents == ("*",)
        assert found[0].values == {"search": "yes", "ai-input": "yes", "ai-train": "no"}
        assert found[0].line == "Content-Signal: search=yes, ai-input=yes, ai-train=no"

    def test_a_line_in_a_named_group_is_that_groups(self) -> None:
        # www.cloudflare.com, 16 Sep 2026: the line follows the Cohere-ai group.
        from webgraph.report.signals import parse_content_signals

        found = parse_content_signals(
            "User-agent: *\nAllow: /\n\nUser-agent: Cohere-ai\nAllow: /\n\n# Content Signals\nContent-Signal: ai-train=yes, search=yes, ai-input=yes\n"
        )
        assert [c.agents for c in found] == [("cohere-ai",)]
        assert found[0].values == {"ai-train": "yes", "search": "yes", "ai-input": "yes"}

    def test_a_line_outside_any_group_is_still_a_declaration(self) -> None:
        from webgraph.report.signals import parse_content_signals

        found = parse_content_signals("Content-Signal: ai-train=no\nSitemap: https://x.test/s.xml\n")
        assert found and found[0].agents == () and found[0].values == {"ai-train": "no"}

    def test_the_meaning_is_the_owners_sentence(self) -> None:
        from webgraph.report.signals import content_signal_meaning

        said = content_signal_meaning({"search": "yes", "ai-input": "yes", "ai-train": "no"})
        assert said.startswith("Your robots.txt tells AI systems they may index it for search and link back and use it as input to AI answers")
        assert "but should not train AI models on it" in said
        assert "not enforced" in said
        partial = content_signal_meaning({"ai-train": "no"})
        assert "says nothing about search and ai-input" in partial

    def test_parse_groups_keeps_the_line_and_a_group_of_only_declarations(self) -> None:
        from webgraph.crawl.discovery import parse_groups

        groups = parse_groups("User-agent: *\nContent-Signal: search=yes\nContent-Usage: train-ai=n\n")
        assert len(groups) == 1
        assert groups[0].lines == ("Content-Signal: search=yes", "Content-Usage: train-ai=n")
        assert groups[0].rules == ()


class TestLicenseAndUsageLines:
    def test_license_lines_are_absolute(self) -> None:
        from webgraph.report.signals import parse_license_lines

        assert parse_license_lines("User-agent: *\nLicense: /rsl.xml\nlicense: https://cdn.test/terms.xml\n", "https://acme.test") == (
            "https://acme.test/rsl.xml",
            "https://cdn.test/terms.xml",
        )

    def test_content_usage_from_header_and_robots(self) -> None:
        from webgraph.report.signals import parse_content_usage

        found = parse_content_usage("Content-Usage: /ai-ok/ train-ai=y\n", {"content-usage": "train-ai=n"})
        assert found == ("header: train-ai=n", "robots.txt: /ai-ok/ train-ai=y")
        assert parse_content_usage("User-agent: *\nAllow: /\n", {}) == ()


class TestLinkHeader:
    def test_vercels_header_parses_into_rels(self) -> None:
        from webgraph.report.signals import parse_link_header

        header = (
            '</.well-known/api-catalog>; rel="api-catalog", </.well-known/ai-catalog.json>; rel="ai-catalog"; '
            'type="application/ai-catalog+json", </.well-known/agent-skills/index.json>; rel="agent-skills"; type="application/json"'
        )
        parsed = parse_link_header(header, "https://vercel.com/")
        assert [u for u, _ in parsed] == [
            "https://vercel.com/.well-known/api-catalog",
            "https://vercel.com/.well-known/ai-catalog.json",
            "https://vercel.com/.well-known/agent-skills/index.json",
        ]
        assert parsed[1][1] == {"rel": "ai-catalog", "type": "application/ai-catalog+json"}


class TestRepeatedHeaders:
    def test_two_link_headers_both_survive(self) -> None:
        # www.cloudflare.com, 16 Sep 2026: fonts and preconnects in one Link header, the
        # agents.json / webmcp.json one in a second; the CDN and the origin each add X-Robots-Tag.
        from webgraph.report.signals import joined_headers, parse_link_header, robots_tokens

        got = joined_headers([
            ("Link", '</fonts/a.woff2>; as=font; rel=preload'),
            ("Link", '<https://www.cloudflare.com/.well-known/agents.json>; rel="api-catalog"'),
            ("X-Robots-Tag", "noarchive"),
            ("X-Robots-Tag", "googlebot: nosnippet"),
            ("Content-Type", "text/html"),
        ])
        rels = {params.get("rel") for _, params in parse_link_header(got["link"], "https://www.cloudflare.com/")}
        assert rels == {"preload", "api-catalog"}
        assert robots_tokens([got["x-robots-tag"]]) == ("noarchive", "nosnippet")
        assert got["content-type"] == "text/html"


class TestRobotsTokens:
    def test_meta_and_x_robots_tag_values_become_tokens(self) -> None:
        from webgraph.report.signals import robots_tokens

        tokens = robots_tokens(["index, max-image-preview:large", "googlebot: noindex, nofollow", "NOAI,noimageai"])
        assert tokens == ("index", "max-image-preview:large", "noindex", "nofollow", "noai", "noimageai")

    def test_unavailable_after_keeps_its_date(self) -> None:
        from webgraph.report.signals import robots_tokens

        assert robots_tokens(["unavailable_after: 25 Jun 2027 15:00:00 PST"]) == ("unavailable_after: 25 jun 2027 15:00:00 pst",)


class TestLlmsFile:
    def test_a_file_is_read_for_title_sections_and_links(self) -> None:
        from webgraph.report.signals import llms_links, read_llms_file

        parsed = read_llms_file(_result("https://acme.test/llms.txt", 200, LLMS, "text/plain"), "/llms.txt")
        assert parsed.found and parsed.title == "Acme College" and parsed.sections == 2 and parsed.links == 4
        assert llms_links(LLMS, "https://acme.test/llms.txt")[-1] == "https://acme.test/about"

    def test_an_html_shell_with_status_200_is_not_one(self) -> None:
        from webgraph.report.signals import read_llms_file

        shell = _result("https://acme.test/llms.txt", 200, "<!DOCTYPE html><html><head><title>Acme</title></head><body># not really</body></html>", "text/plain")
        assert not read_llms_file(shell, "/llms.txt").found

    def test_content_length_is_the_size_when_the_body_was_capped(self) -> None:
        from webgraph.report.signals import read_llms_file

        capped = _result("https://acme.test/llms-full.txt", 200, "# Acme\n\ntruncated", "text/plain", {"content-length": "166160"})
        assert read_llms_file(capped, "/llms-full.txt").bytes == 166160


# ---------------------------------------------------------------------------------------
# The fixture site
# ---------------------------------------------------------------------------------------


class TestEverythingSite:
    def test_every_signal_is_detected_with_its_detail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.report import build_site_report
        from webgraph.report.signals import GROUPS

        serve(monkeypatch, EVERYTHING)
        report = build_site_report("https://acme.test/", pages=1, today=date(2026, 9, 16))
        assert report.signals is not None
        by = _by_key(report)
        measurable = [s for s in report.signals.signals if s.key != "indexnow"]
        assert all(s.present for s in measurable), [s.key for s in measurable if not s.present]
        assert by["indexnow"].present is None

        assert "search=yes, ai-input=yes, ai-train=no (under User-agent: *)" in by["content_signal"].detail
        assert "may index it for search" in by["content_signal"].meaning and "should not train" in by["content_signal"].meaning
        assert by["content_usage"].detail == "header: train-ai=n; robots.txt: train-ai=n"
        assert by["llms_txt"].detail.startswith("2 sections, 4 links")
        assert "3 of 4 sampled links answer" in by["llms_txt"].detail
        assert "llms-full.txt present" in by["llms_txt"].detail
        assert by["ai_txt"].detail == "robots-shaped ai.txt present"
        rsl = by["rsl"].detail
        assert "robots.txt License: https://acme.test/rsl.xml" in rsl and "Link header" in rsl and "<link rel=license>" in rsl
        tdm = by["tdm"].detail
        assert "header tdm-reservation: 1" in tdm and "<meta tdm-reservation> 1" in tdm and "2 rules, 1 reserving" in tdm
        assert "reserves its text-and-data-mining rights" in by["tdm"].meaning
        assert by["noai"].detail == "noai, noimageai"
        assert by["robots_meta"].detail == "max-snippet:160, max-image-preview:large, noarchive (from meta and X-Robots-Tag)"
        assert "is indexable and bounds what they may quote" in by["robots_meta"].meaning

        assert by["sitemap"].detail.startswith("found, 2 URLs read, declared in robots.txt (1)")
        assert by["feeds"].detail.startswith("2 feed links (RSS, JSON Feed)")
        assert "type=text/markdown> -> https://acme.test/index.md" in by["markdown_alternate"].detail
        assert "rel=describedby -> https://acme.test/llms.txt" in by["markdown_alternate"].detail

        assert by["agent_card"].detail == "'Acme Agent', 2 skills (protocol 1.0) at /.well-known/agent-card.json"
        assert by["agents_json"].detail.startswith("'Acme', 1 capability")
        assert by["mcp"].detail.startswith("/.well-known/mcp.json: 1 server (Acme MCP)")
        assert "webmcp.json" in by["mcp"].detail
        assert by["api_catalog"].detail == "rel=api-catalog -> https://acme.test/.well-known/api-catalog"

        assert by["json_ld"].detail == "Organization, WebSite, SearchAction"
        assert by["open_graph"].detail == "2 og:* tags, 1 twitter:* tag"
        assert by["hreflang"].detail == "2 hreflang links"
        assert by["canonical"].detail == "https://acme.test/"

        assert by["security_txt"].detail == "Contact: mailto:security@acme.test; Expires: 2027-01-01T00:00:00.000Z; Policy"
        assert by["manifest"].detail == "'Acme College', display standalone, 1 icons"
        assert by["speculation_rules"].present

        groups = report.signals.by_group()
        assert list(groups) == list(GROUPS)
        assert {s.key for s in groups["ai"]} == {"content_signal", "content_usage", "llms_txt", "ai_txt", "rsl", "tdm", "noai", "robots_meta"}
        assert {s.key for s in groups["agents"]} == {"agent_card", "agents_json", "mcp", "api_catalog"}
        for s in report.signals.signals:
            assert s.spec_url.startswith("https://") and s.who_honours and s.meaning
        # The llms.txt facts flow to the report's own fields as before.
        assert report.llms_txt is not None and report.llms_txt.found and report.llms_txt.links_answering == 3
        assert report.suggested_security_txt is None  # the site has one

    def test_the_pre_0_3_agent_json_path_is_read_and_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # www.cloudflare.com serves its A2A card at /.well-known/agent.json and 404s agent-card.json.
        from webgraph.report import build_site_report

        served = dict(EVERYTHING)
        served["/.well-known/agent.json"] = served.pop("/.well-known/agent-card.json")
        serve(monkeypatch, served)
        report = build_site_report("https://acme.test/", pages=1)
        card = _by_key(report)["agent_card"]
        assert card.present and "at /.well-known/agent.json -- the pre-0.3 path" in card.detail

    def test_the_serialised_report_carries_the_groups(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.report import build_site_report

        serve(monkeypatch, EVERYTHING)
        data = build_site_report("https://acme.test/", pages=1).as_dict()
        assert [g["key"] for g in data["signals"]["groups"]] == ["ai", "discovery", "agents", "metadata", "trust"]
        first = data["signals"]["signals"][0]
        assert set(first) >= {"key", "label", "group", "group_label", "present", "detail", "meaning", "who_honours", "spec_url", "source_url"}
        assert data["signals"]["root_headers"]["tdm-reservation"] == "1"
        assert data["pages"][0]["has_open_graph"] is True
        assert data["signals"]["requests"] >= 12


class TestBareSite:
    def test_a_site_with_nothing_declares_nothing_and_is_told_so_plainly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.report import build_site_report

        serve(monkeypatch, BASIC)
        report = build_site_report("https://acme.test/", pages=1, today=date(2026, 9, 16))
        by = _by_key(report)
        for key in ("content_signal", "llms_txt", "ai_txt", "rsl", "tdm", "noai", "feeds", "agent_card", "agents_json", "mcp", "security_txt", "manifest"):
            assert by[key].present is False, key
        # ROOT has JSON-LD and a canonical but no OpenGraph.
        assert by["json_ld"].present and by["json_ld"].detail == "Organization"
        assert by["open_graph"].present is False and "shows bare in Slack" in by["open_graph"].meaning
        assert "silence grants and restricts nothing" in by["content_signal"].meaning
        assert report.suggested_security_txt is not None
        assert "Contact: mailto:<security@your-domain>" in report.suggested_security_txt
        assert "Expires: 2027-09-16T00:00:00.000Z" in report.suggested_security_txt
        assert "Canonical: https://acme.test/.well-known/security.txt" in report.suggested_security_txt

    def test_a_catch_all_site_answering_html_everywhere_has_none_of_the_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # vercel.com, 16 Sep 2026: /ai.txt, /rsl.xml, /humans.txt, /manifest.json -> 200 + the HTML shell.
        from webgraph.report import build_site_report

        shell = "<!DOCTYPE html><html><head><title>Acme</title></head><body>Not found, but 200.</body></html>"
        served: Served = {**BASIC}
        for path in ("/llms.txt", "/ai.txt", "/rsl.xml", "/.well-known/tdmrep.json", "/.well-known/security.txt",
                     "/security.txt", "/.well-known/agent-card.json", "/.well-known/agent.json", "/.well-known/agents.json",
                     "/.well-known/mcp.json", "/humans.txt"):
            served[path] = (200, shell, "text/html")
        serve(monkeypatch, served)
        by = _by_key(build_site_report("https://acme.test/", pages=1))
        for key in ("llms_txt", "ai_txt", "rsl", "tdm", "security_txt", "agent_card", "agents_json", "mcp", "humans_txt"):
            assert by[key].present is False, key
        assert "the answer was an HTML page, not the format" in by["llms_txt"].detail

    def test_a_probe_robots_disallows_is_unchecked_not_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.report import build_site_report

        served: Served = {**BASIC, "/robots.txt": (200, "User-agent: *\nDisallow: /.well-known/\nDisallow: /ai.txt\n", "text/plain")}
        serve(monkeypatch, served)
        report = build_site_report("https://acme.test/", pages=1)
        by = _by_key(report)
        assert by["ai_txt"].present is None and by["tdm"].present is False
        assert by["agent_card"].present is False and by["agent_card"].status is None
        assert any("robots.txt disallows the path" in n for n in report.notes)


class TestScoreFold:
    def test_open_graph_is_the_fourth_page_field_and_weights_still_sum_to_100(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.report import build_site_report
        from webgraph.report.score import WEIGHTS

        assert sum(WEIGHTS.values()) == 100 and WEIGHTS["structured_data"] == 10
        serve(monkeypatch, BASIC)
        without = build_site_report("https://acme.test/", pages=1)
        served = {**BASIC, "/": (200, ROOT.replace("<link rel='canonical'", "<meta property='og:title' content='Acme'><link rel='canonical'"))}
        serve(monkeypatch, served)
        with_og = build_site_report("https://acme.test/", pages=1)
        assert without.score is not None and with_og.score is not None
        before = {s.key: s for s in without.score.subscores}["structured_data"]
        after = {s.key: s for s in with_og.score.subscores}["structured_data"]
        assert before.score == pytest.approx(6 + 4 * 3 / 4) and "lacks og" in before.evidence
        assert after.score == pytest.approx(10.0) and after.recommendation is None


class TestSuggestedFiles:
    def test_the_robots_block_offers_both_content_signal_variants_as_comments(self) -> None:
        from webgraph.report.suggest import suggest_robots_txt

        text = suggest_robots_txt(
            "User-agent: *\nAllow: /\n", origin="https://acme.test", sitemap_found=True,
            sitemaps_declared=["https://acme.test/sitemap.xml"], has_feed=False, today=date(2026, 9, 16),
        )
        assert "# Content-Signal: search=yes, ai-input=yes, ai-train=no" in text
        assert "# Content-Signal: search=yes, ai-input=yes, ai-train=yes" in text
        assert "A declaration, not enforcement" in text
        assert "No RSS/Atom/JSON feed is advertised" in text
        assert all(line.startswith("#") or not line.strip() for line in text.splitlines()[2:])

    def test_an_existing_content_signal_is_shown_back_not_proposed(self) -> None:
        from webgraph.report.signals import parse_content_signals
        from webgraph.report.suggest import suggest_robots_txt

        robots = "User-agent: *\nContent-Signal: search=yes, ai-input=yes, ai-train=no\nAllow: /\n"
        text = suggest_robots_txt(
            robots, origin="https://acme.test", sitemap_found=True, sitemaps_declared=["x"],
            content_signals=parse_content_signals(robots), has_feed=True,
        )
        assert text.startswith(robots)
        assert "# The file already declares: search=yes, ai-input=yes, ai-train=no  (under User-agent: *)" in text
        assert "# Variant 1" not in text and "feed" not in text.lower().split("content-signal", 1)[1].split("sitemap")[0]

    def test_the_security_txt_template_has_the_required_fields(self) -> None:
        from webgraph.report.suggest import suggest_security_txt

        text = suggest_security_txt(origin="https://acme.test/", today=date(2028, 2, 29))
        assert text.splitlines()[2] == "Contact: mailto:<security@your-domain>"
        assert "Expires: 2029-02-28T00:00:00.000Z" in text
        assert "Canonical: https://acme.test/.well-known/security.txt" in text


class TestCliAndFormatting:
    def test_the_summary_prints_the_signals_by_group(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        from webgraph.cli import main

        serve(monkeypatch, EVERYTHING)
        assert main(["report", "https://acme.test/", "--pages", "1"]) == 0
        out = capsys.readouterr().out
        assert "SIGNALS" in out and "Declarations to AI" in out and "Agents" in out
        assert "Content-Signal (robots.txt)" in out and "search=yes, ai-input=yes, ai-train=no" in out
        assert "A2A agent card" in out and "'Acme Agent', 2 skills" in out
        assert "SUGGESTED security.txt" not in out  # the site has one

    def test_the_summary_prints_the_security_txt_template_when_missing(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        from webgraph.cli import main

        serve(monkeypatch, BASIC)
        main(["report", "https://acme.test/", "--pages", "1"])
        out = capsys.readouterr().out
        assert "SUGGESTED security.txt" in out and "Contact: mailto:<security@your-domain>" in out
