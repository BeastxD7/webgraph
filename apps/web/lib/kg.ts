/**
 * Client for WebGraph, the inferred knowledge graph (`/api/graph/*`, behind `WEBGRAPH_KG`).
 *
 * Types mirror `apps/api/src/webgraph_api/kg_routes.py` and the event dicts in
 * `webgraph/kg/build.py`, `retrieve.py` and `neo4j.py` by hand, like `lib/api.ts` does for
 * the crawler. The provider key travels in the request body and nowhere else: this module
 * never writes it to storage, and the API redacts it from every error it echoes.
 */

import { API_BASE, requestJson, streamFrames } from "./api";

// -- provider ---------------------------------------------------------------------------

export type ProviderKind = "openai-compatible" | "anthropic" | "gemini";

/** What the API accepts as `provider` on build and query. Every field optional: the API
 *  falls back to its `WEBGRAPH_LLM_*` environment for anything left out. */
export interface ProviderIn {
  provider?: string;
  base_url?: string;
  model?: string;
  answer_model?: string;
  /** Sent with this request only. */
  api_key?: string;
  json_mode?: "json_schema" | "json_object" | "prompt";
  max_concurrency?: number;
}

/** The presets the engine knows (`webgraph/kg/providers.py` PRESETS), in the order shown. */
export const PRESETS: ReadonlyArray<{
  id: string;
  label: string;
  kind: ProviderKind;
  base_url: string;
  /** Environment variable the API reads when no key is sent. Empty for local servers. */
  key_env: string;
  local: boolean;
  example_model: string;
}> = [
  { id: "ollama", label: "Ollama (local)", kind: "openai-compatible", base_url: "http://localhost:11434/v1", key_env: "", local: true, example_model: "qwen2.5:7b-instruct" },
  { id: "lmstudio", label: "LM Studio (local)", kind: "openai-compatible", base_url: "http://localhost:1234/v1", key_env: "", local: true, example_model: "the loaded model's id" },
  { id: "vllm", label: "vLLM (local)", kind: "openai-compatible", base_url: "http://localhost:8000/v1", key_env: "", local: true, example_model: "the served model's id" },
  { id: "openai", label: "OpenAI", kind: "openai-compatible", base_url: "https://api.openai.com/v1", key_env: "OPENAI_API_KEY", local: false, example_model: "gpt-4o-mini" },
  { id: "anthropic", label: "Anthropic", kind: "anthropic", base_url: "https://api.anthropic.com", key_env: "ANTHROPIC_API_KEY", local: false, example_model: "claude-haiku-4-5" },
  { id: "gemini", label: "Google Gemini", kind: "gemini", base_url: "https://generativelanguage.googleapis.com/v1beta", key_env: "GEMINI_API_KEY", local: false, example_model: "gemini-2.5-flash" },
  { id: "groq", label: "Groq", kind: "openai-compatible", base_url: "https://api.groq.com/openai/v1", key_env: "GROQ_API_KEY", local: false, example_model: "llama-3.3-70b-versatile" },
  { id: "openrouter", label: "OpenRouter", kind: "openai-compatible", base_url: "https://openrouter.ai/api/v1", key_env: "OPENROUTER_API_KEY", local: false, example_model: "any openrouter model id" },
  { id: "together", label: "Together", kind: "openai-compatible", base_url: "https://api.together.xyz/v1", key_env: "TOGETHER_API_KEY", local: false, example_model: "a together model id" },
  { id: "deepseek", label: "DeepSeek", kind: "openai-compatible", base_url: "https://api.deepseek.com/v1", key_env: "DEEPSEEK_API_KEY", local: false, example_model: "deepseek-chat" },
  { id: "mistral", label: "Mistral", kind: "openai-compatible", base_url: "https://api.mistral.ai/v1", key_env: "MISTRAL_API_KEY", local: false, example_model: "mistral-small-latest" },
  { id: "xai", label: "xAI", kind: "openai-compatible", base_url: "https://api.x.ai/v1", key_env: "XAI_API_KEY", local: false, example_model: "grok-3-mini" },
  { id: "custom", label: "Custom OpenAI-compatible endpoint", kind: "openai-compatible", base_url: "", key_env: "", local: false, example_model: "the model id your server expects" },
];

// -- graph ------------------------------------------------------------------------------

export interface KGNode {
  id: string;
  type: string;
  name: string;
  /** Distinct source blocks that mention it. */
  evidence: number;
  degree: number;
  generic: boolean;
}

export interface KGEdge {
  id: string;
  source: string;
  target: string;
  predicate: string;
  /** Distinct source blocks that state it. */
  weight: number;
  fact: string;
}

export interface KGGraph {
  url: string;
  nodes: KGNode[];
  edges: KGEdge[];
}

export interface KGStats {
  url: string;
  counts: { entities: number; relations: number; evidence: number; mentions?: number; attributes?: number };
  types: Record<string, number>;
  open_types: Record<string, number>;
  predicates: Record<string, number>;
  pages: number;
  generic_entities: number;
  structured_entities: number;
  fts: boolean;
  /** The last build's stats, flattened, with `started`/`finished`/`model` beside them. */
  last_run: ({ id: number; started: number; finished: number; model: string } & Partial<BuildStats>) | null;
  path: string;
}

/** One verified quote: where it is (`url#xpath`) and what it says. */
export interface KGEvidence {
  id: string;
  page_key: string;
  url: string;
  section_id: string;
  block_xpath: string;
  span: [number, number];
  quote: string;
  content_hash: string;
  crawled_at: string;
  anchor: string;
}

export interface KGEntityDetail {
  id: string;
  type: string;
  name: string;
  aliases: string[];
  generic: boolean;
  extractor: string;
  mentions: Array<KGEvidence & { surface: string }>;
  attributes: Record<string, Array<KGEvidence & { value: string; unit: string }>>;
  relations: Array<{
    id: string;
    predicate: string;
    subject: { id: string; name: string };
    object: { id: string; name: string };
    fact: string;
    weight: number;
    evidence: KGEvidence[];
  }>;
}

// -- build events -----------------------------------------------------------------------

export interface BuildEstimate {
  type: "estimate";
  pages: number;
  sections: number;
  cached_sections: number;
  skipped: Record<string, number>;
  input_tokens: number;
  output_tokens: number;
  usd: number | null;
  model: string;
  prompt_version: string;
  caps: Record<string, unknown>;
  provider: { provider: string; base_url: string; model: string; answer_model: string | null; json_mode: string | null; has_key: boolean };
}

export interface BuildSection {
  type: "section";
  page: string;
  section_id: string;
  heading: string;
  entities?: number;
  relations?: number;
  accepted?: number;
  rejected?: number;
  rejected_reasons?: Record<string, number>;
  cached?: boolean;
  tokens?: { in: number; out: number };
  usd?: number | null;
  error?: string;
  done: number;
  total: number;
}

export interface BuildStats {
  model: string;
  pages: number;
  sections: number;
  sections_done: number;
  cache_hits: number;
  errors: number;
  entities: number;
  relations: number;
  accepted: number;
  rejected: number;
  rejected_reasons: Record<string, number>;
  rejection_rate: number;
  input_tokens: number;
  output_tokens: number;
  usd: number | null;
  seconds: number;
  truncated: boolean;
  truncated_reason: string | null;
}

export type BuildEvent =
  | BuildEstimate
  | { type: "stage"; stage: "extract" | "merge" | "store"; message: string }
  | BuildSection
  | { type: "budget"; reason: string; input_tokens: number; output_tokens: number; usd: number | null; cap: number; remaining_sections: number }
  | { type: "merge"; [key: string]: unknown }
  | { type: "done"; stats: BuildStats; truncated: boolean }
  | { type: "error"; message: string };

// -- query events -----------------------------------------------------------------------

export interface SeedsEvent {
  type: "seeds";
  entities: Array<{ id: string; name: string; type: string; score: number }>;
  sections: Array<{ id: string; heading: string; score: number }>;
}

export interface HopEdge {
  from_id: string;
  to_id: string;
  to_name: string;
  to_type: string;
  relation_id: string;
  predicate: string;
  score: number;
}

export interface HopEvent {
  type: "hop";
  hop: number;
  edges: HopEdge[];
}

export interface EvidenceItem {
  n: number;
  url: string;
  xpath: string;
  anchor: string;
  quote: string;
  section_id: string;
  heading: string;
  entity_ids: string[];
  source: string;
  score: number;
}

export interface QueryPath {
  seeds: string[];
  hops: Array<{ from_id: string; to_id: string; relation_id: string; hop: number; score: number }>;
  evidence: KGEvidence[];
  answer_nodes: string[];
}

export interface EvidenceEvent {
  type: "evidence";
  items: EvidenceItem[];
  path: QueryPath;
}

export interface Citation {
  n: number;
  url: string;
  xpath: string;
  anchor: string;
  quote: string;
  section_id: string;
  entity_ids: string[];
}

export interface Sentence {
  text: string;
  citations: number[];
  /** No verified block backs this sentence; shown flagged, never as fact. */
  unsupported: boolean;
}

export interface AnswerEvent {
  type: "answer";
  text: string;
  sentences: Sentence[];
  citations: Citation[];
  path: QueryPath;
  usage: { model?: string; input_tokens?: number; output_tokens?: number; usd?: number | null; [key: string]: unknown };
  abstained: boolean;
  unsupported: number;
}

export type QueryEvent =
  | SeedsEvent
  | HopEvent
  | EvidenceEvent
  | ({ type: "answer_delta" } & Sentence)
  | AnswerEvent
  | { type: "error"; message: string };

export type SyncEvent =
  | { type: "stage"; message: string }
  | { type: "batch"; label: string; rows: number; batches: number }
  | { type: "done"; counts: Record<string, number>; batches: number; typed_edges: boolean }
  | { type: "error"; message: string };

// -- client -----------------------------------------------------------------------------

const q = (params: Record<string, string | number | undefined>) =>
  Object.entries(params)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");

export const kg = {
  stats: (url: string) => requestJson<KGStats>(`/api/graph/stats?${q({ url })}`),

  graph: (url: string, limit = 1500, min_evidence = 1) =>
    requestJson<KGGraph>(`/api/graph?${q({ url, limit, min_evidence })}`),

  entity: (url: string, id: string) => requestJson<KGEntityDetail>(`/api/graph/entity?${q({ url, id })}`),

  drop: (url: string) =>
    requestJson<{ url: string; deleted: boolean }>(`/api/graph?${q({ url })}`, { method: "DELETE" }),

  exportUrl: (url: string, fmt: "jsonl" | "cypher" | "jsonld") => `${API_BASE}/api/graph/export?${q({ url, fmt })}`,
};

export async function streamGraphBuild(
  input: {
    url: string;
    provider: ProviderIn;
    budget?: { max_pages?: number; max_sections?: number; max_input_tokens?: number; max_usd?: number };
    rebuild?: boolean;
  },
  onEvent: (event: BuildEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamFrames("/api/graph/build", input, onEvent as (event: unknown) => void, signal);
}

export async function streamGraphQuery(
  input: { url: string; question: string; provider?: ProviderIn; max_hops?: number; no_model?: boolean },
  onEvent: (event: QueryEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamFrames("/api/graph/query", input, onEvent as (event: unknown) => void, signal);
}

export async function streamGraphSync(
  input: { url: string; uri: string; user: string; password: string; database?: string; typed_edges?: boolean },
  onEvent: (event: SyncEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamFrames("/api/graph/sync/neo4j", input, onEvent as (event: unknown) => void, signal);
}

// -- presentation helpers ---------------------------------------------------------------

/**
 * One hue per entity type, assigned in a fixed order so a type keeps its colour whatever
 * else is on screen. Eight slots; every further type is "other" in grey and is still named
 * in the legend and on the node. Passes the dataviz palette checks (lightness band, chroma,
 * CVD and normal-vision separation, contrast) on both grounds; the light palette warns on
 * contrast, which the node labels and the list view answer.
 */
export const TYPE_SLOTS: readonly string[] = [
  "Organization",
  "Person",
  "Course",
  "Event",
  "Place",
  "Product",
  "Document",
  "Offer",
];

const LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

export function typeColor(type: string, dark: boolean): string {
  const slot = TYPE_SLOTS.indexOf(type);
  if (slot < 0) return dark ? "#7c877f" : "#6b7a70"; // --faint in each theme
  return (dark ? DARK : LIGHT)[slot] ?? "#6b7a70";
}

export function shortUrl(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

/** `xpath` as a short, recognisable tail: the last two steps. */
export function shortXpath(xpath: string): string {
  const steps = xpath.split("/").filter(Boolean);
  return steps.length > 2 ? `…/${steps.slice(-2).join("/")}` : xpath;
}

export function money(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "price not set";
  if (usd === 0) return "$0.00";
  return usd < 0.01 ? `<$0.01` : `$${usd.toFixed(2)}`;
}

export function compactInt(n: number): string {
  return new Intl.NumberFormat("en", { notation: n >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(n);
}
