"""Schema-mapping tests.

The through-line: never invent a value. Most of these assert that a *wrong* match is
declined -- an absent field is recoverable, a confidently wrong one is not.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from webgraph.extract.schema import (
    ALIAS_EXTENSION,
    extract_facts,
    merge_facts,
    normalize_key,
)
from webgraph.types import Extractor, PayloadSource, StructuredPayload

URL = "https://example.com/p"


def payload(data: Any, source: PayloadSource = PayloadSource.JSON_LD) -> StructuredPayload:
    return StructuredPayload(source=source, data=data)


def values(schema: dict[str, Any], data: Any, **kwargs: Any) -> dict[str, Any]:
    facts = extract_facts([payload(data, **kwargs)], schema, URL)
    return {path: fact.value for path, fact in merge_facts(facts).items()}


class TestNormalizeKey:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("price_amount", "priceamount"),
            ("priceAmount", "priceamount"),
            ("Price Amount", "priceamount"),
            ("PRICE-AMOUNT", "priceamount"),
            ("og:title", "ogtitle"),
        ],
    )
    def test_folds_case_and_separators(self, raw: str, expected: str) -> None:
        assert normalize_key(raw) == expected


class TestScalarMatching:
    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "price": {"type": "number"}},
    }

    def test_exact_keys(self) -> None:
        assert values(self.SCHEMA, {"name": "Widget", "price": 49.0}) == {
            "name": "Widget", "price": 49.0,
        }

    def test_normalized_keys(self) -> None:
        assert values(self.SCHEMA, {"Name": "Widget", "PRICE": 49}) == {
            "name": "Widget", "price": 49.0,
        }

    def test_known_alias(self) -> None:
        """`title` is a documented bridge to `name`."""
        assert values(self.SCHEMA, {"title": "Widget"})["name"] == "Widget"

    def test_declared_alias_wins(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "cost": {"type": "number", ALIAS_EXTENSION: ["listPrice"]},
            },
        }
        assert values(schema, {"listPrice": 12.5}) == {"cost": 12.5}

    def test_missing_field_emits_nothing(self) -> None:
        assert values(self.SCHEMA, {"unrelated": 1}) == {}

    def test_null_value_is_not_a_match(self) -> None:
        assert values(self.SCHEMA, {"name": None}) == {}


class TestCoercion:
    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object", "properties": {"price": {"type": "number"}},
    }

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("49", 49.0), ("$49.00", 49.0), ("49.99", 49.99), (49, 49.0), ("  59 ", 59.0)],
    )
    def test_numeric_strings(self, raw: Any, expected: float) -> None:
        assert values(self.SCHEMA, {"price": raw})["price"] == expected

    @pytest.mark.parametrize("raw", ["contact us", "", "free", "N/A", "--"])
    def test_non_numeric_declines_rather_than_guessing(self, raw: str) -> None:
        """`contact us` coerced to 0 would be far worse than no price at all."""
        assert values(self.SCHEMA, {"price": raw}) == {}

    def test_integer_type(self) -> None:
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        assert values(schema, {"count": "42"})["count"] == 42
        assert isinstance(values(schema, {"count": "42"})["count"], int)

    def test_boolean_not_confused_with_number(self) -> None:
        schema = {"type": "object", "properties": {"n": {"type": "number"}}}
        assert values(schema, {"n": True}) == {}

    def test_boolean_type(self) -> None:
        schema = {"type": "object", "properties": {"active": {"type": "boolean"}}}
        assert values(schema, {"active": "true"})["active"] is True

    def test_string_from_number(self) -> None:
        schema = {"type": "object", "properties": {"sku": {"type": "string"}}}
        assert values(schema, {"sku": 12345})["sku"] == "12345"


class TestNesting:
    def test_nested_object_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "offers": {
                    "type": "object",
                    "properties": {"price": {"type": "number"}},
                }
            },
        }
        data = {"offers": {"@type": "Offer", "price": "49"}}
        assert values(schema, data) == {"offers.price": 49.0}

    def test_bounded_descent_finds_deep_value(self) -> None:
        """Hydration payloads bury data under props.pageProps.*"""
        schema = {"type": "object", "properties": {"headline": {"type": "string"}}}
        data = {"props": {"pageProps": {"article": {"headline": "Deep"}}}}
        assert values(schema, data, source=PayloadSource.NEXT_DATA)["headline"] == "Deep"

    def test_shallow_match_beats_deep_one(self) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        data = {"name": "shallow", "nested": {"name": "deep"}}
        assert values(schema, data)["name"] == "shallow"

    def test_descent_is_bounded(self) -> None:
        schema = {"type": "object", "properties": {"target": {"type": "string"}}}
        data: dict[str, Any] = {"target": "found"}
        for _ in range(12):
            data = {"wrap": data}
        assert values(schema, data) == {}


class TestArrays:
    def test_array_of_scalars(self) -> None:
        schema = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        }
        assert values(schema, {"tags": ["a", "b"]}) == {"tags.0": "a", "tags.1": "b"}

    def test_array_of_objects(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "plans": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "price": {"type": "number"},
                        },
                    },
                }
            },
        }
        data = {"plans": [{"name": "Pro", "price": 49}, {"name": "Team", "price": 99}]}
        assert values(schema, data) == {
            "plans.0.name": "Pro",
            "plans.0.price": 49.0,
            "plans.1.name": "Team",
            "plans.1.price": 99.0,
        }

    def test_scalar_promoted_to_single_element_array(self) -> None:
        schema = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        }
        assert values(schema, {"tags": "only"}) == {"tags.0": "only"}


class TestProvenanceAndMerging:
    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object", "properties": {"name": {"type": "string"}},
    }

    def test_provenance_records_source_and_extractor(self) -> None:
        facts = extract_facts([payload({"name": "W"})], self.SCHEMA, URL)
        provenance = facts[0].provenance
        assert provenance.extractor is Extractor.STRUCTURED_DATA
        assert provenance.source_url == URL
        assert "json-ld" in (provenance.note or "")

    def test_exact_match_scores_above_alias(self) -> None:
        exact = extract_facts([payload({"name": "W"})], self.SCHEMA, URL)[0]
        alias = extract_facts([payload({"title": "W"})], self.SCHEMA, URL)[0]
        assert exact.provenance.confidence > alias.provenance.confidence

    def test_json_ld_outranks_open_graph(self) -> None:
        """OpenGraph titles are written for social previews, not accuracy."""
        facts = extract_facts(
            [
                payload({"name": "Marketing variant"}, source=PayloadSource.OPEN_GRAPH),
                payload({"name": "Canonical name"}, source=PayloadSource.JSON_LD),
            ],
            self.SCHEMA,
            URL,
        )
        assert merge_facts(facts)["name"].value == "Canonical name"

    def test_merge_keeps_one_fact_per_path(self) -> None:
        facts = extract_facts(
            [payload({"name": "A"}), payload({"name": "B"})], self.SCHEMA, URL
        )
        assert len(facts) == 2
        assert len(merge_facts(facts)) == 1

    def test_confidence_decays_with_depth(self) -> None:
        shallow = extract_facts([payload({"name": "x"})], self.SCHEMA, URL)[0]
        deep = extract_facts([payload({"a": {"b": {"name": "x"}}})], self.SCHEMA, URL)[0]
        assert deep.provenance.confidence < shallow.provenance.confidence


class TestRealWorldShapes:
    def test_schema_org_product(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "offers": {
                    "type": "object",
                    "properties": {
                        "price": {"type": "number"},
                        "currency": {"type": "string"},
                    },
                },
            },
        }
        data = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Pro plan",
            "offers": {"@type": "Offer", "price": "49.00", "priceCurrency": "USD"},
        }
        assert values(schema, data) == {
            "name": "Pro plan",
            "offers.price": 49.0,
            "offers.currency": "USD",
        }

    def test_open_graph_prefixed_keys(self) -> None:
        schema = {"type": "object", "properties": {"title": {"type": "string"}}}
        data = {"og:title": "Page title", "og:description": "d"}
        got = values(schema, data, source=PayloadSource.OPEN_GRAPH)
        assert got["title"] == "Page title"

    def test_empty_payload_list(self) -> None:
        assert extract_facts([], {"type": "object", "properties": {}}, URL) == []
