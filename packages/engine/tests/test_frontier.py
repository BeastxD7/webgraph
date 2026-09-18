"""URL normalisation and frontier tests.

Normalisation is the highest-leverage correctness surface in a crawler: treating one page as
four URLs spends the budget four times and produces four copies of every entity downstream.
"""

from __future__ import annotations

import re

import pytest

from webgraph.crawl.frontier import (
    CrawlScope,
    Frontier,
    canonical_key,
    normalize_url,
    same_site,
    scope_patterns,
)


class TestNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://Example.COM/Path", "https://example.com/Path"),
            ("https://example.com/a#section", "https://example.com/a"),
            ("https://example.com:443/a", "https://example.com/a"),
            ("http://example.com:80/a", "http://example.com/a"),
            ("https://example.com/index.html", "https://example.com/"),
            ("https://example.com/dir/index.php", "https://example.com/dir/"),
            ("https://example.com", "https://example.com/"),
        ],
    )
    def test_canonical_forms(self, raw: str, expected: str) -> None:
        assert normalize_url(raw) == expected

    def test_tracking_parameters_stripped(self) -> None:
        assert (
            normalize_url("https://example.com/p?utm_source=x&id=7&fbclid=abc")
            == "https://example.com/p?id=7"
        )

    def test_query_order_normalised(self) -> None:
        """Servers emit the same page with parameters in different orders."""
        assert normalize_url("https://example.com/p?b=2&a=1") == normalize_url(
            "https://example.com/p?a=1&b=2"
        )

    def test_relative_resolution(self) -> None:
        assert (
            normalize_url("../about", base="https://example.com/docs/guide/")
            == "https://example.com/docs/about"
        )

    @pytest.mark.parametrize(
        "raw",
        [
            "#anchor",
            "javascript:void(0)",
            "mailto:a@b.com",
            "tel:+1234",
            "data:text/html,x",
            "ftp://example.com/f",
            "",
        ],
    )
    def test_non_pages_rejected(self, raw: str) -> None:
        assert normalize_url(raw) is None

    @pytest.mark.parametrize(
        "raw",
        [
            "https://example.com/a.jpg",
            "https://example.com/s.css",
            "https://example.com/b.js",
            "https://example.com/f.zip",
            "https://example.com/v.mp4",
            "https://example.com/f.woff2",
        ],
    )
    def test_asset_urls_rejected(self, raw: str) -> None:
        assert normalize_url(raw) is None

    def test_pdfs_are_not_rejected(self) -> None:
        """PDFs are documents worth extracting, not assets to discard."""
        assert normalize_url("https://example.com/report.pdf") is not None


class TestSameSite:
    def test_exact_host(self) -> None:
        assert same_site("https://example.com/a", "https://example.com/")

    def test_subdomain_excluded_by_default(self) -> None:
        """Subdomains are usually different apps; following them unbounds the crawl."""
        assert not same_site("https://blog.example.com/a", "https://example.com/")

    def test_subdomain_allowed_when_requested(self) -> None:
        assert same_site(
            "https://blog.example.com/a", "https://example.com/", allow_subdomains=True
        )

    def test_www_and_bare_domain_are_the_same_site(self) -> None:
        """Regression: persyn.ai declares a `www.` canonical while resolving at the bare
        domain. Exact hostname comparison rejected every link and the crawl stopped after
        one page -- 1 page instead of 54."""
        assert same_site("https://www.persyn.ai/blog/x", "https://persyn.ai/")
        assert same_site("https://persyn.ai/blog/x", "https://www.persyn.ai/")
        assert same_site("https://www.example.com/", "https://www.example.com/")

    def test_www_prefix_handled(self) -> None:
        assert same_site(
            "https://shop.example.com/a", "https://www.example.com/", allow_subdomains=True
        )

    def test_different_host(self) -> None:
        assert not same_site("https://other.com/a", "https://example.com/")

    def test_lookalike_domain_rejected(self) -> None:
        assert not same_site(
            "https://notexample.com/a", "https://example.com/", allow_subdomains=True
        )


class TestFrontier:
    def scope(self, **kwargs: object) -> CrawlScope:
        return CrawlScope(root="https://example.com/", **kwargs)  # type: ignore[arg-type]

    def test_deduplicates_equivalent_urls(self) -> None:
        frontier = Frontier(scope=self.scope())
        assert frontier.add("https://example.com/a", 0)
        assert not frontier.add("https://example.com/a#top", 0)
        assert not frontier.add("https://example.com/a?utm_source=x", 0)
        assert len(frontier) == 1

    def test_breadth_first_order(self) -> None:
        frontier = Frontier(scope=self.scope())
        frontier.add("https://example.com/a", 0)
        frontier.add("https://example.com/b", 0)
        assert frontier.pop() == ("https://example.com/a", 0)
        assert frontier.pop() == ("https://example.com/b", 0)
        assert frontier.pop() is None

    def test_depth_limit_enforced(self) -> None:
        frontier = Frontier(scope=self.scope(max_depth=2))
        assert frontier.add("https://example.com/a", 2)
        assert not frontier.add("https://example.com/b", 3)

    def test_offsite_rejected(self) -> None:
        frontier = Frontier(scope=self.scope())
        assert not frontier.add("https://other.com/a", 0)

    def test_exclude_pattern(self) -> None:
        frontier = Frontier(scope=self.scope(exclude_patterns=(re.compile(r"/admin/"),)))
        assert not frontier.add("https://example.com/admin/x", 0)
        assert frontier.add("https://example.com/public/x", 0)

    def test_include_pattern_restricts(self) -> None:
        frontier = Frontier(scope=self.scope(include_patterns=(re.compile(r"/docs/"),)))
        assert frontier.add("https://example.com/docs/a", 0)
        assert not frontier.add("https://example.com/blog/a", 0)

    def test_add_many_counts_accepted(self) -> None:
        frontier = Frontier(scope=self.scope())
        added = frontier.add_many(
            ["https://example.com/a", "https://example.com/a", "https://other.com/b"], 0
        )
        assert added == 1

    def test_relative_links_resolved_against_base(self) -> None:
        frontier = Frontier(scope=self.scope())
        assert frontier.add("/about", 0, base="https://example.com/docs/")
        assert frontier.pop() == ("https://example.com/about", 0)

    def test_seen_count_includes_rejected_duplicates(self) -> None:
        frontier = Frontier(scope=self.scope())
        frontier.add("https://example.com/a", 0)
        frontier.add("https://example.com/a", 0)
        assert frontier.seen_count == 1


class TestCanonicalKey:
    """Deduplication identity, deliberately distinct from the URL used to fetch."""

    def test_www_and_bare_share_a_key(self) -> None:
        """solidjs.com redirects to www.solidjs.com. Keying on the raw string queues every
        page twice -- once per hostname form -- doubling work and duplicating entities."""
        assert canonical_key("https://www.solidjs.com/ecosystem") == canonical_key(
            "https://solidjs.com/ecosystem"
        )

    def test_trailing_slash_shares_a_key(self) -> None:
        assert canonical_key("https://e.com/a/") == canonical_key("https://e.com/a")

    def test_different_paths_keep_distinct_keys(self) -> None:
        assert canonical_key("https://e.com/a") != canonical_key("https://e.com/b")

    def test_query_is_significant(self) -> None:
        assert canonical_key("https://e.com/a?x=1") != canonical_key("https://e.com/a?x=2")

    def test_frontier_dedupes_across_www(self) -> None:
        frontier = Frontier(scope=CrawlScope(root="https://solidjs.com/"))
        assert frontier.add("https://solidjs.com/ecosystem", 0)
        assert not frontier.add("https://www.solidjs.com/ecosystem/", 0)
        assert len(frontier) == 1

    def test_queued_url_is_the_one_linked_not_the_key(self) -> None:
        """Some hosts serve only one hostname form; rewriting the request would 404."""
        frontier = Frontier(scope=CrawlScope(root="https://solidjs.com/"))
        frontier.add("https://www.solidjs.com/store", 0)
        queued = frontier.pop()
        assert queued is not None
        assert queued[0] == "https://www.solidjs.com/store"


class TestMarkSeen:
    """A page the caller already holds is visited, not queued.

    The root is fetched by site analysis before the crawl begins; the frontier must neither
    queue it again nor treat a later link back to it as a discovery.
    """

    def test_marked_url_is_not_queued(self) -> None:
        from webgraph.crawl.frontier import CrawlScope, Frontier

        frontier = Frontier(scope=CrawlScope(root="https://example.test/"))
        assert frontier.mark_seen("https://example.test/") is True
        assert len(frontier) == 0
        assert frontier.seen_count == 1

    def test_marked_url_is_rejected_when_linked_later(self) -> None:
        from webgraph.crawl.frontier import CrawlScope, Frontier

        frontier = Frontier(scope=CrawlScope(root="https://example.test/"))
        frontier.mark_seen("https://example.test/")
        assert frontier.add("https://example.test/", 1) is False
        assert frontier.add("https://www.example.test/", 1) is False
        assert frontier.extend(["https://example.test/", "https://example.test/a"], 1) == [
            "https://example.test/a"
        ]

    def test_marking_twice_is_idempotent(self) -> None:
        from webgraph.crawl.frontier import CrawlScope, Frontier

        frontier = Frontier(scope=CrawlScope(root="https://example.test/"))
        assert frontier.mark_seen("https://example.test/") is True
        assert frontier.mark_seen("https://example.test/") is False
        assert frontier.seen_count == 1

    def test_garbage_is_ignored(self) -> None:
        from webgraph.crawl.frontier import CrawlScope, Frontier

        frontier = Frontier(scope=CrawlScope(root="https://example.test/"))
        assert frontier.mark_seen("not a url") is False
        assert frontier.seen_count == 0


class TestScriptHoles:
    """`/undefined` is a template interpolating a missing value, not an address."""

    def test_undefined_and_null_paths_are_refused(self) -> None:
        from webgraph.crawl.frontier import normalize_url

        for path in ("/undefined", "/null", "/brand/undefined", "/null/", "/NaN"):
            assert normalize_url(f"https://x.test{path}") is None, path

    def test_words_that_merely_contain_them_survive(self) -> None:
        from webgraph.crawl.frontier import normalize_url

        assert normalize_url("https://x.test/nullable-types") is not None
        assert normalize_url("https://x.test/undefined-behaviour-in-c") is not None


class TestBreadthFirstByDepth:
    """Depth is link distance from the root, and the queue empties one depth at a time."""

    def test_every_page_at_depth_n_precedes_every_page_at_depth_n_plus_1(self) -> None:
        from webgraph.crawl.frontier import CrawlScope, Frontier

        frontier = Frontier(scope=CrawlScope(root="https://x.test/", max_depth=5))
        frontier.add("https://x.test/a", 1)
        frontier.add("https://x.test/b", 1)
        # Children of /a arrive while /b is still queued; they must wait behind it.
        frontier.add("https://x.test/a/1", 2)
        frontier.add("https://x.test/a/2", 2)
        frontier.add("https://x.test/c", 1)
        depths = []
        while (item := frontier.pop()) is not None:
            depths.append(item[1])
        assert depths == sorted(depths)

    def test_max_depth_is_a_hard_wall(self) -> None:
        from webgraph.crawl.frontier import CrawlScope, Frontier

        frontier = Frontier(scope=CrawlScope(root="https://x.test/", max_depth=1))
        assert frontier.add("https://x.test/a", 1)
        assert not frontier.add("https://x.test/a/deep", 2)

    def test_depth_counts_describe_the_shape(self) -> None:
        from webgraph.crawl.frontier import CrawlScope, Frontier

        frontier = Frontier(scope=CrawlScope(root="https://x.test/", max_depth=5))
        frontier.mark_seen("https://x.test/")
        for n in range(3):
            frontier.add(f"https://x.test/{n}", 1)
        frontier.add("https://x.test/0/x", 2)
        assert frontier.depth_counts() == {0: 1, 1: 3, 2: 1}


class TestDomainStrictness:
    def test_strict_keeps_to_the_host_and_its_www(self) -> None:
        from webgraph.crawl.frontier import CrawlScope

        scope = CrawlScope(root="https://www.example.com/", allow_subdomains=False)
        assert scope.permits("https://example.com/a", 1)
        assert not scope.permits("https://blog.example.com/a", 1)
        assert not scope.permits("https://other.com/a", 1)

    def test_relaxed_follows_subdomains_but_never_other_sites(self) -> None:
        from webgraph.crawl.frontier import CrawlScope

        scope = CrawlScope(root="https://example.com/", allow_subdomains=True)
        assert scope.permits("https://blog.example.com/a", 1)
        assert scope.permits("https://shop.example.com/a", 1)
        assert not scope.permits("https://other.com/a", 1)
        assert not scope.permits("https://notexample.com/a", 1)


class TestRefusals:
    """Every address the frontier turns away is counted under a reason, and the first of
    each is kept -- files aside, which are `skipped` with a citation instead."""

    def test_each_reason_is_counted_once_per_address(self) -> None:
        scope = CrawlScope(root="https://example.com/", max_depth=1)
        frontier = Frontier(scope=scope)
        base = "https://example.com/"
        assert frontier.add("https://example.com/", 0)
        # Off-site: once, however many pages link to it.
        frontier.extend(["https://other.example/x", "https://other.example/x"], 1, base=base)
        frontier.extend(["https://other.example/x"], 1, base=base)
        # Past depth.
        frontier.extend(["/deep"], 2, base=base)
        # Not a page.
        frontier.extend(["mailto:a@example.com", "javascript:void(0)", "/undefined"], 1, base=base)
        # A same-site file: skipped and cited, not refused. An off-site image: neither.
        frontier.extend(["/brochure.pdf", "/logo.png", "https://cdn.example/x.png"], 1, base=base)
        # Accepted.
        frontier.extend(["/about"], 1, base=base)

        assert frontier.refusals == {
            "off-site": 1,
            "past-depth": 1,
            "not-a-page": 3,
            "excluded": 0,
            "not-included": 0,
            "queue-cap": 0,
        }
        assert frontier.refused_urls == {
            "https://other.example/x": "off-site",
            "https://example.com/deep": "past-depth",
            "mailto:a@example.com": "not-a-page",
            "javascript:void(0)": "not-a-page",
            "https://example.com/undefined": "not-a-page",
        }
        assert frontier.skipped["pdf"] == 1 and frontier.skipped["image"] == 1
        assert len(frontier) == 2  # the root and /about

    def test_patterns_and_the_cap(self) -> None:
        scope = CrawlScope(
            root="https://example.com/",
            include_patterns=(re.compile(r"^/docs/"),),
            exclude_patterns=(re.compile(r"^/docs/private"),),
        )
        frontier = Frontier(scope=scope, max_queue=1)
        base = "https://example.com/"
        frontier.extend(["/docs/a", "/docs/private/b", "/blog/c", "/docs/d"], 1, base=base)
        assert frontier.refusals["excluded"] == 1
        assert frontier.refusals["not-included"] == 1
        assert frontier.refusals["queue-cap"] == 1
        assert frontier.refused_urls["https://example.com/docs/private/b"] == "excluded"
        assert frontier.refused_urls["https://example.com/blog/c"] == "not-included"
        assert frontier.refused_urls["https://example.com/docs/d"] == "queue-cap"

    def test_the_reason_is_the_fact_about_the_address(self) -> None:
        scope = CrawlScope(root="https://example.com/", max_depth=2)
        assert scope.refusal("https://example.com/a", 2) is None
        assert scope.refusal("https://example.com/a", 3) == "past-depth"
        assert scope.refusal("https://blog.example.com/a", 1) == "off-site"
        assert (
            CrawlScope(root="https://example.com/", allow_subdomains=True).refusal(
                "https://blog.example.com/a", 1
            )
            is None
        )
        assert scope.refusal("https://www.example.com/a", 1) is None


class TestScopePatterns:
    """Path patterns, and staying under the start address's path, as `CrawlScope` rules."""

    def test_within_the_start_path(self) -> None:
        include = scope_patterns("", within="https://example.com/docs/guide")
        scope = CrawlScope(root="https://example.com/", include_patterns=include)
        assert scope.refusal("https://example.com/docs/api", 1) is None
        assert scope.refusal("https://example.com/docs/", 1) is None
        assert scope.refusal("https://example.com/blog/x", 1) == "not-included"
        # The root's directory is every path: no restriction is added for it.
        assert scope_patterns("", within="https://example.com/") == ()

    def test_include_and_exclude_over_the_path(self) -> None:
        scope = CrawlScope(
            root="https://example.com/",
            include_patterns=scope_patterns("^/docs/, ^/blog/"),
            exclude_patterns=scope_patterns("/private"),
        )
        assert scope.refusal("https://example.com/docs/a", 1) is None
        assert scope.refusal("https://example.com/blog/b", 1) is None
        assert scope.refusal("https://example.com/about", 1) == "not-included"
        assert scope.refusal("https://example.com/docs/private/c", 1) == "excluded"
        # Patterns are over the path, never the host: "docs" in the host does not match.
        assert scope.refusal("https://docs.example.com/x", 1) == "off-site"

    def test_a_broken_pattern_is_the_callers_error(self) -> None:
        with pytest.raises(ValueError, match="not a valid path pattern"):
            scope_patterns("^/docs/(")
