"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import Button from "@/components/ui/Button";
import Chip from "@/components/ui/Chip";
import {
  type AnswerEvent,
  type Citation,
  type EvidenceItem,
  type HopEvent,
  type QueryEvent,
  type SeedsEvent,
  type Sentence,
  money,
  shortUrl,
  shortXpath,
  streamGraphQuery,
} from "@/lib/kg";
import { providerBody, useApiKey, useProviderPrefs } from "@/lib/kgSettings";

import { Note, Panel, TextInput } from "./fields";
import { pathStore } from "./pathStore";

/** The model's `[n]` markers are rendered as superscripts beside the sentence, not twice. */
function stripMarkers(text: string): string {
  return text.replace(/\s*\[\d+\]/g, "").replace(/\s+([.!?])/g, "$1").trim();
}

/**
 * Ask the graph. Every sentence of the answer cites a numbered quote; a sentence the model
 * wrote with no quote behind it is shown, flagged, and never as fact. The path the question
 * took -- seeds, hops, chosen evidence -- streams into the graph view as it happens through
 * `pathStore`, and is listed here for the reader who wants the same thing in words.
 */
export default function AskPanel({
  siteUrl,
  disabled,
  onFocusEntity,
}: {
  siteUrl: string;
  disabled: boolean;
  onFocusEntity: (id: string) => void;
}) {
  const [prefs] = useProviderPrefs();
  const [apiKey] = useApiKey();
  const [question, setQuestion] = useState("");
  const [useModel, setUseModel] = useState(true);
  const [running, setRunning] = useState(false);
  const [seeds, setSeeds] = useState<SeedsEvent | null>(null);
  const [hops, setHops] = useState<HopEvent[]>([]);
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [sentences, setSentences] = useState<Sentence[]>([]);
  const [answer, setAnswer] = useState<AnswerEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      abort.current?.abort();
      pathStore.reset();
    },
    [],
  );

  const ask = useCallback(
    async (text: string) => {
      const q = text.trim();
      if (!q) return;
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setRunning(true);
      setError(null);
      setSeeds(null);
      setHops([]);
      setEvidence([]);
      setSentences([]);
      setAnswer(null);
      pathStore.begin();
      try {
        await streamGraphQuery(
          { url: siteUrl, question: q, provider: useModel ? providerBody(prefs, apiKey) : undefined, no_model: !useModel, max_hops: 2 },
          (event: QueryEvent) => {
            pathStore.apply(event);
            switch (event.type) {
              case "seeds":
                setSeeds(event);
                break;
              case "hop":
                setHops((h) => [...h, event]);
                break;
              case "evidence":
                setEvidence(event.items);
                break;
              case "answer_delta":
                setSentences((s) => [...s, { text: event.text, citations: event.citations, unsupported: event.unsupported }]);
                break;
              case "answer":
                setAnswer(event);
                setSentences(event.sentences);
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
          setError(cause instanceof Error ? cause.message : "The question failed.");
        }
      } finally {
        if (abort.current === controller) {
          setRunning(false);
          abort.current = null;
        }
      }
    },
    [siteUrl, prefs, apiKey, useModel],
  );

  const citationByN = new Map<number, Citation | EvidenceItem>();
  for (const item of evidence) citationByN.set(item.n, item);
  for (const item of answer?.citations ?? []) citationByN.set(item.n, item);

  return (
    <Panel
      title="Ask"
      lede="Seeds are found by text search over entities, facts and sections; the graph is walked two hops out; the best-supported quotes go to the answer model. Every sentence must cite one of them."
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
        className="flex flex-wrap gap-2"
      >
        <TextInput
          value={question}
          disabled={disabled}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="What does this site say about…"
          aria-label="Question"
          className="flex-1 basis-[16rem]"
        />
        <Button type="submit" disabled={disabled || !question.trim() || running}>
          {running ? "Asking…" : "Ask"}
        </Button>
        {running && (
          <Button
            variant="secondary"
            onClick={() => {
              abort.current?.abort();
              abort.current = null;
              setRunning(false);
            }}
          >
            Stop
          </Button>
        )}
      </form>
      <label className="mt-2 flex items-center gap-2 text-caption text-muted">
        <input type="checkbox" checked={!useModel} onChange={(e) => setUseModel(!e.target.checked)} className="size-4 accent-accent" />
        No model: return the top quotes as the answer, unparaphrased.
      </label>

      {error && (
        <div className="mt-3">
          <Note tone="bad">{error}</Note>
        </div>
      )}

      {(seeds || hops.length > 0) && (
        <div className="mt-5 border-t border-rule pt-4">
          <p className="text-label font-bold uppercase text-muted">Path</p>
          <ol className="mt-2 space-y-1.5 text-small">
            {seeds && (
              <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <Chip tone="assumed">seeds</Chip>
                <span className="text-muted">
                  {seeds.entities.length} entities, {seeds.sections.length} sections matched:
                </span>
                {seeds.entities.slice(0, 8).map((e) => (
                  <button key={e.id} type="button" onClick={() => onFocusEntity(e.id)} className="font-semibold text-ink underline-offset-2 hover:underline">
                    {e.name}
                  </button>
                ))}
                {seeds.entities.length > 8 && <span className="text-faint">+{seeds.entities.length - 8}</span>}
              </li>
            )}
            {hops.map((hop) => (
              <li key={hop.hop} className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <Chip tone="plain">hop {hop.hop}</Chip>
                <span className="text-muted">{hop.edges.length} edges crossed:</span>
                {hop.edges.slice(0, 6).map((edge) => (
                  <button
                    key={`${edge.from_id}-${edge.relation_id}-${edge.to_id}`}
                    type="button"
                    onClick={() => onFocusEntity(edge.to_id)}
                    className="text-ink underline-offset-2 hover:underline"
                  >
                    <span className="font-mono text-[0.75rem] text-faint">{edge.predicate}</span> {edge.to_name}
                  </button>
                ))}
                {hop.edges.length > 6 && <span className="text-faint">+{hop.edges.length - 6}</span>}
              </li>
            ))}
            {evidence.length > 0 && (
              <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <Chip tone="measured">evidence</Chip>
                <span className="text-muted">
                  {evidence.length} quotes chosen ({evidence.filter((e) => e.source === "graph").length} reached through the graph)
                </span>
              </li>
            )}
          </ol>
        </div>
      )}

      {(sentences.length > 0 || answer) && (
        <div className="mt-5 border-t border-rule pt-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <p className="text-label font-bold uppercase text-muted">Answer</p>
            {answer?.abstained && <Chip tone="refused">the site does not state it</Chip>}
            {answer && answer.unsupported > 0 && <Chip tone="assumed">{answer.unsupported} unsupported</Chip>}
            {answer && (
              <span className="ml-auto text-caption text-faint">
                {answer.usage.model === "none" ? "extractive, no model" : `${answer.usage.model ?? "model"} · ${money(answer.usage.usd)}`}
              </span>
            )}
          </div>
          <div className="mt-2 max-w-prose text-body text-ink">
            {sentences.map((sentence, index) => (
              <span key={`${index}-${sentence.text.slice(0, 24)}`} className={sentence.unsupported ? "rounded-sm bg-warn-soft px-0.5 text-warn" : ""}>
                {stripMarkers(sentence.text)}
                {sentence.citations.map((n) => (
                  <a key={n} href={`#kg-cite-${n}`} className="ml-0.5 align-super font-mono text-[0.7rem] font-semibold text-accent-ink" title={citationByN.get(n)?.quote}>
                    [{n}]
                  </a>
                ))}
                {sentence.unsupported && (
                  <span className="ml-1 align-super font-mono text-[0.7rem] font-semibold text-warn" title="No verified quote backs this sentence">
                    [unsupported]
                  </span>
                )}{" "}
              </span>
            ))}
          </div>
        </div>
      )}

      {evidence.length > 0 && (
        <div className="mt-5 border-t border-rule pt-4">
          <p className="text-label font-bold uppercase text-muted">Sources</p>
          <ol className="mt-2 divide-y divide-rule">
            {evidence.map((item) => {
              const cited = answer ? answer.citations.some((c) => c.n === item.n) : true;
              return (
                <li key={item.n} id={`kg-cite-${item.n}`} className={`grid gap-x-3 gap-y-1 py-2.5 sm:grid-cols-[2.5rem_1fr] ${cited || !answer ? "" : "opacity-60"}`}>
                  <span className="font-mono text-code font-semibold text-accent-ink">[{item.n}]</span>
                  <div className="min-w-0">
                    <blockquote className="text-small text-ink">&ldquo;{item.quote}&rdquo;</blockquote>
                    <p className="mt-1 flex flex-wrap items-baseline gap-x-2 text-caption text-muted">
                      <a href={item.anchor} target="_blank" rel="noreferrer" className="font-mono text-[0.75rem] underline-offset-2 hover:text-ink hover:underline">
                        {shortUrl(item.url)}#{shortXpath(item.xpath)}
                      </a>
                      {item.heading && <span>{item.heading}</span>}
                      <span className="text-faint">via {item.source}</span>
                      {item.entity_ids.slice(0, 3).map((id) => (
                        <button key={id} type="button" onClick={() => onFocusEntity(id)} className="text-faint underline-offset-2 hover:text-ink hover:underline">
                          show node
                        </button>
                      ))}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </Panel>
  );
}
