"use client";

import { useMemo, useRef } from "react";
import type { CSSProperties, ReactNode } from "react";

import { BLOCKS, buildOrderCss, CUTS, DOC_BODY, DOC_HEAD, ORDER_MS } from "./readingOrder";
import { useTriggeredLoop } from "./useTriggeredLoop";

/**
 * Step 4 ("reading order, then Markdown"): the page as the browser laid it out on the
 * left -- header, sidebar, main column, footer, every box measured -- with the recursive
 * XY-cut drawn over it live: whole-page cuts first, then down the middle band, then within
 * the main column, so columns stay columns. The numbers land in the order the cuts
 * produce (the sidebar, first in the DOM, reads fifth). On the right the Markdown writes
 * itself in exactly that order, each line's margin badge lighting up with its block, under
 * a header stating how the page was fetched, that its order was measured, and what was
 * refused. Same flat idiom and single generated clock as the other steps (`readingOrder.ts`).
 */
export default function Step4Order({ active = true }: { active?: boolean }) {
  const css = useMemo(() => buildOrderCss(), []);
  const canvasRef = useRef<HTMLDivElement>(null);
  const { loop } = useTriggeredLoop(canvasRef, ORDER_MS.cycle, { active });
  const bar = (w: string, extra = "bg-rule-strong") => <span className={`block h-1 rounded-full ${extra}`} style={{ width: w }} />;

  return (
    <div ref={canvasRef} className="step4-order relative w-[36rem] shrink-0" style={{ height: "24rem" }}>
      <style>{css}</style>

      {/* The page, as laid out: 17rem × 20rem, its boxes on a 100×100 grid the cuts share. */}
      <div className="absolute left-0 top-2 h-[20rem] w-[16.5rem] rounded-xl border border-rule-strong bg-surface p-3 shadow-sm" style={loop("order-page")}>
        <div className="relative grid h-full grid-cols-[30%_1fr] grid-rows-[18%_1fr_16%] gap-[3%]">
          <Block id="header" loop={loop} className="col-span-2 flex items-center gap-2">
            <span className="h-1.5 w-8 rounded-full bg-ink" />{bar("1.2rem")}{bar("1rem")}{bar("1.4rem")}
          </Block>
          <Block id="sidebar" loop={loop} className="space-y-1.5">
            {bar("80%")}{bar("60%")}{bar("70%")}{bar("50%")}{bar("65%")}
          </Block>
          <div className="grid grid-rows-[1fr_1fr_1fr_1.3fr] gap-[4%]">
            <Block id="title" loop={loop} className="flex items-center"><span className="block h-2 w-24 rounded-full bg-ink" /></Block>
            <Block id="para1" loop={loop} className="space-y-1">{bar("95%")}{bar("80%")}</Block>
            <Block id="para2" loop={loop} className="space-y-1">{bar("90%")}{bar("70%")}</Block>
            <Block id="figure" loop={loop} className="flex items-center justify-center bg-sunk/40"><span className="h-full w-3/4 rounded-sm border border-dashed border-rule-strong" /></Block>
          </div>
          <Block id="footer" loop={loop} className="col-span-2 flex items-center gap-2">{bar("2rem")}{bar("1.5rem")}</Block>
          {/* The cuts, drawn over the grid. */}
          <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
            {CUTS.map((c) => (
              <path key={c.id} d={c.d} fill="none" strokeWidth={0.6} strokeLinecap="round" className="stroke-accent" pathLength={1} style={{ strokeDasharray: 1, ...loop(`order-cut-${c.id}`) }} />
            ))}
          </svg>
        </div>
        <span className="absolute -bottom-3 left-3 rounded-full border border-rule-strong bg-surface px-2 py-0.5 font-mono text-[10px] font-semibold text-ink shadow-sm">7 boxes · measured</span>
      </div>

      {/* The Markdown. */}
      <div className="absolute right-0 top-2 w-[18rem] rounded-xl border border-rule-strong bg-surface shadow-sm" style={loop("order-doc")}>
        <div className="flex items-center gap-2 border-b border-rule px-3 py-1.5 font-mono text-caption">
          <span className="text-ink">getting-started.md</span>
        </div>
        <div className="border-b border-rule bg-sunk/40 px-3 py-2 font-mono text-[10px] leading-4 text-muted">
          <div className="text-faint">---</div>
          {DOC_HEAD.map((l, i) => <div key={l} className="whitespace-pre" style={loop(`order-head-${i}`)}>{l}</div>)}
          <div className="text-faint">---</div>
        </div>
        <div className="space-y-1.5 px-3 py-2.5 font-mono text-[10px] leading-4">
          {DOC_BODY.map((l, i) => (
            <div key={l.text} className="flex items-start gap-2">
              <span className="mt-px flex size-3.5 flex-none items-center justify-center rounded-full bg-accent text-[8px] font-bold text-surface" style={loop(`order-margin-${i}`)}>{l.order}</span>
              <span className={`whitespace-pre ${l.text.startsWith("#") ? "font-semibold text-ink" : l.text.startsWith(">") ? "text-faint" : "text-muted"}`} style={loop(`order-line-${i}`)}>{l.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const ORDER_OF = Object.fromEntries(BLOCKS.map((b) => [b.id, b.order])) as Record<(typeof BLOCKS)[number]["id"], number>;

/** One measured box: painted in with the page, then lit and numbered when its turn in the
 * reading order comes. The lit outline is its own layer so the paint-in and the light-up
 * can run as two animations on one box. */
function Block({ id, loop, className, children }: {
  id: (typeof BLOCKS)[number]["id"];
  loop: (name: string) => CSSProperties;
  className: string;
  children: ReactNode;
}) {
  return (
    <div className={`relative rounded-md border border-rule p-1.5 ${className}`} style={loop(`order-paint-${id}`)}>
      <div className="pointer-events-none absolute -inset-px rounded-md border" style={{ borderColor: "var(--rule)", ...loop(`order-lit-${id}`) }} aria-hidden />
      <div className="relative">{children}</div>
      <span className="absolute -left-2 -top-2 flex size-4 items-center justify-center rounded-full bg-accent font-mono text-[9px] font-bold text-surface shadow-sm" style={loop(`order-num-${id}`)}>{ORDER_OF[id]}</span>
    </div>
  );
}
