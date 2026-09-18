"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  motion,
  useMotionValue,
  useMotionValueEvent,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
} from "motion/react";

export interface HowStep {
  title: string;
  body: string;
}

const STEP_COUNT = 5;

/** The curved path's spine, in a 100×1500 box the SVG stretches to fill the column. */
const CURVE_D = "M38,0 C38,50 38,80 38,120 C38,277.5 62,277.5 62,435 C62,592.5 38,592.5 38,750 "
  + "C38,907.5 62,907.5 62,1065 C62,1222.5 38,1222.5 38,1380 C38,1420 38,1460 38,1500";

/** Each step's stop, alternating either side of the curve. */
const STOPS: ReadonlyArray<{ left: string; top: string; side: "left" | "right" }> = [
  { left: "38%", top: "8%", side: "right" },
  { left: "62%", top: "29%", side: "left" },
  { left: "38%", top: "50%", side: "right" },
  { left: "62%", top: "71%", side: "left" },
  { left: "38%", top: "92%", side: "right" },
];

/**
 * The scroll story for "how it reads a page": the scene (`Scene.tsx`) pinned beside a
 * curved path of five numbered stops, its accent line filling in as the reader scrolls,
 * with alternating copy dimming in and out as each step becomes current. `.how-track`
 * holds both columns; scroll progress through it, smoothed by a spring, decides which
 * step is showing and writes it as `data-step`/`data-in` on `.how` -- the exact
 * attributes `how.css`'s cross-morph reads, unchanged from the three-step version this
 * replaces, just extended to five.
 *
 * Every step's copy is real, server-rendered DOM, always present (so a reader with no
 * JavaScript sees every one of them, stacked and readable); `how.css` only dims the
 * others once `main[data-motion]` confirms `Motion.tsx`'s enhancement is live -- the same
 * gate every other reveal on this page uses. Reduced motion (and, by `.how-track`'s own
 * CSS, a narrow viewport) skips the pin, the curve and the tall track outright and
 * renders `.how-static`: the scene stands at step one, the five steps simply stacked.
 */
export default function HowMotion({ steps = [], children }: { steps?: readonly HowStep[]; children?: ReactNode }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const fillRef = useRef<SVGPathElement>(null);
  const [step, setStep] = useState(0);
  // A Motion Value, not React state: `useTransform`'s single-value overload closes over
  // its transformer function and does not reliably pick up a *state* value changing after
  // the initial render, which left the fill line's dash-offset frozen at its mount-time
  // value (0 -- appearing fully painted, never responding to scroll). Combining two Motion
  // Values through the multi-value `useTransform` overload below is the pattern the library
  // actually supports for this.
  const fillLength = useMotionValue(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (fillRef.current) fillLength.set(fillRef.current.getTotalLength());
  }, [fillLength]);

  const { scrollYProgress } = useScroll({ target: trackRef, offset: ["start start", "end end"] });
  const spring = useSpring(scrollYProgress, { stiffness: 120, damping: 26, mass: 0.6 });
  // Five equal-width dwell ranges -- the same split the standalone mockup validated
  // (`idx = floor(progress * 5)`), just expressed as spring breakpoints.
  const stepValue = useTransform(
    spring,
    [0, 0.2, 0.2, 0.4, 0.4, 0.6, 0.6, 0.8, 0.8, 1],
    [0, 0, 1, 1, 2, 2, 3, 3, 4, 4],
  );
  // The capstone: a small overshoot as the scroll-through nears its end, so it reads as a
  // finish rather than an arbitrary cutoff into the section after.
  const stageScale = useTransform(spring, [0, 0.02, 0.98, 1], [0.96, 1, 1, 1.03]);
  const dashOffset = useTransform([spring, fillLength], ([p, len]) => (len as number) - (len as number) * (p as number));

  useMotionValueEvent(spring, "change", (v) => {
    if (panelRef.current && v > 0.01) panelRef.current.dataset.in = "";
  });
  useMotionValueEvent(stepValue, "change", (v) => {
    const rounded = Math.min(STEP_COUNT - 1, Math.max(0, Math.round(v)));
    if (panelRef.current) panelRef.current.dataset.step = String(rounded + 1);
    setStep(rounded);
  });

  function jumpTo(index: number) {
    const track = trackRef.current;
    if (!track) return;
    const rect = track.getBoundingClientRect();
    const total = Math.max(1, rect.height - window.innerHeight);
    const top = rect.top + window.scrollY + ((index + 0.5) / STEP_COUNT) * total;
    window.scrollTo({ top, behavior: "smooth" });
  }

  if (reduced) {
    return (
      <div className="how-static">
        <div className="how-stage">{children}</div>
        <div className="how-static-copy">
          {(steps ?? []).map((s, k) => (
            <div className="how-static-step" key={s.title}>
              <span className="how-num font-mono" aria-hidden>
                <span className="sr-only">Step {k + 1}: </span>
                {String(k + 1).padStart(2, "0")}
              </span>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div ref={trackRef} className="how-track">
      <div className="how-illustration-col">
        <div ref={panelRef} className="how how-stage-pin">
          <motion.div className="how-stage" style={{ scale: stageScale }}>
            {children}
          </motion.div>
        </div>
      </div>
      <div className="how-path">
        <svg className="how-curve" viewBox="0 0 100 1500" preserveAspectRatio="none" aria-hidden>
          <path className="how-track-line" d={CURVE_D} />
          <motion.path
            ref={fillRef}
            className="how-fill-line"
            d={CURVE_D}
            style={{ strokeDasharray: fillLength, strokeDashoffset: dashOffset }}
          />
        </svg>
        {(steps ?? []).map((s, k) => (
          <button
            key={`num-${s.title}`}
            type="button"
            className={`how-curve-num${k === step ? " is-active" : ""}`}
            style={{ left: STOPS[k]?.left, top: STOPS[k]?.top }}
            aria-label={`Go to step ${k + 1}: ${s.title}`}
            onClick={() => jumpTo(k)}
          >
            <span className="ping-ring" aria-hidden />
            <span>{String(k + 1).padStart(2, "0")}</span>
          </button>
        ))}
        {(steps ?? []).map((s, k) => (
          <div
            key={s.title}
            role="button"
            tabIndex={0}
            className={`how-copy how-copy--${STOPS[k]?.side ?? "right"}${k === step ? " is-active" : ""}`}
            style={{ top: STOPS[k]?.top }}
            onClick={() => jumpTo(k)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); jumpTo(k); }
            }}
          >
            <span className="num-mobile" aria-hidden>{String(k + 1).padStart(2, "0")}</span>
            <h3>{s.title}</h3>
            <p>{s.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
