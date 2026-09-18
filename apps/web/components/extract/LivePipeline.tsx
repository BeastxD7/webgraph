"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";

import type { AnalysisEvent, PageEvent } from "@/lib/api";
import type { Phase, PhaseTiming } from "@/hooks/useSiteStream";
import PageTypes from "./PageTypes";
import { TechName } from "@/components/ui/TechIcon";
import Timeline, { type TimelineStep } from "@/components/ui/Timeline";

/**
 * The engine's stages as they actually happen, not as a spinner.
 *
 * The crawl already streams what it is doing -- `stage`, `analysis`, `frontier`, `page` -- and
 * a single progress bar throws all of that away. Here each stage says what it is for, lights
 * up when it starts, and fills in what it *found* when it ends: which technologies, how many
 * routes, which fetch strategy the measurement chose.
 *
 * Two rules it follows. A stage is never shown as finished before its evidence arrives, and a
 * stage that has not started shows nothing rather than zeros -- a zero reads as a measurement,
 * and "not yet" is not a measurement.
 */

type StageId = "probe" | "queue" | "crawl";

const ORDER: readonly StageId[] = ["probe", "queue", "crawl"];

const COPY: Record<StageId, { title: string; does: string; phase: Phase }> = {
  probe: {
    title: "Look at the front door, once",
    does:
      "Fetches the home page two ways at the same time, plain HTTP and a real browser, and reads robots.txt and every sitemap it advertises.",
    phase: "analyzing",
  },
  queue: {
    title: "Build the queue",
    does:
      "Seeds from the sitemap and normalises every address, so one page reached four ways is crawled once.",
    phase: "enumerating",
  },
  crawl: {
    title: "Crawl, classify and extract",
    does:
      "Each page that returns has its links read and fed back, so the crawl reaches what the sitemap never listed. A trained classifier reads every page's type, and that decides how the content boundary is drawn -- on a listing the items are the content, on an article they are not.",
    phase: "extracting",
  },
};

/**
 * A clock that ticks only while something is still running.
 *
 * Reading `Date.now()` during render is impure -- the same render would produce a different
 * result depending on when React happened to run it. The running stage still needs a moving
 * duration, so the time is state that advances on an interval and stops when the run does.
 */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const ticker = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(ticker);
  }, [active]);
  return now;
}

function seconds(timing: PhaseTiming | undefined, now: number): string {
  if (!timing) return "";
  const end = timing.endedAt ?? now;
  return `${((end - timing.startedAt) / 1000).toFixed(1)}s`;
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line-soft py-1 last:border-b-0">
      <dt className="shrink-0 text-caption text-ink-faint">{label}</dt>
      <dd className="tabular min-w-0 break-words text-right font-mono text-caption text-ink-soft">{value}</dd>
    </div>
  );
}

export default function LivePipeline({
  phase,
  timings,
  analysis,
  pages,
  queued,
  cap = 0,
  discovered,
  extracted,
  failed,
  rate,
  elapsed,
  inFlight,
}: {
  phase: Phase;
  timings: Partial<Record<Phase, PhaseTiming>>;
  analysis: AnalysisEvent | null;
  pages: PageEvent[];
  queued: number;
  /** The server's page cap, 0 when unbounded. */
  cap?: number;
  discovered: number;
  extracted: number;
  failed: number;
  rate: number;
  elapsed: number;
  inFlight: string[];
}) {
  const now = useNow(phase !== "done" && phase !== "failed" && phase !== "stopped");
  const reached = (id: StageId) =>
    ORDER.indexOf(id) <= ORDER.indexOf(currentStage(phase));

  const latest = pages[0];

  /**
   * The last page to finish, described once.
   *
   * A scrolling list of everything already done is a log, and a log is the past. What is
   * worth a permanent place on screen is what is happening now and what just happened -- so
   * one line, replaced each time, rather than a column that only grows.
   */
  const justFinished = useMemo(() => {
    if (!latest) return null;
    if (!latest.ok) return { url: shortUrl(latest.url), detail: latest.error ?? "failed", ok: false };
    const kept =
      latest.content_blocks === null
        ? `${latest.blocks} blocks`
        : `${latest.content_blocks} of ${latest.blocks} blocks kept`;
    const steps = latest.content_methods.length
      ? latest.content_methods.join(" → ")
      : "nothing removed";
    return { url: shortUrl(latest.url), detail: `${kept} · ${steps}`, ok: true };
  }, [latest]);



  const live = phase !== "done" && phase !== "failed" && phase !== "stopped";
  const current = currentStage(phase);

  const steps: TimelineStep[] = [];
  for (const id of ORDER) {
    // The future is not drawn: a stage appears when it starts.
    if (!reached(id)) break;
    const copy = COPY[id];
    const timing = timings[copy.phase];
    const running = current === id && live;
    const ended = phase === "failed" || phase === "stopped";
    const state = running
      ? "running"
      : current === id && ended
        ? phase === "failed"
          ? "failed"
          : "stopped"
        : "done";
    const summary =
      id === "probe" && analysis
        ? `${analysis.technologies.slice(0, 3).map((t) => t.name).join(", ") || "no stack detected"} · ${analysis.strategy}`
        : id === "queue" && discovered > 0
          ? `${discovered.toLocaleString("en-US")} addresses${cap > 0 && queued > cap ? ` · cap ${cap}` : ""}`
          : id === "crawl"
            ? `${extracted.toLocaleString("en-US")} extracted${failed ? ` · ${failed} failed` : ""} · ${rate.toFixed(1)}/min`
            : undefined;
    steps.push({
      id,
      title: copy.title,
      description: copy.does,
      summary,
      state,
      duration: timing ? seconds(timing, now) : undefined,
      children: (
        <>
          {id === "probe" && analysis && (
            <dl className="mt-2.5">
              <Row
                label="Technologies identified"
                value={
                  analysis.technologies.length ? (
                    <span className="inline-flex flex-wrap justify-end gap-x-2.5 gap-y-0.5">
                      {analysis.technologies.slice(0, 4).map((t) => (
                        <TechName key={t.name} name={t.name} iconClassName="" />
                      ))}
                    </span>
                  ) : (
                    "none detected"
                  )
                }
              />
              <Row
                label="Plain HTTP vs browser"
                value={`${analysis.static_chars.toLocaleString("en-US")} vs ${analysis.rendered_chars.toLocaleString("en-US")} chars`}
              />
              <Row label="Merged, losing nothing" value={`${analysis.union_chars.toLocaleString("en-US")} chars`} />
              <Row
                label="Strategy chosen by measurement"
                value={analysis.render_required ? `${analysis.strategy} (browser needed)` : analysis.strategy}
              />
              {analysis.metadata && (
                <>
                  <Row label="Title" value={analysis.metadata.title ?? "none declared"} />
                  <Row
                    label="Canonical"
                    value={
                      analysis.metadata.declared_elsewhere.some((d) => d.startsWith("canonical")) ? (
                        <span className="text-flag-warn">{analysis.metadata.canonical} · another site</span>
                      ) : (
                        analysis.metadata.canonical ?? "none declared"
                      )
                    }
                  />
                  <Row label="Language" value={analysis.metadata.language ?? "none declared"} />
                </>
              )}
            </dl>
          )}

          {id === "queue" && discovered > 0 && (
            <dl className="mt-2.5">
              <Row label="Addresses accepted" value={discovered.toLocaleString("en-US")} />
              <Row label="Waiting in the queue" value={queued.toLocaleString("en-US")} />
              {cap > 0 && queued > cap && (
                <Row label="Will be crawled" value={`${cap.toLocaleString("en-US")} (the page cap)`} />
              )}
            </dl>
          )}

          {id === "crawl" && (
            <>
              <dl className="mt-2.5">
                <Row label="Extracted" value={`${extracted.toLocaleString("en-US")}${failed ? ` · ${failed} failed` : ""}`} />
                <Row
                  label="Still queued"
                  value={
                    cap > 0 && queued > Math.max(cap - extracted - failed, 0)
                      ? `${Math.max(cap - extracted - failed, 0).toLocaleString("en-US")} of ${queued.toLocaleString("en-US")} discovered (page cap ${cap})`
                      : queued.toLocaleString("en-US")
                  }
                />
                <Row label="Rate" value={`${rate.toFixed(1)} pages/min · ${elapsed.toFixed(0)}s elapsed`} />
                {latest?.ok && (
                  <Row
                    label="Most recent page"
                    value={`${latest.blocks} blocks → ${latest.content_blocks ?? latest.blocks} kept`}
                  />
                )}
                {latest?.ok && latest.page_type && (
                  <Row
                    label="Classifier read it as"
                    value={
                      latest.page_type === "unknown"
                        ? "not confident — using the default"
                        : `${latest.page_type} (${Math.round(latest.page_type_confidence * 100)}%)`
                    }
                  />
                )}
              </dl>

              <PageTypes pages={pages} total={extracted} />

              {inFlight.length > 0 && (
                <div className="mt-3 rounded-lg border border-line bg-sunk p-2.5">
                  <p className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-faint">
                    fetching now · {inFlight.length} at once
                  </p>
                  <ul className="mt-1.5 flex flex-col gap-1">
                    {inFlight.map((url) => (
                      <li key={url} className="flex items-center gap-2 font-mono text-[11px] text-ink-soft">
                        <span
                          aria-hidden
                          className="size-1.5 shrink-0 rounded-full bg-leaf-500 motion-safe:animate-[drift_1.2s_ease-in-out_infinite]"
                        />
                        <span className="truncate">{shortUrl(url)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {justFinished && (
                <p className="mt-2 truncate font-mono text-[11px] text-ink-faint">
                  <span className={justFinished.ok ? "text-leaf-700" : "text-clay"}>
                    {justFinished.ok ? "✓" : "✕"}
                  </span>{" "}
                  just finished {justFinished.url} — {justFinished.detail}
                </p>
              )}
            </>
          )}
        </>
      ),
    });
  }

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
      <header className="flex flex-wrap items-baseline gap-x-3 border-b border-line px-4 py-3">
        <h2 className="text-[15px] font-extrabold tracking-tight">What the engine is doing</h2>
        <span className="text-[12px] text-ink-faint">
          stage {steps.length} of {ORDER.length}
        </span>
      </header>

      <Timeline steps={steps} live={live} />
    </section>
  );
}

/** Enough of a URL to recognise it, without the scheme or a host repeated on every line. */
function shortUrl(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "") || url;
}

function currentStage(phase: Phase): StageId {
  if (phase === "analyzing") return "probe";
  if (phase === "enumerating") return "queue";
  return "crawl";
}
