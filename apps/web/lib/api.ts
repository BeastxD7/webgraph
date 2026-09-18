/**
 * Typed client for the webgraph API.
 *
 * Types are hand-mirrored from the FastAPI response models rather than generated, because
 * the surface is small and a codegen step would be more machinery than it earns here. If
 * the API grows, generate from `/openapi.json` instead of letting these drift.
 */

/**
 * Where the API is. `NEXT_PUBLIC_API_BASE=/` means "this origin": the requests go to
 * `/api/...` on the web server itself, which proxies them (`next.config.ts` rewrites) to
 * the API -- one host, one tunnel, no CORS. Anything else is an absolute origin.
 */
const configuredBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
export const API_BASE = configuredBase === "/" ? "" : configuredBase.replace(/\/+$/, "");

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

  return `Cannot reach the API at ${API_BASE || "this origin's /api"}. Is it running? Try: make api`;
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

/** Why these fields and not others, when the engine chose the schema rather than the caller. */
export interface SchemaChoice {
  page_type: string;
  confidence: number;
  fields: string[];
  /** The `@type` of every node accepted as describing this page. Empty is a real answer:
   *  the page shipped structured data about its site or its breadcrumbs, nothing about
   *  itself — the common case on category pages. */
  subject_types: string[];
  payloads_considered: number;
  payloads_used: number;
}

export interface ExtractResponse {
  page: PageInfo;
  facts: Record<string, Fact>;
  /** Present only when no schema was supplied. */
  schema_choice: SchemaChoice | null;
}

export interface TextResponse {
  page: PageInfo;
  text: string;
  /** Structure-preserving Markdown: headings, images, links, tables, code. */
  markdown: string;
  /** The page reduced to its content: `<nav>`/`<footer>` removed, then the main-content
   *  boundary drawn around the densest run of prose. Empty when nothing was removed. */
  content_markdown: string;
  /** The comment thread found under the content and left out of `content_markdown`, as
   *  Markdown in page order. Empty when there is none, or when the comments are the page
   *  (a forum thread) and are in `content_markdown` already. */
  comments_markdown: string;
  /** Steps that removed something, in order: "landmarks", "main-landmark",
   *  "article-element", "article-body", "block-model" or "main-content". */
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
  /** `WEBGRAPH_KG=1` on the API: the `/api/graph/*` routes answer. Absent on older APIs. */
  webgraph?: boolean;
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

/**
 * Any method, any body, the same failure vocabulary as `request` below. Exported for the
 * WebGraph client (`lib/kg.ts`), whose routes use GET with query strings and DELETE, so a
 * second copy of the unreachable/detail handling does not grow beside this one.
 */
export async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(unreachableMessage(), 0);
  }
  if (!response.ok) {
    let detail = `The API answered ${response.status}.`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Not JSON; the status-based message stands.
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

async function requestGet<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`);
  } catch {
    throw new ApiError(unreachableMessage(), 0);
  }
  if (!response.ok) throw new ApiError(`The API answered ${response.status}.`, response.status);
  return (await response.json()) as T;
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

/** Per-run overrides. Every field optional; the server's defaults are webgraph/config.py. */
export interface RunOptions {
  crawl?: Record<string, number | boolean | string>;
  fetch?: Record<string, number | boolean | string>;
  renderOptions?: Record<string, number | boolean | string>;
  /** Top-level request fields the settings page may also set. */
  max_pages?: number;
  concurrency?: number;
}

export interface ConfigSetting {
  value: unknown;
  comment: string;
  section: string;
}

export interface ConfigResponse {
  settings: Record<string, ConfigSetting>;
  overridable: Record<"crawl" | "fetch" | "renderOptions", string[]>;
  caps: Record<string, number>;
}

/** `POST /api/site/report` -- the shape of `webgraph.report.SiteReport.as_dict()`. */
/** At the root: `blocked` when `/` is disallowed, `partly` when content paths are, `allowed`
 *  when nothing is or only administrative paths (`/wp-admin/`, `/login`, `/search` …) are. */
export type BotAccess = "allowed" | "partly" | "blocked";
export type BotVia = "named" | "wildcard" | "none";
export type BotPurpose = "search" | "assistant" | "training";
export type Severity = "high" | "medium" | "low" | "info";

export interface BotPolicy {
  token: string;
  operator: string;
  purpose: BotPurpose;
  via: BotVia;
  mentioned: boolean;
  access: BotAccess;
  /** `Disallow` lines that apply and decide something, administrative ones included. */
  disallowed: number;
  /** The disallowed paths that are content, not housekeeping, in file order. */
  content_paths: string[];
  crawl_delay: number | null;
  /** The directives that apply, verbatim from the file. */
  lines: string[];
}

export interface ReportRobots {
  found: boolean;
  status: number;
  text: string;
  group_for_us: string | null;
  rules_for_us: string[];
  crawl_delay_for_us: number | null;
  allows_us_root: boolean;
  sitemaps_declared: string[];
  bots: BotPolicy[];
}

export interface ReportPage {
  requested_url: string;
  url: string;
  section: string;
  title: string;
  description: string;
  strategy: string;
  static_chars: number;
  rendered_chars: number;
  union_chars: number;
  static_words: number;
  rendered_words: number;
  union_words: number;
  static_coverage: number;
  render_error: string | null;
  static_error: string | null;
  /** Which side was served a wall: `browser`, `plain fetch`, or `both`. */
  wall: string | null;
  hidden_words: Record<string, number>;
  /** Links inside hidden elements of any kind (a dropdown menu counts). */
  hidden_links: number;
  hidden_hosts: { host: string; links: number; offscreen: number; external: boolean }[];
  hidden_external_hosts: number;
  /** Links inside elements parked off the page -- the shape of an injection. */
  offscreen_links: number;
  /** Foreign hosts among them; the spam verdict reads this number and no other. */
  offscreen_external_hosts: number;
  consent_words: number;
  total_words: number;
  consent_share: number;
  canonical: string | null;
  lang: string | null;
  structured_data: string[];
  has_schema: boolean;
  /** `og:*` / `twitter:*` tags on the page; the fourth page-field of the metadata sub-score. */
  has_open_graph: boolean;
  internal_links: number;
  links_checked: number;
  dead_links: { url: string; status: number }[];
  dead_count: number;
  links_unreachable: number;
  in_sitemap: boolean | null;
  /** Set when the page could not be read at all; every number is then zero. */
  error: string | null;
}

export interface SubScore {
  key: string;
  label: string;
  weight: number;
  /** Points out of `weight`; null when the measurement could not be made. */
  score: number | null;
  measured: boolean;
  evidence: string;
  recommendation: string | null;
  source: string | null;
}

export interface Finding {
  severity: Severity;
  kind: string;
  title: string;
  detail: string;
  page: string | null;
}

export interface StackEntry {
  name: string;
  category: string;
  version: string | null;
  released: string | null;
  age_years: number | null;
}

export interface LlmsFile {
  path: string;
  found: boolean;
  status: number;
  bytes: number;
  sections: number;
  links: number;
  title: string | null;
  /** A sample of the file's links (up to 5) checked for an answer, and how many did. */
  links_checked: number;
  links_answering: number;
}

/** The five groups of `SiteSignal`, in report order (`webgraph.report.signals.GROUPS`). */
export type SignalGroup = "ai" | "discovery" | "agents" | "metadata" | "trust";

/** One thing the site does or does not publish for machines. */
export interface SiteSignal {
  key: string;
  label: string;
  group: SignalGroup;
  group_label: string;
  /** true: found and shaped like the thing; false: looked for, absent; null: could not be
   *  looked for (robots.txt disallows the path for this client; IndexNow's key is secret). */
  present: boolean | null;
  /** What was found, in the file's own terms. */
  detail: string;
  /** Plain words for the owner: what this says to machines and whether anyone is bound. */
  meaning: string;
  who_honours: string;
  spec_url: string;
  source_url: string | null;
  status: number | null;
}

export interface SiteSignals {
  signals: SiteSignal[];
  groups: { key: SignalGroup; label: string; signals: string[] }[];
  llms_txt: LlmsFile;
  llms_full_txt: LlmsFile;
  content_signals: { agents: string[]; values: Record<string, string>; line: string }[];
  root_status: number;
  /** The root's response headers that are signals: x-robots-tag, link, tdm-reservation … */
  root_headers: Record<string, string>;
  /** Requests the collection made, the root included. */
  requests: number;
  notes: string[];
}

export interface SiteReport {
  url: string;
  root: string;
  host: string;
  generated_at: string;
  reachable: boolean;
  /** The engine's own refusal when the root could not be read; no score then. */
  refusal: string | null;
  stack: StackEntry[];
  robots: ReportRobots | null;
  sitemap_found: boolean;
  sitemap_urls: number;
  sitemap_attempts: { url: string; status: number; ok: boolean; urls: number; index: boolean; source: string }[];
  llms_txt: LlmsFile | null;
  llms_full_txt: LlmsFile | null;
  /** What the site declares to machines, in five groups; null only when unreachable. */
  signals: SiteSignals | null;
  pages: ReportPage[];
  score: { total: number; measured_weight: number; subscores: SubScore[] } | null;
  findings: Finding[];
  suggested_robots_txt: string | null;
  suggested_llms_txt: string | null;
  /** An RFC 9116 template, offered only when the site has no security.txt. */
  suggested_security_txt: string | null;
  llms_txt_note: string;
  measured: {
    engine_version: string;
    commit: string;
    user_agent: string;
    pages_requested: number;
    pages_sampled: number;
    request_interval_seconds: number;
    duration_seconds: number;
    render_available: boolean;
    statement: string;
  } | null;
  notes: string[];
}

// ---------------------------------------------------------------------------------------
// Watch: change monitoring on top of the crawl (`/api/watch`).
// ---------------------------------------------------------------------------------------

export type ChangeKind = "added" | "removed" | "changed";

export interface SectionChange {
  kind: "added" | "removed" | "edited";
  heading: string;
  before: string;
  after: string;
}

export interface WatchChange {
  id: number;
  run_id: number;
  watch_id: string;
  url: string;
  kind: ChangeKind;
  detected_at: number;
  before_hash: string;
  after_hash: string;
  title: string;
  /** The provenance: which sections, in the page's own words. */
  sections: SectionChange[];
}

export interface WatchRun {
  id: number;
  watch_id: string;
  started_at: number;
  finished_at: number | null;
  pages_ok: number;
  pages_failed: number;
  stopped_by: StoppedBy;
}

export interface Watch {
  id: string;
  root: string;
  config: Record<string, unknown>;
  created_at: number;
  schedule_seconds: number;
  last_run: WatchRun | null;
  runs: number;
  changes: number;
}

/** First event of a watch run: what it is being compared against. */
export interface WatchStartEvent {
  type: "watch";
  watch_id: string;
  run_id: number;
  root: string;
  baseline: boolean;
  previous_run: WatchRun | null;
  previous_pages: number;
}

/** One page that differed from the previous run, as it is found. */
export type ChangeEvent = WatchChange & { type: "change" };

/** The crawl's `done` plus the run's own numbers. */
export type WatchDoneEvent = DoneEvent & {
  watch_id: string;
  run_id: number;
  baseline: boolean;
  changes: { added: number; removed: number; changed: number };
  /** Pages whose text differed only in what the noise rules ignore. */
  suppressed: number;
  unchanged: number;
  /** Pages the previous run read that this run never reached. */
  unverified: number;
};

export type WatchEvent =
  | Exclude<SiteEvent, DoneEvent>
  | WatchStartEvent
  | ChangeEvent
  | WatchDoneEvent;


export const api = {
  config: () => requestGet<ConfigResponse>("/api/config"),

  watches: () => requestGet<Watch[]>("/api/watch"),

  watch: (id: string) => requestGet<Watch>(`/api/watch/${encodeURIComponent(id)}`),

  createWatch: (input: {
    url: string;
    config?: Record<string, unknown>;
    schedule_seconds?: number;
  }) => request<Watch>("/api/watch", input),

  watchChanges: (id: string, since?: string) =>
    requestGet<{ watch: Watch; changes: WatchChange[] }>(
      `/api/watch/${encodeURIComponent(id)}/changes${since ? `?since=${encodeURIComponent(since)}` : ""}`,
    ),

  /** The feed's address, for a reader or an Action to subscribe to. */
  watchFeedUrl: (id: string, format: "rss" | "atom" = "rss") =>
    `${API_BASE}/api/watch/${encodeURIComponent(id)}/feed.xml${format === "atom" ? "?format=atom" : ""}`,

  siteReport: (input: { url: string; pages?: number }) =>
    request<SiteReport>("/api/site/report", input),

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
    /** Omit to let the engine classify the page and pick the schema for that type. */
    schema?: unknown;
    render: boolean;
    rtl: boolean;
  }) => request<ExtractResponse>("/api/extract", input),

  text: (input: {
    url: string;
    render: boolean;
    rtl: boolean;
    /** Keep screen-reader-only labels, skip links and wiki edit controls -- text the
     *  browser holds but a sighted reader never sees. Off by default. */
    include_hidden_text?: boolean;
  }) => request<TextResponse>("/api/text", input),
};

export const SCHEMA_PRESETS: ReadonlyArray<{
  label: string;
  description: string;
  /** Undefined means "let the engine choose", which is the default. */
  schema?: unknown;
}> = [
  {
    label: "Auto",
    description:
      "Detect the page type, then read only the structured-data node that describes this " +
      "page — not the site's organisation or its breadcrumbs.",
  },
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

/**
 * What a page declares about itself in its `<head>`: the metadata a crawler, a search
 * engine or a share card reads before any of the page's text. Every address is absolute
 * against the address the page was served at; every text value is one line, capped.
 *
 * `declared_elsewhere` is the part worth reading first: declarations (`canonical`, `og:url`)
 * that name a different site from the one that served the page, as
 * `"canonical -> https://old-host.example"`. Empty is normal. A site that moved domains and
 * kept its old `metadataBase` fills it, and nothing on the page shows it -- the crawl that
 * trusted such a canonical once finished after one page.
 */
export interface PageMetadata {
  url: string;
  title: string | null;
  description: string | null;
  canonical: string | null;
  /** `<html lang>`. */
  language: string | null;
  charset: string | null;
  /** `<meta name="robots">`, verbatim. */
  robots: string | null;
  /** `<meta name="generator">`: the CMS or builder, by its own account. */
  generator: string | null;
  author: string | null;
  keywords: string | null;
  theme_color: string | null;
  viewport: string | null;
  /** `rel="icon"`, `shortcut icon`, `apple-touch-icon`, in document order. */
  icons: string[];
  manifest: string | null;
  /** Every `og:*` and `article:*` property. */
  open_graph: Record<string, string>;
  /** Every `twitter:*` name. */
  twitter: Record<string, string>;
  /** `<link rel="alternate" hreflang>`, capped at 24; `alternate_count` is the whole. */
  alternates: Array<{ hreflang: string; href: string }>;
  alternate_count: number;
  /** RSS and Atom feeds the page advertises. */
  feeds: string[];
  /** The `@type`s of the page's JSON-LD and microdata, in order of first appearance. */
  schema_types: string[];
  declared_elsewhere: string[];
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
  /** The root page's `<head>`, read in the same stage as the stack. Absent from runs
   *  recorded before it was reported. */
  metadata?: PageMetadata | null;
}

/**
 * How the site wants to be found, as the crawl learned it in Stage 0.
 *
 * Two whole-site crawls the owner watched (vtu.ac.in, sode-edu.in) reported `from_sitemap: 0`
 * and nothing about why: neither site publishes a sitemap, and nothing on screen said what
 * robots.txt asked or which sitemap addresses had been tried. This is the why, sent once,
 * right after `analysis` and before the first `frontier`.
 */
export interface DiscoveryEvent {
  type: "discovery";
  robots: {
    /** False when the file could not be fetched -- which means *allow*, by convention. */
    found: boolean;
    url: string;
    /** The HTTP status the fetch returned; 0 when nothing came back at all. */
    fetched_status: number;
    /** Which `User-agent:` the rules came from: "webgraph" when the site names this client,
     *  "*" when it does not, null when no group applies. */
    group: string | null;
    /** The Allow / Disallow / Crawl-delay lines of that group, as the file wrote them. */
    rules_for_us: string[];
    crawl_delay: number | null;
    /** The file as served, capped server-side; `text_truncated` says when it was cut. */
    text: string;
    text_truncated: boolean;
    text_chars: number;
  };
  sitemaps: {
    /** Every address tried, in the order tried. `source` is "robots" for a `Sitemap:` line,
     *  "conventional" for /sitemap.xml and /sitemap_index.xml, "index" for one an index
     *  listed. `ok` means it parsed as a sitemap; a 200 that is the site's HTML 404 is not. */
    attempts: Array<{
      url: string;
      status: number;
      ok: boolean;
      /** Page URLs it contributed; 0 for an index, which lists sitemaps rather than pages. */
      urls: number;
      index: boolean;
      source: "robots" | "conventional" | "index";
    }>;
    /** Sitemaps that parsed and listed pages (indexes excluded). */
    found: number;
    /** Page URLs the sitemaps advertised, before scope and deduplication. */
    total_urls: number;
  };
  /** Sitemap URLs the frontier accepted -- what `from_sitemap` on `frontier` reports. */
  seeds: number;
}

/**
 * What kind of thing each discovered address points at, judged from the URL alone, as a
 * running tally. On vtu.ac.in 7,907 of 17,126 discovered URLs were PDFs, which the crawl
 * fetched one by one to refuse; a count of addresses alone hid that for six hours. Every
 * key is present on every event, zeros included.
 */
export interface DiscoveredKinds {
  page: number;
  pdf: number;
  image: number;
  other_file: number;
  archive: number;
  category: number;
  tag: number;
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

/** How many addresses were accepted at each link distance from the root. */
export type DepthCounts = Record<string, number>;

export interface FrontierEvent {
  type: "frontier";
  queued: number;
  discovered: number;
  from_sitemap: number;
  extracted: number;
  /** URLs newly accepted into the frontier. Clients rebuild the discovered set from these
   *  deltas; resending the whole frontier on every event would be quadratic. */
  new_urls: string[];
  depth_counts?: DepthCounts;
  /** The running tally of discovered addresses by kind; replaces, never adds to, the last. */
  discovered_kinds?: DiscoveredKinds;
}

/**
 * Everything in flight right now, sent whenever that set changes. The pool is kept full and
 * refilled as each page lands (since #94; before, a batch of `concurrency` went out together).
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
  depth_counts?: DepthCounts;
  /** The running tally of discovered addresses by kind; replaces, never adds to, the last. */
  discovered_kinds?: DiscoveredKinds;
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

export type StoppedBy = "pages" | "time" | "queue" | null;

export interface SkippedUrl {
  url: string;
  kind: "pdf" | "image" | "other_file";
  via?: string;
  found_on?: string | null;
  anchor?: string | null;
  depth?: number;
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
  /**
   * Which limit ended the run: the page cap, the time limit, or a queue cap that turned
   * addresses away. Null when the frontier ran dry or the caller stopped it.
   */
  stopped_by: StoppedBy;
  /** The limits this run ran under; 0 means none. */
  limits: { max_pages: number; max_seconds: number; max_queue: number };
  /** Addresses the queue cap turned away. */
  queue_refused: number;
  /** Whether links to PDFs and other files were fetched, or only counted. */
  fetch_files: boolean;
  /** Same-site files counted and never fetched, by kind. */
  skipped: { pdf: number; image: number; other_file: number };
  skipped_total: number;
  /** The first of those, each with the page that linked to it. Capped server-side. */
  skipped_urls: SkippedUrl[];
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
  /** True when the caller supplied the HTML and nothing was fetched (`strategy` is then
   *  `"supplied"`). */
  supplied?: boolean;
  complete?: boolean;
  max_pages?: number;
  concurrency?: number;
  max_depth?: number;
  strict_domain?: boolean;
}

export type SiteEvent =
  | RunEvent
  | StageEvent
  | AnalysisEvent
  | DiscoveryEvent
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
      /** `static-only`, `rendered-only`, `union` -- or `supplied`, when the reader handed
       *  over the HTML and nothing was fetched. `strategyLabel` names each for a reader. */
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
      /** The page's `<head>` declarations -- the first thing known about it. */
      metadata?: PageMetadata | null;
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
      comments_markdown: string;
      images: string[];
      tables: number;
    }
  | { type: "error"; stage: string; message: string; at?: number };

/**
 * What to call a fetch strategy on screen. The wire values are the engine's enum, and
 * `"supplied"` is the one a reader would not decode: it means the HTML came from them.
 */
export const STRATEGY_LABELS: Readonly<Record<string, string>> = {
  supplied: "supplied by you",
};

export function strategyLabel(strategy: string): string {
  return STRATEGY_LABELS[strategy] ?? strategy;
}

/**
 * Stream one page, stage by stage.
 *
 * Shares the frame decoding with `streamSite` deliberately: a second parser for the same
 * wire format is a second place for a frame split across TCP reads to be mishandled.
 */
export async function streamPage(
  input: {
    url: string;
    render: boolean;
    /** The page's HTML, when the reader already has it -- their own signed-in browser, a
     *  saved file. The API fetches nothing and reads this instead; `render` is ignored.
     *  For the sites that refuse every automated fetch. A pasted wall is still refused. */
    html?: string;
  } & Pick<RunOptions, "fetch" | "renderOptions">,
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
 * acquire a second, subtly different, version of that bug. Exported for the same reason: the
 * WebGraph client (`lib/kg.ts`) streams three more routes through it.
 */
export async function streamFrames(
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
    // The server usually says why -- "refused: private addresses are blocked" -- and a
    // status number alone sends the reader to the wrong place.
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Not JSON; the status is all there is.
    }
    throw new ApiError(
      detail || `The API answered ${response.status} without saying why.`,
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
        onEvent(JSON.parse(line.slice(6)));
      } catch {
        // A malformed frame must not kill the stream.
      }
    }
  }
}

/** Run a watch once; the stream is the crawl's events plus `watch`, `change` and `done`. */
export async function streamWatchRun(
  id: string,
  onEvent: (event: WatchEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamFrames(
    `/api/watch/${encodeURIComponent(id)}/run`,
    {},
    onEvent as (event: unknown) => void,
    signal,
  );
}


export async function streamSite(
  /**
   * `max_pages` and `max_seconds` are optional: left out, the API applies the engine's
   * caps (500 pages, an hour). Sending `0` is an explicit ask for an unbounded crawl.
   */
  input: {
    url: string;
    max_pages?: number;
    max_seconds?: number;
    concurrency: number;
    complete: boolean;
  } & Pick<RunOptions, "crawl" | "fetch" | "renderOptions">,
  onEvent: (event: SiteEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamFrames("/api/site/stream", input, onEvent as (event: unknown) => void, signal);
}
