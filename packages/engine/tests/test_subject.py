"""Choosing the node a page is about.

Every fixture here is a real shape, not an invented one: the node orders are the ones Yoast
and Rank Math actually emit, the forum case is Discourse's split between JSON-LD identity and
microdata content, and the wrong values asserted against are ones that were measured coming
out of the naive mapper on real pages.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from webgraph.extract.pageschema import schema_for
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.extract.subject import node_types, select_subject
from webgraph.pagetype import PageType
from webgraph.types import PayloadSource, StructuredPayload


def ld(**data: Any) -> StructuredPayload:
    return StructuredPayload(source=PayloadSource.JSON_LD, data=data, xpath="/html/head/script")


def micro(**data: Any) -> StructuredPayload:
    return StructuredPayload(source=PayloadSource.MICRODATA, data=data, xpath="/html/body/div")


def og(**data: Any) -> StructuredPayload:
    return StructuredPayload(source=PayloadSource.OPEN_GRAPH, data=data)


def names(payloads: list[StructuredPayload], page_type: PageType, url: str = "") -> Any:
    """What the auto-selected schema reports as the page's own name, end to end."""
    schema = schema_for(page_type)
    assert schema is not None
    subject = select_subject(payloads, page_type, url)
    facts = merge_facts(extract_facts(subject, schema, url))
    fact = facts.get("name") or facts.get("headline")
    return fact.value if fact else None


class TestNodeTypes:
    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            ("Product", {"Product"}),
            ("http://schema.org/Product", {"Product"}),
            ("https://schema.org/Product/", {"Product"}),
            (["Product", "https://schema.org/IndividualProduct"], {"Product", "IndividualProduct"}),
        ],
    )
    def test_reads_every_spelling(self, declared: Any, expected: set[str]) -> None:
        """Microdata writes the type as a URL, JSON-LD as a bare name, either may be a list."""
        assert node_types({"@type": declared}) == expected

    def test_a_node_with_no_type_declares_nothing(self) -> None:
        assert node_types({"name": "Untyped"}) == set()


class TestTheCompanyIsNotTheProduct:
    """The failure this module exists to remove.

    Measured on real pages: `Organization` supplied the winning name on 46% of category
    pages and 15% of product pages. `"IKEA"` where the page says "Shelving furniture".
    """

    PAGE: ClassVar[list[StructuredPayload]] = [
        ld(**{"@type": "Organization", "name": "Skullcandy"}),
        ld(**{"@type": "WebSite", "name": "Skullcandy.com"}),
        ld(**{"@type": "BreadcrumbList", "name": "Product Breadcrumbs"}),
        ld(**{"@type": "Product", "name": "Crusher ANC 2"}),
    ]

    def test_the_product_wins_over_the_company(self) -> None:
        assert names(self.PAGE, PageType.PRODUCT) == "Crusher ANC 2"

    def test_yoast_order_and_rank_math_order_agree(self) -> None:
        """Document order cannot break this tie, because the two biggest emitters disagree.

        Yoast puts the subject node first; Rank Math puts `Organization` first and the
        subject node last. A mapper that fell back on order would give a different answer
        depending on which SEO plugin the shop installed.
        """
        rank_math = list(self.PAGE)
        yoast = [self.PAGE[-1], *self.PAGE[:-1]]
        assert names(rank_math, PageType.PRODUCT) == names(yoast, PageType.PRODUCT)

    def test_a_page_with_only_a_company_reports_no_product_name(self) -> None:
        """Declining is the point. The company's name is not the product's name, and a
        missing field can be escalated in a way a confident wrong one cannot."""
        assert names(self.PAGE[:3], PageType.PRODUCT) is None


class TestPerPageType:
    def test_service_keeps_the_organization_every_other_type_refuses(self) -> None:
        """A marketing page has no page-level node; the company is what is there."""
        page = [ld(**{"@type": "Organization", "name": "Acme Ltd", "telephone": "+44 20 7946"})]
        schema = schema_for(PageType.SERVICE)
        assert schema is not None
        facts = merge_facts(extract_facts(select_subject(page, PageType.SERVICE), schema, ""))
        assert facts["organizationName"].value == "Acme Ltd"
        assert facts["telephone"].value == "+44 20 7946"

    def test_a_service_page_reports_no_title(self) -> None:
        """Every method of titling a marketing page measured ~50% wrong. The schema answers
        the question it can answer and declines the one it cannot."""
        schema = schema_for(PageType.SERVICE)
        assert schema is not None
        assert "name" not in schema["properties"] and "headline" not in schema["properties"]

    def test_a_forum_reply_is_not_the_thread(self) -> None:
        """212 `Comment` nodes across 91 forum pages; `Comment` won the name on 16% of them."""
        page = [
            micro(**{"@type": "http://schema.org/Comment", "name": "I had this too, thanks!"}),
            micro(
                **{
                    "@type": "http://schema.org/DiscussionForumPosting",
                    "headline": "Disc brake rub after wheel swap",
                }
            ),
        ]
        assert names(page, PageType.FORUM) == "Disc brake rub after wheel swap"

    def test_microdata_is_read_for_forums_not_just_json_ld(self) -> None:
        """Discourse and Stack Exchange publish JSON-LD for site identity only and put the
        discussion in microdata. Reading JSON-LD alone returns the site's name."""
        page = [
            ld(**{"@type": "WebSite", "name": "Cycling Forum"}),
            micro(
                **{
                    "@type": "http://schema.org/DiscussionForumPosting",
                    "headline": "Disc brake rub after wheel swap",
                }
            ),
        ]
        assert names(page, PageType.FORUM) == "Disc brake rub after wheel swap"

    def test_an_unknown_page_type_selects_nothing(self) -> None:
        """A page the router could not type has no known subject, and guessing one is the
        behaviour this module was written to remove."""
        page = [ld(**{"@type": "Product", "name": "Crusher ANC 2"})]
        assert select_subject(page, PageType.UNKNOWN) == []
        assert schema_for(PageType.UNKNOWN) is None

    def test_documentation_ships_almost_nothing_and_means_it(self) -> None:
        """11% of documentation pages carry a node about the page. Promising more fields
        would be promising blanks."""
        schema = schema_for(PageType.DOCUMENTATION)
        assert schema is not None
        assert set(schema["properties"]) == {"headline", "dateModified"}


class TestSeveralCandidates:
    def test_the_node_naming_this_page_wins(self) -> None:
        page = [
            ld(**{"@type": "Article", "headline": "Something else", "url": "https://x.test/other"}),
            ld(**{"@type": "Article", "headline": "This one", "url": "https://x.test/this"}),
        ]
        assert names(page, PageType.ARTICLE, "https://x.test/this") == "This one"

    def test_a_trailing_slash_or_www_does_not_break_the_match(self) -> None:
        page = [
            ld(**{"@type": "Article", "headline": "Other", "url": "https://x.test/other"}),
            ld(**{"@type": "Article", "headline": "This one", "url": "https://www.x.test/this/"}),
        ]
        assert names(page, PageType.ARTICLE, "https://x.test/this") == "This one"

    def test_a_specific_type_beats_the_generic_wrapper(self) -> None:
        """`WebPage.name` is whatever the CMS put in the <title> -- often the site's name.
        It is a last resort, never a competitor."""
        page = [
            ld(**{"@type": "WebPage", "name": "Acme Blog | Acme"}),
            ld(**{"@type": "BlogPosting", "headline": "How we cut our build time"}),
        ]
        assert names(page, PageType.ARTICLE) == "How we cut our build time"

    def test_the_generic_wrapper_is_used_when_nothing_else_matched(self) -> None:
        page = [ld(**{"@type": "WebPage", "name": "How we cut our build time"})]
        assert names(page, PageType.ARTICLE) == "How we cut our build time"

    def test_open_graph_is_not_a_subject(self) -> None:
        """Open Graph has no `@type` to gate on and is written for social previews, where a
        marketing variant of the title is the norm rather than a mistake."""
        assert select_subject([og(**{"og:title": "Buy now!"})], PageType.ARTICLE) == []
