"use client";

import { useRouter } from "next/navigation";
import { useCallback, useId, useState } from "react";

import { normalizeInput } from "@/lib/url";

type Mode = "site" | "page";

const MODES: ReadonlyArray<{ id: Mode; label: string; hint: string }> = [
  { id: "site", label: "Whole site", hint: "every reachable public route" },
  { id: "page", label: "Single page", hint: "one URL, with schema mapping" },
];

/** Registration marks, as on the reference layout: the card reads as a placed plate. */
function CropMarks() {
  const arm = "absolute bg-white/70";
  return (
    <div aria-hidden className="pointer-events-none absolute -inset-6 hidden sm:block">
      <span className={`${arm} left-0 top-0 h-8 w-px`} />
      <span className={`${arm} left-0 top-0 h-px w-8`} />
      <span className={`${arm} right-0 top-0 h-8 w-px`} />
      <span className={`${arm} right-0 top-0 h-px w-8`} />
      <span className={`${arm} bottom-0 left-0 h-8 w-px`} />
      <span className={`${arm} bottom-0 left-0 h-px w-8`} />
      <span className={`${arm} bottom-0 right-0 h-8 w-px`} />
      <span className={`${arm} bottom-0 right-0 h-px w-8`} />
      <span className="absolute left-0 top-0 size-1.5 -translate-x-[3px] -translate-y-[3px] rounded-full bg-white" />
      <span className="absolute right-0 top-0 size-1.5 translate-x-[3px] -translate-y-[3px] rounded-full bg-white" />
    </div>
  );
}

export default function UrlPrompt() {
  const router = useRouter();
  const inputId = useId();

  const [value, setValue] = useState("");
  const [mode, setMode] = useState<Mode>("site");
  const [complete, setComplete] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(() => {
    const normalized = normalizeInput(value);
    if (!normalized.ok) {
      setError(normalized.reason ?? "Enter a website address.");
      return;
    }
    setError(null);

    const params = new URLSearchParams({
      url: normalized.url,
      mode,
      complete: String(complete),
    });
    router.push(`/extract?${params.toString()}`);
  }, [value, mode, complete, router]);

  return (
    <div id="start" className="relative mx-auto w-full max-w-3xl scroll-mt-24">
      <CropMarks />

      {/* The sheet peeking out below: the reference stacks a second plate under the card. */}
      <div
        aria-hidden
        className="absolute inset-x-6 bottom-0 h-16 translate-y-6 rounded-[26px] bg-white/45 backdrop-blur-md"
      />

      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
        className="relative rounded-[26px] border border-white/25 bg-[rgb(24_48_28/0.42)] p-5 shadow-glass backdrop-blur-xl sm:p-6"
      >
        <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.14em] text-white/80">
          <span aria-hidden className="size-1.5 rounded-full bg-leaf-300" />
          Extract a website
        </div>

        <label htmlFor={inputId} className="sr-only">
          Website address
        </label>
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
          className="mt-3 w-full border-l-2 border-white/70 bg-transparent px-3 py-1 text-[19px] font-medium text-white caret-white outline-none placeholder:text-white/55 sm:text-[22px]"
        />

        <p className="mt-2 pl-3 text-[13px] leading-relaxed text-white/70">
          {mode === "site"
            ? "Detects the stack, enumerates every public route, then extracts each page as rich Markdown."
            : "Extracts one page and maps it onto a JSON schema, with provenance for every field."}
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <div
            role="radiogroup"
            aria-label="Extraction mode"
            className="flex rounded-full bg-black/25 p-1"
          >
            {MODES.map((option) => (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={mode === option.id}
                title={option.hint}
                onClick={() => setMode(option.id)}
                className={
                  mode === option.id
                    ? "rounded-full bg-white px-3.5 py-1.5 text-[12.5px] font-bold text-ink"
                    : "rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold text-white/75 transition-colors hover:text-white"
                }
              >
                {option.label}
              </button>
            ))}
          </div>

          {mode === "site" && (
            <button
              type="button"
              aria-pressed={complete}
              onClick={() => setComplete((current) => !current)}
              title="Merge the static and rendered fetches so neither path loses content"
              className={
                complete
                  ? "flex items-center gap-1.5 rounded-full bg-white/90 px-3.5 py-1.5 text-[12.5px] font-bold text-ink"
                  : "flex items-center gap-1.5 rounded-full bg-black/25 px-3.5 py-1.5 text-[12.5px] font-semibold text-white/75"
              }
            >
              <span aria-hidden>{complete ? "◆" : "◇"}</span>
              Complete extraction
            </button>
          )}

          <button
            type="submit"
            aria-label="Start extracting"
            className="ml-auto grid size-11 place-items-center rounded-full bg-white text-ink shadow-md transition-transform hover:scale-105 active:scale-95"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5" />
              <path d="m5 12 7-7 7 7" />
            </svg>
          </button>
        </div>

        {error && (
          <p role="alert" className="mt-3 pl-3 text-[13px] font-semibold text-white">
            {error}
          </p>
        )}
      </form>
    </div>
  );
}
