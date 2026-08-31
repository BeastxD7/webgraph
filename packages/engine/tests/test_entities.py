"""Deriving entities for sites that publish no structured data.

Recorded outcome, because it is mostly negative: the derivation produces entities and
mentions where there were none (0 -> 31..75 entities, 0 -> 115..473 mentions across attrs,
pytest, Flask, Jinja and Click), but on documentation corpora it does not improve within-site
retrieval (neutral at every mention weight from 0.0 to 0.7) and produces no cross-site
bridges (shared entities: zero). It is kept as a descriptive feature.
"""

from __future__ import annotations

from webgraph.graph.build import GraphBuilder
from webgraph.graph.entities import derive_code_symbols, derive_entities, derive_page_subjects
from webgraph.pipeline import build_document

BASE = "https://example.com/"


def builder_with(pages: list[tuple[str, str, list[tuple[str, str]]]]) -> GraphBuilder:
    builder = GraphBuilder(BASE)
    for url, body, links in pages:
        anchors = "".join(f'<a href="{href}">{text}</a> ' for href, text in links)
        builder.add(
            build_document(f"<html><body>{body}{anchors}</body></html>", url),
            anchored_links=links,
        )
    return builder


class TestPageSubjects:
    def test_a_page_is_named_by_what_other_pages_call_it(self) -> None:
        """The anchor texts pointing at a page are the site's own name for its subject --
        the label an inference pipeline pays a model to write."""
        builder = builder_with(
            [
                (BASE, "<h1>Home</h1><p>" + "intro " * 40 + "</p>", [("/tpl", "Templating")]),
                (f"{BASE}a", "<h1>A</h1><p>" + "words " * 40 + "</p>", [("/tpl", "Templating")]),
                (f"{BASE}tpl", "<h1>Tpl</h1><p>" + "render " * 40 + "</p>", []),
            ]
        )
        assert derive_page_subjects(builder.graph) == 1
        entity = next(iter(builder.graph.entities.values()))
        assert entity.name == "Templating"

    def test_one_page_agreeing_with_itself_is_not_agreement(self) -> None:
        builder = builder_with(
            [
                (BASE, "<h1>Home</h1><p>" + "intro " * 40 + "</p>", [("/tpl", "Templating")]),
                (f"{BASE}tpl", "<h1>Tpl</h1><p>" + "render " * 40 + "</p>", []),
            ]
        )
        assert derive_page_subjects(builder.graph) == 0

    def test_anchors_that_name_the_act_of_linking_are_ignored(self) -> None:
        """"click here" describes the link, not the target."""
        builder = builder_with(
            [
                (BASE, "<h1>Home</h1><p>" + "intro " * 40 + "</p>", [("/tpl", "click here")]),
                (f"{BASE}a", "<h1>A</h1><p>" + "words " * 40 + "</p>", [("/tpl", "read more")]),
                (f"{BASE}tpl", "<h1>Tpl</h1><p>" + "render " * 40 + "</p>", []),
            ]
        )
        assert derive_page_subjects(builder.graph) == 0

    def test_a_name_used_everywhere_produces_no_mentions(self) -> None:
        """An entity every section names connects everything to everything, which connects
        nothing."""
        pages = [
            (f"{BASE}p{i}", f"<h1>P{i}</h1><p>Widget " + "text " * 40 + "</p>", [("/w", "Widget")])
            for i in range(6)
        ]
        pages.append((f"{BASE}w", "<h1>W</h1><p>" + "about " * 40 + "</p>", []))
        builder = builder_with(pages)
        derive_page_subjects(builder.graph)
        assert sum(len(v) for v in builder.graph.mentions.values()) == 0


class TestCodeSymbols:
    def test_a_heading_used_as_code_elsewhere_is_a_symbol(self) -> None:
        """Two independent pieces of evidence, not a guess about capitalisation:
        `Environment` is a class because the site also writes it in backticks."""
        builder = builder_with(
            [
                (
                    f"{BASE}api",
                    "<h1>Environment</h1><p>" + "The environment object. " * 12 + "</p>",
                    [],
                ),
                (
                    f"{BASE}guide",
                    "<h1>Guide</h1><p>Create an <code>Environment</code> first. "
                    + "text " * 30
                    + " Configure <code>Environment</code> options.</p>",
                    [],
                ),
            ]
        )
        assert derive_code_symbols(builder.graph) == 1
        assert "Symbol:Environment" in builder.graph.entities

    def test_an_ordinary_heading_is_not_a_symbol(self) -> None:
        builder = builder_with(
            [
                (f"{BASE}i", "<h1>Installation</h1><p>" + "install " * 40 + "</p>", []),
                (f"{BASE}g", "<h1>Guide</h1><p>" + "words " * 40 + "</p>", []),
            ]
        )
        assert derive_code_symbols(builder.graph) == 0

    def test_underscored_and_dotted_names_need_no_corroboration(self) -> None:
        builder = builder_with(
            [
                (f"{BASE}api", "<h1>render_template</h1><p>" + "renders " * 30 + "</p>", []),
                (f"{BASE}g", "<h1>Guide</h1><p>Call <code>render_template</code> now. "
                 + "text " * 30 + "</p>", []),
            ]
        )
        assert "Symbol:render_template" in builder.graph.entities or derive_code_symbols(
            builder.graph
        ) >= 1


class TestDeriveEntities:
    def test_running_twice_is_idempotent(self) -> None:
        builder = builder_with(
            [
                (BASE, "<h1>Home</h1><p>" + "intro " * 40 + "</p>", [("/tpl", "Templating")]),
                (f"{BASE}a", "<h1>A</h1><p>" + "words " * 40 + "</p>", [("/tpl", "Templating")]),
                (f"{BASE}tpl", "<h1>Tpl</h1><p>" + "render " * 40 + "</p>", []),
            ]
        )
        derive_entities(builder.graph)
        first = builder.graph.describe()
        derive_entities(builder.graph)
        assert builder.graph.describe() == first


class TestFragmentAnchors:
    """A link to a fragment names the section it points at, not the page.

    `/api/#jinja2.Undefined` and `/api/` land on the same edge once the fragment is stripped
    -- right for expansion, since the section is on that page either way, and wrong for
    naming the page's subject. Live output read "Environment, also called Undefined".
    """

    def test_fragment_anchors_do_not_name_the_page(self) -> None:
        builder = GraphBuilder(BASE)
        for source in ("a", "b"):
            builder.add(
                build_document(
                    f'<html><body><h1>{source}</h1><p>{"text " * 40}'
                    '<a href="/api/#Undefined">Undefined</a></p></body></html>',
                    f"{BASE}{source}",
                ),
                anchored_links=[("/api/#Undefined", "Undefined")],
            )
        builder.add(
            build_document(
                "<html><body><h1>API</h1><p>" + "docs " * 40 + "</p></body></html>",
                f"{BASE}api/",
            )
        )
        derive_page_subjects(builder.graph)
        assert "Undefined" not in {e.name for e in builder.graph.entities.values()}

    def test_a_fragment_link_is_still_an_edge(self) -> None:
        """Only the naming changes; expansion still needs the link."""
        builder = GraphBuilder(BASE)
        builder.add(
            build_document(
                "<html><body><h1>Home</h1><p>" + "text " * 40
                + '<a href="/api/#X">X</a></p></body></html>',
                BASE,
            ),
            anchored_links=[("/api/#X", "X")],
        )
        link = next(iter(builder.graph.links.values()))
        assert link.anchors == ("X",)
        assert link.page_anchors == ()
