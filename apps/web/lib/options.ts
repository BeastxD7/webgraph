"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

import type { RunOptions } from "./api";

/**
 * The reader's own settings, kept in this browser and sent with every run.
 *
 * Only *overrides* are stored -- a value the reader changed away from the default. The
 * defaults themselves are never copied here: they come from `webgraph/config.py` through
 * `/api/config`, so editing that file changes what every run does unless the reader has
 * deliberately said otherwise. Clearing an override returns it to whatever the file says.
 *
 * `localStorage` because these are one person's preferences on one machine, not state the
 * server needs; it can be absent (private windows, blocked storage), so every read and write
 * is guarded and the page works with nothing saved.
 */

const KEY = "webgraph.options.v1";

export type Overrides = RunOptions;

export function readOverrides(): Overrides {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Overrides) : {};
  } catch {
    return {};
  }
}

export function writeOverrides(next: Overrides): void {
  try {
    const clean = prune(next);
    if (Object.keys(clean).length === 0) window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, JSON.stringify(clean));
  } catch {
    // Storage unavailable: the settings apply to this page load and no further.
  }
}

/** Drop empty groups so "no overrides" is an empty object, not three empty objects. */
function prune(options: Overrides): Overrides {
  const out: Overrides = {};
  for (const group of ["crawl", "fetch", "renderOptions"] as const) {
    const entries = Object.entries(options[group] ?? {}).filter(([, v]) => v !== undefined && v !== null && v !== "");
    if (entries.length) out[group] = Object.fromEntries(entries);
  }
  if (options.max_pages !== undefined) out.max_pages = options.max_pages;
  if (options.concurrency !== undefined) out.concurrency = options.concurrency;
  return out;
}

export function useOverrides(): [Overrides, (next: Overrides) => void, boolean] {
  // Storage is read after mount, never during render: the server has no storage and a
  // first render that disagreed with the browser's would be torn down as a hydration
  // mismatch. `useSyncExternalStore` is the sanctioned way to subscribe to a browser-only
  // source without a setState inside an effect.
  const snapshot = useSyncExternalStore(subscribe, readOverridesSerialised, () => "");
  const loaded = snapshot !== "";
  const overrides = useMemo<Overrides>(() => (snapshot ? (JSON.parse(snapshot) as Overrides) : {}), [snapshot]);
  const set = useCallback((next: Overrides) => {
    writeOverrides(prune(next));
    notify();
  }, []);
  return [overrides, set, loaded];
}

const listeners = new Set<() => void>();
function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}
function notify(): void {
  for (const listener of listeners) listener();
}
/** A stable string per state, so the store can compare snapshots by value. "{}" when
 *  nothing is saved -- non-empty on purpose, so "loaded" can be told from "server". */
function readOverridesSerialised(): string {
  return JSON.stringify(readOverrides());
}
