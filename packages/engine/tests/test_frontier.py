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
            "#anchor", "javascript:void(0)", "mailto:a@b.com", "tel:+1234",
            "data:text/html,x", "ftp://example.com/f", "",
        ],
    )
    def test_non_pages_rejected(self, raw: str) -> None:
        assert normalize_url(raw) is None

    @pytest.mark.parametrize(
        "raw",
        [
            "https://example.com/a.jpg", "https://example.com/s.css",
            "https://example.com/b.js", "https://example.com/f.zip",
            "https://example.com/v.mp4", "https://example.com/f.woff2",
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
        assert same_site("https://blog.example.com/a", "https://example.com/", allow_subdomains=True)

    def test_www_and_bare_domain_are_the_same_site(self) -> None:
        """Regression: persyn.ai declares a `www.` canonical while resolving at the bare
        domain. Exact hostname comparison rejected every link and the crawl stopped after
        one page -- 1 page instead of 54."""
        assert same_site("https://www.persyn.ai/blog/x", "https://persyn.ai/")
        assert same_site("https://persyn.ai/blog/x", "https://www.persyn.ai/")
        assert same_site("https://www.example.com/", "https://www.example.com/")

    def test_www_prefix_handled(self) -> None:
        assert same_site("https://shop.example.com/a", "https://www.example.com/", allow_subdomains=True)

    def test_different_host(self) -> None:
        assert not same_site("https://other.com/a", "https://example.com/")

    def test_lookalike_domain_rejected(self) -> None:
        assert not same_site("https://notexample.com/a", "https://example.com/", allow_subdomains=True)


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
