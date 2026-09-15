"use client";

import { useSyncExternalStore } from "react";

import { readTheme, serverTheme, setTheme, subscribeTheme, THEMES, type Theme } from "@/lib/theme";

import { buttonClass } from "./Button";

const LABEL: Record<Theme, string> = { system: "System", light: "Light", dark: "Dark" };

/**
 * One quiet button that cycles System → Light → Dark. The label is the state, spelled out,
 * so the control reads without an icon legend; the next state is in the accessible name so
 * a screen reader knows what pressing it does.
 *
 * The server renders "System"; the stored choice is read on the client, where the first
 * paint already carries the right colours from the boot script in `layout.tsx` and only the
 * word needs to catch up.
 */
export default function ThemeToggle({ className = "" }: { className?: string }) {
  const theme = useSyncExternalStore(subscribeTheme, readTheme, serverTheme);
  const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length] ?? "system";

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Theme: ${LABEL[theme]}. Switch to ${LABEL[next]}`}
      title={`Switch to ${LABEL[next]}`}
      className={buttonClass("quiet", className)}
    >
      <ThemeGlyph theme={theme} />
      <span>{LABEL[theme]}</span>
    </button>
  );
}

function ThemeGlyph({ theme }: { theme: Theme }) {
  // A circle: empty for system, filled for dark, half for light. Decorative; the word carries it.
  return (
    <svg aria-hidden width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="5.25" stroke="currentColor" strokeWidth="1.5" />
      {theme === "dark" && <circle cx="7" cy="7" r="3.25" fill="currentColor" />}
      {theme === "light" && <path d="M7 1.75A5.25 5.25 0 0 1 7 12.25Z" fill="currentColor" />}
    </svg>
  );
}
