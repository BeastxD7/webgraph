"""WebGraph v1: the inferred knowledge graph behind `WEBGRAPH_KG`.

The product rule under test is *never a false output*: an assertion whose quote is not in
the block it names (or any block of its section) is rejected and counted; an answer
sentence with no valid citation is flagged; every citation resolves to `url#xpath` and a
verbatim quote. Everything runs on the `FakeProvider` -- no network, no key.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import httpx
import pytest

from webgraph.graph.model import SiteGraph
from webgraph.kg.build import BuildConfig, KGBuilder, cache_key, order_sections
from webgraph.kg.export import to_cypher, to_jsonl, to_jsonld
from webgraph.kg.extract import extract_section, locate_quote, prepare, verify
from webgraph.kg.merge import Merger, jaccard, shingles
from webgraph.kg.model import Evidence, Relation, entity_id, norm_name, snake_case
from webgraph.kg.neo4j import CONSTRAINTS, plan_batches, sync_to_neo4j
from webgraph.kg.offline import graph_from_directory
from webgraph.kg.prompts import EXTRACT_SCHEMA
from webgraph.kg.providers import (
    AnthropicProvider,
    FakeProvider,
    GeminiProvider,
    LLMError,
    OpenAICompatProvider,
    ProviderConfig,
)
from webgraph.kg.retrieve import KGRetriever, parse_answer
from webgraph.kg.store import KGStore, fts_query
from webgraph.types import Extractor

FIXTURE = Path(__file__).resolve().parents[3] / "benchmark" / "kg" / "fixtures" / "site"
ROOT = "https://kg-fixture.test/"


@pytest.fixture(scope="module")
def graph() -> SiteGraph:
    return graph_from_directory(FIXTURE, ROOT)


@pytest.fixture
def store(tmp_path: Path) -> KGStore:
    return KGStore(tmp_path / "kg.sqlite")


@pytest.fixture
def built(graph: SiteGraph, store: KGStore) -> tuple[KGStore, FakeProvider, list[dict]]:
    fake = FakeProvider()
    events = list(KGBuilder(graph, fake, store).run())
    return store, fake, events


def _section(graph: SiteGraph, heading: str):
    section = next(s for s in graph.sections.values() if s.heading == heading)
    return section, graph.pages[section.page_key]


# -- model ---------------------------------------------------------------------------------


class TestModel:
    def test_ids_are_deterministic_and_normalised(self) -> None:
        assert entity_id("Person", "Dr. Anita Rao") == entity_id("Person", "  dr. anita  rao ")
        assert entity_id("Person", "Anita Rao") != entity_id("Organization", "Anita Rao")
        assert norm_name("\u201cSVIT\u2019s\u201d") == "svit"
        assert snake_case("Teaches At") == snake_case("teachesAt") == "teaches_at"

    def test_a_relation_without_evidence_cannot_exist(self) -> None:
        with pytest.raises(ValueError, match="without evidence"):
            Relation(id="r", subject_id="a", predicate="p", object_id="b", fact="f", evidence=[])

    def test_evidence_bridges_to_provenance(self) -> None:
        ev = Evidence("h/p", "https://h/p", "h/p#s0", "/html/body/p[1]", (3, 9), "quote")
        prov = ev.to_provenance()
        assert prov.source_xpath == "/html/body/p[1]"
        assert prov.source_span == (3, 9)
        assert prov.extractor is Extractor.LLM
        assert ev.anchor == "https://h/p#/html/body/p[1]"


# -- extraction and the provenance rule ------------------------------------------------------


class TestVerification:
    def test_prompt_carries_a_marker_per_block(self, graph: SiteGraph) -> None:
        section, page = _section(graph, "Tuition fees")
        prepared = prepare(section, page, [])
        assert [m for m, _, _ in prepared.blocks] == ["b0", "b1"]
        assert "[b0] The tuition fee for B.E. Computer Science" in prepared.prompt
        assert all(ref.xpath.startswith("/html/") for _, _, ref in prepared.blocks)

    def test_a_verbatim_quote_becomes_evidence_with_span_and_xpath(self, graph: SiteGraph) -> None:
        section, page = _section(graph, "Tuition fees")
        prepared = prepare(section, page, [])
        payload = {
            "entities": [{
                "name": "B.E. Computer Science", "type": "Course", "aliases": [],
                "attributes": [{"key": "tuition", "value": "1,20,000", "unit": "INR/year", "block": "b0", "quote": "is ₹1,20,000 per year"}],
                "mentions": [{"block": "b0", "quote": "The tuition fee for B.E. Computer Science"}],
            }],
            "relations": [],
        }
        out = verify(payload, prepared)
        assert not out.rejected
        [entity] = out.entities
        [attr] = entity.attributes
        block_text = prepared.blocks[0][1]
        assert block_text[attr.evidence.span[0] : attr.evidence.span[1]] == "is ₹1,20,000 per year"
        assert attr.evidence.block_xpath == prepared.blocks[0][2].xpath
        assert attr.evidence.url == page.url

    def test_a_fabricated_quote_is_rejected_and_counted(self, graph: SiteGraph) -> None:
        """The product rule. A plausible sentence that is not on the page produces no row."""
        section, page = _section(graph, "Tuition fees")
        prepared = prepare(section, page, [])
        payload = {
            "entities": [{
                "name": "B.E. Computer Science", "type": "Course", "aliases": [],
                "attributes": [{"key": "tuition", "value": "1,50,000", "unit": "INR", "block": "b0", "quote": "The tuition fee is ₹1,50,000 per year"}],
                "mentions": [{"block": "b0", "quote": "B.E. Computer Science"}],
            }],
            "relations": [{
                "subject": "B.E. Computer Science", "predicate": "offered_by", "object": "B.E. Computer Science",
                "fact": "x", "evidence": [{"block": "b0", "quote": "not on this page at all"}],
            }],
        }
        out = verify(payload, prepared)
        [entity] = out.entities
        assert entity.attributes == []
        assert out.rejected["quote_not_found"] == 1
        assert out.rejected["self_relation"] == 1
        assert out.relations == []

    def test_a_misnumbered_block_is_recovered_from_the_right_block(self, graph: SiteGraph) -> None:
        section, page = _section(graph, "Tuition fees")
        prepared = prepare(section, page, [])
        payload = {
            "entities": [{
                "name": "M.Tech Data Science", "type": "Course", "aliases": [], "attributes": [],
                "mentions": [{"block": "b0", "quote": "The tuition fee for M.Tech Data Science is ₹95,000 per year"}],
            }],
            "relations": [],
        }
        out = verify(payload, prepared)
        [entity] = out.entities
        assert entity.mentions[0].evidence.block_xpath == prepared.blocks[1][2].xpath
        assert out.misnumbered == 1
        assert not out.rejected

    def test_a_relation_between_ungrounded_names_is_rejected(self, graph: SiteGraph) -> None:
        section, page = _section(graph, "Tuition fees")
        prepared = prepare(section, page, [])
        payload = {
            "entities": [],
            "relations": [{"subject": "A", "predicate": "p", "object": "B", "fact": "f", "evidence": [{"block": "b0", "quote": "tuition fee"}]}],
        }
        out = verify(payload, prepared)
        assert out.relations == []
        assert out.rejected["unknown_entity_in_relation"] == 1

    def test_locate_quote_is_exact_after_normalisation_only(self) -> None:
        block = "Visit the [admissions page](https://x/adm) — it opens “Monday”.\n\nSecond   line."
        assert locate_quote(block, "Visit the admissions page - it opens \"Monday\".") == (0, block.index(".") + 1)
        assert locate_quote(block, "Second line.") == (block.index("Second"), len(block))
        assert locate_quote(block, "Visit the admission page") is None  # a changed word is not a match
        assert locate_quote(block, "") is None

    def test_scripted_fabrication_through_the_provider_yields_nothing(self, graph: SiteGraph) -> None:
        section, page = _section(graph, "Tuition fees")
        prepared = prepare(section, page, [])
        fake = FakeProvider(scripted=[json.dumps({
            "entities": [{"name": "SVIT", "type": "Organization", "aliases": [], "attributes": [],
                          "mentions": [{"block": "b0", "quote": "SVIT charges nothing at all"}]}],
            "relations": [],
        })])
        out, raw = extract_section(fake, prepared)
        assert out.entities == []
        assert out.rejected == Counter({"quote_not_found": 1, "entity_without_evidence": 1})
        assert raw

    def test_invalid_json_is_retried_once_then_counted(self, graph: SiteGraph) -> None:
        section, page = _section(graph, "Tuition fees")
        prepared = prepare(section, page, [])
        fake = FakeProvider(scripted=["not json", "still not json"])
        out, _ = extract_section(fake, prepared)
        assert fake.calls == 2
        assert out.rejected == Counter({"invalid_json": 1})

    def test_predicate_synonyms_and_reversal(self, graph: SiteGraph) -> None:
        section, page = _section(graph, "M.Tech Data Science")
        prepared = prepare(section, page, [])
        payload = {
            "entities": [
                {"name": "Prof. Kiran Shetty", "type": "Person", "aliases": [], "attributes": [], "mentions": [{"block": "b0", "quote": "Prof. Kiran Shetty"}]},
                {"name": "M.Tech Data Science", "type": "Course", "aliases": [], "attributes": [], "mentions": [{"block": "b0", "quote": "M.Tech Data Science"}]},
            ],
            "relations": [{"subject": "M.Tech Data Science", "predicate": "Taught By", "object": "Prof. Kiran Shetty", "fact": "f",
                           "evidence": [{"block": "b0", "quote": "The programme coordinator is Prof. Kiran Shetty"}]}],
        }
        [relation] = verify(payload, prepared).relations
        assert relation.predicate == "teaches"
        assert (relation.subject, relation.object) == ("Prof. Kiran Shetty", "M.Tech Data Science")


# -- merge -----------------------------------------------------------------------------------


def _extracted(graph: SiteGraph, heading: str, payload: dict):
    section, page = _section(graph, heading)
    return verify(payload, prepare(section, page, []))


class TestMerge:
    def test_same_type_same_normalised_name_is_one_entity(self, graph: SiteGraph) -> None:
        a = _extracted(graph, "Dr. Anita Rao", {"entities": [{"name": "Dr. Anita Rao", "type": "Person", "aliases": [], "attributes": [],
                                                              "mentions": [{"block": "b0", "quote": "Dr. Anita Rao is the Head"}]}], "relations": []})
        b = _extracted(graph, "TechFest 2026", {"entities": [{"name": "DR. ANITA  RAO", "type": "Person", "aliases": [], "attributes": [],
                                                               "mentions": [{"block": "b0", "quote": "convened by Dr. Anita Rao"}]}], "relations": []})
        merger = Merger()
        merger.add_extracted(a)
        merger.add_extracted(b)
        result = merger.finish()
        [entity] = result.entities.values()
        assert entity.name == "Dr. Anita Rao"
        assert entity.aliases == (), "a spelling that normalises the same is not an alias"
        assert len(entity.mentions) == 2

    def test_a_declared_alias_merges_a_later_name(self, graph: SiteGraph) -> None:
        a = _extracted(graph, "Dr. Anita Rao", {"entities": [{"name": "Sode Valley Institute of Technology", "type": "Organization", "aliases": ["SVIT"], "attributes": [],
                                                              "mentions": [{"block": "b0", "quote": "Sode Valley Institute of Technology"}]}], "relations": []})
        b = _extracted(graph, "Dr. Anita Rao", {"entities": [{"name": "SVIT", "type": "Organization", "aliases": [], "attributes": [],
                                                              "mentions": [{"block": "b0", "quote": "joined SVIT in 2009"}]}], "relations": []})
        merger = Merger()
        merger.add_extracted(a)
        merger.add_extracted(b)
        [entity] = merger.finish().entities.values()
        assert entity.name == "Sode Valley Institute of Technology" and entity.aliases == ("SVIT",)
        assert len(entity.mentions) == 2

    def test_open_type_joins_core_type_but_core_types_stay_apart(self, graph: SiteGraph) -> None:
        def one(heading: str, name: str, type_: str, quote: str):
            return _extracted(graph, heading, {"entities": [
                {"name": name, "type": type_, "aliases": [], "attributes": [], "mentions": [{"block": "b0", "quote": quote}]},
            ], "relations": []})

        merger = Merger()
        merger.add_extracted(one("Dr. Anita Rao", "Dr. Anita Rao", "Faculty", "Dr. Anita Rao is the Head"))
        merger.add_extracted(one("TechFest 2026", "Dr. Anita Rao", "Person", "convened by Dr. Anita Rao"))
        merger.add_extracted(one("Contact us", "Sode Valley Institute of Technology", "Organization", "Sode Valley Institute of Technology, Sode Valley Road"))
        merger.add_extracted(one("Dr. Anita Rao", "Sode Valley Institute of Technology", "Place", "at Sode Valley Institute of Technology"))
        result = merger.finish()
        types = sorted((e.type, e.name) for e in result.entities.values())
        assert types == [("Organization", "Sode Valley Institute of Technology"), ("Person", "Dr. Anita Rao"), ("Place", "Sode Valley Institute of Technology")]
        rao = next(e for e in result.entities.values() if e.name == "Dr. Anita Rao")
        assert len(rao.mentions) == 2 and rao.id == entity_id("Person", "Dr. Anita Rao")

    def test_near_duplicates_merge_at_jaccard_point_nine(self, graph: SiteGraph) -> None:
        assert jaccard(shingles("Sode Valley Institute of Technology"), shingles("Sode Valley Institute of Technology.")) >= 0.9
        assert jaccard(shingles("Dr. Anita Rao"), shingles("Dr. Anita Rai")) < 0.9
        payload = {"entities": [
            {"name": "Sode Valley Institute of Technology", "type": "Organization", "aliases": [], "attributes": [], "mentions": [{"block": "b0", "quote": "Sode Valley Institute of Technology"}]},
            {"name": "Sode Valley  Institute of Technology,", "type": "Organization", "aliases": [], "attributes": [], "mentions": [{"block": "b0", "quote": "Institute of Technology"}]},
        ], "relations": []}
        merger = Merger()
        merger.add_extracted(_extracted(graph, "Dr. Anita Rao", payload))
        assert len(merger.finish().entities) == 1

    def test_structured_data_enters_first_and_wins_the_type(self, graph: SiteGraph) -> None:
        merger = Merger(total_pages=len(graph.pages))
        merger.add_structured(graph)
        merger.add_extracted(_extracted(graph, "Dr. Anita Rao", {"entities": [
            {"name": "Dr. Anita Rao", "type": "Organization", "aliases": [], "attributes": [], "mentions": [{"block": "b0", "quote": "Dr. Anita Rao is the Head"}]},
        ], "relations": []}))
        result = merger.finish()
        rao = [e for e in result.entities.values() if e.name == "Dr. Anita Rao"]
        assert len(rao) == 2, "a core-type conflict stays two entities; the structured one keeps Person"
        structured = next(e for e in rao if e.extractor is Extractor.STRUCTURED_DATA)
        assert structured.type == "Person"
        assert structured.attributes["job_title"][0].value.startswith("Head of the Department")
        assert all(m.evidence.block_xpath for m in structured.mentions), "structured entities cite the block that names them"

    def test_merge_is_deterministic_across_runs(self, graph: SiteGraph, tmp_path: Path) -> None:
        def build() -> dict:
            store = KGStore(tmp_path / f"{id(object())}.sqlite")
            list(KGBuilder(graph, FakeProvider(), store, build_config=BuildConfig(concurrency=3)).run())
            return {
                "entities": sorted((e.id, e.type, e.name, tuple(e.aliases), e.evidence_count) for e in store.iter_entities()),
                "relations": sorted((r.id, r.predicate, r.weight) for r in store.iter_relations()),
            }

        assert build() == build()

    def test_generic_names_are_flagged(self, built: tuple[KGStore, FakeProvider, list[dict]]) -> None:
        store, _, _ = built
        svit = next(e for e in store.iter_entities() if e.name == "Sode Valley Institute of Technology")
        assert svit.generic, "named on every page: kept, never expanded through"
        assert len(svit.pages) == 6


# -- store -----------------------------------------------------------------------------------


class TestStore:
    def test_round_trip_keeps_every_row(self, built: tuple[KGStore, FakeProvider, list[dict]]) -> None:
        store, _, events = built
        done = events[-1]["stats"]
        counts = store.stats()["counts"]
        assert counts["entities"] == done["entities"]
        assert counts["relations"] == done["relations"]
        assert counts["evidence"] > 0
        reopened = KGStore(store.path)
        assert reopened.stats()["counts"] == counts
        entity = next(reopened.iter_entities())
        assert entity.mentions and entity.mentions[0].evidence.block_xpath.startswith("/html/")
        relation = next(reopened.iter_relations())
        assert relation.evidence and relation.weight >= 1

    def test_fts_query_survives_punctuation(self, built: tuple[KGStore, FakeProvider, list[dict]]) -> None:
        store, _, _ = built
        assert store.has_fts
        assert fts_query('What is "the" fee: for B.E.? -x') == '"What" OR "is" OR "the" OR "fee" OR "for"'
        hits = store.search_entities("Who is Dr. Anita Rao?")
        assert hits and store.get_entity(hits[0][0]).name == "Dr. Anita Rao"
        assert all(score > 0 for _, score in hits), "bm25 is negated into a positive score"
        assert store.search_facts("!!! ???") == []

    def test_llm_cache_round_trip(self, store: KGStore) -> None:
        from webgraph.kg.providers import Usage

        store.cache_put("k", '{"entities": [], "relations": []}', Usage(10, 2), "m")
        text, usage, model = store.cache_get("k")
        assert (text, usage.input_tokens, usage.output_tokens, model) == ('{"entities": [], "relations": []}', 10, 2, "m")
        assert store.cache_get("missing") is None

    def test_an_old_schema_version_is_recreated(self, tmp_path: Path) -> None:
        import sqlite3

        path = tmp_path / "old.sqlite"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE entities (id TEXT)")
        conn.execute("PRAGMA user_version=999")
        conn.commit()
        conn.close()
        store = KGStore(path)
        assert store.stats()["counts"]["entities"] == 0


# -- build -----------------------------------------------------------------------------------


class TestBuild:
    def test_estimate_comes_first_and_before_any_call(self, graph: SiteGraph, store: KGStore) -> None:
        fake = FakeProvider()
        events = KGBuilder(graph, fake, store).run()
        first = next(events)
        assert first["type"] == "estimate"
        assert fake.calls == 0
        assert first["sections"] == 23 and first["pages"] == 6
        assert first["input_tokens"] > 1000 and first["output_tokens"] == int(first["input_tokens"] * 0.25)
        assert first["usd"] is None, "no prices configured, so no dollar figure is invented"
        assert "api_key" not in json.dumps(first)

    def test_build_counts_and_events(self, built: tuple[KGStore, FakeProvider, list[dict]]) -> None:
        store, fake, events = built
        kinds = [e["type"] for e in events]
        assert kinds[0] == "estimate" and kinds[-1] == "done"
        assert "merge" in kinds and kinds.count("section") == 23
        stats = events[-1]["stats"]
        assert stats["entities"] >= 10 and stats["relations"] >= 5
        assert stats["accepted"] > 50
        assert stats["rejection_rate"] < 0.15
        assert not stats["truncated"]
        assert fake.calls == stats["sections"] - stats["cache_hits"]
        section_events = [e for e in events if e["type"] == "section"]
        assert all(set(e) >= {"page", "section_id", "accepted", "rejected", "rejected_reasons", "cached"} for e in section_events)
        assert store.last_run()["entities"] == stats["entities"]

    def test_second_build_hits_the_cache_and_makes_no_calls(self, built: tuple[KGStore, FakeProvider, list[dict]], graph: SiteGraph) -> None:
        store, _, first = built
        fake = FakeProvider()
        events = list(KGBuilder(graph, fake, store).run())
        assert fake.calls == 0
        assert events[0]["cached_sections"] == 23 and events[0]["input_tokens"] == 0
        assert events[-1]["stats"]["cache_hits"] == 23
        assert events[-1]["stats"]["entities"] == first[-1]["stats"]["entities"]
        assert cache_key("m", "text", []) != cache_key("m2", "text", [])

    def test_rebuild_ignores_the_cache(self, built: tuple[KGStore, FakeProvider, list[dict]], graph: SiteGraph) -> None:
        store, _, _ = built
        fake = FakeProvider()
        list(KGBuilder(graph, fake, store, build_config=BuildConfig(rebuild=True)).run())
        assert fake.calls == 23

    def test_token_cap_stops_the_build_cleanly(self, graph: SiteGraph, store: KGStore) -> None:
        fake = FakeProvider()
        events = list(KGBuilder(graph, fake, store, build_config=BuildConfig(max_input_tokens=1500, concurrency=1)).run())
        budget = [e for e in events if e["type"] == "budget"]
        assert budget and budget[0]["reason"] == "max_input_tokens" and budget[0]["remaining_sections"] > 0
        done = events[-1]
        assert done["truncated"] and done["stats"]["truncated_reason"] == "max_input_tokens"
        assert 0 < fake.calls < 23
        assert done["stats"]["input_tokens"] <= 1500

    def test_usd_cap_stops_the_build(self, graph: SiteGraph, store: KGStore) -> None:
        fake = FakeProvider(ProviderConfig(provider="fake", model="fake-1", price_per_m_in=1000.0, price_per_m_out=1000.0))
        events = list(KGBuilder(graph, fake, store, build_config=BuildConfig(max_usd=0.005, concurrency=1)).run())
        assert events[0]["usd"] > 0.005
        assert events[-1]["stats"]["truncated_reason"] == "max_usd"
        assert events[-1]["stats"]["usd"] <= 0.005

    def test_page_and_section_caps(self, graph: SiteGraph, store: KGStore) -> None:
        events = list(KGBuilder(graph, FakeProvider(), store, build_config=BuildConfig(max_pages=2)).run())
        assert events[0]["pages"] == 2 and events[0]["skipped"]["page_cap"] > 0
        events = list(KGBuilder(graph, FakeProvider(), store, build_config=BuildConfig(max_sections=3)).run())
        assert events[0]["sections"] == 3

    def test_sections_are_ordered_by_in_degree_then_depth(self, graph: SiteGraph) -> None:
        ordered = order_sections(graph)
        degrees = [len(graph.linked_from.get(page.key, ())) for page, _ in ordered]
        assert degrees == sorted(degrees, reverse=True)

    def test_a_graph_without_block_refs_is_skipped_not_cited(self, graph: SiteGraph, store: KGStore) -> None:
        from dataclasses import replace

        stripped = SiteGraph(root=graph.root, pages=dict(graph.pages), sections={k: replace(s, blocks=()) for k, s in graph.sections.items()})
        events = list(KGBuilder(stripped, FakeProvider(), store).run())
        assert events[0]["sections"] == 0 and events[0]["skipped"]["no_block_refs"] == 23

    def test_should_stop_ends_the_build(self, graph: SiteGraph, store: KGStore) -> None:
        events = list(KGBuilder(graph, FakeProvider(), store, build_config=BuildConfig(concurrency=1), should_stop=lambda: True).run())
        assert events[-1]["stats"]["truncated_reason"] == "stopped"


# -- retrieve ----------------------------------------------------------------------------------


class TestRetrieve:
    def test_path_is_streamed_in_order_and_answer_cites_url_xpath(self, built: tuple[KGStore, FakeProvider, list[dict]], graph: SiteGraph) -> None:
        store, fake, _ = built
        events = list(KGRetriever(store, fake, graph=graph).ask("What is the tuition fee for B.E. Computer Science?"))
        kinds = [e["type"] for e in events]
        assert kinds[0] == "seeds" and kinds[-1] == "answer"
        assert kinds.index("seeds") < kinds.index("hop") < kinds.index("evidence") < kinds.index("answer_delta")
        seeds = events[0]
        assert any(e["name"] == "B.E. Computer Science" for e in seeds["entities"])
        hop = next(e for e in events if e["type"] == "hop")
        assert hop["edges"] and set(hop["edges"][0]) >= {"from_id", "to_id", "relation_id", "predicate", "score"}
        evidence = next(e for e in events if e["type"] == "evidence")
        assert all(i["anchor"] == f"{i['url']}#{i['xpath']}" and i["xpath"].startswith("/html/") for i in evidence["items"])
        answer = events[-1]
        assert answer["citations"] and all(c["anchor"].startswith("https://kg-fixture.test/") for c in answer["citations"])
        assert "₹1,20,000" in answer["text"]
        assert answer["unsupported"] == 0
        assert answer["path"]["answer_nodes"]
        assert answer["path"]["seeds"] == [e["id"] for e in seeds["entities"]]

    def test_generic_entities_are_not_expanded_through(self, built: tuple[KGStore, FakeProvider, list[dict]], graph: SiteGraph) -> None:
        store, fake, _ = built
        svit = next(e for e in store.iter_entities() if e.generic)
        events = list(KGRetriever(store, fake, graph=graph).retrieve("Sode Valley Institute of Technology"))
        hops = [edge for e in events if e["type"] == "hop" for edge in e["edges"]]
        assert any(x["id"] == svit.id for x in events[0]["entities"])
        assert not any(edge["from_id"] == svit.id for edge in hops)

    def test_uncited_sentences_are_flagged_never_dropped(self, built: tuple[KGStore, FakeProvider, list[dict]], graph: SiteGraph) -> None:
        store, _, _ = built
        fake = FakeProvider(scripted=["The fee is ₹1,20,000 per year [1]. The campus has a swimming pool. It also has a lake [99]."])
        answer = list(KGRetriever(store, fake, graph=graph).ask("tuition fee B.E. Computer Science"))[-1]
        flags = [(s["text"][:20], s["unsupported"]) for s in answer["sentences"]]
        assert flags == [("The fee is ₹1,20,000", False), ("The campus has a swi", True), ("It also has a lake [", True)]
        assert answer["unsupported"] == 2
        assert [c["n"] for c in answer["citations"]] == [1]

    def test_abstention_is_recognised(self, built: tuple[KGStore, FakeProvider, list[dict]], graph: SiteGraph) -> None:
        store, _, _ = built
        fake = FakeProvider(scripted=["Not stated on this site."])
        answer = list(KGRetriever(store, fake, graph=graph).ask("How many Nobel laureates?"))[-1]
        assert answer["abstained"] and answer["unsupported"] == 0 and answer["citations"] == []

    def test_parse_answer_keeps_abbreviations_together(self) -> None:
        from webgraph.kg.model import Citation, QueryPath

        cites = [Citation(1, "u", "/x", "q", "s"), Citation(2, "u", "/y", "q", "s")]
        answer = parse_answer("Dr. Anita Rao heads the B.E. Computer Science programme [1]. It costs ₹1,20,000 [2].", cites, QueryPath())
        assert [s.citations for s in answer.sentences] == [(1,), (2,)]
        assert answer.unsupported_count == 0

    def test_no_provider_gives_an_extractive_answer(self, built: tuple[KGStore, FakeProvider, list[dict]], graph: SiteGraph) -> None:
        store, _, _ = built
        answer = list(KGRetriever(store, None, graph=graph).ask("TechFest 2026"))[-1]
        assert answer["citations"] and answer["usage"]["model"] == "none"


# -- export ------------------------------------------------------------------------------------


class TestExport:
    def test_jsonl_parses_and_cites(self, built: tuple[KGStore, FakeProvider, list[dict]]) -> None:
        store, _, _ = built
        rows = [json.loads(line) for line in to_jsonl(store)]
        kinds = Counter(r["kind"] for r in rows)
        assert kinds["kg"] == 1 and kinds["evidence"] == store.stats()["counts"]["evidence"]
        assert kinds["entity"] == store.stats()["counts"]["entities"]
        evidence_ids = {r["id"] for r in rows if r["kind"] == "evidence"}
        for r in rows:
            if r["kind"] == "relation":
                assert r["evidence_ids"] and set(r["evidence_ids"]) <= evidence_ids
            if r["kind"] == "entity":
                assert all(m["evidence_id"] in evidence_ids for m in r["mentions"])
        # Evidence precedes everything that cites it.
        first_entity = next(i for i, r in enumerate(rows) if r["kind"] == "entity")
        assert all(r["kind"] in {"kg", "evidence"} for r in rows[:first_entity])

    def test_cypher_is_merge_only_and_escapes_quotes(self, built: tuple[KGStore, FakeProvider, list[dict]]) -> None:
        store, _, _ = built
        lines = list(to_cypher(store))
        body = [ln for ln in lines[1:] if ln.strip()]
        assert all(ln.startswith(("MERGE", "MATCH")) for ln in body)
        assert "CREATE (" not in "\n".join(body)
        assert any("RELATED {predicate:" in ln for ln in body)
        assert all(ln.rstrip().endswith(";") for ln in body)
        typed = list(to_cypher(store, typed_edges=True))
        assert any("[r:MENTIONED_WITH]" in ln for ln in typed)

    def test_jsonld_carries_prov_and_xpath_selectors(self, built: tuple[KGStore, FakeProvider, list[dict]]) -> None:
        store, _, _ = built
        doc = json.loads(json.dumps(to_jsonld(store)))
        assert doc["@context"]["prov"] == "http://www.w3.org/ns/prov#"
        entity = next(n for n in doc["@graph"] if n.get("wg:mention"))
        selector = entity["wg:mention"][0]["wg:selector"]
        assert selector["oa:hasSelector"]["@type"] == "oa:XPathSelector"
        assert selector["oa:hasSelector"]["oa:value"].startswith("/html/")
        assert selector["oa:hasSelector"]["oa:refinedBy"]["@type"] == "oa:TextPositionSelector"
        assert entity["wg:mention"][0]["wasQuotedFrom"].startswith("https://")

    def test_neo4j_plan_is_unwind_merge_batches_and_needs_no_driver(self, built: tuple[KGStore, FakeProvider, list[dict]]) -> None:
        store, _, _ = built
        plan = list(plan_batches(store))
        assert [c for _, c, _ in plan[: len(CONSTRAINTS)]] == list(CONSTRAINTS)
        labels = [label for label, _, _ in plan]
        assert labels.index("page") < labels.index("evidence") < labels.index("entity") < labels.index("mention") < labels.index("relation")
        for label, cypher, rows in plan[len(CONSTRAINTS):]:
            assert cypher.startswith("UNWIND $rows AS r") and ("MERGE" in cypher or label == "label") and rows and len(rows) <= 1000
        assert "apoc" not in " ".join(c for _, c, _ in plan).lower()
        ran: list[tuple[str, int]] = []
        events = list(sync_to_neo4j(store, uri="bolt://x", user="u", password="p", run=lambda c, rows: ran.append((c[:20], len(rows)))))
        assert events[-1]["type"] == "done" and events[-1]["batches"] == len(plan) == len(ran)


# -- providers -----------------------------------------------------------------------------------


class TestProviders:
    def test_env_and_presets(self) -> None:
        cfg = ProviderConfig.from_env({"WEBGRAPH_LLM_PROVIDER": "ollama", "WEBGRAPH_LLM_MODEL": "qwen3:8b"})
        assert (cfg.provider, cfg.base_url, cfg.model) == ("openai-compatible", "http://localhost:11434/v1", "qwen3:8b")
        cfg = ProviderConfig.from_env({"WEBGRAPH_LLM_PROVIDER": "anthropic", "WEBGRAPH_LLM_API_KEY_ENV": "MY_KEY"})
        assert cfg.provider == "anthropic" and cfg.resolve_key({"MY_KEY": "sk-1"}) == "sk-1"
        merged = ProviderConfig.from_dict({"provider": "groq", "model": "llama", "api_key": "k"}, base=cfg)
        assert merged.base_url.startswith("https://api.groq.com") and merged.api_key == "k"
        with pytest.raises(ValueError, match="unknown provider"):
            ProviderConfig.from_dict({"provider": "carrier-pigeon"}, base=cfg)

    def test_the_key_never_appears_in_repr_or_redacted(self) -> None:
        cfg = ProviderConfig(model="m", api_key="sk-secret-123")
        assert "sk-secret-123" not in repr(cfg)
        assert "sk-secret-123" not in json.dumps(cfg.redacted())
        assert cfg.redacted()["has_key"] is True

    def test_openai_compatible_falls_back_from_json_schema_to_json_object(self) -> None:
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen.append(body)
            assert request.headers["authorization"] == "Bearer k"
            if body.get("response_format", {}).get("type") == "json_schema":
                return httpx.Response(400, json={"error": "response_format not supported"})
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"entities": [], "relations": []}'}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}, "model": "m"})

        provider = OpenAICompatProvider(ProviderConfig(model="m", api_key="k", base_url="http://llm.test/v1"), transport=httpx.MockTransport(handler))
        result = provider.complete_json("s", "u", EXTRACT_SCHEMA)
        assert result.json() == {"entities": [], "relations": []}
        assert [b.get("response_format", {}).get("type") for b in seen] == ["json_schema", "json_object"]
        assert "JSON Schema" in seen[1]["messages"][1]["content"]
        assert result.usage.input_tokens == 5
        provider.complete_json("s", "u", EXTRACT_SCHEMA)
        assert seen[-1]["response_format"]["type"] == "json_object", "the fallback is remembered"

    def test_retryable_status_is_retried_and_a_4xx_is_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("webgraph.kg.providers.time.sleep", lambda _: None)
        calls = {"n": 0}

        def flaky(_: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503 if calls["n"] < 3 else 200, json={"choices": [{"message": {"content": "ok"}}]})

        provider = OpenAICompatProvider(ProviderConfig(model="m", base_url="http://llm.test/v1"), transport=httpx.MockTransport(flaky))
        assert provider.complete_text("s", "u").text == "ok" and calls["n"] == 3
        provider = OpenAICompatProvider(ProviderConfig(model="m", base_url="http://llm.test/v1"), transport=httpx.MockTransport(lambda _: httpx.Response(401, json={"error": "bad key"})))
        with pytest.raises(LLMError, match="401"):
            provider.complete_text("s", "u")

    def test_anthropic_request_shape(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"content": [{"type": "text", "text": '{"entities": [], "relations": []}'}], "usage": {"input_tokens": 7, "output_tokens": 3}, "model": "claude"})

        provider = AnthropicProvider(ProviderConfig(provider="anthropic", base_url="https://api.anthropic.com", model="claude", api_key="k"), transport=httpx.MockTransport(handler))
        result = provider.complete_json("sys", "user", EXTRACT_SCHEMA)
        body = json.loads(seen[0].content)
        assert str(seen[0].url) == "https://api.anthropic.com/v1/messages"
        assert seen[0].headers["x-api-key"] == "k" and seen[0].headers["anthropic-version"]
        assert body["output_config"]["format"] == {"type": "json_schema", "schema": EXTRACT_SCHEMA}
        assert body["system"] == "sys" and body["messages"] == [{"role": "user", "content": "user"}]
        assert result.usage.input_tokens == 7 and result.json()["entities"] == []

    def test_gemini_request_shape(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{\"entities\": [], \"relations\": []}"}]}}], "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 1}})

        provider = GeminiProvider(ProviderConfig(provider="gemini", base_url="https://generativelanguage.googleapis.com/v1beta", model="gemini-x", api_key="k"), transport=httpx.MockTransport(handler))
        provider.complete_json("sys", "user", EXTRACT_SCHEMA)
        body = json.loads(seen[0].content)
        assert str(seen[0].url).endswith("/models/gemini-x:generateContent")
        assert seen[0].headers["x-goog-api-key"] == "k"
        assert body["generationConfig"]["responseJsonSchema"] == EXTRACT_SCHEMA
        assert body["systemInstruction"]["parts"][0]["text"] == "sys"

    def test_fake_provider_quotes_verbatim(self, graph: SiteGraph) -> None:
        section, page = _section(graph, "Tuition fees")
        prepared = prepare(section, page, [])
        out, _ = extract_section(FakeProvider(), prepared)
        assert out.accepted > 0 and out.rejected["quote_not_found"] == 0
        fabricated, _ = extract_section(FakeProvider(fabricate=True), prepared)
        assert fabricated.rejected["quote_not_found"] > 0


# -- CLI ---------------------------------------------------------------------------------------


class TestCLI:
    @pytest.fixture
    def env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setenv("WEBGRAPH_KG", "1")
        monkeypatch.setenv("WEBGRAPH_KG_DIR", str(tmp_path / "kg"))
        monkeypatch.setenv("WEBGRAPH_GRAPH_DIR", str(tmp_path / "graphs"))
        return tmp_path

    def test_the_flag_gates_every_subcommand(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from webgraph.cli import main

        monkeypatch.delenv("WEBGRAPH_KG", raising=False)
        monkeypatch.setenv("WEBGRAPH_KG_DIR", str(tmp_path))
        for argv in (["kg", "build", ROOT, "--pages", str(FIXTURE), "--provider", "fake"], ["kg", "ask", ROOT, "q"], ["kg", "export", ROOT], ["kg", "sync-neo4j", ROOT]):
            with pytest.raises(SystemExit, match="WEBGRAPH_KG=1"):
                main(argv)

    def test_build_ask_export(self, env: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from webgraph.cli import main

        assert main(["kg", "build", ROOT, "--pages", str(FIXTURE), "--provider", "fake", "--model", "fake-1", "--json"]) == 0
        events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert events[0]["type"] == "estimate" and events[-1]["type"] == "done"
        assert list((env / "kg").glob("*.sqlite"))

        assert main(["kg", "ask", ROOT, "What is the tuition fee for B.E. Computer Science?", "--pages", str(FIXTURE), "--no-model"]) == 0
        out = capsys.readouterr().out
        assert "₹1,20,000" in out and "#/html/body/main/p[" in out

        assert main(["kg", "export", ROOT, "--format", "jsonl"]) == 0
        rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert rows[0]["kind"] == "kg" and any(r["kind"] == "entity" for r in rows)
        assert main(["kg", "export", ROOT, "--format", "cypher", "--out", str(env / "g.cypher")]) == 0
        assert "MERGE (e:Entity" in (env / "g.cypher").read_text()

    @pytest.mark.usefixtures("env")
    def test_build_needs_a_model_and_ask_needs_a_graph(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.cli import main

        monkeypatch.delenv("WEBGRAPH_LLM_MODEL", raising=False)
        with pytest.raises(SystemExit, match="--model"):
            main(["kg", "build", ROOT, "--pages", str(FIXTURE), "--provider", "ollama"])
        assert main(["kg", "ask", ROOT, "q", "--no-model"]) == 1

    @pytest.mark.usefixtures("env")
    def test_sync_refuses_a_password_on_the_command_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from webgraph.cli import main

        main(["kg", "build", ROOT, "--pages", str(FIXTURE), "--provider", "fake", "--json"])
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
        with pytest.raises(SystemExit, match="NEO4J_PASSWORD"):
            main(["kg", "sync-neo4j", ROOT])
