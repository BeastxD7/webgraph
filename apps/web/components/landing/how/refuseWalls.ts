/**
 * Step 3 ("refuse the walls, drop the hidden") on one clock, in ms. Two acts in one
 * browser window. First the walls: the fetch lands on a login redirect, then a 503, then
 * a bot challenge, and each is stamped REFUSED in the engine's own words -- never passed
 * off as the page. Then the page itself loads, and what the browser hides is shown for
 * what it is -- a cookie banner, sixty links parked off the screen, a `display:none`
 * block holding 2,100 words -- and dropped, one by one, with a log line for each. What's
 * left is the page a reader saw. `buildRefuseCss` turns it into `@keyframes` text.
 */

import { keyframesFor } from "./timeline";

export const REFUSE_MS = {
  windowIn: 0,
  windowSettled: 350,

  // Act one: three walls, each shown, then stamped, then replaced by the next attempt.
  wallMs: 1100,
  wallsStart: 450,
  wallPaintMs: 250,
  stampAfter: 500, // into the wall's slot
  logAfter: 620,

  // Act two: the page loads for real...
  pageIn: 3750,
  pagePainted: 4150,
  // ...and the hidden things surface: a cookie banner, links parked off the screen, a
  // display:none block -- each revealed, then dropped.
  hiddenStart: 4300,
  hiddenStagger: 380,
  hiddenRevealMs: 260,
  dropStart: 5700,
  dropStagger: 380,
  dropMs: 320,

  countIn: 6950,
  countSettled: 7200,

  holdEnd: 8500,
  fadeEnd: 8900,
  cycle: 9100,
} as const;

export const WALLS = [
  { id: "login", url: "/accounts/login?next=/docs", stamp: "login wall", log: "refused · redirected to a login page" },
  { id: "503", url: "/docs", stamp: "503", log: "refused · 503 from the server" },
  { id: "bot", url: "/docs", stamp: "bot challenge", log: "refused · a bot challenge, not a page" },
] as const;

export const HIDDEN = [
  { id: "cookie", log: "dropped · cookie banner" },
  { id: "offscreen", log: "dropped · 60 links parked off-screen" },
  { id: "none", log: "dropped · display:none, 2,100 words" },
] as const;

export const wallSlot = (i: number) => REFUSE_MS.wallsStart + i * REFUSE_MS.wallMs;
export const hiddenAt = (i: number) => REFUSE_MS.hiddenStart + i * REFUSE_MS.hiddenStagger;
export const dropAt = (i: number) => REFUSE_MS.dropStart + i * REFUSE_MS.dropStagger;

export function buildRefuseCss(): string {
  const M = REFUSE_MS;
  const kf = keyframesFor(M.cycle);
  const out: string[] = [];
  const gone = "opacity: 0;";
  const pop = (name: string, at: number, from = "opacity: 0; transform: scale(0.85);", to = "opacity: 1; transform: scale(1);") =>
    kf(name, [[[0, at], from], [at + 160, `opacity: 1; transform: scale(1.06);`], [at + 260, to]]);

  out.push(kf("refuse-window", [
    [[0, M.windowIn], "opacity: 0; transform: scale(0.94);"],
    [M.windowSettled, "opacity: 1; transform: scale(1);"],
    [M.holdEnd, "opacity: 1; transform: scale(1);"],
    [M.fadeEnd, gone],
  ]));
  out.push(kf("refuse-log", [
    [[0, M.windowIn], "opacity: 0; transform: translateX(8px);"],
    [M.windowSettled, "opacity: 1; transform: translateX(0);"],
    [M.holdEnd, "opacity: 1; transform: translateX(0);"],
    [M.fadeEnd, gone],
  ]));

  WALLS.forEach((w, i) => {
    const t = wallSlot(i);
    const end = wallSlot(i + 1);
    // The wall's content and its address-bar URL share one visibility window.
    out.push(kf(`refuse-wall-${w.id}`, [
      [[0, t], gone],
      [t + M.wallPaintMs, "opacity: 1;"],
      [end - 120, "opacity: 1;"],
      [end, gone],
    ]));
    out.push(kf(`refuse-stamp-${w.id}`, [
      [[0, t + M.stampAfter], "opacity: 0; transform: rotate(-8deg) scale(1.6);"],
      [t + M.stampAfter + 140, "opacity: 1; transform: rotate(-8deg) scale(0.96);"],
      [t + M.stampAfter + 220, "opacity: 1; transform: rotate(-8deg) scale(1);"],
      [end - 120, "opacity: 1; transform: rotate(-8deg) scale(1);"],
      [end, "opacity: 0; transform: rotate(-8deg) scale(1);"],
    ]));
    out.push(kf(`refuse-logline-wall-${w.id}`, [
      [[0, t + M.logAfter], "opacity: 0; transform: translateY(4px);"],
      [t + M.logAfter + 220, "opacity: 1; transform: translateY(0);"],
    ]));
  });

  out.push(kf("refuse-page", [[[0, M.pageIn], gone], [M.pagePainted, "opacity: 1;"]]));
  // The page's blocks paint in sequence once it lands.
  [0, 1, 2, 3].forEach((i) => {
    const t = M.pageIn + i * 90;
    out.push(kf(`refuse-paint-${i}`, [[[0, t], gone], [t + 220, "opacity: 1;"]]));
  });

  // Cookie banner: slides up into the window, later slides back out.
  out.push(kf("refuse-hidden-cookie", [
    [[0, hiddenAt(0)], "transform: translateY(110%);"],
    [hiddenAt(0) + M.hiddenRevealMs, "transform: translateY(0);"],
    [dropAt(0), "transform: translateY(0);"],
    [dropAt(0) + M.dropMs, "transform: translateY(110%);"],
  ]));
  // The parked links: appear beyond the window's right edge, later shrink away.
  out.push(kf("refuse-hidden-offscreen", [
    [[0, hiddenAt(1)], "opacity: 0; transform: scale(0.9);"],
    [hiddenAt(1) + M.hiddenRevealMs, "opacity: 1; transform: scale(1);"],
    [dropAt(1), "opacity: 1; transform: scale(1);"],
    [dropAt(1) + M.dropMs, "opacity: 0; transform: scale(0.6);"],
  ]));
  // The display:none block: a dashed ghost that fills in, then is struck and fades.
  out.push(kf("refuse-hidden-none", [
    [[0, hiddenAt(2)], "opacity: 0;"],
    [hiddenAt(2) + M.hiddenRevealMs, "opacity: 1;"],
    [dropAt(2), "opacity: 1;"],
    [dropAt(2) + M.dropMs, "opacity: 0;"],
  ]));
  // The reveal labels ride with their subject; their own keyframe just delays them a beat.
  HIDDEN.forEach((h, i) => {
    out.push(kf(`refuse-tag-${h.id}`, [
      [[0, hiddenAt(i) + 120], "opacity: 0; transform: translateY(3px);"],
      [hiddenAt(i) + 320, "opacity: 1; transform: translateY(0);"],
      [dropAt(i), "opacity: 1; transform: translateY(0);"],
      [dropAt(i) + 120, "opacity: 0; transform: translateY(0);"],
    ]));
    out.push(kf(`refuse-logline-${h.id}`, [
      [[0, dropAt(i) + 100], "opacity: 0; transform: translateY(4px);"],
      [dropAt(i) + 320, "opacity: 1; transform: translateY(0);"],
    ]));
  });

  out.push(pop("refuse-count", M.countIn));
  return out.join("\n");
}
