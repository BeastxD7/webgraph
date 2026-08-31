"use client";

import { useMemo, useState } from "react";

const PAGE_SIZE = 300;

/**
 * A plain list of URLs, for the Discovered and Queued tabs.
 *
 * Rendered in pages of 300. A crawl routinely discovers thousands of URLs, and putting
 * them all in the DOM at once costs more than anyone gains from scrolling past them.
 */
export default function UrlList({
  urls,
  emptyMessage,
}: {
  urls: string[];
  emptyMessage: string;
}) {
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return urls;
    return urls.filter((url) => url.toLowerCase().includes(needle));
  }, [urls, query]);

  const shown = matches.slice(0, limit);

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
      <header className="flex flex-col gap-3 border-b border-line p-4 sm:flex-row sm:items-center">
        <p className="tabular shrink-0 text-[13.5px] font-bold">
          {matches.length.toLocaleString()}
          {matches.length !== urls.length && (
            <span className="font-medium text-ink-faint"> of {urls.length.toLocaleString()}</span>
          )}{" "}
          URLs
        </p>
        <input
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setLimit(PAGE_SIZE);
          }}
          placeholder="Filter by path or host…"
          spellCheck={false}
          aria-label="Filter URLs"
          className="w-full rounded-full border border-line bg-haze px-4 py-2 text-[13.5px] outline-none transition-colors focus:border-leaf-300 focus:bg-surface"
        />
      </header>

      {shown.length === 0 ? (
        <p className="p-8 text-center text-[13.5px] text-ink-faint">
          {query.trim() ? "No URL matches that filter." : emptyMessage}
        </p>
      ) : (
        <ol className="tabular">
          {shown.map((url, index) => (
            <li
              key={url}
              className="flex items-baseline gap-3 border-b border-line px-4 py-2 last:border-b-0"
            >
              <span className="w-12 shrink-0 text-right font-mono text-[11px] text-ink-faint">
                {index + 1}
              </span>
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                className="min-w-0 truncate font-mono text-[12.5px] text-ink-soft hover:text-ink hover:underline"
              >
                {url}
              </a>
            </li>
          ))}
        </ol>
      )}

      {matches.length > shown.length && (
        <button
          type="button"
          onClick={() => setLimit((value) => value + PAGE_SIZE)}
          className="w-full border-t border-line py-3 text-[13px] font-bold text-leaf-700 transition-colors hover:bg-haze"
        >
          Show {Math.min(PAGE_SIZE, matches.length - shown.length)} more
        </button>
      )}
    </section>
  );
}
