"use client";

import { useCallback, useRef, useState } from "react";

import Button from "@/components/ui/Button";
import { type SyncEvent, kg, streamGraphSync } from "@/lib/kg";

import { Field, Note, Panel, TextInput } from "./fields";

/**
 * Take the graph elsewhere. Three files (JSONL with the evidence first, a MERGE-only Cypher
 * script, JSON-LD with PROV-O selectors) and a direct push over bolt. Neo4j credentials go
 * in the body of the one sync request and are held by nothing afterwards -- the same rule as
 * the model key, and the API redacts `password` from any error it echoes.
 */
export default function ExportPanel({ siteUrl, disabled, onDropped }: { siteUrl: string; disabled: boolean; onDropped: () => void }) {
  const [uri, setUri] = useState("bolt://localhost:7687");
  const [user, setUser] = useState("neo4j");
  const [password, setPassword] = useState("");
  const [database, setDatabase] = useState("");
  const [typed, setTyped] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [dropping, setDropping] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const sync = useCallback(async () => {
    setSyncing(true);
    setError(null);
    setDone(null);
    setLog([]);
    const controller = new AbortController();
    abort.current = controller;
    try {
      await streamGraphSync(
        { url: siteUrl, uri, user, password, database: database || undefined, typed_edges: typed },
        (event: SyncEvent) => {
          switch (event.type) {
            case "stage":
              setLog((l) => [...l, event.message]);
              break;
            case "batch":
              setLog((l) => [...l, `${event.label}: ${event.rows} rows in ${event.batches} batch${event.batches === 1 ? "" : "es"}`]);
              break;
            case "done":
              setDone(
                `Synced ${Object.entries(event.counts)
                  .map(([k, v]) => `${v} ${k}`)
                  .join(", ")} in ${event.batches} batches${event.typed_edges ? " with typed relationship labels" : ""}.`,
              );
              break;
            case "error":
              setError(event.message);
              break;
            default:
              break;
          }
        },
        controller.signal,
      );
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === "AbortError")) {
        setError(cause instanceof Error ? cause.message : "The sync failed.");
      }
    } finally {
      setSyncing(false);
      abort.current = null;
    }
  }, [siteUrl, uri, user, password, database, typed]);

  const drop = useCallback(async () => {
    if (!window.confirm("Delete this site's knowledge graph from the server? The crawl stays; a rebuild reads from the cache.")) return;
    setDropping(true);
    try {
      await kg.drop(siteUrl);
      onDropped();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete the graph.");
    } finally {
      setDropping(false);
    }
  }, [siteUrl, onDropped]);

  return (
    <Panel title="Export and sync" lede="Every export carries the evidence: a node or edge without its quotes is not exported, because it does not exist.">
      <div className="flex flex-wrap gap-2">
        <Button href={kg.exportUrl(siteUrl, "jsonl")} external variant="secondary" aria-disabled={disabled}>
          JSONL
        </Button>
        <Button href={kg.exportUrl(siteUrl, "cypher")} external variant="secondary" aria-disabled={disabled}>
          Cypher
        </Button>
        <Button href={kg.exportUrl(siteUrl, "jsonld")} external variant="secondary" aria-disabled={disabled}>
          JSON-LD + PROV-O
        </Button>
        <Button variant="quiet" onClick={() => void drop()} disabled={disabled || dropping} className="ml-auto text-bad hover:text-bad">
          {dropping ? "Deleting…" : "Delete graph"}
        </Button>
      </div>

      <div className="mt-6 border-t border-rule pt-4">
        <p className="text-label font-bold uppercase text-muted">Neo4j</p>
        <p className="mt-1 max-w-prose text-caption text-muted">
          Pushes over bolt in <code className="font-mono">UNWIND $rows MERGE</code> batches; needs the API installed with the{" "}
          <code className="font-mono">kg-neo4j</code> extra. Credentials travel in this one request and are stored nowhere.
        </p>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <Field label="URI">
            <TextInput value={uri} disabled={syncing} onChange={(e) => setUri(e.target.value)} className="font-mono text-code" placeholder="bolt://host:7687" />
          </Field>
          <Field label="Database" hint="Optional">
            <TextInput value={database} disabled={syncing} onChange={(e) => setDatabase(e.target.value)} className="font-mono text-code" placeholder="neo4j" />
          </Field>
          <Field label="User">
            <TextInput value={user} disabled={syncing} autoComplete="off" onChange={(e) => setUser(e.target.value)} className="font-mono text-code" />
          </Field>
          <Field label="Password">
            <TextInput type="password" value={password} disabled={syncing} autoComplete="off" onChange={(e) => setPassword(e.target.value)} className="font-mono text-code" />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-caption text-muted">
            <input type="checkbox" checked={typed} disabled={syncing} onChange={(e) => setTyped(e.target.checked)} className="size-4 accent-accent" />
            Also write typed relationships (<code className="font-mono">:TEACHES</code> beside the portable <code className="font-mono">:RELATED</code>).
          </label>
          {syncing ? (
            <Button variant="secondary" onClick={() => abort.current?.abort()} className="ml-auto">
              Stop
            </Button>
          ) : (
            <Button onClick={() => void sync()} disabled={disabled || !uri || !user} className="ml-auto">
              Sync to Neo4j
            </Button>
          )}
        </div>
        {log.length > 0 && (
          <ul className="mt-3 space-y-0.5 font-mono text-[0.75rem] leading-relaxed text-faint">
            {log.slice(-8).map((line, index) => (
              <li key={`${index}-${line}`}>{line}</li>
            ))}
          </ul>
        )}
        {done && (
          <div className="mt-3">
            <Note tone="good">{done}</Note>
          </div>
        )}
        {error && (
          <div className="mt-3">
            <Note tone="bad">{error}</Note>
          </div>
        )}
      </div>
    </Panel>
  );
}
