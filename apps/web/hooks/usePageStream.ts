"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type PageStageEvent, streamPage } from "@/lib/api";
import { type RunLog, useRunLog } from "./useRunLog";

/**
 * One page's extraction, as it happens.
 *
 * State is accumulated per stage rather than as a list of events, because what a reader
 * wants is the current picture and not a transcript: "resolve finished, here is what each
 * fetch contributed" is useful, and "here are the nine events so far" is a log.
 *
 * `done` is kept separate from the stages so the finished document survives a stage arriving
 * late -- the engine is free to reorder or add stages without this losing the result.
 */
export type PageStage = "resolve" | "parse" | "classify" | "select" | "done";

export const STAGE_ORDER: readonly PageStage[] = [
  "resolve",
  "parse",
  "classify",
  "select",
  "done",
];

type Extract<T extends PageStageEvent["type"]> = globalThis.Extract<PageStageEvent, { type: T }>;

export interface PageRun {
  running: boolean;
  /** The stage now in progress, or null once the run has ended one way or the other. */
  current: PageStage | null;
  resolve: Extract<"resolve"> | null;
  parse: Extract<"parse"> | null;
  classify: Extract<"classify"> | null;
  select: Extract<"select"> | null;
  done: Extract<"done"> | null;
  error: string | null;
  /** Which stage the error happened in, which is most of what makes it actionable. */
  errorStage: string | null;
  elapsed: number;
}

const EMPTY: PageRun = {
  running: true,
  current: "resolve",
  resolve: null,
  parse: null,
  classify: null,
  select: null,
  done: null,
  error: null,
  errorStage: null,
  elapsed: 0,
};

export function usePageStream({ url, render }: { url: string; render: boolean }): PageRun & {
  retry: () => void;
  log: RunLog;
} {
  const [run, setRun] = useState<PageRun>(EMPTY);
  const [attempt, setAttempt] = useState(0);
  const startedAt = useRef(Date.now());
  const log = useRunLog();

  const retry = useCallback(() => {
    startedAt.current = Date.now();
    log.reset();
    setRun(EMPTY);
    setAttempt((n) => n + 1);
  }, [log]);

  useEffect(() => {
    const controller = new AbortController();
    startedAt.current = Date.now();

    void (async () => {
      try {
        await streamPage({ url, render }, (event) => {
          log.record(event);
          setRun((state) => {
            switch (event.type) {
              case "stage":
                return { ...state, current: event.stage as PageStage };
              case "resolve":
                return { ...state, resolve: event, current: "parse" };
              case "parse":
                return { ...state, parse: event, current: "classify" };
              case "classify":
                return { ...state, classify: event, current: "select" };
              case "select":
                return { ...state, select: event, current: "done" };
              case "done":
                return { ...state, done: event, current: null, running: false };
              case "error":
                return {
                  ...state,
                  error: event.message,
                  errorStage: event.stage,
                  current: null,
                  running: false,
                };
              default:
                return state;
            }
          });
        }, controller.signal);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        // Never arrives as a frame -- the request itself failed, so the server said nothing.
        // Without this the log simply stops, which reads like the run is still going.
        log.note({
          type: "error",
          stage: "transport",
          message: error instanceof Error ? error.message : String(error),
        });
        setRun((state) => ({
          ...state,
          running: false,
          current: null,
          error: error instanceof Error ? error.message : String(error),
          errorStage: state.current ?? "unknown",
        }));
      } finally {
        // Only the attempt that is still current may declare the run over. React's
        // development double-mount aborts the first attempt as the second starts, and a
        // `finally` that ran regardless flipped `running` to false on the live run -- so
        // the header said "Extracted" at 0.0s while the first stage was still fetching.
        if (!controller.signal.aborted) {
          setRun((state) => (state.running ? { ...state, running: false } : state));
        }
      }
    })();

    return () => controller.abort();
    // `log` is stable: every member is a ref or a `useCallback` with no dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, render, attempt]);

  // Ticks locally rather than waiting on events: a render can take ten seconds, and a
  // frozen clock during it reads as a hung page.
  useEffect(() => {
    if (!run.running) return;
    const ticker = window.setInterval(
      () => setRun((state) => ({ ...state, elapsed: (Date.now() - startedAt.current) / 1000 })),
      250,
    );
    return () => window.clearInterval(ticker);
  }, [run.running]);

  return { ...run, retry, log };
}
