"""Change detection between two crawls.

Every piece was built for something else: the content hash for deduplication, the graph
store for restarts, heading-scoped sections for retrieval. This is the three put together.
"""

from __future__ import annotations

from webgraph.graph.build import GraphBuilder
from webgraph.graph.diff import diff_graphs
from webgraph.pipeline import build_document

BASE = "https://example.com/"


def graph_of(pages: dict[str, str]):
    builder = GraphBuilder(BASE)
    for url, body in pages.items():
        builder.add(build_document(f"<html><body>{body}</body></html>", url))
    return builder.graph


HOME = "<h1>Home</h1><p>" + "The widget is a fastener. " * 12 + "</p>"
PRICING = "<h1>Pricing</h1><p>" + "Team tier is 99 dollars. " * 12 + "</p>"


class TestPageLevel:
    def test_identical_crawls_report_nothing(self) -> None:
        pages = {BASE: HOME, f"{BASE}p": PRICING}
        result = diff_graphs(graph_of(pages), graph_of(pages))
        assert not result.any_change
        assert result.unchanged == 2

    def test_a_new_page_is_added(self) -> None:
        result = diff_graphs(
            graph_of({BASE: HOME}), graph_of({BASE: HOME, f"{BASE}p": PRICING})
        )
        assert [page.url for page in result.added] == [f"{BASE}p"]

    def test_a_missing_page_is_removed(self) -> None:
        result = diff_graphs(
            graph_of({BASE: HOME, f"{BASE}p": PRICING}), graph_of({BASE: HOME})
        )
        assert [page.url for page in result.removed] == [f"{BASE}p"]

    def test_a_trailing_slash_is_not_a_change(self) -> None:
        """Matching on canonical key, so a URL that gained a slash is one page, not a
        removal and an addition."""
        result = diff_graphs(graph_of({BASE: HOME}), graph_of({"https://example.com": HOME}))
        assert not result.added
        assert not result.removed


class TestSectionLevel:
    def test_an_edited_section_is_named(self) -> None:
        """Knowing a page changed is nearly useless on a page of any size."""
        before = graph_of({BASE: HOME + PRICING})
        after = graph_of(
            {BASE: HOME + "<h1>Pricing</h1><p>" + "Team tier is 149 dollars. " * 12 + "</p>"}
        )
        result = diff_graphs(before, after)
        assert len(result.changed) == 1
        edited = [c for c in result.changed[0].sections if c.kind == "edited"]
        assert [c.heading for c in edited] == ["Pricing"]

    def test_an_inserted_section_does_not_mark_the_rest_as_changed(self) -> None:
        """Matching on position turns a one-paragraph addition into 'the whole page changed'."""
        before = graph_of({BASE: HOME + PRICING})
        after = graph_of(
            {BASE: HOME + "<h1>News</h1><p>" + "Fresh announcement. " * 12 + "</p>" + PRICING}
        )
        result = diff_graphs(before, after)
        kinds = [c.kind for c in result.changed[0].sections]
        assert kinds == ["added"]

    def test_a_removed_section_is_reported(self) -> None:
        result = diff_graphs(graph_of({BASE: HOME + PRICING}), graph_of({BASE: HOME}))
        removed = [c for c in result.changed[0].sections if c.kind == "removed"]
        assert [c.heading for c in removed] == ["Pricing"]

    def test_whitespace_only_differences_are_not_changes(self) -> None:
        before = graph_of({BASE: HOME})
        after = graph_of({BASE: HOME.replace(" ", "  ")})
        result = diff_graphs(before, after)
        assert not result.changed

    def test_the_biggest_change_is_reported_first(self) -> None:
        before = graph_of({BASE: HOME, f"{BASE}p": PRICING})
        after = graph_of(
            {
                BASE: HOME + "<h2>Note</h2><p>" + "tiny. " * 10 + "</p>",
                f"{BASE}p": PRICING + "<h2>Extra</h2><p>" + "much more text here. " * 60 + "</p>",
            }
        )
        result = diff_graphs(before, after)
        assert result.changed[0].url == f"{BASE}p"


class TestSummary:
    def test_no_change_says_so(self) -> None:
        pages = {BASE: HOME}
        assert "No change" in diff_graphs(graph_of(pages), graph_of(pages)).summary()

    def test_counts_appear_in_the_summary(self) -> None:
        result = diff_graphs(
            graph_of({BASE: HOME, f"{BASE}old": PRICING}),
            graph_of({BASE: HOME, f"{BASE}new": PRICING}),
        )
        summary = result.summary()
        assert "1 new" in summary
        assert "1 gone" in summary
