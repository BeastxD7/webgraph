"use client";

import { useState } from "react";

import type { DiscoveredKinds, DiscoveryEvent } from "@/lib/api";
import { prettyUrl } from "@/lib/format";

/**
 * How the site can be discovered, and what the crawl is finding.
 *
 * The owner watched two whole-site crawls (vtu.ac.in, sode-edu.in) whose only word on
 * discovery was `from_sitemap: 0`. Neither site publishes a sitemap, and nothing on screen
 * said so, nor what robots.txt asked, nor that on vtu.ac.in 7,907 of the 17,126 addresses
 * found were PDFs -- which the crawl fetched one by one for a third of six hours to refuse
 * each as not HTML. Three rows, each a one-line verdict that opens to its evidence: the
 * robots.txt rules that apply to this client and the file itself; every sitemap address
 * tried and what came back; and a live tally of what kind of thing the addresses are.
 *
 * Collapsed by default. The summaries are the panel; the rest is there for whoever asks
 * "and how do you know".
 */

const KIND_LABEL: Record<keyof DiscoveredKinds, string> = {
  page: "Pages",
  pdf: "PDFs",
  image: "Images",
  other_file: "Other files",
  archive: "Date archives",
  category: "Categories",
  tag: "Tags",
};

/** `[one, many]`, for the summary line: "1 image", "7,907 PDFs". */
const KIND_NOUN: Record<keyof DiscoveredKinds, [string, string]> = {
  page: ["page", "pages"],
  pdf: ["PDF", "PDFs"],
  image: ["image", "images"],
  other_file: ["other file", "other files"],
  archive: ["date archive", "date archives"],
  category: ["category", "categories"],
  tag: ["tag", "tags"],
};

const KIND_ORDER: readonly (keyof DiscoveredKinds)[] = [
  "page",
  "pdf",
  "image",
  "other_file",
  "archive",
  "category",
  "tag",
];

const n = (value: number) => value.toLocaleString("en-US");

function Row({
  title,
  summary,
  note,
  open,
  onToggle,
  children,
}: {
  title: string;
  summary: string;
  /** A second line under the summary, shown collapsed too: the thing a reader must not miss. */
  note?: string | null;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-3 text-left transition-colors hover:bg-haze"
      >
        <span className="flex items-center gap-2 text-[13.5px] font-bold">
          <span
            aria-hidden
            className={`text-[10px] text-ink-faint transition-transform ${open ? "rotate-90" : ""}`}
          >
            ▶
          </span>
          {title}
        </span>
        <span className="text-[13px] text-ink-soft">{summary}</span>
        {note && <span className="basis-full pl-5 text-[12.5px] text-flag-warn">{note}</span>}
      </button>
      {open && <div className="border-t border-line bg-haze px-4 py-3">{children}</div>}
    </li>
  );
}

function RobotsRow({ robots }: { robots: DiscoveryEvent["robots"] }) {
  const [open, setOpen] = useState(false);
  const [showFile, setShowFile] = useState(false);
  const rules = robots.rules_for_us.filter((line) => !/^crawl-delay/i.test(line));

  const summary = !robots.found
    ? `not found${robots.fetched_status ? ` (HTTP ${robots.fetched_status})` : ""} — everything allowed`
    : robots.group === null
      ? "found · no rules for this client — everything allowed"
      : `found · ${rules.length === 1 ? "1 rule applies" : `${rules.length} rules apply`} to us${
          robots.crawl_delay ? ` · crawl-delay ${robots.crawl_delay}s` : ""
        }`;

  return (
    <Row title="robots.txt" summary={summary} open={open} onToggle={() => setOpen((v) => !v)}>
      {robots.found ? (
        <>
          <p className="text-[12.5px] text-ink-soft">
            {robots.group === null ? (
              <>
                The file names other clients only; nothing in it applies to{" "}
                <code className="font-mono">webgraph</code> or <code className="font-mono">*</code>.
              </>
            ) : (
              <>
                Read under <code className="font-mono">User-agent: {robots.group}</code>
                {robots.group === "*" ? " — the site does not name this client, so the wildcard group applies." : " — the site names this client."}
              </>
            )}
          </p>
          {robots.rules_for_us.length > 0 && (
            <ul className="mt-2 flex flex-col gap-0.5 font-mono text-[12px]">
              {robots.rules_for_us.map((line, index) => (
                <li
                  key={`${index}-${line}`}
                  className={
                    /^disallow/i.test(line)
                      ? "text-clay"
                      : /^allow/i.test(line)
                        ? "text-leaf-700"
                        : "text-ink-soft"
                  }
                >
                  {line}
                </li>
              ))}
            </ul>
          )}
          <button
            type="button"
            aria-expanded={showFile}
            onClick={() => setShowFile((v) => !v)}
            className="mt-3 flex items-center gap-2 text-[12px] font-semibold text-ink-soft hover:text-ink"
          >
            <span
              aria-hidden
              className={`text-[9px] text-ink-faint transition-transform ${showFile ? "rotate-90" : ""}`}
            >
              ▶
            </span>
            The file as served · {n(robots.text_chars)} chars
            {robots.text_truncated ? ` · first ${n(robots.text.length)} shown` : ""}
          </button>
          {showFile && (
            <pre className="mt-2 max-h-72 overflow-auto rounded-xl border border-line bg-surface p-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap break-all">
              {robots.text}
              {robots.text_truncated ? "\n…" : ""}
            </pre>
          )}
        </>
      ) : (
        <p className="text-[12.5px] text-ink-soft">
          <a
            href={robots.url}
            target="_blank"
            rel="noreferrer"
            className="font-mono underline-offset-2 hover:underline"
          >
            {prettyUrl(robots.url)}
          </a>{" "}
          {robots.fetched_status
            ? `answered HTTP ${robots.fetched_status}.`
            : "could not be fetched."}{" "}
          A site with no robots.txt has asked nothing of automated readers, so every page is
          allowed and no crawl-delay applies.
        </p>
      )}
    </Row>
  );
}

function SitemapsRow({ sitemaps, seeds }: { sitemaps: DiscoveryEvent["sitemaps"]; seeds: number }) {
  const [open, setOpen] = useState(false);
  const summary =
    sitemaps.found === 0
      ? "none published — discovery is by links only"
      : `${sitemaps.found === 1 ? "1 found" : `${sitemaps.found} found`} · ${n(sitemaps.total_urls)} URLs${
          seeds !== sitemaps.total_urls ? ` · ${n(seeds)} in scope` : ""
        }`;

  return (
    <Row title="Sitemaps" summary={summary} open={open} onToggle={() => setOpen((v) => !v)}>
      <p className="text-[12.5px] text-ink-soft">
        {sitemaps.attempts.length === 0
          ? "No sitemap address was tried."
          : `${sitemaps.attempts.length === 1 ? "One address was" : `${sitemaps.attempts.length} addresses were`} tried, in this order: what robots.txt advertised first, then the conventional locations, then anything an index listed.`}
      </p>
      {sitemaps.attempts.length > 0 && (
        <div className="mt-2 overflow-x-auto rounded-xl border border-line bg-surface">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-line text-left font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-faint">
                <th className="px-3 py-2 font-medium">address</th>
                <th className="px-3 py-2 font-medium">tried because</th>
                <th className="px-3 py-2 text-right font-medium">status</th>
                <th className="px-3 py-2 text-right font-medium">urls</th>
              </tr>
            </thead>
            <tbody>
              {sitemaps.attempts.map((attempt) => (
                <tr key={attempt.url} className="border-b border-line last:border-b-0">
                  <td className="max-w-[24rem] truncate px-3 py-1.5 font-mono text-ink-soft">
                    <a
                      href={attempt.url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline-offset-2 hover:text-ink hover:underline"
                    >
                      {prettyUrl(attempt.url)}
                    </a>
                  </td>
                  <td className="px-3 py-1.5 text-ink-faint">
                    {attempt.source === "robots"
                      ? "robots.txt advertised it"
                      : attempt.source === "index"
                        ? "a sitemap index listed it"
                        : "the conventional location"}
                  </td>
                  <td
                    className={`tabular px-3 py-1.5 text-right font-mono ${
                      attempt.ok ? "text-leaf-700" : "text-clay"
                    }`}
                  >
                    {attempt.status || "—"}
                    {attempt.status >= 200 && attempt.status < 300 && !attempt.ok ? " · not a sitemap" : ""}
                  </td>
                  <td className="tabular px-3 py-1.5 text-right font-mono text-ink-soft">
                    {attempt.index ? "index" : attempt.ok ? n(attempt.urls) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Row>
  );
}

function KindsRow({ kinds, live }: { kinds: DiscoveredKinds | null; live: boolean }) {
  const [open, setOpen] = useState(false);
  const counts = kinds ?? {
    page: 0,
    pdf: 0,
    image: 0,
    other_file: 0,
    archive: 0,
    category: 0,
    tag: 0,
  };
  const total = KIND_ORDER.reduce((sum, kind) => sum + counts[kind], 0);
  const files = counts.pdf + counts.other_file + counts.image;
  const present = KIND_ORDER.filter((kind) => counts[kind] > 0);

  const summary =
    total === 0
      ? live
        ? "nothing found yet"
        : "nothing found"
      : present
          .map((kind) => `${n(counts[kind])} ${KIND_NOUN[kind][counts[kind] === 1 ? 0 : 1]}`)
          .join(" · ");

  /**
   * Said in the collapsed row, not only inside it. A site that is mostly files is the one
   * fact about discovery a reader cannot afford to miss: the page count says how much of
   * the site reads as pages, and the files are on record with the page that linked to each.
   */
  const note =
    total > 0 && files > counts.page
      ? `Files outnumber pages${counts.pdf > 0 ? ` (${n(counts.pdf)} PDFs)` : ""}. Files are counted with the page that links to each, and never fetched.`
      : null;

  return (
    <Row
      title="URLs found by kind"
      summary={summary}
      note={note}
      open={open}
      onToggle={() => setOpen((v) => !v)}
    >
      <p className="text-[12.5px] text-ink-soft">
        Judged from each address alone as it is discovered, so the tally is live and costs
        nothing. Pages are what the crawl reads; PDFs are queued and refused on fetch; images
        and other files are counted here and never queued; date archives, categories and tags
        are lists of pages rather than pages.
      </p>
      <ul className="mt-2 flex flex-col gap-1">
        {KIND_ORDER.map((kind) => (
          <li key={kind} className="grid grid-cols-[minmax(0,8rem)_1fr_3.5rem] items-center gap-2">
            <span
              className={`truncate text-[12px] ${counts[kind] === 0 ? "text-ink-faint" : "font-semibold"}`}
            >
              {KIND_LABEL[kind]}
            </span>
            <span className="h-1.5 overflow-hidden rounded-full bg-sunk">
              <span
                className={`block h-full rounded-full transition-[width] duration-500 ease-out ${
                  kind === "page" ? "bg-leaf-500" : kind === "pdf" || kind === "other_file" ? "bg-clay" : "bg-ink-faint/40"
                }`}
                style={{ width: `${(counts[kind] / Math.max(total, 1)) * 100}%` }}
              />
            </span>
            <span className="tabular text-right font-mono text-[11.5px] text-ink-soft">
              {n(counts[kind])}
            </span>
          </li>
        ))}
      </ul>
    </Row>
  );
}

export default function DiscoveryPanel({
  discovery,
  kinds,
  live,
}: {
  discovery: DiscoveryEvent;
  kinds: DiscoveredKinds | null;
  /** Whether the crawl is still running, so an empty tally reads as "not yet". */
  live: boolean;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
      <header className="flex flex-wrap items-baseline gap-x-3 border-b border-line px-4 py-3">
        <h2 className="text-[15px] font-extrabold tracking-tight">How the site can be discovered</h2>
        <span className="text-[12px] text-ink-faint">
          robots.txt and sitemaps read once · kinds counted as addresses arrive
        </span>
      </header>
      <ul>
        <RobotsRow robots={discovery.robots} />
        <SitemapsRow sitemaps={discovery.sitemaps} seeds={discovery.seeds} />
        <KindsRow kinds={kinds} live={live} />
      </ul>
    </section>
  );
}
