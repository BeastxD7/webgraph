"use client";

import { useState } from "react";

import CopyButton from "@/components/ui/CopyButton";
import type { RunLog as Log } from "@/hooks/useRunLog";
import { formatRunLog, type RunMeta } from "@/lib/runlog";

/**
 * The whole run, in one paste.
 *
 * Collapsed by default and copyable at any moment, including mid-run — a partial log of a
 * crawl that is still hanging is the most useful paste there is, and gating the button on
 * completion would withhold it exactly when it is wanted.
 *
 * The tail is shown rather than the head. A reader who opens this is looking at the end of
 * the run, because the end is where it went wrong; scrolling past three hundred successful
 * page events to reach the error would be the panel's own fault.
 */
export default function RunLog({ log, meta }: { log: Log; meta: RunMeta }) {
  const [open, setOpen] = useState(false);

  // Rendered only while open. A live crawl pushes a frame every few hundred milliseconds,
  // and a closed panel that still re-rendered a few hundred <div>s for each one would cost
  // the page more than the log is worth.
  const tail = open ? log.entries.current.slice(-40) : [];

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
      <div className="flex flex-wrap items-center gap-3 p-4">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="flex items-center gap-2 text-[15px] font-extrabold tracking-tight"
        >
          <span
            aria-hidden
            className={`text-[10px] text-ink-faint transition-transform ${open ? "rotate-90" : ""}`}
          >
            ▶
          </span>
          Run log
        </button>

        <span className="tabular text-[12.5px] text-ink-faint">
          {log.count.toLocaleString("en-US")} events
          {meta.header?.run ? ` · run ${String(meta.header.run)}` : ""}
          {meta.endedAt === null ? " · still running" : ""}
        </span>

        {/* A function, not a string: the log is assembled on the click, not on every frame
            of a live crawl. */}
        <CopyButton
          className="ml-auto"
          label="Copy run log"
          text={() => formatRunLog(log.entries.current, meta)}
        />
      </div>

      {open && (
        <div className="border-t border-line bg-haze px-4 py-3">
          <p className="text-[12.5px] text-ink-soft">
            Every frame this run received, in arrival order, with extracted content replaced
            by its size. The copy includes the header and all{" "}
            {log.count.toLocaleString("en-US")}; the preview below is the last 40.
          </p>
          {meta.header?.trace ? (
            <p className="mt-1.5 font-mono text-[11.5px] text-ink-faint">
              server trace: {String(meta.header.trace)}
            </p>
          ) : null}

          <pre className="mt-3 max-h-96 overflow-auto rounded-xl border border-line bg-surface p-3 font-mono text-[11.5px] leading-relaxed">
            {tail.length === 0
              ? "No events yet."
              : tail
                  .map(
                    (entry) =>
                      `${entry.t.toFixed(3).padStart(8)}  ${JSON.stringify(entry.event)}`,
                  )
                  .join("\n")}
          </pre>
        </div>
      )}
    </section>
  );
}
