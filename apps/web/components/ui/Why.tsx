"use client";

import { useCallback, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Why the classifier chose what it chose, for one page.
 *
 * The weights are measured rather than written: each signal is withheld from the model and
 * the drop in the chosen type's probability is what that signal was worth. So this is the
 * model's own answer to "what if you had not known this", which is what a person means by
 * "why" -- not a sentence someone wrote next to a label.
 *
 * Two things it gets right that the first version did not.
 *
 * It belongs to a *page*, never to a category. A category is a count, and the reasons that
 * put one page in it are not the reasons that put the others there -- showing one page's
 * explanation on a group heading implies a shared cause that was never measured.
 *
 * And it is rendered into `document.body` rather than beside its button. The pages live in a
 * scrolling list, and anything absolutely positioned inside a scroll container is clipped by
 * it: the panel was being cut in half by the very element it was describing. Fixed
 * positioning against the viewport, clamped to stay on screen, is the only placement that
 * cannot be cropped by an ancestor.
 */
const WIDTH = 300;
const MARGIN = 8;

export default function Why({
  type,
  confidence,
  reasons,
  runnerUp,
  label,
}: {
  type: string;
  confidence: number;
  reasons: Array<{ says: string; weight: number }>;
  runnerUp?: { type: string; confidence: number };
  label?: string;
}) {
  const [at, setAt] = useState<{ top: number; left: number; above: boolean } | null>(null);
  const anchor = useRef<HTMLButtonElement>(null);
  const id = useId();

  const place = useCallback(() => {
    const button = anchor.current;
    if (!button) return;
    const rect = button.getBoundingClientRect();
    // Above by default; below when there is not room, which there often is not for the
    // first row of a list.
    const above = rect.top > 260;
    setAt({
      top: above ? rect.top - MARGIN : rect.bottom + MARGIN,
      left: Math.min(
        Math.max(MARGIN, rect.left + rect.width / 2 - WIDTH / 2),
        window.innerWidth - WIDTH - MARGIN,
      ),
      above,
    });
  }, []);

  useLayoutEffect(() => {
    if (!at) return;
    // Re-place on scroll: fixed positioning does not follow the anchor, so a panel left
    // behind by a scrolling list would point at the wrong row.
    const update = () => place();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [at, place]);

  if (reasons.length === 0) return null;

  const open = at !== null;
  const close = () => setAt(null);

  return (
    <>
      <button
        ref={anchor}
        type="button"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        aria-label={label ?? `Why this page was read as ${type}`}
        onClick={() => (open ? close() : place())}
        onMouseEnter={place}
        onMouseLeave={close}
        onFocus={place}
        onBlur={close}
        onKeyDown={(event) => event.key === "Escape" && close()}
        className="grid size-4 shrink-0 place-items-center rounded-full border border-line text-[9px] font-bold text-ink-faint transition-colors hover:border-ink-faint hover:text-ink"
      >
        i
      </button>

      {open &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            id={id}
            role="tooltip"
            style={{
              position: "fixed",
              top: at.top,
              left: at.left,
              width: WIDTH,
              transform: at.above ? "translateY(-100%)" : undefined,
            }}
            className="z-50 rounded-xl border border-line bg-surface p-3 text-left shadow-lift"
          >
            <p className="text-[12.5px] font-bold">
              Read as {type}, {Math.round(confidence * 100)}% sure
            </p>
            <p className="mt-0.5 text-[11.5px] leading-snug text-ink-faint">
              Each signal is worth the confidence this page loses when the model is not shown
              it.
            </p>

            <ul className="mt-2 flex flex-col gap-1.5">
              {reasons.map((reason) => (
                <li key={reason.says}>
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="text-[12px] leading-snug text-ink-soft">{reason.says}</span>
                    <span className="tabular shrink-0 font-mono text-[11px] text-leaf-700">
                      {Math.round(reason.weight * 100)}%
                    </span>
                  </span>
                  <span className="mt-0.5 block h-1 overflow-hidden rounded-full bg-sunk">
                    <span
                      className="block h-full rounded-full bg-leaf-500"
                      style={{ width: `${Math.min(reason.weight * 200, 100)}%` }}
                    />
                  </span>
                </li>
              ))}
            </ul>

            {runnerUp?.type && (
              <p className="mt-2 border-t border-line-soft pt-1.5 text-[11.5px] text-ink-faint">
                Next closest: {runnerUp.type} at {Math.round(runnerUp.confidence * 100)}%
              </p>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}
