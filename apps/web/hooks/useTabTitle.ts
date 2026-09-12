"use client";

import { useEffect } from "react";

/**
 * Keep the browser tab honest about the run.
 *
 * The page's static title is "Extracting", which is right for the first ten seconds and
 * wrong for the rest of the tab's life. A reader with six tabs open finds the finished one
 * by its title, so it says what happened -- and, while running, what it is running on.
 */
export function useTabTitle(state: "running" | "done" | "failed" | "stopped", host: string) {
  useEffect(() => {
    const previous = document.title;
    const word = { running: "Extracting", done: "Extracted", failed: "Failed", stopped: "Stopped" }[state];
    document.title = `${word} · ${host} · webgraph`;
    return () => {
      document.title = previous;
    };
  }, [state, host]);
}
