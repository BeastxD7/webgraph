"use client";

import Why from "@/components/ui/Why";
import { STAGE_ORDER, type PageRun, type PageStage } from "@/hooks/usePageStream";

/**
 * One page's extraction, stage by stage, with what each stage measured.
 *
 * The same shape as the crawl's panel on purpose: the two halves of this product were doing
 * the same work and reporting it differently, and a reader who has understood one should not
 * have to learn the other.
 *
 * A stage shows nothing until its evidence arrives. A zero reads as a measurement, and "not
 * yet" is not a measurement.
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

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line-soft py-1 last:border-b-0">
      <dt className="shrink-0 text-[12px] text-ink-faint">{label}</dt>
      <dd className="tabular truncate text-right font-mono text-[12px] text-ink-soft">{value}</dd>
    </div>
  );
}

export default function PageStages({ run }: { run: PageRun }) {
  const reached = (stage: PageStage) => {
    if (run.error) {
      // A stage after the failure never ran, and drawing it as pending is the truth.
      const failedAt = STAGE_ORDER.indexOf(run.errorStage as PageStage);
      return failedAt >= 0 && STAGE_ORDER.indexOf(stage) < failedAt;
    }
    if (!run.current) return true;
    return STAGE_ORDER.indexOf(stage) < STAGE_ORDER.indexOf(run.current);
  };

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
      <header className="flex flex-wrap items-baseline gap-x-3 border-b border-line px-4 py-3">
        <h2 className="text-[15px] font-extrabold tracking-tight">What the engine is doing</h2>
        <span className="tabular ml-auto font-mono text-[11.5px] text-ink-faint">
          {run.elapsed.toFixed(1)}s
        </span>
      </header>

      <ol className="flex flex-col">
        {STAGE_ORDER.map((stage, index) => {
          const copy = COPY[stage];
          const done = reached(stage);
          const running = run.current === stage;
          const failed = run.error !== null && run.errorStage === stage;
          return (
            <li
              key={stage}
              className="grid grid-cols-[2.1rem_1fr] gap-x-3 border-b border-line px-4 py-3 last:border-b-0"
            >
              <div className="flex flex-col items-center">
                <span
                  className={`grid size-6 shrink-0 place-items-center rounded-full font-mono text-[11px] font-bold ${
                    failed
                      ? "bg-flag-bad text-white"
                      : done
                        ? "bg-leaf-600 text-white"
                        : running
                          ? "bg-leaf-100 text-leaf-700"
                          : "bg-sunk text-ink-faint"
                  }`}
                >
                  {failed ? "!" : done ? "✓" : index + 1}
                </span>
                {index < STAGE_ORDER.length - 1 && (
                  <span
                    aria-hidden
                    className={`my-1.5 w-px flex-1 ${done ? "bg-leaf-300" : "bg-line"}`}
                  />
                )}
              </div>

              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2.5">
                  <h3 className={`text-[13.5px] font-bold ${done || running ? "" : "text-ink-faint"}`}>
                    {copy.title}
                  </h3>
                  {running && (
                    <span className="rounded-full bg-leaf-50 px-2 py-0.5 font-mono text-[10.5px] font-semibold text-leaf-700">
                      running
                    </span>
                  )}
                </div>
                <p className="mt-1 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-faint">
                  {copy.does}
                </p>

                {stage === "resolve" && run.resolve && (
                  <dl className="mt-2.5">
                    <Row label="Strategy" value={run.resolve.strategy} />
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
                    <Row
                      label="Structured data"
                      value={run.parse.payloads.join(", ") || "none declared"}
                    />
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
                    <Row
                      label="Kept"
                      value={`${run.select.kept} of ${run.select.total} blocks`}
                    />
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
                    <Row
                      label="Markdown"
                      value={`${run.done.markdown.length.toLocaleString("en-US")} chars`}
                    />
                    <Row
                      label="Images · tables"
                      value={`${run.done.images.length} · ${run.done.tables}`}
                    />
                  </dl>
                )}

                {failed && (
                  <p className="mt-2 rounded-md bg-flag-bad/8 px-3 py-2 font-mono text-[12px] leading-relaxed break-words text-flag-bad">
                    {run.error}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
