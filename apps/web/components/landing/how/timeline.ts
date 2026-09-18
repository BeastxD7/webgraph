/**
 * The one piece every animated step shares: a schedule written in milliseconds, turned
 * into real `@keyframes` text whose stops are percentages of one cycle. Each step's story
 * (step 1's typing-then-crawl, step 2's two fetches, ...) is many elements moving on one
 * clock, and a single generated cycle is what keeps them in phase -- two independently
 * `infinite` CSS animations drift apart eventually; percentages of one duration never do.
 *
 * `keyframesFor(cycleMs)` returns a `kf(name, stops)` that writes one `@keyframes` block:
 * each stop is `[ms, css]` (or `[[ms, ms, ...], css]` for several moments sharing one
 * state, e.g. a hold). A stop past the cycle is clamped to 100%; if the last stop ends
 * before the cycle, it is held to 100% explicitly, because a `@keyframes` block with no
 * 100% stop interpolates back to the element's *base* style, not its last keyframe.
 */
export type Stop = readonly [at: number | readonly number[], css: string];

export const pct = (ms: number, cycleMs: number) => `${((Math.min(ms, cycleMs) / cycleMs) * 100).toFixed(3)}%`;

export function keyframesFor(cycleMs: number) {
  return function kf(name: string, stops: readonly Stop[]): string {
    const lines = stops.map(([at, css]) => {
      const ats = (Array.isArray(at) ? at : [at as number]).map((ms) => pct(ms, cycleMs));
      return `  ${ats.join(", ")} { ${css} }`;
    });
    const last = stops[stops.length - 1];
    if (last) {
      const lastMs = Array.isArray(last[0]) ? Math.max(...(last[0] as readonly number[])) : (last[0] as number);
      if (lastMs < cycleMs) lines.push(`  100% { ${last[1]} }`);
    }
    return `@keyframes ${name} {\n${lines.join("\n")}\n}`;
  };
}
