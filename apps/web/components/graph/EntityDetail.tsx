"use client";

import { useEffect, useState } from "react";

import Button from "@/components/ui/Button";
import Chip from "@/components/ui/Chip";
import { type KGEntityDetail, kg, shortUrl, shortXpath, typeColor } from "@/lib/kg";

import { Note } from "./fields";

/**
 * One node, with everything the site says about it: each mention as a quote with its
 * `url#xpath`, each attribute with the quote that states it, each relation with its own.
 * There is no field here that lacks a source, because the store cannot hold one.
 */
export default function EntityDetail({
  siteUrl,
  id,
  dark,
  onClose,
  onFocusEntity,
}: {
  siteUrl: string;
  id: string;
  dark: boolean;
  onClose: () => void;
  onFocusEntity: (id: string) => void;
}) {
  // Keyed by id so a stale answer for the previous node is never shown under the new one.
  const [result, setResult] = useState<{ id: string; detail: KGEntityDetail | null; error: string | null } | null>(null);
  const current = result?.id === id ? result : null;
  const detail = current?.detail ?? null;
  const error = current?.error ?? null;

  useEffect(() => {
    let cancelled = false;
    kg.entity(siteUrl, id).then(
      (d) => {
        if (!cancelled) setResult({ id, detail: d, error: null });
      },
      (cause: unknown) => {
        if (!cancelled) setResult({ id, detail: null, error: cause instanceof Error ? cause.message : "Could not load the entity." });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [siteUrl, id]);

  return (
    <aside className="flex h-full min-h-0 flex-col" aria-label="Entity">
      <div className="flex items-start justify-between gap-3 border-b border-rule pb-3">
        <div className="min-w-0">
          {detail ? (
            <>
              <p className="flex items-center gap-2 text-caption text-muted">
                <span aria-hidden className="size-2.5 rounded-full" style={{ background: typeColor(detail.type, dark) }} />
                {detail.type}
                {detail.generic && <Chip tone="plain">generic</Chip>}
                {detail.extractor === "structured-data" && <Chip tone="measured">from JSON-LD</Chip>}
              </p>
              <h3 className="mt-1 text-h3 font-bold text-ink">{detail.name}</h3>
              {detail.aliases.length > 0 && <p className="mt-0.5 text-caption text-muted">also: {detail.aliases.join(", ")}</p>}
            </>
          ) : (
            <p className="text-caption text-muted">{error ?? "Loading…"}</p>
          )}
        </div>
        <Button variant="quiet" onClick={onClose} aria-label="Close">
          ✕
        </Button>
      </div>

      {error && (
        <div className="mt-3">
          <Note tone="bad">{error}</Note>
        </div>
      )}

      {detail && (
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {Object.keys(detail.attributes).length > 0 && (
            <section className="mt-4">
              <p className="text-label font-bold uppercase text-muted">Attributes</p>
              <dl className="mt-2">
                {Object.entries(detail.attributes).map(([key, values]) => (
                  <div key={key} className="border-b border-rule py-2">
                    <dt className="text-small font-semibold text-ink">{key.replace(/_/g, " ")}</dt>
                    {values.map((v) => (
                      <dd key={v.id} className="mt-1">
                        <p className="text-small text-ink">
                          {v.value}
                          {v.unit && <span className="text-muted"> {v.unit}</span>}
                        </p>
                        <Quote quote={v.quote} anchor={v.anchor} url={v.url} xpath={v.block_xpath} />
                      </dd>
                    ))}
                  </div>
                ))}
              </dl>
            </section>
          )}

          {detail.relations.length > 0 && (
            <section className="mt-4">
              <p className="text-label font-bold uppercase text-muted">Relations</p>
              <ul className="mt-2">
                {detail.relations.map((r) => {
                  const outgoing = r.subject.id === detail.id;
                  const other = outgoing ? r.object : r.subject;
                  return (
                    <li key={r.id} className="border-b border-rule py-2">
                      <p className="text-small text-ink">
                        {outgoing ? (
                          <>
                            <span className="font-mono text-[0.75rem] text-faint">{r.predicate}</span>{" "}
                            <button type="button" onClick={() => onFocusEntity(other.id)} className="font-semibold underline-offset-2 hover:underline">
                              {other.name}
                            </button>
                          </>
                        ) : (
                          <>
                            <button type="button" onClick={() => onFocusEntity(other.id)} className="font-semibold underline-offset-2 hover:underline">
                              {other.name}
                            </button>{" "}
                            <span className="font-mono text-[0.75rem] text-faint">{r.predicate}</span> this
                          </>
                        )}
                        {r.weight > 1 && <span className="ml-2 text-caption text-muted">stated in {r.weight} blocks</span>}
                      </p>
                      {r.evidence[0] && <Quote quote={r.evidence[0].quote} anchor={r.evidence[0].anchor} url={r.evidence[0].url} xpath={r.evidence[0].block_xpath} />}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          <section className="mt-4">
            <p className="text-label font-bold uppercase text-muted">
              Mentions <span className="normal-case tracking-normal">({detail.mentions.length})</span>
            </p>
            <ul className="mt-2">
              {detail.mentions.slice(0, 40).map((m) => (
                <li key={m.id} className="border-b border-rule py-2">
                  {m.surface !== detail.name && <p className="text-caption text-muted">as &ldquo;{m.surface}&rdquo;</p>}
                  <Quote quote={m.quote} anchor={m.anchor} url={m.url} xpath={m.block_xpath} />
                </li>
              ))}
              {detail.mentions.length > 40 && <li className="py-2 text-caption text-faint">+{detail.mentions.length - 40} more</li>}
            </ul>
          </section>
        </div>
      )}
    </aside>
  );
}

function Quote({ quote, anchor, url, xpath }: { quote: string; anchor: string; url: string; xpath: string }) {
  return (
    <div className="mt-1">
      <blockquote className="text-small text-ink">&ldquo;{quote}&rdquo;</blockquote>
      <a href={anchor} target="_blank" rel="noreferrer" className="font-mono text-[0.75rem] text-muted underline-offset-2 hover:text-ink hover:underline">
        {shortUrl(url)}#{shortXpath(xpath)}
      </a>
    </div>
  );
}
