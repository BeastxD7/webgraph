"""The literal prefilter in front of every markup regex, and the proof that it changes nothing.

Measured before it existed: `detect_technologies` took 583 ms on a 250 KB page and 4.9 s on
a 2 MB one -- 77% of `build_document` -- because 116 case-insensitive regexes each scanned
the whole page at ~10 ms per 250 KB, whatever they were looking for. After: 46 ms and
626 ms. The saving comes entirely from *not running* a regex whose required literal is
absent, so the only thing that can go wrong is a needle the regex does not in fact require.
Every test here is therefore about soundness first: the extractor on patterns that have
tripped such tools before, the fold on the three characters IGNORECASE and `str.lower()`
disagree about, and prefilter-on against prefilter-off on every fixture we ship.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

import pytest

from webgraph.profile import technology
from webgraph.profile.fingerprint import FRAMEWORK_RULES
from webgraph.profile.technology import (
    TECH_RULES,
    detect_technologies,
    fold_for_prefilter,
    required_literals,
    same_site_assets,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def prefilter_off():  # type: ignore[no-untyped-def]
    technology._PREFILTER_ENABLED = False
    try:
        yield
    finally:
        technology._PREFILTER_ENABLED = True


class TestRequiredLiterals:
    """Each case is a shape from `TECH_RULES` that a naive extractor gets wrong."""

    def test_plain_literal_is_its_own_needle(self) -> None:
        assert required_literals(r"drupal-settings-json") == (("drupal-settings-json",),)

    def test_uppercase_in_the_pattern_is_folded(self) -> None:
        assert required_literals(r"MuiBox-root|material-ui") == (("material-ui", "muibox-root"),)

    def test_alternation_is_the_union_of_its_branches(self) -> None:
        assert required_literals(r"__cf_bm|challenge-platform") == (
            ("__cf_bm", "challenge-platform"),
        )

    def test_a_branch_without_a_needle_voids_the_whole_alternation(self) -> None:
        # `a` is one character: a page matching via that branch need not contain `bc`.
        assert required_literals(r"(?:a|bc)") == ()

    def test_a_class_yields_nothing(self) -> None:
        assert required_literals(r"[a-z]{3}") == ()
        assert required_literals(r"[0-9a-f]{6,}") == ()

    def test_escaped_dot_is_a_literal(self) -> None:
        assert required_literals(r"cdn\.sanity\.io") == (("cdn.sanity.io",),)

    def test_unescaped_dot_breaks_the_run(self) -> None:
        # `fbq\(\s*.init.` -- the `.` may be any character, so `init` stands alone.
        assert required_literals(r"fbq\(\s*.init.") == (("fbq(",), ("init",))

    def test_optional_group_contributes_nothing_but_does_not_void(self) -> None:
        # `(?:\.min)?` may match nothing; `lodash` and `.js` are still both required.
        assert required_literals(r"lodash(?:\.min)?\.js") == (("lodash",), (".js",))

    def test_repeat_with_a_minimum_requires_its_body_once(self) -> None:
        assert required_literals(r"(?:foo)+bar") == (("foo",), ("bar",))
        assert required_literals(r"(?:foo)*bar") == (("bar",),)

    def test_negated_class_star_splits_the_pattern(self) -> None:
        assert required_literals(r"""(?:src|href)=["'][^"']*plausible\.io""") == (
            ("plausible.io",),
            ('href="', "href='", 'src="', "src='"),
        )

    def test_named_group_is_transparent_and_breaks_at_the_class(self) -> None:
        assert required_literals(r'name="generator"\s+content="Astro v(?P<version>[\d.]+)"') == (
            ('name="generator"',),
            ('content="astro v',),
        )

    def test_run_continues_through_a_group(self) -> None:
        assert required_literals(r"ab(?:cd)ef") == (("abcdef",),)
        assert required_literals(r"ab(cd)ef") == (("abcdef",),)

    def test_nested_groups(self) -> None:
        assert required_literals(r"(?:(?:embed|cdn)\.tawk\.to)") == (
            ("cdn.tawk.to", "embed.tawk.to"),
        )

    def test_hoisted_common_prefix_is_multiplied_back_in(self) -> None:
        # `re` parses `_nghost-|_ngcontent-` as `_ng` followed by a branch. Without the
        # product, the needles would be `host-` and `content-`, and `content-` is on
        # every page with a `Content-Type`.
        assert required_literals(r"_nghost-|_ngcontent-") == (("_ngcontent-", "_nghost-"),)

    def test_literal_alternation_in_a_run_is_a_product(self) -> None:
        assert required_literals(r"(?:sm|md|lg|xl|2xl):") == (
            ("2xl:", "lg:", "md:", "sm:", "xl:"),
        )

    def test_literal_class_in_a_run_is_a_product(self) -> None:
        assert required_literals(r"jquery[.-]\d") == (("jquery-", "jquery."),)

    def test_product_over_the_cap_splits_the_run_soundly(self) -> None:
        # 6 x 6 = 36 > 32: the first six survive as a clause, the trailing single characters
        # are too short to keep. Either way nothing stronger than the regex is claimed.
        clauses = required_literals(r"xyz(?:a|b|c|d|e|f)(?:a|b|c|d|e|f)")
        assert clauses == (("xyza", "xyzb", "xyzc", "xyzd", "xyze", "xyzf"),)

    def test_word_boundary_breaks_but_does_not_void(self) -> None:
        assert required_literals(r"\bwc-ajax\b") == (("wc-ajax",),)

    def test_lookaround_contributes_nothing(self) -> None:
        assert required_literals(r"(?=abc)def") == (("def",),)
        assert required_literals(r"abc(?!def)") == (("abc",),)

    def test_backreference_breaks_the_run(self) -> None:
        assert required_literals(r"(abc)\1xyz") == (("abc",), ("xyz",))

    def test_non_ascii_literal_breaks_the_run(self) -> None:
        # Comparing lowercased ASCII is only exact for ASCII; a non-ASCII literal is treated
        # like a class rather than risk a fold the engine disagrees with. The runs either
        # side of it survive on their own.
        assert required_literals("caf\u00e9-bar") == (("-bar",), ("caf",))

    def test_short_members_void_the_clause_not_just_themselves(self) -> None:
        # Dropping `x` alone would claim `abc` is required; it is not.
        assert required_literals(r"(?:abc|x)") == ()

    def test_conjunction_is_ordered_most_selective_first(self) -> None:
        # `class=` is on every page; `lenis` on almost none. The check that can fail first.
        assert required_literals(r"""class=["'][^"']*\blenis\b""") == (
            ("lenis",),
            ('class="', "class='"),
        )

    def test_unparseable_pattern_degrades_to_no_prefilter(self) -> None:
        assert required_literals(r"(unclosed") == ()


class TestEveryRuleIsPrefiltered:
    """A rule that silently loses its needles is back to a full scan per page. None may.

    There is no allow-list: every markup and bundle pattern in the rule set yields at least
    one clause today. A new rule that cannot (`[a-z]{3}` alone, say) must be added here
    with a reason, not waved through.
    """

    def test_every_html_rule_has_a_clause(self) -> None:
        missing = [r.name for r in TECH_RULES if r.html is not None and not r.html_needles]
        assert missing == []

    def test_every_source_rule_has_a_clause(self) -> None:
        missing = [r.name for r in TECH_RULES if r.source is not None and not r.source_needles]
        assert missing == []

    def test_every_framework_rule_has_a_clause(self) -> None:
        assert [r.name for r in FRAMEWORK_RULES if not r.needles] == []

    def test_needles_are_lowercase_ascii_and_long_enough(self) -> None:
        for rule in TECH_RULES:
            for clause in rule.html_needles + rule.source_needles:
                for needle in clause:
                    assert needle == needle.lower() and needle.isascii() and len(needle) >= 3


class TestFold:
    """`str.lower()` and IGNORECASE disagree on exactly three characters, found by matching
    every code point against every ASCII letter. Each must fold to what the regex accepts."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("\u0130stanbul", "istanbul"),  # capital dotted I lowercases to TWO chars
            ("\u0131", "i"),  # dotless i is already lowercase, and matches `i`
            ("po\u017fthog", "posthog"),  # long s matches `s`
            ("\u212aelvin", "kelvin"),  # KELVIN SIGN, which str.lower() already handles
            ("PostHog", "posthog"),
        ],
    )
    def test_folds_to_what_ignorecase_matches(self, text: str, expected: str) -> None:
        assert fold_for_prefilter(text) == expected

    def test_length_is_preserved(self) -> None:
        text = "<a HREF='/\u0130\u0131\u017f\u212a\u00df\u03a3'>"
        assert len(fold_for_prefilter(text)) == len(text)

    @pytest.mark.parametrize(
        "html",
        [
            "<script>po\u017fthog.init(</script>",
            "<div data-sveltek\u0130t-hydrate></div>",
            "<link rel='https://api.w.org/'>",
            '<meta name="generator" content="WORDPRESS 6.4">',
            '<div class="x"><span class="ast-conta\u0130ner"></span></div>',
        ],
    )
    def test_ignorecase_edge_cases_are_still_detected(self, html: str) -> None:
        with_prefilter = detect_technologies(html)
        technology._PREFILTER_ENABLED = False
        try:
            without = detect_technologies(html)
        finally:
            technology._PREFILTER_ENABLED = True
        assert with_prefilter == without
        assert with_prefilter, html


class TestEquivalenceOnFixtures:
    """Prefilter on and off must produce identical Technology lists, evidence included.

    The full check -- 193 pages including Zyte's 181 -- runs from the scratchpad; this is the
    part of it that ships. Any difference here means a needle the regex does not require.
    """

    PAGES = sorted(FIXTURES.rglob("*.htm*"))

    @pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
    @pytest.mark.parametrize("url", ["https://example.com/page", ""])
    def test_identical_results(self, page: Path, url: str) -> None:
        html = page.read_text(errors="replace")
        on = (detect_technologies(html, url=url), same_site_assets(html, url))
        technology._PREFILTER_ENABLED = False
        try:
            off = (detect_technologies(html, url=url), same_site_assets(html, url))
        finally:
            technology._PREFILTER_ENABLED = True
        assert on == off

    def test_fixtures_exist(self) -> None:
        assert len(self.PAGES) >= 4


class TestSpeed:
    """A page of prose with nothing to find is the case the prefilter exists for."""

    @staticmethod
    def _prose(kilobytes: int) -> str:
        words = [
            "the", "quick", "brown", "fox", "jumps", "over", "a", "lazy", "dog", "while",
            "reading", "about", "history", "geography", "science", "and", "literature",
            "in", "the", "library",
        ]
        rng = random.Random(1)
        body = " ".join(rng.choice(words) for _ in range(kilobytes * 180))
        return f"<html><head><title>Prose</title></head><body><p>{body}</p></body></html>"

    def test_prose_page_is_cheap(self) -> None:
        """512 KB of prose: ~65 ms with the prefilter, ~1.2 s without, on the dev machine.

        The floor is ~180 distinct `str.__contains__` tests at ~0.7 ns per byte; the bound
        below is four times the measured figure so CI noise cannot fail it, and the ratio
        against the unfiltered path is what actually pins the mechanism.
        """
        html = self._prose(512)
        assert len(html) > 500_000

        detect_technologies(html)  # warm
        start = time.perf_counter()
        detect_technologies(html)
        filtered = time.perf_counter() - start

        technology._PREFILTER_ENABLED = False
        try:
            start = time.perf_counter()
            detect_technologies(html)
            unfiltered = time.perf_counter() - start
        finally:
            technology._PREFILTER_ENABLED = True

        assert filtered < 0.3, f"{filtered * 1000:.0f} ms"
        assert filtered < unfiltered / 5, f"{filtered * 1000:.0f} ms vs {unfiltered * 1000:.0f} ms"
