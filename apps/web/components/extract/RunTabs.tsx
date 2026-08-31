"use client";

import type { Live } from "@/hooks/useSiteStream";
import { compact, duration } from "@/lib/format";

export type RunTab = "discovered" | "queued" | "extracted" | "failed";

export interface TabCounts {
  discovered: number;
  queued: number;
  extracted: number;
  failed: number;
}

/**
 * The counters double as the view selector: each one opens the list it counts.
 *
 * The numbers are derived from the same client-side sets that back the lists, not from the
 * server's own tallies. Those differ by whatever is in flight at the moment an event was
 * emitted, and a tab reading "1,612" above a list of 1,606 rows is worse than being a few
 * behind the server.
 */
export default function RunTabs({
  counts,
  live,
  elapsed,
  active,
  onSelect,
}: {
  counts: TabCounts;
  live: Live;
  elapsed: number;
  active: RunTab;
  onSelect: (tab: RunTab) => void;
}) {
  const tabs: ReadonlyArray<{ id: RunTab; label: string; value: number; tone: string }> = [
    { id: "discovered", label: "Discovered", value: counts.discovered, tone: "text-ink" },
    { id: "queued", label: "Queued", value: counts.queued, tone: "text-ink" },
    { id: "extracted", label: "Extracted", value: counts.extracted, tone: "text-leaf-600" },
    {
      id: "failed",
      label: "Failed",
      value: counts.failed,
      tone: counts.failed > 0 ? "text-flag-bad" : "text-ink",
    },
  ];

  return (
    <div
      role="tablist"
      aria-label="Crawl results"
      className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-6"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => onSelect(tab.id)}
          className={`px-4 py-4 text-left transition-colors ${
            active === tab.id ? "bg-leaf-50" : "bg-surface hover:bg-haze"
          }`}
        >
          <span className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.1em] text-ink-faint">
            {tab.label}
            {active === tab.id && <span aria-hidden className="size-1 rounded-full bg-leaf-600" />}
          </span>
          <span className={`tabular mt-1.5 block text-[22px] font-extrabold leading-none ${tab.tone}`}>
            {compact(tab.value)}
          </span>
        </button>
      ))}

      {[
        { label: "Rate", value: `${live.rate.toFixed(0)}/min` },
        { label: "Elapsed", value: duration(elapsed) },
      ].map((cell) => (
        <div key={cell.label} className="bg-surface px-4 py-4">
          <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-ink-faint">
            {cell.label}
          </span>
          <span className="tabular mt-1.5 block text-[22px] font-extrabold leading-none">
            {cell.value}
          </span>
        </div>
      ))}
    </div>
  );
}
