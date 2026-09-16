"use client";

import dynamic from "next/dynamic";

/**
 * `GraphView` imports sigma, which reaches for `window` and a WebGL context the moment it is
 * evaluated. Loading it with `ssr: false` from a client component keeps it out of the server
 * render entirely; the placeholder holds the height so the page does not jump when it lands.
 */
const GraphView = dynamic(() => import("./GraphView"), {
  ssr: false,
  loading: () => (
    <div
      className="flex h-full min-h-[24rem] items-center justify-center text-caption text-muted"
      role="status"
    >
      Loading the renderer…
    </div>
  ),
});

export default GraphView;
