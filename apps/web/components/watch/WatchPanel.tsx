"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import Button from "@/components/ui/Button";
import Chip, { type ChipTone } from "@/components/ui/Chip";
import { useWatchRun } from "@/hooks/useWatchRun";
import {
  api,
  ApiError,
  type ChangeKind,
  type SectionChange,
  type Watch,
  type WatchChange,
  type WatchDoneEvent,
} from "@/lib/api";
import { duration, prettyUrl } from "@/lib/format";

const KIND_TONE: Record<ChangeKind, ChipTone> = {
  added: "measured",
  removed: "refused",
  changed: "assumed",
};

const KIND_WORD: Record<ChangeKind, string> = {
  added: "new page",
  removed: "page gone",
  changed: "changed",
};

function when(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function excerpt(text: string, limit = 220): string {
  const folded = text.replace(/\s+/g, " ").trim();
  return folded.length <= limit ? folded : `${folded.slice(0, limit - 1).trimEnd()}…`;
}

/** What a finished watch run says, in one line. */
export function runLine(summary: WatchDoneEvent): string {
  if (summary.baseline) {
    return `Baseline recorded: ${summary.pages_ok} pages read, ${summary.failed} refused.`;
  }
  const { added, removed, changed } = summary.changes;
  const total = added + removed + changed;
  const parts: string[] = [];
  if (added) parts.push(`${added} new`);
  if (removed) parts.push(`${removed} gone`);
  if (changed) parts.push(`${changed} changed`);
  const head = total ? parts.join(", ") : "No change";
  const tail = [
    `${summary.unchanged} unchanged`,
    summary.suppressed ? `${summary.suppressed} differed only in noise` : "",
    summary.unverified ? `${summary.unverified} not reached` : "",
  ]
    .filter(Boolean)
    .join(", ");
  return `${head} · ${tail} · ${duration(summary.duration_seconds)}`;
}

function SectionRow({ section }: { section: SectionChange }) {
  const heading = section.heading || "(opening)";
  return (
    <li className="grid gap-x-4 gap-y-1 py-2 sm:grid-cols-[6rem_1fr]">
      <span className="font-mono text-caption uppercase tracking-[0.08em] text-faint">
        {section.kind}
      </span>
      <div className="min-w-0">
        <p className="text-small font-semibold text-ink">{heading}</p>
        {section.kind === "edited" ? (
          <>
            {section.before && (
              <p className="mt-0.5 text-small text-muted">
                <span className="text-faint">was</span> {excerpt(section.before)}
              </p>
            )}
            {section.after && (
              <p className="mt-0.5 text-small text-ink">
                <span className="text-faint">now</span> {excerpt(section.after)}
              </p>
            )}
          </>
        ) : (
          (section.after || section.before) && (
            <p className="mt-0.5 text-small text-muted">
              {excerpt(section.after || section.before)}
            </p>
          )
        )}
      </div>
    </li>
  );
}

function ChangeRow({ change }: { change: WatchChange }) {
  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Chip tone={KIND_TONE[change.kind]}>{KIND_WORD[change.kind]}</Chip>
        <a
          href={change.url}
          target="_blank"
          rel="noreferrer"
          className="min-w-0 truncate text-body font-semibold text-ink underline-offset-2 hover:underline"
        >
          {change.title || prettyUrl(change.url)}
        </a>
        <span className="ml-auto font-mono text-caption text-faint">
          {when(change.detected_at)}
        </span>
      </div>
      <p className="mt-0.5 truncate font-mono text-caption text-muted">{prettyUrl(change.url)}</p>
      {change.sections.length > 0 && (
        <ul className="mt-2 divide-y divide-rule border-t border-rule">
          {change.sections.slice(0, 8).map((section, index) => (
            <SectionRow key={`${section.heading}-${index}`} section={section} />
          ))}
          {change.sections.length > 8 && (
            <li className="py-2 text-caption text-faint">
              +{change.sections.length - 8} more sections
            </li>
          )}
        </ul>
      )}
    </li>
  );
}

function WatchRow({
  watch,
  selected,
  running,
  onSelect,
  onRun,
}: {
  watch: Watch;
  selected: boolean;
  running: boolean;
  onSelect: () => void;
  onRun: () => void;
}) {
  const last = watch.last_run;
  return (
    <li
      className={`flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5 ${selected ? "bg-sunk" : "bg-surface"}`}
    >
      <button
        type="button"
        onClick={onSelect}
        className="min-w-0 flex-1 text-left"
        aria-pressed={selected}
      >
        <span className="block truncate text-body font-semibold text-ink">
          {prettyUrl(watch.root)}
        </span>
        <span className="block text-caption text-muted">
          {last
            ? `last run ${when(last.finished_at ?? last.started_at)} · ${last.pages_ok} pages` +
              (last.stopped_by ? ` · stopped by ${last.stopped_by}` : "")
            : "never run"}
          {` · ${watch.runs} ${watch.runs === 1 ? "run" : "runs"} · ${watch.changes} ${watch.changes === 1 ? "change" : "changes"}`}
        </span>
      </button>
      <a
        href={api.watchFeedUrl(watch.id)}
        className="text-caption font-semibold text-muted underline-offset-2 hover:text-ink hover:underline"
      >
        Feed
      </a>
      <Button variant="secondary" onClick={onRun} disabled={running}>
        {running ? "Running…" : "Run now"}
      </Button>
    </li>
  );
}

export default function WatchPanel() {
  const [watches, setWatches] = useState<Watch[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  // Changes for one watch, keyed by its id and by the run that last refreshed them, so a
  // stale list is never shown against a different watch.
  const [loaded, setLoaded] = useState<{ id: string; changes: WatchChange[] } | null>(null);
  const [runsSeen, setRunsSeen] = useState(0);
  const [url, setUrl] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api
      .watches()
      .then((list) => {
        setWatches(list);
        setLoadError(null);
        setSelected((current) => current ?? list[0]?.id ?? null);
      })
      .catch((cause: unknown) => {
        setLoadError(cause instanceof ApiError ? cause.message : String(cause));
        setWatches([]);
      });
  }, []);

  // A finished run changes the row's counts and the list below it.
  const run = useWatchRun({
    onFinished: () => {
      refresh();
      setRunsSeen((n) => n + 1);
    },
  });

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    api
      .watchChanges(selected)
      .then((result) => {
        if (!cancelled) setLoaded({ id: selected, changes: result.changes });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ id: selected, changes: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [selected, runsSeen]);

  const changes = loaded?.id === selected ? loaded.changes : [];

  async function create(event: FormEvent) {
    event.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await api.createWatch({
        url: /^https?:\/\//.test(trimmed) ? trimmed : `https://${trimmed}`,
      });
      setUrl("");
      setSelected(created.id);
      refresh();
    } catch (cause) {
      setCreateError(cause instanceof ApiError ? cause.message : String(cause));
    } finally {
      setCreating(false);
    }
  }

  const current = watches?.find((w) => w.id === selected) ?? null;

  return (
    <div className="space-y-8">
      <form onSubmit={create} className="flex flex-wrap items-stretch gap-2">
        <label htmlFor="watch-url" className="sr-only">
          Site to watch
        </label>
        <input
          id="watch-url"
          type="text"
          inputMode="url"
          autoComplete="off"
          placeholder="vtu.ac.in"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="h-9 min-w-0 flex-1 rounded-md border border-rule-strong bg-surface px-3 text-body text-ink placeholder:text-faint pointer-coarse:min-h-11"
        />
        <Button type="submit" disabled={creating || !url.trim()}>
          {creating ? "Adding…" : "Watch this site"}
        </Button>
        {createError && (
          <p role="alert" className="basis-full text-small text-bad">
            {createError}
          </p>
        )}
      </form>

      {loadError && (
        <p role="alert" className="rounded-md border border-bad/25 bg-bad-soft px-4 py-3 text-small text-bad">
          {loadError}
        </p>
      )}

      {watches && watches.length === 0 && !loadError && (
        <p className="text-body text-muted">
          No watches yet. Add a site above; the first run records a baseline, every run after
          that says what changed and in which section.
        </p>
      )}

      {watches && watches.length > 0 && (
        <ul className="divide-y divide-rule overflow-hidden rounded-md border border-rule">
          {watches.map((watch) => (
            <WatchRow
              key={watch.id}
              watch={watch}
              selected={watch.id === selected}
              running={run.running && run.watchId === watch.id}
              onSelect={() => setSelected(watch.id)}
              onRun={() => {
                setSelected(watch.id);
                run.run(watch.id);
              }}
            />
          ))}
        </ul>
      )}

      {current && (
        <section aria-labelledby="watch-detail" className="space-y-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 id="watch-detail" className="text-h3 font-bold text-ink">
              {prettyUrl(current.root)}
            </h2>
            <span className="font-mono text-caption text-faint">watch {current.id}</span>
            <a
              href={api.watchFeedUrl(current.id, "atom")}
              className="ml-auto text-caption font-semibold text-muted underline-offset-2 hover:text-ink hover:underline"
            >
              Atom feed
            </a>
          </div>

          {run.watchId === current.id && (run.running || run.summary || run.error) && (
            <div className="rounded-md border border-rule bg-surface px-5 py-4">
              <p className="flex items-center gap-2 text-small font-semibold text-ink">
                <span
                  aria-hidden
                  className={`size-2 rounded-full ${run.running ? "animate-pulse bg-accent" : run.error ? "bg-bad" : "bg-accent"}`}
                />
                {run.error
                  ? run.error
                  : run.summary
                    ? runLine(run.summary)
                    : run.start
                      ? run.start.baseline
                        ? `First run: recording a baseline · ${run.pages} pages so far`
                        : `Comparing against run ${run.start.previous_run?.id ?? "?"} (${run.start.previous_pages} pages) · ${run.pages} pages so far · ${run.changes.length} changed`
                      : (run.stage ?? "Starting")}
                {run.running && (
                  <button
                    type="button"
                    onClick={run.stop}
                    className="ml-auto text-caption font-semibold text-muted hover:text-ink"
                  >
                    Stop
                  </button>
                )}
              </p>
              {run.inFlight.length > 0 && (
                <p className="mt-1 truncate font-mono text-caption text-faint">
                  fetching {run.inFlight.map(prettyUrl).join(" · ")}
                </p>
              )}
            </div>
          )}

          {changes.length === 0 ? (
            <p className="text-small text-muted">
              {current.runs === 0
                ? "Not run yet. The first run records a baseline."
                : current.runs === 1
                  ? "Baseline recorded. Run it again to see what changed."
                  : "No changes recorded."}
            </p>
          ) : (
            <ul className="divide-y divide-rule overflow-hidden rounded-md border border-rule bg-surface">
              {changes.map((change) => (
                <ChangeRow key={change.id} change={change} />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
