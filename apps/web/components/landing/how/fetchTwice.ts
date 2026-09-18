/**
 * Step 2 ("fetch twice") on one clock, in ms: a page picked from the crawl, two fetches
 * fired at it side by side -- the plain request streaming raw server HTML on the left, a
 * real browser window painting on the right, then losing a block on hydration and gaining
 * one from a script -- two different word counts, and the two results sliding together
 * into the union the engine keeps. `buildFetchCss` turns it into `@keyframes` text;
 * `Step2Fetch.tsx` injects that once and points each element at its animation by name.
 */

import { keyframesFor } from "./timeline";

export const FETCH_MS = {
  chipIn: 0,
  chipSettled: 400,

  lanesStart: 500,
  lanesEnd: 1000,
  labelsIn: 900,
  labelsSettled: 1150,

  cardsIn: 1000,
  cardsSettled: 1350,

  // The plain response streams in line by line...
  plainStart: 1400,
  plainStagger: 150,
  plainLineMs: 220,

  // ...while the browser loads (progress bar), then paints block by block.
  progressStart: 1400,
  progressEnd: 2000,
  paintStart: 2000,
  paintStagger: 150,
  paintMs: 220,

  // Hydration replaces the server's markup; the pricing table it rendered is gone.
  lostStart: 2900,
  lostEnd: 3200,
  lostLabelIn: 3000,

  // A script inserts what no plain fetch would ever see.
  insertStart: 3300,
  insertEnd: 3600,
  insertLabelIn: 3450,

  countersIn: 3800,
  countersSettled: 4050,

  mergeStart: 4500,
  mergeEnd: 5000,
  cardsGoneStart: 4900,
  cardsGone: 5100,

  unionIn: 5000,
  unionSettled: 5350,
  stampIn: 5500,
  stampSettled: 5750,
  pingEnd: 6100,

  holdEnd: 7300,
  fadeEnd: 7700,
  cycle: 7900,
} as const;

/** The raw response, one line of server HTML each. `kept` marks what the rendered page
 * later loses, so the union can show it came from here. */
export const PLAIN_LINES: ReadonlyArray<{ text: string; kept?: boolean }> = [
  { text: "<h1>Products</h1>" },
  { text: "<nav>Home · Docs · Pricing</nav>" },
  { text: "<p>Three tiers, one API.</p>" },
  { text: '<table class="pricing">', kept: true },
  { text: "  <tr><td>Starter</td><td>$0</td>", kept: true },
  { text: '<section id="faq">…</section>' },
  { text: '<script src="/app.js"></script>' },
  { text: "</body>" },
];

/** What the browser paints, in paint order. `lost` is server markup hydration throws away;
 * `inserted` arrives from a script after the page has painted. */
export const PAINT_BLOCKS: ReadonlyArray<{ id: string; lost?: boolean; inserted?: boolean }> = [
  { id: "header" },
  { id: "hero" },
  { id: "pricing", lost: true },
  { id: "grid" },
  { id: "reviews", inserted: true },
];

export function buildFetchCss(): string {
  const M = FETCH_MS;
  const kf = keyframesFor(M.cycle);
  const out: string[] = [];
  const gone = "opacity: 0;";
  const hidden = "opacity: 0; transform: translateY(6px) scale(0.96);";
  const shown = "opacity: 1; transform: translateY(0) scale(1);";
  const fade = (css: string) => [[M.holdEnd, css], [M.fadeEnd, gone]] as const;

  out.push(kf("fetch-chip", [
    [[0, M.chipIn], "opacity: 0; transform: scale(0.85);"],
    [M.chipSettled, "opacity: 1; transform: scale(1);"],
    ...fade("opacity: 1; transform: scale(1);"),
  ]));
  out.push(kf("fetch-lane", [
    [[0, M.lanesStart], "stroke-dashoffset: 1; opacity: 0;"], // hidden: an offset dash's round cap still shows as a dot
    [M.lanesStart + 1, "stroke-dashoffset: 1; opacity: 1;"],
    [M.lanesEnd, "stroke-dashoffset: 0; opacity: 1;"],
    [M.holdEnd, "stroke-dashoffset: 0; opacity: 1;"],
    [M.fadeEnd, "stroke-dashoffset: 0; opacity: 0;"],
  ]));
  out.push(kf("fetch-label", [
    [[0, M.labelsIn], hidden],
    [M.labelsSettled, shown],
    ...fade(shown),
  ]));
  // The two results: in together, then slide toward each other and hand over to the union.
  const card = (name: string, slide: string) => kf(name, [
    [[0, M.cardsIn], "opacity: 0; transform: translateX(0) scale(0.94);"],
    [M.cardsSettled, "opacity: 1; transform: translateX(0) scale(1);"],
    [M.mergeStart, "opacity: 1; transform: translateX(0) scale(1);"],
    [M.cardsGoneStart, `opacity: 1; transform: translateX(${slide}) scale(0.98);`],
    [M.mergeEnd, `opacity: 0.4; transform: translateX(${slide}) scale(0.96);`],
    [M.cardsGone, `opacity: 0; transform: translateX(${slide}) scale(0.96);`],
  ]);
  out.push(card("fetch-plain", "var(--fetch-plain-slide)"));
  out.push(card("fetch-window", "var(--fetch-window-slide)"));

  PLAIN_LINES.forEach((_, i) => {
    const t = M.plainStart + i * M.plainStagger;
    out.push(kf(`fetch-plain-line-${i}`, [
      [[0, t], "clip-path: inset(0 100% 0 0);"],
      [t + M.plainLineMs, "clip-path: inset(0 0 0 0);"],
    ]));
  });

  out.push(kf("fetch-progress", [
    [[0, M.progressStart], "transform: scaleX(0); opacity: 1;"],
    [M.progressEnd, "transform: scaleX(1); opacity: 1;"],
    [M.progressEnd + 250, "transform: scaleX(1); opacity: 0;"],
  ]));
  PAINT_BLOCKS.forEach((b, i) => {
    const t = M.paintStart + i * M.paintStagger;
    if (b.inserted) {
      out.push(kf(`fetch-paint-${b.id}`, [
        [[0, M.insertStart], "opacity: 0; transform: translateY(10px); max-height: 0;"],
        [M.insertEnd, "opacity: 1; transform: translateY(0); max-height: 3rem;"],
      ]));
    } else if (b.lost) {
      out.push(kf(`fetch-paint-${b.id}`, [
        [[0, t], "opacity: 0;"],
        [t + M.paintMs, "opacity: 1;"],
        [M.lostStart, "opacity: 1;"],
        [M.lostEnd, "opacity: 0.22;"],
      ]));
    } else {
      out.push(kf(`fetch-paint-${b.id}`, [
        [[0, t], "opacity: 0;"],
        [t + M.paintMs, "opacity: 1;"],
      ]));
    }
  });
  out.push(kf("fetch-lost-label", [[[0, M.lostLabelIn], hidden], [M.lostLabelIn + 250, shown]]));
  out.push(kf("fetch-insert-label", [[[0, M.insertLabelIn], hidden], [M.insertLabelIn + 250, shown]]));

  out.push(kf("fetch-counter", [
    [[0, M.countersIn], "opacity: 0; transform: scale(0.7);"],
    [M.countersIn + 150, "opacity: 1; transform: scale(1.08);"],
    [M.countersSettled, "opacity: 1; transform: scale(1);"],
  ]));

  out.push(kf("fetch-union", [
    [[0, M.unionIn], "opacity: 0; transform: scale(0.9);"],
    [M.unionSettled, "opacity: 1; transform: scale(1);"],
    ...fade("opacity: 1; transform: scale(1);"),
  ]));
  out.push(kf("fetch-stamp", [
    [[0, M.stampIn], "opacity: 0; transform: scale(0.6);"],
    [M.stampIn + 150, "opacity: 1; transform: scale(1.1);"],
    [M.stampSettled, "opacity: 1; transform: scale(1);"],
  ]));
  out.push(kf("fetch-ping", [
    [[0, M.stampIn], "opacity: 0; transform: scale(1);"],
    [M.stampIn + 1, "opacity: 0.55; transform: scale(1);"],
    [M.pingEnd, "opacity: 0; transform: scale(1.9);"],
  ]));
  return out.join("\n");
}
