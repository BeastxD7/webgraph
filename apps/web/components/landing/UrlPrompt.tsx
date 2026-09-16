"use client";

import { useRouter } from "next/navigation";
import { useCallback, useId, useState } from "react";

import { normalizeInput } from "@/lib/url";

type Mode = "site" | "page";

const MODES: ReadonlyArray<{ id: Mode; label: string; hint: string }> = [
  { id: "site", label: "Whole site", hint: "every reachable public route" },
  { id: "page", label: "Single page", hint: "one URL, with schema mapping" },
];

/**
 * The one centred thing on the page (DESIGN.md §3, §6).
 *
 * A field on the surface colour with a rule-strong border; the Run button sits inside it at
 * the right. The mode is two joined secondary buttons and "Complete extraction" is a
 * checkbox with a label, because that is what it is. An invalid address is said below the
 * field in the `bad` colour with `role=alert`; pressing Run turns its label into "Running…"
 * with the breathing dot until the run view takes over.
 */
export default function UrlPrompt() {
  const router = useRouter();
  const inputId = useId();
  const errorId = useId();

  const [value, setValue] = useState("");
  const [mode, setMode] = useState<Mode>("site");
  const [complete, setComplete] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const submit = useCallback(() => {
    const normalized = normalizeInput(value);
    if (!normalized.ok) {
      setError(normalized.reason ?? "Enter a website address.");
      return;
    }
    setError(null);
    setRunning(true);

    const params = new URLSearchParams({
      url: normalized.url,
      mode,
      complete: String(complete),
    });
    router.push(`/extract?${params.toString()}`);
  }, [value, mode, complete, router]);

  return (
    <form
      id="start"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="scroll-mt-24"
    >
      <label htmlFor={inputId} className="sr-only">
        Website address
      </label>
      <div
        className={`flex h-14 items-center gap-2 rounded-xl border bg-surface pl-4 pr-2 transition-[border-color,box-shadow] duration-(--dur-fast) ease-(--ease) focus-within:ring-2 focus-within:ring-focus/30 ${
          error
            ? "border-bad"
            : "border-rule-strong focus-within:border-accent"
        }`}
      >
        <input
          id={inputId}
          type="text"
          inputMode="url"
          autoComplete="url"
          spellCheck={false}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            if (error) setError(null);
          }}
          placeholder="docs.astro.build"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
          className="tabular min-w-0 flex-1 bg-transparent font-mono text-code text-ink outline-none placeholder:text-faint sm:text-[1rem]"
        />
        <button
          type="submit"
          disabled={running}
          className="inline-flex h-10 shrink-0 items-center gap-2 rounded-md bg-ink px-4 text-small font-semibold text-inverse transition-opacity duration-(--dur-fast) hover:opacity-88 active:translate-y-[0.5px] active:opacity-100 disabled:opacity-45 pointer-coarse:min-h-11"
        >
          {running && (
            <span
              aria-hidden
              className="is-running size-2 rounded-full bg-accent animate-[breathe_1.8s_ease-out_infinite]"
            />
          )}
          {running ? "Running…" : "Run"}
        </button>
      </div>

      {error && (
        <p id={errorId} role="alert" className="mt-2 text-caption font-medium text-bad">
          {error}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <div role="radiogroup" aria-label="What to read" className="inline-flex">
          {MODES.map((option, index) => {
            const selected = mode === option.id;
            return (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={selected}
                title={option.hint}
                onClick={() => setMode(option.id)}
                className={`inline-flex h-9 items-center border border-rule-strong px-3.5 text-small font-semibold transition-colors duration-(--dur-fast) pointer-coarse:min-h-11 ${
                  index === 0 ? "rounded-l-md" : "-ml-px rounded-r-md"
                } ${selected ? "bg-sunk text-ink" : "bg-transparent text-muted hover:bg-sunk hover:text-ink"}`}
              >
                {option.label}
              </button>
            );
          })}
        </div>

        {mode === "site" && (
          <label className="inline-flex min-h-9 cursor-pointer items-center gap-2 text-small text-muted pointer-coarse:min-h-11">
            <input
              type="checkbox"
              checked={complete}
              onChange={(event) => setComplete(event.target.checked)}
              className="size-4 accent-accent"
            />
            Complete extraction
            <span className="sr-only">: merge the plain fetch and the browser render</span>
          </label>
        )}
      </div>
    </form>
  );
}
