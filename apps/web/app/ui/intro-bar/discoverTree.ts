/**
 * One shared timeline, in milliseconds, for the whole intro-bar cycle: blank canvas, the
 * brand mark, the mark dissolving into the search bar, typing, entering, and -- from here on
 * -- the page tree the "crawl" turns up, revealed strictly breadth-first: every node at one
 * depth settles before the next depth's first node starts anywhere in the tree, even across
 * different parents. Everything is computed from these ms constants and one shared
 * `cycleMs`, so the intro and the tree reveal can never drift out of phase with each other
 * the way two independently-`infinite` CSS animations eventually would. `buildKeyframesCss`
 * turns all of it into real `@keyframes` text; the component injects that once and points
 * each element at its generated animation name via inline `style` (Tailwind's arbitrary
 * `animate-[...]` values have to be static strings it can see at build time, which a
 * computed duration/percentage isn't).
 */

/** The intro, in absolute ms -- unchanged from the tuned 3200ms sequence, just no longer
 * the *whole* cycle: the tree reveal continues on from where this leaves off instead of
 * looping straight back to blank. */
export const INTRO_MS = {
  logoPeak: 410,
  logoHoldStart: 563,
  logoHoldEnd: 870,
  logoGone: 1075,

  barExpandStart: 870,
  barFullStart: 1229,
  barFullEnd: 2253,
  barCollapseEnd: 2458,

  contentInStart: 1126,
  contentInEnd: 1280,
  contentOutStart: 2253,
  contentOutEnd: 2406,

  typeStart: 1280,
  typeFullStart: 1946,
  typeFullEnd: 2253,
  typeClearEnd: 2406,

  enterFlashPeak: 1997,
  enterFlashEnd: 2099,
} as const;

/** Root appears once the bar has visually finished dissolving (its content and shape both
 * fully faded) -- a clean handoff, not a race between the two. */
const ROOT_START = Math.max(INTRO_MS.contentOutEnd, INTRO_MS.barCollapseEnd);

export interface PageNode {
  readonly path: string;
  readonly children?: readonly PageNode[];
}

export const DISCOVER_TREE: PageNode = {
  path: "webgraph.com",
  children: [
    { path: "/about" },
    { path: "/products" },
    { path: "/contact" },
    { path: "/features" },
    {
      path: "/docs",
      children: [
        { path: "/docs/getting-started" },
        { path: "/docs/api" },
        { path: "/docs/faq" },
      ],
    },
  ],
};

/** Retime the reveal from here -- these are the only numbers that should need touching. */
export const TIMING = {
  rootStart: ROOT_START,
  rootSettle: 100,
  depthGap: 60,
  siblingStagger: 110,
  edgeDrawMs: 80,
  nodePopMs: 90,
  holdMs: 300,
  fadeMs: 200,
  tailMs: 180,
} as const;

export interface TimedNode {
  readonly id: string;
  readonly path: string;
  readonly depth: number;
  readonly startMs: number; // when this node's incoming edge begins drawing (root: rootStart)
  readonly popMs: number; // when the node itself starts popping in
  readonly doneMs: number; // when this node itself has settled (not its subtree)
  readonly children: TimedNode[];
}

const slug = (path: string) => path.replace(/[^a-zA-Z0-9]+/g, "-").replace(/(^-|-$)/g, "");

export interface Layout {
  root: TimedNode;
  holdEnd: number;
  fadeEnd: number;
  cycleMs: number;
}

/** Breadth-first, level by level: every node in `currentLevel` gets its start/pop/done times
 * computed together (staggered across the *whole* level, not per-parent), and only once an
 * entire level is done does the next level -- the pooled children of every node in this
 * level -- get laid out, all starting from that level's shared finish time. */
export function layoutTree(root: PageNode): Layout {
  const timedRoot: TimedNode = {
    id: slug(root.path), path: root.path, depth: 0,
    startMs: TIMING.rootStart, popMs: TIMING.rootStart, doneMs: TIMING.rootStart + TIMING.rootSettle,
    children: [],
  };

  let levelFinish = timedRoot.doneMs;
  let currentLevel: ReadonlyArray<{ source: PageNode; timed: TimedNode }> = [{ source: root, timed: timedRoot }];
  let depth = 0;

  while (true) {
    const nextSources: ReadonlyArray<{ source: PageNode; parent: TimedNode }> = currentLevel.flatMap(({ source, timed }) =>
      (source.children ?? []).map((child) => ({ source: child, parent: timed })));
    if (nextSources.length === 0) break;
    depth += 1;
    const depthStart = levelFinish + TIMING.depthGap;
    let thisLevelFinish = depthStart;
    const nextLevel = nextSources.map(({ source, parent }, i) => {
      const startMs = depthStart + i * TIMING.siblingStagger;
      const popMs = startMs + TIMING.edgeDrawMs;
      const doneMs = popMs + TIMING.nodePopMs;
      thisLevelFinish = Math.max(thisLevelFinish, doneMs);
      const timed: TimedNode = { id: slug(source.path), path: source.path, depth, startMs, popMs, doneMs, children: [] };
      parent.children.push(timed);
      return { source, timed };
    });
    levelFinish = thisLevelFinish;
    currentLevel = nextLevel;
  }

  const holdEnd = levelFinish + TIMING.holdMs;
  const fadeEnd = holdEnd + TIMING.fadeMs;
  const cycleMs = fadeEnd + TIMING.tailMs;
  return { root: timedRoot, holdEnd, fadeEnd, cycleMs };
}

export function flattenExceptRoot(root: TimedNode): TimedNode[] {
  const out: TimedNode[] = [];
  const walk = (node: TimedNode) => {
    for (const child of node.children) {
      out.push(child);
      walk(child);
    }
  };
  walk(root);
  return out;
}

const pct = (ms: number, cycleMs: number) => `${((ms / cycleMs) * 100).toFixed(3)}%`;

/** All of it, as real `@keyframes` text: the intro (fixed absolute ms, rescaled onto
 * whatever `cycleMs` the tree ends up needing) plus one node + one edge keyframe per
 * discovered page. */
export function buildKeyframesCss(layout: Layout): string {
  const { root, holdEnd, fadeEnd, cycleMs } = layout;
  const p = (ms: number) => pct(ms, cycleMs);

  const intro = `
@keyframes discover-logo {
  0% { opacity: 0; transform: scale(0.7); animation-timing-function: cubic-bezier(0.34, 1.56, 0.64, 1); }
  ${p(INTRO_MS.logoPeak)} { opacity: 1; transform: scale(1.06); animation-timing-function: cubic-bezier(0.34, 1.56, 0.64, 1); }
  ${p(INTRO_MS.logoHoldStart)}, ${p(INTRO_MS.logoHoldEnd)} { opacity: 1; transform: scale(1); animation-timing-function: cubic-bezier(0.4, 0, 1, 1); }
  ${p(INTRO_MS.logoGone)}, 100% { opacity: 0; transform: scale(0.82); }
}
@keyframes discover-bar-shape {
  0%, ${p(INTRO_MS.barExpandStart)} { transform: scaleX(0); animation-timing-function: cubic-bezier(0.16, 1, 0.3, 1); }
  ${p(INTRO_MS.barFullStart)}, ${p(INTRO_MS.barFullEnd)} { transform: scaleX(1); animation-timing-function: cubic-bezier(0.4, 0, 1, 1); }
  ${p(INTRO_MS.barCollapseEnd)}, 100% { transform: scaleX(0); }
}
@keyframes discover-bar-content {
  0%, ${p(INTRO_MS.contentInStart)} { opacity: 0; }
  ${p(INTRO_MS.contentInEnd)}, ${p(INTRO_MS.contentOutStart)} { opacity: 1; }
  ${p(INTRO_MS.contentOutEnd)}, 100% { opacity: 0; }
}
@keyframes discover-type-width {
  0%, ${p(INTRO_MS.typeStart)} { width: 0; }
  ${p(INTRO_MS.typeFullStart)}, ${p(INTRO_MS.typeFullEnd)} { width: 12ch; }
  ${p(INTRO_MS.typeClearEnd)}, 100% { width: 0; }
}
@keyframes discover-enter-flash {
  0%, ${p(INTRO_MS.enterFlashPeak - 128)} { transform: scale(1); background-color: var(--surface); }
  ${p(INTRO_MS.enterFlashPeak)} { transform: scale(1.18); background-color: var(--accent); }
  ${p(INTRO_MS.enterFlashEnd)}, 100% { transform: scale(1); background-color: var(--surface); }
}
@keyframes discover-enter-arrow-flash {
  0%, ${p(INTRO_MS.enterFlashPeak - 128)} { stroke: var(--accent-ink); }
  ${p(INTRO_MS.enterFlashPeak)} { stroke: var(--surface); }
  ${p(INTRO_MS.enterFlashEnd)}, 100% { stroke: var(--accent-ink); }
}
@keyframes discover-root {
  0%, ${p(TIMING.rootStart)} { opacity: 0; transform: scale(0.85); }
  ${p(root.doneMs)}, ${p(holdEnd)} { opacity: 1; transform: scale(1); }
  ${p(fadeEnd)}, 100% { opacity: 0; transform: scale(0.85); }
}`;

  const nodeCss = flattenExceptRoot(root).map((n) => `
@keyframes discover-node-${n.id} {
  0%, ${p(n.popMs)} { opacity: 0; transform: translateY(-14px) scale(0.85); filter: blur(3px); }
  ${p(n.popMs + TIMING.nodePopMs * 0.6)} { opacity: 1; transform: translateY(2px) scale(1.05); filter: blur(0); }
  ${p(n.doneMs)}, ${p(holdEnd)} { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
  ${p(fadeEnd)}, 100% { opacity: 0; transform: translateY(-10px) scale(0.9); filter: blur(3px); }
}
@keyframes discover-edge-${n.id} {
  0%, ${p(n.startMs)} { stroke-dashoffset: 1; }
  ${p(n.popMs)}, ${p(holdEnd)} { stroke-dashoffset: 0; }
  ${p(fadeEnd)}, 100% { stroke-dashoffset: 1; }
}`).join("\n");

  // A brief expanding "ping" ring on arrival, once per node -- a nested child of the node's
  // own element, so (a nested element, never the animated one itself) it only reads as visible
  // for as long as the parent's own opacity keyframe already says it should.
  const pingCss = flattenExceptRoot(root).map((n) => `
@keyframes discover-ping-${n.id} {
  0%, ${p(n.popMs)}   { opacity: 0; transform: scale(1); }
  ${p(n.popMs + 1)}    { opacity: 0.55; transform: scale(1); }
  ${p(n.popMs + 90)}  { opacity: 0; transform: scale(1.9); }
  100% { opacity: 0; transform: scale(1.9); }
}`).join("\n");

  return intro + nodeCss + pingCss;
}
