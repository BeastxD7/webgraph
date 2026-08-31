/** Presentation-only number and time formatting shared by the run views. */

/** `1234` -> `1.2k`. Keeps stat tiles a fixed width as a crawl grows. */
export function compact(value: number): string {
  if (value < 1_000) return String(value);
  if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(1)}M`;
}

/** Seconds as `42s` or `3m 07s`. */
export function duration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds - minutes * 60);
  return `${minutes}m ${String(rest).padStart(2, "0")}s`;
}

/** `https://example.com/a/b?q=1` -> `example.com/a/b`. */
export function prettyUrl(url: string): string {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/$/, "");
    return `${parsed.hostname.replace(/^www\./, "")}${path}`;
  } catch {
    return url;
  }
}

export function percent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}
