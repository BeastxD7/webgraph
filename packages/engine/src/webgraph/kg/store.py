"""One SQLite file per site: the knowledge graph, its evidence, and the model cache.

Why SQLite
----------
The embedded graph databases considered for the design are either archived (Kuzu), lagging
on PyPI (its fork), research prototypes (DuckPGQ), or source-available servers (FalkorDB,
Memgraph). SQLite is in the interpreter, has FTS5 (checked at open, with a pure-Python
fallback), needs no server, and a 200-page site is a few megabytes. k-hop expansion does
not need a graph query language: the `(subject, object, weight)` triples load into an
in-memory adjacency once per process, the way `SiteGraph` already works.

A database is an export target elsewhere in this engine; here it is a cache with an index.
Deleting the file costs a rebuild, which the LLM cache in the same file makes nearly free
-- so the file is also kept when a build is replaced, and only `llm_cache` and `build_runs`
survive a `replace_graph`.

The schema is versioned with `PRAGMA user_version`; an older file is recreated, not
migrated, for the same reason `graph/store.py` skips an unreadable graph.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from types import TracebackType
from typing import Any, Final

from webgraph.kg.merge import MergeResult
from webgraph.kg.model import Attribute, Entity, Evidence, Mention, Relation
from webgraph.kg.providers import Usage
from webgraph.settings import Settings
from webgraph.types import Extractor

__all__ = ["SCHEMA_VERSION", "KGStore", "default_kg_dir", "fts_query"]

SCHEMA_VERSION: Final[int] = 1
_SLUG = re.compile(r"[^a-z0-9]+")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'_-]*")

_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL, aliases TEXT NOT NULL,
    description TEXT, extractor TEXT NOT NULL, generic INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL DEFAULT '', last_seen TEXT NOT NULL DEFAULT '',
    evidence_count INTEGER NOT NULL DEFAULT 0, page_count INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS entities_type ON entities(type);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY, page_key TEXT NOT NULL, url TEXT NOT NULL, section_id TEXT NOT NULL,
    block_xpath TEXT NOT NULL, span_start INTEGER NOT NULL, span_end INTEGER NOT NULL,
    quote TEXT NOT NULL, content_hash TEXT NOT NULL DEFAULT '', crawled_at TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS evidence_page ON evidence(page_key);
CREATE TABLE IF NOT EXISTS mentions (
    entity_id TEXT NOT NULL, surface TEXT NOT NULL, evidence_id TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0, PRIMARY KEY (entity_id, evidence_id));
CREATE TABLE IF NOT EXISTS attributes (
    entity_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, unit TEXT NOT NULL DEFAULT '',
    evidence_id TEXT NOT NULL, PRIMARY KEY (entity_id, key, value, evidence_id));
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, predicate TEXT NOT NULL, object_id TEXT NOT NULL,
    fact TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 1.0, weight INTEGER NOT NULL DEFAULT 1,
    valid_from TEXT, valid_to TEXT, first_seen TEXT NOT NULL DEFAULT '', last_seen TEXT NOT NULL DEFAULT '',
    retired_at TEXT);
CREATE INDEX IF NOT EXISTS relations_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS relations_object ON relations(object_id);
CREATE TABLE IF NOT EXISTS relation_evidence (
    relation_id TEXT NOT NULL, evidence_id TEXT NOT NULL, PRIMARY KEY (relation_id, evidence_id));
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY, response TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0, model TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS build_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL NOT NULL, finished REAL,
    model TEXT NOT NULL DEFAULT '', stats TEXT NOT NULL DEFAULT '{}');
"""

_FTS: Final[str] = """
CREATE VIRTUAL TABLE IF NOT EXISTS entity_fts USING fts5(id UNINDEXED, name, aliases, description, tokenize='unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS relation_fts USING fts5(id UNINDEXED, fact, predicate, tokenize='unicode61');
"""

_GRAPH_TABLES: Final[tuple[str, ...]] = ("mentions", "attributes", "relation_evidence", "relations", "evidence", "entities")


def default_kg_dir() -> Path:
    """Where knowledge graphs are kept, overridable with `WEBGRAPH_KG_DIR`."""
    override = Settings.from_env().kg_dir
    if override is not None:
        return override.expanduser()
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / "webgraph" / "kg"


def fts_query(text: str) -> str:
    """A question as an FTS5 MATCH expression: each term quoted, joined with OR.

    A raw question (`?`, `:`, `-`, quotes) is a syntax error in MATCH; quoting each token
    and OR-ing them turns the question into a bag of words BM25 can rank against.
    """
    terms = [m.group(0).replace('"', "") for m in _WORD.finditer(text)]
    terms = [t for t in terms if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))


class _Rows:
    """What `_Connection.execute` returns: the rows, already fetched, plus `lastrowid`."""

    def __init__(self, rows: list[sqlite3.Row], lastrowid: int | None) -> None:
        self._rows = rows
        self.lastrowid = lastrowid

    def fetchone(self) -> sqlite3.Row | None:
        return self._rows[0] if self._rows else None

    def scalar(self) -> Any:
        """The first column of the first row; `None` when there is no row."""
        return self._rows[0][0] if self._rows else None

    def fetchall(self) -> list[sqlite3.Row]:
        return list(self._rows)

    def __iter__(self) -> Iterator[sqlite3.Row]:
        return iter(self._rows)


class _Connection:
    """One SQLite connection behind one re-entrant lock.

    A build calls the model from several threads and each thread reads and writes the
    LLM cache; `check_same_thread=False` allows that but sqlite3 does not make it safe, and
    two threads in one connection at once raise `InterfaceError`. Serialising every call is
    cheap next to a model call and keeps one file handle per store.
    """

    def __init__(self, path: Path) -> None:
        self._raw = sqlite3.connect(path, check_same_thread=False)
        self._raw.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def execute(self, sql: str, parameters: tuple[Any, ...] | list[Any] = ()) -> _Rows:
        # Rows are fetched under the lock: a cursor read after another thread has run a
        # statement on the same connection returns nothing, or someone else's row.
        with self._lock:
            cursor = self._raw.execute(sql, parameters)
            rows = cursor.fetchall() if cursor.description else []
            return _Rows(rows, cursor.lastrowid)

    def executescript(self, script: str) -> None:
        with self._lock:
            self._raw.executescript(script)

    def commit(self) -> None:
        with self._lock:
            self._raw.commit()

    def close(self) -> None:
        with self._lock:
            self._raw.close()

    def __enter__(self) -> _Connection:
        self._lock.acquire()
        self._raw.__enter__()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        try:
            self._raw.__exit__(exc_type, exc, tb)
        finally:
            self._lock.release()


class KGStore:
    """Open one site's knowledge graph. Use as a context manager or call `close()`."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _Connection(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._adjacency: dict[str, list[tuple[str, str, int]]] | None = None
        self.has_fts = self._init_schema()

    # -- lifecycle ------------------------------------------------------------------------

    @classmethod
    def path_for(cls, root: str, directory: Path | str | None = None) -> Path:
        base = Path(directory) if directory else default_kg_dir()
        slug = _SLUG.sub("-", root.lower()).strip("-")[:60] or "site"
        digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:10]
        return base / f"{slug}.{digest}.sqlite"

    @classmethod
    def for_site(cls, root: str, directory: Path | str | None = None) -> KGStore:
        return cls(cls.path_for(root, directory))

    @classmethod
    def exists_for(cls, root: str, directory: Path | str | None = None) -> bool:
        return cls.path_for(root, directory).exists()

    def _init_schema(self) -> bool:
        version = int(self._conn.execute("PRAGMA user_version").scalar() or 0)
        if version and version != SCHEMA_VERSION:
            # Recreate rather than migrate: the file is a cache of a build, and the LLM
            # responses it holds are keyed by prompt version, so they are worth dropping
            # too when the schema they fed has changed.
            for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index') AND name NOT LIKE 'sqlite_%'").fetchall():
                self._conn.execute(f"DROP TABLE IF EXISTS {row[0]}")
        self._conn.executescript(_SCHEMA)
        try:
            self._conn.executescript(_FTS)
            fts = True
        except sqlite3.OperationalError:
            fts = False
        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._conn.commit()
        return fts

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> KGStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
        self._conn.commit()

    def meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else None

    # -- writing --------------------------------------------------------------------------

    def replace_graph(self, result: MergeResult) -> None:
        """Write a merged graph, replacing what was there. The LLM cache is kept."""
        conn = self._conn
        with conn:
            for table in _GRAPH_TABLES:
                conn.execute(f"DELETE FROM {table}")
            if self.has_fts:
                conn.execute("DELETE FROM entity_fts")
                conn.execute("DELETE FROM relation_fts")
            evidence: dict[str, Evidence] = {}
            for entity in result.entities.values():
                conn.execute(
                    "INSERT INTO entities VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        entity.id, entity.type, entity.name, json.dumps(list(entity.aliases)), entity.description,
                        entity.extractor.value, int(entity.generic), entity.first_seen, entity.last_seen,
                        entity.evidence_count, len(entity.pages),
                    ),
                )
                if self.has_fts:
                    conn.execute(
                        "INSERT INTO entity_fts VALUES (?,?,?,?)",
                        (entity.id, entity.name, " ".join(entity.aliases), entity.description or ""),
                    )
                for mention in entity.mentions:
                    evidence[mention.evidence.id] = mention.evidence
                    conn.execute(
                        "INSERT OR IGNORE INTO mentions VALUES (?,?,?,?)",
                        (entity.id, mention.surface, mention.evidence.id, mention.confidence),
                    )
                for values in entity.attributes.values():
                    for attr in values:
                        evidence[attr.evidence.id] = attr.evidence
                        conn.execute(
                            "INSERT OR IGNORE INTO attributes VALUES (?,?,?,?,?)",
                            (entity.id, attr.key, attr.value, attr.unit, attr.evidence.id),
                        )
            for relation in result.relations.values():
                conn.execute(
                    "INSERT INTO relations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        relation.id, relation.subject_id, relation.predicate, relation.object_id, relation.fact,
                        relation.confidence, relation.weight, relation.valid_from, relation.valid_to,
                        relation.first_seen, relation.last_seen, relation.retired_at,
                    ),
                )
                if self.has_fts:
                    conn.execute(
                        "INSERT INTO relation_fts VALUES (?,?,?)",
                        (relation.id, relation.fact, relation.predicate.replace("_", " ")),
                    )
                for ev in relation.evidence:
                    evidence[ev.id] = ev
                    conn.execute("INSERT OR IGNORE INTO relation_evidence VALUES (?,?)", (relation.id, ev.id))
            for ev in evidence.values():
                conn.execute(
                    "INSERT OR REPLACE INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        ev.id, ev.page_key, ev.url, ev.section_id, ev.block_xpath, ev.span[0], ev.span[1],
                        ev.quote, ev.content_hash, ev.crawled_at,
                    ),
                )
        self._adjacency = None

    # -- the LLM cache ----------------------------------------------------------------------

    def cache_get(self, key: str) -> tuple[str, Usage, str] | None:
        row = self._conn.execute("SELECT response, input_tokens, output_tokens, model FROM llm_cache WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        return str(row["response"]), Usage(int(row["input_tokens"]), int(row["output_tokens"])), str(row["model"])

    def cache_put(self, key: str, response: str, usage: Usage, model: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?,?,?)",
            (key, response, usage.input_tokens, usage.output_tokens, model, time.time()),
        )
        self._conn.commit()

    def cache_size(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM llm_cache").scalar() or 0)

    # -- build runs -------------------------------------------------------------------------

    def record_run(self, started: float, finished: float, model: str, stats: dict[str, Any]) -> int:
        cursor = self._conn.execute(
            "INSERT INTO build_runs(started, finished, model, stats) VALUES (?,?,?,?)",
            (started, finished, model, json.dumps(stats, default=str)),
        )
        self._conn.commit()
        return int(cursor.lastrowid or 0)

    def last_run(self) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM build_runs ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {"id": row["id"], "started": row["started"], "finished": row["finished"], "model": row["model"], **json.loads(row["stats"])}

    # -- reading ----------------------------------------------------------------------------

    def _evidence_rows(self, ids: Iterable[str]) -> dict[str, Evidence]:
        wanted = list(dict.fromkeys(ids))
        out: dict[str, Evidence] = {}
        for chunk in _chunks(wanted, 500):
            marks = ",".join("?" * len(chunk))
            for row in self._conn.execute(f"SELECT * FROM evidence WHERE id IN ({marks})", chunk):
                out[row["id"]] = _evidence(row)
        return out

    def get_entity(self, entity_id: str) -> Entity | None:
        return self.entities([entity_id]).get(entity_id)

    def entities(self, ids: Iterable[str]) -> dict[str, Entity]:
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return {}
        out: dict[str, Entity] = {}
        mention_rows: list[sqlite3.Row] = []
        attribute_rows: list[sqlite3.Row] = []
        for chunk in _chunks(wanted, 500):
            marks = ",".join("?" * len(chunk))
            for row in self._conn.execute(f"SELECT * FROM entities WHERE id IN ({marks})", chunk):
                out[row["id"]] = _entity(row)
            mention_rows += self._conn.execute(f"SELECT * FROM mentions WHERE entity_id IN ({marks})", chunk).fetchall()
            attribute_rows += self._conn.execute(f"SELECT * FROM attributes WHERE entity_id IN ({marks})", chunk).fetchall()
        evidence = self._evidence_rows([r["evidence_id"] for r in mention_rows] + [r["evidence_id"] for r in attribute_rows])
        for row in mention_rows:
            ev = evidence.get(row["evidence_id"])
            if ev is not None and row["entity_id"] in out:
                out[row["entity_id"]].mentions.append(Mention(row["entity_id"], row["surface"], ev, float(row["confidence"])))
        for row in attribute_rows:
            ev = evidence.get(row["evidence_id"])
            if ev is not None and row["entity_id"] in out:
                out[row["entity_id"]].attributes.setdefault(row["key"], []).append(Attribute(row["key"], row["value"], row["unit"], ev))
        return out

    def relations(self, ids: Iterable[str]) -> dict[str, Relation]:
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return {}
        rows: list[sqlite3.Row] = []
        links: list[sqlite3.Row] = []
        for chunk in _chunks(wanted, 500):
            marks = ",".join("?" * len(chunk))
            rows += self._conn.execute(f"SELECT * FROM relations WHERE id IN ({marks})", chunk).fetchall()
            links += self._conn.execute(f"SELECT * FROM relation_evidence WHERE relation_id IN ({marks})", chunk).fetchall()
        evidence = self._evidence_rows(r["evidence_id"] for r in links)
        by_relation: dict[str, list[Evidence]] = defaultdict(list)
        for link in links:
            ev = evidence.get(link["evidence_id"])
            if ev is not None:
                by_relation[link["relation_id"]].append(ev)
        out: dict[str, Relation] = {}
        for row in rows:
            evs = by_relation.get(row["id"], [])
            if evs:
                out[row["id"]] = _relation(row, evs)
        return out

    def iter_entities(self) -> Iterator[Entity]:
        ids = [row[0] for row in self._conn.execute("SELECT id FROM entities ORDER BY evidence_count DESC, name").fetchall()]
        for chunk in _chunks(ids, 500):
            loaded = self.entities(chunk)
            for entity_id in chunk:
                if entity_id in loaded:
                    yield loaded[entity_id]

    def iter_relations(self, *, include_retired: bool = False) -> Iterator[Relation]:
        clause = "" if include_retired else "WHERE retired_at IS NULL"
        ids = [row[0] for row in self._conn.execute(f"SELECT id FROM relations {clause} ORDER BY weight DESC, id").fetchall()]
        for chunk in _chunks(ids, 500):
            loaded = self.relations(chunk)
            for relation_id in chunk:
                if relation_id in loaded:
                    yield loaded[relation_id]

    def iter_evidence(self) -> Iterator[Evidence]:
        for row in self._conn.execute("SELECT * FROM evidence ORDER BY page_key, block_xpath, span_start"):
            yield _evidence(row)

    def entity_summaries(self, *, limit: int = 5000, min_evidence: int = 1) -> list[dict[str, Any]]:
        """Lightweight rows for a graph view: id, type, name, evidence count, degree."""
        degree: Counter[str] = Counter()
        for row in self._conn.execute("SELECT subject_id, object_id FROM relations WHERE retired_at IS NULL"):
            degree[row[0]] += 1
            degree[row[1]] += 1
        rows = self._conn.execute(
            "SELECT id, type, name, evidence_count, generic FROM entities WHERE evidence_count >= ? ORDER BY evidence_count DESC, name LIMIT ?",
            (min_evidence, limit),
        ).fetchall()
        return [
            {"id": r["id"], "type": r["type"], "name": r["name"], "evidence": int(r["evidence_count"]), "degree": degree[r["id"]], "generic": bool(r["generic"])}
            for r in rows
        ]

    def relation_summaries(self, entity_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT id, subject_id, predicate, object_id, weight, fact FROM relations WHERE retired_at IS NULL").fetchall()
        allowed = set(entity_ids) if entity_ids is not None else None
        return [
            {"id": r["id"], "source": r["subject_id"], "target": r["object_id"], "predicate": r["predicate"], "weight": int(r["weight"]), "fact": r["fact"]}
            for r in rows
            if allowed is None or (r["subject_id"] in allowed and r["object_id"] in allowed)
        ]

    def entities_in_sections(self, section_ids: Iterable[str]) -> dict[str, set[str]]:
        """section id -> entity ids mentioned there (through evidence rows)."""
        wanted = list(dict.fromkeys(section_ids))
        out: dict[str, set[str]] = defaultdict(set)
        for chunk in _chunks(wanted, 500):
            marks = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT m.entity_id, e.section_id FROM mentions m JOIN evidence e ON e.id = m.evidence_id WHERE e.section_id IN ({marks})",
                chunk,
            )
            for row in rows:
                out[row["section_id"]].add(row["entity_id"])
        return dict(out)

    def adjacency(self) -> dict[str, list[tuple[str, str, int]]]:
        """entity id -> [(neighbour id, relation id, weight)], both directions, cached."""
        if self._adjacency is None:
            adjacency: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
            for row in self._conn.execute("SELECT id, subject_id, object_id, weight FROM relations WHERE retired_at IS NULL"):
                adjacency[row["subject_id"]].append((row["object_id"], row["id"], int(row["weight"])))
                adjacency[row["object_id"]].append((row["subject_id"], row["id"], int(row["weight"])))
            self._adjacency = dict(adjacency)
        return self._adjacency

    # -- search -----------------------------------------------------------------------------

    def search_entities(self, question: str, *, limit: int = 20) -> list[tuple[str, float]]:
        """Entity ids with a positive relevance score, best first."""
        if self.has_fts:
            match = fts_query(question)
            if not match:
                return []
            try:
                rows = self._conn.execute(
                    "SELECT id, bm25(entity_fts, 0.0, 3.0, 1.5, 1.0) AS rank FROM entity_fts WHERE entity_fts MATCH ? ORDER BY rank LIMIT ?",
                    (match, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            # FTS5's bm25() is negative and lower is better; negate for a score.
            return [(r["id"], -float(r["rank"])) for r in rows]
        return self._scan("SELECT id, name || ' ' || aliases AS text FROM entities", question, limit)

    def search_facts(self, question: str, *, limit: int = 30) -> list[tuple[str, float]]:
        if self.has_fts:
            match = fts_query(question)
            if not match:
                return []
            try:
                rows = self._conn.execute(
                    "SELECT id, bm25(relation_fts, 0.0, 1.0, 2.0) AS rank FROM relation_fts WHERE relation_fts MATCH ? ORDER BY rank LIMIT ?",
                    (match, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            return [(r["id"], -float(r["rank"])) for r in rows]
        return self._scan("SELECT id, fact || ' ' || predicate AS text FROM relations WHERE retired_at IS NULL", question, limit)

    def _scan(self, sql: str, question: str, limit: int) -> list[tuple[str, float]]:
        """No FTS5: a term-overlap score over every row. Slow, correct, and rarely needed."""
        terms = {m.group(0).lower() for m in _WORD.finditer(question) if len(m.group(0)) > 1}
        if not terms:
            return []
        scored: list[tuple[str, float]] = []
        for row in self._conn.execute(sql):
            words = {m.group(0).lower() for m in _WORD.finditer(row["text"])}
            hits = len(terms & words)
            if hits:
                scored.append((row["id"], hits / len(terms)))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:limit]

    # -- stats ------------------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        conn = self._conn
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").scalar() or 0)
            for table in ("entities", "relations", "evidence", "mentions", "attributes", "llm_cache")
        }
        types = Counter({row[0]: int(row[1]) for row in conn.execute("SELECT type, COUNT(*) FROM entities GROUP BY type")})
        from webgraph.kg.prompts import CORE_TYPES

        core = set(CORE_TYPES)
        return {
            "counts": counts,
            "types": dict(types.most_common()),
            "open_types": {t: n for t, n in types.most_common() if t not in core},
            "predicates": {row[0]: int(row[1]) for row in conn.execute("SELECT predicate, COUNT(*) FROM relations GROUP BY predicate ORDER BY 2 DESC LIMIT 40")},
            "pages": int(conn.execute("SELECT COUNT(DISTINCT page_key) FROM evidence").scalar() or 0),
            "generic_entities": int(conn.execute("SELECT COUNT(*) FROM entities WHERE generic=1").scalar() or 0),
            "structured_entities": int(conn.execute("SELECT COUNT(*) FROM entities WHERE extractor=?", (Extractor.STRUCTURED_DATA.value,)).scalar() or 0),
            "fts": self.has_fts,
            "last_run": self.last_run(),
            "path": str(self.path),
        }


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _evidence(row: sqlite3.Row) -> Evidence:
    return Evidence(
        page_key=row["page_key"],
        url=row["url"],
        section_id=row["section_id"],
        block_xpath=row["block_xpath"],
        span=(int(row["span_start"]), int(row["span_end"])),
        quote=row["quote"],
        content_hash=row["content_hash"],
        crawled_at=row["crawled_at"],
    )


def _entity(row: sqlite3.Row) -> Entity:
    return Entity(
        id=row["id"],
        type=row["type"],
        name=row["name"],
        aliases=tuple(json.loads(row["aliases"])),
        description=row["description"],
        extractor=Extractor(row["extractor"]),
        generic=bool(row["generic"]),
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
    )


def _relation(row: sqlite3.Row, evidence: list[Evidence]) -> Relation:
    return Relation(
        id=row["id"],
        subject_id=row["subject_id"],
        predicate=row["predicate"],
        object_id=row["object_id"],
        fact=row["fact"],
        evidence=evidence,
        confidence=float(row["confidence"]),
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        retired_at=row["retired_at"],
    )
