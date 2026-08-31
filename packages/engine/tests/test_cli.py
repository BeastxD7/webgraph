"""CLI tests. Local-file inputs only, so nothing here touches the network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from webgraph.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = Path(__file__).resolve().parents[3] / "benchmark" / "corpus-v0"


@pytest.fixture
def page(tmp_path: Path) -> Path:
    path = tmp_path / "p.html"
    path.write_text(
        '<html><head><script type="application/ld+json">'
        '{"@type":"Product","name":"Widget","offers":{"price":"49"}}'
        "</script></head><body><h1>Widget</h1><p>Body copy here.</p></body></html>",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def schema(tmp_path: Path) -> Path:
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "offers": {"type": "object", "properties": {"price": {"type": "number"}}},
            },
        }),
        encoding="utf-8",
    )
    return path


class TestTextCommand:
    def test_prints_reading_ordered_text(
        self, page: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["-q", "text", str(page)]) == 0
        assert "Widget" in capsys.readouterr().out

    def test_json_mode_includes_diagnostics(
        self, page: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["-q", "text", str(page), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["payloads"] == ["json-ld"]
        assert payload["content_hash"]
        assert payload["blocks"] > 0

    def test_script_content_not_in_output(
        self, page: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["-q", "text", str(page)])
        assert "ld+json" not in capsys.readouterr().out


class TestExtractCommand:
    def test_emits_facts_with_provenance(
        self, page: Path, schema: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["-q", "extract", str(page), "--schema", str(schema)]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["facts"]["name"]["value"] == "Widget"
        assert payload["facts"]["offers.price"]["value"] == 49.0
        assert payload["facts"]["name"]["extractor"] == "structured-data"
        assert 0.0 < payload["facts"]["name"]["confidence"] <= 1.0

    def test_returns_nonzero_when_nothing_extracted(
        self, tmp_path: Path, schema: Path
    ) -> None:
        empty = tmp_path / "empty.html"
        empty.write_text("<html><body><p>no structured data</p></body></html>", encoding="utf-8")
        assert main(["-q", "extract", str(empty), "--schema", str(schema)]) == 1


class TestBenchCommand:
    @pytest.mark.skipif(not CORPUS.exists(), reason="benchmark corpus not present")
    def test_runs_shipped_corpus(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["bench", str(CORPUS)]) == 0
        out = capsys.readouterr().out
        assert "Page-level success" in out
        assert "PER-FIELD ACCURACY" in out

    @pytest.mark.skipif(not CORPUS.exists(), reason="benchmark corpus not present")
    def test_threshold_gate_fails_below_target(self) -> None:
        """The CI gate must actually fail, not just print."""
        assert main(["bench", str(CORPUS), "--min-page-success", "0.99"]) == 1

    @pytest.mark.skipif(not CORPUS.exists(), reason="benchmark corpus not present")
    def test_threshold_gate_passes_at_current_level(self) -> None:
        assert main(["bench", str(CORPUS), "--min-page-success", "0.80"]) == 0


class TestArgumentHandling:
    def test_missing_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit):
            main([])

    def test_unknown_file_is_treated_as_url_and_fails_cleanly(self) -> None:
        with pytest.raises(SystemExit):
            main(["-q", "text", "http://127.0.0.1:9/nope"])
