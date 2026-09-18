"use client";

import { useEffect, useState } from "react";
import type { CSSProperties, RefObject } from "react";

/**
 * How every animated step runs its cycle: *triggered*, not mount-timed. The loop plays
 * only while its step is current (`active`, from `HowMotion`'s step) *and* the element is
 * actually in view (an `IntersectionObserver` on `ref`), and each time that becomes true
 * every animation under `ref` is seeked back to time zero through the Web Animations API
 * -- so a reader arriving at a step always sees its story from the top, not whatever
 * phase a free-running loop happened to be in -- then cycles for as long as it holds.
 *
 * Returns `loop(name)`: the inline style that points an element at one of the step's
 * generated `@keyframes` on the shared cycle (`{}` under `reduced`, so the element simply
 * shows its resting markup).
 */
export function useTriggeredLoop(ref: RefObject<HTMLElement | null>, cycleMs: number, { reduced = false, active = true } = {}) {
  const [inView, setInView] = useState(false);
  const playing = !reduced && active && inView;

  useEffect(() => {
    if (reduced) return;
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => setInView(!!entry?.isIntersecting), { threshold: 0.2 });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, reduced]);

  useEffect(() => {
    if (!playing || !ref.current) return;
    for (const el of ref.current.querySelectorAll("*")) {
      for (const anim of el.getAnimations()) anim.currentTime = 0;
    }
  }, [playing, ref]);

  const dur = `${Math.round(cycleMs)}ms`;
  const loop = (name: string): CSSProperties =>
    reduced
      ? {}
      : { animationName: name, animationDuration: dur, animationIterationCount: "infinite", animationPlayState: playing ? "running" : "paused" };

  return { playing, loop };
}
