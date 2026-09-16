/**
 * The landing stage: a page becomes ordered blocks, the hidden things fall away, the rest
 * becomes Markdown and a graph.
 *
 * Plain TypeScript over Canvas 2D, no library. The scene lives in an 800×600 virtual box
 * that `draw` scales to whatever canvas it is given. Scroll selects a chapter and a local
 * progress `t`; the bodies are simulated on the wall clock with per-chapter targets — gravity
 * and a bounce while a block is falling, a critically damped spring to its slot once it has
 * landed, an outward impulse and a fade when the scan refuses it. Reversal (scrolling back
 * up) works because the targets change, not because the simulation rewinds. Everything
 * deterministic — the scan line, the typing, the numbering — reads `t` directly.
 *
 * Chapters: 0 the promise (hero), 1 the pain, 2 the turn, 3 the result.
 */

export const VW = 800;
export const VH = 600;

export type Palette = {
  ink: string;
  muted: string;
  faint: string;
  rule: string;
  ruleStrong: string;
  accent: string;
  accentInk: string;
  accentSoft: string;
  warn: string;
  bad: string;
  surface: string;
  sunk: string;
  ground: string;
  inverse: string;
  sans: string;
  mono: string;
  dark: boolean;
};

/** Text the stage shows that comes from `lib/benchmarks.ts` and the changelog. */
export type StageCopy = {
  /** e.g. "word recall 1.000 on 22 of 29 sites · nothing below 0.945" */
  fidelity: string;
  /** The Site Truth Report rows: [label, value]. */
  report: ReadonlyArray<readonly [string, string]>;
};

type Shape = "nav" | "h1" | "text" | "image" | "table" | "banner" | "modal" | "badge" | "links" | "hidden";

type Body = {
  id: string;
  kind: "kept" | "junk";
  shape: Shape;
  /** The slot: where the body belongs when it is present. */
  tx: number;
  ty: number;
  w: number;
  h: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  rot: number;
  vrot: number;
  alpha: number;
  present: boolean;
  falling: boolean;
  /** Kept: reading order, 1-based. Junk: the chapter-1 progress at which it drops in. */
  order: number;
  drop: number;
  /** Kept blocks that lose their words in chapter 1 (the page needed a browser). */
  missing: boolean;
  /** Junk: the caption drawn on the body, the refusal drawn when the scan passes, its colour. */
  caption: string;
  refusal: readonly string[];
  flag: "bad" | "warn";
  /** Junk: what a naive extractor emitted for it. */
  emitted: string;
  /** Junk: which side it flies off to when refused (-1 left, 1 right). */
  side: -1 | 1;
};

/** The page's frame in virtual units. */
const PAGE = { x: 150, y: 50, w: 320, h: 510 } as const;
/** The output column to the right of the page. */
const OUT = { x: 520, w: 260 } as const;

const G = 1900; // gravity, virtual px/s²
const SPRING_K = 150;
const SPRING_C = 2 * Math.sqrt(SPRING_K); // critically damped

function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

function ease(v: number): number {
  const t = clamp01(v);
  return 1 - (1 - t) * (1 - t) * (1 - t);
}

function body(
  partial: Pick<Body, "id" | "kind" | "shape" | "tx" | "ty" | "w" | "h"> & Partial<Body>,
): Body {
  return {
    x: partial.tx,
    y: partial.ty,
    vx: 0,
    vy: 0,
    rot: 0,
    vrot: 0,
    alpha: 0,
    present: false,
    falling: false,
    order: 0,
    drop: 0,
    missing: false,
    caption: "",
    refusal: [],
    flag: "bad",
    emitted: "",
    side: 1,
    ...partial,
  };
}

/** The kept blocks, in reading order: nav, h1, lede, image beside a column, two paragraphs and a table. */
function keptBodies(): Body[] {
  const L = PAGE.x + 20;
  const W = PAGE.w - 40;
  return [
    body({ id: "nav", kind: "kept", shape: "nav", tx: L, ty: 82, w: W, h: 18, order: 1 }),
    body({ id: "h1", kind: "kept", shape: "h1", tx: L, ty: 118, w: 210, h: 34, order: 2 }),
    body({ id: "lede", kind: "kept", shape: "text", tx: L, ty: 166, w: W, h: 38, order: 3 }),
    body({ id: "img", kind: "kept", shape: "image", tx: L, ty: 222, w: 128, h: 96, order: 4 }),
    body({ id: "colB", kind: "kept", shape: "text", tx: L + 144, ty: 222, w: W - 144, h: 96, order: 5, missing: true }),
    body({ id: "paraB", kind: "kept", shape: "text", tx: L, ty: 336, w: W, h: 62, order: 6, missing: true }),
    body({ id: "table", kind: "kept", shape: "table", tx: L, ty: 416, w: W, h: 78, order: 7 }),
    body({ id: "paraC", kind: "kept", shape: "text", tx: L, ty: 512, w: W, h: 30, order: 8 }),
  ];
}

/**
 * What a naive extractor returns as content. Every one is a shape the engine met on a real
 * site (CHANGELOG): a consent dialog chosen as the thread, a login redirect, a 5xx served
 * to the render, ~60 off-screen gambling links on vtu.ac.in, 2,100 words in nine closed
 * dialogs. The refusal strings are the engine's own (`resolve.py`), shortened to fit.
 */
function junkBodies(): Body[] {
  return [
    body({
      id: "cookie", kind: "junk", shape: "banner",
      tx: PAGE.x, ty: PAGE.y + PAGE.h - 66, w: PAGE.w, h: 66, drop: 0.08, side: -1,
      caption: "We use cookies. Accept all?", emitted: "Accept all cookies",
      refusal: ["consent dialog", "left out of content"], flag: "warn",
    }),
    body({
      id: "login", kind: "junk", shape: "modal",
      tx: PAGE.x + 62, ty: 196, w: 196, h: 128, drop: 0.24, side: 1,
      caption: "Sign in to continue", emitted: "Sign in to continue",
      refusal: ["refused: redirected to a login page (…);", "the page requires a sign-in", "and nothing of it was served"], flag: "bad",
    }),
    body({
      id: "503", kind: "junk", shape: "badge",
      tx: PAGE.x + 20, ty: 12, w: 280, h: 26, drop: 0.4, side: 1,
      caption: "503 Service Unavailable", emitted: "503 Service Unavailable",
      refusal: ["HTTP 503 on the render: a failed side,", "not content"], flag: "bad",
    }),
    body({
      id: "spam", kind: "junk", shape: "links",
      tx: 34, ty: 380, w: 98, h: 84, drop: 0.55, side: -1,
      caption: "left: −9999px", emitted: "[casino] [slots] [bet now] [casino] …",
      refusal: ["off-screen, negative coordinates:", "dropped"], flag: "warn",
    }),
    body({
      id: "hidden", kind: "junk", shape: "hidden",
      tx: PAGE.x + 150, ty: 340, w: 150, h: 58, drop: 0.7, side: 1,
      caption: "display:none · 2,100 words", emitted: "Dear visitor, this dialog …",
      refusal: ["display:none: dropped;", "a reader never saw it"], flag: "warn",
    }),
  ];
}

const MARKDOWN: readonly string[] = [
  "## Documentation",
  "# Reading a page",
  "Point it at a website. Every public page …",
  "![figure](figure.png)",
  "Neither fetch alone is complete; …",
  "Blocks are matched by content and unioned.",
  "| board | pages | metric |",
  "Order is measured, not assumed.",
];

const GRAPH_NODES: ReadonlyArray<readonly [number, number, string]> = [
  [652, 96, "/"],
  [600, 56, "/docs"],
  [716, 50, "/api"],
  [742, 118, "/pricing"],
  [690, 154, "/about"],
  [612, 150, "/blog"],
];
const GRAPH_EDGES: ReadonlyArray<readonly [number, number]> = [
  [0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [1, 5], [2, 3], [4, 3],
];

export type Scene = {
  /** Overall scroll progress through the story, 0..1. */
  setProgress(p: number): void;
  /** Advance the simulation by `dt` seconds of wall clock. */
  step(dt: number): void;
  draw(ctx: CanvasRenderingContext2D, width: number, height: number, palette: Palette): void;
  /** True when nothing would change on the next frame, so the loop may idle. */
  settled(): boolean;
  /** Snap every body to the end state of `chapter`, for a still frame. */
  still(chapter: number): void;
  readonly chapter: number;
  /** How much of the "pain" is on the stage right now, 0..1 — the backdrop reads it. */
  readonly heat: number;
};

export function createScene(copy: StageCopy): Scene {
  const kept = keptBodies();
  const junk = junkBodies();
  const all = [...kept, ...junk];
  const rand = seeded(7);
  const wobble = new Map(all.map((b) => [b.id, (rand() - 0.5) * 2]));

  let chapter = 0;
  let t = 0.5;
  let time = 0;
  let started = false; // the hero drop has begun
  let heroStart = 0;

  function scanY(): number {
    if (chapter === 2) return PAGE.y + PAGE.h * clamp01((t - 0.3) / 0.5);
    if (chapter === 0) return PAGE.y + PAGE.h * ((time * 0.11) % 1);
    return chapter === 3 ? PAGE.y + PAGE.h : -1;
  }

  function wantsPresent(b: Body): boolean {
    if (b.kind === "kept") return started;
    if (chapter === 1) return t >= b.drop;
    if (chapter === 2) return scanY() < b.ty + 2 || t < 0.3;
    return false;
  }

  function setProgress(p: number): void {
    const u = clamp01(p) * 3;
    const c = Math.min(3, Math.max(0, Math.round(u)));
    chapter = c;
    t = clamp01(u - c + 0.5);
  }

  function spawnAbove(b: Body): void {
    b.x = b.tx + (wobble.get(b.id) ?? 0) * 6;
    b.y = b.ty - 260 - (b.order || 2) * 26;
    b.vx = 0;
    b.vy = 0;
    b.rot = (wobble.get(b.id) ?? 0) * 0.05;
    b.vrot = 0;
    b.falling = true;
    b.alpha = 0.001;
  }

  function step(dt: number): void {
    time += dt;
    if (!started) {
      started = true;
      heroStart = time;
      // The hero assembles: kept blocks drop in, one after another.
      for (const b of kept) spawnAbove(b);
    }
    const since = time - heroStart;

    for (const b of all) {
      const want = wantsPresent(b) && (b.kind === "junk" || since >= (b.order - 1) * 0.09);

      if (want && !b.present) {
        b.present = true;
        if (b.alpha < 0.05 && (chapter === 1 || b.kind === "kept")) spawnAbove(b);
        else {
          b.falling = false;
        }
      } else if (!want && b.present) {
        b.present = false;
        b.falling = false;
        if (chapter === 2) {
          // The scan refuses it: shoved off the page, tumbling.
          b.vx = b.side * (380 + Math.abs(wobble.get(b.id) ?? 0) * 160);
          b.vy = -160;
          b.vrot = b.side * (2.2 + (wobble.get(b.id) ?? 0));
        }
      }

      if (b.present) {
        if (b.alpha < 1) b.alpha = Math.min(1, b.alpha + dt * 5);
        if (b.falling) {
          b.vy += G * dt;
          b.y += b.vy * dt;
          b.x += (b.tx - b.x) * Math.min(1, dt * 6);
          b.rot += b.vrot * dt;
          if (b.y >= b.ty) {
            b.y = b.ty;
            b.vy = -b.vy * 0.26;
            b.vrot = (wobble.get(b.id) ?? 0) * 0.6;
            if (Math.abs(b.vy) < 60) {
              b.vy = 0;
              b.falling = false;
            }
          }
        } else {
          const ax = SPRING_K * (b.tx - b.x) - SPRING_C * b.vx;
          const ay = SPRING_K * (b.ty - b.y) - SPRING_C * b.vy;
          b.vx += ax * dt;
          b.vy += ay * dt;
          b.x += b.vx * dt;
          b.y += b.vy * dt;
          b.vrot += (-SPRING_K * b.rot - SPRING_C * b.vrot) * dt;
          b.rot += b.vrot * dt;
          if (Math.abs(b.vx) + Math.abs(b.vy) < 0.4 && Math.abs(b.tx - b.x) + Math.abs(b.ty - b.y) < 0.2) {
            b.x = b.tx;
            b.y = b.ty;
            b.vx = 0;
            b.vy = 0;
          }
          if (Math.abs(b.vrot) + Math.abs(b.rot) < 0.002) {
            b.rot = 0;
            b.vrot = 0;
          }
        }
      } else if (b.alpha > 0) {
        b.vy += G * 0.35 * dt;
        b.x += b.vx * dt;
        b.y += b.vy * dt;
        b.rot += b.vrot * dt;
        b.alpha = Math.max(0, b.alpha - dt * (Math.abs(b.vx) > 1 ? 1.6 : 4));
        if (b.alpha === 0) {
          b.x = b.tx;
          b.y = b.ty;
          b.vx = 0;
          b.vy = 0;
          b.rot = 0;
          b.vrot = 0;
        }
      }
    }
  }

  function settled(): boolean {
    if (chapter === 0 || chapter === 3) return false; // ambient motion: scan loop, particles
    return all.every(
      (b) =>
        !b.falling &&
        (b.alpha === 0 || b.alpha === 1) &&
        Math.abs(b.vx) + Math.abs(b.vy) + Math.abs(b.vrot) === 0,
    );
  }

  function still(c: number): void {
    chapter = c;
    t = 1;
    started = true;
    time = 6;
    heroStart = 0;
    for (const b of all) {
      const want = wantsPresent(b);
      b.present = want;
      b.alpha = want ? 1 : 0;
      b.falling = false;
      b.x = b.tx;
      b.y = b.ty;
      b.vx = b.vy = b.rot = b.vrot = 0;
    }
  }

  // ---------------------------------------------------------------- drawing

  type Ctx = CanvasRenderingContext2D;

  function rr(ctx: Ctx, x: number, y: number, w: number, h: number, r: number): void {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
  }

  function text(
    ctx: Ctx,
    pal: Palette,
    s: string,
    x: number,
    y: number,
    size: number,
    color: string,
    font: "mono" | "sans" = "mono",
    weight = 500,
    align: CanvasTextAlign = "left",
  ): void {
    ctx.font = `${weight} ${size}px ${font === "mono" ? pal.mono : pal.sans}`;
    ctx.fillStyle = color;
    ctx.textAlign = align;
    ctx.textBaseline = "alphabetic";
    ctx.fillText(s, x, y);
  }

  function withAlpha(hex: string, a: number): string {
    // Tokens arrive as #rrggbb or rgb(...) — color-mix keeps either.
    return `color-mix(in srgb, ${hex} ${Math.round(a * 100)}%, transparent)`;
  }

  function drawPageFrame(ctx: Ctx, pal: Palette, dx = 0, dashed = false, color?: string, alpha = 1): void {
    ctx.save();
    ctx.globalAlpha = alpha;
    rr(ctx, PAGE.x + dx, PAGE.y, PAGE.w, PAGE.h, 8);
    if (!dashed) {
      ctx.fillStyle = pal.surface;
      ctx.fill();
    }
    ctx.lineWidth = dashed ? 1.5 : 1;
    ctx.setLineDash(dashed ? [5, 4] : []);
    ctx.strokeStyle = color ?? pal.ruleStrong;
    ctx.stroke();
    ctx.setLineDash([]);
    if (!dashed) {
      // address strip
      ctx.strokeStyle = pal.rule;
      ctx.beginPath();
      ctx.moveTo(PAGE.x + dx, PAGE.y + 22);
      ctx.lineTo(PAGE.x + dx + PAGE.w, PAGE.y + 22);
      ctx.stroke();
      text(ctx, pal, "example.org/docs/reading-a-page", PAGE.x + dx + 12, PAGE.y + 15, 9, pal.faint);
    }
    ctx.restore();
  }

  function lines(ctx: Ctx, x: number, y: number, w: number, h: number, color: string, gap = 9, missing = false, warn = ""): void {
    const n = Math.max(1, Math.floor((h + 3) / gap));
    for (let i = 0; i < n; i++) {
      const lw = i === n - 1 ? w * 0.58 : w * (0.86 + (((i * 37) % 10) / 100) * 1.4);
      if (missing && i % 2 === 1) {
        ctx.fillStyle = warn;
        ctx.globalAlpha *= 0.55;
        rr(ctx, x, y + i * gap, lw * 0.22, 4, 2);
        ctx.fill();
        ctx.globalAlpha /= 0.55;
        continue;
      }
      ctx.fillStyle = color;
      rr(ctx, x, y + i * gap, lw, 4, 2);
      ctx.fill();
    }
  }

  function drawKept(ctx: Ctx, pal: Palette, b: Body, numbered: boolean, missing: boolean): void {
    ctx.save();
    ctx.globalAlpha = b.alpha;
    ctx.translate(b.x + b.w / 2, b.y + b.h / 2);
    ctx.rotate(b.rot);
    ctx.translate(-b.w / 2, -b.h / 2);
    const bar = pal.dark ? withAlpha(pal.ink, 0.28) : withAlpha(pal.ink, 0.22);
    switch (b.shape) {
      case "nav": {
        let x = 0;
        for (const w of [34, 28, 40, 30]) {
          ctx.fillStyle = bar;
          rr(ctx, x, 4, w, 10, 5);
          ctx.fill();
          x += w + 10;
        }
        ctx.fillStyle = pal.accent;
        rr(ctx, b.w - 42, 2, 42, 14, 7);
        ctx.fill();
        break;
      }
      case "h1":
        ctx.fillStyle = withAlpha(pal.ink, 0.86);
        rr(ctx, 0, 0, b.w, 12, 3);
        ctx.fill();
        rr(ctx, 0, 20, b.w * 0.62, 12, 3);
        ctx.fill();
        break;
      case "text":
        lines(ctx, 0, 0, b.w, b.h, bar, 9, missing, pal.warn);
        if (missing) text(ctx, pal, "needed a browser", 0, b.h + 9, 8, pal.warn);
        break;
      case "image":
        ctx.fillStyle = pal.sunk;
        rr(ctx, 0, 0, b.w, b.h, 4);
        ctx.fill();
        ctx.strokeStyle = pal.faint;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(8, b.h - 12);
        ctx.lineTo(b.w * 0.36, b.h * 0.42);
        ctx.lineTo(b.w * 0.55, b.h * 0.66);
        ctx.lineTo(b.w * 0.72, b.h * 0.5);
        ctx.lineTo(b.w - 8, b.h - 12);
        ctx.stroke();
        ctx.fillStyle = pal.faint;
        ctx.beginPath();
        ctx.arc(b.w * 0.76, b.h * 0.26, 6, 0, Math.PI * 2);
        ctx.fill();
        break;
      case "table": {
        ctx.fillStyle = pal.sunk;
        rr(ctx, 0, 0, b.w, 16, 3);
        ctx.fill();
        ctx.strokeStyle = pal.rule;
        ctx.lineWidth = 1;
        for (let r = 1; r < 5; r++) {
          ctx.beginPath();
          ctx.moveTo(0, r * 15.5);
          ctx.lineTo(b.w, r * 15.5);
          ctx.stroke();
        }
        for (let c = 1; c < 4; c++) {
          ctx.beginPath();
          ctx.moveTo((b.w / 4) * c, 0);
          ctx.lineTo((b.w / 4) * c, b.h);
          ctx.stroke();
        }
        ctx.fillStyle = bar;
        for (let r = 0; r < 5; r++)
          for (let c = 0; c < 4; c++) {
            rr(ctx, (b.w / 4) * c + 6, r * 15.5 + 6, (b.w / 4) * (c === 0 ? 0.6 : 0.4), 4, 2);
            ctx.fill();
          }
        break;
      }
      default:
        break;
    }
    ctx.restore();

    if (numbered && b.alpha > 0.5) {
      ctx.save();
      ctx.globalAlpha = b.alpha;
      ctx.fillStyle = pal.accent;
      ctx.beginPath();
      ctx.arc(b.x - 11, b.y + 7, 7, 0, Math.PI * 2);
      ctx.fill();
      text(ctx, pal, String(b.order), b.x - 11, b.y + 10.5, 9, pal.dark ? pal.ground : pal.inverse, "mono", 700, "center");
      ctx.restore();
    }
  }

  function drawJunk(ctx: Ctx, pal: Palette, b: Body): void {
    if (b.alpha <= 0) return;
    const c = b.flag === "bad" ? pal.bad : pal.warn;
    ctx.save();
    ctx.globalAlpha = b.alpha;
    ctx.translate(b.x + b.w / 2, b.y + b.h / 2);
    ctx.rotate(b.rot);
    ctx.translate(-b.w / 2, -b.h / 2);
    ctx.lineWidth = 1.5;
    switch (b.shape) {
      case "banner":
        ctx.fillStyle = pal.surface;
        rr(ctx, 0, 0, b.w, b.h, 6);
        ctx.fill();
        ctx.fillStyle = withAlpha(c, 0.14);
        ctx.fill();
        ctx.strokeStyle = c;
        ctx.stroke();
        text(ctx, pal, b.caption, 14, 24, 10, c, "sans", 700);
        lines(ctx, 14, 32, b.w * 0.5, 12, withAlpha(c, 0.45), 8);
        ctx.fillStyle = c;
        rr(ctx, b.w - 96, 22, 82, 22, 5);
        ctx.fill();
        text(ctx, pal, "Accept all", b.w - 55, 37, 9, pal.dark ? pal.ground : pal.inverse, "sans", 700, "center");
        break;
      case "modal":
        ctx.fillStyle = pal.surface;
        rr(ctx, 0, 0, b.w, b.h, 8);
        ctx.fill();
        ctx.fillStyle = withAlpha(c, 0.1);
        ctx.fill();
        ctx.strokeStyle = c;
        ctx.stroke();
        text(ctx, pal, b.caption, 16, 28, 11, c, "sans", 700);
        ctx.strokeStyle = withAlpha(c, 0.7);
        ctx.lineWidth = 1;
        rr(ctx, 16, 44, b.w - 32, 20, 4);
        ctx.stroke();
        rr(ctx, 16, 70, b.w - 32, 20, 4);
        ctx.stroke();
        ctx.fillStyle = c;
        rr(ctx, 16, 98, b.w - 32, 20, 4);
        ctx.fill();
        text(ctx, pal, "Sign in", b.w / 2, 112, 9, pal.dark ? pal.ground : pal.inverse, "sans", 700, "center");
        break;
      case "badge":
        ctx.fillStyle = c;
        rr(ctx, 0, 0, b.w, b.h, 5);
        ctx.fill();
        text(ctx, pal, b.caption, b.w / 2, 17, 11, pal.dark ? pal.ground : pal.inverse, "mono", 700, "center");
        break;
      case "links": {
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = c;
        ctx.lineWidth = 1;
        for (let i = 0; i < 8; i++) {
          const col = i % 2;
          const row = Math.floor(i / 2);
          rr(ctx, col * 50, row * 19, 44, 12, 6);
          ctx.stroke();
        }
        ctx.setLineDash([]);
        text(ctx, pal, b.caption, 0, b.h + 10, 8, c);
        break;
      }
      case "hidden":
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = c;
        rr(ctx, 0, 0, b.w, b.h, 5);
        ctx.stroke();
        ctx.setLineDash([]);
        lines(ctx, 10, 10, b.w - 20, b.h - 24, withAlpha(c, 0.4), 8);
        text(ctx, pal, b.caption, 10, b.h - 5, 8, c);
        break;
      default:
        break;
    }
    ctx.restore();
  }

  function drawOutput(ctx: Ctx, pal: Palette, sinceHero: number): void {
    const x = OUT.x;
    // Chapter 1: what a naive extractor emitted, in oxide red.
    if (chapter === 1) {
      text(ctx, pal, "WHAT YOUR AI GOT", x, 74, 9, pal.bad, "sans", 700);
      let y = 98;
      for (const b of junk) {
        if (b.alpha <= 0.02) continue;
        ctx.globalAlpha = b.alpha;
        text(ctx, pal, "> " + b.emitted, x, y, 11, pal.bad);
        y += 22;
      }
      ctx.globalAlpha = 1;
      const missingOn = kept.some((b) => b.missing && b.alpha > 0.5);
      if (missingOn && t > 0.62) {
        text(ctx, pal, "> … 41% of the words. The rest needed a browser.", x, y + 6, 10, pal.warn);
      }
      return;
    }

    // Chapter 2: refusals, in the engine's words, beside where the scan found them.
    if (chapter === 2) {
      const sy = scanY();
      for (const b of junk) {
        if (t < 0.3 || sy < b.ty + 2) continue;
        const c = b.flag === "bad" ? pal.bad : pal.warn;
        const yy = Math.max(70, Math.min(VH - 40, b.ty + 12));
        b.refusal.forEach((line, i) => text(ctx, pal, line, x, yy + i * 13, 9.5, c));
      }
      if (t >= 0.3) {
        text(ctx, pal, "READING ORDER", x, VH - 78, 9, pal.accentInk, "sans", 700);
        text(ctx, pal, "measured by XY-cut over the boxes", x, VH - 62, 9.5, pal.muted);
        text(ctx, pal, "columns stay columns", x, VH - 48, 9.5, pal.muted);
      }
      return;
    }

    // Chapters 0 and 3: Markdown, typed in reading order, numbered like the blocks.
    const typing = chapter === 3 ? clamp01((t - 0.02) / 0.5) : clamp01((sinceHero - 1.0) / 1.8);
    if (typing <= 0) return;
    const shown = typing * MARKDOWN.length;
    text(ctx, pal, "content.md", x, 74, 9, pal.faint);
    let y = 98;
    MARKDOWN.forEach((line, i) => {
      const f = clamp01(shown - i);
      if (f <= 0) return;
      const n = Math.ceil(line.length * f);
      ctx.fillStyle = pal.accent;
      ctx.beginPath();
      ctx.arc(x + 5, y - 4, 5, 0, Math.PI * 2);
      ctx.fill();
      text(ctx, pal, String(i + 1), x + 5, y - 1, 7.5, pal.dark ? pal.ground : pal.inverse, "mono", 700, "center");
      text(ctx, pal, line.slice(0, n) + (f < 1 ? "▌" : ""), x + 16, y, 10.5, line.startsWith("#") ? pal.ink : pal.muted);
      y += 20;
    });
  }

  function drawGraph(ctx: Ctx, pal: Palette, grow: number, phase: number): void {
    if (grow <= 0) return;
    ctx.save();
    ctx.translate(0, 190);
    const g = ease(grow);
    const [hx, hy] = GRAPH_NODES[0] ?? [0, 0, ""];
    GRAPH_EDGES.forEach(([a, b], i) => {
      const na = GRAPH_NODES[a];
      const nb = GRAPH_NODES[b];
      if (!na || !nb) return;
      const f = clamp01(g * 1.6 - i * 0.08);
      if (f <= 0) return;
      const ax = hx + (na[0] - hx) * g;
      const ay = hy + (na[1] - hy) * g;
      const bx = ax + (hx + (nb[0] - hx) * g - ax) * f;
      const by = ay + (hy + (nb[1] - hy) * g - ay) * f;
      ctx.strokeStyle = withAlpha(pal.accent, 0.45);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
      ctx.stroke();
      if (f >= 1) {
        // an edge particle
        const p = (phase * 0.35 + i * 0.13) % 1;
        ctx.fillStyle = pal.accent;
        ctx.beginPath();
        ctx.arc(ax + (bx - ax) * p, ay + (by - ay) * p, 1.6, 0, Math.PI * 2);
        ctx.fill();
      }
    });
    GRAPH_NODES.forEach(([nx, ny, label], i) => {
      const x = hx + (nx - hx) * g;
      const y = hy + (ny - hy) * g;
      const r = i === 0 ? 7 : 4.5;
      ctx.fillStyle = withAlpha(pal.accent, 0.18 + 0.1 * Math.sin(phase * 2 + i));
      ctx.beginPath();
      ctx.arc(x, y, r * 2.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = i === 0 ? pal.accent : pal.surface;
      ctx.strokeStyle = pal.accent;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      if (g > 0.85) text(ctx, pal, label, x + r + 4, y + 3, 8.5, pal.muted);
    });
    ctx.restore();
  }

  function drawReport(ctx: Ctx, pal: Palette, f: number): void {
    if (f <= 0) return;
    const e = ease(f);
    const x = OUT.x;
    const y = 428 + (1 - e) * 50;
    const h = 126;
    ctx.save();
    ctx.globalAlpha = e;
    ctx.fillStyle = pal.surface;
    rr(ctx, x, y, OUT.w, h, 6);
    ctx.fill();
    ctx.strokeStyle = pal.ruleStrong;
    ctx.lineWidth = 1;
    ctx.stroke();
    text(ctx, pal, "SITE TRUTH REPORT · COMING SOON", x + 14, y + 20, 8, pal.muted, "sans", 700);
    text(ctx, pal, "what the site hides", x + 14, y + 38, 12, pal.ink, "sans", 700);
    ctx.strokeStyle = pal.rule;
    copy.report.forEach(([label, value], i) => {
      const yy = y + 60 + i * 21;
      text(ctx, pal, label, x + 14, yy, 9, pal.muted, "sans", 600);
      text(ctx, pal, value, x + OUT.w - 14, yy, 9, pal.ink, "mono", 500, "right");
      ctx.beginPath();
      ctx.moveTo(x + 14, yy + 7);
      ctx.lineTo(x + OUT.w - 14, yy + 7);
      ctx.stroke();
    });
    ctx.restore();
  }

  function drawChip(ctx: Ctx, pal: Palette, f: number): void {
    if (f <= 0) return;
    const e = ease(f);
    ctx.save();
    ctx.globalAlpha = e;
    ctx.font = `500 9.5px ${pal.mono}`;
    const w = ctx.measureText(copy.fidelity).width + 24;
    const x = OUT.x;
    const y = 30 + (1 - e) * -8;
    ctx.fillStyle = pal.accentSoft;
    rr(ctx, x, y, w, 22, 11);
    ctx.fill();
    ctx.fillStyle = pal.accent;
    ctx.beginPath();
    ctx.arc(x + 12, y + 11, 3, 0, Math.PI * 2);
    ctx.fill();
    text(ctx, pal, copy.fidelity, x + 20, y + 15, 9.5, pal.accentInk);
    ctx.restore();
  }

  function draw(ctx: Ctx, width: number, height: number, pal: Palette): void {
    ctx.clearRect(0, 0, width, height);
    const s = Math.min(width / VW, height / VH);
    ctx.save();
    ctx.translate((width - VW * s) / 2, (height - VH * s) / 2);
    ctx.scale(s, s);

    const sinceHero = started ? time - heroStart : 0;
    const sy = scanY();
    const converging = chapter === 2 && t < 0.3;

    // The two fetches converge on the page.
    if (chapter === 2 && t < 0.42) {
      const f = ease(t / 0.3);
      const fade = t < 0.3 ? 1 : 1 - (t - 0.3) / 0.12;
      const dx = (1 - f) * 240;
      drawPageFrame(ctx, pal, -dx, true, pal.accentInk, fade * 0.9);
      drawPageFrame(ctx, pal, dx, true, pal.accent, fade * 0.9);
      ctx.save();
      ctx.globalAlpha = fade;
      text(ctx, pal, "plain fetch", PAGE.x - dx + 12, PAGE.y - 8, 9, pal.accentInk);
      text(ctx, pal, "Chromium · 1440×900", PAGE.x + dx + PAGE.w - 12, PAGE.y - 8, 9, pal.accent, "mono", 500, "right");
      ctx.restore();
    }

    drawPageFrame(ctx, pal);

    // Kept blocks. Numbered once the scan has passed them (chapter 2), or when the page is read.
    for (const b of kept) {
      const passed = chapter === 2 ? t >= 0.3 && sy >= b.ty + 4 : chapter === 3 || (chapter === 0 && sinceHero > 1.1);
      const missing = b.missing && (chapter === 1 ? t > 0.5 : chapter === 2 && (!passed || t < 0.3));
      drawKept(ctx, pal, b, passed && !converging, missing);
    }

    // XY-cut: the hairlines the scan leaves behind.
    if (chapter === 2 && t >= 0.3) {
      ctx.save();
      ctx.strokeStyle = withAlpha(pal.accent, 0.4);
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 3]);
      for (const cutY of [156, 212, 328, 408, 504]) {
        if (sy < cutY) continue;
        ctx.beginPath();
        ctx.moveTo(PAGE.x + 8, cutY);
        ctx.lineTo(PAGE.x + PAGE.w - 8, cutY);
        ctx.stroke();
      }
      if (sy > 330) {
        ctx.beginPath();
        ctx.moveTo(PAGE.x + 20 + 136, 216);
        ctx.lineTo(PAGE.x + 20 + 136, 324);
        ctx.stroke();
      }
      ctx.restore();
    }

    for (const b of junk) drawJunk(ctx, pal, b);

    // The scan line.
    if ((chapter === 2 && t >= 0.3 && t < 0.86) || chapter === 0) {
      const a = chapter === 0 ? 0.35 : 1;
      const grad = ctx.createLinearGradient(0, sy - 46, 0, sy);
      grad.addColorStop(0, withAlpha(pal.accent, 0));
      grad.addColorStop(1, withAlpha(pal.accent, 0.16 * a));
      ctx.fillStyle = grad;
      ctx.fillRect(PAGE.x + 1, sy - 46, PAGE.w - 2, 46);
      ctx.strokeStyle = withAlpha(pal.accent, a);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(PAGE.x - 6, sy);
      ctx.lineTo(PAGE.x + PAGE.w + 6, sy);
      ctx.stroke();
    }

    drawOutput(ctx, pal, sinceHero);

    if (chapter === 3) {
      drawChip(ctx, pal, (t - 0.5) / 0.2);
      drawGraph(ctx, pal, (t - 0.4) / 0.35, time);
      drawReport(ctx, pal, (t - 0.62) / 0.25);
    } else if (chapter === 0) {
      drawGraph(ctx, pal, (sinceHero - 2.4) / 1.2, time);
    }

    ctx.restore();
  }

  return {
    setProgress,
    step,
    draw,
    settled,
    still,
    get chapter() {
      return chapter;
    },
    get heat() {
      if (chapter === 1) return clamp01(0.35 + t);
      if (chapter === 2) return clamp01(1 - (t - 0.2) / 0.6);
      return 0;
    },
  };
}
