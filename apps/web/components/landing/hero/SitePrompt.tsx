"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { normalizeInput } from "@/lib/url";

import RunCard from "./RunCard";

export type Mode = "page" | "site" | "report";

const MODES: ReadonlyArray<{ id: Mode; label: string; hint: string }> = [
  { id: "page", label: "Read a page", hint: "one URL as Markdown, with how it was read" },
  { id: "site", label: "Run a site", hint: "every public page, in reading order" },
  { id: "report", label: "Site report", hint: "what the site shows people against what it shows crawlers" },
];

/** Sites the changelog records; each is a story the reader can tell. */
const EXAMPLES: readonly string[] = ["vtu.ac.in", "docs.python.org", "gov.uk/browse", "sode-edu.in"];

/**
 * The prompt: the one thing to do on the page, standing in the scene. A wide field with a
 * round dark submit, and beneath the field, inside the box, the mode as a segmented row and
 * example addresses as chips.
 * Submitting normalises the address (`lib/url`) and routes it: a page or a site to
 * `/extract`, a report to `/report`.
 *
 * In the hero (`scene`) it also drives the field: while an example is hovered, or once Run
 * is pressed, the frame's `data-hero-state` becomes `preview`/`running`, the pages organise
 * into reading order, and the run card rises above the prompt as what the address becomes.
 * Focusing the field alone tidies the pages a little (`focus`).
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
  const [preview, setPreview] = useState<string | null>(null);
  const [focused, setFocused] = useState(false);

  const setState = useCallback(
    (next: "idle" | "focus" | "preview" | "running") => {
      if (!scene) return;
      const frame = box.current?.closest<HTMLElement>("[data-hero-frame]");
      if (frame) frame.dataset.heroState = next;
    },
    [scene],
  );
  const state = running ? "running" : preview ? "preview" : focused ? "focus" : "idle";
  useEffect(() => setState(state), [state, setState]);

  const submit = useCallback(() => {
    const normalized = normalizeInput(value);
    if (!normalized.ok) {
      setError(normalized.reason ?? "Enter a website address.");
      return;
    }
    setError(null);
    setRunning(true);
    if (mode === "report") {
      router.push(`/report?url=${encodeURIComponent(normalized.url)}`);
      return;
    }
    const params = new URLSearchParams({ url: normalized.url, mode, complete: "true" });
    router.push(`/extract?${params.toString()}`);
  }, [value, mode, router]);

  const current = MODES.find((m) => m.id === mode) ?? MODES[1]!;
  const shownHost = preview ?? (value.trim() ? normalizeHost(value) : null);

  return (
    <div ref={box} className={scene ? "hero-prompt" : ""} data-scene-card={scene ? "" : undefined}>
      {scene && (
        <div className="hero-preview" aria-hidden={!shownHost} data-shown={shownHost ? "" : undefined}>
          <RunCard host={shownHost ?? EXAMPLES[0]!} mode={mode} />
        </div>
      )}
      <form
        id={id}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
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
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 px-2 pb-3 pt-1.5">
            <div role="radiogroup" aria-label="What to do with it" className="inline-flex rounded-pill bg-sunk p-0.5">
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
                    className={`inline-flex h-8 items-center whitespace-nowrap rounded-pill px-3 text-caption font-semibold transition-colors duration-(--dur-fast) ${
                      selected ? "bg-surface text-ink shadow-[0_1px_2px_rgb(15_26_20/0.12)]" : "text-muted hover:text-ink"
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            <p id={hintId} className="sr-only">
              {current.hint}
            </p>
            {/* Examples, inside the composer so the nearest pages of the field never cover them. */}
            <ul className="flex flex-wrap items-center gap-1.5" aria-label="Try one">
              {EXAMPLES.map((host, i) => (
                <li key={host} className={i >= 2 ? "max-sm:hidden" : i === EXAMPLES.length - 1 ? "max-lg:hidden" : ""}>
                  <button
                    type="button"
                    onClick={() => {
                      setValue(host);
                      setPreview(host);
                      setError(null);
                      document.getElementById(inputId)?.focus();
                    }}
                    onPointerEnter={() => setPreview(host)}
                    onPointerLeave={() => setPreview(value.trim() ? normalizeHost(value) : null)}
                    onFocus={() => setPreview(host)}
                    onBlur={() => setPreview(value.trim() ? normalizeHost(value) : null)}
                    className="inline-flex h-8 items-center rounded-pill border border-rule px-2.5 font-mono text-caption text-muted transition-colors duration-(--dur-fast) hover:border-rule-strong hover:bg-sunk hover:text-ink"
                  >
                    {host}
                  </button>
                </li>
              ))}
            </ul>
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
