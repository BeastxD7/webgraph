"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";

import { Mark } from "@/components/site/Wordmark";

import { buildKeyframesCss, DISCOVER_TREE, layoutTree, TEMPO, type TimedNode } from "./discoverTree";
import "./step1-intro.css";
import { useTriggeredLoop } from "./useTriggeredLoop";

interface Edge { id: string; d: string }

/**
 * Step 1 ("discover the pages"): a blank canvas, the brand mark, the mark dissolving into a
 * search bar that expands from the same center point, typing "webgraph.com," "entering" --
 * and then the page tree the crawl turns up, revealed strictly breadth-first (one whole
 * depth settles before the next starts, anywhere in the tree), connected by smooth curves
 * measured from the nodes' own real positions. Plain HTML/CSS/SVG, the first of the five
 * flat illustrations `HowMotion` stacks on the stage (`how.css`'s `.how-step`, shown while
 * `data-step="1"`), and the idiom the other four follow.
 *
 * Every animation's timing comes from one shared ms-based schedule in `discoverTree.ts`,
 * generated into real `@keyframes` and injected once below, so the intro and the tree
 * reveal share a single cycle and can't drift apart the way two independently `infinite`
 * CSS animations eventually would.
 *
 * `reduced`: under `prefers-reduced-motion`, `HowMotion.tsx` renders this with `reduced`
 * instead of animating it -- no logo, no typing, the bar's already-typed and the whole tree
 * already standing, all in one readable resting frame.
 *
 * The loop is *triggered*, not mount-timed (`useTriggeredLoop`): it starts from its first
 * frame the moment its step is current (`active`) and the overlay is in view, and cycles
 * for as long as that holds -- build, hold, dissolve, build again.
 */
export default function Step1Intro({ reduced = false, active = true }: { reduced?: boolean; active?: boolean }) {
  const layout = useMemo(() => layoutTree(DISCOVER_TREE), []);
  const css = useMemo(() => buildKeyframesCss(layout), [layout]);
  const canvasRef = useRef<HTMLDivElement>(null);
  const { loop } = useTriggeredLoop(canvasRef, layout.cycleMs * TEMPO, { reduced, active });
  const rootPillRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef(new Map<string, HTMLDivElement>());
  const [edges, setEdges] = useState<Edge[]>([]);

  useLayoutEffect(() => {
    function measure() {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const base = canvas.getBoundingClientRect();
      // Rects are in screen px; the SVG draws in the canvas's own (layout) px, and an ancestor
      // may be scaling us (`--how-zoom`, the stage's capstone scale) -- divide that back out.
      const k = canvas.offsetWidth ? base.width / canvas.offsetWidth : 1;
      const centerTopOf = (el: Element) => {
        const r = el.getBoundingClientRect();
        return { x: (r.left + r.width / 2 - base.left) / k, yTop: (r.top - base.top) / k, yBottom: (r.bottom - base.top) / k };
      };
      const next: Edge[] = [];
      const walk = (node: TimedNode, parentEl: HTMLDivElement | null) => {
        const el = node.depth === 0 ? rootPillRef.current : nodeRefs.current.get(node.id) ?? null;
        if (el && parentEl) {
          const p1 = centerTopOf(parentEl);
          const p2 = centerTopOf(el);
          const midY = (p1.yBottom + p2.yTop) / 2;
          const d = `M${p1.x},${p1.yBottom} C${p1.x},${midY} ${p2.x},${midY} ${p2.x},${p2.yTop}`;
          next.push({ id: node.id, d });
        }
        for (const child of node.children) walk(child, el ?? parentEl);
      };
      walk(layout.root, null);
      setEdges(next);
    }
    measure();
    const ro = new ResizeObserver(measure);
    if (canvasRef.current) ro.observe(canvasRef.current);
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  }, [layout]);

  return (
    <div ref={canvasRef} className="relative flex w-full flex-col items-center justify-center">
      {!reduced && <style>{css}</style>}
      <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible">
        {edges.map((e) => (
          <path
            key={e.id}
            d={e.d}
            fill="none"
            strokeWidth={2}
            strokeLinecap="round"
            className="stroke-accent-ink/70"
            style={{ strokeDasharray: 1, ...loop(`discover-edge-${e.id}`) }}
            pathLength={1}
          />
        ))}
      </svg>

      <div className="relative h-14 w-[min(36rem,90%)]">
        {!reduced && (
          <>
            <div className="step1-intro-logo absolute inset-0 flex origin-center items-center justify-center" style={loop("discover-logo")}>
              <Mark />
            </div>
            <div className="absolute inset-0 flex items-center">
              <div
                className="absolute inset-0 origin-center rounded-full bg-surface"
                style={{ ...loop("discover-bar-shape"), boxShadow: "0 1px 6px 0 rgb(32 33 36 / 0.16), 0 1px 2px 0 rgb(32 33 36 / 0.1)" }}
              />
              <div className="relative flex w-full items-center gap-3.5 px-7" style={loop("discover-bar-content")}>
                <svg className="size-5 flex-none fill-none stroke-muted stroke-[1.6]" viewBox="0 0 20 20" aria-hidden>
                  <circle cx="9" cy="9" r="6" />
                  <line x1="13.2" y1="13.2" x2="17" y2="17" />
                </svg>
                <span
                  className="inline-block w-0 overflow-hidden whitespace-nowrap align-bottom font-mono text-lg font-medium text-ink"
                  style={{ ...loop("discover-type-width"), animationTimingFunction: "steps(12, end)" }}
                >
                  webgraph.com
                </span>
                <span className="ml-0.5 inline-block h-5 w-0.5 animate-[step1-intro-blink_1s_step-end_infinite] bg-accent-ink align-[-0.24rem]" />
                <span className="ml-auto flex size-10 flex-none items-center justify-center rounded-full" style={loop("discover-enter-flash")}>
                  <svg className="size-4 fill-none stroke-accent-ink stroke-[1.6]" viewBox="0 0 20 20" aria-hidden style={loop("discover-enter-arrow-flash")}>
                    <path d="M4 10 h10 M10 5 l5 5 l-5 5" />
                  </svg>
                </span>
              </div>
            </div>
          </>
        )}

        {/* The root: appears where the bar was, once it's fully dissolved (or, under reduced
            motion, is simply the resting state -- there's no bar to dissolve from). */}
        <div className={reduced ? "flex h-full items-center justify-center" : "absolute inset-0 flex items-center justify-center"} style={loop("discover-root")}>
          <div
            ref={rootPillRef}
            className="relative rounded-full border border-rule-strong bg-surface px-6 py-2.5 font-mono text-body font-semibold text-ink"
            style={{ boxShadow: "0 4px 16px -4px rgb(32 33 36 / 0.18), 0 1px 3px 0 rgb(32 33 36 / 0.1)" }}
          >
            webgraph.com
          </div>
        </div>
      </div>

      <TreeLevel nodes={layout.root.children} loop={loop} nodeRefs={nodeRefs} reduced={reduced} />
    </div>
  );
}

const DEPTH_STYLE = [
  "", // depth 0 handled separately (the root pill)
  "rounded-lg border border-rule-strong bg-surface px-4 py-2 font-mono text-small font-medium text-ink",
  "rounded-md border border-rule bg-surface px-3 py-1.5 font-mono text-caption text-muted",
] as const;

function TreeLevel({ nodes, loop, nodeRefs, reduced }: {
  nodes: readonly TimedNode[];
  loop: (name: string) => CSSProperties;
  nodeRefs: React.RefObject<Map<string, HTMLDivElement>>;
  reduced: boolean;
}) {
  if (nodes.length === 0) return null;
  const gapClass = nodes[0]!.depth === 1 ? "mt-16" : "mt-12";
  return (
    <div className={`flex flex-wrap items-start justify-center gap-x-8 gap-y-6 ${gapClass}`}>
      {nodes.map((n) => (
        <div key={n.id} className="flex flex-col items-center">
          <div
            ref={(el) => {
              if (el) nodeRefs.current.set(n.id, el);
              else nodeRefs.current.delete(n.id);
            }}
            className={`relative whitespace-nowrap shadow-sm ${DEPTH_STYLE[n.depth] ?? DEPTH_STYLE[2]}`}
            style={loop(`discover-node-${n.id}`)}
          >
            {!reduced && (
              <span
                aria-hidden
                className="pointer-events-none absolute inset-0 rounded-[inherit] border-2 border-accent"
                style={loop(`discover-ping-${n.id}`)}
              />
            )}
            {n.path}
          </div>
          {n.children.length > 0 && <TreeLevel nodes={n.children} loop={loop} nodeRefs={nodeRefs} reduced={reduced} />}
        </div>
      ))}
    </div>
  );
}
