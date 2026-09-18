"use client";

import { useMemo, useRef } from "react";
import type { CSSProperties } from "react";

import { buildFetchCss, PAINT_BLOCKS, PLAIN_LINES } from "./fetchTwice";
import { FETCH_MS } from "./fetchTwice";
import { useTriggeredLoop } from "./useTriggeredLoop";

/**
 * Step 2 ("fetch twice"): one page from the crawl -- `/products` -- fetched two ways at
 * once. Left, the plain request: raw server HTML streaming in line by line, 2,108 words.
 * Right, a real browser window: a progress bar, the page painting block by block, then
 * hydration throwing away the server's pricing table and a script inserting a reviews
 * block no plain fetch would ever see -- 2,195 words, a different 2,195. Then the two
 * slide together into the union the engine keeps, with each side's exclusive content
 * tinted by where it came from. Flat "browser chrome" like step 1, on the same kind of
 * single generated clock (`fetchTwice.ts`), triggered and looped by `useTriggeredLoop`.
 */
export default function Step2Fetch({ active = true }: { active?: boolean }) {
  const css = useMemo(() => buildFetchCss(), []);
  const canvasRef = useRef<HTMLDivElement>(null);
  const { loop } = useTriggeredLoop(canvasRef, FETCH_MS.cycle, { active });

  return (
    <div ref={canvasRef} className="step2-fetch relative w-[36rem] shrink-0" style={{ height: "24rem" }}>
      <style>{css}</style>

      {/* The two lanes, chip to card, in the stage's own 576×384 box (its size in px at full width,
          so a 1.5 stroke is 1.5px); `pathLength={1}` drives the draw-on, which a
          `non-scaling-stroke` would defeat -- under it the dash pattern is screen pixels. */}
      <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" viewBox="0 0 576 384" preserveAspectRatio="none" aria-hidden>
        {["M288,34 C288,50 112,42 112,56", "M288,34 C288,50 440,42 440,56"].map((d) => (
          <path key={d} d={d} fill="none" strokeWidth={1.5} strokeLinecap="round" className="stroke-accent-ink/60" pathLength={1} style={{ strokeDasharray: 1, ...loop("fetch-lane") }} />
        ))}
      </svg>

      {/* The page picked from the crawl. */}
      <div className="absolute left-1/2 top-0 -translate-x-1/2" style={loop("fetch-chip")}>
        <div className="rounded-lg border border-rule-strong bg-surface px-4 py-1.5 font-mono text-small font-medium text-ink shadow-sm">webgraph.com/products</div>
      </div>

      <div className="absolute left-0 top-[3.85rem] w-56 text-center font-mono text-caption text-muted" style={loop("fetch-label")}>
        GET /products <span className="text-faint">· text/html</span>
      </div>
      <div className="absolute right-0 top-[3.85rem] w-[17rem] text-center font-mono text-caption text-muted" style={loop("fetch-label")}>
        Chromium <span className="text-faint">· 1440×900</span>
      </div>

      {/* Left: the plain response. */}
      <div
        className="absolute left-0 top-[5.75rem] w-56 rounded-xl border border-rule-strong bg-surface shadow-sm"
        style={{ "--fetch-plain-slide": "11rem", ...loop("fetch-plain") } as CSSProperties}
      >
        <div className="flex items-center gap-2 border-b border-rule px-3 py-1.5 font-mono text-caption">
          <span className="rounded bg-good-soft px-1.5 py-0.5 text-good">200</span>
          <span className="text-muted">text/html</span>
          <span className="ml-auto text-faint">41 kB</span>
        </div>
        <div className="space-y-1 px-3 py-2 font-mono text-[10px] leading-4 text-muted">
          {PLAIN_LINES.map((l, i) => (
            <div key={l.text} className={`whitespace-pre ${l.kept ? "text-accent-ink" : ""}`} style={loop(`fetch-plain-line-${i}`)}>{l.text}</div>
          ))}
        </div>
        <Counter words="2,108" className="absolute -bottom-3 right-3" style={loop("fetch-counter")} />
      </div>

      {/* Right: the browser. */}
      <div
        className="absolute right-0 top-[5.75rem] w-[17rem] rounded-xl border border-rule-strong bg-surface shadow-sm"
        style={{ "--fetch-window-slide": "-9.5rem", ...loop("fetch-window") } as CSSProperties}
      >
        <div className="relative flex items-center gap-2 rounded-t-xl border-b border-rule bg-sunk/60 px-3 py-1.5">
          <span className="flex gap-1" aria-hidden>
            <span className="size-2 rounded-full bg-rule-strong" /><span className="size-2 rounded-full bg-rule-strong" /><span className="size-2 rounded-full bg-rule-strong" />
          </span>
          <span className="flex-1 rounded-md bg-surface px-2 py-0.5 font-mono text-[10px] text-muted">webgraph.com/products</span>
          <span className="absolute inset-x-0 bottom-0 h-0.5 origin-left bg-accent" style={loop("fetch-progress")} />
        </div>
        <div className="relative space-y-1.5 p-3">
          {PAINT_BLOCKS.map((b) => (
            <PaintBlock key={b.id} id={b.id} lost={b.lost} inserted={b.inserted} style={loop(`fetch-paint-${b.id}`)} />
          ))}
          <span className="absolute right-2 top-[4.35rem] rounded bg-bad-soft px-1.5 py-0.5 font-mono text-[10px] text-bad" style={loop("fetch-lost-label")}>− lost on hydration</span>
          <span className="absolute bottom-2 right-2 rounded bg-good-soft px-1.5 py-0.5 font-mono text-[10px] text-good" style={loop("fetch-insert-label")}>+ inserted by script</span>
        </div>
        <Counter words="2,195" className="absolute -bottom-3 right-3" style={loop("fetch-counter")} />
      </div>

      {/* The union: what the engine keeps. */}
      <div className="absolute left-1/2 top-[5.75rem] w-64 -translate-x-1/2 rounded-xl border border-rule-strong bg-surface shadow-md" style={loop("fetch-union")}>
        <div className="flex items-center gap-2 border-b border-rule px-3 py-1.5 font-mono text-caption">
          <span className="text-ink">union</span>
          <span className="text-faint">· one page</span>
          <span className="relative ml-auto inline-flex items-center rounded-full bg-accent px-2.5 py-0.5 text-[10px] font-semibold text-surface" style={loop("fetch-stamp")}>
            <span className="pointer-events-none absolute inset-0 rounded-full border-2 border-accent" style={loop("fetch-ping")} aria-hidden />
            2,198 words
          </span>
        </div>
        <div className="space-y-1 px-3 py-2 font-mono text-[10px] leading-4 text-muted">
          {PLAIN_LINES.slice(0, 5).map((l) => (
            <div key={l.text} className={`whitespace-pre ${l.kept ? "rounded bg-accent-soft px-1 text-accent-ink" : ""}`}>{l.text}</div>
          ))}
          <div className="whitespace-pre rounded bg-good-soft px-1 text-good">{'<section id="reviews">…</section>'}</div>
          {PLAIN_LINES.slice(5, 6).map((l) => <div key={l.text} className="whitespace-pre">{l.text}</div>)}
        </div>
        <div className="flex items-center gap-3 border-t border-rule px-3 py-1.5 font-mono text-[10px]">
          <span className="text-accent-ink">■ plain fetch only</span>
          <span className="text-good">■ render only</span>
        </div>
      </div>
    </div>
  );
}

function Counter({ words, className, style }: { words: string; className: string; style: CSSProperties }) {
  return (
    <span className={`${className} rounded-full border border-rule-strong bg-surface px-2 py-0.5 font-mono text-[10px] font-semibold text-ink shadow-sm`} style={style}>
      {words} words
    </span>
  );
}

/** One painted region of the rendered page, as the browser would lay it out. */
function PaintBlock({ id, lost, inserted, style }: { id: string; lost?: boolean; inserted?: boolean; style: CSSProperties }) {
  const bar = (w: string, extra = "") => <span className={`block h-1 rounded-full bg-rule-strong ${extra}`} style={{ width: w }} />;
  const tint = lost ? "border-bad/50" : inserted ? "border-good bg-good-soft" : "border-rule";
  return (
    <div className={`rounded-md border ${tint} px-2 py-1.5 ${inserted ? "overflow-hidden" : ""}`} style={style} data-block={id}>
      {id === "header" && <div className="flex items-center gap-2"><span className="h-1.5 w-8 rounded-full bg-ink" />{bar("1.2rem")}{bar("1rem")}{bar("1.4rem")}</div>}
      {id === "hero" && <div className="space-y-1"><span className="block h-1.5 w-20 rounded-full bg-ink" />{bar("85%")}{bar("60%")}</div>}
      {id === "pricing" && <div className="grid grid-cols-3 gap-1">{[0, 1, 2, 3, 4, 5].map((k) => <span key={k} className="h-2 rounded-sm bg-accent-soft" />)}</div>}
      {id === "grid" && <div className="grid grid-cols-3 gap-1.5">{[0, 1, 2].map((k) => <span key={k} className="h-5 rounded-sm bg-sunk" />)}</div>}
      {id === "reviews" && <div className="space-y-1">{bar("70%", "bg-good/60")}{bar("50%", "bg-good/60")}</div>}
    </div>
  );
}
