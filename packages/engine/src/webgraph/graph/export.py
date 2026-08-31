"""Write a site graph out for a graph database, or read it back.

Why the engine does not depend on a database
--------------------------------------------
Embedded property-graph stores -- Kuzu, and Neo4j at the other end of the weight scale --
are useful and neither is a dependency here. Binding the engine to one would mean its schema
lived in that vendor's dialect, its install carried that vendor's wheels, and its tests
needed a running server to say anything about extraction. The graph is built in memory,
which is fine for any site a laptop can crawl (2,000 pages is roughly 20,000 sections), and
this module is the seam.

Two formats, for two jobs
-------------------------
- **JSONL** round-trips: one object per line, typed by a `kind` field. Streamable, diffable,
  and loadable by anything.
- **Cypher** is for loading into Kuzu or Neo4j. Emitted as parameterised `MERGE` statements
  so a re-import is idempotent and a partial import can be resumed.

`MERGE` rather than `CREATE` throughout: a crawl re-run must update a graph, not duplicate it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from webgraph.graph.model import Entity, PageNode, Section, SiteGraph

__all__ = ["CYPHER_SCHEMA", "load_jsonl", "to_cypher", "to_jsonl", "write_jsonl"]

CYPHER_SCHEMA = """\
// webgraph site graph -- schema
// Kuzu requires an explicit schema; Neo4j ignores these and infers from the data.
CREATE NODE TABLE IF NOT EXISTS Page(
    key STRING, url STRING, title STRING, depth INT64, chars INT64,
    content_hash STRING, PRIMARY KEY (key));
CREATE NODE TABLE IF NOT EXISTS Section(
    id STRING, page_key STRING, heading STRING, level INT64, ord INT64,
    chars INT64, text STRING, PRIMARY KEY (id));
CREATE NODE TABLE IF NOT EXISTS Entity(
    key STRING, type STRING, name STRING, data STRING, PRIMARY KEY (key));

CREATE REL TABLE IF NOT EXISTS LINKS_TO(FROM Page TO Page, anchors STRING, count INT64);
CREATE REL TABLE IF NOT EXISTS HAS_SECTION(FROM Page TO Section, ord INT64);
CREATE REL TABLE IF NOT EXISTS PARENT_OF(FROM Section TO Section);
CREATE REL TABLE IF NOT EXISTS MENTIONS(FROM Section TO Entity);
CREATE REL TABLE IF NOT EXISTS DESCRIBES(FROM Page TO Entity);
CREATE REL TABLE IF NOT EXISTS SECTION_LINKS_TO(FROM Section TO Page);
"""


def to_jsonl(graph: SiteGraph) -> Iterator[str]:
    """One JSON object per line. Nodes precede the edges that reference them."""
    yield json.dumps({"kind": "site", "root": graph.root, **graph.describe()})

    for page in graph.pages.values():
        yield json.dumps(
            {
                "kind": "page",
                "key": page.key,
                "url": page.url,
                "title": page.title,
                "depth": page.depth,
                "chars": page.chars,
                "content_hash": page.content_hash,
                "sections": list(page.section_ids),
            }
        )

    for section in graph.sections.values():
        yield json.dumps(
            {
                "kind": "section",
                "id": section.id,
                "page_key": section.page_key,
                "order": section.order,
                "heading": section.heading,
                "level": section.level,
                "parent_id": section.parent_id,
                "text": section.text,
            }
        )

    for entity in graph.entities.values():
        yield json.dumps(
            {
                "kind": "entity",
                "key": entity.key,
                "type": entity.type,
                "name": entity.name,
                "pages": list(entity.pages),
                "data": entity.data,
            }
        )

    for link in graph.links.values():
        yield json.dumps(
            {
                "kind": "link",
                "source": link.source,
                "target": link.target,
                "anchors": list(link.anchors),
                "count": link.count,
            }
        )

    for section_id_, entity_keys in graph.mentions.items():
        for entity_key in sorted(entity_keys):
            yield json.dumps(
                {"kind": "mention", "section": section_id_, "entity": entity_key}
            )

    for section_id_, targets in graph.section_links.items():
        for target in sorted(targets):
            yield json.dumps(
                {"kind": "section_link", "section": section_id_, "target": target}
            )


def write_jsonl(graph: SiteGraph, path: str | Path) -> int:
    """Write the graph to `path`. Returns the number of lines written."""
    written = 0
    with Path(path).open("w", encoding="utf-8") as handle:
        for line in to_jsonl(graph):
            handle.write(line + "\n")
            written += 1
    return written


def load_jsonl(path: str | Path) -> SiteGraph:
    """Read a graph back. The inverse of `write_jsonl`."""
    graph = SiteGraph()
    pending_sections: list[dict[str, Any]] = []

    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            kind = record.get("kind")
            if kind == "site":
                graph.root = str(record.get("root", ""))
            elif kind == "page":
                graph.add_page(
                    PageNode(
                        key=record["key"],
                        url=record["url"],
                        title=record["title"],
                        depth=int(record["depth"]),
                        chars=int(record["chars"]),
                        section_ids=tuple(record.get("sections", ())),
                        content_hash=record.get("content_hash", ""),
                    )
                )
            elif kind == "section":
                pending_sections.append(record)
            elif kind == "entity":
                graph.add_entity(
                    Entity(
                        key=record["key"],
                        type=record["type"],
                        name=record.get("name", ""),
                        data=record.get("data") or {},
                        pages=tuple(record.get("pages", ())),
                    )
                )
            elif kind == "link":
                for anchor in record.get("anchors") or [""]:
                    graph.add_link(record["source"], record["target"], anchor)
            elif kind == "mention":
                graph.add_mention(record["section"], record["entity"])
            elif kind == "section_link":
                graph.add_section_link(record["section"], record["target"])

    for record in pending_sections:
        graph.add_section(
            Section(
                id=record["id"],
                page_key=record["page_key"],
                order=int(record["order"]),
                heading=record.get("heading", ""),
                level=int(record.get("level", 0)),
                text=record.get("text", ""),
                parent_id=record.get("parent_id"),
            )
        )
    return graph


def to_cypher(graph: SiteGraph, *, include_text: bool = False) -> Iterator[str]:
    """Parameterised `MERGE` statements for Kuzu or Neo4j.

    `include_text` is off by default. Section bodies are the bulk of the data and are
    frequently better left in the JSONL, with the database holding structure and the text
    fetched by id.
    """
    yield CYPHER_SCHEMA

    for page in graph.pages.values():
        yield (
            f"MERGE (p:Page {{key: {_q(page.key)}}}) SET p.url = {_q(page.url)}, "
            f"p.title = {_q(page.title)}, p.depth = {page.depth}, p.chars = {page.chars}, "
            f"p.content_hash = {_q(page.content_hash)};"
        )

    for section in graph.sections.values():
        text = _q(section.text) if include_text else "''"
        yield (
            f"MERGE (s:Section {{id: {_q(section.id)}}}) "
            f"SET s.page_key = {_q(section.page_key)}, s.heading = {_q(section.heading)}, "
            f"s.level = {section.level}, s.ord = {section.order}, "
            f"s.chars = {section.chars}, s.text = {text};"
        )
        yield (
            f"MATCH (p:Page {{key: {_q(section.page_key)}}}), "
            f"(s:Section {{id: {_q(section.id)}}}) "
            f"MERGE (p)-[r:HAS_SECTION]->(s) SET r.ord = {section.order};"
        )
        if section.parent_id:
            yield (
                f"MATCH (a:Section {{id: {_q(section.parent_id)}}}), "
                f"(b:Section {{id: {_q(section.id)}}}) MERGE (a)-[:PARENT_OF]->(b);"
            )

    for entity in graph.entities.values():
        yield (
            f"MERGE (e:Entity {{key: {_q(entity.key)}}}) SET e.type = {_q(entity.type)}, "
            f"e.name = {_q(entity.name)}, e.data = {_q(json.dumps(entity.data)[:4000])};"
        )
        for page_key in entity.pages:
            yield (
                f"MATCH (p:Page {{key: {_q(page_key)}}}), "
                f"(e:Entity {{key: {_q(entity.key)}}}) MERGE (p)-[:DESCRIBES]->(e);"
            )

    for link in graph.links.values():
        yield (
            f"MATCH (a:Page {{key: {_q(link.source)}}}), "
            f"(b:Page {{key: {_q(link.target)}}}) MERGE (a)-[r:LINKS_TO]->(b) "
            f"SET r.anchors = {_q(' | '.join(link.anchors))}, r.count = {link.count};"
        )

    for section_id_, entity_keys in graph.mentions.items():
        for entity_key in sorted(entity_keys):
            yield (
                f"MATCH (s:Section {{id: {_q(section_id_)}}}), "
                f"(e:Entity {{key: {_q(entity_key)}}}) MERGE (s)-[:MENTIONS]->(e);"
            )

    for section_id_, targets in graph.section_links.items():
        for target in sorted(targets):
            yield (
                f"MATCH (s:Section {{id: {_q(section_id_)}}}), "
                f"(p:Page {{key: {_q(target)}}}) MERGE (s)-[:SECTION_LINKS_TO]->(p);"
            )


def _q(value: str) -> str:
    """Single-quoted Cypher string literal.

    `json.dumps` handles the escaping and produces a double-quoted literal, which Cypher
    also accepts -- and which cannot be broken by an apostrophe in a page title.
    """
    return json.dumps(value or "")
