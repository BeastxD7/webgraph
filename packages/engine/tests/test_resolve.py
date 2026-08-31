"""Union-resolution tests.

These pin the completeness property: merging two representations of a page must never lose
content that either one had. Every case here is drawn from a failure measured against real
sites, so a regression reproduces a real-world data loss rather than a hypothetical one.
"""

from __future__ import annotations

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


class TestUnionOrdering:
    def test_rendered_order_leads(self) -> None:
        """The rendered document's order is measured; the static document's is assumed."""
        static = doc("<p>Static extra</p>")
        rendered = doc("<p>First</p><p>Second</p>")
        merged, _, _ = union_documents(static, rendered)
        texts = [b.text for b in merged.blocks]
        assert texts[:2] == ["First", "Second"]
        assert texts[-1] == "Static extra"

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
