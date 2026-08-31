"use client";

import { useEffect, useState } from "react";

import { type GraphSummary, api } from "@/lib/api";
import { compact, percent, prettyUrl } from "@/lib/format";

/**
 * What the crawl learned about how the site is put together.
 *
 * The two columns answer different questions. **Hubs** are what the site links to most — its
 * own account of what is central, though a page linked from everywhere is usually navigation
 * rather than a topic, which is what the specificity figure separates. **Subjects** are what
 * the site's pages call each other, taken from anchor text, so the names are the authors'
 * own rather than anything inferred.
 */
export default function GraphPanel({ siteUrl }: { siteUrl: string }) {
  const [summary, setSummary] = useState<GraphSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .graphSummary(siteUrl)
      .then((result) => {
        if (!cancelled) setSummary(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Could not read the graph.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [siteUrl]);

  if (loading) {
    return (
      <p className="rounded-2xl border border-line bg-surface px-5 py-8 text-center text-[13.5px] text-ink-faint">
        Reading the graph…
      </p>
    );
  }

  if (error || !summary) {
    return (
      <p
        role="alert"
        className="rounded-2xl border border-line bg-surface px-5 py-8 text-center text-[13.5px] text-ink-faint"
      >
        {error ?? "No graph yet."}
      </p>
    );
  }

  const counts: ReadonlyArray<[string, string]> = [
    ["Pages", compact(summary.counts.pages ?? 0)],
    ["Sections", compact(summary.counts.sections ?? 0)],
    ["Links", compact(summary.counts.links ?? 0)],
    ["Subjects", compact(summary.counts.entities ?? 0)],
    ["Mentions", compact(summary.counts.mentions ?? 0)],
  ];

  return (
    <div className="space-y-5">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-line bg-line sm:grid-cols-5">
        {counts.map(([label, value]) => (
          <div key={label} className="bg-surface px-4 py-4">
            <dt className="text-[11px] font-bold uppercase tracking-[0.1em] text-ink-faint">
              {label}
            </dt>
            <dd className="tabular mt-1.5 text-[22px] font-extrabold leading-none">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
          <header className="border-b border-line p-4">
            <h3 className="text-[15px] font-extrabold tracking-tight">Most linked-to pages</h3>
            <p className="mt-1 text-[12.5px] text-ink-soft">
              The site&rsquo;s own account of what is central. Low specificity means everything
              links there — navigation rather than a topic.
            </p>
          </header>
          <ul className="divide-y divide-line">
            {summary.hubs.map((hub) => (
              <li key={hub.url} className="flex items-baseline gap-3 px-4 py-2.5">
                <span className="tabular w-10 shrink-0 text-right text-[13px] font-extrabold">
                  {hub.inbound}
                </span>
                <span className="min-w-0 flex-1">
                  <a
                    href={hub.url}
                    target="_blank"
                    rel="noreferrer"
                    className="block truncate text-[13.5px] font-semibold hover:underline"
                  >
                    {hub.title || prettyUrl(hub.url)}
                  </a>
                  <span className="block truncate font-mono text-[11px] text-ink-faint">
                    {prettyUrl(hub.url)}
                  </span>
                </span>
                <span
                  title="How topical this link target is: 0 means every page links to it"
                  className={`tabular shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold ${
                    hub.specificity < 0.15
                      ? "bg-sunk text-ink-faint"
                      : "bg-leaf-50 text-leaf-700"
                  }`}
                >
                  {percent(hub.specificity)}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
          <header className="border-b border-line p-4">
            <h3 className="text-[15px] font-extrabold tracking-tight">Subjects</h3>
            <p className="mt-1 text-[12.5px] text-ink-soft">
              What the site&rsquo;s pages call each other, taken from anchor text — the
              authors&rsquo; own names, not inferred ones.
            </p>
          </header>
          {summary.entities.length === 0 ? (
            <p className="p-6 text-center text-[13px] text-ink-faint">
              No subjects derived. The site publishes no structured data and its pages do not
              agree on a name for anything.
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {summary.entities.map((entity) => (
                <li key={entity.key} className="px-4 py-2.5">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-[13.5px] font-semibold">{entity.name}</span>
                    <span className="rounded-full bg-sunk px-2 py-0.5 text-[10.5px] font-bold uppercase tracking-wide text-ink-faint">
                      {entity.type}
                    </span>
                  </div>
                  {entity.aliases.length > 1 && (
                    <p className="mt-1 text-[12px] text-ink-faint">
                      also called {entity.aliases.slice(1).join(", ")}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
