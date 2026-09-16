"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

import { PRESETS, type ProviderIn } from "./kg";

/**
 * The reader's model settings for WebGraph, kept in this browser.
 *
 * Two stores on purpose. Provider, endpoint and model names are preferences and live in
 * `localStorage` like `lib/options.ts`. The API key is a secret: by default it lives in
 * module memory for this page load only and is sent in the body of each build or ask
 * request -- the server uses it for that request and holds it nowhere afterwards (see
 * `ProviderConfig.redacted()` and the 422 handler in `apps/api`). A reader who wants it
 * back tomorrow ticks "remember in this browser", which writes it to `localStorage` under
 * a separate key; unticking removes it. Nothing here ever logs it.
 */

const PREFS_KEY = "webgraph.kg.provider.v1";
const SECRET_KEY = "webgraph.kg.key.v1";

export interface ProviderPrefs {
  preset: string;
  base_url: string;
  model: string;
  answer_model: string;
  /** Lower for local servers; the engine's default is 4. */
  max_concurrency: number;
}

export const DEFAULT_PREFS: ProviderPrefs = {
  preset: "ollama",
  base_url: "http://localhost:11434/v1",
  model: "",
  answer_model: "",
  max_concurrency: 4,
};

function readPrefs(): string {
  try {
    return window.localStorage.getItem(PREFS_KEY) ?? "{}";
  } catch {
    return "{}";
  }
}

function writePrefs(prefs: ProviderPrefs): void {
  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // Storage unavailable: the settings apply to this page load and no further.
  }
}

// The key, outside React and outside storage unless asked.
let memoryKey = "";
let remember = false;
let booted = false;

function bootSecret(): void {
  if (booted) return;
  booted = true;
  try {
    const stored = window.localStorage.getItem(SECRET_KEY);
    if (stored) {
      memoryKey = stored;
      remember = true;
    }
  } catch {
    // Nothing remembered.
  }
}

function secretSnapshot(): string {
  bootSecret();
  return JSON.stringify({ key: memoryKey, remember });
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

export function useProviderPrefs(): [ProviderPrefs, (next: Partial<ProviderPrefs>) => void, boolean] {
  const snapshot = useSyncExternalStore(subscribe, readPrefs, () => "");
  const loaded = snapshot !== "";
  const prefs = useMemo<ProviderPrefs>(() => {
    try {
      return { ...DEFAULT_PREFS, ...(JSON.parse(snapshot || "{}") as Partial<ProviderPrefs>) };
    } catch {
      return DEFAULT_PREFS;
    }
  }, [snapshot]);
  const set = useCallback(
    (next: Partial<ProviderPrefs>) => {
      writePrefs({ ...prefs, ...next });
      notify();
    },
    [prefs],
  );
  return [prefs, set, loaded];
}

export function useApiKey(): [string, boolean, (key: string) => void, (remember: boolean) => void] {
  const snapshot = useSyncExternalStore(subscribe, secretSnapshot, () => JSON.stringify({ key: "", remember: false }));
  const { key, remember: remembered } = JSON.parse(snapshot) as { key: string; remember: boolean };
  const setKey = useCallback((next: string) => {
    memoryKey = next;
    if (remember) {
      try {
        if (next) window.localStorage.setItem(SECRET_KEY, next);
        else window.localStorage.removeItem(SECRET_KEY);
      } catch {
        // Fine: it stays in memory.
      }
    }
    notify();
  }, []);
  const setRemember = useCallback((next: boolean) => {
    remember = next;
    try {
      if (next && memoryKey) window.localStorage.setItem(SECRET_KEY, memoryKey);
      else window.localStorage.removeItem(SECRET_KEY);
    } catch {
      // Fine: it stays in memory.
    }
    notify();
  }, []);
  return [key, remembered, setKey, setRemember];
}

/** The request body's `provider`, built from prefs and the key. Empty strings are left out
 *  so the API's environment defaults apply. */
export function providerBody(prefs: ProviderPrefs, apiKey: string): ProviderIn {
  const preset = PRESETS.find((p) => p.id === prefs.preset);
  const body: ProviderIn = {};
  if (preset && preset.id !== "custom") body.provider = preset.id;
  else body.provider = "openai-compatible";
  if (prefs.base_url) body.base_url = prefs.base_url;
  if (prefs.model) body.model = prefs.model;
  if (prefs.answer_model) body.answer_model = prefs.answer_model;
  if (apiKey) body.api_key = apiKey;
  if (prefs.max_concurrency && prefs.max_concurrency !== 4) body.max_concurrency = prefs.max_concurrency;
  return body;
}
