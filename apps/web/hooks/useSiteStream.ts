"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import {
  type AnalysisEvent,
  type DoneEvent,
  type PageEvent,
  type SiteEvent,
  streamSite,
} from "@/lib/api";

export type Phase =
  | "analyzing"
  | "enumerating"
  | "extracting"
  | "done"
  | "stopped"
  | "failed";

export const PHASE_LABEL: Record<Phase, string> = {
  analyzing: "Detecting the technology stack",
  enumerating: "Seeding routes from sitemap and links",
  extracting: "Crawling and extracting",
  done: "Complete",
  stopped: "Stopped",
  failed: "Failed",
};

export interface Live {
  discovered: number;
  queued: number;
  extracted: number;
  failed: number;
  rate: number;
  chars: number;
  markdown: number;
  images: number;
  tables: number;
}

const NO_COUNTS: Live = {
  discovered: 0,
  queued: 0,
  extracted: 0,
  failed: 0,
  rate: 0,
  chars: 0,
  markdown: 0,
  images: 0,
  tables: 0,
};

interface RunState {
  phase: Phase;
  analysis: AnalysisEvent | null;
  pages: PageEvent[];
  /** Every URL the crawl has accepted, in discovery order, rebuilt from `new_urls` deltas. */
  discoveredUrls: string[];
  live: Live;
  summary: DoneEvent | null;
  error: string | null;
}

const INITIAL: RunState = {
  phase: "analyzing",
  analysis: null,
  pages: [],
  discoveredUrls: [],
  live: NO_COUNTS,
  summary: null,
  error: null,
};

type Action =
  | { kind: "event"; event: SiteEvent }
  | { kind: "stopped" }
  | { kind: "failed"; message: string };

function reduce(state: RunState, action: Action): RunState {
  if (action.kind === "stopped") return { ...state, phase: "stopped" };
  if (action.kind === "failed") {
    return { ...state, phase: "failed", error: action.message };
  }

  const event = action.event;
  switch (event.type) {
    case "stage": {
      const phase =
        event.stage === "analyze"
          ? "analyzing"
          : event.stage === "enumerate"
            ? "enumerating"
            : "extracting";
      return { ...state, phase };
    }
    case "analysis":
      return { ...state, analysis: event };
    case "frontier":
      return {
        ...state,
        discoveredUrls: [...state.discoveredUrls, ...(event.new_urls ?? [])],
        live: { ...state.live, discovered: event.discovered, queued: event.queued },
      };
    case "page":
      // Newest first: on a long crawl the interesting thing is what just landed.
      return {
        ...state,
        pages: [event, ...state.pages],
        discoveredUrls: [...state.discoveredUrls, ...(event.new_urls ?? [])],
        live: {
          discovered: event.discovered,
          queued: event.queued,
          extracted: event.extracted,
          failed: event.failed,
          rate: event.pages_per_minute,
          chars: event.totals.chars,
          markdown: event.totals.markdown,
          images: event.totals.images,
          tables: event.totals.tables,
        },
      };
    case "done":
      return { ...state, summary: event, phase: "done" };
    case "error":
      return { ...state, phase: "failed", error: event.message };
    default:
      return state;
  }
}

export interface SiteStreamRequest {
  url: string;
  complete: boolean;
  maxPages: number;
}

export interface SiteStream extends RunState {
  running: boolean;
  elapsed: number;
  stop: () => void;
}

/**
 * Run the whole-site pipeline for `request`, starting on mount.
 *
 * The crawl starts from an effect rather than a click, which makes React's development
 * double-invoke visible: the first stream is aborted by the cleanup before the second
 * starts, so only one crawl is ever in flight. Aborting in cleanup is what keeps that
 * true — dropping it would leave two unbounded crawls racing against a live site.
 */
export function useSiteStream(request: SiteStreamRequest): SiteStream {
  const [state, dispatch] = useReducer(reduce, INITIAL);
  const [elapsed, setElapsed] = useState(0);
  const controllerRef = useRef<AbortController | null>(null);
  // Written from the effect, never during render: a wall-clock read while rendering is
  // not idempotent.
  const startedAtRef = useRef(0);

  const { url, complete, maxPages } = request;

  const running =
    state.phase === "analyzing" ||
    state.phase === "enumerating" ||
    state.phase === "extracting";

  useEffect(() => {
    if (!url) return;

    const controller = new AbortController();
    controllerRef.current = controller;
    startedAtRef.current = Date.now();

    void (async () => {
      try {
        await streamSite(
          { url, max_pages: maxPages, concurrency: 6, complete },
          (event) => dispatch({ kind: "event", event }),
          controller.signal,
        );
      } catch (cause) {
        if (controller.signal.aborted) return;
        dispatch({
          kind: "failed",
          message: cause instanceof Error ? cause.message : "The stream failed.",
        });
      }
    })();

    return () => controller.abort();
  }, [url, complete, maxPages]);

  // Elapsed ticks locally rather than waiting on events: the analyze stage can take several
  // seconds on a slow site, and a frozen clock there reads as a hung page.
  useEffect(() => {
    if (!running) return;
    const ticker = window.setInterval(() => {
      setElapsed((Date.now() - startedAtRef.current) / 1000);
    }, 250);
    return () => window.clearInterval(ticker);
  }, [running]);

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    dispatch({ kind: "stopped" });
  }, []);

  return { ...state, running, elapsed, stop };
}
