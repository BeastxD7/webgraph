"""Export round-trip and Cypher generation.

The engine deliberately does not depend on a graph database. This module is the seam, so
the property that matters is that nothing is lost across it.
"""

from __future__ import annotations

from webgraph.graph.build import GraphBuilder
from webgraph.graph.export import load_jsonl, to_cypher, to_jsonl, write_jsonl
from webgraph.pipeline import build_document

BASE = "https://example.com/"


def sample_graph():
    builder = GraphBuilder(BASE)
    builder.add(
        build_document(
            '<html><body><h1>Home</h1><p>' + "The widget is a fastener. " * 12
            + '<a href="/pricing">what it costs</a></p>'
            '<script type="application/ld+json">'
            '{"@type":"Organization","name":"Acme","@id":"https://example.com/#org"}'
            "</script></body></html>",
            BASE,
        ),
        anchored_links=[("/pricing", "what it costs")],
    )
    builder.add(
        build_document(
            "<html><body><h1>Plans</h1><p>" + "Team tier is 99 dollars. " * 12
            + "</p></body></html>",
            f"{BASE}pricing",
        )
    )
    return builder.graph


class TestJsonlRoundTrip:
    def test_every_node_and_edge_survives(self, tmp_path) -> None:
        original = sample_graph()
        path = tmp_path / "graph.jsonl"
        write_jsonl(original, path)
        restored = load_jsonl(path)
        assert restored.describe() == original.describe()

    def test_section_text_survives(self, tmp_path) -> None:
        original = sample_graph()
        path = tmp_path / "graph.jsonl"
        write_jsonl(original, path)
        restored = load_jsonl(path)
        for section_id, section in original.sections.items():
            assert restored.sections[section_id].text == section.text

    def test_anchor_text_survives(self, tmp_path) -> None:
        """The anchor is the relation label. Losing it in export would throw away the one
        thing this graph has that an inferred one pays a model for."""
        original = sample_graph()
        path = tmp_path / "graph.jsonl"
        write_jsonl(original, path)
        restored = load_jsonl(path)
        anchors = {a for link in restored.links.values() for a in link.anchors}
        assert "what it costs" in anchors

    def test_root_survives(self, tmp_path) -> None:
        path = tmp_path / "graph.jsonl"
        write_jsonl(sample_graph(), path)
        assert load_jsonl(path).root == BASE

    def test_nodes_precede_their_edges(self) -> None:
        """A loader that streams must never see an edge before both of its endpoints."""
        lines = list(to_jsonl(sample_graph()))
        kinds = [line.split('"kind": "')[1].split('"')[0] for line in lines]
        last_node = max(
            index for index, kind in enumerate(kinds) if kind in {"page", "section", "entity"}
        )
        first_edge = min(
            index
            for index, kind in enumerate(kinds)
            if kind in {"link", "mention", "section_link"}
        )
        assert last_node < first_edge


class TestCypher:
    def test_statements_are_idempotent(self) -> None:
        """A re-crawl must update the graph, not duplicate it."""
        statements = [s for s in to_cypher(sample_graph()) if s.startswith(("MERGE", "MATCH"))]
        assert statements
        assert all("CREATE (" not in s for s in statements)

    def test_schema_is_emitted_first(self) -> None:
        first = next(iter(to_cypher(sample_graph())))
        assert "CREATE NODE TABLE" in first

    def test_apostrophes_cannot_break_a_literal(self) -> None:
        builder = GraphBuilder(BASE)
        builder.add(
            build_document(
                "<html><body><h1>It's a Trap's Trap</h1><p>" + "words " * 40
                + "</p></body></html>",
                BASE,
            )
        )
        assert any("Trap" in s for s in to_cypher(builder.graph))

    def test_section_text_is_omitted_by_default(self) -> None:
        """Bodies are the bulk of the data and are usually better left in the JSONL, with
        the database holding structure and the text fetched by id."""
        without = "\n".join(to_cypher(sample_graph()))
        with_text = "\n".join(to_cypher(sample_graph(), include_text=True))
        assert len(with_text) > len(without)
        assert "fastener" not in without
