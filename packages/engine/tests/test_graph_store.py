"""Keeping graphs across restarts.

A crawl costs minutes of network and browser time. Holding the result only in memory means a
restart throws it away and every question afterwards re-crawls the site.
"""

from __future__ import annotations

import os

from webgraph.graph.build import GraphBuilder
from webgraph.graph.store import GraphStore, default_graph_dir
from webgraph.pipeline import build_document

BASE = "https://example.com/"


def sample():
    builder = GraphBuilder(BASE)
    builder.add(
        build_document(
            "<html><body><h1>Home</h1><p>" + "content " * 40 + "</p></body></html>", BASE
        )
    )
    return builder.graph


class TestRoundTrip:
    def test_a_saved_graph_reads_back(self, tmp_path) -> None:
        store = GraphStore(tmp_path)
        original = sample()
        store.save(original)
        restored = store.load(BASE)
        assert restored is not None
        assert restored.describe() == original.describe()

    def test_an_absent_graph_is_none_not_an_error(self, tmp_path) -> None:
        assert GraphStore(tmp_path).load("https://never-crawled.test/") is None

    def test_a_corrupt_file_is_treated_as_absent(self, tmp_path) -> None:
        """A bad or outdated file should cost a re-crawl, not an error the caller handles."""
        store = GraphStore(tmp_path)
        path = store.path_for(BASE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json\n", encoding="utf-8")
        assert store.load(BASE) is None

    def test_two_roots_never_share_a_file(self, tmp_path) -> None:
        """Slugs collide; the hash is what keeps the name unique."""
        store = GraphStore(tmp_path)
        assert store.path_for("https://a.test/x/") != store.path_for("https://a.test/x")

    def test_no_temporary_file_is_left_behind(self, tmp_path) -> None:
        """Writes go through a rename so an interrupted crawl cannot leave a truncated graph
        that looks valid."""
        store = GraphStore(tmp_path)
        store.save(sample())
        assert list(tmp_path.glob("*.tmp")) == []


class TestPruning:
    def test_pruning_keeps_the_newest(self, tmp_path) -> None:
        """A cache that only grows is a disk leak with a friendly name."""
        store = GraphStore(tmp_path)
        for index in range(5):
            graph = sample()
            graph.root = f"{BASE}{index}"
            store.save(graph, f"{BASE}{index}")
        assert store.prune(keep=2) == 3
        assert len(list(tmp_path.glob("*.jsonl"))) == 2

    def test_pruning_an_empty_directory_is_harmless(self, tmp_path) -> None:
        assert GraphStore(tmp_path / "missing").prune() == 0

    def test_stored_lists_what_is_there(self, tmp_path) -> None:
        store = GraphStore(tmp_path)
        store.save(sample())
        rows = store.stored()
        assert len(rows) == 1
        assert rows[0][0] == BASE


class TestLocation:
    def test_the_directory_is_overridable(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("WEBGRAPH_GRAPH_DIR", str(tmp_path / "elsewhere"))
        assert default_graph_dir() == tmp_path / "elsewhere"

    def test_it_defaults_under_the_cache_directory(self, monkeypatch) -> None:
        monkeypatch.delenv("WEBGRAPH_GRAPH_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/cache-test")
        assert default_graph_dir() == __import__("pathlib").Path(
            "/tmp/cache-test/webgraph/graphs"
        )
        assert os.sep in str(default_graph_dir())
