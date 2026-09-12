"""The one file every knob lives in.

These tests pin two promises: every configuration a person might change is importable from
`webgraph.config`, and the old import paths still work -- the definitions moved, nothing
else did.
"""

from __future__ import annotations

import pytest


class TestOneFile:
    def test_every_config_class_is_here(self) -> None:
        from webgraph import config

        for name in ("FetchConfig", "RenderConfig", "SiteConfig", "MainContentConfig", "OrderingConfig", "Settings", "Strategy"):
            assert hasattr(config, name), name

    @pytest.mark.parametrize(
        ("module", "name"),
        [
            ("webgraph.fetch.static", "FetchConfig"),
            ("webgraph.fetch.static", "DEFAULT_USER_AGENT"),
            ("webgraph.fetch.render", "RenderConfig"),
            ("webgraph.fetch.render", "MIN_SALVAGED_TEXT"),
            ("webgraph.resolve", "Strategy"),
            ("webgraph.resolve", "MISSING_STATUSES"),
            ("webgraph.site", "SiteConfig"),
            ("webgraph.main_content", "MainContentConfig"),
            ("webgraph.dom.reading_order", "OrderingConfig"),
            ("webgraph.boilerplate", "MIN_PAGES"),
            ("webgraph.pagetype", "DEFAULT_MIN_CONFIDENCE"),
            ("webgraph.dom.rich", "LONG_CELL_CHARS"),
        ],
    )
    def test_the_old_import_paths_still_work(self, module: str, name: str) -> None:
        """Moving a definition must not break a single caller."""
        import importlib

        from webgraph import config

        assert getattr(importlib.import_module(module), name) is getattr(config, name)

    def test_config_imports_nothing_from_the_engine(self) -> None:
        """It must stay importable first, by everything, without a cycle."""
        import ast
        import inspect

        from webgraph import config

        tree = ast.parse(inspect.getsource(config))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom | ast.Import):
                names = [node.module] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
                for name in names:
                    assert not (name or "").startswith("webgraph"), name


class TestSettings:
    def test_defaults_when_nothing_is_set(self) -> None:
        from webgraph.config import Settings

        settings = Settings.from_env({})
        assert settings.max_pages == 0
        assert settings.max_concurrent_renders == 2
        assert settings.max_browsers == 6
        assert settings.trace_dir is None
        assert settings.allowed_origins == ()

    def test_reads_every_variable(self) -> None:
        from pathlib import Path

        from webgraph.config import Settings

        settings = Settings.from_env(
            {
                "WEBGRAPH_MAX_PAGES": "25",
                "WEBGRAPH_MAX_CONCURRENCY": "3",
                "WEBGRAPH_MAX_CONCURRENT_RENDERS": "1",
                "WEBGRAPH_MAX_CONCURRENT_CRAWLS": "2",
                "WEBGRAPH_MAX_BROWSERS": "4",
                "WEBGRAPH_TRACE_DIR": "/var/run/traces",
                "WEBGRAPH_GRAPH_DIR": "/var/lib/graphs",
                "WEBGRAPH_ALLOWED_ORIGINS": "https://a.example, https://b.example,,",
                "WEBGRAPH_CHROMIUM_ARGS": "--disable-gpu",
            }
        )
        assert settings.max_pages == 25
        assert settings.max_concurrency == 3
        assert settings.max_concurrent_renders == 1
        assert settings.max_concurrent_crawls == 2
        assert settings.max_browsers == 4
        assert settings.trace_dir == Path("/var/run/traces")
        assert settings.graph_dir == Path("/var/lib/graphs")
        assert settings.allowed_origins == ("https://a.example", "https://b.example")
        assert settings.chromium_args == "--disable-gpu"

    def test_a_blank_value_means_unset(self) -> None:
        """A deploy script that exports `WEBGRAPH_MAX_PAGES=` must not crash the process."""
        from webgraph.config import Settings

        assert Settings.from_env({"WEBGRAPH_MAX_PAGES": "", "WEBGRAPH_TRACE_DIR": " "}).max_pages == 0
