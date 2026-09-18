"use client";

import { useEffect, useRef, useState } from "react";

import Scene from "@/components/landing/how/Scene";
import "@/components/landing/how/how.css";

const STEPS = [1, 2, 3, 4, 5] as const;
const WIDTHS = [
  { label: "Phone · 390", value: 390 },
  { label: "Tablet · 900", value: 900 },
  { label: "Laptop · 1440", value: 1440 },
  { label: "Wide · 1920", value: 1920 },
  { label: "Full", value: null },
] as const;

/**
 * A direct-control preview of `how/Scene.tsx` at its real production sizing (the same
 * `.how-track`/`.how-illustration-col`/`.how-stage-pin` classes from `how.css`), with the
 * states `HowMotion.tsx` normally derives from scroll position exposed as buttons instead --
 * so a step, or the "not yet in view" state, or a simulated viewport width, can be checked
 * instantly instead of scrolling the real page into position each time. `data-motion` is
 * stamped on `<main>` by hand here (`Motion.tsx` normally does this on mount) so the same
 * `main[data-motion]` gated rules in how.css apply.
 */
export default function HowScenePlayground() {
  const [step, setStep] = useState<number>(1);
  const [dataIn, setDataIn] = useState(true);
  const [width, setWidth] = useState<number | null>(1440);
  const [showBounds, setShowBounds] = useState(true);
  const [freeze, setFreeze] = useState(false);

  const mainRef = useRef<HTMLElement>(null);
  const illColRef = useRef<HTMLDivElement>(null);
  const stagePinRef = useRef<HTMLDivElement>(null);
  const sceneWrapRef = useRef<HTMLDivElement>(null);
  const [metrics, setMetrics] = useState<{ leftGap: number; rightGap: number; w: number; h: number } | null>(null);

  useEffect(() => {
    mainRef.current?.setAttribute("data-motion", "");
  }, []);

  useEffect(() => {
    function measure() {
      const scene = sceneWrapRef.current?.querySelector(".how-scene");
      const stagePin = stagePinRef.current;
      if (!scene || !stagePin) return;
      const stageRect = stagePin.getBoundingClientRect();
      const visible = [...scene.querySelectorAll(`.s${step}, .core`)].filter((el) => {
        const cs = getComputedStyle(el);
        return cs.opacity !== "0";
      });
      let minX = Infinity;
      let maxX = -Infinity;
      for (const el of visible) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        minX = Math.min(minX, r.left);
        maxX = Math.max(maxX, r.right);
      }
      if (minX === Infinity) { setMetrics(null); return; }
      setMetrics({
        leftGap: Math.round(minX - stageRect.left),
        rightGap: Math.round(stageRect.right - maxX),
        w: Math.round(stageRect.width),
        h: Math.round(stageRect.height),
      });
    }
    // Polled, not one-shot: step 1's search bar and tree-reveal are themselves continuously
    // animating (the typing loop), so which elements count as "visible" keeps changing even
    // with no control touched.
    const id = setInterval(measure, 300);
    measure();
    return () => clearInterval(id);
  }, [step, width, dataIn]);

  return (
    <main ref={mainRef} className="min-h-dvh bg-ground">
      <div className="sticky top-0 z-20 flex flex-wrap items-center gap-4 border-b border-rule bg-surface px-6 py-3">
        <strong className="font-mono text-caption uppercase tracking-wide text-muted">how-scene</strong>

        <div className="flex items-center gap-1">
          {STEPS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStep(s)}
              className={`rounded-md border px-2.5 py-1 text-small font-medium ${
                step === s ? "border-accent bg-accent text-surface" : "border-rule text-ink"
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-1.5 text-small text-ink">
          <input type="checkbox" checked={dataIn} onChange={(e) => setDataIn(e.target.checked)} />
          in view
        </label>
        <label className="flex items-center gap-1.5 text-small text-ink">
          <input type="checkbox" checked={showBounds} onChange={(e) => setShowBounds(e.target.checked)} />
          show bounds
        </label>
        <label className="flex items-center gap-1.5 text-small text-ink">
          <input type="checkbox" checked={freeze} onChange={(e) => setFreeze(e.target.checked)} />
          freeze, tree shown
        </label>

        <div className="flex items-center gap-1">
          {WIDTHS.map((w) => (
            <button
              key={w.label}
              type="button"
              onClick={() => setWidth(w.value)}
              className={`rounded-md border px-2.5 py-1 text-small font-medium ${
                width === w.value ? "border-accent bg-accent text-surface" : "border-rule text-ink"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>

        {metrics && (
          <span className="ml-auto font-mono text-caption text-muted">
            box {metrics.w}×{metrics.h} · left gap {metrics.leftGap}px · right gap {metrics.rightGap}px
            {Math.abs(metrics.leftGap - metrics.rightGap) > 8 && (
              <span className="ml-2 rounded bg-bad-soft px-1.5 py-0.5 text-bad">off-center</span>
            )}
          </span>
        )}
      </div>

      {freeze && (
        // Step 1's search bar and tree-reveal are on their own always-running loops, which
        // makes them hard to hold still for inspection -- this pauses every animation inside
        // the scene at whatever frame it's on, and forces the tree fully visible regardless
        // of where its own cycle happened to be paused.
        <style>{`
          .how-stage .how-scene * { animation-play-state: paused !important; }
          .how-stage .how-scene .tree-reveal-wave1,
          .how-stage .how-scene .tree-reveal-wave2 { opacity: 1 !important; transform: none !important; }
        `}</style>
      )}
      <div className="flex justify-center py-10">
        <div style={{ width: width ?? "100%", maxWidth: "100%" }}>
          <div
            className="how-track"
            style={{ display: "flex", minHeight: 0 }}
          >
            <div
              ref={illColRef}
              className="how-illustration-col"
              style={{ minHeight: 0, outline: showBounds ? "1px dashed #e8544a" : "none" }}
            >
              <div
                ref={stagePinRef}
                className="how how-stage-pin"
                data-step={step}
                data-in={dataIn ? "" : undefined}
                style={{ position: "relative", outline: showBounds ? "1px dashed #4a7ce8" : "none" }}
              >
                <div ref={sceneWrapRef} className="how-stage" style={{ outline: showBounds ? "1px dashed #3fae5c" : "none" }}>
                  <Scene />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
