"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type ChangeEvent,
  type WatchDoneEvent,
  type WatchEvent,
  type WatchStartEvent,
  streamWatchRun,
} from "@/lib/api";

/**
 * One watch run at a time, as the stream reports it: which watch, what it is compared
 * against, the pages as they land, each change as it is found, and the summary.
 *
 * The same shape as `useSiteStream` -- an AbortController per run, events reduced into
 * state -- without the reading-session state (no Markdown, no discovery panel): a watch run
 * is bookkeeping, and the page events arrive without their text.
 */
export interface WatchRunState {
  watchId: string | null;
  running: boolean;
  start: WatchStartEvent | null;
  pages: number;
  failed: number;
  inFlight: string[];
  changes: ChangeEvent[];
  summary: WatchDoneEvent | null;
  error: string | null;
  stage: string | null;
}

const IDLE: WatchRunState = {
  watchId: null,
  running: false,
  start: null,
  pages: 0,
  failed: 0,
  inFlight: [],
  changes: [],
  summary: null,
  error: null,
  stage: null,
};

function reduce(state: WatchRunState, event: WatchEvent): WatchRunState {
  switch (event.type) {
    case "watch":
      return { ...state, start: event };
    case "stage":
      return { ...state, stage: event.message };
    case "fetching":
      return { ...state, inFlight: event.urls };
    case "page":
      return {
        ...state,
        pages: state.pages + 1,
        failed: state.failed + (event.ok ? 0 : 1),
        inFlight: state.inFlight.filter((url) => url !== event.url),
      };
    case "change":
      return { ...state, changes: [event, ...state.changes] };
    case "done":
      return { ...state, summary: event, inFlight: [], stage: null };
    case "error":
      return { ...state, error: event.message, inFlight: [] };
    default:
      return state;
  }
}

export function useWatchRun(options: { onFinished?: (watchId: string) => void } = {}): WatchRunState & {
  run: (watchId: string) => void;
  stop: () => void;
  reset: () => void;
} {
  const [state, setState] = useState<WatchRunState>(IDLE);
  const controllerRef = useRef<AbortController | null>(null);
  // The latest callback, so a run started under one render calls the one the caller has now.
  const onFinishedRef = useRef(options.onFinished);
  useEffect(() => {
    onFinishedRef.current = options.onFinished;
  });

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setState((s) => ({ ...s, running: false, inFlight: [] }));
  }, []);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setState(IDLE);
  }, []);

  const run = useCallback((watchId: string) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState({ ...IDLE, watchId, running: true });
    void (async () => {
      try {
        await streamWatchRun(
          watchId,
          (event) => setState((s) => reduce(s, event)),
          controller.signal,
        );
      } catch (cause) {
        if (controller.signal.aborted) return;
        const message = cause instanceof Error ? cause.message : String(cause);
        setState((s) => ({ ...s, error: message }));
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
          setState((s) => ({ ...s, running: false }));
          onFinishedRef.current?.(watchId);
        }
      }
    })();
  }, []);

  useEffect(() => () => controllerRef.current?.abort(), []);

  return { ...state, run, stop, reset };
}
