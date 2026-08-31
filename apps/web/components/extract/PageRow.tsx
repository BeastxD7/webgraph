"use client";

import { useMemo, useState } from "react";

import type { PageEvent } from "@/lib/api";
import { compact } from "@/lib/format";

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const index = text.toLowerCase().indexOf(query.toLowerCase());
  if (index < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded bg-leaf-100 px-0.5 text-ink">
        {text.slice(index, index + query.length)}
      </mark>
      {text.slice(index + query.length)}
    </>
  );
}

export default function PageRow({
  page,
  query,
  contentOnly,
  showPath = false,
}: {
  page: PageEvent;
  query: string;
  contentOnly: boolean;
  /** True when other pages share this title, so the title alone identifies nothing. */
  showPath?: boolean;
}) {
  const [open, setOpen] = useState(false);

  const hasCleanView = Boolean(page.content_markdown);
  const [clean, setClean] = useState(contentOnly);
  const shown = clean && hasCleanView ? page.content_markdown : page.markdown;
  const removed = hasCleanView
    ? 1 - page.content_markdown.length / Math.max(page.markdown.length, 1)
    : 0;

  // A content match should be visible without opening the row, otherwise the reader has to
  // hunt through several thousand characters to see why the page matched.
  const snippet = useMemo(() => {
    if (!query) return null;
    const index = page.markdown.toLowerCase().indexOf(query.toLowerCase());
    if (index < 0) return null;
    const start = Math.max(0, index - 90);
    return `${start > 0 ? "…" : ""}${page.markdown
      .slice(start, index + query.length + 120)
      .replace(/\s+/g, " ")}…`;
  }, [page.markdown, query]);

  const path = page.url.replace(/^https?:\/\/[^/]+/, "") || "/";
  const label = page.title ? (showPath ? `${page.title} — ${path}` : page.title) : path;

  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-haze"
      >
        <span
          aria-hidden
          className={`text-[10px] text-ink-faint transition-transform ${open ? "rotate-90" : ""}`}
        >
          ▶
        </span>
        <span className="min-w-0 flex-1 truncate text-[14px] font-semibold">
          <Highlight text={label} query={query} />
        </span>

        <span className="tabular hidden shrink-0 items-center gap-2 text-[12px] text-ink-faint sm:flex">
          {page.ok ? (
            <>
              <span>{compact(page.markdown.length)} chars</span>
              {page.images.length > 0 && <span>{page.images.length} img</span>}
              {page.tables > 0 && <span>{page.tables} tbl</span>}
              {hasCleanView && (
                <span
                  title="Share of the page identified as site chrome"
                  className="rounded-full bg-leaf-50 px-2 py-0.5 font-semibold text-leaf-700"
                >
                  −{Math.round(removed * 100)}% chrome
                </span>
              )}
            </>
          ) : (
            <span className="text-flag-bad">{page.error?.slice(0, 48)}</span>
          )}
        </span>
      </button>

      {!open && snippet && (
        <p className="px-4 pb-3 pl-10 text-[12.5px] leading-relaxed text-ink-soft">
          <Highlight text={snippet} query={query} />
        </p>
      )}

      {open && page.ok && (
        <div className="border-t border-line bg-haze px-4 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <a
              href={page.url}
              target="_blank"
              rel="noreferrer"
              className="truncate font-mono text-[12px] text-ink-soft underline underline-offset-2 hover:text-ink"
            >
              {page.url}
            </a>

            {hasCleanView && (
              <div role="group" aria-label="Markdown view" className="flex rounded-full bg-sunk p-0.5">
                {[
                  { id: true, label: "Content only" },
                  { id: false, label: "Full page" },
                ].map((option) => (
                  <button
                    key={String(option.id)}
                    type="button"
                    aria-pressed={clean === option.id}
                    onClick={() => setClean(option.id)}
                    className={
                      clean === option.id
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

          {page.images.length > 0 && (
            <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
              {page.images.slice(0, 12).map((src) => (
                // Arbitrary remote hosts, so next/image's optimiser is not usable here.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={src}
                  src={src}
                  alt=""
                  loading="lazy"
                  className="h-16 w-24 shrink-0 rounded-lg border border-line object-cover"
                />
              ))}
            </div>
          )}

          <pre className="mt-3 max-h-96 overflow-auto rounded-xl border border-line bg-surface p-4 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
            {shown}
          </pre>
        </div>
      )}
    </li>
  );
}
