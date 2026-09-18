/**
 * Step 4 ("reading order, then Markdown") on one clock, in ms. Left, the page as the
 * browser laid it out: a header, two columns, a footer -- every element measured. The
 * reading order is a recursive XY-cut over those boxes: a cut across the whole page
 * below the header, another above the footer, then a cut *down* the middle band, then
 * cuts within each column -- so columns stay columns, and the numbers land in the order
 * a reader would take. Right, the Markdown writes itself in exactly that order, under a
 * header that says how the page was fetched, whether its order was measured, and what
 * was refused. `buildOrderCss` turns it into `@keyframes` text.
 */

import { keyframesFor } from "./timeline";

export const ORDER_MS = {
  pageIn: 0,
  pageSettled: 350,
  paintStart: 300,
  paintStagger: 70,
  paintMs: 200,

  cutsStart: 1000,
  cutStagger: 320,
  cutMs: 260,

  numbersStart: 2800,
  numberStagger: 190,
  numberMs: 220,

  docIn: 2700,
  docSettled: 3000,
  headStart: 3100,
  headStagger: 200,
  headMs: 220,
  bodyStart: 4000,
  bodyStagger: 260,
  bodyMs: 240,

  holdEnd: 7600,
  fadeEnd: 8000,
  cycle: 8200,
} as const;

/** The page's boxes, in *document* order (how they'd come off the DOM), each with the
 * reading-order number the XY-cut assigns it. The sidebar is first in the DOM (a common
 * layout) but reads after the main column -- the whole point of measuring. */
export const BLOCKS = [
  { id: "header", order: 1 },
  { id: "sidebar", order: 5 },
  { id: "title", order: 2 },
  { id: "para1", order: 3 },
  { id: "para2", order: 4 },
  { id: "figure", order: 6 },
  { id: "footer", order: 7 },
] as const;

/** The cuts, in the order the recursion makes them: whole-page cuts first, then within
 * the band they leave, then within each column. Geometry in the page grid's 100×100 box,
 * each cut through the middle of the gap it separates (the grid's rows/columns and gaps
 * in `Step4Order.tsx` are what these numbers come from). */
export const CUTS = [
  { id: "below-header", d: "M0,19.5 L100,19.5" },
  { id: "above-footer", d: "M0,82.5 L100,82.5" },
  { id: "between-columns", d: "M31.5,19.5 L31.5,82.5" },
  { id: "main-1", d: "M33,34.5 L100,34.5" },
  { id: "main-2", d: "M33,49.2 L100,49.2" },
  { id: "main-3", d: "M33,63.8 L100,63.8" },
] as const;

/** The Markdown, line by line, in reading order; `order` ties a line to its block. */
export const DOC_HEAD = ["fetched: plain + render", "order: measured (xy-cut)", "refused: none"] as const;
export const DOC_BODY = [
  { order: 1, text: "Home · Docs · Pricing" },
  { order: 2, text: "# Getting started" },
  { order: 3, text: "Install the CLI, point it at a site." },
  { order: 4, text: "It reads each page twice, keeps both." },
  { order: 5, text: "> See also: Configure · API · FAQ" },
  { order: 6, text: "![The crawl, as a tree](crawl.png)" },
  { order: 7, text: "© WebGraph" },
] as const;

export const cutAt = (i: number) => ORDER_MS.cutsStart + i * ORDER_MS.cutStagger;
export const numberAt = (order: number) => ORDER_MS.numbersStart + (order - 1) * ORDER_MS.numberStagger;
export const bodyAt = (i: number) => ORDER_MS.bodyStart + i * ORDER_MS.bodyStagger;

export function buildOrderCss(): string {
  const M = ORDER_MS;
  const kf = keyframesFor(M.cycle);
  const out: string[] = [];
  const gone = "opacity: 0;";

  out.push(kf("order-page", [
    [[0, M.pageIn], "opacity: 0; transform: scale(0.94);"],
    [M.pageSettled, "opacity: 1; transform: scale(1);"],
    [M.holdEnd, "opacity: 1; transform: scale(1);"],
    [M.fadeEnd, gone],
  ]));
  BLOCKS.forEach((b, i) => {
    const t = M.paintStart + i * M.paintStagger;
    out.push(kf(`order-paint-${b.id}`, [[[0, t], gone], [t + M.paintMs, "opacity: 1;"]]));
    // The block lights up as its number lands.
    const n = numberAt(b.order);
    out.push(kf(`order-lit-${b.id}`, [
      [[0, n], "border-color: var(--rule); background-color: transparent;"],
      [n + 160, "border-color: var(--accent); background-color: var(--accent-soft);"],
      [n + 900, "border-color: var(--accent); background-color: var(--accent-soft);"],
      [n + 1400, "border-color: var(--accent); background-color: transparent;"],
    ]));
    out.push(kf(`order-num-${b.id}`, [
      [[0, n], "opacity: 0; transform: scale(0.5);"],
      [n + 140, "opacity: 1; transform: scale(1.15);"],
      [n + M.numberMs, "opacity: 1; transform: scale(1);"],
    ]));
  });
  CUTS.forEach((c, i) => {
    const t = cutAt(i);
    out.push(kf(`order-cut-${c.id}`, [
      [[0, t], "stroke-dashoffset: 1; opacity: 0;"], // hidden: an offset dash's round cap still shows as a dot
      [t + 1, "stroke-dashoffset: 1; opacity: 1;"],
      [t + M.cutMs, "stroke-dashoffset: 0; opacity: 1;"],
      [M.numbersStart + 600, "stroke-dashoffset: 0; opacity: 1;"],
      [M.numbersStart + 1100, "stroke-dashoffset: 0; opacity: 0.35;"],
    ]));
  });

  out.push(kf("order-doc", [
    [[0, M.docIn], "opacity: 0; transform: translateX(10px);"],
    [M.docSettled, "opacity: 1; transform: translateX(0);"],
    [M.holdEnd, "opacity: 1; transform: translateX(0);"],
    [M.fadeEnd, gone],
  ]));
  DOC_HEAD.forEach((_, i) => {
    const t = M.headStart + i * M.headStagger;
    out.push(kf(`order-head-${i}`, [[[0, t], "clip-path: inset(0 100% 0 0);"], [t + M.headMs, "clip-path: inset(0 0 0 0);"]]));
  });
  DOC_BODY.forEach((_, i) => {
    const t = bodyAt(i);
    out.push(kf(`order-line-${i}`, [[[0, t], "clip-path: inset(0 100% 0 0);"], [t + M.bodyMs, "clip-path: inset(0 0 0 0);"]]));
    out.push(kf(`order-margin-${i}`, [
      [[0, t], "opacity: 0; transform: scale(0.6);"],
      [t + 140, "opacity: 1; transform: scale(1.1);"],
      [t + M.bodyMs, "opacity: 1; transform: scale(1);"],
    ]));
  });
  return out.join("\n");
}
