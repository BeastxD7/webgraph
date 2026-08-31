"""Technology fingerprinting tests.

Rules are hand-written because every maintained Wappalyzer ruleset is GPL-3.0 and would
force this Apache-2.0 engine to GPL. These tests pin the signal sources that an earlier
HTML-only profiler missed entirely.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from webgraph.profile.technology import (
    Technology,
    detect_technologies,
    merge_technologies,
)


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


class TestBundledFrameworks:
    """A bundled framework exposes no global at all.

    A Vite build of React has no `window.React`; the browser side reports it from the
    private properties React leaves on the DOM nodes it owns, and has no version to give.
    The sentinel must not become a version string.
    """

    def test_presence_sentinel_is_not_a_version(self) -> None:
        found = {t.name: t for t in detect_technologies("", None, {"React": "present"})}
        assert found["React"].version is None

    def test_numeric_report_is_still_a_version(self) -> None:
        found = {t.name: t for t in detect_technologies("", None, {"React Router": "6"})}
        assert found["React Router"].version == "6"

    def test_runtime_only_names_get_a_real_category(self) -> None:
        found = {t.name: t for t in detect_technologies("", None, {"React": "present"})}
        assert found["React"].category == "JavaScript frameworks"


class TestComponentLibraryRules:
    """These fire on emitted attributes, never on prose."""

    def test_tailwind_needs_a_responsive_prefix(self) -> None:
        names = {t.name for t in detect_technologies('<div class="md:grid-cols-3 flex">x</div>')}
        assert "Tailwind CSS" in names

    def test_the_word_tailwind_alone_does_not_count(self) -> None:
        names = {t.name for t in detect_technologies("<p>We rebuilt the site in Tailwind CSS.</p>")}
        assert "Tailwind CSS" not in names

    def test_lucide_needs_the_icon_class_not_the_word(self) -> None:
        used = {t.name for t in detect_technologies('<svg class="lucide lucide-arrow-right">')}
        mentioned = {t.name for t in detect_technologies("<p>We use lucide for icons.</p>")}
        assert "Lucide" in used
        assert "Lucide" not in mentioned

    def test_radix_needs_its_data_attribute(self) -> None:
        names = {t.name for t in detect_technologies('<div data-radix-popper-content-wrapper>')}
        assert "Radix UI" in names

    def test_open_graph_and_pwa_are_read_from_link_and_meta(self) -> None:
        names = {
            t.name
            for t in detect_technologies(
                '<meta property="og:title" content="x"><link rel="manifest" href="/m.json">'
            )
        }
        assert {"Open Graph", "PWA"} <= names


class TestRuntimeSignals:
    """The four signals a bare HTTP fetch cannot see.

    These closed most of the gap against a browser extension. On persyn.ai the engine went
    from 4 detections to 23 -- covering all 17 Wappalyzer reports, with matching versions
    for Facebook Pixel, Lenis, core-js and React Router.
    """

    def test_global_name_identifies_a_service(self) -> None:
        """`window.Tinybird` is the only trace Tinybird leaves anywhere on the page."""
        names = {t.name for t in detect_technologies("", custom_globals=["Tinybird", "foo"])}
        assert "Tinybird" in names

    def test_network_request_identifies_a_service(self) -> None:
        found = {
            t.name: t
            for t in detect_technologies(
                "", requests=["https://us-assets.i.posthog.com/array/phc_x/config.js"]
            )
        }
        assert "PostHog" in found
        assert "request:" in found["PostHog"].evidence

    def test_cookie_identifies_bot_management(self) -> None:
        """`__cf_bm` is set by a third-party script, so it never reaches the main response."""
        names = {t.name for t in detect_technologies("", cookies={"__cf_bm": "x"})}
        assert "Cloudflare Bot Management" in names

    def test_bundle_source_identifies_a_component_library(self) -> None:
        """Radix mounts its attributes only when a component opens; the bundle always names it."""
        names = {t.name for t in detect_technologies("", bundle_source='import "@radix-ui/react-dialog"')}
        assert "Radix UI" in names

    def test_absent_signals_produce_nothing(self) -> None:
        """Every runtime rule must decline on a static-only fetch rather than guess."""
        assert detect_technologies("<html><body><p>hello</p></body></html>") == []


class TestImplications:
    def test_meta_framework_implies_its_framework(self) -> None:
        """Next.js exposes `__NEXT_DATA__`; React underneath it exposes nothing at all."""
        found = {t.name: t for t in detect_technologies("", custom_globals=["__NEXT_DATA__"])}
        assert "React" in found
        assert "implied by Next.js" in found["React"].evidence
        assert found["React"].confidence < 100

    def test_shadcn_needs_more_than_radix_and_tailwind(self) -> None:
        """Plenty of projects use both directly; shadcn is inferred only with its own packages."""
        without = merge_technologies(
            [
                Technology("Radix UI", "UI frameworks"),
                Technology("Tailwind CSS", "UI frameworks"),
            ]
        )
        assert "shadcn/ui" not in {t.name for t in without}

        with_registry = merge_technologies(
            [
                Technology("Radix UI", "UI frameworks"),
                Technology("Tailwind CSS", "UI frameworks"),
                Technology("Sonner", "UI frameworks"),
            ]
        )
        assert "shadcn/ui" in {t.name for t in with_registry}

    def test_implications_see_the_union_of_passes(self) -> None:
        """Tailwind comes from the markup pass and Radix from the bundle pass.

        Neither alone can infer shadcn, which is why implications run over the merge rather
        than inside a single detection.
        """
        markup_pass = [Technology("Tailwind CSS", "UI frameworks")]
        bundle_pass = [
            Technology("Radix UI", "UI frameworks"),
            Technology("class-variance-authority", "JavaScript libraries"),
        ]
        assert "shadcn/ui" in {t.name for t in merge_technologies(markup_pass, bundle_pass)}

    def test_version_survives_the_merge(self) -> None:
        merged = {
            t.name: t
            for t in merge_technologies(
                [Technology("jQuery", "JavaScript libraries")],
                [Technology("jQuery", "JavaScript libraries", version="3.6.0")],
            )
        }
        assert merged["jQuery"].version == "3.6.0"


class TestNoFalsePositives:
    """Each of these fired on a real site before the rule was tightened."""

    def test_data_slot_alone_is_not_shadcn(self) -> None:
        """`data-slot` is a plain web-component attribute; Vercel's Geist uses it, and it
        credited nextjs.org with shadcn/ui."""
        names = {t.name for t in detect_technologies('<div data-slot="geist-logo">x</div>')}
        assert "shadcn/ui" not in names

    def test_single_letter_globals_are_not_libraries(self) -> None:
        """`window.L` is Leaflet's global and also anybody's one-letter variable."""
        names = {t.name for t in detect_technologies("", custom_globals=["L", "ga"])}
        assert "Leaflet" not in names
        assert "Google Analytics" not in names


class TestOutboundLinksAreNotEvidence:
    """A link to somebody else's stack says nothing about this site's.

    Hacker News was reported as running WordPress because its front page linked to a PDF
    hosted on one. This is the same failure as matching prose -- a page that *references* a
    technology being mistaken for one that *uses* it -- and it needs the same fix: anchor to
    something only the site itself can emit.
    """

    def test_a_link_to_another_sites_wordpress_is_not_wordpress(self) -> None:
        html = '<a href="https://elsewhere.example/wp-content/uploads/paper.pdf">paper</a>'
        assert "WordPress" not in names(detect_technologies(html))

    def test_a_root_relative_wordpress_asset_is_wordpress(self) -> None:
        html = '<link href="/wp-content/themes/x/style.css" rel="stylesheet">'
        assert "WordPress" in names(detect_technologies(html))

    def test_the_rest_api_discovery_link_is_wordpress(self) -> None:
        """WordPress emits this by default, so absolute-URL installs are still caught."""
        html = '<link rel="https://api.w.org/" href="https://site.example/wp-json/">'
        assert "WordPress" in names(detect_technologies(html))

    def test_the_generator_meta_still_carries_a_version(self) -> None:
        found = {
            t.name: t
            for t in detect_technologies('<meta name="generator" content="WordPress 6.4.2">')
        }
        assert found["WordPress"].version == "6.4.2"

    def test_a_link_to_another_sites_drupal_is_not_drupal(self) -> None:
        html = '<a href="https://elsewhere.example/sites/default/files/report.pdf">report</a>'
        assert "Drupal" not in names(detect_technologies(html))

    def test_drupals_own_settings_attribute_needs_no_anchoring(self) -> None:
        assert "Drupal" in names(detect_technologies('<script type="application/json" '
                                                     'data-drupal-settings-json>{}</script>'))


class TestSameOriginAssets:
    """`asset` rules match only references that resolve to the site being profiled.

    Anchoring to `href=` is not enough: the Hacker News false positive *was* an href. What
    separates "this site runs WordPress" from "this site links to one" is whose host the
    reference points at.
    """

    SITE: ClassVar[str] = "https://mysite.example/page"

    def test_a_link_to_another_sites_theme_is_not_that_theme(self) -> None:
        html = '<a href="https://other.example/wp-content/themes/divi/x.css">x</a>'
        assert "Divi" not in names(detect_technologies(html, url=self.SITE))

    def test_a_root_relative_reference_counts(self) -> None:
        html = '<link href="/wp-content/themes/divi/style.css">'
        assert "Divi" in names(detect_technologies(html, url=self.SITE))

    def test_an_absolute_reference_to_the_same_host_counts(self) -> None:
        html = '<link href="https://mysite.example/wp-content/themes/divi/s.css">'
        assert "Divi" in names(detect_technologies(html, url=self.SITE))

    def test_the_www_variant_is_the_same_host(self) -> None:
        html = '<script src="https://www.mysite.example/wp-content/plugins/wpforms/a.js"></script>'
        assert "WPForms" in names(detect_technologies(html, url=self.SITE))

    def test_without_a_url_only_relative_references_count(self) -> None:
        """The conservative reading: better to miss a site that writes absolute URLs to its
        own domain than to credit one with its neighbour's stack."""
        absolute = '<link href="https://mysite.example/wp-content/themes/divi/s.css">'
        relative = '<link href="/wp-content/themes/divi/s.css">'
        assert "Divi" not in names(detect_technologies(absolute))
        assert "Divi" in names(detect_technologies(relative))

    def test_class_based_signals_are_unaffected(self) -> None:
        """A class the page emits is not a URL and needs no origin check."""
        assert "Elementor" in names(detect_technologies('<div class="elementor-widget"></div>'))

    def test_data_and_scheme_urls_are_ignored(self) -> None:
        html = '<img src="data:image/gif;base64,AAA"><a href="mailto:x@y.z">m</a>'
        from webgraph.profile.technology import same_site_assets

        assert same_site_assets(html, self.SITE) == []
