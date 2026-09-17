"use client";

import { type ReactNode, useSyncExternalStore } from "react";

import { resolvedTheme, subscribeTheme } from "@/lib/theme";
import type { techIcon, TechMark } from "@/lib/tech-icons";

/**
 * The mark beside a technology's name (DESIGN.md §6: nothing is carried by the mark alone).
 * Decorative -- `aria-hidden`, no title -- because the visible name says what it is; the
 * mark only makes a list of names scannable. A brand mark is a fill on the 24-unit grid, in
 * that brand's own colour (Simple Icons' own `hex`) rather than the surrounding text's --
 * eight technologies read as eight recognisable logos, not one undifferentiated list, which
 * is the point of showing a logo at all. The generic glyph (no mark in the set) has no
 * brand colour to show, so it stays an outline in the site's own 1.5 px stroke, tinted like
 * the text beside it; that also keeps it visually distinct from a real, coloured mark.
 *
 * The map itself is loaded on demand. A hundred Simple Icons paths are ~114 KB of path
 * data (57 KB gzipped) -- far more than the components that show them -- so `lib/tech-icons`
 * is a dynamic import: its own chunk, fetched once the first page that can show a stack
 * loads, in parallel with the request whose answer will name one. Every place a mark
 * renders is downstream of a fetch or a stream, so the chunk is there before the names
 * are; if it is not, the name renders alone for a moment with the mark's space held.
 */
type Icons = { techIcon: typeof techIcon };

let loaded: Icons | null = null;
let loading: Promise<Icons> | null = null;
const listeners = new Set<() => void>();

function load(): Promise<Icons> {
  loading ??= import("@/lib/tech-icons").then((mod) => {
    loaded = mod;
    for (const notify of listeners) notify();
    return mod;
  });
  return loading;
}

if (typeof window !== "undefined") void load();

function subscribe(notify: () => void): () => void {
  listeners.add(notify);
  if (!loaded) void load();
  return () => {
    listeners.delete(notify);
  };
}

// The loaded module as an external store: the server snapshot is always "not yet", so a
// server render and the client's first render agree on the placeholder even when the chunk
// has already arrived, and React fills the mark in on the next pass.
function useTechMark(name: string): TechMark | null {
  const icons = useSyncExternalStore(
    subscribe,
    () => loaded,
    () => null,
  );
  return icons ? icons.techIcon(name) : null;
}

/** Perceptual luminance, 0-255, from a `#rrggbb` string. */
function luminance(hex: string): number {
  const n = Number.parseInt(hex.slice(1), 16);
  return 0.299 * ((n >> 16) & 0xff) + 0.587 * ((n >> 8) & 0xff) + 0.114 * (n & 0xff);
}

/**
 * A handful of real brand marks (Next.js, Vercel, Three.js, shadcn/ui, ...) are pure black:
 * a deliberate choice by those brands, which invert to white themselves against a dark
 * background everywhere they're shown -- their own docs and marketing included. Left as
 * literal black here, they vanish into this site's own dark theme instead of just being
 * the wrong colour. Only touches marks dark enough that this is clearly the same situation,
 * not a dark-but-still-visible brand colour (GitHub's near-black, say) losing its identity.
 */
function themedFill(hex: string, theme: "light" | "dark"): string {
  return theme === "dark" && luminance(hex) < 24 ? "#f4f4f5" : hex;
}

export default function TechIcon({
  name,
  size = 14,
  className = "text-muted",
}: {
  name: string;
  size?: number;
  className?: string;
}) {
  const mark = useTechMark(name);
  const theme = useSyncExternalStore(subscribeTheme, resolvedTheme, () => "light" as const);
  if (!mark) {
    return <span aria-hidden className="inline-block shrink-0" style={{ width: size, height: size }} />;
  }
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={`shrink-0 ${className}`}
      {...(mark.generic
        ? { fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinejoin: "round", strokeLinecap: "round" }
        : { fill: mark.hex ? themedFill(mark.hex, theme) : "currentColor" })}
    >
      <path d={mark.path} />
    </svg>
  );
}

/** Mark + name as one inline unit; the name is the visible text, the mark rides beside it. */
export function TechName({
  name,
  children,
  iconClassName,
  className = "",
}: {
  name: string;
  /** What follows the name inside the unit (a version, a date); the name itself is always shown. */
  children?: ReactNode;
  iconClassName?: string;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <TechIcon name={name} className={iconClassName} />
      <span>
        {name}
        {children}
      </span>
    </span>
  );
}

/** The one-line note that goes under any list of marks. */
export function TrademarkNote({ className = "" }: { className?: string }) {
  return (
    <p className={`text-caption text-muted ${className}`}>
      Marks are trademarks of their owners, shown to identify the detected technology.
    </p>
  );
}
