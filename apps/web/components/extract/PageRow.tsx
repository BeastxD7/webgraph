"use client";

import { useMemo, useState } from "react";

import type { PageEvent } from "@/lib/api";
import { compact } from "@/lib/format";
import CopyButton from "@/components/ui/CopyButton";
import MathBadge from "@/components/ui/MathBadge";
import { containsMath, renderMarkdown } from "@/lib/markdown";
import Citation from "@/components/ui/Citation";

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
  // Two orthogonal questions: *what* to show, and *how*. Kept as separate controls
  // rather than one four-way switch, because they are not alternatives to each other.
  const [preview, setPreview] = useState(true);
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
              {page.render_note && (
                <span title={page.render_note} className="rounded-full bg-flag-warn/10 px-2 py-0.5 font-semibold text-flag-warn">
                  gate hid the page
                </span>
              )}
              {page.strategy === "union" && page.rendered_chars === 0 && (page.static_chars ?? 0) > 0 && (
                <span
                  title={`The browser rendered an empty page; the plain fetch's ${page.static_chars} characters are what was read`}
                  className="rounded-full bg-sunk px-2 py-0.5 font-semibold text-ink-faint"
                >
                  render was empty
                </span>
              )}
              {page.canvas && (
                <span
                  title={`${page.canvas.words} readable words; ${page.canvas.canvases} canvas; ${compact(page.canvas.script_bytes)} bytes of script read`}
                  className="rounded-full bg-flag-warn/10 px-2 py-0.5 font-semibold text-flag-warn"
                >
                  drawn in a canvas
                </span>
              )}
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

      {open && !page.ok && (
        <div className="border-t border-line bg-haze px-4 py-4">
          {/* A failure is where provenance earns its place. The collapsed row can only fit a
              truncated message, and the two things needed to act on it -- what went wrong in
              full, and which page sent the crawl here -- both live below the fold. */}
          <p className="font-mono text-[12px] break-words text-flag-bad">{page.error}</p>
          <Citation citation={page.citation} className="mt-2 block" />
          <a
            href={page.url}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-block font-mono text-[11.5px] text-ink-soft underline underline-offset-2 hover:text-ink"
          >
            open {page.url.replace(/^https?:\/\//, "")}
          </a>
        </div>
      )}

      {open && page.ok && (
        <div className="border-t border-line bg-haze px-4 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="flex min-w-0 flex-col gap-0.5">
              <a
                href={page.url}
                target="_blank"
                rel="noreferrer"
                className="truncate font-mono text-[12px] text-ink-soft underline underline-offset-2 hover:text-ink"
              >
                {page.url}
              </a>
              {/* Where this came from. On a failure it is the only actionable fact. */}
              <Citation citation={page.citation} className="truncate" />
            </span>

            <div className="flex flex-wrap items-center gap-2">
              {page.page_type && page.page_type !== "unknown" && (
                <span
                  className="rounded-full bg-sunk px-2.5 py-1 font-mono text-[11px] text-ink-soft"
                  title={`Classifier confidence ${Math.round(page.page_type_confidence * 100)}%`}
                >
                  {page.page_type}
                </span>
              )}
              {containsMath(shown) && <MathBadge preview={preview} />}
              {/* Copies exactly what is on screen: switching the toggle changes what you get,
                  which is the only behaviour that is not surprising. */}
              <CopyButton text={shown} label={clean && hasCleanView ? "Copy content" : "Copy page"} />
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
                  { id: false, label: "Full page" },
                  { id: true, label: "Content only" },
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
          </div>

          {page.canvas && (
            <p className="mt-3 rounded-xl border border-flag-warn/30 bg-flag-warn/10 px-4 py-2.5 text-small text-ink-soft">
              <span className="font-bold text-flag-warn">Content drawn in a canvas.</span> This page has{" "}
              {page.canvas.words} readable {page.canvas.words === 1 ? "word" : "words"} and {page.canvas.canvases}{" "}
              {page.canvas.canvases === 1 ? "canvas" : "canvases"}; what it shows is drawn by script, not written in
              the page. A reader without JavaScript and a click — a search engine, a screen reader, this crawl — gets
              the words.{page.canvas.script_bytes > 0 && ` ${compact(page.canvas.script_bytes)} bytes of its own script were read for the addresses it holds.`}
            </p>
          )}

          <LinksOut links={page.links_out} />

          {page.images.length > 0 && (
            <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
              {page.images.slice(0, 12).map((src, n) => (
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
            <div className="mt-3 max-h-96 overflow-auto rounded-xl border border-line bg-surface px-4 py-3 text-[14px]">
              {renderMarkdown(shown)}
            </div>
          ) : (
            <pre className="mt-3 max-h-96 overflow-auto rounded-xl border border-line bg-surface p-4 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
              {shown}
            </pre>
          )}
        </div>
      )}
    </li>
  );
}

/** Where the page points beyond this site: its real links, and -- for a canvas page -- the
 * addresses its scripts hold. Two lists, labelled, because they are two different facts: a
 * link is something the page offers a reader; a URL in a bundle is something the code says. */
function LinksOut({ links }: { links: PageEvent["links_out"] }) {
  if (!links || (links.external.length === 0 && links.in_script.length === 0)) return null;
  const host = (url: string) => url.replace(/^https?:\/\//, "").replace(/^www\./, "");
  return (
    <div className="mt-3 grid gap-3 sm:grid-cols-2">
      {links.external.length > 0 && (
        <div className="rounded-xl border border-line bg-surface px-4 py-3">
          <p className="text-label font-bold uppercase tracking-[0.1em] text-ink-faint">
            Links to other sites · {links.external.length}
          </p>
          <ul className="mt-1.5 space-y-1">
            {links.external.slice(0, 20).map((l) => (
              <li key={l.url} className="flex items-baseline gap-2 text-small">
                <a href={l.url} target="_blank" rel="noreferrer" className="min-w-0 truncate font-mono text-ink-soft hover:text-ink hover:underline" title={l.url}>
                  {host(l.url)}
                </a>
                {l.anchor && <span className="shrink-0 truncate text-caption text-ink-faint">“{l.anchor.slice(0, 40)}”</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {links.in_script.length > 0 && (
        <div className="rounded-xl border border-line bg-surface px-4 py-3">
          <p className="text-label font-bold uppercase tracking-[0.1em] text-ink-faint">
            Addresses in its scripts · {links.in_script.length}
          </p>
          <p className="mt-0.5 text-caption text-ink-faint">Found in code, not on the page. Not crawled.</p>
          <ul className="mt-1.5 space-y-1">
            {links.in_script.slice(0, 20).map((l) => (
              <li key={l.url} className="flex items-baseline gap-2 text-small">
                <span className="shrink-0 rounded bg-sunk px-1 font-mono text-caption text-ink-faint">{l.key}</span>
                <a href={l.url} target="_blank" rel="noreferrer" className="min-w-0 truncate font-mono text-ink-soft hover:text-ink hover:underline" title={l.url}>
                  {host(l.url)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
