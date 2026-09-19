"use client";

import Link from "next/link";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api, type ConfigResponse } from "@/lib/api";
import { type Overrides, useOverrides } from "@/lib/options";

import type { Mode } from "./SitePrompt";

/**
 * The run's options, at the prompt.
 *
 * The Settings page has held every overridable value since the product phase, linked from
 * the footer and nowhere else. The owner crawled lakshx.in with a saved `max_depth` of 1
 * -- set there, some day, by someone -- got 7 pages of 24, and had no way to see why from
 * the box they typed the address into. Firecrawl's playground puts the same options behind
 * a sliders icon on its input; this is ours. Same store as Settings (`lib/options`): a
 * value changed here shows there and rides with every run from this browser, and the chips
 * under the prompt say what is in force before the run starts.
 *
 * Only the options a reader reaches for are here; the full list, with every default's
 * comment from config.py, stays on the Settings page.
 */

type Group = "crawl" | "fetch" | "renderOptions";
type Scalar = number | boolean | string;

interface Field {
  /** `top` for the two request-level fields (`max_pages`, `concurrency`). */
  group: Group | "top";
  key: string;
  label: string;
  kind: "number" | "switch" | "text";
  /** The config.py name that holds the default, for the placeholder. */
  source?: string;
  hint: string;
  /** A second field set to the same value: robots.txt is one switch to a reader, two to the API. */
  mirror?: [Group, string];
  section: "site" | "page";
}

const FIELDS: readonly Field[] = [
  {
    group: "top",
    key: "max_pages",
    label: "Max pages",
    kind: "number",
    source: "CRAWL_MAX_PAGES",
    hint: "Stop after this many pages. 0 means no limit.",
    section: "site",
  },
  {
    group: "crawl",
    key: "max_depth",
    label: "Max depth",
    kind: "number",
    source: "CRAWL_MAX_DEPTH",
    hint: "How many links away from the start a page may be. 1 is the start page and what it links to.",
    section: "site",
  },
  {
    group: "crawl",
    key: "within_path",
    label: "Stay within the path",
    kind: "switch",
    source: "CRAWL_WITHIN_PATH",
    hint: "Start at /docs and only /docs/… is crawled.",
    section: "site",
  },
  {
    group: "crawl",
    key: "strict_domain",
    label: "Stay on the exact host",
    kind: "switch",
    source: "CRAWL_STRICT_DOMAIN",
    hint: "Off: the site's subdomains are crawled too.",
    section: "site",
  },
  {
    group: "crawl",
    key: "include_paths",
    label: "Include only paths",
    kind: "text",
    source: "CRAWL_INCLUDE_PATHS",
    hint: "Patterns over the path, comma-separated: ^/docs/, ^/blog/",
    section: "site",
  },
  {
    group: "crawl",
    key: "exclude_paths",
    label: "Exclude paths",
    kind: "text",
    source: "CRAWL_EXCLUDE_PATHS",
    hint: "Patterns over the path, comma-separated: /tag/, \\?page=",
    section: "site",
  },
  {
    group: "crawl",
    key: "respect_robots",
    label: "Respect robots.txt",
    kind: "switch",
    source: "CRAWL_RESPECT_ROBOTS",
    mirror: ["fetch", "respect_robots"],
    hint: "Obey the site's Disallow rules. Off by default: the engine reads everything it can reach.",
    section: "site",
  },
  {
    group: "renderOptions",
    key: "reveal_collapsed",
    label: "Reveal collapsed content",
    kind: "switch",
    source: "RENDER_REVEAL_COLLAPSED",
    hint: "Open tabs, accordions and details the page describes, without clicking.",
    section: "page",
  },
  {
    group: "renderOptions",
    key: "click_collapsed",
    label: "Click collapsed content",
    kind: "switch",
    source: "RENDER_CLICK_COLLAPSED",
    hint: "Click the tabs and 'show more' buttons only JavaScript can open.",
    section: "page",
  },
  {
    group: "renderOptions",
    key: "dismiss_gates",
    label: "Dismiss cookie and country gates",
    kind: "switch",
    source: "RENDER_DISMISS_GATES",
    hint: "Close the dialog drawn over the page before measuring it.",
    section: "page",
  },
  {
    group: "fetch",
    key: "timeout_seconds",
    label: "Fetch timeout (s)",
    kind: "number",
    source: "FETCH_TIMEOUT_SECONDS",
    hint: "How long one plain fetch may take.",
    section: "page",
  },
];

const SECTION_TITLE: Record<Field["section"], string> = {
  site: "Crawling a site",
  page: "Reading each page",
};

function current(overrides: Overrides, field: Field): Scalar | undefined {
  if (field.group === "top") return overrides[field.key as "max_pages" | "concurrency"];
  return (overrides[field.group] as Record<string, Scalar> | undefined)?.[field.key];
}

function withValue(overrides: Overrides, field: Field, value: Scalar | undefined): Overrides {
  const next: Overrides = { ...overrides };
  const targets: Array<[Group | "top", string]> = [[field.group, field.key]];
  if (field.mirror) targets.push(field.mirror);
  for (const [group, key] of targets) {
    if (group === "top") {
      if (value === undefined) delete next[key as "max_pages" | "concurrency"];
      else next[key as "max_pages" | "concurrency"] = Number(value);
      continue;
    }
    const bucket: Record<string, Scalar> = { ...(next[group] ?? {}) };
    if (value === undefined) delete bucket[key];
    else bucket[key] = value;
    next[group] = bucket;
  }
  return next;
}

/** One line per override in force, for the chips: "max depth 1", "robots.txt on". */
export function activeOverrides(overrides: Overrides): Array<{ field: Field; text: string }> {
  const out: Array<{ field: Field; text: string }> = [];
  for (const field of FIELDS) {
    const value = current(overrides, field);
    if (value === undefined) continue;
    const label = field.label.toLowerCase();
    out.push({
      field,
      text: field.kind === "switch" ? `${label}: ${value ? "on" : "off"}` : `${label} ${String(value)}`,
    });
  }
  return out;
}

export function OverrideChips({ mode }: { mode: Mode }) {
  const [overrides, setOverrides, loaded] = useOverrides();
  if (!loaded) return null;
  const active = activeOverrides(overrides).filter(
    ({ field }) => mode === "site" || field.section === "page",
  );
  if (active.length === 0) return null;
  return (
    <ul className="flex flex-wrap items-center gap-1.5 px-4 pt-1" aria-label="Settings in force for this run">
      <li className="text-[11px] font-semibold uppercase tracking-[0.1em] text-faint">runs with</li>
      {active.map(({ field, text }) => (
        <li key={`${field.group}.${field.key}`}>
          <span className="inline-flex h-7 items-center gap-1 pill-shape border border-rule bg-sunk pl-2.5 pr-1 font-mono text-[11.5px] text-ink">
            {text}
            <button
              type="button"
              aria-label={`Clear ${field.label}`}
              title="Back to the default"
              onClick={() => setOverrides(withValue(overrides, field, undefined))}
              className="inline-flex size-5 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface hover:text-ink"
            >
              ×
            </button>
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function RunOptions({ mode }: { mode: Mode }) {
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [overrides, setOverrides, loaded] = useOverrides();
  const panelId = useId();
  const root = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  // Where the panel goes, in viewport coordinates. It is portalled to <body>: inside the
  // hero the prompt sits in a clipped, 3D-transformed frame, and an absolutely positioned
  // panel was cut off at the frame's edge (and `position: fixed` would be measured from the
  // transformed ancestor, not the viewport).
  // Below the button when the viewport has room there, above it otherwise -- the prompt
  // at the foot of the home page opened a panel the reader could not see the bottom of.
  // Either way the panel is no taller than the space it has and scrolls inside.
  const [place, setPlace] = useState<
    { left: number; width: number; maxHeight: number } & ({ top: number } | { bottom: number })
  >();

  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const anchor = root.current?.getBoundingClientRect();
      if (!anchor) return;
      const margin = 16;
      const gap = 8;
      const width = Math.min(480, window.innerWidth - 2 * margin);
      const left = Math.max(margin, Math.min(anchor.left, window.innerWidth - width - margin));
      const below = window.innerHeight - anchor.bottom - gap - margin;
      const above = anchor.top - gap - margin;
      // The panel wants about 560px; take the side that has it, else the roomier side.
      const wanted = 560;
      if (below >= wanted || below >= above) {
        setPlace({ left, width, top: anchor.bottom + gap, maxHeight: Math.max(160, below) });
      } else {
        setPlace({
          left,
          width,
          bottom: window.innerHeight - anchor.top + gap,
          maxHeight: Math.max(160, above),
        });
      }
    };
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open]);

  // The defaults are the engine's, read once the panel is first opened -- a page that
  // never opens it never asks.
  useEffect(() => {
    if (!open || config) return;
    api.config().then(setConfig).catch(() => setConfig(null));
  }, [open, config]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (root.current?.contains(target) || panel.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  const count = loaded ? activeOverrides(overrides).length : 0;
  const sections: Array<Field["section"]> = mode === "site" ? ["site", "page"] : ["page", "site"];

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={count ? `Options, ${count} changed` : "Options"}
        title="Options for this run"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex h-8 items-center gap-1.5 pill-shape border px-2.5 text-caption font-semibold transition-colors duration-(--dur-fast) ${
          open || count ? "border-rule-strong bg-sunk text-ink" : "border-rule text-muted hover:border-rule-strong hover:bg-sunk hover:text-ink"
        }`}
      >
        <svg aria-hidden width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <path d="M2 4.5h8M13 4.5h1M2 11.5h1M6 11.5h8" />
          <circle cx="11" cy="4.5" r="1.8" />
          <circle cx="4" cy="11.5" r="1.8" />
        </svg>
        Options
        {count > 0 && (
          <span className="tabular inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-ink px-1 font-mono text-[10px] font-bold text-inverse">
            {count}
          </span>
        )}
      </button>

      {open && place && createPortal(
        <div
          ref={panel}
          id={panelId}
          role="dialog"
          aria-label="Options for this run"
          style={{
            left: place.left,
            width: place.width,
            maxHeight: place.maxHeight,
            ...("top" in place ? { top: place.top } : { bottom: place.bottom }),
          }}
          className="fixed z-50 overflow-y-auto rounded-2xl border border-rule-strong bg-surface p-4 text-left shadow-[0_12px_40px_rgb(15_26_20/0.16)]"
        >
          <div className="flex items-center justify-between gap-3">
            <p className="text-[13px] font-bold text-ink">Options for this run</p>
            <div className="flex items-center gap-3 text-[12px]">
              {count > 0 && (
                <button type="button" onClick={() => setOverrides({})} className="font-semibold text-muted underline underline-offset-2 hover:text-ink">
                  Reset all
                </button>
              )}
              <Link href="/settings" className="font-semibold text-muted underline underline-offset-2 hover:text-ink">
                All settings →
              </Link>
            </div>
          </div>
          <p className="mt-1 text-[12px] text-muted">
            Saved in this browser and sent with every run. Empty means the engine&rsquo;s default.
          </p>

          {sections.map((section) => (
            <fieldset key={section} className="mt-4">
              <legend className="font-mono text-[11px] uppercase tracking-[0.12em] text-faint">
                {SECTION_TITLE[section]}
                {section === "site" && mode !== "site" && <span className="ml-2 normal-case tracking-normal">· applies to Run a site</span>}
              </legend>
              <div className="mt-2 divide-y divide-rule">
                {FIELDS.filter((field) => field.section === section).map((field) => {
                  const value = current(overrides, field);
                  const fallback = field.source ? config?.settings[field.source]?.value : undefined;
                  const id = `${panelId}-${field.group}-${field.key}`;
                  return (
                    <div key={`${field.group}.${field.key}`} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-0.5 py-2">
                      <label htmlFor={id} className="text-[12.5px] font-semibold text-ink">
                        {field.label}
                      </label>
                      {field.kind === "switch" ? (
                        <button
                          id={id}
                          type="button"
                          role="switch"
                          aria-checked={value === undefined ? Boolean(fallback) : Boolean(value)}
                          onClick={() => {
                            const now = value === undefined ? Boolean(fallback) : Boolean(value);
                            const next = !now;
                            // Back to the default when the reader lands on it, so no
                            // override is kept that says what the file already says.
                            setOverrides(withValue(overrides, field, fallback !== undefined && next === Boolean(fallback) ? undefined : next));
                          }}
                          className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
                            (value === undefined ? Boolean(fallback) : Boolean(value)) ? "bg-ink" : "bg-rule-strong"
                          }`}
                        >
                          <span
                            className={`absolute top-0.5 size-4 rounded-full bg-surface shadow transition-transform ${
                              (value === undefined ? Boolean(fallback) : Boolean(value)) ? "left-[1.125rem]" : "left-0.5"
                            }`}
                          />
                        </button>
                      ) : (
                        <input
                          id={id}
                          type={field.kind === "number" ? "number" : "text"}
                          inputMode={field.kind === "number" ? "decimal" : undefined}
                          min={field.kind === "number" ? 0 : undefined}
                          value={value === undefined ? "" : String(value)}
                          placeholder={fallback === undefined ? "" : String(fallback) || "none"}
                          onChange={(event) => {
                            const raw = event.target.value;
                            setOverrides(withValue(overrides, field, raw === "" ? undefined : field.kind === "number" ? Number(raw) : raw));
                          }}
                          className={`h-8 rounded-lg border border-rule bg-sunk px-2.5 font-mono text-[12px] text-ink outline-none placeholder:text-faint focus:border-rule-strong ${
                            field.kind === "number" ? "w-24 tabular" : "w-44"
                          }`}
                        />
                      )}
                      <p className="col-span-2 text-[11.5px] leading-snug text-muted">{field.hint}</p>
                    </div>
                  );
                })}
              </div>
            </fieldset>
          ))}
        </div>,
        document.body,
      )}
    </div>
  );
}
