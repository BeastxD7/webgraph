"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";

import { Mark } from "@/components/site/Wordmark";

import { buildKeyframesCss, DISCOVER_TREE, layoutTree, type TimedNode } from "./discoverTree";
import "./intro-bar.css";

interface Edge { id: string; d: string }

/**
 * A focused experiment, on its own on purpose: the opening beat of
 * "how it reads a page" step 1 -- blank canvas, the brand mark, the mark dissolving into a
 * search bar that expands from the same center point, typing, "entering" -- and what happens
 * after: the page tree the crawl turns up, revealed strictly breadth-first (one whole depth
 * settles before the next starts, anywhere in the tree), connected by smooth curves measured
 * from the nodes' own real positions rather than flat CSS lines guessed at layout time.
 * Every animation's timing comes from one shared ms-based schedule in `discoverTree.ts`,
 * generated into real `@keyframes` and injected once below, so the intro and the tree reveal
 * share a single cycle. Plain HTML/CSS/SVG so the timing, easing and look can be iterated
 * on quickly; the landing page's copy of it is `components/landing/how/Step1Intro.tsx`.
 */
export default function IntroBarPlayground() {
  const layout = useMemo(() => layoutTree(DISCOVER_TREE), []);
  const css = useMemo(() => buildKeyframesCss(layout), [layout]);
  const dur = `${layout.cycleMs}ms`;
  const loop = (name: string): CSSProperties => ({ animationName: name, animationDuration: dur, animationIterationCount: "infinite" });

  const canvasRef = useRef<HTMLDivElement>(null);
  const rootPillRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef(new Map<string, HTMLDivElement>());
  const [edges, setEdges] = useState<Edge[]>([]);

  useLayoutEffect(() => {
    function measure() {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const base = canvas.getBoundingClientRect();
      const centerTopOf = (el: Element) => {
        const r = el.getBoundingClientRect();
        return { x: r.left + r.width / 2 - base.left, yTop: r.top - base.top, yBottom: r.bottom - base.top };
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
    <main className="min-h-dvh bg-ground">
      <style>{css}</style>
      <div className="border-b border-rule px-6 py-3">
        <strong className="font-mono text-caption uppercase tracking-wide text-muted">intro-bar</strong>
        <span className="ml-3 text-small text-muted">
          Blank → mark → mark dissolves into the bar → types → enters → the page tree unfolds
          breadth-first. Loops every {(layout.cycleMs / 1000).toFixed(1)}s.
        </span>
      </div>

      <div ref={canvasRef} className="relative flex flex-col items-center py-16">
        <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible">
          {edges.map((e) => (
            <path
              key={e.id}
              d={e.d}
              fill="none"
              strokeWidth={2}
              strokeLinecap="round"
              className="stroke-accent-ink/70"
              style={{ strokeDasharray: 1, animationName: `discover-edge-${e.id}`, animationDuration: dur, animationIterationCount: "infinite" }}
              pathLength={1}
            />
          ))}
        </svg>

        <div className="relative h-14 w-[36rem]">
          <div className="intro-logo absolute inset-0 flex origin-center items-center justify-center" style={loop("discover-logo")}>
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
              <span className="ml-0.5 inline-block h-5 w-0.5 animate-[intro-bar-blink_1s_step-end_infinite] bg-accent-ink align-[-0.24rem]" />
              <span className="ml-auto flex size-10 flex-none items-center justify-center rounded-full" style={loop("discover-enter-flash")}>
                <svg className="size-4 fill-none stroke-accent-ink stroke-[1.6]" viewBox="0 0 20 20" aria-hidden style={loop("discover-enter-arrow-flash")}>
                  <path d="M4 10 h10 M10 5 l5 5 l-5 5" />
                </svg>
              </span>
            </div>
          </div>

          {/* The root: appears where the bar was, once it's fully dissolved. */}
          <div className="absolute inset-0 flex items-center justify-center" style={loop("discover-root")}>
            <div
              ref={rootPillRef}
              className="relative rounded-full border border-rule-strong bg-surface px-6 py-2.5 font-mono text-body font-semibold text-ink"
              style={{ boxShadow: "0 4px 16px -4px rgb(32 33 36 / 0.18), 0 1px 3px 0 rgb(32 33 36 / 0.1)" }}
            >
              webgraph.com
            </div>
          </div>
        </div>

        <TreeLevel nodes={layout.root.children} dur={dur} nodeRefs={nodeRefs} />
      </div>
    </main>
  );
}

const DEPTH_STYLE = [
  "", // depth 0 handled separately (the root pill)
  "rounded-lg border border-rule-strong bg-surface px-4 py-2 font-mono text-small font-medium text-ink",
  "rounded-md border border-rule bg-surface px-3 py-1.5 font-mono text-caption text-muted",
] as const;

function TreeLevel({ nodes, dur, nodeRefs }: { nodes: readonly TimedNode[]; dur: string; nodeRefs: React.RefObject<Map<string, HTMLDivElement>> }) {
  if (nodes.length === 0) return null;
  const gapClass = nodes[0]!.depth === 1 ? "mt-16" : "mt-12";
  return (
    <div className={`flex items-start justify-center gap-8 ${gapClass}`}>
      {nodes.map((n) => (
        <div key={n.id} className="flex flex-col items-center">
          <div
            ref={(el) => {
              if (el) nodeRefs.current.set(n.id, el);
              else nodeRefs.current.delete(n.id);
            }}
            className={`relative whitespace-nowrap shadow-sm ${DEPTH_STYLE[n.depth] ?? DEPTH_STYLE[2]}`}
            style={{ animationName: `discover-node-${n.id}`, animationDuration: dur, animationIterationCount: "infinite" }}
          >
            <span
              aria-hidden
              className="pointer-events-none absolute inset-0 rounded-[inherit] border-2 border-accent"
              style={{ animationName: `discover-ping-${n.id}`, animationDuration: dur, animationIterationCount: "infinite" }}
            />
            {n.path}
          </div>
          {n.children.length > 0 && <TreeLevel nodes={n.children} dur={dur} nodeRefs={nodeRefs} />}
        </div>
      ))}
    </div>
  );
}
