"use client";

import { useEffect, useRef, useState } from "react";

import { createScene, type Palette, type StageCopy, VH, VW } from "./scene/scene";

/**
 * The stage's canvas. Mounts over the server-rendered still (`StoryStill`) once JavaScript
 * runs, and only then: without it, or under `prefers-reduced-motion`, the still stays. The
 * reduced-motion path draws the scene too, as four still frames — a comic strip — rather
 * than animating it.
 *
 * The chapter comes from which copy panel of the enclosing `[data-story]` section is level
 * with the stage. The loop runs only while the canvas is on screen and something is moving;
 * the palette is read from the CSS tokens so the scene follows the theme toggle.
 */
const REDUCE = "(prefers-reduced-motion: reduce)";

function readPalette(): Palette {
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string) => cs.getPropertyValue(name).trim();
  return {
    ink: v("--ink"),
    muted: v("--muted"),
    faint: v("--faint"),
    rule: v("--rule"),
    ruleStrong: v("--rule-strong"),
    accent: v("--accent"),
    accentInk: v("--accent-ink"),
    accentSoft: v("--accent-soft"),
    warn: v("--warn"),
    bad: v("--bad"),
    surface: v("--surface"),
    sunk: v("--sunk"),
    ground: v("--ground"),
    inverse: v("--inverse"),
    sans: getComputedStyle(document.body).fontFamily,
    mono: v("--font-mono-stack") || "ui-monospace, monospace",
    dark: cs.colorScheme.includes("dark"),
  };
}

/** Re-runs `fn` when the theme attribute or the system scheme changes. */
function onThemeChange(fn: () => void): () => void {
  const mo = new MutationObserver(fn);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
  const mq = matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", fn);
  return () => {
    mo.disconnect();
    mq.removeEventListener("change", fn);
  };
}

function fitCanvas(canvas: HTMLCanvasElement): { w: number; h: number } | null {
  const rect = canvas.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2) return null;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = Math.round(rect.width * dpr);
  const h = Math.round(rect.height * dpr);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  return { w, h };
}

export default function Stage({ copy }: { copy: StageCopy }) {
  const [mode, setMode] = useState<"still" | "live" | "strip">("still");

  useEffect(() => {
    const mq = matchMedia(REDUCE);
    const pick = () => setMode(mq.matches ? "strip" : "live");
    pick();
    mq.addEventListener("change", pick);
    return () => mq.removeEventListener("change", pick);
  }, []);

  if (mode === "still") return null;
  return mode === "strip" ? <Strip copy={copy} /> : <Live copy={copy} />;
}

function Live({ copy }: { copy: StageCopy }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const story = canvas.closest<HTMLElement>("[data-story]");
    const stage = canvas.closest<HTMLElement>(".story-stage");
    if (!story || !stage) return;

    const scene = createScene(copy);
    stage.dataset.stage = "live";
    let palette = readPalette();
    let intersecting = false;
    let visible = false;
    let dirty = true;
    let last = 0;
    let frame = 0;
    let lastChapter = -1;

    const panels = Array.from(story.querySelectorAll<HTMLElement>("[data-panel]"));

    // Which panel is on the stage: the one under a reference line — the stage's middle
    // when the stage stands beside the copy, or a line just below it when it is a band
    // above the copy (phones). `t` is how far that line has travelled down the panel; the
    // last panel is centred when the section ends, so it plays out over its upper half.
    const progress = () => {
      const s = stage.getBoundingClientRect();
      const band = s.width > story.getBoundingClientRect().width * 0.8;
      const ref = band ? s.bottom + (window.innerHeight - s.bottom) * 0.4 : s.top + s.height / 2;
      let chapter = 0;
      let t = 0;
      panels.forEach((panel, i) => {
        const r = panel.getBoundingClientRect();
        if (ref >= r.top) {
          chapter = i;
          t = (ref - r.top) / Math.max(1, r.height);
        }
      });
      if (chapter === panels.length - 1 && !band) t *= 2;
      scene.setChapter(chapter, t);
      if (scene.chapter !== lastChapter) {
        lastChapter = scene.chapter;
        story.dataset.chapter = String(lastChapter);
      }
      stage.style.setProperty("--story-heat", scene.heat.toFixed(3));
    };

    const tick = (now: number) => {
      frame = 0;
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 1 / 60;
      last = now;
      scene.step(dt);
      const size = fitCanvas(canvas);
      if (size) scene.draw(ctx, size.w, size.h, palette);
      dirty = false;
      if (visible && (!scene.settled() || dirty)) frame = requestAnimationFrame(tick);
      else last = 0;
    };
    const wake = () => {
      dirty = true;
      if (visible && !frame) frame = requestAnimationFrame(tick);
    };

    const onScroll = () => {
      progress();
      wake();
    };
    const io = new IntersectionObserver(
      ([entry]) => {
        intersecting = Boolean(entry?.isIntersecting);
        visible = intersecting && document.visibilityState === "visible";
        if (visible) wake();
      },
      { threshold: 0.02 },
    );
    io.observe(canvas);
    const ro = new ResizeObserver(wake);
    ro.observe(canvas);
    const offTheme = onThemeChange(() => {
      palette = readPalette();
      wake();
    });
    const onVisibility = () => {
      visible = intersecting && document.visibilityState === "visible";
      wake();
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    document.addEventListener("visibilitychange", onVisibility);
    progress();
    // Fonts first, so the first typed line is not drawn in the fallback face.
    document.fonts?.ready.then(wake).catch(() => wake());
    wake();

    return () => {
      delete stage.dataset.stage;
      if (frame) cancelAnimationFrame(frame);
      io.disconnect();
      ro.disconnect();
      offTheme();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [copy]);

  return <canvas ref={ref} aria-hidden className="absolute inset-0 size-full" />;
}

/** Reduced motion: the four chapters as still frames, drawn once and on theme change. */
function Strip({ copy }: { copy: StageCopy }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const stage = root.closest<HTMLElement>(".story-stage");
    if (stage) stage.dataset.stage = "strip";
    const canvases = Array.from(root.querySelectorAll("canvas"));
    const scene = createScene(copy);
    const paint = () => {
      const palette = readPalette();
      canvases.forEach((canvas, i) => {
        const ctx = canvas.getContext("2d");
        const size = fitCanvas(canvas);
        if (!ctx || !size) return;
        scene.still(i);
        scene.draw(ctx, size.w, size.h, palette);
      });
    };
    const ro = new ResizeObserver(paint);
    ro.observe(root);
    const offTheme = onThemeChange(paint);
    document.fonts?.ready.then(paint).catch(() => paint());
    paint();
    return () => {
      if (stage) delete stage.dataset.stage;
      ro.disconnect();
      offTheme();
    };
  }, [copy]);

  return (
    <div ref={ref} aria-hidden className="absolute inset-0 grid grid-cols-2 grid-rows-2 gap-2 p-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="relative min-h-0 rounded-md border border-rule">
          <canvas className="absolute inset-0 size-full" style={{ aspectRatio: `${VW} / ${VH}` }} />
          <span className="absolute left-2 top-1.5 font-mono text-label font-medium text-faint">
            {String(i + 1).padStart(2, "0")}
          </span>
        </div>
      ))}
    </div>
  );
}
