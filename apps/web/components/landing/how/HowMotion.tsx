"use client";

import { useEffect } from "react";

/**
 * Behaviour for the "how it reads a page" panel. Renders nothing; attaches to the
 * server-rendered `[data-how]` panel:
 *
 * - the steps are `<details>`: one open at a time, and the open one is the panel's
 *   `data-step`, which the stylesheet turns into the scene's cross-morph;
 * - while the panel is on screen and untouched, the steps advance every few seconds
 *   (`data-auto` runs the progress line under the open step); a click or a key stops that;
 * - the scene's `.par` groups follow the pointer a few pixels, on a damped spring, by depth.
 *
 * Under `prefers-reduced-motion` the accordion still works and nothing else runs.
 */
const AUTO_MS = 6500;

export default function HowMotion() {
  useEffect(() => {
    const panel = document.querySelector<HTMLElement>("[data-how]");
    if (!panel) return;
    const steps = Array.from(panel.querySelectorAll<HTMLDetailsElement>("details[data-step-id]"));
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const cleanups: Array<() => void> = [];

    // -- the accordion ---------------------------------------------------------------
    let opening = false;
    const show = (step: HTMLDetailsElement) => {
      opening = true;
      for (const other of steps) if (other !== step && other.open) other.open = false;
      if (!step.open) step.open = true;
      panel.dataset.step = step.dataset.stepId;
      opening = false;
    };
    for (const step of steps) {
      const onToggle = () => {
        if (opening) return;
        if (step.open) show(step);
      };
      step.addEventListener("toggle", onToggle);
      cleanups.push(() => step.removeEventListener("toggle", onToggle));
    }
    panel.dataset.step = steps.find((s) => s.open)?.dataset.stepId ?? "1";

    // -- auto-advance while on screen and untouched -------------------------------------
    let timer = 0;
    let touched = reduce;
    let visible = false;
    const stop = () => {
      window.clearTimeout(timer);
      timer = 0;
      delete panel.dataset.auto;
    };
    const arm = () => {
      stop();
      if (touched || !visible || document.hidden) return;
      panel.dataset.auto = "";
      timer = window.setTimeout(() => {
        const at = steps.findIndex((s) => s.open);
        const next = steps[(at + 1) % steps.length];
        if (next) show(next);
        arm();
      }, AUTO_MS);
    };
    const onTouch = () => {
      touched = true;
      stop();
    };
    panel.addEventListener("pointerdown", onTouch);
    panel.addEventListener("keydown", onTouch);
    cleanups.push(() => {
      panel.removeEventListener("pointerdown", onTouch);
      panel.removeEventListener("keydown", onTouch);
    });
    const io = new IntersectionObserver(
      ([entry]) => {
        visible = entry?.isIntersecting ?? false;
        if (visible) arm();
        else stop();
      },
      { threshold: 0.35 },
    );
    io.observe(panel);
    cleanups.push(() => io.disconnect());
    const onVis = () => (document.hidden ? stop() : arm());
    document.addEventListener("visibilitychange", onVis);
    cleanups.push(() => document.removeEventListener("visibilitychange", onVis));

    // -- pointer parallax ----------------------------------------------------------------
    if (!reduce) {
      const layers = Array.from(panel.querySelectorAll<SVGGElement>(".par")).map((el) => ({
        el,
        d: Number(el.dataset.d ?? 1),
      }));
      let tx = 0, ty = 0, x = 0, y = 0, vx = 0, vy = 0, raf = 0, last = 0;
      const tick = (now: number) => {
        const dt = Math.min(0.05, (now - last) / 1000 || 0.016);
        last = now;
        // A damped spring toward the target: ω 7, ζ 0.9.
        const w = 7, z = 0.9;
        vx += (-2 * z * w * vx - w * w * (x - tx)) * dt;
        vy += (-2 * z * w * vy - w * w * (y - ty)) * dt;
        x += vx * dt;
        y += vy * dt;
        for (const { el, d } of layers) el.style.transform = `translate(${(x * 9 * d).toFixed(2)}px, ${(y * 6 * d).toFixed(2)}px)`;
        const settled = Math.abs(x - tx) < 0.002 && Math.abs(y - ty) < 0.002 && Math.abs(vx) < 0.01 && Math.abs(vy) < 0.01;
        raf = settled ? 0 : requestAnimationFrame(tick);
      };
      const wake = () => {
        if (!raf) {
          last = performance.now();
          raf = requestAnimationFrame(tick);
        }
      };
      const onMove = (e: PointerEvent) => {
        const r = panel.getBoundingClientRect();
        tx = ((e.clientX - r.left) / r.width) * 2 - 1;
        ty = ((e.clientY - r.top) / r.height) * 2 - 1;
        wake();
      };
      const onLeave = () => {
        tx = 0;
        ty = 0;
        wake();
      };
      panel.addEventListener("pointermove", onMove);
      panel.addEventListener("pointerleave", onLeave);
      cleanups.push(() => {
        panel.removeEventListener("pointermove", onMove);
        panel.removeEventListener("pointerleave", onLeave);
        cancelAnimationFrame(raf);
      });
    }

    return () => {
      stop();
      for (const fn of cleanups) fn();
    };
  }, []);

  return null;
}
