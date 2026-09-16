"use client";

import { useEffect } from "react";

/**
 * Scroll reveals and count-ups for the landing, in one observer.
 *
 * Renders nothing. On mount it stamps `data-motion` on the page's `main`, which is the only
 * thing that lets the stylesheet hide a `[data-reveal]` element; without JavaScript, or under
 * `prefers-reduced-motion`, nothing is ever hidden. Each element is revealed once, when a
 * fifth of it is on screen; `[data-count]` numbers inside it count up from zero to the value
 * that was server-rendered, keeping that value's own decimals and suffix.
 */
export default function Motion() {
  useEffect(() => {
    const main = document.querySelector("main");
    if (!main || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    main.dataset.motion = "";

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const el = entry.target as HTMLElement;
          el.dataset.in = "";
          io.unobserve(el);
          el.querySelectorAll<HTMLElement>("[data-count]").forEach(countUp);
        }
      },
      { threshold: 0.2, rootMargin: "0px 0px -8% 0px" },
    );
    main.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el) => io.observe(el));

    return () => {
      io.disconnect();
      delete main.dataset.motion;
    };
  }, []);

  return null;
}

/** "0.862" → counts 0.000 → 0.862; "98.1%" keeps its one decimal and its sign. */
function countUp(el: HTMLElement): void {
  const final = el.textContent ?? "";
  const match = /^([^\d]*)(\d[\d,]*)(\.(\d+))?(.*)$/.exec(final.trim());
  if (!match) return;
  const [, prefix = "", whole = "0", , frac, suffix = ""] = match;
  const target = Number(whole.replace(/,/g, "") + (frac ? `.${frac}` : ""));
  if (!Number.isFinite(target)) return;
  const decimals = frac?.length ?? 0;
  const grouped = whole.includes(",");
  const duration = 1100;
  const start = performance.now();
  const frame = (now: number) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    const value = target * eased;
    el.textContent =
      prefix +
      (grouped ? value.toLocaleString("en", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : value.toFixed(decimals)) +
      suffix;
    if (t < 1) requestAnimationFrame(frame);
    else el.textContent = final;
  };
  requestAnimationFrame(frame);
}
