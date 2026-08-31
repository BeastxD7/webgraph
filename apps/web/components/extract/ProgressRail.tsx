"use client";

import type { Live } from "@/hooks/useSiteStream";

/**
 * Completion against the frontier as it stands right now. The denominator grows while the
 * crawl discovers, so the bar can move backwards — that is honest, and better than a fake
 * monotonic bar that implies a total nobody knows yet.
 */
export default function ProgressRail({
  live,
  active,
}: {
  live: Live;
  active: boolean;
}) {
  const total = live.extracted + live.failed + live.queued;
  const done = total > 0 ? (live.extracted + live.failed) / total : 0;

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
