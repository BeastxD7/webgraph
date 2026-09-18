"use client";

import { useEffect, useRef, useState } from "react";
import {
  motion,
  useMotionValue,
  useMotionValueEvent,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
} from "motion/react";

import Step1Intro from "./Step1Intro";
import Step2Fetch from "./Step2Fetch";
import Step3Refuse from "./Step3Refuse";
import Step4Order from "./Step4Order";
import Step5Graph from "./Step5Graph";

export interface HowStep {
  title: string;
  body: string;
}

const STEP_COUNT = 5;

/** One flat illustration per step, each looping its own story on its own clock while its
 * step is current (`active`) -- see `useTriggeredLoop`. All five are stacked on the stage
 * and `how.css` crossfades to the one `data-step` names. They're `aria-hidden`: real DOM
 * with text, but decorative -- everything a reader needs is in the captions. */
const SCENES = [Step1Intro, Step2Fetch, Step3Refuse, Step4Order, Step5Graph] as const;

/** How far an illustration may scale up to fill the stage; past this the type gets big. */
const STAGE_ZOOM_MAX = 1.35;

/**
 * The curved path's spine, in a 100×1500 box the SVG stretches to fill the column.
 *
 * The column is three lanes: caption-left (x 0..40), the curve's lane (x 40..60), and
 * caption-right (x 60..100). The caption is pinned at the viewport's center while the curve
 * scrolls past it, so the two must never share horizontal space -- the curve stays inside
 * its lane for its whole length, and within the lane it leans *away* from whichever side
 * the current step's caption is on (x 45 while the caption is right, x 55 while it's left).
 *
 * It runs from the first stop to the last, not edge to edge: the numbered circles are its
 * two ends (the line's own caps sit under them), so it reads as a route between stops
 * rather than a line arriving from under the navbar and stopping in mid-air.
 *
 * Where it leans is tied to what's at the viewport's center during each step: the pinned
 * stage is 100vh tall inside a 325vh track, so during step k (scroll fraction 0.2k..0.2k+0.2)
 * the center sweeps path fractions (45k+50)/325 .. (45k+95)/325. The lean switches sides at
 * those band edges (y 438, 647, 854, 1062 of 1500), and each stop sits at its band's center
 * -- so stop k slides through the caption's height exactly midway through step k, on the
 * opposite side from the caption. */
const CURVE_D = "M45,335 L45,398 C45,438 55,438 55,478 L55,607 C55,647 45,647 45,687 "
  + "L45,814 C45,854 55,854 55,894 L55,1022 C55,1062 45,1062 45,1102 L45,1165";

/** The line's length as drawn, not as authored: it's stroked with `non-scaling-stroke`
 * (one crisp width however the 100×1500 box is stretched -- without it the stretch makes
 * a 4-unit stroke a 24px ribbon), and that puts the dash pattern in screen pixels too
 * (`pathLength` is ignored under it), so the fill's dasharray must be measured the same
 * way: the path sampled in box units, each step scaled by the box's actual stretch. */
function drawnLength(path: SVGPathElement): number {
  const total = path.getTotalLength();
  const box = path.ownerSVGElement?.getBoundingClientRect();
  if (!box || !box.width || !box.height) return total;
  const sx = box.width / 100;
  const sy = box.height / 1500;
  const samples = 400;
  let len = 0;
  let prev = path.getPointAtLength(0);
  for (let i = 1; i <= samples; i++) {
    const pt = path.getPointAtLength((total * i) / samples);
    len += Math.hypot((pt.x - prev.x) * sx, (pt.y - prev.y) * sy);
    prev = pt;
  }
  return len;
}

/** Each step's stop -- on the curve, at its band's center -- and which side its caption
 * takes (alternating, starting on the right, so the curve leans left first). */
const STOPS: ReadonlyArray<{ left: string; top: string; side: "left" | "right" }> = [
  { left: "45%", top: "22.3%", side: "right" },
  { left: "55%", top: "36.2%", side: "left" },
  { left: "45%", top: "50%", side: "right" },
  { left: "55%", top: "63.8%", side: "left" },
  { left: "45%", top: "77.7%", side: "right" },
];

/**
 * The scroll story for "how it reads a page": five flat illustrations (`Step1Intro` ...
 * `Step5Graph`, one per step, stacked on a pinned stage) beside a curved path of five
 * numbered stops, its accent line filling in as the reader scrolls, with one pinned caption
 * cross-fading as each step becomes current. `.how-track` holds both columns; scroll
 * progress through it, smoothed by a spring, decides which step is showing and writes it
 * as `data-step`/`data-in` on `.how`, which `how.css` reads to crossfade the illustrations.
 *
 * Every step's copy is real, server-rendered DOM, always present (so a reader with no
 * JavaScript sees every one of them, stacked and readable); `how.css` only dims the
 * others once `main[data-motion]` confirms `Motion.tsx`'s enhancement is live -- the same
 * gate every other reveal on this page uses. Reduced motion (and, by `.how-track`'s own
 * CSS, a narrow viewport) skips the pin, the curve and the tall track outright and
 * renders `.how-static`: step one's illustration at rest, the five steps simply stacked.
 */
export default function HowMotion({ steps = [] }: { steps?: readonly HowStep[] }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
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

  // The illustrations are drawn at one natural size (36×24rem, see each Step*.tsx) and
  // scaled up to fill the stage they're centered in, to a cap -- `how.css` reads
  // `--how-zoom` off `.how`. Measured, not a container query: CSS can't divide two lengths.
  useEffect(() => {
    const panel = panelRef.current;
    const stage = stageRef.current;
    if (!panel || !stage) return;
    const fit = () => {
      const { width, height } = stage.getBoundingClientRect();
      const zoom = Math.min(width / 576, height / 384, STAGE_ZOOM_MAX);
      panel.style.setProperty("--how-zoom", zoom > 0 ? zoom.toFixed(3) : "1");
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(stage);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const path = fillRef.current;
    if (!path) return;
    const measure = () => fillLength.set(drawnLength(path));
    measure();
    // The drawn length changes with the column's size, not just once at mount.
    const ro = new ResizeObserver(measure);
    if (path.ownerSVGElement) ro.observe(path.ownerSVGElement);
    return () => ro.disconnect();
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
  // The fill reaches each stop exactly as that stop's step becomes current, and moves
  // continuously with scroll in between -- a smooth, ever-moving line that is never short
  // of the highlighted stop, rather than five flat plateaus with a jump at each. The line
  // starts at 01 and the stops are evenly spaced along it (the bends are symmetric), so
  // stop k sits at (k-1)/4 of its length; it is complete once 05 is current.
  const fillProgress = useTransform(spring, [0, 0.2, 0.4, 0.6, 0.8], [0, 0.25, 0.5, 0.75, 1]);
  const dashOffset = useTransform([fillProgress, fillLength], ([p, len]) => (len as number) - (len as number) * (p as number));

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
        <div className="how-stage">
          <div className="how-step" data-for="1" style={{ opacity: 1 }} aria-hidden>
            <Step1Intro reduced />
          </div>
        </div>
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
          <motion.div ref={stageRef} className="how-stage" style={{ scale: stageScale }}>
            {SCENES.map((Scene, k) => (
              <div key={k} className="how-step" data-for={k + 1} aria-hidden>
                <Scene active={step === k} />
              </div>
            ))}
          </motion.div>
        </div>
      </div>
      <div className="how-path">
        <svg className="how-curve" viewBox="0 0 100 1500" preserveAspectRatio="none" aria-hidden>
          <path className="how-track-line" d={CURVE_D} vectorEffect="non-scaling-stroke" />
          <motion.path
            ref={fillRef}
            className="how-fill-line"
            d={CURVE_D}
            vectorEffect="non-scaling-stroke"
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
        <div className="how-copy-pin">
          {(steps ?? []).map((s, k) => (
            <div
              key={s.title}
              role="button"
              tabIndex={k === step ? 0 : -1}
              className={`how-copy how-copy--${STOPS[k]?.side ?? "right"}${k === step ? " is-active" : ""}`}
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
    </div>
  );
}
