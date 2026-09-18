"use client";

import { useEffect, useMemo, useState } from "react";

import { api, type ConfigResponse } from "@/lib/api";
import { type Overrides, useOverrides } from "@/lib/options";

/**
 * Maps a request field to the config.py name that holds its default, so each control can
 * show the file's value and comment beside it. The config.py name is the source of truth;
 * this table only says which request field changes which one.
 */
const SOURCE: Record<"crawl" | "fetch" | "renderOptions", Record<string, string>> = {
  crawl: {
    max_depth: "CRAWL_MAX_DEPTH",
    strict_domain: "CRAWL_STRICT_DOMAIN",
    within_path: "CRAWL_WITHIN_PATH",
    include_paths: "CRAWL_INCLUDE_PATHS",
    exclude_paths: "CRAWL_EXCLUDE_PATHS",
    delay_seconds: "CRAWL_DELAY_SECONDS",
    verify_inventory: "CRAWL_VERIFY_INVENTORY",
    follow_links: "CRAWL_FOLLOW_LINKS",
    discovery_limit: "CRAWL_DISCOVERY_LIMIT",
    sitemap_limit: "CRAWL_SITEMAP_LIMIT",
    respect_robots: "CRAWL_RESPECT_ROBOTS",
    remove_chrome: "CRAWL_REMOVE_CHROME",
    main_content: "CRAWL_MAIN_CONTENT",
  },
  fetch: { timeout_seconds: "FETCH_TIMEOUT_SECONDS", retries: "FETCH_RETRIES" },
  renderOptions: {
    timeout_ms: "RENDER_TIMEOUT_MS",
    wait_until: "RENDER_WAIT_UNTIL",
    settle_ms: "RENDER_SETTLE_MS",
    dismiss_gates: "RENDER_DISMISS_GATES",
    reveal_collapsed: "RENDER_REVEAL_COLLAPSED",
    viewport_width: "RENDER_VIEWPORT_WIDTH",
    viewport_height: "RENDER_VIEWPORT_HEIGHT",
  },
};

const GROUP_TITLE = {
  crawl: "Crawling a whole site",
  fetch: "Fetching (plain HTTP)",
  renderOptions: "Rendering (real browser)",
} as const;

const WAIT_UNTIL = ["commit", "domcontentloaded", "load", "networkidle"] as const;

type Group = keyof typeof SOURCE;
type Scalar = number | boolean | string;

function Control({
  group,
  field,
  setting,
  current,
  onChange,
}: {
  group: Group;
  field: string;
  setting: { value: unknown; comment: string } | undefined;
  current: Scalar | undefined;
  onChange: (value: Scalar | undefined) => void;
}) {
  const fallback = setting?.value;
  const overridden = current !== undefined;
  const id = `${group}-${field}`;
  const label = field.replace(/_/g, " ");

  let input;
  if (typeof fallback === "boolean") {
    const value = overridden ? Boolean(current) : fallback;
    input = (
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={value}
        onClick={() => onChange(!value)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${value ? "bg-leaf-600" : "bg-line-strong"}`}
      >
        <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-transform ${value ? "left-[1.375rem]" : "left-0.5"}`} />
      </button>
    );
  } else if (field === "wait_until") {
    input = (
      <select
        id={id}
        value={String(overridden ? current : fallback)}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg border border-line bg-haze px-2.5 py-1.5 font-mono text-[12.5px]"
      >
        {WAIT_UNTIL.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    );
  } else if (typeof fallback === "string") {
    // A text setting: path patterns, comma-separated. Empty means "no override", so the
    // default (usually nothing) applies again.
    input = (
      <input
        id={id}
        type="text"
        value={overridden ? String(current) : ""}
        placeholder={fallback ? String(fallback) : field.includes("paths") ? "e.g. ^/docs/, ^/blog/" : ""}
        onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value)}
        className="w-full max-w-md rounded-lg border border-line bg-haze px-2.5 py-1.5 font-mono text-[12.5px]"
      />
    );
  } else {
    input = (
      <input
        id={id}
        type="number"
        inputMode="decimal"
        step={field.includes("seconds") ? 0.1 : 1}
        value={overridden ? String(current) : ""}
        placeholder={String(fallback ?? "")}
        onChange={(event) => {
          const raw = event.target.value;
          onChange(raw === "" ? undefined : Number(raw));
        }}
        className="tabular w-32 rounded-lg border border-line bg-haze px-2.5 py-1.5 font-mono text-[12.5px]"
      />
    );
  }

  return (
    <div className="grid gap-x-6 gap-y-2 border-b border-line-soft py-3.5 last:border-b-0 sm:grid-cols-[14rem_1fr]">
      <div className="flex items-start justify-between gap-3 sm:flex-col sm:items-start sm:gap-1">
        <label htmlFor={id} className="text-[13.5px] font-semibold capitalize">{label}</label>
        {overridden && (
          <button
            type="button"
            onClick={() => onChange(undefined)}
            className="text-[11.5px] font-semibold text-leaf-700 underline underline-offset-2"
          >
            reset to {String(fallback)}
          </button>
        )}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-3">
          {input}
          {!overridden && (
            <span className="text-[11.5px] text-ink-faint">
              default {typeof fallback === "boolean" ? (fallback ? "on" : "off") : String(fallback)}
            </span>
          )}
        </div>
        {setting?.comment && (
          <p className="mt-1.5 max-w-[60ch] text-[12.5px] leading-relaxed text-ink-faint">{setting.comment}</p>
        )}
      </div>
    </div>
  );
}

export default function SettingsPanel() {
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overrides, setOverrides, loaded] = useOverrides();

  useEffect(() => {
    api.config().then(setConfig).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, []);

  const overriddenCount = useMemo(
    () =>
      Object.values(overrides.crawl ?? {}).length +
      Object.values(overrides.fetch ?? {}).length +
      Object.values(overrides.renderOptions ?? {}).length +
      (overrides.max_pages !== undefined ? 1 : 0) +
      (overrides.concurrency !== undefined ? 1 : 0),
    [overrides],
  );

  const update = (group: Group, field: string, value: Scalar | undefined) => {
    const next: Overrides = { ...overrides, [group]: { ...(overrides[group] ?? {}) } };
    const bucket = next[group] as Record<string, Scalar>;
    if (value === undefined) delete bucket[field];
    else bucket[field] = value;
    setOverrides(next);
  };

  if (error) {
    return <p role="alert" className="rounded-2xl border border-flag-bad/25 bg-flag-bad/5 px-5 py-4 text-[13.5px] font-semibold text-flag-bad">{error}</p>;
  }
  if (!config || !loaded) {
    return <p className="text-[13.5px] text-ink-faint">Loading the engine&rsquo;s settings…</p>;
  }

  const readOnly = Object.entries(config.settings).filter(
    ([name]) => !Object.values(SOURCE).some((map) => Object.values(map).includes(name)),
  );
  const sections = new Map<string, Array<[string, ConfigResponse["settings"][string]]>>();
  for (const entry of readOnly) {
    const list = sections.get(entry[1].section) ?? [];
    list.push(entry);
    sections.set(entry[1].section, list);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-line bg-surface px-5 py-3.5 shadow-card">
        <span className="text-[13px] text-ink-soft">
          {overriddenCount === 0
            ? "Everything is at the file's defaults."
            : `${overriddenCount} setting${overriddenCount === 1 ? "" : "s"} changed from the defaults. Saved in this browser.`}
        </span>
        {overriddenCount > 0 && (
          <button
            type="button"
            onClick={() => setOverrides({})}
            className="ml-auto rounded-full border border-line px-3.5 py-1.5 text-[12.5px] font-bold text-ink-soft transition-colors hover:bg-haze"
          >
            Reset everything
          </button>
        )}
      </div>

      <section className="rounded-2xl border border-line bg-surface p-5 shadow-card">
        <h2 className="text-[15px] font-extrabold tracking-tight">Page budget</h2>
        <p className="mt-1 text-[12.5px] text-ink-faint">
          These two travel as top-level request fields rather than through config.py.
          {(config.caps.max_pages ?? 0) > 0 && ` This host caps pages at ${config.caps.max_pages}.`}
          {(config.caps.max_concurrency ?? 0) > 0 && ` Concurrency is capped at ${config.caps.max_concurrency}.`}
        </p>
        <div className="mt-2">
          <Control
            group="crawl"
            field="max_pages"
            setting={{ value: config.settings.CRAWL_MAX_PAGES?.value ?? 0, comment: config.settings.CRAWL_MAX_PAGES?.comment ?? "" }}
            current={overrides.max_pages}
            onChange={(value) => setOverrides({ ...overrides, max_pages: typeof value === "number" ? value : undefined })}
          />
          <Control
            group="crawl"
            field="concurrency"
            setting={{ value: 6, comment: "Pages fetched in parallel within one crawl, as the web client requests it." }}
            current={overrides.concurrency}
            onChange={(value) => setOverrides({ ...overrides, concurrency: typeof value === "number" ? value : undefined })}
          />
        </div>
      </section>

      {(Object.keys(SOURCE) as Group[]).map((group) => (
        <section key={group} className="rounded-2xl border border-line bg-surface p-5 shadow-card">
          <h2 className="text-[15px] font-extrabold tracking-tight">{GROUP_TITLE[group]}</h2>
          <div className="mt-2">
            {config.overridable[group].map((field) => (
              <Control
                key={field}
                group={group}
                field={field}
                setting={config.settings[SOURCE[group][field] ?? ""]}
                current={(overrides[group] as Record<string, Scalar> | undefined)?.[field]}
                onChange={(value) => update(group, field, value)}
              />
            ))}
          </div>
        </section>
      ))}

      <details className="rounded-2xl border border-line bg-surface p-5 shadow-card">
        <summary className="cursor-pointer text-[15px] font-extrabold tracking-tight">
          Everything else in config.py
          <span className="ml-2 text-[12.5px] font-medium text-ink-faint">read-only here · {readOnly.length} settings</span>
        </summary>
        <p className="mt-2 text-[12.5px] text-ink-faint">
          A request cannot change these; edit the file and restart the API.
        </p>
        {[...sections.entries()].map(([section, entries]) => (
          <div key={section} className="mt-5">
            <h3 className="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-faint">{section}</h3>
            <dl className="mt-2">
              {entries.map(([name, setting]) => (
                <div key={name} className="grid gap-x-6 gap-y-1 border-b border-line-soft py-2.5 last:border-b-0 sm:grid-cols-[16rem_1fr]">
                  <dt className="font-mono text-[12px] font-semibold">{name}</dt>
                  <dd className="min-w-0">
                    <span className="tabular font-mono text-[12px] text-ink-soft">{JSON.stringify(setting.value)}</span>
                    {setting.comment && <p className="mt-0.5 max-w-[60ch] text-[12px] leading-relaxed text-ink-faint">{setting.comment}</p>}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </details>
    </div>
  );
}
