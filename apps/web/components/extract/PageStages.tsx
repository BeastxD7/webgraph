"use client";

import Timeline, { type TimelineStep } from "@/components/ui/Timeline";
import Why from "@/components/ui/Why";
import { STAGE_ORDER, type PageRun, type PageStage } from "@/hooks/usePageStream";
import { strategyLabel } from "@/lib/api";

/**
 * One page's extraction, stage by stage, with what each stage measured.
 *
 * The same shape as the crawl's panel on purpose: the two halves of this product were doing
 * the same work and reporting it differently, and a reader who has understood one should not
 * have to learn the other.
 *
 * A stage shows nothing until its evidence arrives. A zero reads as a measurement, and "not
 * yet" is not a measurement -- and a stage that has not started is not shown at all. The
 * panel is a timeline of what has happened, revealed as it happens, not a checklist of what
 * is planned.
 */
const COPY: Record<PageStage, { title: string; does: string }> = {
  resolve: {
    title: "Fetch it both ways",
    does: "Plain HTTP and a real browser, merged. Neither alone can be trusted to be complete.",
  },
  parse: {
    title: "Turn markup into blocks",
    does: "One block per element that holds text, then put them in the order a person reads.",
  },
  classify: {
    title: "Read the page type",
    does: "A trained classifier decides what kind of page this is, and that chooses how the content boundary is drawn.",
  },
  select: {
    title: "Decide what counts as content",
    does: "Landmarks, then the main region, then the boundary. The complete document is never reduced.",
  },
  done: { title: "Hand it back", does: "Text, Markdown, images and tables." },
};

/** The resolve stage when the reader supplied the HTML: nothing was fetched, and a title
 *  saying "fetch it both ways" would be describing a run that did not happen. */
const SUPPLIED_RESOLVE = {
  title: "Read the HTML you supplied",
  does: "Nothing fetched or rendered. Reading order is source order, and what a browser would have hidden may appear.",
};

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line-soft py-1 last:border-b-0">
      <dt className="shrink-0 text-[12px] text-ink-faint">{label}</dt>
      <dd className="tabular truncate text-right font-mono text-[12px] text-ink-soft">{value}</dd>
    </div>
  );
}

export default function PageStages({ run }: { run: PageRun }) {
  /** Where each stage ended, in seconds since the run began, from the engine's own clock. */
  const endedAt: Partial<Record<PageStage, number>> = {
    resolve: run.resolve?.at,
    parse: run.parse?.at,
    classify: run.classify?.at,
    select: run.select?.at,
    done: run.done?.at,
  };

  const failedAt = run.error ? (run.errorStage as PageStage) : null;
  const failedIndex = failedAt ? STAGE_ORDER.indexOf(failedAt) : -1;

  const steps: TimelineStep[] = [];
  const supplied = run.resolve?.strategy === "supplied";

  for (const [index, stage] of STAGE_ORDER.entries()) {
    const copy = stage === "resolve" && supplied ? SUPPLIED_RESOLVE : COPY[stage];
    const finished = endedAt[stage] !== undefined;
    const running = run.current === stage && !run.error;
    const failed = failedIndex === index;
    // The future is not drawn. A stage appears when it starts, and a stage after a failure
    // never started.
    if (!finished && !running && !failed) break;
    // A transport failure names no stage the engine knows; it lands on whatever was running.
    const previous = index > 0 ? endedAt[STAGE_ORDER[index - 1] as PageStage] : 0;
    const duration = finished
      ? `${Math.max(0, (endedAt[stage] ?? 0) - (previous ?? 0)).toFixed(1)}s`
      : running
        ? `${Math.max(0, run.elapsed - (previous ?? 0)).toFixed(1)}s`
        : undefined;

    // What the collapsed line says: the one fact worth a glance per stage.
    const summary =
      stage === "resolve" && run.resolve
        ? `${strategyLabel(run.resolve.strategy)} · ${run.resolve.union_chars.toLocaleString("en-US")} chars`
        : stage === "parse" && run.parse
          ? `${run.parse.blocks.toLocaleString("en-US")} blocks · ${run.parse.words.toLocaleString("en-US")} words · ${run.parse.reading_order}`
          : stage === "classify" && run.classify
            ? run.classify.page_type === "unknown"
              ? "not confident — default policy"
              : `${run.classify.page_type} (${Math.round(run.classify.confidence * 100)}%)`
            : stage === "select" && run.select
              ? `kept ${run.select.kept} of ${run.select.total} blocks`
              : stage === "done" && run.done
                ? `${run.done.markdown.length.toLocaleString("en-US")} chars of Markdown · ${run.done.images.length} images`
                : undefined;
    steps.push({
      id: stage,
      title: copy.title,
      description: copy.does,
      summary,
      state: failed ? "failed" : finished ? "done" : "running",
      duration,
      children: (
        <>
          {stage === "resolve" && run.resolve && (
            <dl className="mt-2.5">
              <Row label="Strategy" value={strategyLabel(run.resolve.strategy)} />
              {supplied ? (
                // One representation, unmeasured: a "plain HTTP vs browser" comparison
                // would be comparing the paste with a fetch that never happened.
                <Row
                  label="Read from your HTML"
                  value={`${run.resolve.union_chars.toLocaleString("en-US")} chars`}
                />
              ) : (
                <>
                  <Row
                    label="Plain HTTP vs browser"
                    value={`${run.resolve.static_chars.toLocaleString("en-US")} vs ${run.resolve.rendered_chars.toLocaleString("en-US")} chars`}
                  />
                  <Row
                    label="Merged, losing nothing"
                    value={`${run.resolve.union_chars.toLocaleString("en-US")} chars`}
                  />
                  <Row
                    label="Plain HTTP alone would have given"
                    value={`${Math.round(run.resolve.static_coverage * 100)}% of it`}
                  />
                  {run.resolve.render_error && (
                    <Row label="Browser" value={run.resolve.render_error.slice(0, 60)} />
                  )}
                </>
              )}
            </dl>
          )}

          {stage === "parse" && run.parse && (
            <dl className="mt-2.5">
              <Row
                label="Blocks"
                value={`${run.parse.blocks.toLocaleString("en-US")} · ${run.parse.words.toLocaleString("en-US")} words`}
              />
              <Row label="Reading order" value={run.parse.reading_order} />
              <Row
                label="Kinds"
                value={
                  Object.entries(run.parse.kinds)
                    .slice(0, 4)
                    .map(([kind, n]) => `${n} ${kind}`)
                    .join(", ") || "none"
                }
              />
              <Row label="Structured data" value={run.parse.payloads.join(", ") || "none declared"} />
            </dl>
          )}

          {stage === "classify" && run.classify && (
            <dl className="mt-2.5">
              <div className="flex items-center gap-2 border-b border-line-soft py-1">
                <dt className="shrink-0 text-[12px] text-ink-faint">Read as</dt>
                <dd className="ml-auto flex items-center gap-1.5 font-mono text-[12px] text-ink-soft">
                  {run.classify.available
                    ? run.classify.page_type === "unknown"
                      ? "not confident — using the default"
                      : `${run.classify.page_type} (${Math.round(run.classify.confidence * 100)}%)`
                    : "no classifier shipped"}
                  {run.classify.reasons.length > 0 && (
                    <Why
                      type={run.classify.page_type}
                      confidence={run.classify.confidence}
                      reasons={run.classify.reasons}
                      runnerUp={run.classify.runner_up}
                    />
                  )}
                </dd>
              </div>
              {run.classify.runner_up.type && (
                <Row
                  label="Next closest"
                  value={`${run.classify.runner_up.type} (${Math.round(run.classify.runner_up.confidence * 100)}%)`}
                />
              )}
            </dl>
          )}

          {stage === "select" && run.select && (
            <dl className="mt-2.5">
              <Row label="Kept" value={`${run.select.kept} of ${run.select.total} blocks`} />
              <Row
                label="Steps that removed something"
                value={run.select.methods.join(" → ") || "nothing removed"}
              />
              {Object.entries(run.select.removed)
                .filter(([, n]) => n > 0)
                .map(([step, n]) => (
                  <Row key={step} label={step.replace(/_/g, " ")} value={`−${n} blocks`} />
                ))}
            </dl>
          )}

          {stage === "done" && run.done && (
            <dl className="mt-2.5">
              <Row label="Markdown" value={`${run.done.markdown.length.toLocaleString("en-US")} chars`} />
              <Row label="Images · tables" value={`${run.done.images.length} · ${run.done.tables}`} />
            </dl>
          )}

          {failed && (
            <p className="mt-2 rounded-md bg-flag-bad/8 px-3 py-2 font-mono text-[12px] leading-relaxed break-words text-flag-bad">
              {run.error}
            </p>
          )}
        </>
      ),
    });
    if (failed) break;
  }

  // A failure the engine could not place (the API down, the request refused) still needs a
  // line on the timeline, or the run ends with no explanation on screen.
  if (run.error && failedIndex < 0) {
    steps.push({
      id: "transport",
      title: "The request did not complete",
      state: "failed",
      children: (
        <p className="mt-2 rounded-md bg-flag-bad/8 px-3 py-2 font-mono text-[12px] leading-relaxed break-words text-flag-bad">
          {run.error}
        </p>
      ),
    });
  }

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
      <header className="flex flex-wrap items-baseline gap-x-3 border-b border-line px-4 py-3">
        <h2 className="text-[15px] font-extrabold tracking-tight">What the engine is doing</h2>
        <span className="text-[12px] text-ink-faint">
          step {Math.min(steps.length, STAGE_ORDER.length)} of {STAGE_ORDER.length}
        </span>
        <span className="tabular ml-auto font-mono text-[11.5px] text-ink-faint">
          {run.elapsed.toFixed(1)}s
        </span>
      </header>
      <Timeline steps={steps} live={run.running} />
    </section>
  );
}
