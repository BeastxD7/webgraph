"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import AskPanel from "./AskPanel";
import DepthTree from "./DepthTree";
import DiscoveryPanel from "./DiscoveryPanel";
import GraphPanel from "./GraphPanel";
import PageList from "./PageList";
import LivePipeline from "./LivePipeline";
import ProgressRail from "./ProgressRail";
import RunLog from "./RunLog";
import RunSummary from "./RunSummary";
import RunTabs, { type RunTab } from "./RunTabs";
import TechnologyPanel from "./TechnologyPanel";
import UrlList from "./UrlList";
import Citation from "@/components/ui/Citation";
import { PHASE_LABEL, STOPPED_BY_LABEL, useSiteStream } from "@/hooks/useSiteStream";
import { useTabTitle } from "@/hooks/useTabTitle";
import type { RunMeta } from "@/lib/runlog";

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
  useTabTitle(
    run.running ? "running" : run.phase === "failed" ? "failed" : run.phase === "stopped" ? "stopped" : "done",
    url.replace(/^https?:\/\//, "").split("/")[0] ?? url,
  );

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

  /**
   * The header of the copied log. `endedAt` comes from the run's own elapsed clock rather
   * than a `Date.now()` read during render, which would not be idempotent.
   */
  const logMeta: RunMeta = {
    url,
    mode: "whole site",
    request: { complete, max_pages: maxPages },
    header: (run.log.entries.current[0]?.event.type === "run"
      ? run.log.entries.current[0]?.event
      : null) as Record<string, unknown> | null,
    startedAt: run.log.startedAt.current,
    endedAt: run.running ? null : run.log.startedAt.current + run.elapsed * 1000,
    outcome: run.error ? `failed: ${run.error}` : run.phase,
  };

  return (
    <div className="page-col space-y-5 pb-20">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-2 text-[13.5px] font-semibold">
          <span aria-hidden className={`size-2 rounded-full ${PHASE_DOT[run.phase]}`} />
          {run.phase === "done" && run.summary && run.summary.stopped_by
            ? `${STOPPED_BY_LABEL[run.summary.stopped_by]} · ${run.summary.remaining_queued.toLocaleString("en-US")} pages not crawled`
            : PHASE_LABEL[run.phase]}
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

      <ProgressRail live={run.live} active={run.running} cap={run.cap} />

      {/* The stages themselves, filling in what each one found. A progress bar says how far
          along a run is; this says what the engine is actually doing and what it learned. */}
      <LivePipeline
        phase={run.phase}
        timings={run.timings}
        analysis={run.analysis}
        pages={run.pages}
        queued={run.live.queued}
        cap={run.cap}
        discovered={run.live.discovered}
        extracted={run.live.extracted}
        failed={run.live.failed}
        rate={run.live.rate}
        elapsed={run.elapsed}
        inFlight={run.inFlight}
      />

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

      <div className="flex flex-wrap gap-2">
        {(["extracted", "depth", "graph"] as const).map((view) => (
          <button
            key={view}
            type="button"
            aria-pressed={tab === view}
            onClick={() => setTab(view)}
            className={
              tab === view
                ? "rounded-full bg-ink px-3.5 py-1.5 text-[12.5px] font-bold text-inverse"
                : "rounded-full border border-line px-3.5 py-1.5 text-[12.5px] font-semibold text-ink-soft transition-colors hover:bg-haze"
            }
          >
            {view === "extracted" ? "Pages" : view === "depth" ? "Depth tree" : "Site graph"}
          </button>
        ))}
      </div>

      {/* Above the page lists rather than below them: a crawl that discovered 1,600 URLs
          would otherwise bury its own record under 1,600 rows. */}
      <RunLog log={run.log} meta={logMeta} />

      {run.analysis && <TechnologyPanel analysis={run.analysis} />}

      {/* Why discovery looks the way it does: what robots.txt asked, which sitemaps were
          tried, and what kind of thing the addresses are. Shown the moment Stage 0 reports
          it, and the kinds tally moves with every page. */}
      {run.discovery && (
        <DiscoveryPanel discovery={run.discovery} kinds={run.kinds} live={run.running} />
      )}

      {run.summary && <RunSummary summary={run.summary} />}

      {/* Available as soon as enough pages exist to be worth asking about, not only once the
          crawl finishes -- an unbounded crawl may never finish. */}
      {run.pages.length >= 3 && <AskPanel siteUrl={url} />}

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

      {tab === "graph" && <GraphPanel siteUrl={url} />}

      {tab === "depth" && (
        <DepthTree
          root={run.root}
          origins={run.origins}
          depthCounts={run.depthCounts}
          pages={run.pages}
          cap={run.cap}
        />
      )}

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
                  {/* Where the crawl got this address. On a failure it is the only fact a
                      reader can act on: a link that 404s from one page is that page's bug. */}
                  <Citation citation={page.citation} />
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
