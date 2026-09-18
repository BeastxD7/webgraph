# Firecrawl and the alternatives, read from the code — and what to take from them

**Date:** 2026-09-19
**Sources:** `firecrawl/firecrawl` at `7b0b0b9` (cloned, `apps/api/src` read: `scraper/scrapeURL/index.ts`, `engines/index.ts`, `transformers/index.ts`, `lib/removeUnwantedElements.ts`, `WebScraper/crawler.ts`, `lib/map-utils.ts`, `lib/extractMetadata.ts`); `unclecode/crawl4ai` at `862f6bc` (`content_filter_strategy.py`, `adaptive_crawler.py`, `async_url_seeder.py`, `deep_crawling/`). Claims below cite the file they come from. Nothing here is from a README or a marketing page.
**Against:** this engine at `main` `e2e4fc8` plus PR #134.

---

## 1. The one-paragraph version

Firecrawl is a **scrape-as-a-service platform**: an Express API and BullMQ workers in front of a proprietary browser fleet ("fire-engine": Chrome-over-CDP, a TLS-fingerprinting HTTP client, stealth proxies), with Playwright and plain `fetch` as the self-host fallbacks. A scrape is a *waterfall* of engines ranked by a quality number, and a result is "successful" when the markdown is non-empty and the status is 2xx — a 401/403/429 escalates to a **stealth proxy** and retries. Content is reduced to "main content" by a CSS-selector blocklist plus per-domain selectors learned across its customers' scrapes. Everything after markdown is an LLM format: `json`, `summary`, `query`, `agent`, `branding`, change-tracking with a schema. Discovery (`/map`) is sitemap ∪ a `site:` web-search ∪ its own cache of every page it ever scraped. It is optimised for **getting *something* back from any URL, fast, at scale, through walls** — the opposite trade from this engine's, which is optimised for **being right about what a page said, and saying how it knows**.

crawl4ai is the open-source Python cousin: Playwright-driven, "fit markdown" via a readability-style tree pruner (text density, link density, tag weights, negative class patterns) or a BM25 query filter, deep-crawl strategies (BFS/DFS/best-first with URL scorers), an "adaptive" crawler that stops when coverage/consistency/saturation say the question is answered, and a URL seeder that reads Common Crawl's index instead of the site.

---

## 2. Firecrawl, mechanism by mechanism

### 2.1 Architecture (`apps/`)
- `api`: Express + TypeScript. Controllers per endpoint (`controllers/v2/`: `scrape`, `crawl`, `map`, `search`, `extract`, `agent`, `batch-scrape`, `monitor`, …). Jobs on BullMQ/Redis; state in Postgres (Supabase). Rust natives (`@mendable/firecrawl-rs`: HTML transform, link extraction) and a Go `html-to-markdown` service. Playwright as a separate microservice (`playwright-service-ts`). SDKs in eight languages; an MCP server; a CLI with "skills".
- **Fire-engine is not in the repo.** `engines/fire-engine/` is a client. Self-host gets `playwright` + `fetch` + `pdf`/`document` parsers.

### 2.2 The engine waterfall (`scraper/scrapeURL/engines/index.ts`)
- Engines: `exchange` (quality 2000), `index` (1000 — "should always be tried first"), fire-engine chrome-cdp (50), chrome-cdp retry (45), playwright (20), fetch (10), tlsclient (5), then the specialty parsers at negative quality (pdf −1, document −2, image −5), stealth variants (−15/−20).
- Each request derives **feature flags** (`actions`, `waitFor`, `screenshot`, `pdf`, `location`, `mobile`, `stealthProxy`, `branding`, …) with priorities; `buildFallbackList` keeps engines whose feature support covers the flags, ordered by quality. Files (pdf/docx) are routed through the browser fleet's proxies first, then parsed.
- **Escalation is by thrown errors**: `AddFeatureError(["stealthProxy"])` re-enters the loop with the flag added; `RemoveFeatureError` the reverse. There is a `MaxReasonableTime` per engine and a global scrape timeout.

### 2.3 What "success" means (`scrapeURL/index.ts::scrapeURLLoopIter`)
```
isLongEnough   = markdown(html, onlyMainContent).trim().length > 0   (retry with onlyMainContent=false if empty)
isGoodStatus   = 2xx or 304
hasRequiredOutput = isLongEnough || !isGoodStatus      ← a bad status is accepted as a result
401/403/429 with proxy:"auto" → AddFeatureError(["stealthProxy"])
```
Two things to see here. (a) A wall that returns 200 with a "verify you are human" page passes this test — there is no wall detection at this layer (their `scrape-evals` harness has nine "block-page needles", but the scraper itself checks length and status). (b) The response to being refused is to **disguise** (stealth proxies, TLS-fingerprint client). This engine refuses to disguise and reports the refusal in the engine's own words (`resolve.wall_evidence`, `PageBlockedError`).

### 2.4 Transformers (`transformers/index.ts`, `lib/removeUnwantedElements.ts`)
Stack, in order: raw HTML → HTML → markdown (Go service, cheerio fallback) → `performCleanContent` → PII redaction → links → images → branding → **metadata** → product/menu fetchers → write to index → LLM extract / deterministic JSON / summary / query / attributes / agent → strip base64 images → diff → audio/video → coerce to requested formats.
- **`onlyMainContent`** = remove `header, footer, nav, aside, .header, .navbar, .sidebar, .modal, .popup, .ad, .cookie, .breadcrumbs, .share, .widget …` unless the element contains a `forceIncludeMainTags` selector (`#main`, and a hand-list of one vendor's classes), plus **OMCE signatures**: per-domain selectors fetched from their index service (`queryOMCESignatures`), i.e. learned from the corpus of everything they have scraped. Then `img[srcset]` is rewritten to the biggest candidate.
- Compare: this engine's content selection is *measured* — landmarks → cross-page chrome learned from ≥6 pages of *this* site → a trained block model → the main-content boundary — and it reports which step removed what (`content_methods`). Firecrawl's is a blocklist with a crowd-sourced per-domain patch; it cannot say why a block went, and it removes `.social`/`.language` on a page whose content *is* the language list.

### 2.5 Metadata (`lib/extractMetadata.ts`)
`title, description, lang, keywords, robots, og:title/description/url/image/audio/determiner/locale/locale:alternate/site_name/video, article:section/tag/published_time/modified_time, favicon, dc.* (Dublin Core), itemprop`, plus every other `<meta name|property>` flattened into `metadata` verbatim, and `sourceURL`, `statusCode`, `contentType`, `proxyUsed`, `cacheState`, `creditsUsed`. **Nothing is checked against anything**: a canonical on another host is reported as a string. PR #133 here reports the same head and adds `declared_elsewhere`.

### 2.6 The crawler (`WebScraper/crawler.ts`)
- BFS from the initial URL. `maxDepth` is **path-segment depth** (`getURLDepth`), not link distance. Default scope is *the initial URL's path and below* (`BACKWARD_CRAWLING` denial) unless `crawlEntireDomain`; subdomains and external links off by default; `includePaths`/`excludePaths` regex; robots respected (`ignoreRobotsTxt` exists); non-document extensions skipped; social-media hosts and `mailto:` skipped; `#fragment` URLs deduplicated to their base.
- **Every URL that is *not* crawled gets a `DenialReason`** — a human sentence naming the parameter to change (`DEPTH_LIMIT`, `EXCLUDE_PATTERN`, `INCLUDE_PATTERN`, `ROBOTS_TXT`, `FILE_TYPE`, `URL_PARSE_ERROR`, `BACKWARD_CRAWLING`, `SOCIAL_MEDIA`, `EXTERNAL_LINK`, `SECTION_LINK`, `NON_WEB_PROTOCOL`). This is the single best idea in the crawler, and it is exactly what this engine's frontier lacks: our `/projects` bug was invisible for a day because `Frontier.add` returned `False` and nothing recorded why.
- Links are read from HTML (Rust, cheerio fallback) **and from the markdown** (`extractLinksFromMarkdownContent`) — so a link a converter emitted from text is followed too.
- Sitemaps: robots `Sitemap:` lines, `/sitemap.xml`, nested indexes, `.gz`; a cache of sitemap fetches.

### 2.7 `/map` (`lib/map-utils.ts`)
Sitemap ∪ **web search** (`fireEngineMap("site:host")`, up to 100 results/page, cached in Redis) ∪ their **index** of previously scraped URLs; optional `search` term ranks results by cosine similarity of the URL string to the query (`map-cosine.ts`); `sitemap: "only"|"include"|"skip"`. Fast because it never fetches the site's pages. The search-engine leg is what makes it find pages nothing links to — and also what makes it non-reproducible and third-party-dependent.

### 2.8 Index and change tracking
- `index` engine: every scrape is written to a shared store (`sendDocumentToIndex`); a later request with `maxAge` is served from it. The whole company's scrapes are one cache. Strong for cost; it means a customer can be handed a page as another customer saw it.
- `changeTracking` (`transformers/diff.ts`): compares against the previous scrape of the same URL from the index; modes `git-diff` (line diff of markdown) and `json` (LLM extraction against a schema, then compared). This engine's Watch does the first with a content hash and a per-page diff; it has no LLM mode by design.

### 2.9 Everything else is an LLM feature
`json` (schema extraction), `summary`, `query` (question answering over the page), `highlights`, `attributes`, `agent` (a browser agent driving actions), `branding` (extract a brand profile), `/extract` (agent over a crawl), `/search`, deep research, `redactPII`. These are products, not extraction. This engine's line is: nothing inferred by a model is presented as a fact about the page; the page-type router is the one model, and it explains itself by ablation.

---

## 3. crawl4ai, briefly (`crawl4ai/`)
- **Content filters** (`content_filter_strategy.py`): `PruningContentFilter` walks the tree and drops a node whose composite score — text density (`text_len/tag_len`), 1 − link density, a tag weight table, a negative class/id pattern penalty, `log(text_len)` — falls under a threshold (fixed, or dynamic per tag importance/text ratio/link ratio). `BM25ContentFilter` keeps chunks relevant to a query (the page's own title/description by default). `LLMContentFilter` asks a model. This is Readability's family, tuned; ours replaces the heuristics with a trained block model and *measured* geometry.
- **Deep crawl** (`deep_crawling/`): BFS/DFS/best-first with pluggable `URLFilter`s (domain, pattern, content-type, SEO score) and `URLScorer`s (keyword relevance, path depth, freshness, domain authority).
- **Adaptive crawler** (`adaptive_crawler.py`): for a *query*, keeps crawling until a confidence from coverage (query terms seen), consistency (agreement across pages) and saturation (new pages add nothing) crosses a threshold, then stops. An honest stopping rule for research crawls.
- **URL seeder** (`async_url_seeder.py`): discovers URLs from **Common Crawl's CDX index** and sitemaps, thousands of hosts concurrently, optional HEAD liveness and partial-`<head>` fetch. Discovery without touching the site.
- **Anti-bot** (`antibot_detector.py`, "magic" mode, stealth): same trade as Firecrawl, more modest.

---

## 4. Side by side

| | Firecrawl | crawl4ai | This engine |
|---|---|---|---|
| Fetch | engine waterfall; proprietary browser fleet; stealth proxies on 403 | Playwright; stealth options | plain HTTP **and** a real browser, always both, merged (`union`) |
| "Did we get the page?" | markdown non-empty and 2xx | length heuristics | wall/challenge/login **refused in the engine's words**; static vs rendered chars measured; never disguised |
| Main content | selector blocklist + crowd-learned per-domain selectors | density/link/tag pruner, BM25, or LLM | landmarks → chrome learned from *this* site → trained block model → boundary; each step reported |
| Reading order | DOM order | DOM order | measured XY-cut over rendered boxes; says whether measured or assumed |
| Metadata | flattened `<meta>` dump | basic | typed head + `declared_elsewhere` (#133) |
| Discovery | sitemap ∪ web search ∪ global cache | Common Crawl CDX ∪ sitemap | robots → sitemap → links, breadth-first, cited (`via/found_on/anchor`) |
| Why a URL was skipped | **a sentence per URL** | filter logs | *silently dropped* ← gap |
| Links off-site / in scripts | recorded (`links` format) | recorded | #134: recorded, labelled, in the tree |
| Change tracking | markdown diff + LLM schema diff | — | Watch: hash + diff |
| Structure output | markdown, HTML, links, screenshot, JSON (LLM) | markdown, "fit" markdown, JSON (CSS/XPath or LLM) | markdown with provenance, sections, **graph** (pages/sections/entities, schema.org identity), Site Truth Report |
| Scale | queue + fleet + cache; thousands of hosts | async, single process | thread pool, per-host politeness, bounded frontier |

---

## 5. What to take, what to leave

**Take — ranked by value ÷ cost, all consistent with "measured, not assumed":**

1. **Denial reasons on the frontier** (Firecrawl §2.6). `Frontier.add` returns `False` for off-site, depth, file kind, queue cap, exclude/include, and says nothing. Record a reason per turned-away URL (capped, with a per-reason tally), report it on `discovery`/`frontier` events and in the "URLs found by kind" panel, and let the Site Truth Report say "27 addresses were off-site, 3 over depth". *This would have shown the canonical bug in one look.* Small: one dict on the frontier, one field on two events.
2. **Path-scoped crawls and include/exclude patterns** as user options (Firecrawl §2.6). `CrawlScope` already has `include_patterns`/`exclude_patterns` — unexposed through the API and UI. Expose them, plus a "stay under this path" option (their default; ours should stay whole-site by default).
3. **Links from the markdown too** (Firecrawl §2.6) — cheap belt-and-braces for converters that emit bare URLs; low value here since links are read from the served HTML, but zero risk.
4. **Link-distance vs path-segment depth**: keep ours (link distance is what "depth" means to a reader), but *report* path depth in the tree, since both Firecrawl and crawl4ai users think in it.
5. **Adaptive stopping for question-driven crawls** (crawl4ai §3): not for the whole-site crawl, but a `Report`/`Ask` feature could stop when saturation says new pages add no new sections/entities — and we can measure saturation from the graph, which is more honest than term coverage.
6. **Discovery without touching the site** (crawl4ai's Common Crawl seeder): as an *optional*, clearly labelled source for `discovery` — "Common Crawl last saw 1,240 URLs on this host" — never queued without a live check. Cheap to add (`index.commoncrawl.org` CDX), useful for the Site Truth Report's "how big is this site" question.
7. **`srcset` → largest image** (Firecrawl §2.4): trivial, correct, do it in block extraction.
8. **Gzipped sitemaps** (`sitemap.xml.gz`, common on large sites): Firecrawl decompresses them explicitly (`sitemap.ts:62`); ours follows nested indexes (`discovery.py`, `_SITEMAP_INDEX`) but has no `.gz` handling — HTTP content-encoding is decoded, a gzipped *file* is not. A site whose index lists `.xml.gz` parts reads as "sitemap found, 0 URLs" here. Fix.

**Leave — by design:**
- Stealth proxies, TLS-fingerprint clients, "magic" anti-bot modes. The engine's rule is to read only what a site serves an honest client and to report refusals. Every board where Firecrawl beats us on *coverage* is a board where seven of thirteen engines fetch through anti-bot infrastructure (see `benchmarks/public-boards`).
- LLM formats (`summary`, `json`, `query`, `agent`, `branding`). Products, not facts about the page; nothing inferred is presented as extracted here.
- The shared cross-customer index. Watch's own history is the cache; nobody is served another person's fetch.
- Selector-blocklist main content and crowd-learned per-domain selectors. Ours is measured and per-site.
- Web-search-backed `/map`. Non-reproducible and third-party. The Common Crawl seeder is the honest substitute.

---

## 6. Where they are simply ahead
- **Operational maturity**: queues, per-team concurrency, credit accounting, webhooks, cancellation, zero-data-retention mode, eight SDKs, an MCP server, a CLI. None of it is extraction, all of it is product.
- **File types**: PDF (with page markers and blocks), DOCX/XLSX, images with OCR, audio/video transcripts. We refuse files by default and count them; a PDF reader is the one of these worth having.
- **Actions**: click/scroll/type before scraping. Our position is that a page that needs a click is a page whose content is behind a click, and we say so (#134's canvas verdict) — but a bounded, declared `actions` list for the single-page path is defensible.
- **Throughput**: a browser fleet vs one machine. Not a design question.

---

## 7. Things learned that are not about the alternatives
- Their scraper accepts a 200 wall as content; their eval harness has block-page needles. The two disagree about what a successful scrape is. Ours has one definition, in `resolve`.
- Both alternatives treat "depth" as path segments. Users coming from them will read our depth tree as path depth until told otherwise — the tree should say "links from the root".
- Firecrawl's "why not crawled" sentences name the *parameter to change*. Ours should name the *fact* ("on another site", "past depth 1") — the parameter is one word away, the fact is what a Site Truth Report needs.
