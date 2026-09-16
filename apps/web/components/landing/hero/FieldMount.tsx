"use client";

import { useEffect, useRef } from "react";

/**
 * Mounts the live field over the hero's still. Two canvases: the back one draws the sky,
 * the ground, the plinth and every page behind it; the front one, sized to the frame's
 * lower half and above the card in the stacking order, draws only the pages between the
 * camera and the plinth, so they overlap the card's foot. The renderer is a separate chunk,
 * imported here so the page's own JavaScript carries none of it.
 *
 * Reduced motion draws one frame and stops. No WebGL2, or a lost context, leaves the still.
 */
export default function FieldMount() {
  const back = useRef<HTMLCanvasElement>(null);
  const front = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const backEl = back.current;
    const frontEl = front.current;
    const frame = backEl?.closest<HTMLElement>("[data-hero-frame]");
    if (!backEl || !frontEl || !frame) return;
    let dispose: (() => void) | undefined;
    let cancelled = false;
    import("./field/field").then(({ mountField }) => {
      if (cancelled) return;
      dispose = mountField({ frame, back: backEl, front: frontEl, preset: "hero" });
    });
    return () => {
      cancelled = true;
      dispose?.();
    };
  }, []);

  return (
    <>
      <canvas ref={back} aria-hidden className="hero-canvas-back absolute inset-0 size-full" />
      <canvas ref={front} aria-hidden className="hero-canvas-front pointer-events-none absolute inset-x-0 bottom-0 w-full" />
    </>
  );
}
