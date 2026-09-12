"""What a deployment can set from the outside, read once.

The defaults come from `webgraph.config` (the `DEPLOY_*` names); an environment variable
named `WEBGRAPH_*` beside each of them overrides it at process start. `Settings.from_env`
is the one place those variables are read, so the list of things a deployment can set is
that method and not a grep.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from webgraph import config

__all__ = ["SETTINGS", "Settings"]


@dataclass(frozen=True, slots=True)
class Settings:
    """What a deployment can set from the outside. Read once, by `from_env`.

    Every variable is prefixed `WEBGRAPH_`. Zero means "no cap" for the caps.
    """

    max_pages: int = config.DEPLOY_MAX_PAGES
    """`WEBGRAPH_MAX_PAGES`: hard ceiling on pages per crawl, whatever a client asks for."""

    max_concurrency: int = config.DEPLOY_MAX_CONCURRENCY
    """`WEBGRAPH_MAX_CONCURRENCY`: ceiling on parallel fetches within one crawl."""

    max_concurrent_renders: int = config.DEPLOY_MAX_CONCURRENT_RENDERS
    """`WEBGRAPH_MAX_CONCURRENT_RENDERS`: browser pages open at once across the API."""

    max_concurrent_crawls: int = config.DEPLOY_MAX_CONCURRENT_CRAWLS
    """`WEBGRAPH_MAX_CONCURRENT_CRAWLS`: crawls the API runs at once; the rest queue."""

    max_browsers: int = config.DEPLOY_MAX_BROWSERS
    """`WEBGRAPH_MAX_BROWSERS`: live browsers across the whole process, roughly 150 MB
    resident each. Six suits a laptop with 16 GB; a 2 GB container cannot hold six, and the
    failure mode is the kernel killing the process, so the cap belongs where the memory
    budget is known."""

    trace_dir: Path | None = Path(config.DEPLOY_TRACE_DIR) if config.DEPLOY_TRACE_DIR else None
    """`WEBGRAPH_TRACE_DIR`: where run traces are written. The system temp directory when
    unset -- a trace is diagnostic, and a server that fills a disk with them by default has
    replaced one problem with another."""

    trace_file: Path | None = Path(config.DEPLOY_TRACE_FILE) if config.DEPLOY_TRACE_FILE else None
    """`WEBGRAPH_TRACE`: a single trace file for library and CLI use, when set."""

    graph_dir: Path | None = Path(config.DEPLOY_GRAPH_DIR) if config.DEPLOY_GRAPH_DIR else None
    """`WEBGRAPH_GRAPH_DIR`: where crawled graphs are kept between requests."""

    allowed_origins: tuple[str, ...] = tuple(config.DEPLOY_ALLOWED_ORIGINS)
    """`WEBGRAPH_ALLOWED_ORIGINS`: browser origins the API answers, comma-separated. Never
    `*` -- this service fetches arbitrary URLs on the caller's behalf."""

    chromium_args: str = config.DEPLOY_CHROMIUM_ARGS
    """`WEBGRAPH_CHROMIUM_ARGS`: extra flags for the browser, shell-split."""

    @classmethod
    def from_env(cls, environ: os._Environ[str] | dict[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ

        def integer(name: str, default: int) -> int:
            raw = env.get(name, "").strip()
            return int(raw) if raw else default

        def path(name: str) -> Path | None:
            raw = env.get(name, "").strip()
            return Path(raw) if raw else None

        origins = tuple(o.strip() for o in env.get("WEBGRAPH_ALLOWED_ORIGINS", "").split(",") if o.strip())
        return cls(
            max_pages=integer("WEBGRAPH_MAX_PAGES", config.DEPLOY_MAX_PAGES),
            max_concurrency=integer("WEBGRAPH_MAX_CONCURRENCY", config.DEPLOY_MAX_CONCURRENCY),
            max_concurrent_renders=integer("WEBGRAPH_MAX_CONCURRENT_RENDERS", config.DEPLOY_MAX_CONCURRENT_RENDERS),
            max_concurrent_crawls=integer("WEBGRAPH_MAX_CONCURRENT_CRAWLS", config.DEPLOY_MAX_CONCURRENT_CRAWLS),
            max_browsers=integer("WEBGRAPH_MAX_BROWSERS", config.DEPLOY_MAX_BROWSERS),
            trace_dir=path("WEBGRAPH_TRACE_DIR") or (Path(config.DEPLOY_TRACE_DIR) if config.DEPLOY_TRACE_DIR else None),
            trace_file=path("WEBGRAPH_TRACE") or (Path(config.DEPLOY_TRACE_FILE) if config.DEPLOY_TRACE_FILE else None),
            graph_dir=path("WEBGRAPH_GRAPH_DIR") or (Path(config.DEPLOY_GRAPH_DIR) if config.DEPLOY_GRAPH_DIR else None),
            allowed_origins=origins or tuple(config.DEPLOY_ALLOWED_ORIGINS),
            chromium_args=env.get("WEBGRAPH_CHROMIUM_ARGS", "") or config.DEPLOY_CHROMIUM_ARGS,
        )


SETTINGS: Final[Settings] = Settings.from_env()
"""The process's settings, read once at import. Tests that need different values build a
`Settings` of their own or monkeypatch the module-level names that consume this one."""


def describe_config() -> dict[str, dict[str, object]]:
    """Every setting in `webgraph.config`, with its value and the comment above it.

    Parsed from the file's source rather than declared twice: the comment beside a setting
    is its documentation, and a second copy in a docstring or a schema would drift. Used by
    the API to offer the settings page its defaults and their meanings.
    """
    import ast
    import inspect

    from webgraph import config

    source = inspect.getsource(config)
    lines = source.split("\n")
    tree = ast.parse(source)
    described: dict[str, dict[str, object]] = {}
    section = ""
    for index, line in enumerate(lines):
        # Section banners: a "# ===" line, a "# Title" line, a "# ===" line.
        if line.startswith("# ===") and index + 1 < len(lines) and lines[index + 1].startswith("# "):
            section = lines[index + 1][2:].strip()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        name = node.targets[0].id if isinstance(node.targets[0], ast.Name) else None
        if not name:
            continue
        # The comment block immediately above, and any trailing comment on the line.
        comment: list[str] = []
        cursor = node.lineno - 2
        while cursor >= 0 and lines[cursor].startswith("#") and not lines[cursor].startswith("# ==="):
            comment.insert(0, lines[cursor][1:].strip())
            cursor -= 1
        trailing = lines[node.lineno - 1].partition("#")[2].strip()
        if trailing:
            comment.append(trailing)
        # Which banner this setting sits under.
        heading = ""
        for index in range(node.lineno - 1, -1, -1):
            if lines[index].startswith("# ===") and index + 1 < len(lines) and lines[index + 1].startswith("# "):
                heading = lines[index + 1][2:].strip()
                break
        value = getattr(config, name)
        described[name] = {
            "value": sorted(value) if isinstance(value, frozenset | set) else value,
            "comment": " ".join(comment),
            "section": heading or section,
        }
    return described
