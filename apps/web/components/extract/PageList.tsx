"use client";

import { useCallback, useMemo, useState } from "react";

import PageRow from "./PageRow";
import CopyButton from "@/components/ui/CopyButton";
import type { PageEvent } from "@/lib/api";
import { pageFileName, withFrontMatter, zipText } from "@/lib/zip";

export default function PageList({
  pages,
  siteUrl,
}: {
  pages: PageEvent[];
  siteUrl: string;
}) {
  const [query, setQuery] = useState("");
  // Full page by default, as on the single-page view.
  const [contentOnly, setContentOnly] = useState(false);

  // Failures live in their own tab, so this list is always the successful pages.
  const candidates = pages;

  // Content is searched as well as the URL: on a large crawl "pricing" is far more likely
  // to be a word on the page than a path segment.
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return candidates;
    return candidates.filter(
      (page) =>
        page.url.toLowerCase().includes(needle) ||
        page.title.toLowerCase().includes(needle) ||
        page.markdown.toLowerCase().includes(needle),
    );
  }, [candidates, query]);

  // Some sites put the project name in every `<h1>`, so a whole crawl arrives titled
  // "attrs: Classes Without Boilerplate". A title shared by several pages identifies none of
  // them, so those rows fall back to showing their path as well.
  const ambiguous = useMemo(() => {
    const counts = new Map<string, number>();
    for (const page of pages) {
      const title = page.title.trim();
      if (title) counts.set(title, (counts.get(title) ?? 0) + 1);
    }
    return new Set([...counts].filter(([, count]) => count > 1).map(([title]) => title));
  }, [pages]);

  /** Every successful page as one document, in crawl order, each headed by its URL. */
  const everything = useMemo(
    () =>
      pages
        .filter((page) => page.ok)
        .slice()
        .reverse()
        .map((page) => {
          const content =
            contentOnly && page.content_markdown ? page.content_markdown : page.markdown;
          return `<!-- ${page.url} -->\n\n${content}`;
        })
        .join("\n\n---\n\n"),
    [pages, contentOnly],
  );

  const save = useCallback((blob: Blob, name: string) => {
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = name;
    anchor.click();
    URL.revokeObjectURL(href);
  }, []);

  const download = useCallback(() => {
    save(new Blob([everything], { type: "text/markdown" }), `${new URL(siteUrl).hostname}.md`);
  }, [everything, siteUrl, save]);

  /** The same pages as one file each, named by their path, with `url` and `title` front
   *  matter -- the shape a folder of pages is expected in (Firecrawl's export, most
   *  static-site tools). The owner asked for it after downloading a 24-page site as one
   *  file and wanting the pages apart. */
  const downloadZip = useCallback(() => {
    const entries = pages
      .filter((page) => page.ok)
      .slice()
      .reverse()
      .map((page) => ({
        name: pageFileName(page.url),
        content: withFrontMatter(
          page.url,
          page.title,
          contentOnly && page.content_markdown ? page.content_markdown : page.markdown,
        ),
      }));
    const bytes = zipText(entries);
    save(new Blob([bytes], { type: "application/zip" }), `${new URL(siteUrl).hostname}.zip`);
  }, [pages, contentOnly, siteUrl, save]);

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
      <header className="flex flex-col gap-3 border-b border-line p-4 lg:flex-row lg:items-center">
        <h2 className="shrink-0 text-[15px] font-extrabold tracking-tight">
          Extracted pages{" "}
          <span className="tabular font-medium text-ink-faint">
            {query.trim() ? `${visible.length} of ${candidates.length}` : candidates.length}
          </span>
        </h2>

        <div className="relative min-w-0 flex-1">
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search URLs, titles and page content…"
            spellCheck={false}
            aria-label="Search extracted pages"
            className="w-full rounded-full border border-line bg-haze px-4 py-2 text-[13.5px] outline-none transition-colors focus:border-leaf-300 focus:bg-surface"
          />
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-3 text-[12.5px]">
          <label
            className="flex items-center gap-1.5 font-semibold text-ink-soft"
            title="Strip navigation, footers and other repeated site chrome"
          >
            <input
              type="checkbox"
              checked={contentOnly}
              onChange={(event) => setContentOnly(event.target.checked)}
              className="accent-leaf-600"
            />
            content only
          </label>
          {/* Copy and download hand over exactly the same document, and both follow the
              "content only" checkbox -- the one behaviour that is not surprising. */}
          <CopyButton text={everything} label="Copy all" />
          <button
            type="button"
            onClick={download}
            title="Every page in one Markdown file, in crawl order"
            className="rounded-full bg-ink px-3.5 py-1.5 font-bold text-inverse transition-opacity hover:opacity-85"
          >
            Download .md
          </button>
          <button
            type="button"
            onClick={downloadZip}
            title="One Markdown file per page, named by its path, with url and title front matter"
            className="rounded-full border border-line-strong bg-surface px-3.5 py-1.5 font-bold text-ink transition-colors hover:bg-haze"
          >
            .zip, a file per page
          </button>
        </div>
      </header>

      {visible.length === 0 ? (
        <p className="p-8 text-center text-[13.5px] text-ink-faint">
          {query.trim() ? "No page matches that search." : "No pages yet."}
        </p>
      ) : (
        <ul>
          {visible.map((page) => (
            <PageRow
              key={`${page.index}-${page.url}`}
              page={page}
              query={query.trim()}
              contentOnly={contentOnly}
              showPath={ambiguous.has(page.title.trim())}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
