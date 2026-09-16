"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import Button from "@/components/ui/Button";
import { type BuildEstimate, type BuildEvent, type BuildStats, compactInt, money, shortUrl, streamGraphBuild } from "@/lib/kg";
import { providerBody, useApiKey, useProviderPrefs } from "@/lib/kgSettings";

import { Field, Note, Panel, TextInput } from "./fields";

/**
 * Read the crawl with the model and write the graph.
 *
 * The first event is the estimate -- pages, sections, tokens, and the price when the reader
 * has told us one -- before a single request goes out, and the build honours the caps set
 * here. A section that was read before with the same prompt version and text is served from
 * the cache, so a rebuild after a small crawl change costs only the changed sections.
 */
export default function BuildPanel({
  siteUrl,
  disabled,
  hasGraph,
  onBuilt,
}: {
  siteUrl: string;
  disabled: boolean;
  hasGraph: boolean;
  onBuilt: (stats: BuildStats) => void;
}) {
  const [prefs] = useProviderPrefs();
  const [apiKey] = useApiKey();
  const [maxUsd, setMaxUsd] = useState("");
  const [maxTokens, setMaxTokens] = useState("");
  const [maxPages, setMaxPages] = useState("");
  const [rebuild, setRebuild] = useState(false);
  const [running, setRunning] = useState(false);
  const [estimate, setEstimate] = useState<BuildEstimate | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number; entities: number; relations: number; rejected: number; cached: number; usd: number | null; errors: number }>({
    done: 0,
    total: 0,
    entities: 0,
    relations: 0,
    rejected: 0,
    cached: 0,
    usd: null,
    errors: 0,
  });
  const [stage, setStage] = useState<string | null>(null);
  const [budget, setBudget] = useState<string | null>(null);
  const [stats, setStats] = useState<BuildStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const run = useCallback(async () => {
    setRunning(true);
    setError(null);
    setStats(null);
    setEstimate(null);
    setBudget(null);
    setStage(null);
    setRecent([]);
    setProgress({ done: 0, total: 0, entities: 0, relations: 0, rejected: 0, cached: 0, usd: null, errors: 0 });
    const controller = new AbortController();
    abort.current = controller;
    const num = (value: string) => (value.trim() === "" ? undefined : Math.max(0, Number(value) || 0));
    try {
      await streamGraphBuild(
        {
          url: siteUrl,
          provider: providerBody(prefs, apiKey),
          budget: { max_usd: num(maxUsd), max_input_tokens: num(maxTokens), max_pages: num(maxPages) },
          rebuild,
        },
        (event: BuildEvent) => {
          switch (event.type) {
            case "estimate":
              setEstimate(event);
              setProgress((p) => ({ ...p, total: event.sections }));
              break;
            case "stage":
              setStage(event.message);
              break;
            case "section":
              setProgress((p) => ({
                done: event.done,
                total: event.total,
                entities: p.entities + (event.entities ?? 0),
                relations: p.relations + (event.relations ?? 0),
                rejected: p.rejected + (event.rejected ?? 0),
                cached: p.cached + (event.cached ? 1 : 0),
                usd: event.usd ?? p.usd,
                errors: p.errors + (event.error ? 1 : 0),
              }));
              setRecent((r) => [`${event.error ? "failed" : event.cached ? "cached" : "read"} · ${event.heading || shortUrl(event.page)}${event.error ? ` — ${event.error}` : ""}`, ...r].slice(0, 6));
              break;
            case "budget":
              setBudget(`Stopped at the ${event.reason.replace(/_/g, " ")} cap (${event.cap}); ${event.remaining_sections} sections unread.`);
              break;
            case "done":
              setStats(event.stats);
              onBuilt(event.stats);
              break;
            case "error":
              setError(event.message);
              break;
            default:
              break;
          }
        },
        controller.signal,
      );
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === "AbortError")) {
        setError(cause instanceof Error ? cause.message : "The build failed.");
      }
    } finally {
      setRunning(false);
      abort.current = null;
    }
  }, [siteUrl, prefs, apiKey, maxUsd, maxTokens, maxPages, rebuild, onBuilt]);

  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <Panel
      title="Build"
      lede="The model reads every section of the crawl, names entities and relations, and each is kept only with a verbatim quote from the page that states it. The estimate comes first; nothing is sent until then."
      aside={
        running ? (
          <Button variant="secondary" onClick={() => abort.current?.abort()}>
            Stop
          </Button>
        ) : (
          <Button onClick={() => void run()} disabled={disabled}>
            {hasGraph ? "Read again" : "Build the graph"}
          </Button>
        )
      }
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Spend cap (USD)" hint="Needs a price per million tokens; 0 or empty = no cap.">
          <TextInput type="number" min={0} step="0.01" value={maxUsd} placeholder="no cap" disabled={running} onChange={(e) => setMaxUsd(e.target.value)} />
        </Field>
        <Field label="Input token cap" hint="Default 2,000,000.">
          <TextInput type="number" min={0} step={1000} value={maxTokens} placeholder="2000000" disabled={running} onChange={(e) => setMaxTokens(e.target.value)} />
        </Field>
        <Field label="Pages cap" hint="Read the first N pages by link rank.">
          <TextInput type="number" min={0} value={maxPages} placeholder="all" disabled={running} onChange={(e) => setMaxPages(e.target.value)} />
        </Field>
      </div>
      <label className="mt-3 flex items-center gap-2 text-caption text-muted">
        <input type="checkbox" checked={rebuild} disabled={running} onChange={(e) => setRebuild(e.target.checked)} className="size-4 accent-accent" />
        Ignore the section cache and read every section again.
      </label>

      {estimate && (
        <dl className="tabular mt-5 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-rule pt-4 sm:grid-cols-4">
          {[
            ["Pages", compactInt(estimate.pages)],
            ["Sections", `${compactInt(estimate.sections)}${estimate.cached_sections ? ` (${estimate.cached_sections} cached)` : ""}`],
            ["Input tokens", compactInt(estimate.input_tokens)],
            ["Estimated cost", money(estimate.usd)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-label font-bold uppercase text-muted">{label}</dt>
              <dd className="mt-1 text-body font-semibold text-ink">{value}</dd>
            </div>
          ))}
          <div className="col-span-2 sm:col-span-4">
            <dt className="text-label font-bold uppercase text-muted">Model</dt>
            <dd className="mt-1 font-mono text-code text-ink">
              {estimate.provider.provider} · {estimate.model}
              {estimate.provider.has_key ? "" : " · no key"}
              {Object.keys(estimate.skipped).length > 0 && (
                <span className="ml-2 font-sans text-caption text-muted">
                  skipped: {Object.entries(estimate.skipped).map(([k, v]) => `${k} ${v}`).join(", ")}
                </span>
              )}
            </dd>
          </div>
        </dl>
      )}

      {(running || stats) && (
        <div className="mt-5">
          <div className="flex items-baseline justify-between text-caption text-muted">
            <span>{stage ?? (running ? "Starting…" : "Done")}</span>
            <span className="tabular">
              {progress.done}/{progress.total} sections · {pct}%
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-pill bg-sunk" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full bg-accent transition-[width] duration-(--dur-base) ease-(--ease)" style={{ width: `${pct}%` }} />
          </div>
          <dl className="tabular mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-small sm:grid-cols-5">
            {[
              ["Entities", compactInt(progress.entities)],
              ["Relations", compactInt(progress.relations)],
              ["Rejected", compactInt(progress.rejected)],
              ["Cached", compactInt(progress.cached)],
              ["Spent", money(progress.usd)],
            ].map(([label, value]) => (
              <div key={label} className="flex items-baseline gap-2">
                <dt className="text-muted">{label}</dt>
                <dd className="font-semibold text-ink">{value}</dd>
              </div>
            ))}
          </dl>
          {recent.length > 0 && running && (
            <ul className="mt-3 space-y-0.5 font-mono text-[0.75rem] leading-relaxed text-faint" aria-live="polite">
              {recent.map((line, index) => (
                <li key={`${index}-${line}`} className="truncate">
                  {line}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {budget && (
        <div className="mt-3">
          <Note tone="warn">{budget}</Note>
        </div>
      )}
      {error && (
        <div className="mt-3">
          <Note tone="bad">{error}</Note>
        </div>
      )}
      {stats && (
        <p className="mt-4 text-caption text-muted">
          Read {stats.sections_done} of {stats.sections} sections in {stats.seconds}s with{" "}
          <span className="font-mono">{stats.model}</span>: {stats.entities} entities, {stats.relations} relations after merging;{" "}
          {stats.rejected} assertions ({Math.round(stats.rejection_rate * 100)}%) had no verbatim quote on the page and were dropped
          {stats.cache_hits ? `; ${stats.cache_hits} sections came from the cache` : ""}
          {stats.errors ? `; ${stats.errors} sections failed` : ""}.
          {stats.truncated && ` Stopped early: ${stats.truncated_reason?.replace(/_/g, " ")}.`}
        </p>
      )}
    </Panel>
  );
}
