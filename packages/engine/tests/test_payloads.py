"""Structured-payload extraction tests.

Fixtures mirror real markup shapes rather than idealised ones: JSON-LD with `@graph` and
trailing commas, RSC flight data split across `push` calls mid-value, and microdata with
nested scopes -- all of which naive parsers get wrong.
"""

from __future__ import annotations

import json

import pytest

from webgraph.dom.blocks import parse_html
from webgraph.structured.payloads import (
    extract_initial_state,
    extract_json_ld,
    extract_microdata,
    extract_next_data,
    extract_open_graph,
    extract_payloads,
    extract_rsc_flight,
    find_balanced_json,
)
from webgraph.types import PayloadSource


class TestBalancedJson:
    def test_stops_at_matching_brace(self) -> None:
        text = 'var x = {"a": {"b": 1}}; more code {"unrelated": 2}'
        assert find_balanced_json(text, 8) == '{"a": {"b": 1}}'

    def test_ignores_braces_inside_strings(self) -> None:
        """A brace in a string literal must not change nesting depth."""
        text = '{"a": "not } a brace", "b": 1}'
        assert find_balanced_json(text, 0) == text

    def test_handles_escaped_quotes(self) -> None:
        text = r'{"a": "he said \"hi\" }", "b": 2}'
        assert find_balanced_json(text, 0) == text

    def test_arrays(self) -> None:
        assert find_balanced_json('[1, [2, 3], 4] trailing', 0) == "[1, [2, 3], 4]"

    def test_unterminated_returns_none(self) -> None:
        assert find_balanced_json('{"a": 1', 0) is None

    def test_non_json_start_returns_none(self) -> None:
        assert find_balanced_json("hello", 0) is None


class TestJsonLd:
    def test_simple_object(self) -> None:
        html = """
        <html><head><script type="application/ld+json">
        {"@type": "Product", "name": "Widget", "price": 49}
        </script></head><body><p>x</p></body></html>
        """
        payloads = extract_json_ld(parse_html(html))
        assert len(payloads) == 1
        assert payloads[0].data["name"] == "Widget"
        assert payloads[0].source is PayloadSource.JSON_LD

    def test_array_of_entities(self) -> None:
        html = """
        <html><head><script type="application/ld+json">
        [{"@type":"A","n":1},{"@type":"B","n":2}]
        </script></head><body><p>x</p></body></html>
        """
        assert len(extract_json_ld(parse_html(html))) == 2

    def test_graph_container_is_unwrapped(self) -> None:
        html = """
        <html><head><script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[{"@type":"X","n":1},{"@type":"Y","n":2}]}
        </script></head><body><p>x</p></body></html>
        """
        payloads = extract_json_ld(parse_html(html))
        types = {p.data.get("@type") for p in payloads}
        assert types == {"X", "Y"}

    def test_trailing_comma_is_recovered(self) -> None:
        """Hand-authored JSON-LD routinely ships trailing commas."""
        html = """
        <html><head><script type="application/ld+json">
        {"@type": "Product", "name": "Widget",}
        </script></head><body><p>x</p></body></html>
        """
        payloads = extract_json_ld(parse_html(html))
        assert payloads and payloads[0].data["name"] == "Widget"

    def test_uppercase_mime_type(self) -> None:
        html = """
        <html><head><script type="APPLICATION/LD+JSON">{"@type":"T"}</script></head>
        <body><p>x</p></body></html>
        """
        assert len(extract_json_ld(parse_html(html))) == 1

    def test_unparseable_block_is_skipped_not_raised(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">{ this is not json </script>
        <script type="application/ld+json">{"@type":"Good"}</script>
        </head><body><p>x</p></body></html>
        """
        payloads = extract_json_ld(parse_html(html))
        assert len(payloads) == 1
        assert payloads[0].data["@type"] == "Good"

    def test_xpath_recorded(self) -> None:
        html = """
        <html><head><script type="application/ld+json">{"@type":"T"}</script></head>
        <body><p>x</p></body></html>
        """
        assert extract_json_ld(parse_html(html))[0].xpath


class TestNextData:
    def test_reads_pages_router_payload(self) -> None:
        payload = {"props": {"pageProps": {"title": "Hello"}}}
        html = f"""
        <html><body><p>x</p>
        <script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>
        </body></html>
        """
        payloads = extract_next_data(parse_html(html))
        assert len(payloads) == 1
        assert payloads[0].data["props"]["pageProps"]["title"] == "Hello"
        assert payloads[0].source is PayloadSource.NEXT_DATA

    def test_absent_yields_nothing(self) -> None:
        assert extract_next_data(parse_html("<html><body><p>x</p></body></html>")) == []


class TestRscFlight:
    def test_reassembles_chunks(self) -> None:
        """Chunks are JS string literals that must be decoded then concatenated."""
        line = '1:{"title":"Streamed","price":42}\n'
        first, second = line[:12], line[12:]
        html = (
            "<html><body><p>x</p><script>"
            f"self.__next_f.push([1,{json.dumps(first)}]);"
            f"self.__next_f.push([1,{json.dumps(second)}]);"
            "</script></body></html>"
        )
        payloads = extract_rsc_flight(html)
        assert len(payloads) == 1
        assert payloads[0].data == {"title": "Streamed", "price": 42}
        assert payloads[0].source is PayloadSource.RSC_FLIGHT

    def test_split_mid_value_still_parses(self) -> None:
        line = '2:{"deeply":{"nested":{"value":"ok"}}}\n'
        html = "<html><body><p>x</p><script>" + "".join(
            f"self.__next_f.push([1,{json.dumps(line[i:i + 7])}]);"
            for i in range(0, len(line), 7)
        ) + "</script></body></html>"
        payloads = extract_rsc_flight(html)
        assert payloads[0].data["deeply"]["nested"]["value"] == "ok"

    def test_non_json_lines_ignored(self) -> None:
        """Module-reference lines like `2:I[...]` carry no page data."""
        stream = '0:I["module"]\n1:{"real":"data"}\n'
        html = (
            "<html><body><p>x</p><script>"
            f"self.__next_f.push([1,{json.dumps(stream)}]);"
            "</script></body></html>"
        )
        payloads = extract_rsc_flight(html)
        assert len(payloads) == 1
        assert payloads[0].data == {"real": "data"}

    def test_no_flight_data(self) -> None:
        assert extract_rsc_flight("<html><body><p>x</p></body></html>") == []


class TestInitialState:
    @pytest.mark.parametrize(
        ("name", "expected_source"),
        [
            ("__NUXT__", PayloadSource.NUXT),
            ("__INITIAL_STATE__", PayloadSource.INITIAL_STATE),
            ("__APOLLO_STATE__", PayloadSource.INITIAL_STATE),
        ],
    )
    def test_reads_state_assignments(self, name: str, expected_source: PayloadSource) -> None:
        html = f'<html><body><script>window.{name} = {{"a": 1}};</script></body></html>'
        payloads = extract_initial_state(html)
        assert len(payloads) == 1
        assert payloads[0].data == {"a": 1}
        assert payloads[0].source is expected_source

    def test_function_call_form_is_skipped(self) -> None:
        """Nuxt 3 devalue payloads cannot be read without executing JS -- skip, don't guess."""
        html = '<html><body><script>window.__NUXT__ = (function(a){return {b:a}})(1);</script></body></html>'
        assert extract_initial_state(html) == []

    def test_trailing_code_not_swallowed(self) -> None:
        html = '<html><body><script>window.__NUXT__={"a":1};var other={"b":2};</script></body></html>'
        payloads = extract_initial_state(html)
        assert len(payloads) == 1
        assert payloads[0].data == {"a": 1}


class TestOpenGraph:
    def test_collects_og_and_twitter(self) -> None:
        html = """
        <html><head>
          <meta property="og:title" content="Title">
          <meta name="twitter:card" content="summary">
          <meta name="viewport" content="width=device-width">
        </head><body><p>x</p></body></html>
        """
        payloads = extract_open_graph(parse_html(html))
        assert payloads[0].data == {"og:title": "Title", "twitter:card": "summary"}

    def test_none_present(self) -> None:
        html = '<html><head><meta name="viewport" content="x"></head><body><p>y</p></body></html>'
        assert extract_open_graph(parse_html(html)) == []


class TestMicrodata:
    def test_flat_scope(self) -> None:
        html = """
        <html><body><div itemscope itemtype="https://schema.org/Person">
          <span itemprop="name">Ada</span>
          <span itemprop="jobTitle">Engineer</span>
        </div></body></html>
        """
        payloads = extract_microdata(parse_html(html))
        assert payloads[0].data["name"] == "Ada"
        assert payloads[0].data["@type"] == "https://schema.org/Person"

    def test_nested_scope_attaches_to_parent(self) -> None:
        html = """
        <html><body><div itemscope itemtype="https://schema.org/Product">
          <span itemprop="name">Widget</span>
          <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
            <span itemprop="price">49</span>
          </div>
        </div></body></html>
        """
        payloads = extract_microdata(parse_html(html))
        assert len(payloads) == 1, "nested scope must not emit a second top-level payload"
        assert payloads[0].data["offers"]["price"] == "49"

    def test_machine_readable_attribute_preferred(self) -> None:
        html = """
        <html><body><div itemscope>
          <time itemprop="date" datetime="2026-08-31">last Monday</time>
        </div></body></html>
        """
        assert extract_microdata(parse_html(html))[0].data["date"] == "2026-08-31"

    def test_repeated_property_becomes_list(self) -> None:
        html = """
        <html><body><div itemscope>
          <span itemprop="tag">a</span><span itemprop="tag">b</span>
        </div></body></html>
        """
        assert extract_microdata(parse_html(html))[0].data["tag"] == ["a", "b"]


class TestAggregate:
    def test_extract_payloads_runs_every_source(self) -> None:
        html = """
        <html><head>
          <script type="application/ld+json">{"@type":"Product","name":"W"}</script>
          <meta property="og:title" content="T">
        </head><body>
          <div itemscope itemtype="https://schema.org/Thing"><span itemprop="name">M</span></div>
          <script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>
          <script>window.__INITIAL_STATE__ = {"s": 1};</script>
        </body></html>
        """
        sources = {p.source for p in extract_payloads(parse_html(html), html)}
        assert sources == {
            PayloadSource.JSON_LD,
            PayloadSource.OPEN_GRAPH,
            PayloadSource.MICRODATA,
            PayloadSource.NEXT_DATA,
            PayloadSource.INITIAL_STATE,
        }

    def test_empty_page_yields_nothing(self) -> None:
        html = "<html><body><p>just text</p></body></html>"
        assert extract_payloads(parse_html(html), html) == ()
