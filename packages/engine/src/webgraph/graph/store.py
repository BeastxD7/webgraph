"""Keep graphs across process restarts.

A crawl is the expensive part -- minutes of network and browser time -- and the graph is
what it produces. Holding it only in memory means a service restart silently throws away
work that cost far more than the disk it would have taken, and every question asked
afterwards re-crawls the site.

Shape
-----
One JSONL file per site, named by a slug of the root plus a hash of it. The slug makes the
directory readable; the hash makes the name unique, since two roots can slugify the same way.

Deliberately not a database. The format is the export format, so a stored graph is also a
file you can hand to something else, `webgraph ask --graph` reads it directly, and there is
no migration to write when the schema changes -- an unreadable file is skipped and the site
is re-crawled.

Writes go through a temporary file and a rename, which is atomic on every filesystem this
runs on. A crawl interrupted mid-write would otherwise leave a truncated graph that looks
valid and is not.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Final

from webgraph.graph.export import load_jsonl, write_jsonl
from webgraph.graph.model import SiteGraph

__all__ = ["GraphStore", "default_graph_dir"]

_SLUG = re.compile(r"[^a-z0-9]+")

ENV_VAR: Final[str] = "WEBGRAPH_GRAPH_DIR"


def default_graph_dir() -> Path:
    """Where graphs are kept, overridable with `WEBGRAPH_GRAPH_DIR`."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / "webgraph" / "graphs"


class GraphStore:
    """A directory of stored site graphs."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory) if directory else default_graph_dir()

    def path_for(self, root: str) -> Path:
        slug = _SLUG.sub("-", root.lower()).strip("-")[:60] or "site"
        digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:10]
        return self.directory / f"{slug}.{digest}.jsonl"

    def save(self, graph: SiteGraph, root: str | None = None) -> Path:
        """Write `graph`, atomically. Returns the path written."""
        target = self.path_for(root or graph.root)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f".{os.getpid()}.tmp")
        try:
            write_jsonl(graph, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def load(self, root: str) -> SiteGraph | None:
        """Read a stored graph, or `None` if there is none or it is unreadable.

        Unreadable is treated as absent on purpose: a corrupt or outdated file should cost a
        re-crawl, not an error the caller has to handle.
        """
        path = self.path_for(root)
        if not path.exists():
            return None
        try:
            return load_jsonl(path)
        except Exception:
            return None

    def stored(self) -> list[tuple[str, int, float]]:
        """Every stored graph as (root, bytes, modified-at), newest first."""
        if not self.directory.exists():
            return []
        rows: list[tuple[str, int, float]] = []
        for path in self.directory.glob("*.jsonl"):
            try:
                with path.open(encoding="utf-8") as handle:
                    first = handle.readline()
                root = first.split('"root": "', 1)[-1].split('"', 1)[0] if first else ""
                stat = path.stat()
                rows.append((root or path.stem, stat.st_size, stat.st_mtime))
            except OSError:
                continue
        return sorted(rows, key=lambda row: -row[2])

    def prune(self, keep: int = 32, max_age_days: float = 30.0) -> int:
        """Drop the oldest graphs. Returns how many were removed.

        A cache that only grows is a disk leak with a friendly name.
        """
        if not self.directory.exists():
            return 0
        files = sorted(self.directory.glob("*.jsonl"), key=lambda p: -p.stat().st_mtime)
        cutoff = time.time() - max_age_days * 86_400
        removed = 0
        for index, path in enumerate(files):
            if index >= keep or path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed
