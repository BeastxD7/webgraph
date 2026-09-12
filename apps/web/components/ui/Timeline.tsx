"use client";

import type { ReactNode } from "react";

/**
 * A run, told in the order it happened -- and only as far as it has got.
 *
 * The earlier panels drew every stage up front with the future ones greyed out, which reads
 * as a checklist: five things, three ticked. A run is not a checklist. Nothing is known
 * about a stage that has not started, and drawing it invites the reader to wait for a
 * specific thing rather than watch what is happening. So a step appears when it starts,
 * slides into place at the bottom, and the rail beneath the running step fades out rather
 * than pointing at anything.
 *
 * Every step stays expanded once it has happened. What a stage measured is the reason to
 * look at this panel at all, and collapsing it behind a click would hide the evidence that
 * a green tick is meant to summarise.
 */

export type TimelineState = "done" | "running" | "failed" | "stopped";

export interface TimelineStep {
  id: string;
  title: string;
  /** What this stage is for, in one sentence. Shown under the title. */
  description?: string;
  state: TimelineState;
  /** Elapsed time, already formatted. Ticks while running, freezes when done. */
  duration?: string;
  /** The evidence: what the stage found. Rendered below the description. */
  children?: ReactNode;
}

const DOT: Record<TimelineState, string> = {
  done: "bg-leaf-600 text-white",
  running: "bg-leaf-100 text-leaf-700 animate-[breathe_1.8s_ease-out_infinite]",
  failed: "bg-flag-bad text-white",
  stopped: "bg-ink-faint text-white",
};

const BADGE: Partial<Record<TimelineState, string>> = {
  running: "running",
  failed: "failed",
  stopped: "stopped",
};

export default function Timeline({
  steps,
  live,
}: {
  /** Only the steps that have started, in order. The future is not passed in. */
  steps: TimelineStep[];
  /** Whether more steps may still arrive; draws the fading rail tail under the last one. */
  live: boolean;
}) {
  return (
    <ol className="flex flex-col" aria-live="polite">
      {steps.map((step, index) => {
        const last = index === steps.length - 1;
        return (
          <li
            key={step.id}
            className="grid animate-[reveal_320ms_ease-out_both] grid-cols-[2.1rem_1fr] gap-x-3 px-4 py-3.5"
          >
            <div className="flex flex-col items-center">
              <span
                className={`grid size-6 shrink-0 place-items-center rounded-full font-mono text-[11px] font-bold ${DOT[step.state]}`}
                aria-label={step.state}
              >
                {step.state === "done" ? "✓" : step.state === "failed" ? "!" : index + 1}
              </span>
              {/* The rail. Solid between finished steps; under the last step it fades out
                  while the run is live, and ends when the run has ended. */}
              {!last && <span aria-hidden className="my-1.5 w-px flex-1 bg-leaf-300" />}
              {last && live && step.state === "running" && (
                <span
                  aria-hidden
                  className="my-1.5 h-8 w-px bg-gradient-to-b from-leaf-300 to-transparent"
                />
              )}
            </div>

            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-2.5">
                <h3 className="text-[13.5px] font-bold">{step.title}</h3>
                {BADGE[step.state] && (
                  <span
                    className={`rounded-full px-2 py-0.5 font-mono text-[10.5px] font-semibold ${
                      step.state === "failed"
                        ? "bg-flag-bad/10 text-flag-bad"
                        : step.state === "stopped"
                          ? "bg-sunk text-ink-soft"
                          : "bg-leaf-50 text-leaf-700"
                    }`}
                  >
                    {BADGE[step.state]}
                  </span>
                )}
                {step.duration && (
                  <span className="tabular ml-auto font-mono text-[11px] text-ink-faint">
                    {step.duration}
                  </span>
                )}
              </div>
              {step.description && (
                <p className="mt-1 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-faint">
                  {step.description}
                </p>
              )}
              {step.children}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
