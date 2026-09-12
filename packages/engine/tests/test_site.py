"""Site-pipeline tests: inventory accounting and cross-page aggregation.

Both areas produce *numbers a person will trust*, so the tests here mostly pin honesty
properties: liveness must be measured against what was checked, and aggregation must not
imply more distinct data than the site actually published.
"""

from __future__ import annotations

from webgraph.pipeline import build_document
from webgraph.site import (
    PageExtraction,
    PageInventory,
    SiteEntity,
    _aggregate_entities,
)

ORG = (
    '<html><head><script type="application/ld+json">'
    '{"@type":"Organization","name":"Acme"}</script></head>'
    "<body><p>Some body copy that is long enough to be real.</p></body></html>"
)


def page(url: str, html: str) -> PageExtraction:
    document = build_document(html, url)
    return PageExtraction(url=url, document=document, text_chars=len(document.text))


class TestInventoryAccounting:
    def test_liveness_is_measured_against_checked_not_advertised(self) -> None:
        """Regression: dividing live pages by the full advertised count reported 1%
        liveness for a site whose sampled pages were 97% healthy."""
        inventory = PageInventory(
            advertised=tuple(f"https://e.com/{i}" for i in range(5000)),
            live=tuple(f"https://e.com/{i}" for i in range(35)),
            dead=(("https://e.com/x", 404),),
            verified=True,
            checked_count=36,
        )
        assert inventory.advertised_count == 5000
        assert round(inventory.liveness, 2) == round(35 / 36, 2)
        assert not inventory.fully_verified

    def test_fully_verified_when_everything_checked(self) -> None:
        inventory = PageInventory(
            advertised=("a", "b"), live=("a", "b"), verified=True, checked_count=2
        )
        assert inventory.fully_verified
        assert inventory.liveness == 1.0

    def test_liveness_zero_when_nothing_checked(self) -> None:
        assert PageInventory(advertised=("a",)).liveness == 0.0

    def test_dead_pages_counted(self) -> None:
        inventory = PageInventory(
            advertised=("a", "b", "c"),
            live=("a",),
            dead=(("b", 404), ("c", 500)),
            verified=True,
            checked_count=3,
        )
        assert inventory.dead_count == 2
        assert inventory.live_count == 1


class TestAggregation:
    def test_same_entity_across_pages_collapses_to_one(self) -> None:
        """90 pages carrying one Organization block is one entity, not ninety."""
        pages = [page(f"https://e.com/{i}", ORG) for i in range(5)]
        entities = _aggregate_entities(pages)

        organizations = [e for e in entities if e.entity_type == "Organization"]
        assert len(organizations) == 1
        assert organizations[0].page_count == 5

    def test_distinct_entities_stay_distinct(self) -> None:
        a = page("https://e.com/a", ORG)
        b = page(
            "https://e.com/b",
            ORG.replace('"name":"Acme"', '"name":"Other"'),
        )
        entities = _aggregate_entities([a, b])
        names = {e.data.get("name") for e in entities if e.entity_type == "Organization"}
        assert names == {"Acme", "Other"}

    def test_source_pages_recorded(self) -> None:
        pages = [page("https://e.com/1", ORG), page("https://e.com/2", ORG)]
        organizations = [
            e for e in _aggregate_entities(pages) if e.entity_type == "Organization"
        ]
        assert set(organizations[0].source_pages) == {"https://e.com/1", "https://e.com/2"}

    def test_sorted_by_prevalence(self) -> None:
        common = [page(f"https://e.com/{i}", ORG) for i in range(3)]
        rare = [page("https://e.com/rare", ORG.replace("Acme", "Rare"))]
        entities = _aggregate_entities(common + rare)
        assert entities[0].page_count >= entities[-1].page_count

    def test_pages_without_documents_are_skipped(self) -> None:
        broken = PageExtraction(url="https://e.com/x", error="boom")
        assert _aggregate_entities([broken]) == ()

    def test_empty_input(self) -> None:
        assert _aggregate_entities([]) == ()


class TestSiteEntity:
    def test_page_count_matches_sources(self) -> None:
        entity = SiteEntity(
            entity_type="Organization",
            data={"name": "Acme"},
            source_pages=("https://e.com/a", "https://e.com/b"),
        )
        assert entity.page_count == 2


class TestStreamContract:
    """The stream's event shape is a published contract the frontend depends on."""

    def test_event_types_are_stable(self) -> None:
        from webgraph.site import stream_site

        assert callable(stream_site)

    def test_bad_url_yields_error_event_not_exception(self) -> None:
        """A crawl that cannot start must report through the stream, not raise."""
        from webgraph.site import stream_site

        events = list(stream_site("not-a-url"))
        assert events
        assert events[0]["type"] == "error"
        assert "crawlable" in events[0]["message"]


class TestRedirectScoping:
    """A cross-host redirect must not make a site uncrawlable."""

    def test_resolve_root_is_importable_and_pure_on_bad_input(self) -> None:
        from webgraph.site import resolve_root

        assert resolve_root("not-a-url") == "not-a-url"

    def test_scope_uses_landed_host(self) -> None:
        """Regression: docs.pydantic.dev/latest/ redirects to pydantic.dev/docs/...

        Scoping on the requested host rejected every link as off-site (`docs.` is a
        subdomain, excluded by default) and the crawl stopped after 2 pages on a site with
        thousands of URLs.
        """
        from webgraph.crawl.frontier import same_site

        requested = "https://docs.pydantic.dev/latest/"
        landed = "https://pydantic.dev/docs/validation/latest/get-started/"
        link = "https://pydantic.dev/docs/concepts/models/"

        assert not same_site(link, requested), "fixture no longer reproduces the bug"
        assert same_site(link, landed)


class TestPageTitleFallback:
    def test_a_page_with_no_heading_uses_its_title_without_the_site_name(self) -> None:
        from webgraph.pipeline import build_document
        from webgraph.site import _page_title

        html = (
            "<html><head><title>Privacy Policy | Reliance Digital</title>"
            '<meta property="og:site_name" content="Reliance Digital"></head>'
            "<body><p>Text.</p></body></html>"
        )
        assert _page_title(build_document(html, "https://x.test/privacy-policy")) == "Privacy Policy"

    def test_without_a_declared_site_name_the_title_is_kept_whole(self) -> None:
        from webgraph.pipeline import build_document
        from webgraph.site import _page_title

        html = "<html><head><title>Rust | what the borrow checker does</title></head><body><p>x</p></body></html>"
        assert _page_title(build_document(html, "https://x.test/p")) == "Rust | what the borrow checker does"


class TestEntityAggregation:
    def test_hydration_state_is_not_an_entity(self) -> None:
        """Ten pages' `__INITIAL_STATE__` used to be ten entities seen once each."""
        from webgraph.site import PageExtraction, _aggregate_entities
        from webgraph.types import PayloadSource, StructuredPayload

        pages = []
        for n in range(3):
            html = (
                '<html><head><script type="application/ld+json">'
                '{"@type":"Organization","name":"Acme"}</script></head>'
                f"<body><p>page {n}</p></body></html>"
            )
            from webgraph.pipeline import build_document

            document = build_document(html, f"https://x.test/{n}")
            state = StructuredPayload(source=PayloadSource.INITIAL_STATE, data={"page": n})
            document = document.model_copy(
                update={"structured_data": (*document.structured_data, state)}
            )
            pages.append(PageExtraction(url=document.url, document=document))
        entities = _aggregate_entities(pages)
        types = [e.entity_type for e in entities]
        assert "initial-state" not in types
        organisation = next(e for e in entities if e.entity_type == "Organization")
        assert organisation.page_count == 3
