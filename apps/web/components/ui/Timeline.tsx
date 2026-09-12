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
 * The visual grammar is the one order-tracking pages settled on years ago, because it is
 * read by more people than any other timeline: a large disc per step (a tick when done, a
 * turning arc while running), a hairline between discs, the step's name with its status
 * in a quieter line beneath, and -- when a step has parts of its own -- a rounded elbow
 * into an indented list where finished parts are struck through, the current one is a
 * filled dot, and the ones still to come are hollow rings.
 *
 * Every step stays expanded once it has happened. What a stage measured is the reason to
 * look at this panel at all, and collapsing it behind a click would hide the evidence that
 * a tick is meant to summarise.
 */

export type TimelineState = "done" | "running" | "failed" | "stopped";

export interface SubStep {
  id: string;
  label: string;
  state: "done" | "current" | "pending";
}

export interface TimelineStep {
  id: string;
  title: string;
  /** The status line under the title: "Completed in 3.9s", "In progress", the failure. */
  status: string;
  state: TimelineState;
  /** What this stage is for, in one sentence. Shown under the status. */
  description?: string;
  /** Parts of this step, shown in an indented sub-list joined by an elbow. */
  substeps?: SubStep[];
  /** The evidence: what the stage found. Rendered below the description. */
  children?: ReactNode;
}

function Check({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" className={className} aria-hidden>
      <path d="M5 10.5l3.2 3.2L15 6.8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Cross({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" className={className} aria-hidden>
      <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/** The running marker: a grey ring with a quarter arc that turns. */
function Arc() {
  return (
    <svg viewBox="0 0 44 44" className="size-11 motion-safe:animate-[spin_1.6s_linear_infinite]" aria-hidden>
      <circle cx="22" cy="22" r="19" fill="none" className="stroke-line" strokeWidth="2.5" />
      <circle
        cx="22"
        cy="22"
        r="19"
        fill="none"
        className="stroke-leaf-600"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray="30 200"
        transform="rotate(-90 22 22)"
      />
    </svg>
  );
}

function Marker({ state }: { state: TimelineState }) {
  if (state === "running") return <Arc />;
  const disc =
    state === "done"
      ? "border-leaf-200 bg-leaf-50 text-leaf-600"
      : state === "failed"
        ? "border-flag-bad/30 bg-flag-bad/10 text-flag-bad"
        : "border-line bg-sunk text-ink-faint";
  return (
    <span className={`grid size-11 place-items-center rounded-full border ${disc}`} aria-label={state}>
      {state === "failed" ? <Cross className="size-5" /> : state === "stopped" ? <span className="block h-0.5 w-4 rounded bg-current" /> : <Check className="size-5" />}
    </span>
  );
}

function SubSteps({ items, continues }: { items: SubStep[]; continues: boolean }) {
  return (
    <>
      {/* Left column: the elbow. Down from the disc's centre, then a rounded turn to the
          right, into the sub-list. When the main rail carries on below, it runs beside. */}
      <div aria-hidden className="relative">
        <div className="absolute -top-1 left-[calc(1.375rem-0.5px)] h-8 w-5 rounded-bl-2xl border-b border-l border-line" />
        {continues && <div className="absolute top-0 bottom-0 left-[calc(1.375rem-0.5px)] w-px bg-line" />}
      </div>
      <ol className="mt-3.5 mb-2 flex flex-col">
        {items.map((item, index) => (
          <li key={item.id} className="grid grid-cols-[1.25rem_1fr] items-stretch gap-x-3">
            <div className="flex flex-col items-center">
              {item.state === "done" ? (
                <Check className="mt-1 size-4 shrink-0 text-leaf-600" />
              ) : item.state === "current" ? (
                <span className="mt-1.5 block size-3 shrink-0 rounded-full bg-leaf-600" />
              ) : (
                <span className="mt-1.5 block size-3 shrink-0 rounded-full border-[1.5px] border-line" />
              )}
              {index < items.length - 1 && (
                <span className="my-1 w-px flex-1 border-l border-dashed border-line" />
              )}
            </div>
            <span
              className={`truncate pb-2.5 font-mono text-[13px] leading-6 ${
                item.state === "done"
                  ? "text-ink-faint line-through decoration-ink-faint/60"
                  : item.state === "current"
                    ? "font-semibold text-ink"
                    : "text-ink-faint"
              }`}
              title={item.label}
            >
              {item.label}
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}

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
    <ol className="flex flex-col px-5 py-4" aria-live="polite">
      {steps.map((step, index) => {
        const last = index === steps.length - 1;
        return (
          <li
            key={step.id}
            className="grid animate-[reveal_320ms_ease-out_both] grid-cols-[2.75rem_1fr] gap-x-4"
          >
            <div className="flex flex-col items-center">
              <Marker state={step.state} />
              {/* The rail: solid down to the next step, or down to this step's own
                  sub-list; a fading tail under a running last step with no parts yet. */}
              {(!last || (step.substeps?.length ?? 0) > 0) && (
                <span aria-hidden className="my-1 w-px flex-1 bg-line" />
              )}
              {last && live && step.state === "running" && !(step.substeps?.length ?? 0) && (
                <span aria-hidden className="my-1 h-8 w-px bg-gradient-to-b from-line to-transparent" />
              )}
            </div>

            <div className={`min-w-0 ${last ? "pb-1" : "pb-6"}`}>
              <h3 className="pt-1.5 text-[17px] font-semibold leading-tight tracking-tight text-ink">
                {step.title}
              </h3>
              <p
                className={`mt-1 text-[13.5px] ${
                  step.state === "failed" ? "text-flag-bad" : "text-ink-soft"
                }`}
              >
                {step.status}
              </p>
              {step.description && (
                <p className="mt-1.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-faint">
                  {step.description}
                </p>
              )}
              {step.children}
            </div>

            {step.substeps && step.substeps.length > 0 && (
              <SubSteps items={step.substeps} continues={!last} />
            )}
          </li>
        );
      })}
    </ol>
  );
}
