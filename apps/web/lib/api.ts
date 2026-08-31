/**
 * Typed client for the webgraph API.
 *
 * Types are hand-mirrored from the FastAPI response models rather than generated, because
 * the surface is small and a codegen step would be more machinery than it earns here. If
 * the API grows, generate from `/openapi.json` instead of letting these drift.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type ReadingOrderMethod =
  | "geometric-xy-cut"
  /** Most blocks measured; the rest placed beside their source-order neighbours. */
  | "geometric-anchored"
  | "dom-fallback"
  | "single-block";

export interface PageInfo {
  url: string;
  content_hash: string;
  reading_order: ReadingOrderMethod;
  /** False means order was assumed from source, not measured from the rendered layout. */
  reading_order_measured: boolean;
  /** True when the page uses CSS to reorder content away from its source order. */
  dom_order_differs: boolean;
  blocks: number;
  frameworks: string[];
  requires_render: boolean;
  payloads: string[];
}

export interface Fact {
  value: unknown;
  confidence: number;
  extractor: string;
  modality: string;
  source: string | null;
  source_xpath: string | null;
}

export interface ExtractResponse {
  page: PageInfo;
  facts: Record<string, Fact>;
}

export interface TextResponse {
  page: PageInfo;
  text: string;
  /** Structure-preserving Markdown: headings, images, links, tables, code. */
  markdown: string;
  /** The same page with `<nav>` and `<footer>` removed. Empty when it declares neither. */
  content_markdown: string;
  images: string[];
  tables: number;
}

export interface HealthResponse {
  status: "ok";
  render_available: boolean;
  max_concurrent_renders: number;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    // A network-level failure here almost always means the API process is not running,
    // which is worth saying plainly rather than surfacing "Failed to fetch".
    throw new ApiError(
      `Cannot reach the API at ${API_BASE}. Is it running? Try: make api`,
      0,
    );
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Response body was not JSON; the status-based message stands.
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as T;
}

export interface ContextSource {
  heading: string;
  page_url: string;
  page_title: string;
  hops: number;
  score: number;
  /** Why this section is here, in words: "matched query", "linked from this section as …". */
  reason: string;
  chars: number;
  tier: "full" | "opening";
}

export interface ContextResponse {
  text: string;
  sources: ContextSource[];
  /** Pages named in the map tier but not included in full. */
  pages_mapped: string[];
  stats: Record<string, number>;
  graph: { pages: number; sections: number; entities: number; links: number; mentions: number };
}

export interface GraphEntity {
  key: string;
  type: string;
  name: string;
  /** Other names the site's own pages use for this subject. */
  aliases: string[];
  pages: string[];
}

export interface GraphHub {
  url: string;
  title: string;
  inbound: number;
  outbound: number;
  sections: number;
  /** Low means everything links here — navigation. High means a topic. */
  specificity: number;
}

export interface GraphSummary {
  root: string;
  counts: Record<string, number>;
  entities: GraphEntity[];
  hubs: GraphHub[];
  deepest: string[];
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),

  graphSummary: (url: string) =>
    request<GraphSummary>(`/api/site/graph/summary?url=${encodeURIComponent(url)}`),

  context: (input: {
    url: string;
    query: string;
    max_chars: number;
    max_hops: number;
  }) => request<ContextResponse>("/api/site/context", input),

  extract: (input: {
    url: string;
    schema: unknown;
    render: boolean;
    rtl: boolean;
  }) => request<ExtractResponse>("/api/extract", input),

  text: (input: { url: string; render: boolean; rtl: boolean }) =>
    request<TextResponse>("/api/text", input),
};

export const SCHEMA_PRESETS: ReadonlyArray<{
  label: string;
  description: string;
  schema: unknown;
}> = [
  {
    label: "Product",
    description: "Name, SKU and price from schema.org Product markup",
    schema: {
      type: "object",
      properties: {
        name: { type: "string" },
        sku: { type: "string" },
        description: { type: "string" },
        offers: {
          type: "object",
          properties: {
            price: { type: "number" },
            currency: { type: "string" },
          },
        },
      },
    },
  },
  {
    label: "Article",
    description: "Headline, author and publication date",
    schema: {
      type: "object",
      properties: {
        title: { type: "string" },
        author: { type: "string" },
        description: { type: "string" },
        datePublished: { type: "string" },
      },
    },
  },
  {
    label: "Pricing plan",
    description: "Plan name and price, for SaaS pricing pages",
    schema: {
      type: "object",
      properties: {
        name: { type: "string" },
        description: { type: "string" },
        offers: {
          type: "object",
          properties: {
            price: { type: "number" },
            currency: { type: "string" },
          },
        },
      },
    },
  },
];


/* ---------- Whole-site pipeline (streamed) ---------- */

export interface StageEvent {
  type: "stage";
  stage: "analyze" | "enumerate" | "extract";
  message: string;
  unlimited?: boolean;
}

export interface Technology {
  name: string;
  category: string;
  version: string | null;
  confidence: number;
  evidence: string;
}

export interface AnalysisEvent {
  type: "analysis";
  root: string;
  frameworks: string[];
  technologies: Technology[];
  payload_sources: string[];
  render_required: boolean;
  render_loses_content: boolean;
  static_chars: number;
  rendered_chars: number;
  union_chars: number;
  static_coverage: number;
  strategy: string;
}

export interface InventoryEvent {
  type: "inventory";
  source: string;
  advertised: number;
  checked: number;
  live: number;
  dead: number;
  liveness: number;
  fully_verified: boolean;
}

export interface FrontierEvent {
  type: "frontier";
  queued: number;
  discovered: number;
  from_sitemap: number;
  extracted: number;
  /** URLs newly accepted into the frontier. Clients rebuild the discovered set from these
   *  deltas; resending the whole frontier on every event would be quadratic. */
  new_urls: string[];
}

export interface PageEvent {
  type: "page";
  index: number;
  url: string;
  title: string;
  ok: boolean;
  error: string | null;
  chars: number;
  markdown: string;
  /** Same page with site chrome removed. Empty when chrome could not be identified. */
  content_markdown: string;
  images: string[];
  tables: number;
  strategy: string | null;
  depth: number;
  queued: number;
  discovered: number;
  extracted: number;
  failed: number;
  newly_queued: number;
  /** URLs this page contributed to the frontier. */
  new_urls: string[];
  pages_per_minute: number;
  totals: { chars: number; markdown: number; images: number; tables: number };
  /** Null when graph building is disabled. */
  graph: GraphStats | null;
}

export interface GraphStats {
  pages: number;
  sections: number;
  entities: number;
  links: number;
  mentions: number;
}

export interface DoneEvent {
  type: "done";
  pages_ok: number;
  pages_total: number;
  total_chars: number;
  total_markdown_chars: number;
  total_images: number;
  total_tables: number;
  failed: number;
  discovered: number;
  remaining_queued: number;
  exhausted: boolean;
  /** True when the crawl ended because the caller stopped it. */
  stopped: boolean;
  /** Repeated text blocks identified as site chrome. */
  chrome_blocks: number;
  /** Template slots that never vary across pages. */
  chrome_slots: number;
  entities: { type: string; pages: number; keys: string[] }[];
  graph: GraphStats | null;
  duration_seconds: number;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type SiteEvent =
  | StageEvent
  | AnalysisEvent
  | InventoryEvent
  | FrontierEvent
  | PageEvent
  | DoneEvent
  | ErrorEvent;

/**
 * Stream the whole-site pipeline.
 *
 * `fetch` + ReadableStream rather than `EventSource`, because EventSource is GET-only and
 * the request carries a JSON body. Events are newline-delimited SSE frames; the buffer is
 * carried across chunks since a frame can be split across TCP reads.
 */
export async function streamSite(
  input: { url: string; max_pages: number; concurrency: number; complete: boolean },
  onEvent: (event: SiteEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/site/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new ApiError(
      `Stream failed with status ${response.status}`,
      response.status,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as SiteEvent);
      } catch {
        // A malformed frame must not kill the stream.
      }
    }
  }
}
