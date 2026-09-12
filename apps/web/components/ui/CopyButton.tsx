"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Copy text to the clipboard, and say whether it worked.
 *
 * The confirmation is the whole point. A copy button that looks identical before and after
 * being pressed leaves the reader pressing it again, or pasting to find out — and the
 * clipboard API fails quietly and routinely: over plain HTTP, in a cross-origin frame, or
 * when the document is not focused. So the three outcomes are all shown, and the failure says
 * what to do instead rather than apologising.
 */
export default function CopyButton({
  text,
  label = "Copy",
  className = "",
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const copy = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    timer.current = setTimeout(() => setState("idle"), 2200);
  }, [text]);

  const words = text.trim() ? text.trim().split(/\s+/).length : 0;

  return (
    <button
      type="button"
      onClick={copy}
      disabled={!text}
      // `aria-live` on the label, not the button: a screen reader should hear the outcome,
      // not the whole control again.
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        state === "copied"
          ? "border-leaf-300 bg-leaf-50 text-leaf-700"
          : state === "failed"
            ? "border-clay/40 bg-clay/10 text-clay"
            : "border-line bg-surface text-ink-soft hover:border-ink-faint hover:text-ink"
      } ${className}`}
      title={words ? `${words.toLocaleString("en-US")} words` : undefined}
    >
      <span aria-hidden>{state === "copied" ? "✓" : state === "failed" ? "!" : "⧉"}</span>
      <span aria-live="polite">
        {state === "copied" ? "Copied" : state === "failed" ? "Press ⌘C instead" : label}
      </span>
    </button>
  );
}
