"use client";

import { useState } from "react";

import type { PageEvent } from "@/lib/api";
import Why from "@/components/ui/Why";

/**
 * What the site is made of, and which pages make it up.
 *
 * A crawl of a hundred pages is hard to picture. A tally of the kinds of page found is the
 * shortest true description of a site: mostly articles with a few listings is a blog; mostly
 * products is a shop. It also makes the model's work visible, which is otherwise invisible --
 * a type is chosen for every page and until now nothing said so.
 *
 * Each row opens to the pages behind it, because a count nobody can check is a claim. And
 * each page carries the model's own reasoning, measured by withholding signals rather than
 * written by hand.
 *
 * `unknown` is shown rather than hidden. It means the classifier was not confident enough to
 * commit, which is a real answer and the one that keeps the default extraction behaviour.
 */
const LABEL: Record<string, string> = {
  article: "Articles",
  listing: "Listings",
  collection: "Collections",
  product: "Products",
  forum: "Forums",
  documentation: "Documentation",
  service: "Service pages",
  unknown: "Not confident",
};

function shortUrl(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "") || url;
}

export default function PageTypes({ pages, total }: { pages: PageEvent[]; total: number }) {
  const [open, setOpen] = useState<string | null>(null);

  const grouped = new Map<string, PageEvent[]>();
  for (const page of pages) {
    if (!page.ok) continue;
    const type = page.page_type || "unknown";
    const bucket = grouped.get(type);
    if (bucket) bucket.push(page);
    else grouped.set(type, [page]);
  }

  const rows = [...grouped.entries()].sort((a, b) => b[1].length - a[1].length);
  if (rows.length === 0) return null;

  return (
    <div className="mt-3 rounded-lg border border-line bg-surface p-3">
      <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-faint">
        what this site is made of
      </p>

      <ul className="mt-2 flex flex-col gap-1">
        {rows.map(([type, group]) => {
          const expanded = open === type;
          return (
            <li key={type}>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : type)}
                  className="grid flex-1 grid-cols-[minmax(0,7.5rem)_1fr_2.2rem] items-center gap-2 rounded px-1 py-1 text-left transition-colors hover:bg-haze"
                >
                  <span className="flex min-w-0 items-center gap-1">
                    <span
                      aria-hidden
                      className={`text-[9px] text-ink-faint transition-transform ${expanded ? "rotate-90" : ""}`}
                    >
                      ▶
                    </span>
                    <span
                      className={`truncate text-[12px] ${
                        type === "unknown" ? "italic text-ink-faint" : "font-semibold"
                      }`}
                    >
                      {LABEL[type] ?? type}
                    </span>
                  </span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-sunk">
                    <span
                      className={`block h-full rounded-full transition-[width] duration-500 ease-out ${
                        type === "unknown" ? "bg-ink-faint/40" : "bg-leaf-500"
                      }`}
                      style={{ width: `${(group.length / Math.max(total, 1)) * 100}%` }}
                    />
                  </span>
                  <span className="tabular text-right font-mono text-[11.5px] text-ink-soft">
                    {group.length}
                  </span>
                </button>

              </div>

              {expanded && (
                <ul className="mb-1 ml-4 flex max-h-52 flex-col gap-0.5 overflow-y-auto border-l border-line pl-3">
                  {group.map((page) => (
                    <li key={page.url} className="flex items-center gap-2 py-0.5">
                      <a
                        href={page.url}
                        target="_blank"
                        rel="noreferrer"
                        className="min-w-0 flex-1 truncate font-mono text-[11px] text-ink-soft underline-offset-2 hover:text-ink hover:underline"
                      >
                        {shortUrl(page.url)}
                      </a>
                      <span className="tabular shrink-0 font-mono text-[10.5px] text-ink-faint">
                        {Math.round(page.page_type_confidence * 100)}%
                      </span>
                      {/* Per page, never per category: the reasons that put this page here
                          are not the reasons that put the others here. */}
                      <Why
                        type={page.page_type}
                        confidence={page.page_type_confidence}
                        reasons={page.page_type_reasons ?? []}
                        runnerUp={page.page_type_runner_up}
                        label={`Why ${shortUrl(page.url)} was read as ${page.page_type}`}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
