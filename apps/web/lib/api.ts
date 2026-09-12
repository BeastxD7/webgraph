/**
 * Typed client for the webgraph API.
 *
 * Types are hand-mirrored from the FastAPI response models rather than generated, because
 * the surface is small and a codegen step would be more machinery than it earns here. If
 * the API grows, generate from `/openapi.json` instead of letting these drift.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

/**
 * Why the API cannot be reached, in the caller's terms.
 *
 * `NEXT_PUBLIC_API_BASE` is inlined at *build* time, not read at runtime. A deployment
 * built without it keeps the localhost default and then asks each visitor's own machine
 * for the API -- which fails with a generic network error that points at the wrong thing
 * entirely. That misconfiguration is worth naming explicitly, because the symptom looks
 * identical to a backend that is merely down.
 */
function unreachableMessage(): string {
  const local = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:|$|\/)/.test(API_BASE);
  const servedRemotely =
    typeof window !== "undefined" &&
    !/^(127\.0\.0\.1|localhost|\[::1\])$/.test(window.location.hostname);

  if (local && servedRemotely) {
    return (
      `This build points at ${API_BASE}, which is your own machine, not the server. ` +
      "Set NEXT_PUBLIC_API_BASE to the deployed API URL and redeploy -- it is baked in " +
      "at build time, so changing the variable alone is not enough."
    );
  }

  // A CORS rejection reaches JavaScript as an indistinguishable network failure: the
  // browser refuses to say more, on purpose. Naming it is the only help available, and it
  // is the expected state of a fresh deployment whose API has not been told this origin
  // exists yet -- exactly when a misleading "is it running?" costs the most time.
  if (!local && typeof window !== "undefined") {
    return (
      `Could not reach ${API_BASE} from ${window.location.origin}. If the API is up, the ` +
      "likely cause is CORS: it only answers origins listed in WEBGRAPH_ALLOWED_ORIGINS, " +
      "and this one may not be among them."
    );
  }

  return `Cannot reach the API at ${API_BASE}. Is it running? Try: make api`;
}

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
  /** The page reduced to its content: `<nav>`/`<footer>` removed, then the main-content
   *  boundary drawn around the densest run of prose. Empty when nothing was removed. */
  content_markdown: string;
  /** Steps that removed something, in order: "landmarks", "main-landmark", "block-model"
   *  or "main-content". */
  content_methods: string[];
  /** Blocks kept in `content_markdown`, out of `page.blocks`. */
  content_blocks: number;
  /** What kind of page this is, from a trained classifier: "article", "documentation",
   *  "service", "forum", "collection", "listing", "product", or "unknown". Reported only --
   *  content selection does not branch on it. */
  page_type: string;
  /** Probability assigned to `page_type`; 0 when unknown. */
  page_type_confidence: number;
  images: string[];
  tables: number;
}

export interface HealthResponse {
  status: "ok";
  render_available: boolean;
  max_concurrent_renders: number;
  /** False means this instance will fetch loopback and link-local addresses. */
  private_hosts_blocked: boolean;
  /** Server-side page ceiling per crawl. 0 means the frontier is crawled to exhaustion. */
  max_pages: number;
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
    // A network-level failure here almost always means the API process is not running or
    // the build points somewhere wrong, either of which is worth saying plainly rather
    // than surfacing "Failed to fetch".
    throw new ApiError(unreachableMessage(), 0);
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

/**
 * A batch about to be fetched, announced before the work starts.
 *
 * Completion events alone can only ever describe the past. This is what lets a live view show
 * the pages being fetched *now*, and remove each one as its result arrives.
 */
export interface FetchingEvent {
  type: "fetching";
  urls: string[];
  queued: number;
  extracted: number;
  failed: number;
}

export interface PageEvent {
  type: "page";
  index: number;
  url: string;
  /** How this address came to be in the crawl: by what method, from which page, and through
   *  which link text. Null only if it was never recorded. Everything the crawl reports
   *  should be answerable with "and how do you know"; this is that answer for the page
   *  existing at all. */
  citation: {
    /** "seed", "sitemap" or "link". */
    via: string;
    found_on: string | null;
    /** The words a reader would have clicked. Often the only human-readable reason a link
     *  was followed. */
    anchor: string | null;
    depth: number;
  } | null;
  title: string;
  ok: boolean;
  error: string | null;
  chars: number;
  markdown: string;
  /** The page reduced to its content: landmarks, cross-page chrome and boilerplate removed,
   *  then the main-content boundary drawn. Empty when nothing was removed. */
  content_markdown: string;
  /** Blocks kept in `content_markdown`, out of `blocks`. Null when content selection is off. */
  content_blocks: number | null;
  /** Which steps removed something, in order: "landmarks", "site-chrome", "main-content". */
  content_methods: string[];
  /** Blocks in the complete document. */
  blocks: number;
  /** What kind of page a trained classifier judged this to be: "article", "listing",
   *  "product", "forum", "collection", "documentation", "service", or "unknown" when no type
   *  was confident enough. Reported, and used to choose how the content boundary is drawn. */
  page_type: string;
  /** Probability the classifier assigned to `page_type`; 0 when unknown. */
  page_type_confidence: number;
  /** Why that type, strongest first. Each signal's weight is the probability the chosen type
   *  loses when the model is not allowed to see it -- measured, not narrated. */
  page_type_reasons: Array<{ says: string; weight: number }>;
  /** The type it nearly chose. Most of what "how sure" means is what came second. */
  page_type_runner_up: { type: string; confidence: number };
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

/**
 * The first frame of either stream: what this run is, and where the server wrote its trace.
 *
 * Sent before any work happens, and before the site crawl's queue wait, so a run that never
 * produced a page still has an identity. `options` are the ones actually applied after the
 * host's caps -- a log that reports what was asked for rather than what was run explains
 * nothing on the occasions the two differ.
 */
export interface RunEvent {
  type: "run";
  /** Server-side run id. The same id names the trace file and prefixes every line in it. */
  run: string;
  /** File name only, never a path: enough to find the trace, nothing about the server. */
  trace: string;
  url: string;
  mode: "page" | "site";
  engine: string;
  /** Server wall clock, seconds. The client's own clock is what the log measures against. */
  started: number;
  strategy?: string;
  render?: boolean;
  complete?: boolean;
  max_pages?: number;
  concurrency?: number;
}

export type SiteEvent =
  | RunEvent
  | StageEvent
  | AnalysisEvent
  | InventoryEvent
  | FrontierEvent
  | FetchingEvent
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
/** One stage of a single-page extraction, as the engine reports it. */
export type PageStageEvent =
  | RunEvent
  | { type: "stage"; stage: string; state: "running"; message: string }
  | {
      type: "resolve";
      stage: "resolve";
      at: number;
      url: string;
      strategy: string;
      static_chars: number;
      rendered_chars: number;
      union_chars: number;
      static_coverage: number;
      blocks_only_in_static: number;
      blocks_only_in_rendered: number;
      /** Set when the browser was unavailable or gave up. Not a failure: it says the result
       *  is the plain fetch alone, which a completeness claim has to account for. */
      render_error: string | null;
    }
  | {
      type: "parse";
      stage: "parse";
      at: number;
      blocks: number;
      words: number;
      reading_order: string;
      /** False means the order was assumed from source, not measured from a rendered
       *  layout. A reconstruction and a guess deserve different confidence. */
      reading_order_measured: boolean;
      dom_order_differs: boolean;
      content_hash: string;
      frameworks: string[];
      requires_render: boolean;
      kinds: Record<string, number>;
      payloads: string[];
    }
  | {
      type: "classify";
      stage: "classify";
      at: number;
      page_type: string;
      confidence: number;
      reasons: Array<{ says: string; weight: number }>;
      runner_up: { type: string; confidence: number };
      /** False when no model shipped. A page typed `unknown` because nothing could judge it
       *  and one the model declined to commit on are different facts. */
      available: boolean;
    }
  | {
      type: "select";
      stage: "select";
      at: number;
      kept: number;
      total: number;
      methods: string[];
      removed: Record<string, number>;
    }
  | {
      type: "done";
      stage: "done";
      at: number;
      url: string;
      title: string;
      text: string;
      markdown: string;
      content_markdown: string;
      images: string[];
      tables: number;
    }
  | { type: "error"; stage: string; message: string; at?: number };

/**
 * Stream one page, stage by stage.
 *
 * Shares the frame decoding with `streamSite` deliberately: a second parser for the same
 * wire format is a second place for a frame split across TCP reads to be mishandled.
 */
export async function streamPage(
  input: { url: string; render: boolean },
  onEvent: (event: PageStageEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamFrames("/api/text/stream", input, onEvent as (event: unknown) => void, signal);
}

/**
 * POST a body and read the Server-Sent Event frames that come back.
 *
 * `fetch` + ReadableStream rather than `EventSource`, because EventSource is GET-only and
 * these requests carry a JSON body. The buffer is carried across chunks because a frame can
 * be split across TCP reads -- and this lives in one function so that a second stream cannot
 * acquire a second, subtly different, version of that bug.
 */
async function streamFrames(
  path: string,
  input: unknown,
  onEvent: (event: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
      signal,
    });
  } catch (error) {
    // An aborted stream is the user closing the page, not a failure -- rethrow it as-is so
    // callers can tell the two apart.
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(unreachableMessage(), 0);
  }

  if (!response.ok || !response.body) {
    throw new ApiError(`Stream failed with status ${response.status}`, response.status);
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
        onEvent(JSON.parse(line.slice(6)));
      } catch {
        // A malformed frame must not kill the stream.
      }
    }
  }
}

export async function streamSite(
  input: { url: string; max_pages: number; concurrency: number; complete: boolean },
  onEvent: (event: SiteEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamFrames("/api/site/stream", input, onEvent as (event: unknown) => void, signal);
}
