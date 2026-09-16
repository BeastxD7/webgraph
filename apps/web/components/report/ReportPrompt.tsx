"use client";

import { useRouter } from "next/navigation";
import { useCallback, useId, useState } from "react";

import { normalizeInput } from "@/lib/url";

/**
 * The report's URL field: the landing prompt's form (DESIGN.md §6, URL input) without the
 * mode segment, because a report has one mode. Submitting puts the address in the query
 * string, so the result has a link that can be sent to someone.
 */
export default function ReportPrompt({ initial = "" }: { initial?: string }) {
  const router = useRouter();
  const inputId = useId();
  const errorId = useId();
  const [value, setValue] = useState(initial);
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
    router.push(`/report?url=${encodeURIComponent(normalized.url)}`);
  }, [value, router]);

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label htmlFor={inputId} className="sr-only">
        Website address
      </label>
      <div
        className={`flex h-14 items-center gap-2 rounded-xl border bg-surface pl-4 pr-2 transition-[border-color,box-shadow] duration-(--dur-fast) ease-(--ease) focus-within:ring-2 focus-within:ring-focus/30 ${
          error ? "border-bad" : "border-rule-strong focus-within:border-accent"
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
          placeholder="vtu.ac.in"
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
          {running ? "Running…" : "Run a report"}
        </button>
      </div>
      {error && (
        <p id={errorId} role="alert" className="mt-2 text-caption font-medium text-bad">
          {error}
        </p>
      )}
    </form>
  );
}
