"""Site graph construction and budgeted context assembly.

The measured claim these support, at a budget of 3-4% of the site:

| bucket                        | naive | BM25  | graph |
|-------------------------------|-------|-------|-------|
| single-hop (control)          |  7.7% | 100%  | 100%  |
| multi-hop, no lexical overlap |  8.6% |  0.0% | 30.1% |
| multi-hop, weak overlap       | 16.7% | 58.3% |  100% |

BM25 scoring exactly zero on the no-overlap bucket is by construction: those queries share
no rare vocabulary with the answer page, which is the case a similarity search cannot reach
and a link can.
"""

from __future__ import annotations

from webgraph.graph.build import GraphBuilder, sections_from_document
from webgraph.graph.model import SiteGraph
from webgraph.graph.retrieve import Budget, ContextAssembler
from webgraph.pipeline import build_document

BASE = "https://example.com/"


def document(body: str, url: str = BASE):
    return build_document(f"<html><body>{body}</body></html>", url)


class TestSections:
    def test_heading_owns_the_text_below_it(self) -> None:
        sections = sections_from_document(
            document(
                "<h1>Install</h1><p>" + "Run pip install. " * 5 + "</p>"
                "<h1>Usage</h1><p>" + "Import the module. " * 5 + "</p>"
            )
        )
        assert [s.heading for s in sections] == ["Install", "Usage"]
        assert "pip install" in sections[0].text
        assert "pip install" not in sections[1].text

    def test_deeper_heading_becomes_a_child(self) -> None:
        sections = sections_from_document(
            document(
                "<h1>Guide</h1><p>" + "Overview text here. " * 4 + "</p>"
                "<h2>Details</h2><p>" + "Specific detail text. " * 4 + "</p>"
            )
        )
        assert sections[1].parent_id == sections[0].id

    def test_a_sibling_heading_closes_the_deeper_branch(self) -> None:
        """`##` after `###` starts a sibling, not a child of the section that just ended."""
        sections = sections_from_document(
            document(
                "<h1>A</h1><p>" + "aaa " * 20 + "</p>"
                "<h2>B</h2><p>" + "bbb " * 20 + "</p>"
                "<h3>C</h3><p>" + "ccc " * 20 + "</p>"
                "<h2>D</h2><p>" + "ddd " * 20 + "</p>"
            )
        )
        by_heading = {s.heading: s for s in sections}
        assert by_heading["D"].parent_id == by_heading["A"].id

    def test_oversized_section_splits_on_paragraphs(self) -> None:
        big = "".join(f"<p>{'word ' * 200}</p>" for _ in range(12))
        sections = sections_from_document(document(f"<h1>Long</h1>{big}"))
        assert len(sections) > 1
        assert all(s.heading == "Long" for s in sections)

    def test_order_is_preserved(self) -> None:
        sections = sections_from_document(
            document("<h1>One</h1><p>" + "x " * 30 + "</p><h1>Two</h1><p>" + "y " * 30 + "</p>")
        )
        assert [s.order for s in sections] == sorted(s.order for s in sections)


class TestGraphEdges:
    def test_anchor_text_is_kept_on_the_link(self) -> None:
        """The anchor is a human-written label for the target -- the relation label an
        inferred graph would pay a model to invent."""
        builder = GraphBuilder(BASE)
        builder.add(
            document('<h1>Home</h1><p>' + "text " * 30 + '<a href="/pricing">See pricing</a></p>'),
            anchored_links=[("/pricing", "See pricing")],
        )
        link = next(iter(builder.graph.links.values()))
        assert "See pricing" in link.anchors

    def test_off_site_links_are_not_edges(self) -> None:
        builder = GraphBuilder(BASE)
        builder.add(
            document("<h1>Home</h1><p>" + "text " * 30 + "</p>"),
            anchored_links=[("https://elsewhere.test/x", "Elsewhere")],
        )
        assert builder.graph.links == {}

    def test_link_specificity_discounts_navigation(self) -> None:
        """A target linked from every page is navigation; one linked from a few is a topic.

        The same cross-page insight as chrome detection, applied to edges instead of text.
        """
        graph = SiteGraph(root=BASE)
        from webgraph.graph.model import PageNode

        for index in range(10):
            key = f"example.com/p{index}"
            graph.add_page(PageNode(key=key, url=f"{BASE}p{index}", title=f"P{index}", depth=1, chars=100))
        graph.add_page(PageNode(key="example.com/nav", url=f"{BASE}nav", title="Nav", depth=1, chars=100))
        graph.add_page(PageNode(key="example.com/topic", url=f"{BASE}topic", title="Topic", depth=1, chars=100))

        for index in range(10):
            graph.add_link(f"example.com/p{index}", "example.com/nav")
        graph.add_link("example.com/p0", "example.com/topic")

        assert graph.link_specificity("example.com/topic") > graph.link_specificity(
            "example.com/nav"
        )

    def test_section_level_links_are_recorded(self) -> None:
        """A link inside the matching paragraph is the one a reader would have clicked;
        a link elsewhere on the page is a much weaker claim."""
        builder = GraphBuilder(BASE)
        sections = builder.add(
            document(
                "<h1>Guide</h1><p>" + "words " * 30
                + '<a href="/deploy">deployment guide</a></p>'
            ),
            anchored_links=[("/deploy", "deployment guide")],
        )
        assert any(builder.graph.section_links.get(s.id) for s in sections)


class TestAssembly:
    def build(self) -> ContextAssembler:
        builder = GraphBuilder(BASE)
        builder.add(
            document(
                "<h1>Widgets</h1><p>" + "The widget is a fastener. " * 12
                + '<a href="/pricing">what it costs</a></p>',
                url=BASE,
            ),
            anchored_links=[("/pricing", "what it costs")],
        )
        builder.add(
            document(
                "<h1>Plans</h1><p>" + "Team tier is 99 dollars monthly. " * 12 + "</p>",
                url=f"{BASE}pricing",
            ),
        )
        builder.add(
            document(
                "<h1>Careers</h1><p>" + "We are hiring engineers in Berlin. " * 12 + "</p>",
                url=f"{BASE}careers",
            ),
        )
        return ContextAssembler(builder.graph)

    def test_lexical_seeding_finds_the_obvious_page(self) -> None:
        assembler = self.build()
        seeds = assembler.score_sections("hiring engineers Berlin")
        assert seeds
        assert "careers" in seeds[0].section.page_key

    def test_expansion_reaches_a_linked_page_with_no_shared_vocabulary(self) -> None:
        """The whole point: 'fastener' appears only on the widgets page, and the pricing page
        never says it. A similarity search cannot get there; a link can."""
        assembler = self.build()
        out = assembler.assemble("widget fastener")
        reached = {s.section.page_key for s in out.sections_full}
        assert any("pricing" in key for key in reached)

    def test_unrelated_page_is_not_pulled_in_by_expansion(self) -> None:
        assembler = self.build()
        out = assembler.assemble("widget fastener")
        full = {s.section.page_key for s in out.sections_full}
        assert not any("careers" in key for key in full)

    def test_context_stays_within_budget(self) -> None:
        assembler = self.build()
        out = assembler.assemble("widget fastener", budget=Budget(max_chars=2_000))
        assert len(out.text) <= 2_000 * 1.5  # the map tier is capped by entries, not chars

    def test_omitted_pages_are_still_named(self) -> None:
        """A truncated context must not lie by omission: whatever was cut is still listed
        with its address, so an agent can ask for it."""
        assembler = self.build()
        out = assembler.assemble("hiring engineers Berlin", budget=Budget(max_chars=1_500))
        assert "Other pages on this site" in out.text

    def test_every_included_section_carries_its_source(self) -> None:
        assembler = self.build()
        out = assembler.assemble("widget fastener")
        for item in out.sections_full:
            assert item.section.page_key in out.text or item.reason in out.text

    def test_empty_query_returns_a_map_not_a_crash(self) -> None:
        assembler = self.build()
        out = assembler.assemble("")
        assert out.sections_full == []
        assert "Other pages on this site" in out.text


class TestScoringChoices:
    """Both of these were measured, and both times the obvious implementation lost."""

    def test_evidence_accumulates_across_paths(self) -> None:
        """A section reached from two seeds should outrank one reached from a single seed of
        equal strength. Keeping the maximum instead throws that away."""
        builder = GraphBuilder(BASE)
        builder.add(
            document("<h1>A</h1><p>" + "alpha topic here. " * 15 + '<a href="/t">t</a></p>'),
            anchored_links=[("/t", "t")],
        )
        builder.add(
            document("<h1>B</h1><p>" + "alpha topic here. " * 15 + '<a href="/t">t</a></p>',
                     url=f"{BASE}b"),
            anchored_links=[("/t", "t")],
        )
        builder.add(document("<h1>T</h1><p>" + "unrelated words entirely. " * 15 + "</p>",
                             url=f"{BASE}t"))
        assembler = ContextAssembler(builder.graph)
        seeds = assembler.score_sections("alpha topic")
        summed = {s.section.id: s.score for s in assembler.expand(seeds, "alpha topic")}
        maxed = {
            s.section.id: s.score
            for s in assembler.expand(seeds, "alpha topic", accumulate=False)
        }
        target = next(i for i in summed if "/t#" in i or i.startswith("example.com/t"))
        assert summed[target] >= maxed[target]

    def test_propagation_is_mass_conserving(self) -> None:
        """A seed spreads a fixed amount of evidence rather than handing every neighbour a
        full copy of its score.

        Unnormalised, a page linked from everywhere collects a little from every seed and
        outranks the page that answers the question -- measured at 10-17 points of lost
        recall on the realistic case.
        """
        assembler = ContextAssembler(GraphBuilder(BASE).graph)
        assert assembler.expand([], "anything") == []
