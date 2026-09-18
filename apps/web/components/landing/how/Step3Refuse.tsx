"use client";

import { useMemo, useRef } from "react";

import { buildRefuseCss, HIDDEN, REFUSE_MS, WALLS } from "./refuseWalls";
import { useTriggeredLoop } from "./useTriggeredLoop";

/**
 * Step 3 ("refuse the walls, drop the hidden"): one browser window and the engine's log
 * beside it. Act one, the walls: the fetch of `/docs` lands on a login redirect, then a
 * 503, then a bot challenge, and each gets a REFUSED stamp and a log line in the engine's
 * own words -- none of them is ever passed off as the page. Act two, the page loads for
 * real, and what the browser hides is surfaced and then dropped one by one: a cookie
 * banner sliding up, sixty links parked beyond the window's right edge, a `display:none`
 * block holding 2,100 words. What's left is the page a reader saw, with its word count.
 * Same flat idiom and single generated clock as steps 1 and 2 (`refuseWalls.ts`).
 */
export default function Step3Refuse({ active = true }: { active?: boolean }) {
  const css = useMemo(() => buildRefuseCss(), []);
  const canvasRef = useRef<HTMLDivElement>(null);
  const { loop } = useTriggeredLoop(canvasRef, REFUSE_MS.cycle, { active });
  const bar = (w: string, extra = "bg-rule-strong") => <span className={`block h-1 rounded-full ${extra}`} style={{ width: w }} />;

  return (
    <div ref={canvasRef} className="step3-refuse relative w-[36rem] shrink-0" style={{ height: "24rem" }}>
      <style>{css}</style>

      {/* The window. `overflow: visible` so the parked links can sit outside it. */}
      <div className="absolute left-0 top-4 w-[19.5rem] rounded-xl border border-rule-strong bg-surface shadow-sm" style={loop("refuse-window")}>
        <div className="relative flex items-center gap-2 rounded-t-xl border-b border-rule bg-sunk/60 px-3 py-1.5">
          <span className="flex gap-1" aria-hidden>
            <span className="size-2 rounded-full bg-rule-strong" /><span className="size-2 rounded-full bg-rule-strong" /><span className="size-2 rounded-full bg-rule-strong" />
          </span>
          <span className="relative h-5 flex-1 rounded-md bg-surface font-mono text-[10px] text-muted">
            {WALLS.map((w) => (
              <span key={w.id} className="absolute inset-0 truncate px-2 leading-5" style={loop(`refuse-wall-${w.id}`)}>webgraph.com{w.url}</span>
            ))}
            <span className="absolute inset-0 truncate px-2 leading-5" style={loop("refuse-page")}>webgraph.com/docs</span>
          </span>
        </div>

        <div className="relative h-[13.5rem] overflow-hidden rounded-b-xl">
          {/* Wall 1: a login page. */}
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4" style={loop("refuse-wall-login")}>
            <span className="block h-1.5 w-20 rounded-full bg-ink" />
            <span className="mt-1 block h-5 w-36 rounded-md border border-rule bg-sunk/50" />
            <span className="block h-5 w-36 rounded-md border border-rule bg-sunk/50" />
            <span className="mt-1 block h-5 w-36 rounded-md bg-ink/80" />
          </div>
          {/* Wall 2: a 503. */}
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4" style={loop("refuse-wall-503")}>
            <span className="font-mono text-2xl font-semibold text-ink">503</span>
            <span className="font-mono text-caption text-muted">Service Unavailable</span>
            {bar("8rem")}{bar("6rem")}
          </div>
          {/* Wall 3: a bot challenge. */}
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4" style={loop("refuse-wall-bot")}>
            <span className="size-6 rounded-full border-2 border-rule-strong border-t-ink" />
            <span className="font-mono text-caption text-muted">Checking your browser…</span>
            <span className="mt-1 flex items-center gap-2 rounded border border-rule px-2 py-1"><span className="size-3 rounded-sm border border-rule-strong" /><span className="font-mono text-[10px] text-muted">I&apos;m not a robot</span></span>
          </div>
          {WALLS.map((w) => (
            <div key={w.id} className="pointer-events-none absolute inset-0 flex items-center justify-center" style={loop(`refuse-stamp-${w.id}`)}>
              <span className="flex flex-col items-center rounded-md border-[3px] border-bad px-3 py-1 font-mono uppercase text-bad"><span className="text-lg font-bold leading-tight tracking-wider">refused</span><span className="text-[10px] font-semibold tracking-wide">{w.stamp}</span></span>
            </div>
          ))}

          {/* The page itself, once it lands. */}
          <div className="absolute inset-0 p-3" style={loop("refuse-page")}>
            <div className="flex items-center gap-2" style={loop("refuse-paint-0")}><span className="h-1.5 w-8 rounded-full bg-ink" />{bar("1.2rem")}{bar("1rem")}{bar("1.4rem")}</div>
            <div className="mt-3 grid grid-cols-[5rem_1fr] gap-3">
              <div className="space-y-1.5" style={loop("refuse-paint-1")}>{bar("80%")}{bar("60%")}{bar("70%")}{bar("50%")}</div>
              <div className="space-y-1.5">
                <div className="space-y-1" style={loop("refuse-paint-2")}><span className="block h-1.5 w-24 rounded-full bg-ink" />{bar("95%")}{bar("88%")}{bar("70%")}</div>
                {/* The display:none block, made visible for the reader's sake, then dropped. */}
                <div className="relative rounded-md border border-dashed border-bad/60 bg-bad-soft/40 p-1.5" style={loop("refuse-hidden-none")}>
                  <div className="space-y-1">{bar("90%", "bg-bad/40")}{bar("75%", "bg-bad/40")}{bar("85%", "bg-bad/40")}</div>
                  <span className="absolute -top-2 right-1 rounded bg-bad-soft px-1 font-mono text-[9px] text-bad" style={loop("refuse-tag-none")}>display:none · 2,100 words</span>
                </div>
                <div className="space-y-1" style={loop("refuse-paint-3")}>{bar("92%")}{bar("64%")}</div>
              </div>
            </div>
            {/* The cookie banner. */}
            <div className="absolute inset-x-0 bottom-0 border-t border-rule bg-surface px-3 py-2 shadow-[0_-4px_12px_-6px_rgb(0_0_0/0.2)]" style={loop("refuse-hidden-cookie")}>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] text-muted">We use cookies to improve your experience.</span>
                <span className="ml-auto rounded bg-ink px-2 py-0.5 font-mono text-[9px] text-surface">Accept</span>
                <span className="absolute -top-2 left-3 rounded bg-bad-soft px-1 font-mono text-[9px] text-bad" style={loop("refuse-tag-cookie")}>cookie banner</span>
              </div>
            </div>
          </div>
        </div>

        {/* The parked links: outside the viewport's right edge, where a reader never sees them. */}
        <div className="absolute -right-[6.3rem] top-[3.2rem] w-[5.6rem]" style={loop("refuse-hidden-offscreen")}>
          <span className="mb-1 inline-block rounded bg-bad-soft px-1 font-mono text-[9px] leading-tight text-bad" style={loop("refuse-tag-offscreen")}>60 links<br />parked off-screen</span>
          <div className="grid grid-cols-6 gap-[3px]">
            {Array.from({ length: 60 }, (_, k) => <span key={k} className="h-[5px] rounded-[2px] bg-bad/45" />)}
          </div>
        </div>

        <span className="absolute -bottom-3 right-3 rounded-full border border-rule-strong bg-surface px-2 py-0.5 font-mono text-[10px] font-semibold text-ink shadow-sm" style={loop("refuse-count")}>1,340 words · the page</span>
      </div>

      {/* The engine's log, in its own words. */}
      <div className="absolute right-0 top-4 w-[10rem] rounded-xl border border-rule-strong bg-surface shadow-sm" style={loop("refuse-log")}>
        <div className="border-b border-rule px-3 py-1.5 font-mono text-caption text-ink">engine log</div>
        {/* Plain divs, not a list: this is drawn text in an aria-hidden illustration, not
            body copy (which the responsive check rightly holds to 14px on phones). */}
        <div className="space-y-1.5 px-3 py-2 font-mono text-[10px] leading-snug">
          {WALLS.map((w) => (
            <div key={w.id} className="text-bad" style={loop(`refuse-logline-wall-${w.id}`)}>{w.log}</div>
          ))}
          {HIDDEN.map((h) => (
            <div key={h.id} className="text-muted" style={loop(`refuse-logline-${h.id}`)}>{h.log}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
