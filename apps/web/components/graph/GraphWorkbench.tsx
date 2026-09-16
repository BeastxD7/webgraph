"use client";

import type { Route } from "next";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import Button from "@/components/ui/Button";
import Chip from "@/components/ui/Chip";
import { ApiError, api } from "@/lib/api";
import { type BuildStats, type KGGraph, type KGStats, TYPE_SLOTS, compactInt, kg, typeColor } from "@/lib/kg";
import { normalizeInput } from "@/lib/url";

import AskPanel from "./AskPanel";
import BuildPanel from "./BuildPanel";
import EntityDetail from "./EntityDetail";
import ExportPanel from "./ExportPanel";
import GraphViewLoader from "./GraphViewLoader";
import ProviderPanel from "./ProviderPanel";
import { INPUT } from "./fields";
import { usePath } from "./pathStore";

/**
 * The WebGraph page, in one client component so the panels can share the site, the flag,
 * the loaded graph and the selected node without a store.
 *
 * Order on the page follows the order of work: which site, which model, build, look, ask,
 * take it away. The graph view sits between build and ask because that is where its answer
 * to "what did the model find" is wanted, and the ask panel lights it up from below.
 */

type Flag = "checking" | "on" | "off" | "unreachable";

interface Loaded {
  url: string;
  seq: number;
  stats: KGStats | null;
  graph: KGGraph | null;
  error: string | null;
}

async function loadGraph(url: string): Promise<Omit<Loaded, "url" | "seq">> {
  try {
    const stats = await kg.stats(url);
    const graph = await kg.graph(url, 1500);
    return { stats, graph, error: null };
  } catch (cause) {
    // 404 is "no graph yet": the build panel is the next step, not an error.
    if (cause instanceof ApiError && cause.status === 404) return { stats: null, graph: null, error: null };
    return { stats: null, graph: null, error: cause instanceof Error ? cause.message : "Could not load the graph." };
  }
}

function useDark(): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const observer = new MutationObserver(onChange);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    media.addEventListener("change", onChange);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", onChange);
    };
  }, []);
  return useSyncExternalStore(
    subscribe,
    () => {
      const explicit = document.documentElement.getAttribute("data-theme");
      if (explicit === "dark") return true;
      if (explicit === "light") return false;
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    },
    () => false,
  );
}

export default function GraphWorkbench({ initialUrl }: { initialUrl: string }) {
  const [draft, setDraft] = useState(initialUrl);
  const [siteUrl, setSiteUrl] = useState(initialUrl);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [flag, setFlag] = useState<Flag>("checking");
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [reloads, setReloads] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [showList, setShowList] = useState(false);
  const dark = useDark();
  const path = usePath();

  useEffect(() => {
    let cancelled = false;
    api.health().then(
      (health) => {
        if (!cancelled) setFlag(health.webgraph ? "on" : "off");
      },
      () => {
        if (!cancelled) setFlag("unreachable");
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  // The graph for the current site, fetched when the site or the reload counter changes.
  // State is set only from the promise, and tagged with what it answers, so a slow answer for
  // a previous site is ignored rather than shown under the new one.
  useEffect(() => {
    if (flag !== "on" || !siteUrl) return;
    let cancelled = false;
    const seq = reloads;
    loadGraph(siteUrl).then((result) => {
      if (!cancelled) setLoaded({ ...result, url: siteUrl, seq });
    });
    return () => {
      cancelled = true;
    };
  }, [flag, siteUrl, reloads]);

  const current = loaded && loaded.url === siteUrl && loaded.seq === reloads ? loaded : null;
  const stats = current?.stats ?? null;
  const graph = current?.graph ?? null;
  const loadError = current?.error ?? null;
  const loading = flag === "on" && Boolean(siteUrl) && !current;
  const reload = useCallback(() => {
    setSelected(null);
    setReloads((n) => n + 1);
  }, []);
  const onBuilt = useCallback((_stats: BuildStats) => reload(), [reload]);

  const submitUrl = (event: React.FormEvent) => {
    event.preventDefault();
    const normalized = normalizeInput(draft);
    if (!normalized.ok) {
      setUrlError(normalized.reason ?? "That is not a website address.");
      return;
    }
    setUrlError(null);
    setDraft(normalized.url);
    setSiteUrl(normalized.url);
    setSelected(null);
    const params = new URLSearchParams(window.location.search);
    params.set("url", normalized.url);
    window.history.replaceState(null, "", `?${params.toString()}`);
  };

  const legend = useMemo(() => {
    if (!stats) return [];
    const rows = Object.entries(stats.types).sort((a, b) => b[1] - a[1]);
    const known = rows.filter(([type]) => TYPE_SLOTS.includes(type));
    const other = rows.filter(([type]) => !TYPE_SLOTS.includes(type)).reduce((sum, [, n]) => sum + n, 0);
    return [...known.map(([type, n]) => ({ type, n, color: typeColor(type, dark) })), ...(other ? [{ type: "other types", n: other, color: typeColor("", dark) }] : [])];
  }, [stats, dark]);

  const litNodes = useMemo(() => {
    if (!graph || !path.active) return [];
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    return [...path.nodes.entries()].map(([id, role]) => ({ id, role, node: byId.get(id) })).filter((x) => x.node);
  }, [graph, path]);

  const ready = flag === "on" && Boolean(siteUrl);
  const hasGraph = Boolean(stats && graph);

  return (
    <div className="space-y-8 pb-20">
      <header>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-display text-h1 text-ink">WebGraph</h1>
          <Chip tone={flag === "on" ? "available" : "coming"}>
            {flag === "on" ? "preview, behind a flag" : flag === "checking" ? "checking the API…" : flag === "off" ? "not enabled on this API" : "API unreachable"}
          </Chip>
        </div>
        <p className="measure-lede mt-4 text-body text-muted">
          A model reads every page of a crawl and builds a knowledge graph of the site. Nothing enters the graph without a verbatim quote from the page
          that states it, and every sentence of every answer cites one. Bring your own key, or a local model.
        </p>
      </header>

      {flag === "off" && (
        <section className="border-t border-rule pt-5">
          <p className="max-w-prose text-small text-ink">
            The API at this address has WebGraph switched off. Start it with <code className="rounded-sm bg-sunk px-1 py-0.5 font-mono text-[0.9em]">WEBGRAPH_KG=1</code>{" "}
            and reload; until then the <code className="font-mono">/api/graph/*</code> routes answer 404.{" "}
            <Link href={"/docs/webgraph" as Route} className="font-semibold underline underline-offset-2">
              Read how it works
            </Link>
            .
          </p>
        </section>
      )}
      {flag === "unreachable" && (
        <section className="border-t border-rule pt-5">
          <p role="alert" className="max-w-prose text-small text-bad">
            The API could not be reached. Start it (<code className="font-mono">make api</code>) or set <code className="font-mono">NEXT_PUBLIC_API_BASE</code>.
          </p>
        </section>
      )}

      {flag === "on" && (
        <>
          <section className="border-t border-rule pt-5">
            <h2 className="text-h3 font-bold text-ink">Site</h2>
            <p className="mt-1 max-w-prose text-caption text-muted">
              A site the crawler has already read. The API keeps each crawl on disk; if this one is not there yet,{" "}
              <Link href={{ pathname: "/extract", query: { url: siteUrl || "" } }} className="underline underline-offset-2">
                run the crawl first
              </Link>
              .
            </p>
            <form onSubmit={submitUrl} className="mt-3 flex flex-wrap gap-2">
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="https://example.edu/"
                aria-label="Site URL"
                className={`${INPUT} flex-1 basis-[18rem] font-mono text-code`}
              />
              <Button type="submit" variant="secondary" disabled={loading}>
                {loading ? "Loading…" : "Load"}
              </Button>
            </form>
            {urlError && (
              <p role="alert" className="mt-2 text-caption font-medium text-bad">
                {urlError}
              </p>
            )}
            {loadError && (
              <p role="alert" className="mt-2 text-caption font-medium text-bad">
                {loadError}
              </p>
            )}
            {stats && (
              <dl className="tabular mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
                {[
                  ["Entities", compactInt(stats.counts.entities)],
                  ["Relations", compactInt(stats.counts.relations)],
                  ["Quotes", compactInt(stats.counts.evidence)],
                  ["Pages cited", compactInt(stats.pages)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-label font-bold uppercase text-muted">{label}</dt>
                    <dd className="mt-1 font-display text-stat text-ink">{value}</dd>
                  </div>
                ))}
              </dl>
            )}
            {stats?.last_run && (
              <p className="mt-3 text-caption text-muted">
                Last read with <span className="font-mono">{stats.last_run.model}</span>
                {typeof stats.last_run.rejection_rate === "number" && <>; {Math.round(stats.last_run.rejection_rate * 100)}% of the model&rsquo;s assertions had no quote on the page and were dropped</>}
                {stats.last_run.truncated && <>; stopped early ({stats.last_run.truncated_reason?.replace(/_/g, " ")})</>}.
              </p>
            )}
            {!stats && !loading && siteUrl && !loadError && <p className="mt-3 text-caption text-muted">No knowledge graph for this site yet. Choose a model and build one below.</p>}
          </section>

          <ProviderPanel disabled={!ready} />

          <BuildPanel siteUrl={siteUrl} disabled={!ready} hasGraph={hasGraph} onBuilt={onBuilt} />

          {hasGraph && graph && (
            <section className="border-t border-rule pt-5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
                <h2 className="text-h3 font-bold text-ink">Graph</h2>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-muted">
                  <span>
                    {compactInt(graph.nodes.length)} of {compactInt(stats?.counts.entities ?? graph.nodes.length)} entities shown, by degree; size is the number of quotes
                  </span>
                  <button type="button" onClick={() => setShowList((v) => !v)} className="font-semibold text-ink underline-offset-2 hover:underline max-sm:hidden">
                    {showList ? "Graph view" : "List view"}
                  </button>
                </div>
              </div>

              <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-caption text-muted" aria-label="Colour by type">
                {legend.map((row) => (
                  <li key={row.type} className="flex items-center gap-1.5">
                    <span aria-hidden className="size-2.5 rounded-full" style={{ background: row.color }} />
                    {row.type} <span className="tabular text-faint">{row.n}</span>
                  </li>
                ))}
                {path.active && (
                  <>
                    <li className="ml-auto flex items-center gap-1.5">
                      <span aria-hidden className="size-2.5 rounded-full bg-warn" /> seeds
                    </li>
                    <li className="flex items-center gap-1.5">
                      <span aria-hidden className="size-2.5 rounded-full" style={{ background: dark ? "#3987e5" : "#2a78d6" }} /> reached
                    </li>
                    <li className="flex items-center gap-1.5">
                      <span aria-hidden className="size-2.5 rounded-full bg-accent" /> answer
                    </li>
                  </>
                )}
              </ul>

              <div className="mt-4 grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
                {showList ? (
                  <NodeList graph={graph} dark={dark} selected={selected} onSelect={setSelected} lit={path.active ? path.nodes : null} />
                ) : (
                  <div className="h-[28rem] overflow-hidden rounded-md border border-rule bg-surface max-sm:hidden sm:h-[32rem] lg:h-[36rem]">
                    <GraphViewLoader data={graph} dark={dark} selected={selected} onSelect={setSelected} className="h-full w-full" />
                  </div>
                )}
                {!showList && (
                  <div className="sm:hidden">
                    <NodeList graph={graph} dark={dark} selected={selected} onSelect={setSelected} lit={path.active ? path.nodes : null} />
                  </div>
                )}
                <div className="min-h-[12rem] min-w-0 rounded-md border border-rule bg-surface p-4 lg:h-[36rem]">
                  {selected ? (
                    <EntityDetail siteUrl={siteUrl} id={selected} dark={dark} onClose={() => setSelected(null)} onFocusEntity={setSelected} />
                  ) : (
                    <div className="text-caption text-muted">
                      <p>Click a node to see every mention of it with its quote and <span className="font-mono">url#xpath</span>.</p>
                      {litNodes.length > 0 && (
                        <ul className="mt-3 space-y-1">
                          {litNodes.slice(0, 14).map(({ id, role, node }) => (
                            <li key={id}>
                              <button type="button" onClick={() => setSelected(id)} className="text-left text-small text-ink underline-offset-2 hover:underline">
                                <span className={`mr-2 inline-block size-2 rounded-full align-middle ${role === "seed" ? "bg-warn" : role === "answer" ? "bg-accent" : "bg-faint"}`} />
                                {node!.name}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}

          {hasGraph && <AskPanel siteUrl={siteUrl} disabled={!ready} onFocusEntity={setSelected} />}

          {hasGraph && (
            <ExportPanel
              siteUrl={siteUrl}
              disabled={!ready}
              onDropped={reload}
            />
          )}
        </>
      )}
    </div>
  );
}

/** The graph as rows, for phones and for anyone who would rather read than pan. */
function NodeList({
  graph,
  dark,
  selected,
  onSelect,
  lit,
}: {
  graph: KGGraph;
  dark: boolean;
  selected: string | null;
  onSelect: (id: string) => void;
  lit: Map<string, string> | null;
}) {
  const [filter, setFilter] = useState("");
  const rows = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const sorted = [...graph.nodes].sort((a, b) => {
      const la = lit?.has(a.id) ? 1 : 0;
      const lb = lit?.has(b.id) ? 1 : 0;
      return lb - la || b.evidence - a.evidence || b.degree - a.degree;
    });
    return (needle ? sorted.filter((n) => n.name.toLowerCase().includes(needle) || n.type.toLowerCase().includes(needle)) : sorted).slice(0, 200);
  }, [graph, filter, lit]);

  return (
    <div className="min-w-0 overflow-hidden rounded-md border border-rule bg-surface">
      <div className="border-b border-rule p-3">
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by name or type" aria-label="Filter entities" className={INPUT} />
      </div>
      <ul className="max-h-[32rem] divide-y divide-rule overflow-y-auto">
        {rows.map((node) => {
          const role = lit?.get(node.id);
          return (
            <li key={node.id}>
              <button
                type="button"
                onClick={() => onSelect(node.id)}
                className={`flex w-full min-w-0 items-baseline gap-3 px-3 py-2 text-left text-small hover:bg-sunk ${selected === node.id ? "bg-sunk" : ""}`}
              >
                <span aria-hidden className="mt-1 size-2.5 shrink-0 self-center rounded-full" style={{ background: typeColor(node.type, dark) }} />
                <span className="min-w-0 flex-1 truncate font-semibold text-ink">{node.name}</span>
                <span className="shrink-0 text-caption text-muted max-sm:hidden">{node.type}</span>
                <span className="tabular shrink-0 text-caption text-faint" title="quotes">
                  {node.evidence}
                </span>
                {role && <Chip tone={role === "answer" ? "available" : role === "seed" ? "assumed" : "plain"}>{role}</Chip>}
              </button>
            </li>
          );
        })}
        {rows.length === 0 && <li className="px-3 py-3 text-caption text-muted">Nothing matches.</li>}
      </ul>
    </div>
  );
}
