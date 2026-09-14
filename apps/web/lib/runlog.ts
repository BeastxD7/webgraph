/**
 * A run, written down in the form someone can paste into a bug report.
 *
 * The stages panel answers "what is happening"; this answers "what happened", which is a
 * different question asked by a different person at a different time — usually after the
 * run went wrong, usually by someone who was not watching it. So this keeps every frame,
 * in arrival order, including the ones no panel draws.
 *
 * Two things are deliberately *not* summarised away:
 *
 * - **Order and timing.** Each entry carries `t`, seconds since the client's first frame.
 *   A run that spent nine of its twelve seconds in one render is a different bug from one
 *   that spent them evenly, and no aggregate shows the difference.
 * - **Events the UI ignores.** A frame this version of the UI has no component for is still
 *   written down. The next question asked about a run is rarely the one the UI was built to
 *   answer.
 *
 * What is dropped is the content itself — Markdown, HTML, plain text — replaced by its size.
 * That mirrors `_SKIP_KEYS` and `_MAX_VALUE_CHARS` in the engine's `webgraph/trace.py`, so
 * the clipboard and the server's trace file agree about what a log is; the content has its
 * own copy button a few inches away, and a "log" that is mostly one page's article is not
 * one.
 */

/** Fields that are output rather than evidence. Mirrors `_SKIP_KEYS` in `webgraph/trace.py`. */
const CONTENT_KEYS = new Set(["markdown", "content_markdown", "comments_markdown", "html", "text"]);

/** Mirrors `_MAX_VALUE_CHARS` in `webgraph/trace.py`. */
const MAX_VALUE_CHARS = 2_000;

/** Longest list kept whole. A 400-page crawl's `pages` array is a result, not a record. */
const MAX_ITEMS = 200;

export interface LogEntry {
  /** Seconds since the first frame of this run arrived, client-side. */
  t: number;
  event: Record<string, unknown>;
}

/**
 * The event with its payload replaced by the payload's size.
 *
 * Sizes rather than nothing: "the page came back with 41,207 characters of Markdown" is
 * evidence, and it is the fact someone chasing an empty extraction needs. Deleting the key
 * outright would make a page that returned nothing and a page that returned a novel look
 * the same in the log.
 */
export function trim(value: unknown): unknown {
  if (Array.isArray(value)) {
    const kept = value.slice(0, MAX_ITEMS).map(trim);
    return value.length > MAX_ITEMS ? [...kept, `… ${value.length - MAX_ITEMS} more`] : kept;
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, inner] of Object.entries(value as Record<string, unknown>)) {
      if (CONTENT_KEYS.has(key)) {
        out[key] = typeof inner === "string" ? `«${inner.length} chars»` : "«omitted»";
        continue;
      }
      out[key] = trim(inner);
    }
    return out;
  }
  if (typeof value === "string" && value.length > MAX_VALUE_CHARS) {
    return `${value.slice(0, MAX_VALUE_CHARS)}… (${value.length} chars)`;
  }
  return value;
}

export interface RunMeta {
  url: string;
  mode: "single page" | "whole site";
  /** What the client asked for, before the server's caps — the header prints both. */
  request: Record<string, string | number | boolean>;
  /** The server's `run` frame, when one has arrived. */
  header: Record<string, unknown> | null;
  /** Client wall clock at the first frame, or 0 if none has arrived. */
  startedAt: number;
  /** Set once the run ends; null while it is still going. */
  endedAt: number | null;
  /** How the run ended, in the words the UI is showing. */
  outcome: string;
}

function pairs(record: Record<string, unknown>): string {
  return Object.entries(record)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(" ");
}

/**
 * The whole log as one string: a header block, then one JSON object per line.
 *
 * NDJSON because it is the shape the server's own trace has, so the two can be diffed
 * directly, and because a log that needs a parser to read is a log nobody reads. The header
 * is plain text above it: whoever opens the paste should not have to decode anything to
 * learn which URL this was.
 */
export function formatRunLog(entries: readonly LogEntry[], meta: RunMeta): string {
  // Called from a click handler, never during render, so reading the clock here is fine --
  // and it is the only way a still-running log can state its own duration.
  const ended = meta.endedAt ?? Date.now();
  const started = meta.startedAt || ended;
  const header = meta.header ?? {};

  const lines = [
    "# webgraph run log",
    `url        ${meta.url}`,
    `mode       ${meta.mode}`,
    `requested  ${pairs(meta.request)}`,
    // Only present once the server's first frame has arrived. A log copied before that --
    // the API down, the request refused -- says so by their absence rather than by a blank.
    ...(header.run ? [`run        ${String(header.run)}`] : []),
    ...(header.trace ? [`trace      ${String(header.trace)} (on the API host)`] : []),
    ...(header.engine ? [`engine     webgraph ${String(header.engine)}`] : []),
    ...(header.strategy ? [`applied    ${pairs(appliedFrom(header))}`] : []),
    `started    ${meta.startedAt ? new Date(started).toISOString() : "no frame received"}`,
    `duration   ${((ended - started) / 1000).toFixed(1)}s${
      meta.endedAt === null ? " (still running)" : ""
    }`,
    `outcome    ${meta.outcome}`,
    `events     ${entries.length}`,
    "#",
    "# One JSON object per line, in arrival order. `t` is seconds since the first frame,",
    "# measured in the browser. Extracted content (markdown, html, text) is replaced by its",
    "# size -- it is the result, not the record.",
    "",
  ];

  for (const entry of entries) {
    lines.push(JSON.stringify({ t: Number(entry.t.toFixed(3)), ...entry.event }));
  }
  return lines.join("\n");
}

/** The options the server reported applying, without the identity fields around them. */
function appliedFrom(header: Record<string, unknown>): Record<string, unknown> {
  const applied: Record<string, unknown> = {};
  for (const key of ["strategy", "max_pages", "concurrency", "render", "complete"]) {
    if (header[key] !== undefined) applied[key] = header[key];
  }
  return applied;
}
