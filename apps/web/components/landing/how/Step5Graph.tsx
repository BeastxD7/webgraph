"use client";

import { useMemo, useRef } from "react";
import type { CSSProperties } from "react";

import { BOX, buildGraphCss, edgePath, ENTITY, GRAPH_MS, LINKS, MENTIONS, nodeAt, PAGES, SECTIONS } from "./buildGraph";
import { useTriggeredLoop } from "./useTriggeredLoop";

/**
 * Step 5 ("build the graph"): the pages from the crawl settle as nodes with their
 * structure drawn between them; the links the pages carry to each other draw as a second
 * kind of edge, across the tree; each page's sections hang off it; and an entity the
 * pages name -- `WebGraph Inc.`, with its `schema.org/Organization` identity -- appears
 * with an edge from every page and section that mentions it. Nothing inferred: the site
 * already is a graph. Same flat idiom and single generated clock as the other steps
 * (`buildGraph.ts`); HTML nodes over an SVG of edges sharing one 576×384 box.
 */
export default function Step5Graph({ active = true }: { active?: boolean }) {
  const css = useMemo(() => buildGraphCss(), []);
  const canvasRef = useRef<HTMLDivElement>(null);
  const { loop } = useTriggeredLoop(canvasRef, GRAPH_MS.cycle, { active });
  const at = (x: number, y: number): CSSProperties => ({ left: `${(x / BOX.w) * 100}%`, top: `${(y / BOX.h) * 100}%` });
  const edge = (name: string, d: string, cls: string, width = 1.5) => (
    <path key={name} d={d} fill="none" strokeWidth={width} strokeLinecap="round" className={cls} pathLength={1} style={{ strokeDasharray: 1, ...loop(name) }} />
  );

  return (
    <div ref={canvasRef} className="step5-graph relative w-[36rem] shrink-0" style={{ height: "24rem" }}>
      <style>{css}</style>

      <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" viewBox={`0 0 ${BOX.w} ${BOX.h}`} preserveAspectRatio="none" aria-hidden>
        {/* Structure: parent to child. */}
        {[...PAGES, ...SECTIONS].filter((n) => n.parent).map((n) => edge(`graph-tree-${n.id}`, edgePath(nodeAt(n.parent!), n), "stroke-rule-strong"))}
        {/* Links the pages carry to each other. */}
        {LINKS.map((l) => edge(`graph-link-${l.from}-${l.to}`, edgePath(nodeAt(l.from), nodeAt(l.to)), "stroke-accent", 1.75))}
        {/* Mentions of the entity. */}
        {MENTIONS.map((id) => edge(`graph-mention-${id}`, edgePath(nodeAt(id), nodeAt(ENTITY.id)), "stroke-good", 1.5))}
      </svg>

      {PAGES.map((p) => (
        <div key={p.id} className="absolute -translate-x-1/2 -translate-y-1/2" style={{ ...at(p.x, p.y), ...loop(`graph-node-${p.id}`) }}>
          <div className={`whitespace-nowrap rounded-lg border border-rule-strong bg-surface px-3 py-1.5 font-mono font-medium text-ink shadow-sm ${p.parent ? "text-small" : "rounded-full px-4 py-2 text-body font-semibold"}`}>{p.label}</div>
        </div>
      ))}
      {SECTIONS.map((s) => (
        <div key={s.id} className="absolute -translate-x-1/2 -translate-y-1/2" style={{ ...at(s.x, s.y), ...loop(`graph-node-${s.id}`) }}>
          <div className="whitespace-nowrap rounded-md border border-rule bg-surface px-2 py-1 font-mono text-caption text-muted shadow-sm"><span className="text-faint">#</span> {s.label}</div>
        </div>
      ))}
      <div className="absolute -translate-x-1/2 -translate-y-1/2" style={{ ...at(ENTITY.x, ENTITY.y), ...loop(`graph-node-${ENTITY.id}`) }}>
        {/* The pill is the node (edges end at its center); the badge hangs below it. */}
        <div className="relative">
          <span className="pointer-events-none absolute -inset-1.5 rounded-full border-2 border-good" style={loop("graph-ping")} aria-hidden />
          <div className="whitespace-nowrap rounded-full border border-good bg-good-soft px-3.5 py-1.5 font-mono text-small font-semibold text-good shadow-sm">{ENTITY.label}</div>
          <span className="absolute left-1/2 top-full mt-1 -translate-x-1/2 whitespace-nowrap rounded bg-surface px-1.5 py-0.5 font-mono text-[9px] text-muted shadow-sm ring-1 ring-rule" style={loop("graph-badge")}>{ENTITY.type}</span>
        </div>
      </div>

      <div className="absolute bottom-0 left-1/2 flex items-center gap-3 whitespace-nowrap rounded-full border border-rule-strong bg-surface px-3 py-1 font-mono text-[10px] text-muted shadow-sm" style={loop("graph-caption")}>
        <span><span className="text-ink">5</span> pages</span>
        <span><span className="text-ink">4</span> sections</span>
        <span><span className="text-ink">1</span> entity</span>
        <span className="text-faint">·</span>
        <span className="text-accent-ink">nothing inferred</span>
      </div>
    </div>
  );
}
