"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { hostOf } from "@/lib/country";
import { normalizeInput } from "@/lib/url";

import RunCard from "./RunCard";
import RunOptions, { OverrideChips } from "./RunOptions";

export type Mode = "page" | "site" | "report";

const MODES: ReadonlyArray<{ id: Mode; label: string; hint: string }> = [
  { id: "page", label: "Read a page", hint: "one URL as Markdown, with how it was read" },
  { id: "site", label: "Run a site", hint: "every public page, in reading order" },
  { id: "report", label: "Site report", hint: "what the site shows people against what it shows crawlers" },
];

/** What the preview card shows while no address is typed (it is hidden then). */
const PLACEHOLDER_HOST = "your-site.com";

/**
 * The prompt: the one thing to do on the page, standing in the scene. A wide field with a
 * round dark submit, and beneath the field, inside the box, the mode as a segmented row and
 * the run's options.
 * Submitting normalises the address (`lib/url`) and routes it: a page or a site to
 * `/extract`, a report to `/report`.
 *
 * In the hero (`scene`) it also drives the Earth: the frame's `data-hero-host` is the host
 * typed or hovered, and the planet turns to its country; `data-hero-state` becomes
 * `running` once Run is pressed, when the camera pushes in for 620 ms
 * before the app navigates.
 */
export default function SitePrompt({ id, scene = false }: { id?: string; scene?: boolean }) {
  const router = useRouter();
  const inputId = useId();
  const errorId = useId();
  const hintId = useId();
  const box = useRef<HTMLDivElement>(null);

  const [value, setValue] = useState("");
  const [mode, setMode] = useState<Mode>("site");
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [focused, setFocused] = useState(false);

  const setState = useCallback(
    (next: "idle" | "focus" | "running") => {
      if (!scene) return;
      const frame = box.current?.closest<HTMLElement>("[data-hero-frame]");
      if (frame) frame.dataset.heroState = next;
    },
    [scene],
  );
  const state = running ? "running" : focused ? "focus" : "idle";
  useEffect(() => setState(state), [state, setState]);
  // The host the scene should turn to: the example under the pointer, else what is typed.
  const sceneHost = hostOf(value) ?? "";
  useEffect(() => {
    if (!scene) return;
    const frame = box.current?.closest<HTMLElement>("[data-hero-frame]");
    if (frame) frame.dataset.heroHost = sceneHost;
  }, [scene, sceneHost]);

  const submit = useCallback(() => {
    const normalized = normalizeInput(value);
    if (!normalized.ok) {
      setError(normalized.reason ?? "Enter a website address.");
      return;
    }
    setError(null);
    setRunning(true);
    const go = () => {
      if (mode === "report") {
        router.push(`/report?url=${encodeURIComponent(normalized.url)}`);
        return;
      }
      const params = new URLSearchParams({ url: normalized.url, mode, complete: "true" });
      router.push(`/extract?${params.toString()}`);
    };
    // In the scene the camera pushes in toward the site first; the run follows it.
    if (scene && !matchMedia("(prefers-reduced-motion: reduce)").matches) window.setTimeout(go, 620);
    else go();
  }, [value, mode, router, scene]);

  const current = MODES.find((m) => m.id === mode) ?? MODES[1]!;
  const shownHost = value.trim() ? normalizeHost(value) : null;

  return (
    <div ref={box} className={scene ? "hero-prompt" : ""} data-scene-card={scene ? "" : undefined}>
      {scene && (
        <div className="hero-preview" aria-hidden={!shownHost} data-shown={shownHost ? "" : undefined}>
          <RunCard host={shownHost ?? PLACEHOLDER_HOST} mode={mode} />
        </div>
      )}
      {/* A plain GET form underneath: before React attaches (a slow phone, a failed script)
          the browser itself submits to /extract with the address, instead of reloading `/?`. */}
      <form
        id={id}
        action="/extract"
        method="get"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <input type="hidden" name="mode" value={mode === "page" ? "page" : "site"} />
        <input type="hidden" name="complete" value="true" />
        <label htmlFor={inputId} className="sr-only">
          Website or page address
        </label>
        <div
          className={`prompt-box rounded-2xl border bg-surface transition-[border-color,box-shadow] duration-(--dur-fast) ease-(--ease) focus-within:ring-2 focus-within:ring-focus/30 ${
            error ? "border-bad" : "border-rule-strong focus-within:border-accent"
          }`}
        >
          <div className="flex items-center gap-2 pl-4 pr-2 pt-2">
            <input
              id={inputId}
              type="text"
              name="url"
              inputMode="url"
              autoComplete="url"
              spellCheck={false}
              value={value}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              onChange={(event) => {
                setValue(event.target.value);
                if (error) setError(null);
              }}
              placeholder="Paste a site or a page URL…"
              aria-invalid={Boolean(error)}
              aria-describedby={error ? errorId : hintId}
              className="tabular h-11 min-w-0 flex-1 bg-transparent font-mono text-code text-ink outline-none placeholder:text-faint sm:text-[1rem]"
            />
            <button
              type="submit"
              disabled={running}
              aria-label={running ? "Running" : current.label}
              title={current.label}
              className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-ink text-inverse transition-[opacity,transform] duration-(--dur-fast) hover:opacity-88 active:translate-y-[0.5px] disabled:opacity-60 pointer-coarse:size-11"
            >
              {running ? (
                <span aria-hidden className="is-running size-2 rounded-full bg-accent animate-[breathe_1.8s_ease-out_infinite]" />
              ) : (
                <svg aria-hidden width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 14.5V3.5M4.5 8 9 3.5 13.5 8" />
                </svg>
              )}
            </button>
          </div>
          {/* What is in force for this run, before it starts: a saved depth of 1 once cut
              a 24-page site to 7 with nothing on this screen to say so. */}
          <OverrideChips mode={mode} />
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 px-2 pb-3 pt-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
            <div role="radiogroup" aria-label="What to do with it" className="inline-flex pill-shape bg-sunk p-0.5">
              {MODES.map((option) => {
                const selected = mode === option.id;
                return (
                  <button
                    key={option.id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    title={option.hint}
                    onClick={() => setMode(option.id)}
                    className={`inline-flex h-8 items-center whitespace-nowrap pill-shape px-3 text-caption font-semibold transition-colors duration-(--dur-fast) ${
                      selected ? "bg-surface text-ink shadow-[0_1px_2px_rgb(15_26_20/0.12)]" : "text-muted hover:text-ink"
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            {mode !== "report" && <RunOptions mode={mode} />}
            </div>
            <p id={hintId} className="sr-only">
              {current.hint}
            </p>
          </div>
        </div>

        {error && (
          <p id={errorId} role="alert" className="mt-2 text-caption font-medium text-bad">
            {error}
          </p>
        )}
      </form>

    </div>
  );
}

function normalizeHost(raw: string): string | null {
  const n = normalizeInput(raw);
  if (!n.ok) return null;
  try {
    const u = new URL(n.url);
    return u.hostname + (u.pathname !== "/" ? u.pathname : "");
  } catch {
    return null;
  }
}
