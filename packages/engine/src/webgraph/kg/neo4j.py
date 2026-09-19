"""Push a site's knowledge graph into Neo4j (or anything that speaks bolt and Cypher).

The driver is an optional extra (`pip install "webgraph[kg-neo4j]"`), imported inside the
function that needs it. `plan_batches` is pure: it yields `(cypher, rows)` pairs, so the
statements are testable without a server, and `sync_to_neo4j` is a thin loop that runs them
through whatever `run(cypher, rows)` callable it is given -- the driver's session by default.

Shape: `UNWIND $rows AS r MERGE (...) SET ... += r.props` in batches of 1,000, idempotent on
`id`, constraints first. That is the one sync path that works on Aura (`LOAD CSV` and
`apoc.import.json` do not). No APOC anywhere, so Memgraph and FalkorDB accept the same
statements.

Relationships: `(:Entity)-[:RELATED {predicate, fact, weight, confidence, evidence_ids}]->
(:Entity)` is the portable default -- relation evidence is a list property because a
relationship cannot be the target of another. `typed_edges=True` adds `-[:PREDICATE]->`
edges as well, for servers that are happy with many relationship types. Provenance:
`(:Entity)-[:MENTIONED_IN {surface}]->(:Evidence)-[:IN_SECTION]->(:Section)-[:ON_PAGE]->
(:Page)`, and `(:Entity)-[:HAS_ATTRIBUTE {key, value, unit}]->(:Evidence)`.

The database is a push target, never the source of truth: Aura Free auto-pauses after 72
hours idle and is deleted after 30 days paused, and the SQLite file rebuilds it in seconds.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, Final

from webgraph.kg.store import KGStore

__all__ = ["BATCH_SIZE", "CONSTRAINTS", "Neo4jUnavailableError", "plan_batches", "sync_to_neo4j"]

BATCH_SIZE: Final[int] = 1000

CONSTRAINTS: Final[tuple[str, ...]] = (
    "CREATE CONSTRAINT kg_entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT kg_evidence_id IF NOT EXISTS FOR (v:Evidence) REQUIRE v.id IS UNIQUE",
    "CREATE CONSTRAINT kg_page_key IF NOT EXISTS FOR (p:Page) REQUIRE p.key IS UNIQUE",
    "CREATE CONSTRAINT kg_section_id IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE",
)

_PAGES = "UNWIND $rows AS r MERGE (p:Page {key: r.key}) SET p.url = r.url"
_SECTIONS = (
    "UNWIND $rows AS r MERGE (s:Section {id: r.id}) "
    "WITH s, r MATCH (p:Page {key: r.page_key}) MERGE (s)-[:ON_PAGE]->(p)"
)
_EVIDENCE = (
    "UNWIND $rows AS r MERGE (v:Evidence {id: r.id}) SET v += r.props "
    "WITH v, r MATCH (s:Section {id: r.section_id}) MERGE (v)-[:IN_SECTION]->(s)"
)
_ENTITIES = "UNWIND $rows AS r MERGE (e:Entity {id: r.id}) SET e += r.props"
_ENTITY_LABEL = "UNWIND $rows AS r MATCH (e:Entity {id: r.id}) SET e:`%s`"
_MENTIONS = (
    "UNWIND $rows AS r MATCH (e:Entity {id: r.entity_id}), (v:Evidence {id: r.evidence_id}) "
    "MERGE (e)-[m:MENTIONED_IN]->(v) SET m.surface = r.surface"
)
_ATTRIBUTES = (
    "UNWIND $rows AS r MATCH (e:Entity {id: r.entity_id}), (v:Evidence {id: r.evidence_id}) "
    "MERGE (e)-[a:HAS_ATTRIBUTE {key: r.key, value: r.value}]->(v) SET a.unit = r.unit"
)
_RELATED = (
    "UNWIND $rows AS r MATCH (a:Entity {id: r.subject_id}), (b:Entity {id: r.object_id}) "
    "MERGE (a)-[x:RELATED {predicate: r.predicate}]->(b) SET x += r.props"
)
_TYPED = (
    "UNWIND $rows AS r MATCH (a:Entity {id: r.subject_id}), (b:Entity {id: r.object_id}) "
    "MERGE (a)-[x:`%s`]->(b) SET x += r.props"
)


class Neo4jUnavailableError(RuntimeError):
    """The `neo4j` driver is not installed. Install the `kg-neo4j` extra."""


def _label(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    return cleaned if cleaned and not cleaned[0].isdigit() else f"T_{cleaned}"


def _batched(rows: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start : start + BATCH_SIZE]


def plan_batches(
    store: KGStore, *, typed_edges: bool = False
) -> Iterator[tuple[str, str, list[dict[str, Any]]]]:
    """`(label, cypher, rows)` in dependency order: constraints, pages, sections, evidence,
    entities, labels, mentions, attributes, relations."""
    for statement in CONSTRAINTS:
        yield ("constraint", statement, [])

    pages: dict[str, dict[str, Any]] = {}
    sections: dict[str, dict[str, Any]] = {}
    evidence_rows: list[dict[str, Any]] = []
    for ev in store.iter_evidence():
        pages.setdefault(ev.page_key, {"key": ev.page_key, "url": ev.url})
        sections.setdefault(ev.section_id, {"id": ev.section_id, "page_key": ev.page_key})
        evidence_rows.append(
            {
                "id": ev.id,
                "section_id": ev.section_id,
                "props": {
                    "url": ev.url,
                    "xpath": ev.block_xpath,
                    "span_start": ev.span[0],
                    "span_end": ev.span[1],
                    "quote": ev.quote,
                    "content_hash": ev.content_hash,
                },
            }
        )
    for batch in _batched(list(pages.values())):
        yield ("page", _PAGES, batch)
    for batch in _batched(list(sections.values())):
        yield ("section", _SECTIONS, batch)
    for batch in _batched(evidence_rows):
        yield ("evidence", _EVIDENCE, batch)

    entity_rows: list[dict[str, Any]] = []
    by_label: dict[str, list[dict[str, Any]]] = {}
    mention_rows: list[dict[str, Any]] = []
    attribute_rows: list[dict[str, Any]] = []
    for entity in store.iter_entities():
        entity_rows.append(
            {
                "id": entity.id,
                "props": {
                    "type": entity.type,
                    "name": entity.name,
                    "aliases": list(entity.aliases),
                    "generic": entity.generic,
                    "extractor": entity.extractor.value,
                    "evidence_count": entity.evidence_count,
                },
            }
        )
        by_label.setdefault(_label(entity.type), []).append({"id": entity.id})
        mention_rows += [
            {"entity_id": entity.id, "evidence_id": m.evidence.id, "surface": m.surface}
            for m in entity.mentions
        ]
        attribute_rows += [
            {
                "entity_id": entity.id,
                "evidence_id": a.evidence.id,
                "key": key,
                "value": a.value,
                "unit": a.unit,
            }
            for key, values in entity.attributes.items()
            for a in values
        ]
    for batch in _batched(entity_rows):
        yield ("entity", _ENTITIES, batch)
    for label, rows in sorted(by_label.items()):
        for batch in _batched(rows):
            yield ("label", _ENTITY_LABEL % label, batch)
    for batch in _batched(mention_rows):
        yield ("mention", _MENTIONS, batch)
    for batch in _batched(attribute_rows):
        yield ("attribute", _ATTRIBUTES, batch)

    relation_rows: list[dict[str, Any]] = []
    typed: dict[str, list[dict[str, Any]]] = {}
    for relation in store.iter_relations():
        row = {
            "subject_id": relation.subject_id,
            "object_id": relation.object_id,
            "predicate": relation.predicate,
            "props": {
                "id": relation.id,
                "fact": relation.fact,
                "weight": relation.weight,
                "confidence": relation.confidence,
                "evidence_ids": [e.id for e in relation.evidence],
            },
        }
        relation_rows.append(row)
        if typed_edges:
            typed.setdefault(_label(relation.predicate.upper()), []).append(row)
    for batch in _batched(relation_rows):
        yield ("relation", _RELATED, batch)
    for label, rows in sorted(typed.items()):
        for batch in _batched(rows):
            yield ("typed_relation", _TYPED % label, batch)


def sync_to_neo4j(
    store: KGStore,
    *,
    uri: str,
    user: str,
    password: str,
    database: str | None = None,
    typed_edges: bool = False,
    run: Callable[[str, list[dict[str, Any]]], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Push the graph, yielding `batch` events and a final `done`.

    `run` defaults to a session of the official driver; a test passes a recorder. The
    credentials are used for this call and held by nothing afterwards.
    """
    if run is None:
        try:
            import neo4j  # optional extra, imported where it is needed
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise Neo4jUnavailableError(
                'the neo4j driver is not installed; install it with pip install "webgraph[kg-neo4j]"'
            ) from exc
        driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
        session = driver.session(database=database) if database else driver.session()

        def run_with_driver(cypher: str, rows: list[dict[str, Any]]) -> None:
            session.run(cypher, rows=rows).consume()

        run = run_with_driver
        closers: list[Callable[[], None]] = [session.close, driver.close]
    else:
        closers = []

    counts: dict[str, int] = {}
    batches = 0
    try:
        for label, cypher, rows in plan_batches(store, typed_edges=typed_edges):
            run(cypher, rows)
            batches += 1
            counts[label] = counts.get(label, 0) + (len(rows) or 1)
            yield {"type": "batch", "label": label, "rows": len(rows), "batches": batches}
    finally:
        for close in closers:
            close()
    yield {"type": "done", "counts": counts, "batches": batches, "typed_edges": typed_edges}
