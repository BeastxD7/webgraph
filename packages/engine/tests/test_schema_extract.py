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
            "name": "Widget",
            "price": 49.0,
        }

    def test_normalized_keys(self) -> None:
        assert values(self.SCHEMA, {"Name": "Widget", "PRICE": 49}) == {
            "name": "Widget",
            "price": 49.0,
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
        "type": "object",
        "properties": {"price": {"type": "number"}},
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
        "type": "object",
        "properties": {"name": {"type": "string"}},
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
        facts = extract_facts([payload({"name": "A"}), payload({"name": "B"})], self.SCHEMA, URL)
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


class TestDecimalSeparators:
    """Prices written the way most of Europe writes them.

    `_coerce` used to strip everything but digits, dots and minus, which turns `"19,99"`
    into `1999.0` — a hundred times the real price, emitted with full confidence and no
    way for anything downstream to notice. It is the worst failure shape this module can
    have: not a missing value, an authoritative wrong one.

    It is also not rare. In a census of 2,008 labelled pages, comma-decimal was 34% of
    string-valued prices, and the two largest e-commerce platforms are the reason:
    WooCommerce formats prices through PHP's `number_format` with the store's own decimal
    separator, and Shopify emits the price as a quoted string.
    """

    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"price": {"type": "number"}},
    }

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("19,99", 19.99),
            ("1.299,00", 1299.0),
            ("1 299,99", 1299.99),
            # A non-breaking space, which is what a page actually contains when it groups
            # thousands: browsers and CMSes both emit it so the number cannot wrap.
            ("1\u00a0299,99", 1299.99),
            ("1,299.00", 1299.0),
            ("$168.00", 168.0),
            ("1,299", 1299.0),
            ("€ 19,99", 19.99),
            ("19.99", 19.99),
        ],
    )
    def test_reads_both_conventions(self, raw: str, expected: float) -> None:
        assert values(self.SCHEMA, {"price": raw})["price"] == expected

    @pytest.mark.parametrize("raw", ["1.2.3", "12,34,56", "1,2345"])
    def test_declines_when_the_convention_cannot_be_told(self, raw: str) -> None:
        """Emitting nothing is recoverable. Emitting the wrong number is not.

        `"1,2345"` has no reading under either convention — four digits after a comma is
        not a decimal fraction and not a thousands group.
        """
        assert values(self.SCHEMA, {"price": raw}) == {}

    @pytest.mark.parametrize("raw", ["1.299", "1,299", "1 299"])
    def test_three_digits_after_a_separator_is_a_thousands_group(self, raw: str) -> None:
        """Both conventions agree here, for once.

        `"1.299"` is 1,299 in Berlin and $1.299 in Boston — but a price written to three
        decimal places is far rarer than a price of one thousand two hundred and ninety
        nine, so the thousands reading is the one that is almost always right.
        """
        assert values(self.SCHEMA, {"price": raw})["price"] == 1299.0


class TestEntitiesAndEnums:
    def test_html_entities_are_unescaped(self) -> None:
        """JSON-LD is JSON, so entities in it were never meant to survive.

        They do, on roughly one in six pages carrying JSON-LD, because the emitter built
        the string from already-escaped HTML: `"Maria &amp; Katerina"` where the page
        shows `"Maria & Katerina"`.
        """
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        assert values(schema, {"name": "Maria &amp; Katerina"})["name"] == "Maria & Katerina"

    @pytest.mark.parametrize(
        "raw",
        [
            "https://schema.org/InStock",
            "http://schema.org/InStock",
            "InStock",
            "https://schema.org/InStock/",
        ],
    )
    def test_enum_matches_the_last_path_segment(self, raw: str) -> None:
        """All four spellings are in the wild, and the `http://` half is not legacy drift:
        Shopify's current default themes emit it."""
        schema = {
            "type": "object",
            "properties": {"availability": {"type": "string", "enum": ["InStock", "OutOfStock"]}},
        }
        assert values(schema, {"availability": raw})["availability"] == "InStock"

    def test_a_value_outside_the_enum_is_declined(self) -> None:
        """One page in the census says `OutStock`. A typo is not a state."""
        schema = {
            "type": "object",
            "properties": {"availability": {"type": "string", "enum": ["InStock", "OutOfStock"]}},
        }
        assert values(schema, {"availability": "OutStock"}) == {}


class TestDateFormat:
    """`format: "date-time"` means ISO-8601 or nothing.

    7% of `datePublished` values are not ISO, and they include `"13/11/2025 09:21:40"` —
    day-month or month-day, indistinguishable for any day below 13. A date read the wrong
    way round is wrong for eleven months of the year and right for one.
    """

    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"datePublished": {"type": "string", "format": "date-time"}},
    }

    @pytest.mark.parametrize(
        "raw",
        [
            "2024-03-11T09:00:00Z",
            "2024-03-11T09:00:00+05:30",
            "2024-03-11",
            '"2024-03-11T09:00:00Z"',
        ],
    )
    def test_accepts_iso_8601(self, raw: str) -> None:
        assert values(self.SCHEMA, {"datePublished": raw})["datePublished"].startswith("2024-03-11")

    @pytest.mark.parametrize(
        "raw",
        [
            "Feb 08, 2022",
            "November 18, 2025",
            "Thu, 09/25/2025 - 11:38",
            "13/11/2025 09:21:40",
            "On 8 Oct 2022",
        ],
    )
    def test_declines_everything_else(self, raw: str) -> None:
        assert values(self.SCHEMA, {"datePublished": raw}) == {}

    def test_the_format_only_applies_to_dates(self) -> None:
        """A string field without `format` keeps taking whatever the page said."""
        schema = {"type": "object", "properties": {"datePublished": {"type": "string"}}}
        assert values(schema, {"datePublished": "Feb 08, 2022"})["datePublished"] == "Feb 08, 2022"


class TestListsAndWrappers:
    """Values the page put inside a list.

    `_lookup` used to recurse into dicts only, so anything a publisher wrapped in a list was
    invisible: an article with two authors reported none, and every WooCommerce product
    reported no price at all — WooCommerce always wraps `offers` in a one-element array.
    That is a large share of the web's shops answering "no price" for a reason that has
    nothing to do with the page.
    """

    def test_finds_a_key_inside_a_list_of_objects(self) -> None:
        schema = {"type": "object", "properties": {"price": {"type": "number"}}}
        payload = {"@type": "Product", "offers": [{"@type": "Offer", "price": "19.99"}]}
        assert values(schema, payload)["price"] == 19.99

    def test_a_one_element_list_satisfies_an_object_field(self) -> None:
        """WooCommerce's shape: `offers` is always an array, even for one offer."""
        schema = {
            "type": "object",
            "properties": {
                "offers": {"type": "object", "properties": {"price": {"type": "number"}}}
            },
        }
        payload = {"@type": "Product", "offers": [{"@type": "Offer", "price": "1.299,00"}]}
        assert values(schema, payload)["offers.price"] == 1299.0

    def test_the_first_author_of_several(self) -> None:
        """21% of article author values are a list. One byline is not every byline, but it
        is the one the page leads with, and it beats reporting none."""
        schema = {
            "type": "object",
            "properties": {
                "author": {"type": "object", "properties": {"name": {"type": "string"}}}
            },
        }
        payload = {
            "@type": "Article",
            "author": [{"@type": "Person", "name": "Ada"}, {"@type": "Person", "name": "Grace"}],
        }
        assert values(schema, payload)["author.name"] == "Ada"

    def test_an_aggregate_offer_does_not_supply_a_price(self) -> None:
        """`AggregateOffer.lowPrice` is the cheapest variant, not the price of the thing.

        WooCommerce emits one whenever a variable product's cheapest and dearest variants
        differ, so this is the common case on exactly the pages where getting it wrong is
        most visible.
        """
        schema = {
            "type": "object",
            "properties": {
                "offers": {"type": "object", "properties": {"price": {"type": "number"}}}
            },
        }
        payload = {
            "@type": "Product",
            "offers": [{"@type": "AggregateOffer", "lowPrice": "89.00", "highPrice": "400.00"}],
        }
        assert values(schema, payload) == {}

    def test_a_shallower_match_still_wins(self) -> None:
        """Entering lists must not let a deep value outrank one at the top level."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        payload = {"name": "Right", "items": [{"name": "Wrong"}]}
        assert values(schema, payload)["name"] == "Right"
