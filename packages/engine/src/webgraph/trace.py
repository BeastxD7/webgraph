"""A durable, structured record of one run.

Why this is not logging
-----------------------
`stream_site` already yields an event per thing that happens, and the web client draws them.
But those events are consumed and dropped: once a run finishes, the only evidence it ever ran
is whatever a human happened to be looking at. When somebody reports "the crawl failed on
these two brand pages", the questions are always the same -- which page linked to them, what
was tried, how long it took, what came back -- and none of it survives.

So a trace is the same events, written down, one JSON object per line. The stream is for
watching; the trace is for afterwards.

What is in every record
-----------------------
`run` (a stable id for the whole crawl), `seq` (monotonic, so an interleaved file still
orders), `at` (seconds since the run began, not a wall clock -- a duration is what anyone
reading a trace actually wants), and `type`. Everything else is the event's own payload.

Deliberately not here
---------------------
No log levels, no formatting, no rotation. A run is bounded and its trace is one file; a
level is a decision about what to discard, taken before anyone knows which line mattered.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from webgraph.config import (
    _MAX_VALUE_CHARS as _MAX_VALUE_CHARS,
)
from webgraph.config import Settings

__all__ = ["RunTrace", "trace_events"]

_SKIP_KEYS: Final[frozenset[str]] = frozenset({"markdown", "content_markdown", "html", "text"})
"""Payload fields that are output rather than evidence, dropped whole."""


def _lean(value: Any) -> Any:
    """The event, minus the payload it was carrying, so the trace stays readable."""
    if isinstance(value, Mapping):
        return {k: _lean(v) for k, v in value.items() if k not in _SKIP_KEYS}
    if isinstance(value, (list, tuple)):
        return [_lean(v) for v in value][:200]
    if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
        return f"{value[:_MAX_VALUE_CHARS]}… ({len(value)} chars)"
    return value


@dataclass(slots=True)
class RunTrace:
    """Writes one JSON object per event, and closes itself when the run ends.

    Failures to write are swallowed on purpose. A trace exists to explain a crawl; a crawl
    that dies because its trace could not be written has been made worse by the thing meant
    to help it.
    """

    path: Path
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started: float = field(default_factory=time.monotonic)
    seq: int = 0
    _handle: Any = None

    def __post_init__(self) -> None:
        with suppress(OSError):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("w", encoding="utf-8")

    def write(self, event: Mapping[str, Any]) -> None:
        if self._handle is None:
            return
        self.seq += 1
        record = {
            "run": self.run_id,
            "seq": self.seq,
            "at": round(time.monotonic() - self.started, 3),
            **_lean(dict(event)),
        }
        with suppress(OSError, TypeError, ValueError):
            self._handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            with suppress(OSError):
                self._handle.close()
            self._handle = None


def trace_events[E: Mapping[str, Any]](
    events: Iterator[E], path: Path | str | RunTrace | None = None
) -> Iterator[E]:
    """Pass an event stream through unchanged, writing each event to a trace on the way.

    The event type passes through as it came: a tracer that widened what it was given would
    force every caller downstream to re-narrow it, for the privilege of being observed.

    A generator rather than a callback so that tracing cannot change what a consumer sees:
    the events yielded are the same objects, in the same order, whether or not anyone is
    recording them.

        for event in trace_events(stream_site(url), "runs/latest.jsonl"):
            ...

    With no path and no `WEBGRAPH_TRACE` in the environment it is a straight pass-through,
    so wrapping a stream is always safe.

    **Lifetime.** Given a path, this owns the trace and closes it when the stream ends.
    Given a `RunTrace`, the caller owns it and this closes nothing -- which is the only way
    a run can record its own death. An exception raised by the stream runs this generator's
    `finally` *before* the caller's `except` block sees it, so a tracer that closed the file
    there would guarantee that the one event worth having, the failure, is the one event
    never written down.
    """
    if isinstance(path, RunTrace):
        for event in events:
            path.write(event)
            yield event
        return

    target = path or Settings.from_env().trace_file
    if not target:
        yield from events
        return

    trace = RunTrace(Path(target))
    try:
        for event in events:
            trace.write(event)
            yield event
    finally:
        trace.write({"type": "trace-closed"})
        trace.close()
