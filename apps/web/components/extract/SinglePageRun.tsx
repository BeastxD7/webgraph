"use client";

import Link from "next/link";

import PageStages from "./PageStages";
import RunLog from "./RunLog";
import { usePageStream } from "@/hooks/usePageStream";
import { useTabTitle } from "@/hooks/useTabTitle";
import { useCallback, useId, useMemo, useState } from "react";

import {
  type ExtractResponse,
  SCHEMA_PRESETS,
  type PageInfo,
  type TextResponse,
  api,
} from "@/lib/api";
import { compact, percent } from "@/lib/format";
import { renderMarkdown } from "@/lib/markdown";
import type { RunMeta } from "@/lib/runlog";
import CopyButton from "@/components/ui/CopyButton";

function Meta({ page }: { page: TextResponse["page"] }) {
  const flags: ReadonlyArray<{ label: string; tone: "ok" | "warn" | "plain" }> = [
    {
      label: page.reading_order_measured
        ? `reading order measured (${page.reading_order})`
        : `reading order assumed (${page.reading_order})`,
      tone: page.reading_order_measured ? "ok" : "warn",
    },
    ...(page.dom_order_differs
      ? [{ label: "CSS reorders this page", tone: "warn" as const }]
      : []),
    { label: `${page.blocks} blocks`, tone: "plain" as const },
    ...page.frameworks.map((framework) => ({ label: framework, tone: "plain" as const })),
    ...page.payloads.map((payload) => ({ label: `payload: ${payload}`, tone: "plain" as const })),
  ];

  const toneClass = {
    ok: "bg-leaf-50 text-leaf-700",
    warn: "bg-flag-warn/10 text-flag-warn",
    plain: "bg-sunk text-ink-soft",
  } as const;

  return (
    <div className="flex flex-wrap gap-1.5">
      {flags.map((flag) => (
        <span
          key={flag.label}
          className={`rounded-full px-2.5 py-1 text-[12px] font-semibold ${toneClass[flag.tone]}`}
        >
          {flag.label}
        </span>
      ))}
    </div>
  );
}

/**
 * "Paste the page's HTML instead": the way in for the sites that refuse every automated
 * fetch -- a Cloudflare challenge, a login wall. The engine does not disguise itself to get
 * past them; the reader, who has the page open in their own browser, hands its source over
 * and nothing is fetched. A pasted wall is refused exactly like a fetched one.
 *
 * The textarea is a draft: the run restarts only on "Read it", not on every keystroke,
 * because a run is a request to the API and a draft is not.
 */
function SuppliedHtml({
  html,
  onSubmit,
  onClear,
  failed,
}: {
  html: string | undefined;
  onSubmit: (html: string) => void;
  onClear: () => void;
  failed: boolean;
}) {
  const [draft, setDraft] = useState("");
  const inputId = useId();
  const ready = draft.trim().length > 0;

  return (
    <details
      // Opened for the reader when the fetch failed: that is the moment this is for.
      open={failed && !html ? true : undefined}
      className="rounded-2xl border border-line bg-surface shadow-card"
    >
      <summary className="flex cursor-pointer flex-wrap items-center gap-3 p-4 text-[15px] font-extrabold tracking-tight">
        Paste the page&rsquo;s HTML instead
        {html && (
          <span className="rounded-full bg-leaf-50 px-2 py-0.5 text-[11.5px] font-semibold text-leaf-700">
            reading your HTML · {compact(html.length)} chars
          </span>
        )}
        <span className="ml-auto text-[12.5px] font-semibold text-ink-soft">
          For sites that refuse every automated fetch
        </span>
      </summary>
      <div className="space-y-3 border-t border-line px-5 py-4">
        <p className="text-[13px] leading-relaxed text-ink-soft">
          If the site answers with a bot challenge or a sign-in page, open it in your own
          browser, view the page source, and paste it here. Nothing is fetched: the engine
          reads what you paste, with links made absolute against the address above. Reading
          order is source order, hidden text may appear, and a pasted wall is still refused.
        </p>
        <label htmlFor={inputId} className="sr-only">
          The page&rsquo;s HTML
        </label>
        <textarea
          id={inputId}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          spellCheck={false}
          rows={6}
          placeholder="<!doctype html><html>…"
          className="w-full rounded-xl border border-line bg-haze px-3 py-2 font-mono text-[12px] leading-relaxed outline-none focus:border-leaf-600"
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={!ready}
            onClick={() => onSubmit(draft)}
            className="rounded-full bg-ink px-4 py-1.5 text-[13px] font-bold text-inverse transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            Read it
          </button>
          {html && (
            <button
              type="button"
              onClick={onClear}
              className="rounded-full border border-line px-3.5 py-1.5 text-[12.5px] font-semibold text-ink-soft transition-colors hover:bg-sunk"
            >
              Fetch it again instead
            </button>
          )}
        </div>
      </div>
    </details>
  );
}

/**
 * Single-page mode. Two requests against the same URL: the Markdown rendering, and — on
 * demand — a JSON-schema mapping that reports where each value came from and how sure the
 * engine is. A field the engine cannot support yields no fact rather than a guess, so an
 * absent row here is the engine declining, not failing silently.
 */
export default function SinglePageRun({ url }: { url: string }) {
  // The page's HTML when the reader supplied it (see `SuppliedHtml`); undefined means fetch.
  const [html, setHtml] = useState<string | undefined>(undefined);
  // Streamed rather than awaited. A render can take ten seconds, and a page that says
  // nothing until it finishes is indistinguishable from one that has hung -- which is why
  // the whole-site crawl has always streamed and this, until now, did not.
  const run = usePageStream({ url, render: true, html });
  const loading = run.running;
  const error = run.error;
  useTabTitle(loading ? "running" : error ? "failed" : "done", url.replace(/^https?:\/\//, "").split("/")[0] ?? url);

  // Landmarks are declared on the page itself, so a single page gets a content-only view
  // without the whole-site crawl that cross-page chrome detection needs.
  const [contentOnly, setContentOnly] = useState(true);
  // Rendered by default. Markdown is what the engine produces, but a reader checking whether
  // the extraction is right reads the page, not the syntax.
  const [preview, setPreview] = useState(true);
  const [presetIndex, setPresetIndex] = useState(0);
  const [facts, setFacts] = useState<ExtractResponse | null>(null);
  const [mapping, setMapping] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  /**
   * The finished page in the shape the rest of this view already expects.
   *
   * Derived from the stream rather than fetched separately: two requests for one page would
   * double the work and could disagree with each other, and the stream already carries
   * everything the old response did.
   */
  const text: TextResponse | null = useMemo(() => {
    if (!run.done) return null;
    return {
      page: {
        url: run.done.url,
        content_hash: run.parse?.content_hash ?? "",
        reading_order: (run.parse?.reading_order ?? "dom-fallback") as PageInfo["reading_order"],
        reading_order_measured: run.parse?.reading_order_measured ?? false,
        dom_order_differs: run.parse?.dom_order_differs ?? false,
        blocks: run.parse?.blocks ?? 0,
        frameworks: run.parse?.frameworks ?? [],
        requires_render: run.parse?.requires_render ?? false,
        payloads: run.parse?.payloads ?? [],
      },
      text: run.done.text,
      markdown: run.done.markdown,
      content_markdown: run.done.content_markdown,
      comments_markdown: run.done.comments_markdown ?? "",
      content_methods: run.select?.methods ?? [],
      content_blocks: run.select?.kept ?? 0,
      page_type: run.classify?.page_type ?? "unknown",
      page_type_confidence: run.classify?.confidence ?? 0,
      images: run.done.images,
      tables: run.done.tables,
    };
  }, [run.done, run.parse, run.select, run.classify]);

  const hasCleanView = Boolean(text?.content_markdown);
  const shown = (contentOnly && hasCleanView ? text?.content_markdown : text?.markdown) ?? "";
  const removed =
    text && hasCleanView
      ? 1 - text.content_markdown.length / Math.max(text.markdown.length, 1)
      : 0;

  /**
   * The header of the copied log.
   *
   * `endedAt` is derived from the run's own elapsed clock rather than read from
   * `Date.now()` here: reading a clock during render is not idempotent, and React is free
   * to render this twice.
   */
  const logMeta: RunMeta = {
    url,
    mode: "single page",
    // What was asked for: `render` is ignored by the API when the HTML is supplied, and
    // the log says which of the two this run was.
    request: html ? { render: false, supplied: true } : { render: true },
    header: (run.log.entries.current[0]?.event.type === "run"
      ? run.log.entries.current[0]?.event
      : null) as Record<string, unknown> | null,
    startedAt: run.log.startedAt.current,
    endedAt: run.running ? null : run.log.startedAt.current + run.elapsed * 1000,
    outcome: run.running ? "running" : error ? `failed: ${error}` : "completed",
  };

  const mapSchema = useCallback(async () => {
    const preset = SCHEMA_PRESETS[presetIndex];
    if (!preset) return;

    setMapping(true);
    setMapError(null);
    try {
      setFacts(await api.extract({ url, schema: preset.schema, render: true, rtl: false }));
    } catch (cause) {
      setMapError(cause instanceof Error ? cause.message : "Schema mapping failed.");
    } finally {
      setMapping(false);
    }
  }, [url, presetIndex]);

  return (
    <div className="page-col space-y-5 pb-20">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[13.5px] font-semibold">
          {loading ? "Extracting…" : error ? "Failed" : "Extracted"}
        </span>
        <Link
          href="/#start"
          className="ml-auto rounded-full bg-leaf-600 px-4 py-1.5 text-[13px] font-bold text-inverse transition-colors hover:bg-leaf-700"
        >
          Extract another page
        </Link>
      </div>

      {/* Always visible, running or not: while the run is going it is the only thing
          happening, and once it has finished or failed it is the record of what was done. */}
      <PageStages run={run} />

      {/* Outside the `text &&` block below on purpose: a run that produced no page is
          exactly the run whose log someone needs. */}
      <RunLog log={run.log} meta={logMeta} />

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-2xl border border-flag-bad/25 bg-flag-bad/5 px-5 py-4"
        >
          <p className="text-[13.5px] font-semibold text-flag-bad">{error}</p>
          <button
            type="button"
            onClick={run.retry}
            className="ml-auto rounded-full border border-flag-bad/40 px-3.5 py-1.5 text-[12.5px] font-bold text-flag-bad transition-colors hover:bg-flag-bad/10"
          >
            Try again
          </button>
        </div>
      )}

      <SuppliedHtml
        html={html}
        failed={Boolean(error)}
        // A new source is a new run: `retry` clears the previous run's stages, error and
        // log, and React batches it with the source change into one restart.
        onSubmit={(pasted) => {
          setHtml(pasted);
          run.retry();
        }}
        onClear={() => {
          setHtml(undefined);
          run.retry();
        }}
      />

      {text && (
        <>
          <section className="rounded-2xl border border-line bg-surface p-6 shadow-card">
            <h2 className="text-[15px] font-extrabold tracking-tight">Provenance</h2>
            <div className="mt-3">
              <Meta page={text.page} />
            </div>
            <p className="tabular mt-4 border-t border-line pt-4 text-[13px] text-ink-soft">
              {compact(text.markdown.length)} chars of Markdown · {text.images.length} images ·{" "}
              {text.tables} tables
            </p>
          </section>

          {text.comments_markdown && (
            <details className="rounded-2xl border border-line bg-surface shadow-card">
              <summary className="flex cursor-pointer flex-wrap items-center gap-3 p-4 text-[15px] font-extrabold tracking-tight">
                Comments
                <span className="tabular rounded-full bg-sunk px-2 py-0.5 text-[11.5px] font-semibold text-ink-soft">
                  {compact(text.comments_markdown.length)} chars · left out of the content
                </span>
                <span className="ml-auto text-[12.5px] font-semibold text-ink-soft">
                  The thread under the page, in page order
                </span>
              </summary>
              <div className="flex justify-end border-t border-line px-4 py-2">
                <CopyButton text={text.comments_markdown} label="Copy comments" />
              </div>
              <div className="max-h-[28rem] overflow-auto border-t border-line px-5 py-4 text-[14px]">
                {renderMarkdown(text.comments_markdown)}
              </div>
            </details>
          )}

          <section className="rounded-2xl border border-line bg-surface p-6 shadow-card">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-[15px] font-extrabold tracking-tight">Schema mapping</h2>
              <select
                value={presetIndex}
                onChange={(event) => setPresetIndex(Number(event.target.value))}
                className="rounded-full border border-line bg-haze px-3 py-1.5 text-[13px] font-semibold"
                aria-label="Schema preset"
              >
                {SCHEMA_PRESETS.map((preset, index) => (
                  <option key={preset.label} value={index}>
                    {preset.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void mapSchema()}
                disabled={mapping || Boolean(html)}
                title={html ? "Schema mapping fetches the page itself; it cannot read supplied HTML yet" : undefined}
                className="rounded-full bg-ink px-4 py-1.5 text-[13px] font-bold text-inverse transition-opacity hover:opacity-85 disabled:opacity-50"
              >
                {mapping ? "Mapping…" : "Map fields"}
              </button>
            </div>
            <p className="mt-2 text-[13px] text-ink-soft">
              {html
                ? "Schema mapping fetches the page itself and cannot read supplied HTML yet, so it is off for this run."
                : SCHEMA_PRESETS[presetIndex]?.description}
            </p>

            {mapError && (
              <p role="alert" className="mt-3 text-[13px] font-semibold text-flag-bad">
                {mapError}
              </p>
            )}

            {facts?.schema_choice && (
              <div className="mt-4 rounded-xl border border-line bg-haze px-4 py-3 text-[12.5px]">
                <p className="text-ink-soft">
                  Read as a{" "}
                  <strong className="font-bold text-ink">{facts.schema_choice.page_type}</strong>{" "}
                  page ({percent(facts.schema_choice.confidence)} confident), so the fields are{" "}
                  {facts.schema_choice.fields.join(", ")}.
                </p>
                <p className="mt-1 text-ink-faint">
                  {facts.schema_choice.payloads_used === 0 ? (
                    <>
                      Of {facts.schema_choice.payloads_considered} structured-data blocks on this
                      page, none describes the page itself — they describe the site, its
                      breadcrumbs or its navigation. Nothing is reported rather than reporting
                      the site&rsquo;s details as the page&rsquo;s.
                    </>
                  ) : (
                    <>
                      Read {facts.schema_choice.payloads_used} of{" "}
                      {facts.schema_choice.payloads_considered} structured-data blocks:{" "}
                      {facts.schema_choice.subject_types.join(", ")}. The rest describe the site
                      rather than this page.
                    </>
                  )}
                </p>
              </div>
            )}

            {facts && (
              <div className="mt-4 overflow-x-auto">
                {Object.keys(facts.facts).length === 0 ? (
                  <p className="text-[13px] text-ink-faint">
                    No field could be supported by evidence on this page. The engine declines
                    rather than guessing.
                  </p>
                ) : (
                  <table className="w-full min-w-[34rem] border-collapse text-[13px]">
                    <thead>
                      <tr className="text-left text-[11px] uppercase tracking-[0.1em] text-ink-faint">
                        <th className="border-b border-line py-2 pr-4 font-bold">Field</th>
                        <th className="border-b border-line py-2 pr-4 font-bold">Value</th>
                        <th className="border-b border-line py-2 pr-4 font-bold">Confidence</th>
                        <th className="border-b border-line py-2 font-bold">Extractor</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(facts.facts).map(([field, fact]) => (
                        <tr key={field}>
                          <td className="border-b border-line py-2 pr-4 font-mono text-[12px]">
                            {field}
                          </td>
                          <td className="border-b border-line py-2 pr-4">
                            {String(fact.value)}
                          </td>
                          <td className="tabular border-b border-line py-2 pr-4">
                            {percent(fact.confidence)}
                          </td>
                          <td className="border-b border-line py-2 font-mono text-[12px] text-ink-soft">
                            {fact.extractor}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </section>

          <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
            <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
              <h2 className="text-[15px] font-extrabold tracking-tight">Markdown</h2>
              {hasCleanView && (
                <span
                  title="Share of the page identified as navigation, footer or other furniture"
                  className="tabular rounded-full bg-leaf-50 px-2 py-0.5 text-[11.5px] font-semibold text-leaf-700"
                >
                  −{Math.round(removed * 100)}% chrome
                </span>
              )}

              <div className="ml-auto flex flex-wrap items-center gap-2">
                {/* Copies exactly what is on screen: switching a toggle changes what you
                    get, which is the only behaviour that is not surprising. */}
                <CopyButton text={shown} label={contentOnly && hasCleanView ? "Copy content" : "Copy page"} />

                {/* Two orthogonal questions -- *what* to show and *how* -- kept as separate
                    controls rather than one four-way switch, because they are not
                    alternatives to each other. Same pair the crawl's page rows carry, so a
                    page read on its own behaves like the same page read inside a site. */}
                <div role="group" aria-label="How to show it" className="flex rounded-full bg-sunk p-0.5">
                  {[
                    { id: true, label: "Preview" },
                    { id: false, label: "Markdown" },
                  ].map((option) => (
                    <button
                      key={String(option.id)}
                      type="button"
                      aria-pressed={preview === option.id}
                      onClick={() => setPreview(option.id)}
                      className={
                        preview === option.id
                          ? "rounded-full bg-surface px-3 py-1 text-[12px] font-bold shadow-sm"
                          : "rounded-full px-3 py-1 text-[12px] font-semibold text-ink-soft"
                      }
                    >
                      {option.label}
                    </button>
                  ))}
                </div>

                {hasCleanView && (
                  <div role="group" aria-label="What to show" className="flex rounded-full bg-sunk p-0.5">
                    {[
                      { id: true, label: "Content only" },
                      { id: false, label: "Full page" },
                    ].map((option) => (
                      <button
                        key={String(option.id)}
                        type="button"
                        aria-pressed={contentOnly === option.id}
                        onClick={() => setContentOnly(option.id)}
                        className={
                          contentOnly === option.id
                            ? "rounded-full bg-surface px-3 py-1 text-[12px] font-bold shadow-sm"
                            : "rounded-full px-3 py-1 text-[12px] font-semibold text-ink-soft"
                        }
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {text.images.length > 0 && (
              <div className="flex gap-2 overflow-x-auto border-b border-line px-4 py-3">
                {text.images.slice(0, 12).map((src, n) => (
                  // Arbitrary remote hosts, so next/image's optimiser is not usable here.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    key={`${n}-${src}`}
                    src={src}
                    alt=""
                    loading="lazy"
                    className="h-16 w-24 shrink-0 rounded-lg border border-line object-cover"
                  />
                ))}
              </div>
            )}

            {preview ? (
              <div className="max-h-[38rem] overflow-auto px-5 py-4 text-[14px]">
                {renderMarkdown(shown)}
              </div>
            ) : (
              <pre className="max-h-[38rem] overflow-auto p-5 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
                {shown}
              </pre>
            )}
          </section>
        </>
      )}
    </div>
  );
}
