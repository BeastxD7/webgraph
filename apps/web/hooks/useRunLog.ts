"use client";

import { useCallback, useRef, useState } from "react";

import { type LogEntry, trim } from "@/lib/runlog";

/**
 * Every frame of a run, kept as it arrives.
 *
 * The entries live in a ref rather than in state: a 400-page crawl emits thousands of
 * frames, and copying a growing array into new state on each one would make the log the
 * most expensive thing on the page — for a panel that is collapsed most of the time. What
 * *is* state is the count, which is what the closed panel shows, so the button still says
 * something true while the run is going.
 *
 * `note` exists because the most important lines in a log are often the ones that never
 * arrived as frames. A stream that dies because the API is down produces no `error` event;
 * a reader who pressed Stop produced no event at all. Without these the log ends
 * mid-sentence, and the reader is left to infer the ending — which is exactly the guessing
 * a log exists to end.
 */
export interface RunLog {
  entries: React.RefObject<LogEntry[]>;
  /** Wall clock of the first frame, or 0 before one arrives. Read during render, so it is
   *  never a live clock: `Date.now()` in a render body is not idempotent. */
  startedAt: React.RefObject<number>;
  count: number;
  record: (event: unknown) => void;
  note: (event: Record<string, unknown>) => void;
  reset: () => void;
}

export function useRunLog(): RunLog {
  const entries = useRef<LogEntry[]>([]);
  // Zero until the first frame. Seeding it with `Date.now()` would read a clock during
  // render, and would also time the run from when the component mounted rather than from
  // when it started.
  const startedAt = useRef(0);
  const [count, setCount] = useState(0);

  const push = useCallback((event: Record<string, unknown>) => {
    if (entries.current.length === 0) startedAt.current = Date.now();
    entries.current.push({ t: (Date.now() - startedAt.current) / 1000, event });
    setCount(entries.current.length);
  }, []);

  const record = useCallback(
    (event: unknown) => push(trim(event) as Record<string, unknown>),
    [push],
  );

  /** A client-side observation, marked as such so nobody mistakes it for the server's. */
  const note = useCallback(
    (event: Record<string, unknown>) => push({ ...event, source: "client" }),
    [push],
  );

  const reset = useCallback(() => {
    entries.current = [];
    startedAt.current = 0;
    setCount(0);
  }, []);

  return { entries, startedAt, count, record, note, reset };
}
