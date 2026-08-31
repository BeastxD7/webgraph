"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  type ExtractResponse,
  SCHEMA_PRESETS,
  type TextResponse,
  api,
} from "@/lib/api";
import { compact, percent } from "@/lib/format";

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
 * Single-page mode. Two requests against the same URL: the Markdown rendering, and — on
 * demand — a JSON-schema mapping that reports where each value came from and how sure the
 * engine is. A field the engine cannot support yields no fact rather than a guess, so an
 * absent row here is the engine declining, not failing silently.
 */
export default function SinglePageRun({ url }: { url: string }) {
  const [text, setText] = useState<TextResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The component is keyed by URL, so a new target remounts it and these start clean.
  const [loading, setLoading] = useState(true);

  // Landmarks are declared on the page itself, so a single page gets a content-only view
  // without the whole-site crawl that cross-page chrome detection needs.
  const [contentOnly, setContentOnly] = useState(true);
  const [presetIndex, setPresetIndex] = useState(0);
  const [facts, setFacts] = useState<ExtractResponse | null>(null);
  const [mapping, setMapping] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;

    api
      .text({ url, render: true, rtl: false })
      .then((response) => {
        if (!cancelled.current) setText(response);
      })
      .catch((cause: unknown) => {
        if (!cancelled.current) {
          setError(cause instanceof Error ? cause.message : "Extraction failed.");
        }
      })
      .finally(() => {
        if (!cancelled.current) setLoading(false);
      });

    return () => {
      cancelled.current = true;
    };
  }, [url]);

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
    <div className="mx-auto w-full max-w-6xl space-y-5 px-5 pb-20 sm:px-8">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[13.5px] font-semibold">
          {loading ? "Fetching and rendering…" : error ? "Failed" : "Extracted"}
        </span>
        <Link
          href="/#start"
          className="ml-auto rounded-full bg-leaf-600 px-4 py-1.5 text-[13px] font-bold text-inverse transition-colors hover:bg-leaf-700"
        >
          Extract another page
        </Link>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-2xl border border-flag-bad/25 bg-flag-bad/5 px-5 py-4 text-[13.5px] font-semibold text-flag-bad"
        >
          {error}
        </p>
      )}

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
                disabled={mapping}
                className="rounded-full bg-ink px-4 py-1.5 text-[13px] font-bold text-inverse transition-opacity hover:opacity-85 disabled:opacity-50"
              >
                {mapping ? "Mapping…" : "Map fields"}
              </button>
            </div>
            <p className="mt-2 text-[13px] text-ink-soft">
              {SCHEMA_PRESETS[presetIndex]?.description}
            </p>

            {mapError && (
              <p role="alert" className="mt-3 text-[13px] font-semibold text-flag-bad">
                {mapError}
              </p>
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
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4">
              <h2 className="text-[15px] font-extrabold tracking-tight">Markdown</h2>
              {text.content_markdown && (
                <div role="group" aria-label="Markdown view" className="flex rounded-full bg-sunk p-0.5">
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
            <pre className="max-h-[38rem] overflow-auto p-5 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
              {contentOnly && text.content_markdown ? text.content_markdown : text.markdown}
            </pre>
          </section>
        </>
      )}
    </div>
  );
}
