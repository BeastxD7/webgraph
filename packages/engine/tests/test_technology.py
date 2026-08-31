"""Technology fingerprinting tests.

Rules are hand-written because every maintained Wappalyzer ruleset is GPL-3.0 and would
force this Apache-2.0 engine to GPL. These tests pin the signal sources that an earlier
HTML-only profiler missed entirely.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from webgraph.profile.technology import detect_technologies


def names(techs) -> set[str]:
    return {t.name for t in techs}


class TestHeaderSignals:
    """Server-side technology exists ONLY in headers. An HTML-only profiler reported
    'none detected' for a site running Apache, PHP and OpenSSL."""

    HEADERS: ClassVar[dict[str, str]] = {
        "server": "Apache/2.4.37 (Rocky Linux) OpenSSL/1.1.1k",
        "x-powered-by": "PHP/7.4.33",
    }

    def test_detects_server_language_and_extension(self) -> None:
        found = detect_technologies("<html></html>", self.HEADERS)
        assert {"Apache HTTP Server", "PHP", "OpenSSL"} <= names(found)

    @pytest.mark.parametrize(
        ("name", "version"),
        [("Apache HTTP Server", "2.4.37"), ("PHP", "7.4.33"), ("OpenSSL", "1.1.1k")],
    )
    def test_versions_extracted(self, name: str, version: str) -> None:
        found = {t.name: t for t in detect_technologies("<html></html>", self.HEADERS)}
        assert found[name].version == version

    def test_categories_assigned(self) -> None:
        found = {t.name: t for t in detect_technologies("<html></html>", self.HEADERS)}
        assert found["Apache HTTP Server"].category == "Web servers"
        assert found["PHP"].category == "Programming languages"
        assert found["OpenSSL"].category == "Web server extensions"

    def test_header_name_case_insensitive(self) -> None:
        found = detect_technologies("<html></html>", {"SERVER": "nginx/1.25.3"})
        assert "nginx" in names(found)

    def test_no_headers_is_safe(self) -> None:
        assert detect_technologies("<html></html>", None) == []


class TestMarkupSignals:
    @pytest.mark.parametrize(
        ("markup", "expected"),
        [
            ('<script src="/js/jquery.min.js">', "jQuery"),
            ('<link href="/css/bootstrap.min.css">', "Bootstrap"),
            ('<script src="https://static.hotjar.com/c/hotjar.js">', "Hotjar"),
            ('<script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC">', "Google Tag Manager"),
            ('<link href="https://fonts.googleapis.com/css?family=Inter">', "Google Font API"),
            ('<script src="https://www.googletagmanager.com/gtag/js?id=UA-123">', "Google Analytics"),
            ('<script src="/js/tailwind.min.css">', "Tailwind CSS"),
            ('<div id="__NEXT_DATA__">', "Next.js"),
        ],
    )
    def test_library_and_service_detection(self, markup: str, expected: str) -> None:
        assert expected in names(detect_technologies(markup))

    def test_version_from_filename(self) -> None:
        found = {t.name: t for t in detect_technologies('<script src="/jquery-3.6.0.min.js">')}
        assert found["jQuery"].version == "3.6.0"

    def test_angular_version_from_attribute(self) -> None:
        found = {t.name: t for t in detect_technologies('<app ng-version="17.1.2">')}
        assert found["Angular"].version == "17.1.2"


class TestRuntimeGlobals:
    """`jquery.min.js` carries no version; `jQuery.fn.jquery` reports it exactly."""

    def test_runtime_version_wins_over_bare_markup_match(self) -> None:
        found = {
            t.name: t
            for t in detect_technologies(
                '<script src="/js/jquery.min.js">', None, {"jQuery": "3.6.0"}
            )
        }
        assert found["jQuery"].version == "3.6.0"
        assert found["jQuery"].evidence == "runtime global"

    def test_runtime_global_alone_is_enough(self) -> None:
        found = detect_technologies("<html></html>", None, {"Bootstrap": "5.3.2"})
        assert "Bootstrap" in names(found)

    def test_runtime_global_keeps_known_category(self) -> None:
        found = {t.name: t for t in detect_technologies("", None, {"Bootstrap": "5.3.2"})}
        assert found["Bootstrap"].category == "UI frameworks"


class TestOrderingAndDedup:
    def test_grouped_by_category_order(self) -> None:
        found = detect_technologies(
            '<script src="/jquery.min.js"><link href="/bootstrap.min.css">',
            {"server": "Apache/2.4.37"},
        )
        categories = [t.category for t in found]
        assert categories.index("JavaScript libraries") < categories.index("Web servers")

    def test_no_duplicate_names(self) -> None:
        markup = '<script src="/jquery-3.6.0.min.js"><script src="/jquery.min.js">'
        found = detect_technologies(markup)
        assert len(found) == len({t.name for t in found})


class TestAstroAndAstra:
    """Owner reported an Astro site going undetected. Both `Astro` (the framework) and
    `Astra` (the WordPress theme) were missing or unreliable."""

    def test_astro_generator_meta_with_version(self) -> None:
        """The decisive signal. A fully static Astro build -- its whole selling point --
        ships no `astro-island` marker at all, so island detection alone misses it."""
        html = '<html><head><meta name="generator" content="Astro v7.2.6"></head></html>'
        found = {t.name: t for t in detect_technologies(html)}
        assert found["Astro"].version == "7.2.6"

    def test_astro_asset_path(self) -> None:
        html = '<html><head><link rel="stylesheet" href="/_astro/index.abc123.css"></head></html>'
        assert "Astro" in names(detect_technologies(html))

    def test_astro_island_still_detected(self) -> None:
        assert "Astro" in names(detect_technologies("<astro-island uid='1'></astro-island>"))

    def test_starlight(self) -> None:
        html = '<meta name="generator" content="Starlight v0.41.8">'
        found = {t.name: t for t in detect_technologies(html)}
        assert found["Starlight"].version == "0.41.8"

    def test_astra_wordpress_theme(self) -> None:
        html = '<link id="astra-theme-css" href="/wp-content/themes/astra/style.css">'
        found = {t.name: t for t in detect_technologies(html)}
        assert found["Astra"].category == "UI frameworks"

    @pytest.mark.parametrize(
        ("markup", "expected"),
        [
            ('<link href="/wp-content/themes/generatepress/x.css">', "GeneratePress"),
            ('<div class="elementor-widget">', "Elementor"),
            ('<div class="et_pb_row">', "Divi"),
            ('<div class="fl-builder-content">', "Beaver Builder"),
        ],
    )
    def test_other_wordpress_builders(self, markup: str, expected: str) -> None:
        assert expected in names(detect_technologies(markup))


class TestFalsePositives:
    """A wrong technology claim is worse than a missing one. Both classes below were found
    against live sites, not imagined."""

    def test_documenting_a_technology_is_not_using_it(self) -> None:
        """docs.astro.build was reported as running Strapi and Alpine.js purely because its
        sidebar links to /guides/cms/strapi/ and /guides/integrations-guide/alpinejs/."""
        html = (
            '<nav><a href="/en/guides/cms/strapi/">Strapi</a>'
            '<a href="/en/guides/integrations-guide/alpinejs/">Alpine.js</a></nav>'
        )
        found = names(detect_technologies(html))
        assert "Strapi" not in found
        assert "Alpine.js" not in found

    def test_consent_manager_vendor_list_is_not_usage(self) -> None:
        """wpastra.com embeds a cookie-consent lookup table naming dozens of vendors. It was
        reported as running 4 competing chat widgets and 5 competing analytics tools."""
        html = (
            "<script>var vendors = "
            '{"cdn.amplitude.com":["analytics","amplitude"],'
            '"client.crisp.chat":["functional","crisp"],'
            '"js.driftt.com":["functional","drift"],'
            '"widget.intercom.io":["functional","intercom"],'
            '"plausible.io/js":["analytics","plausible"],'
            '"cdn.segment.com":["analytics","segment"]};</script>'
        )
        found = names(detect_technologies(html))
        for vendor in ("Amplitude", "Crisp", "Drift", "Intercom", "Plausible", "Segment"):
            assert vendor not in found, f"{vendor} matched a consent-manager entry"

    def test_actually_loaded_script_is_still_detected(self) -> None:
        """The guard must not suppress genuine usage."""
        html = '<script src="https://cdn.segment.com/analytics.js/v1/abc/analytics.min.js"></script>'
        assert "Segment" in names(detect_technologies(html))
