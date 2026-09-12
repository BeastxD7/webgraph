"use client";

import type { Live } from "@/hooks/useSiteStream";

/**
 * Completion against the frontier as it stands right now — or against the page cap, when
 * there is one. An unbounded crawl's denominator grows while it discovers, so the bar can
 * move backwards; that is honest, and better than a fake monotonic bar that implies a total
 * nobody knows yet. A capped crawl *does* know its total: measuring 13 finished pages
 * against 12,128 discovered ones drew an empty bar for a crawl that was nearly done.
 */
export default function ProgressRail({
  live,
  active,
  cap = 0,
}: {
  live: Live;
  active: boolean;
  /** The server's page cap, 0 when unbounded. */
  cap?: number;
}) {
  const finished = live.extracted + live.failed;
  const frontier = finished + live.queued;
  const total = cap > 0 ? Math.min(cap, frontier || cap) : frontier;
  const done = total > 0 ? finished / total : 0;

  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-sunk">
      <div
        className="h-full rounded-full bg-leaf-600 transition-[width] duration-500 ease-out"
        style={{ width: `${Math.min(done * 100, 100)}%` }}
      />
      {active && (
        <div className="absolute inset-y-0 w-1/4 animate-[sweep_1.6s_ease-in-out_infinite] rounded-full bg-leaf-300/60" />
      )}
    </div>
  );
}
