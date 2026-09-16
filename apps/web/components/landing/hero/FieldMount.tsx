"use client";

import { useEffect, useRef } from "react";

/**
 * Mounts the live Earth over the hero's still once the WebGL chunk has loaded; the renderer
 * is a separate chunk, imported here so the page's own JavaScript carries none of it.
 * Reduced motion draws one frame and stops. No WebGL2, or a lost context, leaves the still.
 */
export default function FieldMount() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const frame = canvas?.closest<HTMLElement>("[data-hero-frame]");
    if (!canvas || !frame) return;
    let dispose: (() => void) | undefined;
    let cancelled = false;
    import("./field/field").then(({ mountField }) => {
      if (cancelled) return;
      dispose = mountField({ frame, canvas });
    });
    return () => {
      cancelled = true;
      dispose?.();
    };
  }, []);

  return <canvas ref={ref} aria-hidden className="hero-canvas absolute inset-0 size-full" />;
}
