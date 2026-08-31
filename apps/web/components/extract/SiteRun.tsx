"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import PageList from "./PageList";
import ProgressRail from "./ProgressRail";
import RunSummary from "./RunSummary";
import RunTabs, { type RunTab } from "./RunTabs";
import TechnologyPanel from "./TechnologyPanel";
import UrlList from "./UrlList";
import { PHASE_LABEL, useSiteStream } from "@/hooks/useSiteStream";

const PHASE_DOT: Record<string, string> = {
  analyzing: "bg-leaf-300 animate-pulse",
  enumerating: "bg-leaf-300 animate-pulse",
  extracting: "bg-leaf-600 animate-pulse",
  done: "bg-leaf-600",
  stopped: "bg-ink-faint",
  failed: "bg-flag-bad",
};

export default function SiteRun({
  url,
  complete,
  maxPages,
}: {
  url: string;
  complete: boolean;
  maxPages: number;
}) {
  const run = useSiteStream({ url, complete, maxPages });
  const [tab, setTab] = useState<RunTab>("extracted");

  const { succeeded, failedPages, queuedUrls } = useMemo(() => {
    const ok = run.pages.filter((page) => page.ok);
    const bad = run.pages.filter((page) => !page.ok);
    // Queued is everything discovered that has not yet come back as a page. That includes
    // the batch currently in flight, which is why this can sit a few above the server's own
    // frontier length; it is the number that matches the list beside it.
    const settled = new Set(run.pages.map((page) => page.url));
    return {
      succeeded: ok,
      failedPages: bad,
      queuedUrls: run.discoveredUrls.filter((candidate) => !settled.has(candidate)),
    };
  }, [run.pages, run.discoveredUrls]);

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 px-5 pb-20 sm:px-8">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-2 text-[13.5px] font-semibold">
          <span aria-hidden className={`size-2 rounded-full ${PHASE_DOT[run.phase]}`} />
          {PHASE_LABEL[run.phase]}
        </span>

        <div className="ml-auto flex items-center gap-2">
          {run.running ? (
            <button
              type="button"
              onClick={run.stop}
              className="rounded-full border border-line-strong bg-surface px-4 py-1.5 text-[13px] font-bold transition-colors hover:bg-haze"
            >
              Stop
            </button>
          ) : (
            <Link
              href="/#start"
              className="rounded-full bg-leaf-600 px-4 py-1.5 text-[13px] font-bold text-inverse transition-colors hover:bg-leaf-700"
            >
              Extract another site
            </Link>
          )}
        </div>
      </div>

      <ProgressRail live={run.live} active={run.running} />

      {run.error && (
        <p
          role="alert"
          className="rounded-2xl border border-flag-bad/25 bg-flag-bad/5 px-5 py-4 text-[13.5px] font-semibold text-flag-bad"
        >
          {run.error}
        </p>
      )}

      <RunTabs
        counts={{
          discovered: run.discoveredUrls.length,
          queued: queuedUrls.length,
          extracted: succeeded.length,
          failed: failedPages.length,
        }}
        live={run.live}
        elapsed={run.elapsed}
        active={tab}
        onSelect={setTab}
      />

      {run.analysis && <TechnologyPanel analysis={run.analysis} />}

      {run.summary && <RunSummary summary={run.summary} />}

      {tab === "discovered" && (
        <UrlList
          urls={run.discoveredUrls}
          emptyMessage="No URLs discovered yet."
        />
      )}

      {tab === "queued" && (
        <UrlList
          urls={queuedUrls}
          emptyMessage={
            run.running ? "Nothing waiting right now." : "The frontier was fully drained."
          }
        />
      )}

      {tab === "extracted" &&
        (succeeded.length > 0 ? (
          <PageList pages={succeeded} siteUrl={url} />
        ) : (
          <p className="rounded-2xl border border-line bg-surface px-5 py-8 text-center text-[13.5px] text-ink-faint">
            {run.running
              ? "Working through the first pages. Results appear here as they land."
              : "No page was extracted."}
          </p>
        ))}

      {tab === "failed" &&
        (failedPages.length > 0 ? (
          <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
            <ul>
              {failedPages.map((page) => (
                <li
                  key={`${page.index}-${page.url}`}
                  className="flex flex-col gap-1 border-b border-line px-4 py-3 last:border-b-0"
                >
                  <a
                    href={page.url}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate font-mono text-[12.5px] text-ink-soft hover:text-ink hover:underline"
                  >
                    {page.url}
                  </a>
                  <span className="text-[12.5px] font-semibold text-flag-bad">{page.error}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : (
          <p className="rounded-2xl border border-line bg-surface px-5 py-8 text-center text-[13.5px] text-ink-faint">
            Nothing has failed.
          </p>
        ))}
    </div>
  );
}
