"""config.py is names and values, and nothing else.

Two promises. Every setting is a plain constant in one file, with no class or function
around it -- so a reader can open it and change a number. And every old import path still
works, because the code that groups settings for a call (`FetchConfig`, `SiteConfig`...)
lives beside the code it configures and reads its defaults from that file.
"""

from __future__ import annotations

import ast
import inspect

import pytest


class TestFlatFile:
    def test_config_holds_only_names_and_values(self) -> None:
        """No classes, no functions, no imports: a value per name, a comment above it."""
        from webgraph import config

        tree = ast.parse(inspect.getsource(config))
        for node in tree.body:
            assert isinstance(node, ast.Assign | ast.Expr), ast.dump(node)[:80]
            if isinstance(node, ast.Assign):
                assert all(isinstance(t, ast.Name) and t.id.isupper() for t in node.targets)

    def test_every_setting_is_commented(self) -> None:
        """A number with no words beside it is a number nobody dares change."""
        from webgraph import config

        lines = inspect.getsource(config).split("\n")
        bare = []
        for i, line in enumerate(lines):
            if line and line[0].isupper() and "=" in line:
                above = lines[i - 1].strip() if i else ""
                if not (above.startswith("#") or (above and above[0].isupper()) or "#" in line):
                    bare.append(line.split("=")[0].strip())
        assert bare == [], bare

    @pytest.mark.parametrize(
        ("module", "name", "setting"),
        [
            ("webgraph.fetch.static", "DEFAULT_USER_AGENT", "USER_AGENT"),
            ("webgraph.fetch.render", "MIN_SALVAGED_TEXT", "MIN_SALVAGED_TEXT"),
            ("webgraph.resolve", "MISSING_STATUSES", "MISSING_STATUSES"),
            ("webgraph.boilerplate", "MIN_PAGES", "CHROME_MIN_PAGES"),
            ("webgraph.pagetype", "DEFAULT_MIN_CONFIDENCE", "ROUTER_MIN_CONFIDENCE"),
            ("webgraph.dom.rich", "LONG_CELL_CHARS", "LONG_CELL_CHARS"),
            ("webgraph.graph.retrieve", "B", "GRAPH_BM25_B"),
        ],
    )
    def test_modules_read_their_constants_from_config(self, module: str, name: str, setting: str) -> None:
        import importlib

        from webgraph import config

        assert getattr(importlib.import_module(module), name) == getattr(config, setting)

    @pytest.mark.parametrize(
        ("module", "name", "field", "setting"),
        [
            ("webgraph.fetch.static", "FetchConfig", "timeout_seconds", "FETCH_TIMEOUT_SECONDS"),
            ("webgraph.fetch.render", "RenderConfig", "timeout_ms", "RENDER_TIMEOUT_MS"),
            ("webgraph.site", "SiteConfig", "max_depth", "CRAWL_MAX_DEPTH"),
            ("webgraph.site", "SiteConfig", "strict_domain", "CRAWL_STRICT_DOMAIN"),
            ("webgraph.main_content", "MainContentConfig", "cost_ratio", "CONTENT_COST_RATIO"),
            ("webgraph.dom.reading_order", "OrderingConfig", "max_depth", "ORDER_MAX_DEPTH"),
        ],
    )
    def test_config_classes_default_to_the_file(self, module: str, name: str, field: str, setting: str) -> None:
        import importlib

        from webgraph import config

        cls = getattr(importlib.import_module(module), name)
        assert getattr(cls(), field) == getattr(config, setting)


class TestSettings:
    def test_defaults_come_from_config(self) -> None:
        from webgraph import config
        from webgraph.settings import Settings

        settings = Settings.from_env({})
        assert settings.max_pages == config.DEPLOY_MAX_PAGES
        assert settings.max_concurrent_renders == config.DEPLOY_MAX_CONCURRENT_RENDERS
        assert settings.max_browsers == config.DEPLOY_MAX_BROWSERS
        assert settings.trace_dir is None
        assert settings.allowed_origins == ()

    def test_reads_every_variable(self) -> None:
        from pathlib import Path

        from webgraph.settings import Settings

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
        from webgraph.settings import Settings

        assert Settings.from_env({"WEBGRAPH_MAX_PAGES": "", "WEBGRAPH_TRACE_DIR": " "}).max_pages == 0
