import type { DoneEvent } from "@/lib/api";
import { compact, duration } from "@/lib/format";

export default function RunSummary({ summary }: { summary: DoneEvent }) {
  const chrome = summary.chrome_blocks + summary.chrome_slots;

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
        {summary.exhausted
          ? "every reachable page crawled"
          : `${summary.remaining_queued} still queued`}{" "}
        · {duration(summary.duration_seconds)}
      </p>
    </div>
  );
}
