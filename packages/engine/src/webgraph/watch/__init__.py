"""Watch a site: crawl it again, say what changed, and where.

What this is for
----------------
"Tell me when the university posts a circular." The research behind it (scratchpad
`research/DEMAND-VALIDATION.md` §4, `WILLINGNESS-TO-PAY.md` §6) found the cheap tier of
change monitoring saturated and its one open complaint to be false positives: alerts for
layout churn, ad rotation, a clock. What buyers name as the differentiator is a diff that
says *which section* changed, in the page's own words, and stays quiet otherwise. The
engine already has the pieces: a `content_hash` per page over the extracted text, content
selection that removes navigation, footers and comments, and `graph.diff.diff_sections`
that matches heading-scoped sections across two crawls. A watch is those three, run on a
schedule, with a store between runs and a feed out the other end.

The model
---------
A **watch** is a root URL and a configuration. A **run** crawls it -- the previous run's
URL set as seeds beside the sitemap and the links, under the same limits and politeness
as any crawl -- and records every page: its `content_hash`, its content Markdown, and the
heading-scoped sections cut from it. For each page the run compares against the last
finished run: by hash first (identical text is identical, no diff needed), then section
by section with the noise rules applied (`watch.noise`), and records a **change** --
`added`, `removed`, `changed` -- carrying the page, the section headings and the text on
each side. The first run is the baseline and records no changes. No model is involved
anywhere; two runs over the same two versions of a site produce the same changes.

`removed` is a claim the run can stand behind: a page the previous run read that this run
asked for and was told is gone (an HTTP 4xx). A page the run did not reach -- the cap was
hit first -- is counted as `unverified`, not as gone.

Scheduling is not the engine's business in v1. `webgraph watch run <id>` (or
`POST /api/watch/{id}/run`) is what a cron entry or a GitHub Action calls;
`.github/workflows/example-watch.yml` shows one.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from webgraph import config as engine_config
from webgraph.crawl.frontier import canonical_key
from webgraph.graph.diff import SectionChange, diff_sections
from webgraph.graph.model import Section
from webgraph.resolve import Strategy
from webgraph.site import SiteConfig, stream_site
from webgraph.watch import feed as feed_module
from webgraph.watch.noise import NoiseRules
from webgraph.watch.sections import sections_from_markdown, sections_from_records
from webgraph.watch.store import Change, PageRecord, Run, Watch, WatchStore

__all__ = [
    "Change",
    "PageRecord",
    "Run",
    "RunSummary",
    "Watch",
    "WatchStore",
    "create_watch",
    "export_changes",
    "get_watch",
    "list_changes",
    "list_watches",
    "run_watch",
    "site_config_from",
    "stream_watch",
]

CRAWL_FIELDS: tuple[str, ...] = (
    "max_pages",
    "max_seconds",
    "max_queue",
    "fetch_files",
    "concurrency",
    "delay_seconds",
    "host_interval_seconds",
    "max_depth",
    "strict_domain",
    "sitemap_limit",
    "respect_robots",
    "remove_chrome",
    "main_content",
)
"""The `SiteConfig` fields a watch's config may set, by name. `strategy` is handled apart
(a string), and `complete: true|false` is accepted as sugar for union / static-only."""

SECTION_TEXT_CHARS = engine_config.WATCH_SECTION_TEXT_CHARS
MAX_SECTIONS_PER_PAGE = engine_config.WATCH_MAX_SECTIONS_PER_PAGE


def site_config_from(options: dict[str, Any] | None) -> SiteConfig:
    """A `SiteConfig` from a watch's stored config. Unknown keys are ignored so a config
    written by a newer version still runs; the crawl's own defaults fill the rest."""
    options = options or {}
    # Landmarks and site chrome come off (that is what keeps a footer edit from being 2,000
    # changes); the main-content *boundary* does not, unless asked. It is a prose-seeking
    # step, and a watched page is as likely to be a list of circulars as an article -- on
    # a four-page fixture it cut two of three sections from the About page.
    overrides: dict[str, Any] = {"main_content": False}
    overrides.update({k: options[k] for k in CRAWL_FIELDS if k in options})
    strategy: Strategy | None = None
    if options.get("strategy"):
        strategy = Strategy(str(options["strategy"]))
    elif "complete" in options:
        strategy = Strategy.UNION if options["complete"] else Strategy.STATIC_ONLY
    if strategy is not None:
        overrides["strategy"] = strategy
    return replace(SiteConfig(), **overrides)


def _store(store: WatchStore | Path | str | None) -> WatchStore:
    if isinstance(store, WatchStore):
        return store
    return WatchStore(store)


def create_watch(
    root: str,
    config: dict[str, Any] | None = None,
    *,
    schedule_seconds: int = 0,
    store: WatchStore | Path | str | None = None,
) -> Watch:
    """Register a site to watch. `config` takes `SiteConfig` fields by name (`max_pages`,
    `strategy`, ...) and the watch's own `noise` / `noise_patterns`. Validated by building
    the `SiteConfig` once, so a bad value fails here and not on the first scheduled run."""
    if not root.startswith(("http://", "https://")):
        raise ValueError(f"a watch needs an http or https root, not {root!r}")
    site_config_from(config)
    NoiseRules.from_config(config)
    return _store(store).create_watch(root, config, schedule_seconds=schedule_seconds)


def get_watch(watch_id: str, *, store: WatchStore | Path | str | None = None) -> Watch | None:
    return _store(store).get_watch(watch_id)


def list_watches(*, store: WatchStore | Path | str | None = None) -> list[Watch]:
    return _store(store).list_watches()


@dataclass(frozen=True, slots=True)
class RunSummary:
    """What a run found, in numbers, with the changes themselves."""

    watch_id: str
    run_id: int
    baseline: bool
    pages_ok: int
    pages_failed: int
    stopped_by: str | None
    added: int
    removed: int
    changed: int
    suppressed: int
    """Pages whose text differed only in what the noise rules ignore."""

    unchanged: int
    unverified: int
    """Pages the previous run read that this run never reached."""

    duration_seconds: float
    changes: tuple[Change, ...] = field(default_factory=tuple)

    @property
    def any_change(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "watch_id": self.watch_id,
            "run_id": self.run_id,
            "baseline": self.baseline,
            "pages_ok": self.pages_ok,
            "pages_failed": self.pages_failed,
            "stopped_by": self.stopped_by,
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
            "suppressed": self.suppressed,
            "unchanged": self.unchanged,
            "unverified": self.unverified,
            "duration_seconds": self.duration_seconds,
            "changes": [c.as_dict() for c in self.changes],
        }

    def summary(self) -> str:
        if self.baseline:
            return f"Baseline recorded: {self.pages_ok} pages, {self.pages_failed} failed."
        if not self.any_change:
            return (
                f"No change. {self.unchanged} pages identical, {self.suppressed} differed "
                "only in noise."
            )
        return (
            f"{self.added} new, {self.removed} gone, {self.changed} changed; "
            f"{self.unchanged} unchanged, {self.suppressed} noise only, "
            f"{self.unverified} not reached."
        )


def _record_from_event(event: dict[str, Any]) -> PageRecord:
    """A page as the run stores it, from the crawl's `page` event. The sections are cut
    from the content Markdown -- the page with chrome removed -- or from the whole page
    when nothing was removed."""
    markdown = str(event.get("content_markdown") or event.get("markdown") or "")
    sections = sections_from_markdown(markdown) if event.get("ok") else []
    return PageRecord(
        url=str(event["url"]),
        content_hash=str(event.get("content_hash") or ""),
        title=str(event.get("title") or ""),
        markdown=markdown,
        fetched_at=time.time(),
        strategy=event.get("strategy"),
        error=event.get("error"),
        sections=tuple(
            {"heading": s.heading, "level": s.level, "text": s.text} for s in sections
        ),
    )


def _clip(text: str) -> str:
    return text if len(text) <= SECTION_TEXT_CHARS else text[: SECTION_TEXT_CHARS - 1] + "…"


def _section_dicts(changes: list[SectionChange]) -> list[dict[str, Any]]:
    return [
        {
            "kind": c.kind,
            "heading": c.heading,
            "before": _clip(c.before),
            "after": _clip(c.after),
        }
        for c in changes[:MAX_SECTIONS_PER_PAGE]
    ]


def _cleaned(sections: list[Section], rules: NoiseRules) -> list[Section]:
    """The sections as compared: each one's text with the noise removed. A section whose
    entire body was noise keeps its heading and an empty body, so it still matches."""
    return [replace(s, text=rules.clean(s.text)) for s in sections]


def _gone(error: str | None) -> bool:
    """An HTTP 4xx is the site saying the page is not there. A timeout is not."""
    return bool(error) and str(error).startswith("HTTP 4")


@dataclass(frozen=True, slots=True)
class _Verdict:
    kind: str | None
    """`added`, `removed`, `changed`, or None."""

    sections: list[dict[str, Any]] = field(default_factory=list)
    suppressed: bool = False


def _compare(previous: PageRecord | None, current: PageRecord, rules: NoiseRules) -> _Verdict:
    if previous is None or not previous.ok:
        if current.ok:
            now = sections_from_records(current.sections)
            return _Verdict(
                "added",
                _section_dicts(
                    [SectionChange(kind="added", heading=s.heading, after=s.text) for s in now]
                ),
            )
        return _Verdict(None)
    if not current.ok:
        if _gone(current.error):
            was = sections_from_records(previous.sections)
            return _Verdict(
                "removed",
                _section_dicts(
                    [SectionChange(kind="removed", heading=s.heading, before=s.text) for s in was]
                ),
            )
        return _Verdict(None)
    if previous.content_hash and previous.content_hash == current.content_hash:
        return _Verdict(None)
    before = _cleaned(sections_from_records(previous.sections), rules)
    after = _cleaned(sections_from_records(current.sections), rules)
    changes = diff_sections(before, after)
    if not changes:
        return _Verdict(None, suppressed=True)
    return _Verdict("changed", _section_dicts(changes))


def stream_watch(
    watch_id: str,
    *,
    store: WatchStore | Path | str | None = None,
    should_stop: Callable[[], bool] | None = None,
    adjust: Callable[[SiteConfig], SiteConfig] | None = None,
) -> Iterator[dict[str, Any]]:
    """Run a watch once, yielding the crawl's events plus a `watch` event first, a
    `change` event per page that differed, and a `done` event that carries the run's
    summary (`changes`, `suppressed`, `unverified`, `run_id`, `baseline`).

    `adjust` lets a host apply its own caps to the watch's crawl config before it runs --
    the API clamps `max_pages` to `WEBGRAPH_MAX_PAGES` there, as it does for any crawl.
    The `page` events are forwarded without their Markdown: a watch run is bookkeeping,
    not a reading session, and the text is in the store.
    """
    db = _store(store)
    watch = db.get_watch(watch_id)
    if watch is None:
        yield {"type": "error", "message": f"no watch with id {watch_id!r}"}
        return

    site_config = site_config_from(watch.config)
    if adjust is not None:
        site_config = adjust(site_config)
    rules = NoiseRules.from_config(watch.config)

    previous_run = db.last_finished_run(watch.id)
    previous_pages = db.pages_of(previous_run.id) if previous_run is not None else {}
    previous_by_key = {canonical_key(url): page for url, page in previous_pages.items()}
    baseline = previous_run is None

    run = db.start_run(watch.id)
    started = time.monotonic()
    yield {
        "type": "watch",
        "watch_id": watch.id,
        "run_id": run.id,
        "root": watch.root,
        "baseline": baseline,
        "previous_run": previous_run.as_dict() if previous_run else None,
        "previous_pages": len(previous_pages),
        "noise": rules.describe(),
        "limits": {
            "max_pages": site_config.max_pages,
            "max_seconds": site_config.max_seconds,
            "max_queue": site_config.max_queue,
        },
    }

    seen_keys: set[str] = set()
    counts = {"added": 0, "removed": 0, "changed": 0, "suppressed": 0, "unchanged": 0}
    changes: list[Change] = []
    pages_ok = pages_failed = 0
    stopped_by: str | None = None
    crawl_done: dict[str, Any] | None = None
    seeds = [url for url, page in previous_pages.items() if page.ok]

    try:
        for event in stream_site(
            watch.root, config=site_config, should_stop=should_stop, seeds=seeds
        ):
            kind = event.get("type")
            if kind == "page":
                record = _record_from_event(event)
                db.save_page(run.id, record)
                key = canonical_key(record.url)
                seen_keys.add(key)
                if record.ok:
                    pages_ok += 1
                else:
                    pages_failed += 1
                forwarded = {k: v for k, v in event.items() if k not in {"markdown", "content_markdown"}}
                forwarded["content_hash"] = record.content_hash
                yield forwarded
                if baseline:
                    continue
                verdict = _compare(previous_by_key.get(key), record, rules)
                if verdict.kind is None:
                    if verdict.suppressed:
                        counts["suppressed"] += 1
                    elif record.ok:
                        counts["unchanged"] += 1
                    continue
                previous = previous_by_key.get(key)
                change = db.add_change(
                    run.id,
                    watch.id,
                    url=record.url,
                    kind=verdict.kind,
                    before_hash=previous.content_hash if previous else "",
                    after_hash=record.content_hash,
                    title=record.title or (previous.title if previous else ""),
                    sections=verdict.sections,
                )
                changes.append(change)
                counts[verdict.kind] += 1
                yield {"type": "change", "watch_id": watch.id, "run_id": run.id, **change.as_dict()}
            elif kind == "done":
                crawl_done = event
                stopped_by = event.get("stopped_by")
            else:
                yield event
    finally:
        # The run is closed however the loop ended -- a caller that stops mid-crawl still
        # leaves a finished run, which the next run compares against. An error also
        # closes it, so a run that died is not mistaken for one still going.
        db.finish_run(run.id, pages_ok=pages_ok, pages_failed=pages_failed, stopped_by=stopped_by)

    unverified = [url for url in previous_pages if canonical_key(url) not in seen_keys]
    summary = RunSummary(
        watch_id=watch.id,
        run_id=run.id,
        baseline=baseline,
        pages_ok=pages_ok,
        pages_failed=pages_failed,
        stopped_by=stopped_by,
        added=counts["added"],
        removed=counts["removed"],
        changed=counts["changed"],
        suppressed=counts["suppressed"],
        unchanged=counts["unchanged"],
        unverified=len(unverified),
        duration_seconds=round(time.monotonic() - started, 1),
        changes=tuple(changes),
    )
    yield {
        **(crawl_done or {}),
        "type": "done",
        "watch_id": watch.id,
        "run_id": run.id,
        "baseline": baseline,
        "changes": {k: counts[k] for k in ("added", "removed", "changed")},
        "suppressed": counts["suppressed"],
        "unchanged": counts["unchanged"],
        "unverified": len(unverified),
        "unverified_urls": unverified[:50],
        "summary": summary.as_dict(),
    }


def run_watch(
    watch_id: str,
    *,
    store: WatchStore | Path | str | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    adjust: Callable[[SiteConfig], SiteConfig] | None = None,
) -> RunSummary:
    """Run a watch once and return what it found. `on_event` sees every event as it
    happens (`stream_watch` is the same run as an iterator)."""
    last: dict[str, Any] | None = None
    for event in stream_watch(watch_id, store=store, should_stop=should_stop, adjust=adjust):
        if on_event is not None:
            on_event(event)
        last = event
    if last is None or last.get("type") != "done":
        message = (last or {}).get("message", "the run produced no result")
        raise RuntimeError(f"watch {watch_id}: {message}")
    summary = last["summary"]
    return RunSummary(
        **{k: v for k, v in summary.items() if k != "changes"},
        changes=tuple(
            list_changes(watch_id, store=store, run_id=int(summary["run_id"]))
        ),
    )


def list_changes(
    watch_id: str,
    since: float | None = None,
    *,
    store: WatchStore | Path | str | None = None,
    run_id: int | None = None,
    limit: int = 500,
) -> list[Change]:
    """Changes recorded for a watch, newest first. `since` is an epoch timestamp."""
    return _store(store).changes(watch_id, since=since, run_id=run_id, limit=limit)


def export_changes(
    watch_id: str,
    since: float | None = None,
    *,
    fmt: str = "json",
    store: WatchStore | Path | str | None = None,
    feed_url: str = "",
    limit: int = 200,
) -> str:
    """The changes as `json`, `md`, `rss` (RSS 2.0) or `atom` (Atom 1.0)."""
    db = _store(store)
    watch = db.get_watch(watch_id)
    if watch is None:
        raise KeyError(f"no watch with id {watch_id!r}")
    changes = db.changes(watch_id, since=since, limit=limit)
    if fmt == "json":
        return feed_module.to_json(watch, changes)
    if fmt in {"md", "markdown"}:
        return feed_module.to_markdown(watch, changes)
    if fmt == "rss":
        return feed_module.to_rss(watch, changes, feed_url=feed_url)
    if fmt == "atom":
        return feed_module.to_atom(watch, changes, feed_url=feed_url)
    raise ValueError(f"unknown format {fmt!r}: expected json, md, rss or atom")
