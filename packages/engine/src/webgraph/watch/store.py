"""Where a watch keeps what it saw: one SQLite file, standard library only.

A watch is a site and a configuration; a run is one crawl of it; a page is what one run
saw at one address; a change is what a run found different from the run before. All four
live in one file under the cache directory (`~/.cache/webgraph/watch.sqlite3`,
`XDG_CACHE_HOME` and `WEBGRAPH_WATCH_DB` respected), beside the graphs.

SQLite rather than the graph store's JSONL because a watch is queried, not exported:
"changes since Tuesday", "the last finished run", "every page of run 12". Each of those is
one indexed query here and a full read there. No ORM and no migration framework: the
schema is created if absent and never altered in place -- a column added later is added
with `ALTER TABLE ... ADD COLUMN` in `_migrate`, which is the whole migration story.

Connections are opened per operation and closed after it. A run happens on a worker
thread while the API answers reads on another, and SQLite's rule is one connection per
thread; opening one costs microseconds against a crawl that costs minutes.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from webgraph.settings import Settings

__all__ = ["Change", "PageRecord", "Run", "Watch", "WatchStore", "default_watch_db"]


def default_watch_db() -> Path:
    """The watch database, overridable with `WEBGRAPH_WATCH_DB`."""
    override = Settings.from_env().watch_db
    if override is not None:
        return override.expanduser()
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / "webgraph" / "watch.sqlite3"


@dataclass(frozen=True, slots=True)
class Watch:
    id: str
    root: str
    config: dict[str, Any]
    """Crawl settings (`SiteConfig` fields by name) and watch settings (`noise`,
    `noise_patterns`), as given to `create_watch`."""

    created_at: float
    schedule_seconds: int = 0
    """How often the owner means to run it. Advisory: nothing in the engine schedules --
    `webgraph watch run` is what a cron entry or a GitHub Action calls."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "root": self.root,
            "config": self.config,
            "created_at": self.created_at,
            "schedule_seconds": self.schedule_seconds,
        }


@dataclass(frozen=True, slots=True)
class Run:
    id: int
    watch_id: str
    started_at: float
    finished_at: float | None = None
    pages_ok: int = 0
    pages_failed: int = 0
    stopped_by: str | None = None

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "watch_id": self.watch_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pages_ok": self.pages_ok,
            "pages_failed": self.pages_failed,
            "stopped_by": self.stopped_by,
        }


@dataclass(frozen=True, slots=True)
class PageRecord:
    """What one run saw at one address."""

    url: str
    content_hash: str = ""
    title: str = ""
    markdown: str = ""
    """The content Markdown the sections were cut from (the page with chrome removed, or
    the whole page when nothing was removed). Stored as a blob, not a path: a watch's pages
    are small, and a row that points at a file is a row that can dangle."""

    fetched_at: float = 0.0
    strategy: str | None = None
    error: str | None = None
    sections: tuple[dict[str, Any], ...] = ()
    """`{"heading", "level", "text"}` per heading-scoped section, in reading order. Kept
    beside the Markdown so the next run diffs against them without cutting them again."""

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class Change:
    """One page that differed from the previous run, with the sections that did."""

    id: int
    run_id: int
    watch_id: str
    url: str
    kind: str
    """`added`, `removed` or `changed`."""

    detected_at: float
    before_hash: str = ""
    after_hash: str = ""
    title: str = ""
    sections: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    """`{"kind": added|removed|edited, "heading", "before", "after"}` -- the provenance:
    which part of the page, in the page's own words."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "watch_id": self.watch_id,
            "url": self.url,
            "kind": self.kind,
            "detected_at": self.detected_at,
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "title": self.title,
            "sections": list(self.sections),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    id TEXT PRIMARY KEY,
    root TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    schedule_seconds INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id TEXT NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    started_at REAL NOT NULL,
    finished_at REAL,
    pages_ok INTEGER NOT NULL DEFAULT 0,
    pages_failed INTEGER NOT NULL DEFAULT 0,
    stopped_by TEXT
);
CREATE INDEX IF NOT EXISTS runs_by_watch ON runs(watch_id, started_at);
CREATE TABLE IF NOT EXISTS pages (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    markdown TEXT NOT NULL DEFAULT '',
    fetched_at REAL NOT NULL,
    strategy TEXT,
    error TEXT,
    sections_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (run_id, url)
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    watch_id TEXT NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('added', 'removed', 'changed')),
    before_hash TEXT NOT NULL DEFAULT '',
    after_hash TEXT NOT NULL DEFAULT '',
    diff_json TEXT NOT NULL DEFAULT '{}',
    detected_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS changes_by_watch ON changes(watch_id, detected_at);
"""


class WatchStore:
    """The file, and every read and write of it."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_watch_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- watches ----------------------------------------------------------------------

    def create_watch(
        self, root: str, config: dict[str, Any] | None = None, *, schedule_seconds: int = 0
    ) -> Watch:
        watch = Watch(
            id=uuid.uuid4().hex[:12],
            root=root,
            config=dict(config or {}),
            created_at=time.time(),
            schedule_seconds=int(schedule_seconds),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO watches (id, root, config_json, created_at, schedule_seconds) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    watch.id,
                    watch.root,
                    json.dumps(watch.config, sort_keys=True),
                    watch.created_at,
                    watch.schedule_seconds,
                ),
            )
        return watch

    def get_watch(self, watch_id: str) -> Watch | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM watches WHERE id = ?", (watch_id,)).fetchone()
        return _watch(row) if row else None

    def list_watches(self) -> list[Watch]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM watches ORDER BY created_at DESC").fetchall()
        return [_watch(row) for row in rows]

    def delete_watch(self, watch_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
        return cursor.rowcount > 0

    # -- runs -------------------------------------------------------------------------

    def start_run(self, watch_id: str) -> Run:
        started = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO runs (watch_id, started_at) VALUES (?, ?)", (watch_id, started)
            )
            run_id = cursor.lastrowid
        assert run_id is not None
        return Run(id=run_id, watch_id=watch_id, started_at=started)

    def finish_run(
        self, run_id: int, *, pages_ok: int, pages_failed: int, stopped_by: str | None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET finished_at = ?, pages_ok = ?, pages_failed = ?, stopped_by = ? "
                "WHERE id = ?",
                (time.time(), pages_ok, pages_failed, stopped_by, run_id),
            )

    def get_run(self, run_id: int) -> Run | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run(row) if row else None

    def runs(self, watch_id: str, *, limit: int = 50) -> list[Run]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE watch_id = ? ORDER BY started_at DESC LIMIT ?",
                (watch_id, limit),
            ).fetchall()
        return [_run(row) for row in rows]

    def last_finished_run(self, watch_id: str) -> Run | None:
        """The most recent run that finished, whatever it found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE watch_id = ? AND finished_at IS NOT NULL "
                "ORDER BY finished_at DESC LIMIT 1",
                (watch_id,),
            ).fetchone()
        return _run(row) if row else None

    def baseline_run(self, watch_id: str) -> Run | None:
        """The run the next one is compared against: the most recent that finished, read at
        least one page, and was not cut short by the caller or by an error.

        A run stopped at three pages by a closed browser tab is a finished run, but it is
        not what the site looked like; comparing against it would report every real page
        as `added` -- the false-positive storm a watch exists to avoid. A run that ended
        at a limit (`pages`, `time`, `queue`) *is* a baseline: a watch capped at 80 pages
        ends that way every time, and its 80 pages are the pages it watches."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE watch_id = ? AND finished_at IS NOT NULL "
                "AND pages_ok > 0 AND (stopped_by IS NULL OR stopped_by NOT IN ('stopped', 'error')) "
                "ORDER BY finished_at DESC LIMIT 1",
                (watch_id,),
            ).fetchone()
        return _run(row) if row else None

    # -- pages ------------------------------------------------------------------------

    def save_page(self, run_id: int, page: PageRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pages (run_id, url, content_hash, title, markdown, "
                "fetched_at, strategy, error, sections_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    page.url,
                    page.content_hash,
                    page.title,
                    page.markdown,
                    page.fetched_at or time.time(),
                    page.strategy,
                    page.error,
                    json.dumps(list(page.sections)),
                ),
            )

    def pages_of(self, run_id: int) -> dict[str, PageRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM pages WHERE run_id = ?", (run_id,)).fetchall()
        return {row["url"]: _page(row) for row in rows}

    # -- changes ----------------------------------------------------------------------

    def add_change(
        self,
        run_id: int,
        watch_id: str,
        *,
        url: str,
        kind: str,
        before_hash: str = "",
        after_hash: str = "",
        title: str = "",
        sections: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> Change:
        detected = time.time()
        diff = {"title": title, "sections": list(sections)}
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO changes (run_id, watch_id, url, kind, before_hash, after_hash, "
                "diff_json, detected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, watch_id, url, kind, before_hash, after_hash, json.dumps(diff), detected),
            )
            change_id = cursor.lastrowid
        assert change_id is not None
        return Change(
            id=change_id,
            run_id=run_id,
            watch_id=watch_id,
            url=url,
            kind=kind,
            detected_at=detected,
            before_hash=before_hash,
            after_hash=after_hash,
            title=title,
            sections=tuple(sections),
        )

    def count_changes(self, watch_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM changes WHERE watch_id = ?", (watch_id,)
            ).fetchone()
        return int(row[0]) if row else 0

    def changes(
        self,
        watch_id: str,
        *,
        since: float | None = None,
        run_id: int | None = None,
        limit: int = 500,
    ) -> list[Change]:
        """Changes newest first; `since` is an epoch timestamp, exclusive."""
        clauses = ["watch_id = ?"]
        params: list[Any] = [watch_id]
        if since is not None:
            clauses.append("detected_at > ?")
            params.append(float(since))
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM changes WHERE {' AND '.join(clauses)} "
                "ORDER BY detected_at DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [_change(row) for row in rows]


def _watch(row: sqlite3.Row) -> Watch:
    return Watch(
        id=row["id"],
        root=row["root"],
        config=json.loads(row["config_json"] or "{}"),
        created_at=row["created_at"],
        schedule_seconds=row["schedule_seconds"],
    )


def _run(row: sqlite3.Row) -> Run:
    return Run(
        id=row["id"],
        watch_id=row["watch_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        pages_ok=row["pages_ok"],
        pages_failed=row["pages_failed"],
        stopped_by=row["stopped_by"],
    )


def _page(row: sqlite3.Row) -> PageRecord:
    return PageRecord(
        url=row["url"],
        content_hash=row["content_hash"],
        title=row["title"],
        markdown=row["markdown"],
        fetched_at=row["fetched_at"],
        strategy=row["strategy"],
        error=row["error"],
        sections=tuple(json.loads(row["sections_json"] or "[]")),
    )


def _change(row: sqlite3.Row) -> Change:
    diff = json.loads(row["diff_json"] or "{}")
    return Change(
        id=row["id"],
        run_id=row["run_id"],
        watch_id=row["watch_id"],
        url=row["url"],
        kind=row["kind"],
        detected_at=row["detected_at"],
        before_hash=row["before_hash"],
        after_hash=row["after_hash"],
        title=str(diff.get("title") or ""),
        sections=tuple(diff.get("sections") or ()),
    )
