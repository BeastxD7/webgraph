"use client";

import { useCallback, useState } from "react";

import { API_BASE, type ContextResponse, api } from "@/lib/api";
import { compact, prettyUrl } from "@/lib/format";

const BUDGETS: ReadonlyArray<{ label: string; chars: number }> = [
  { label: "8k tokens", chars: 32_000 },
  { label: "32k tokens", chars: 128_000 },
  { label: "128k tokens", chars: 512_000 },
];

const EXAMPLES = ["pricing", "how do I get started", "who is this for"];

/**
 * Ask a question of the whole crawl.
 *
 * The crawl is far larger than any context window — a 200-page site is millions of tokens —
 * so this returns a *bounded* context assembled about the question: sections that matched,
 * plus sections reached by following links from them, plus a map of everything that did not
 * fit. Every included section says why it is there, because a ranked list with no
 * explanation cannot be argued with.
 */
export default function AskPanel({ siteUrl }: { siteUrl: string }) {
  const [query, setQuery] = useState("");
  const [budget, setBudget] = useState(BUDGETS[1]!.chars);
  const [result, setResult] = useState<ContextResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);

  const ask = useCallback(
    async (question: string) => {
      if (!question.trim()) return;
      setLoading(true);
      setError(null);
      try {
        setResult(
          await api.context({
            url: siteUrl,
            query: question,
            max_chars: budget,
            max_hops: 2,
          }),
        );
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not assemble a context.");
        setResult(null);
      } finally {
        setLoading(false);
      }
    },
    [siteUrl, budget],
  );

  return (
    <section className="rounded-2xl border border-line bg-surface p-6 shadow-card">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-[15px] font-extrabold tracking-tight">Ask the whole site</h2>
        <p className="text-[13px] text-ink-soft">
          Assembles a context under a token budget — matched sections, plus what they link to.
        </p>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask(query);
        }}
        className="mt-4 flex flex-wrap gap-2"
      >
        <input
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="What do you want to know about this site?"
          className="min-w-0 flex-1 rounded-full border border-line bg-haze px-4 py-2.5 text-[14px] outline-none transition-colors focus:border-leaf-300 focus:bg-surface"
          aria-label="Question"
        />
        <select
          value={budget}
          onChange={(event) => setBudget(Number(event.target.value))}
          aria-label="Context budget"
          className="rounded-full border border-line bg-haze px-3 py-2.5 text-[13px] font-semibold"
        >
          {BUDGETS.map((option) => (
            <option key={option.chars} value={option.chars}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="rounded-full bg-leaf-600 px-5 py-2.5 text-[13px] font-bold text-inverse transition-colors hover:bg-leaf-700 disabled:opacity-50"
        >
          {loading ? "Assembling…" : "Assemble"}
        </button>
      </form>

      {!result && !error && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px] text-ink-faint">
          try:
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => {
                setQuery(example);
                void ask(example);
              }}
              className="rounded-full border border-line px-2.5 py-1 font-semibold text-ink-soft transition-colors hover:bg-haze"
            >
              {example}
            </button>
          ))}
        </div>
      )}

      {error && (
        <p role="alert" className="mt-4 text-[13px] font-semibold text-flag-bad">
          {error}
        </p>
      )}

      {result && (
        <div className="mt-5 space-y-4">
          <dl className="tabular grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
            {[
              { label: "Context", value: `${compact(Math.round(result.stats.approx_tokens ?? 0))} tok` },
              { label: "Sections", value: String(result.sources.length) },
              { label: "Also listed", value: String(result.pages_mapped.length) },
              { label: "Budget used", value: `${Math.round((result.stats.budget_used ?? 0) * 100)}%` },
            ].map((cell) => (
              <div key={cell.label} className="bg-surface px-3 py-2.5">
                <dt className="text-[10.5px] font-bold uppercase tracking-[0.1em] text-ink-faint">
                  {cell.label}
                </dt>
                <dd className="mt-0.5 text-[16px] font-extrabold">{cell.value}</dd>
              </div>
            ))}
          </dl>

          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line">
            {result.sources.map((source, index) => (
              <li
                key={`${source.page_url}-${source.heading}-${index}`}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-3 py-2 text-[13px]"
              >
                <span
                  className={`rounded-full px-2 py-0.5 text-[10.5px] font-bold uppercase tracking-wide ${
                    source.hops === 0
                      ? "bg-leaf-50 text-leaf-700"
                      : "bg-sunk text-ink-soft"
                  }`}
                >
                  {source.hops === 0 ? "matched" : `${source.hops} hop`}
                </span>
                <span className="font-semibold">{source.heading}</span>
                <a
                  href={source.page_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono text-[11.5px] text-ink-faint hover:text-ink hover:underline"
                >
                  {prettyUrl(source.page_url)}
                </a>
                <span className="ml-auto text-[11.5px] text-ink-faint">{source.reason}</span>
              </li>
            ))}
          </ul>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setShowText((value) => !value)}
              className="rounded-full border border-line-strong px-3.5 py-1.5 text-[12.5px] font-bold transition-colors hover:bg-haze"
            >
              {showText ? "Hide assembled context" : "Show assembled context"}
            </button>
            <button
              type="button"
              onClick={() => void navigator.clipboard.writeText(result.text)}
              className="rounded-full border border-line-strong px-3.5 py-1.5 text-[12.5px] font-bold transition-colors hover:bg-haze"
            >
              Copy for a model
            </button>
            <a
              href={`${API_BASE}/api/site/graph?url=${encodeURIComponent(siteUrl)}`}
              className="rounded-full border border-line-strong px-3.5 py-1.5 text-[12.5px] font-bold transition-colors hover:bg-haze"
            >
              Download graph (.jsonl)
            </a>
          </div>

          {showText && (
            <pre className="max-h-[32rem] overflow-auto rounded-xl border border-line bg-haze p-4 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
              {result.text}
            </pre>
          )}
        </div>
      )}
    </section>
  );
}
