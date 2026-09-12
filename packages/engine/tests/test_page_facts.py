"""The tiers: the page's own node, then its wrapper, then its social preview.

The order is the design. Each tier is weaker evidence than the one above it, and a weaker
source that can displace a stronger one is not a fallback — it is a second opinion nobody
asked for. So a lower tier only ever fills a gap.
"""

from __future__ import annotations

from typing import Any

from webgraph.extract.page_facts import facts_for_page
from webgraph.pagetype import PageType
from webgraph.types import PayloadSource, StructuredPayload


def ld(**data: Any) -> StructuredPayload:
    return StructuredPayload(source=PayloadSource.JSON_LD, data=data, xpath="/html/head/script")


def og(**data: Any) -> StructuredPayload:
    return StructuredPayload(source=PayloadSource.OPEN_GRAPH, data=data)


class TestTierOrder:
    def test_the_article_node_beats_the_social_preview(self) -> None:
        """Open Graph is written for a share card. It is coverage, never a correction."""
        page = [
            og(**{"og:title": "You won't BELIEVE this build time trick"}),
            ld(**{"@type": "Article", "headline": "How we cut our build time"}),
        ]
        result = facts_for_page(page, PageType.ARTICLE)
        assert result.facts["headline"].value == "How we cut our build time"
        assert result.filled_from_generic == ()

    def test_the_social_preview_fills_a_gap(self) -> None:
        """95% of article pages carry `og:title`, and 40% ship no article node at all. On
        those the choice is Open Graph or nothing.

        It lands in `name` rather than `headline`, which is the honest place for it:
        `og:title` is what the page calls itself, and `headline` is the headline the
        publisher declared for the article. They are different claims and the schema keeps
        them apart.
        """
        page = [og(**{"og:title": "How we cut our build time"})]
        result = facts_for_page(page, PageType.ARTICLE)
        assert result.facts["name"].value == "How we cut our build time"
        assert "headline" not in result.facts
        assert "name" in result.filled_from_generic

    def test_a_gap_filled_value_says_where_it_came_from(self) -> None:
        """A reader deciding whether to trust a title needs to know it came off a share
        card, and the confidence alone does not say that."""
        page = [og(**{"og:title": "How we cut our build time"})]
        fact = facts_for_page(page, PageType.ARTICLE).facts["name"]
        assert fact.provenance.note is not None
        assert "social preview" in fact.provenance.note
        assert fact.provenance.confidence < 0.95

    def test_the_page_wrapper_comes_before_the_social_preview(self) -> None:
        page = [
            og(**{"og:title": "From the share card"}),
            ld(**{"@type": "WebPage", "name": "From the page wrapper"}),
        ]
        assert facts_for_page(page, PageType.ARTICLE).facts["name"].value == "From the page wrapper"


class TestSiteNameSuffix:
    """`og:title` is usually the headline with the site's name bolted on."""

    def test_the_site_name_is_trimmed_when_the_page_declares_it(self) -> None:
        page = [
            og(
                **{
                    "og:title": "What is Cloud Computing? | Google Cloud",
                    "og:site_name": "Google Cloud",
                }
            )
        ]
        assert (
            facts_for_page(page, PageType.ARTICLE).facts["name"].value
            == "What is Cloud Computing?"
        )

    def test_a_leading_site_name_is_trimmed_too(self) -> None:
        page = [og(**{"og:title": "Acme Blog - How we ship", "og:site_name": "Acme Blog"})]
        assert facts_for_page(page, PageType.ARTICLE).facts["name"].value == "How we ship"

    def test_nothing_is_trimmed_without_og_site_name(self) -> None:
        """Otherwise this is guessing that whatever follows a pipe is a site name, and
        plenty of real headlines contain one."""
        page = [og(**{"og:title": "Rust | what the borrow checker actually does"})]
        assert (
            facts_for_page(page, PageType.ARTICLE).facts["name"].value
            == "Rust | what the borrow checker actually does"
        )

    def test_a_title_that_is_only_the_site_name_survives(self) -> None:
        """Trimming it to an empty string would be worse than leaving it."""
        page = [og(**{"og:title": "Google Cloud", "og:site_name": "Google Cloud"})]
        assert facts_for_page(page, PageType.ARTICLE).facts["name"].value == "Google Cloud"


class TestDeclining:
    def test_an_unknown_page_type_produces_nothing(self) -> None:
        page = [ld(**{"@type": "Product", "name": "Crusher ANC 2"})]
        result = facts_for_page(page, PageType.UNKNOWN)
        assert result.facts == {}
        assert result.payloads_considered == 1

    def test_a_page_whose_markup_is_all_about_the_site_produces_nothing(self) -> None:
        """The common case on category pages: 72-79% ship JSON-LD, 16% ship a node about
        the page. Saying nothing is the difference between "no products" and "IKEA"."""
        page = [
            ld(**{"@type": "Organization", "name": "IKEA"}),
            ld(**{"@type": "BreadcrumbList", "name": "Product Breadcrumbs"}),
        ]
        result = facts_for_page(page, PageType.PRODUCT)
        assert result.facts == {}
        assert result.payloads_used == 0

    def test_the_result_reports_what_it_read(self) -> None:
        page = [
            ld(**{"@type": "Organization", "name": "Acme"}),
            ld(**{"@type": "Product", "name": "Widget", "offers": {"price": "19,99"}}),
        ]
        result = facts_for_page(page, PageType.PRODUCT)
        assert result.subject_types == ("Product",)
        assert result.payloads_considered == 2
        assert result.payloads_used == 1
        assert result.facts["name"].value == "Widget"
        assert result.facts["offers.price"].value == 19.99
