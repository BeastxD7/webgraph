import type { DoneEvent } from "@/lib/api";
import { compact, duration } from "@/lib/format";

/** Why the run ended, in the run's own words: which limit, or none. */
export function endedBecause(summary: DoneEvent): string {
  const queued = summary.remaining_queued.toLocaleString("en-US");
  if (summary.stopped) return `stopped by you · ${queued} still queued`;
  switch (summary.stopped_by) {
    case "pages":
      return `stopped at the page cap (${summary.limits.max_pages}) · ${queued} more pages are known and were not crawled`;
    case "time":
      return `stopped at the time limit (${duration(summary.limits.max_seconds)}) · ${queued} still queued`;
    case "queue":
      return `the queue cap (${summary.limits.max_queue.toLocaleString("en-US")}) turned ${summary.queue_refused.toLocaleString("en-US")} addresses away · not every page was reached`;
    default:
      return summary.exhausted ? "every reachable page crawled" : `${queued} still queued`;
  }
}

/** Files the site links to that were counted and never fetched. Empty when there were none. */
export function skippedFiles(summary: DoneEvent): string {
  if (!summary.skipped_total) return "";
  const parts: string[] = [];
  if (summary.skipped.pdf) parts.push(`${summary.skipped.pdf.toLocaleString("en-US")} PDFs`);
  if (summary.skipped.image) parts.push(`${summary.skipped.image.toLocaleString("en-US")} images`);
  if (summary.skipped.other_file) parts.push(`${summary.skipped.other_file.toLocaleString("en-US")} other files`);
  return `${parts.join(", ")} counted, not fetched`;
}

export default function RunSummary({ summary }: { summary: DoneEvent }) {
  const chrome = summary.chrome_blocks + summary.chrome_slots;
  const skipped = skippedFiles(summary);

  return (
    <div className="flex flex-col gap-1.5 rounded-2xl border border-leaf-100 bg-leaf-50 px-5 py-4">
      <p className="text-[14.5px] font-extrabold">
        {summary.pages_ok} pages · {compact(summary.total_markdown_chars)} chars ·{" "}
        {summary.total_images} images · {summary.total_tables} tables
      </p>
      <p className="text-[13px] text-ink-soft">
        {chrome > 0 && (
          <>
            Site chrome: {summary.chrome_blocks} repeated blocks, {summary.chrome_slots} static
            template slots ·{" "}
          </>
        )}
        {endedBecause(summary)} · {duration(summary.duration_seconds)}
        {skipped && <> · {skipped}</>}
        {summary.refused_total > 0 && (
          <> · {summary.refused_total.toLocaleString("en-US")} {summary.refused_total === 1 ? "address" : "addresses"} turned away{summary.refused["off-site"] > 0 ? ` (${summary.refused["off-site"].toLocaleString("en-US")} on other sites)` : ""}</>
        )}
      </p>
    </div>
  );
}
