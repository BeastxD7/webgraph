"""Joining several crawled sites into one graph.

Measured on the Pallets documentation (Flask, Jinja, Click -- 55 pages between them):
cross-site links went from **1 to 8** once redirecting targets were resolved, with the
anchor text naming each relationship: "Jinja", "Click", "Jinja Template Documentation",
"BaseLoader", "Jinja for loops", "Flask".
"""

from __future__ import annotations

from webgraph.graph.build import GraphBuilder
from webgraph.graph.corpus import Corpus
from webgraph.graph.model import Entity
from webgraph.graph.retrieve import ContextAssembler
from webgraph.pipeline import build_document

A = "https://alpha.test/"
B = "https://beta.test/"


def page(url: str, heading: str, body: str, link: tuple[str, str] | None = None):
    anchor = f'<a href="{link[0]}">{link[1]}</a>' if link else ""
    return build_document(
        f"<html><body><h1>{heading}</h1><p>{body} {anchor}</p></body></html>", url
    )


def two_sites() -> Corpus:
    first = GraphBuilder(A)
    first.add(
        page(A, "Alpha", "Alpha renders templates. " * 12, (f"{B}templates", "Beta templates")),
        anchored_links=[(f"{B}templates", "Beta templates")],
    )
    second = GraphBuilder(B)
    second.add(page(f"{B}templates", "Templates", "Autoescaping is on by default. " * 12))

    corpus = Corpus()
    corpus.add(first.graph)
    corpus.add(second.graph)
    return corpus


class TestCrossSiteLinks:
    def test_an_off_site_link_becomes_an_edge_once_the_target_is_crawled(self) -> None:
        """Off-site is out of scope for crawling, not for the graph."""
        corpus = two_sites()
        edges = corpus.cross_links()
        assert len(edges) == 1
        assert edges[0].source_site == A
        assert edges[0].target_site == B

    def test_the_anchor_labels_the_relationship(self) -> None:
        """The label a graph-inference pipeline pays a model to write, already in the page."""
        assert "Beta templates" in corpus_anchors(two_sites())

    def test_a_single_site_has_no_cross_links(self) -> None:
        corpus = Corpus()
        corpus.add(two_sites().sites[A])
        assert corpus.cross_links() == []

    def test_merging_keeps_every_section(self) -> None:
        corpus = two_sites()
        merged = corpus.merged()
        total = sum(len(g.sections) for g in corpus.sites.values())
        assert len(merged.sections) == total

    def test_merged_graph_works_with_the_ordinary_retriever(self) -> None:
        """`merged()` returns a plain SiteGraph, so nothing downstream knows a corpus exists."""
        assembler = ContextAssembler(two_sites().merged())
        out = assembler.assemble("autoescaping default")
        assert out.sections_full

    def test_a_question_can_cross_the_site_boundary(self) -> None:
        """Seeded on alpha's vocabulary, the context should still reach beta's page."""
        assembler = ContextAssembler(two_sites().merged())
        out = assembler.assemble("alpha renders templates")
        reached = {s.section.page_key for s in out.sections_full}
        assert any("beta.test" in key for key in reached)


class TestAliases:
    def test_an_alias_resolves_to_the_crawled_page(self) -> None:
        """Sites link to the address they publish; a crawl files the page under the address
        it was finally served at."""
        builder = GraphBuilder(A)
        builder.add(
            page(f"{A}en/stable/guide", "Guide", "content " * 40),
            requested_url=f"{A}guide",
        )
        graph = builder.graph
        assert graph.resolve_key("alpha.test/guide") == "alpha.test/en/stable/guide"

    def test_an_unknown_key_resolves_to_nothing(self) -> None:
        assert two_sites().sites[A].resolve_key("alpha.test/nope") is None


class TestSharedEntities:
    def test_the_same_subject_on_two_sites_is_one_entity(self) -> None:
        corpus = two_sites()
        for root in (A, B):
            corpus.sites[root].add_entity(
                Entity(
                    key="Organization:https://acme.test/#org",
                    type="Organization",
                    name="Acme",
                    pages=(root,),
                )
            )
        shared = corpus.shared_entities()
        assert "Organization:https://acme.test/#org" in shared
        assert len(shared["Organization:https://acme.test/#org"]) == 2

    def test_a_generic_name_does_not_establish_identity(self) -> None:
        """"API" appearing on two sites says nothing about them being the same API."""
        corpus = two_sites()
        for root in (A, B):
            corpus.sites[root].add_entity(
                Entity(key="Thing:api", type="Thing", name="API", pages=(root,))
            )
        assert "Thing:api" not in corpus.shared_entities()


class TestUrlHierarchy:
    def test_a_parent_page_is_found_by_path(self) -> None:
        """This edge silently never fired: keys still carried `https://`, so partitioning on
        the first slash produced a host of `https:` and a candidate that matched nothing."""
        builder = GraphBuilder(A)
        builder.add(page(f"{A}docs/", "Docs", "overview " * 40))
        builder.add(page(f"{A}docs/deploy", "Deploy", "deployment " * 40))
        graph = builder.graph
        assert graph.parent_path("alpha.test/docs/deploy") == "alpha.test/docs"

    def test_a_root_page_has_no_parent(self) -> None:
        builder = GraphBuilder(A)
        builder.add(page(A, "Home", "home " * 40))
        assert builder.graph.parent_path("alpha.test") is None


def corpus_anchors(corpus: Corpus) -> set[str]:
    return {anchor for edge in corpus.cross_links() for anchor in edge.anchors}
