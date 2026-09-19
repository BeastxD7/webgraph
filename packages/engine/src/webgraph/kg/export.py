"""Write the knowledge graph out: JSONL, a Cypher script, JSON-LD with PROV-O.

Three formats for three consumers. JSONL round-trips and streams (the `graph/export.py`
convention: one object per line, typed by `kind`, nodes before the edges that reference
them). Cypher is for pasting into a Neo4j, Memgraph or FalkorDB console -- plain `MERGE`
statements, no APOC, idempotent. JSON-LD is for anything that speaks RDF: each entity is a
schema.org-typed node and each assertion a `prov:Entity` that `prov:wasQuotedFrom` the page,
with a Web Annotation selector (`oa:XPathSelector` + `oa:TextPositionSelector`) naming the
block and the span. That is the provenance vocabulary the design chose because nothing else
in the field records a span to put in it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from webgraph.kg.model import Entity, Evidence, Relation
from webgraph.kg.store import KGStore

__all__ = ["CYPHER_HEADER", "to_cypher", "to_jsonl", "to_jsonld"]

CYPHER_HEADER = """\
// webgraph knowledge graph -- portable Cypher (Neo4j 5+, Memgraph, FalkorDB). No APOC.
CREATE CONSTRAINT kg_entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT kg_evidence_id IF NOT EXISTS FOR (v:Evidence) REQUIRE v.id IS UNIQUE;
CREATE CONSTRAINT kg_page_key IF NOT EXISTS FOR (p:Page) REQUIRE p.key IS UNIQUE;
CREATE CONSTRAINT kg_section_id IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE;
"""


def _entity_row(entity: Entity) -> dict[str, Any]:
    return {
        "kind": "entity",
        "id": entity.id,
        "type": entity.type,
        "name": entity.name,
        "aliases": list(entity.aliases),
        "description": entity.description,
        "extractor": entity.extractor.value,
        "generic": entity.generic,
        "first_seen": entity.first_seen,
        "last_seen": entity.last_seen,
        "evidence_count": entity.evidence_count,
        "attributes": {
            key: [{"value": a.value, "unit": a.unit, "evidence_id": a.evidence.id} for a in values]
            for key, values in entity.attributes.items()
        },
        "mentions": [{"surface": m.surface, "evidence_id": m.evidence.id} for m in entity.mentions],
    }


def _relation_row(relation: Relation) -> dict[str, Any]:
    return {
        "kind": "relation",
        "id": relation.id,
        "subject_id": relation.subject_id,
        "predicate": relation.predicate,
        "object_id": relation.object_id,
        "fact": relation.fact,
        "weight": relation.weight,
        "confidence": relation.confidence,
        "evidence_ids": [e.id for e in relation.evidence],
        "valid_from": relation.valid_from,
        "valid_to": relation.valid_to,
        "first_seen": relation.first_seen,
        "last_seen": relation.last_seen,
    }


def to_jsonl(store: KGStore) -> Iterator[str]:
    """Evidence first (everything cites it), then entities, then relations."""
    stats = store.stats()
    yield json.dumps({"kind": "kg", "root": store.meta("root") or "", **stats["counts"]})
    for ev in store.iter_evidence():
        yield json.dumps({"kind": "evidence", **ev.as_dict()})
    for entity in store.iter_entities():
        yield json.dumps(_entity_row(entity))
    for relation in store.iter_relations():
        yield json.dumps(_relation_row(relation))


def _q(value: object) -> str:
    return json.dumps("" if value is None else str(value))


def to_cypher(store: KGStore, *, typed_edges: bool = False) -> Iterator[str]:
    """`MERGE` statements. `typed_edges` also emits `-[:PREDICATE]->` relationships, which
    needs a server that accepts many relationship types; the `RELATED {predicate}` edge is
    always emitted because it is portable and queryable on any of them."""
    yield CYPHER_HEADER
    pages: set[str] = set()
    sections: set[tuple[str, str]] = set()
    for ev in store.iter_evidence():
        if ev.page_key not in pages:
            pages.add(ev.page_key)
            yield f"MERGE (p:Page {{key: {_q(ev.page_key)}}}) SET p.url = {_q(ev.url)};"
        if (ev.section_id, ev.page_key) not in sections:
            sections.add((ev.section_id, ev.page_key))
            yield (
                f"MERGE (s:Section {{id: {_q(ev.section_id)}}}) "
                f"WITH s MATCH (p:Page {{key: {_q(ev.page_key)}}}) MERGE (s)-[:ON_PAGE]->(p);"
            )
        yield (
            f"MERGE (v:Evidence {{id: {_q(ev.id)}}}) SET v.xpath = {_q(ev.block_xpath)}, "
            f"v.span_start = {ev.span[0]}, v.span_end = {ev.span[1]}, v.quote = {_q(ev.quote)}, "
            f"v.url = {_q(ev.url)}, v.content_hash = {_q(ev.content_hash)} "
            f"WITH v MATCH (s:Section {{id: {_q(ev.section_id)}}}) MERGE (v)-[:IN_SECTION]->(s);"
        )
    for entity in store.iter_entities():
        label = _label(entity.type)
        yield (
            f"MERGE (e:Entity {{id: {_q(entity.id)}}}) SET e:{label}, e.type = {_q(entity.type)}, "
            f"e.name = {_q(entity.name)}, e.aliases = {json.dumps(list(entity.aliases))}, "
            f"e.generic = {'true' if entity.generic else 'false'}, e.extractor = {_q(entity.extractor.value)};"
        )
        for key, values in entity.attributes.items():
            for attr in values:
                yield (
                    f"MATCH (e:Entity {{id: {_q(entity.id)}}}), (v:Evidence {{id: {_q(attr.evidence.id)}}}) "
                    f"MERGE (e)-[a:HAS_ATTRIBUTE {{key: {_q(key)}, value: {_q(attr.value)}}}]->(v) SET a.unit = {_q(attr.unit)};"
                )
        for mention in entity.mentions:
            yield (
                f"MATCH (e:Entity {{id: {_q(entity.id)}}}), (v:Evidence {{id: {_q(mention.evidence.id)}}}) "
                f"MERGE (e)-[m:MENTIONED_IN]->(v) SET m.surface = {_q(mention.surface)};"
            )
    for relation in store.iter_relations():
        evidence_ids = json.dumps([e.id for e in relation.evidence])
        yield (
            f"MATCH (a:Entity {{id: {_q(relation.subject_id)}}}), (b:Entity {{id: {_q(relation.object_id)}}}) "
            f"MERGE (a)-[r:RELATED {{predicate: {_q(relation.predicate)}}}]->(b) "
            f"SET r.fact = {_q(relation.fact)}, r.weight = {relation.weight}, r.confidence = {relation.confidence}, "
            f"r.evidence_ids = {evidence_ids};"
        )
        if typed_edges:
            yield (
                f"MATCH (a:Entity {{id: {_q(relation.subject_id)}}}), (b:Entity {{id: {_q(relation.object_id)}}}) "
                f"MERGE (a)-[r:{_label(relation.predicate.upper())}]->(b) SET r.fact = {_q(relation.fact)}, r.evidence_ids = {evidence_ids};"
            )


def _label(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"T_{cleaned}"
    return cleaned


_CONTEXT: dict[str, Any] = {
    "@vocab": "https://schema.org/",
    "prov": "http://www.w3.org/ns/prov#",
    "oa": "http://www.w3.org/ns/oa#",
    "wg": "https://webgraph.dev/ns#",
    "wasQuotedFrom": {"@id": "prov:wasQuotedFrom", "@type": "@id"},
}


def _selector(ev: Evidence) -> dict[str, Any]:
    return {
        "@type": "oa:SpecificResource",
        "oa:hasSource": ev.url,
        "oa:hasSelector": {
            "@type": "oa:XPathSelector",
            "oa:value": ev.block_xpath,
            "oa:refinedBy": {
                "@type": "oa:TextPositionSelector",
                "oa:start": ev.span[0],
                "oa:end": ev.span[1],
            },
        },
        "oa:exact": ev.quote,
    }


def to_jsonld(store: KGStore) -> dict[str, Any]:
    """One document: entities as schema.org nodes, every assertion a `prov:Entity`."""
    graph: list[dict[str, Any]] = []
    for entity in store.iter_entities():
        node: dict[str, Any] = {
            "@id": f"wg:{entity.id}",
            "@type": entity.type,
            "name": entity.name,
            "alternateName": list(entity.aliases),
            "wg:generic": entity.generic,
            "wg:extractor": entity.extractor.value,
        }
        node["wg:attribute"] = [
            {
                "@type": "prov:Entity",
                "wg:key": key,
                "value": attr.value,
                "unitText": attr.unit,
                "wasQuotedFrom": attr.evidence.url,
                "wg:selector": _selector(attr.evidence),
            }
            for key, values in entity.attributes.items()
            for attr in values
        ]
        node["wg:mention"] = [
            {
                "@type": "prov:Entity",
                "wg:surface": mention.surface,
                "wasQuotedFrom": mention.evidence.url,
                "wg:selector": _selector(mention.evidence),
            }
            for mention in entity.mentions
        ]
        graph.append(node)
    for relation in store.iter_relations():
        graph.append(
            {
                "@id": f"wg:{relation.id}",
                "@type": ["prov:Entity", "wg:Relation"],
                "wg:subject": {"@id": f"wg:{relation.subject_id}"},
                "wg:predicate": relation.predicate,
                "wg:object": {"@id": f"wg:{relation.object_id}"},
                "description": relation.fact,
                "wg:weight": relation.weight,
                "wasQuotedFrom": [e.url for e in relation.evidence],
                "wg:selector": [_selector(e) for e in relation.evidence],
            }
        )
    return {"@context": _CONTEXT, "@graph": graph}
