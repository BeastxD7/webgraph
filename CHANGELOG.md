# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (2026-09-16, PR #100) — WebGraph page: the graph, and the query path lit in real time (behind WEBGRAPH_KG)
- `/graph?url=` (`apps/web/app/graph/page.tsx`, client components under
  `components/graph/`): the site, a model panel (presets for Ollama, LM Studio, vLLM,
  OpenAI, Anthropic, Gemini, Groq, OpenRouter, Together, DeepSeek, Mistral, xAI, or a
  custom OpenAI-compatible endpoint; the key is typed in the browser, sent only in the
  body of each request, never stored server-side, and kept in page memory unless the reader
  ticks "remember in this browser"), a build panel that shows the `estimate` first and
  streams progress, caps and the final stats, the graph, an ask box, export and Neo4j sync.
- The graph: sigma 3 (WebGL) + graphology, ForceAtlas2 in a worker for a bounded time;
  colour by type in a fixed eight-slot categorical order validated for both grounds, size by
  evidence count; hover and selection dim the rest; clicking a node shows every mention with
  its quote and `url#xpath`, attributes and relations each with their quote. Phone width
  falls back to a filterable list; the page never scrolls sideways.
- The path in real time: a store outside React (`pathStore`) receives each query event and
  sigma's reducers read it on refresh -- seeds amber, hop edges blue with a 350 ms particle
  on an overlay canvas, evidence nodes enlarged, answer nodes green with a camera pan;
  everything else ghosted. Answer sentences carry `[n]` superscripts to a numbered source
  list; an uncited sentence is rendered flagged.
- npm: `sigma`, `graphology`, `graphology-layout-forceatlas2`, `@react-sigma/core` (the
  four the design allows; nothing else). `lib/api.ts` exports `streamFrames` and a
  `requestJson` so the WebGraph client (`lib/kg.ts`) shares one SSE parser and one failure
  vocabulary. `/api/health` type gains `webgraph`; when it is false the page says how to
  turn the flag on.
- API: `no_model: true` on `POST /api/graph/query` forces the extractive answer even when
  the server has `WEBGRAPH_LLM_MODEL`; the extractive answer is one quoted sentence per
  row so the sentence splitter keeps their citations apart.
- `/products`: the WebGraph card is "Available — preview, behind a flag" with CTAs to
  `/graph` and the docs; the footer gains WebGraph; `/docs/webgraph` gains "The page".
- Measured only with the fake provider (no key in the environment; Ollama has no models):
  the fixture site builds, the path streams and lights, every citation resolves to
  `url#xpath`, both themes, 1440 px and 400 px, no console errors. Not measured: a real
  model's answers, or a graph above ~40 nodes in the browser.

### Added (2026-09-16, PR #97) — WebGraph v1 (behind WEBGRAPH_KG)
- **The inferred layer over a crawl**, `packages/engine/src/webgraph/kg/`: a language
  model reads every heading-scoped section and states what it says -- entities of twelve
  core types plus open ones, typed attributes (price, date, phone, email) and relations --
  and every row is kept only if the model's verbatim quote is found in a block of that
  section. The row then cites `url#xpath` and a character span (`Evidence`); a quote not
  found is rejected and counted by reason. No unverified tier exists in the store.
  `Section.blocks` (`BlockRef(xpath, kind, start, end)`) is the one change inside `graph/`
  that makes this possible; section text is byte-identical to before.
- **Bring your own key.** Three raw-`httpx` adapters (`kg/providers.py`): OpenAI-compatible
  with a `base_url` (OpenAI, Groq, Together, OpenRouter, DeepSeek, Mistral, xAI, Ollama,
  LM Studio, vLLM, any custom endpoint), Anthropic (`output_config` json_schema) and Gemini
  (`responseJsonSchema`), with a `json_schema` → `json_object` → prompt ladder and retries
  on 408/409/429/5xx. Config per request or from `WEBGRAPH_LLM_*`; the key is excluded from
  `repr`, never persisted, never traced, and the API's new 422 handler redacts `api_key`
  and `password` from validation errors (FastAPI echoes the whole body on a missing field).
  A deterministic `FakeProvider` runs the tests and the CI benchmark.
- **Build with the bill visible** (`kg/build.py`): the first event is `estimate` (sections,
  cached sections, input tokens, output at a quarter, USD when prices are configured);
  caps on pages, sections, input tokens (2M) and dollars stop the build cleanly with
  `truncated: true`; the LLM cache (`llm_cache` in the site's SQLite file, keyed on prompt
  version, model, section text and known entities) makes a second build free. Sections
  are read by page in-degree, then depth. No gleaning, no build-time summaries.
- **Deterministic merge** (`kg/merge.py`): `(type, norm(name))`, model-declared aliases,
  open type into same-name core type, MinHash/LSH 3-gram Jaccard ≥ 0.9; JSON-LD/microdata
  entities enter first and win on a type conflict; a name on more than 60% of pages is
  `generic` and never expanded through. No LLM-judged dedup.
- **Store**: one SQLite file per site under `WEBGRAPH_KG_DIR` (`kg/store.py`) with FTS5
  over entity names and facts (pure-Python scan when FTS5 is missing), in-memory
  adjacency, `build_runs`, a versioned schema.
- **Ask, with the path streamed** (`kg/retrieve.py`): FTS5 BM25 seeds ∪ the crawl's
  section BM25 → two mass-normalised hops → evidence with 35% of slots reserved for rows
  reached by expansion → one answer call; every factual sentence carries `[n]` citations
  to `url#xpath`, an uncited sentence is returned `unsupported: true` (never silently
  kept), "Not stated on this site." is recognised as abstention. Events: `seeds`, `hop`,
  `evidence`, `answer_delta`, `answer`.
- **Exports and Neo4j**: JSONL, a portable `MERGE`-only Cypher script, JSON-LD with
  `prov:wasQuotedFrom` and `oa:XPathSelector` + `oa:TextPositionSelector` per assertion
  (`kg/export.py`); `kg/neo4j.py` pushes `UNWIND $rows MERGE` batches of 1,000 over bolt
  (`RELATED {predicate, evidence_ids}` edges, typed edges behind a flag, no APOC) with the
  official driver as the optional extra `webgraph[kg-neo4j]`.
- **API** (`apps/api/src/webgraph_api/kg_routes.py`, `WEBGRAPH_KG=1`, otherwise 404
  naming the flag): `POST /api/graph/build`, `POST /api/graph/query`, `GET
  /api/graph/stats`, `GET /api/graph` (nodes and edges), `GET /api/graph/entity`, `GET
  /api/graph/export?fmt=jsonl|cypher|jsonld`, `POST /api/graph/sync/neo4j` (credentials per
  request, never stored), `DELETE /api/graph`; `/api/health` reports `webgraph`.
- **CLI**: `webgraph kg build <site>` (from the stored crawl, `--graph` JSONL, `--pages`
  a directory of saved HTML, or a fresh crawl), `kg ask <site> "question"`, `kg export
  --format jsonl|cypher|jsonld`, `kg sync-neo4j` (password from `NEO4J_PASSWORD` only).
- **Benchmark** `benchmark/kg/`: `generate.py` derives typed questions from a site's own
  JSON-LD with the gold page and block located verbatim; `run.py` scores answer
  correctness by type, citation precision/recall at page *and block* level,
  unsupported-sentence rate, abstention, graph statistics and cost, in three modes
  (`bm25` baseline, `kg`, `kg+sections`); a six-page fixture site with 23 questions
  (three 2-hop, two not-on-site). **On the fixture with the fake provider the BM25
  baseline beats the KG on answer correctness (0.86 vs 0.62)** -- the fake's quotes are
  six-word windows -- and no real model was measured in this PR (no key in the
  environment, Ollama up with no models). The flag stays on until `kg+sections` beats
  `bm25` on typed and two-hop questions on three real sites.
- Docs: `/docs/webgraph` (what it is, the provenance rule, cost controls, the benchmark,
  what v1 does not do), `/docs/webgraph/providers`, `/docs/webgraph/neo4j`; the
  deployment configuration table gains `WEBGRAPH_KG`, `WEBGRAPH_KG_DIR`, `WEBGRAPH_LLM_*`.
- Config: `KG_*` in `config.py` (section "WebGraph"), `DEPLOY_KG`, `DEPLOY_KG_DIR`;
  `Settings.kg_enabled`, `Settings.kg_dir`.
- Not in this PR: the web UI (`/graph` with the sigma graph and the live query path) is
  the next PR; the `/products` WebGraph card stays "coming".

### Changed (2026-09-16, PR #93) — landing page, products page, design tokens
- The landing page is rebuilt from the design spec. The hero photograph, its glass prompt,
  its CC BY credit and the light-only commitment are gone; the page is the ground colour,
  one display line ("The honest web reader."), the URL prompt, and four measured numbers
  with their caveats beside them (WCXB 0.862 dev split, first of seven by a margin the
  board calls a tie; WCEB 0.883 with content and comments joined, content alone 0.856;
  route recall 98.1% on 96 sites against a real-browser oracle, static alone 31.0%; 0%
  wrong-value rate). Two columns list what the engine refuses, in its own error messages,
  and what it drops because a reader would not have seen it; three steps say how a page is
  read; a five-board table gives this engine's score, the leader's and the place in words,
  scrape-evals marked "not a ranking". Every figure is read from `lib/benchmarks.ts`
  (`selfScore`, `leaderScore`, new `ROUTE_RECALL`, `FIDELITY`, `WCXB_TEST`,
  `RENDER_PREDICTION`); the earlier `Pipeline.tsx` copy with 132 rules across 18
  categories is replaced.
- `/products`: one composed 2×2 grid. Crawler and CLI are marked available (a filled dot);
  WebGraph -- an LLM-built knowledge graph of a site with every node and edge cited to its
  page and block -- and Site Truth Report -- what a site shows people against what it sends
  crawlers, grounded in vtu.ac.in's ~60 off-screen gambling links per page (#88) -- are
  marked coming soon (a hollow ring). The chip carries the state in word and form; nothing
  coming soon is described as existing.
- Design tokens: `globals.css` now carries the spec's `tokens.css` -- light values on
  `:root`, a system-dark block and a `data-theme="dark"` block that wins over it, mapped
  onto Tailwind with `@theme inline` so utilities follow the theme; a type scale as
  utilities (`text-display` … `text-stat`); three radii (4 / 6 / 10px, replacing the
  Tailwind ramp so the run view's `rounded-2xl` panels flatten to 10px); one shadow, for
  things that float; reduced motion collapses every transition and turns the running dot
  into a static ring. The `--color-fd-*` bridge for the docs shell is in place. The run
  view, benchmarks, how-it-works and settings keep their earlier utility names through an
  alias block (`ink-soft`→`muted`, `ink-faint`→`faint`, `haze`→`ground`,
  `line`/`line-soft`→`rule`, `line-strong`→`rule-strong`, `leaf-*`→`accent`/`accent-ink`/
  `accent-soft`, `clay`/`flag-warn`→`warn`, `flag-bad`→`bad`, `shadow-lift`→`shadow-float`);
  `shadow-card` and `shadow-glass` are not aliased and now emit nothing.
- One header and footer for every page, from `layout.tsx`: Home, Products, Docs (the route
  is being built alongside), Benchmarks, How it works, GitHub; a theme toggle cycling
  System → Light → Dark, written to `data-theme` on `<html>` and remembered in
  `localStorage` under next-themes' key so the docs shell can share it; a "Run a site"
  button to `/#start`. Below 900px the items fold behind a "Menu" button that opens a
  full-width sheet with 48px rows. The bar takes the surface colour and a rule after 8px of
  scroll. The run view's banner loses the photograph band and its duplicate back link.
  Under `/docs` the header and footer step aside (`SiteChrome`): the docs shell draws its
  own bar and sidebar, and two navigations on one page is one too many.
- Known and open: `app/docs/docs.css` is a second Tailwind entry, and its utilities land
  after `globals.css`'s in the shared `utilities` layer. Once `/docs` has been visited the
  stylesheet stays loaded across client-side navigation, and any `hidden md:flex`-style
  pair on the rest of the site then loses to the docs copy of `.hidden` (measured: the
  nav collapsed to "Menu" at 1280px after visiting the docs). The new components write
  symmetric `max-md:` / `md:` pairs so no base utility is left to be overridden; the
  older pages (`/benchmarks`, `/how-it-works`, `/settings`, the run view) still carry
  such pairs. The fix is one Tailwind entry -- the Fumadocs preset imported from
  `globals.css`, as DESIGN.md §4c has it -- and belongs with the docs shell.
- Measured with Playwright at 1280 and 400px, light and dark: no page scrolls
  horizontally; the phone gutter is 16px; buttons are 44px under a coarse pointer; a
  remembered theme is on `<html>` at DOMContentLoaded (a `next/script` beforeInteractive
  variant was measured to set it after, and was not used).

### Added (2026-09-16, PR #92) — documentation site
- The web app serves documentation at `/docs`, built with Fumadocs from MDX files under
  `apps/web/content/docs/`. The sidebar has seven sections in a fixed order -- getting
  started, API, how it reads a page, crawling, benchmarks, deployment, contributing --
  each a placeholder page for now; the content follows in this pull request series. The
  landing page carries the README's opening and a card per section. Built-in full-text
  search (`/api/search`), a table of contents per page, light and dark themes, and a
  "Docs" link in the site header.
- The docs use the site's own palette and type (haze, ink, leaf; Manrope, JetBrains Mono,
  Instrument Serif for the title) and are styled by a stylesheet loaded only under
  `/docs`; the dark palette applies only while the docs layout is on the page, so the
  rest of the site renders exactly as before, also after navigating away from the docs.
  `apps/web/content/docs/_authoring.md` says how to add a page, what frontmatter it takes
  and which components are available.

### Fixed (2026-09-15, PR #90) — a block's XPath is the geometry map's
- The browser's measurements are keyed by each element's XPath in a fresh parse; the
  block walk removes hidden twins, clipped labels, permalinks and unreachable trays and
  only then computes a block's XPath -- and lxml writes `div[2]` while there are sibling
  divs and plain `div` once a removal leaves one, so every block below a removed sibling
  got a path the map did not hold. allbirds.com/collections/mens: 641 `display: none`
  elements first, 161 of 217 blocks without a rectangle, the page in source order, and the
  repeated product-card titles deduplicated as unmeasured text. Every element's path is now
  stamped (`PATH_ATTRIBUTE`) before the tree is edited and blocks read the stamp.
- Measured, whole page: nextjs.org/docs 0.940 → 0.979 recall, flipkart.com/mobiles 0.470
  → 0.975, allbirds collection 0.685 → 0.887 (219 of 304 blocks measured, all 34 cards),
  react.dev 0.996 → 1.000; fidelity suite cppreference 0.985 → 0.990, w3schools 0.994 →
  0.998, cameronsworld 0.992 → 1.000. Live suite: simonwillison.net R 0.75 → 0.92 / P 0.74
  → 0.84, discourse R 0.31 → 0.38, github issue P 0.00 → 0.25, astro +0.02. Boards (no
  geometry in the corpora): WCXB 0.8632 = 0.8632, Zyte 0.945 = 0.945, WebMainBench 0.7335
  → 0.7336.
- Known and open: ar.wikipedia's "القاهرة" now measures its 16-picture mid-article
  gallery, and the content boundary ends the article there (kept 654 → 274; whole-page
  output unaffected). Scoring a run of pictures and short captions as one unit fixed it
  and was rejected twice on the boards -- any short caption: WCXB −0.0016, WebMainBench
  −0.009; unlinked captions only: WCXB −0.0006, WebMainBench −0.005 (product-variant and
  related-story strips are galleries by that shape too).

### Fixed (2026-09-15, PR #89) — a browser answered with a server error is not a page
- flipkart.com/mobiles: the plain fetch returned the listing (200, 560 KB) and Chromium,
  seconds later, a 503 "No server is available to handle this request". The render
  reported `ok` -- it navigated and measured -- and the union merged the error page's
  sentence into the listing. `RenderResult.status` now carries the response's status
  (None for a salvaged timeout), and `resolve_page` treats a 5xx render as a failed side:
  the static page stands alone with `render_error` saying what the browser was told; both
  sides 5xx is a refusal. A 4xx render is still judged on its words, as before.

### Fixed (2026-09-15, PR #88) — text pushed off the page is not on the page
- vtu.ac.in (the owner's first live whole-site test) carries ~60 injected gambling links
  on every page, each in `<div style="position:absolute; left:-20914565266523px">`. The
  browser reports a box for them -- twenty trillion pixels to the left -- and the collector
  read "has a box" as "visible", so the whole-page Markdown opened with sixty lines of
  spam before "About VTU" and the reading order put them first. A box lying entirely at
  negative page coordinates is now hidden the way `display: none` is (`offscreen` in
  `collect.js`, an `_ABSENT_KINDS` member, honoured by `hidden_matter` so the union does
  not put the static copy back). Not inside a scroll container, though: w3schools' fixed
  sidebar and php.net's manual index scroll themselves to the current entry, and the
  entries above it have negative boxes while being one wheel tick away -- the first
  version dropped a heading on each. On a plain fetch the inline style that puts an
  element there (`position:absolute` with `left`/`top` ≤ -999px, or `text-indent` that
  far) is the same signal (`_drop_offscreen_styled`); `include_hidden_text` keeps it, as
  it keeps every other screen-reader-only string.
- Measured: vtu.ac.in/about-vtu 202 → 148 blocks, zero spam tokens, opens with "Online
  Fee Payment" as the screen does. Fidelity suite: unchanged except arxiv's off-screen
  "Skip to main content" link (now dropped, as the class rule already drops it elsewhere).
  Live suite: bbc's skip link likewise; every other column identical or page noise. WCXB
  0.8632 = 0.8632 (jococups.com's colour swatches, `text-indent:-9999px` labels a reader
  sees as coloured squares, move −0.074 on one page and +0.018 on another); Zyte
  0.945 = 0.945.

### Added (2026-09-15, PR #87) — discovery is visible
- The site run shows what robots.txt said and which sitemaps were tried. Two whole-site
  crawls the owner watched (vtu.ac.in, sode-edu.in, 14 Sep) reported `from_sitemap: 0`
  and nothing else: neither site publishes a sitemap, and no event said whether robots.txt
  existed, what it asked, or which addresses had been tried. `stream_site` now emits a
  `discovery` event after `analysis` -- `robots` (found, url, fetched_status, group,
  rules_for_us, crawl_delay, the file's text capped at `DISCOVERY_ROBOTS_TEXT_CHARS` with
  `text_truncated`/`text_chars`), `sitemaps` (every attempt with url / status / ok / urls /
  index / source, plus `found` and `total_urls`) and `seeds`. `RobotsPolicy` keeps `text`,
  `status`, `rules` and `group`; `discover_sitemaps` returns `(urls, attempts)` beside the
  unchanged `discover_sitemap_urls`; `SiteAnalysis` carries `robots_rules` and
  `sitemap_attempts` and prints them. One robots parser for both readers: the group
  selection in `fetch.robots.rule_that_applied` moved to `crawl.discovery.group_for_client`
  and `policy_for` builds its policy with the same `policy_from` the crawl uses.
- `frontier` and `page` events carry `discovered_kinds`: a running tally of discovered
  addresses by `url_kind` -- page, pdf, image, other_file, archive (`/2024/06/`,
  `/date/…`; a dated post permalink is a page), category, tag. On vtu.ac.in 7,907 of the
  17,126 discovered URLs were PDFs, which the crawl fetched one at a time to refuse each as
  not HTML -- a third of six hours -- and nothing on screen said so. Images and other files
  are counted once even though `normalize_url` never queues them, so the tally says what
  the site is rather than what the frontier holds. O(new URLs) per event.
- Web: a **How the site can be discovered** panel under the technology panel, three
  collapsed rows that open to their evidence -- "robots.txt · found · 1 rule applies to us
  · crawl-delay 1s" (the rules, then the file, monospace and scrollable), "Sitemaps · none
  published — discovery is by links only" (the table of attempts), "URLs found by kind"
  (live counts with a warning line when files outnumber pages). Extraction output is
  untouched: WCXB, Zyte, WCEB and WMB cannot move.

### Fixed (2026-09-15, PR #86) — prose before a code block
- A paragraph of four words or fewer directly before a `<pre>` was dropped as MDN's
  language-and-copy strip ("js Copy"). perldoc.perl.org/perlre lost "is made equivalent
  to", "For example, this program" and "will output the following:" -- sixty words of
  prose; pubs.opengroup.org's awk page lost its example lead-ins the same way. The strip
  is now a container that holds a button, or one whose words are all labels (a language
  name, the block's own declared language, "Copy"); a `<p>` is never the strip. Fidelity:
  perldoc 0.997 → 1.000, posix-awk 0.999 → 1.000. WebMainBench 0.7331 → 0.7335 (code_edit
  0.8468 → 0.8500, 12 pages up, none down); WCXB 0.8632 = 0.8632; Zyte 0.945 = 0.945.
- Reading those captions at all moved the content boundary on one tutorial: a dozen
  "Start the service:" lines each paid the block cost and Kadane ended the run before the
  last commands (WebMainBench 0ed88efa code_edit 1.000 → 0.874). A prose caption of at
  most `CODE_CAPTION_MAX_WORDS` before a code block is floored at zero like the code, and a
  run extends forward over the neutral code that closes it. Not a link strip: exploit-db's
  "« Previous Paper Next Paper »" above a `<pre>` bridged a metadata table into the run
  until captions were required to be prose (`link_density` ≤ 0.5).
- phpBB's `<p>Code: <a href="#">Select all</a></p>` is still the strip: a paragraph with a
  control that goes nowhere counts, one without does not.
- A highlighter's `language-undefined` (highlight.js on a block it could not classify)
  is no language: perldoc's fences came out as ```undefined, a word the page never
  showed. `none`, `plaintext`, `text`, `nohighlight` likewise.
### Fixed (2026-09-15, PR #85) — shadow DOM composed the way the browser paints it
- A serialised shadow root (`<template shadowrootmode>`, how the browser hands over what
  `outerHTML` omits) was unwrapped and the host's own children left behind it. That is not
  what a reader sees: a `<slot>`'s fallback text ("Untitled card", "Nothing was slotted
  here") came out although the browser had replaced it with the slotted content --
  invented text -- the slotted children landed after the whole component instead of at
  their slot, a title slotted into an `<h2>` stopped being a heading, and light children
  assigned to no slot, which the browser never renders, were read as paragraphs. The flat
  tree is now composed as the browser composes it: each slot replaced by what is assigned
  to it (`slot="name"` to the first `<slot name>`, the rest and the light text to the
  first unnamed slot), its fallback kept only when nothing is; what no slot takes is
  dropped; nested components inside out. `flatten_shadow_roots`, `_compose_slots`. No
  corpus page carries a shadow root (WCXB, Zyte, WCEB, WebMainBench: 0 files), so the
  boards cannot move; measured on the live and fidelity suites: github.com's `<relative-time>`
  no longer reads twice ("on Dec 5, 2022on Dec 5, 2022" → "on Dec 5, 2022", one duplicate
  block gone), MDN and every other page unchanged.

### Added (2026-09-14, PR #84) — bring your own HTML
- `/api/text` and `/api/text/stream` take `html`: the page as the caller already has it,
  from their own signed-in browser, an extension or a saved file. Nothing is fetched or
  rendered; the engine reads the paste (`resolve_supplied`, `Strategy.SUPPLIED`) and
  returns the same `text` / `markdown` / `content_markdown`. For the sites that refuse
  every automated fetch — stackoverflow.com answers both fetches with a Cloudflare
  challenge, nyc.gov with Akamai's, a login wall serves nothing to anyone signed out. The
  owner's decision is not to disguise the client to get past them; the reader who has the
  page hands it over instead.
- Never a false output: a pasted wall is refused as a fetched one is — a Cloudflare block
  page, a challenge script, an empty document all raise the same `PageBlockedError` /
  `ValueError` (502 on the API, an `error` event on the stream). A pasted login page has
  no redirect to be caught by, so its own `<link rel="canonical">` / `og:url` stands in
  for where the fetch ended: www.linkedin.com/login declares both as itself (measured
  2026-09-14), and a paste of it with the feed's URL is refused as a login redirect. `url`
  stays required (422 without
  it, or when not http(s)): links and images are made absolute against it. `render` is
  ignored. HTML over `FETCH_MAX_BYTES` (32 MB, the fetch limit) is refused with the limit
  named.
- The supplied path makes no request at all — a pasted `<frameset>` is parsed as the
  markup it is, not composed by fetching its frames, since a caller who can name frame
  URLs in a paste would otherwise be naming URLs for this process to fetch from inside its
  network. The stream skips the private-host guard for a supplied page (there is nothing
  for it to stop) and its `run` header says `strategy: supplied`, `render: false`.
- The result says what it is: `rendered_chars` 0, `static_chars` = `union_chars`, and
  `render_error` "HTML supplied by the caller; not fetched or rendered -- reading order
  is source order, and what the browser would have hidden may appear".
- Web: the single-page run has a "Paste the page's HTML instead" disclosure, opened for
  the reader when the fetch failed; the resolve stage then reads "Read the HTML you
  supplied" and the strategy "supplied by you". Schema mapping still fetches on its own
  and is off for a supplied run, and says so.
- Fetched output is unchanged: `resolve_page` gains only a guard refusing
  `strategy=SUPPLIED` (it would have fallen through to the union branch). Whole-page
  fidelity on columbia-sample, stallman.org and catb.org: identical recall / extra /
  inversions / blocks before and after.
### Changed (2026-09-14, PR #83) — a single page honours robots.txt
- `resolve_page` -- and so `/api/text`, `/api/text/stream`, `/api/extract` -- asks the
  host's robots.txt before fetching a page, as the crawl has since its first version. A
  page the file disallows for this client is not fetched; the refusal
  (`PageDisallowedError`) names the file, quotes the group and rule that decided
  (`User-agent: *` / `Disallow: /`), and says what the site offers instead -- its API
  where the engine can cite one (`ROBOTS_SANCTIONED_SOURCES`: Stack Overflow, Reddit) and
  the caller's own HTML. One fetch of the file per host per hour
  (`fetch/robots.py`); a file that cannot be fetched means allow. Per request:
  `FetchConfig.respect_robots` / `fetch.respect_robots` on the API, the same switch the
  crawl has always had. Measured on the live suite (24 sites, main@8b49391 vs this): two pages flip to a
  refusal -- thesun.co.uk (`User-agent: * / Disallow: /`, 189 blocks read before) and
  old.reddit.com (disallowed now, a login wall before); every other page identical
  (amazon's recall moved 0.69 → 0.27 on an oracle that served 566 vs 1,548 words to the
  two runs; our 1,163 words were the same). Fidelity suite: no page moved.
- Rules are asked for by the client's name. `urllib.robotparser` matches the first
  `/`-split token of the string it is given, and the engine's browser-shaped User-Agent
  made every rule for `webgraph` a rule for `mozilla`, which no robots.txt names; the crawl
  had the same bug (`RobotsPolicy.allows`, `crawl_delay`). `ROBOTS_AGENT_TOKEN`.

### Added (2026-09-14, PR #82) — a declared client for sites that ask who is calling
- sec.gov answers the engine's browser-shaped User-Agent with HTTP 403 and a page saying
  "Your Request Originates from an Undeclared Automated Tool … declare your traffic by
  updating your user agent to include company specific information". That is not a wall
  against automation, it is a question, and it is now answered: when a refusal says so
  (`declaration_demanded`) and the deployment has `WEBGRAPH_CONTACT` set
  (`Name contact@example.com`), the page is fetched again — static and browser — as
  `<contact> webgraph/0.1`, the form the site documents (measured: a URL in the string is
  refused, `Name email webgraph/0.1` is admitted). The contact goes only to a site that
  asked; every other page gets the ordinary fetch. Without a contact the refusal names the
  setting and quotes the demand (`PageBlockedError.kind == "undeclared"`); a site that keeps
  refusing a declared client is refused as such. `ResolvedPage.identity_declared` and the
  stream's `resolve` event say when a page was served to the declared client.

### Fixed (2026-09-14, PR #81) — the blocking API routes see walls
- `/api/text` and `/api/extract` resolve the page through `resolve_page`, the path the
  streaming route and the crawl already used. They fetched and parsed on their own, with
  none of the wall checks (#64, #67, #73): a Cloudflare block page served with a 200, or a
  login redirect, came back as a page of text with a green tick. Now both answer 502 with
  the wall's own words. `render=false` still escalates a JavaScript shell to the browser;
  without one, `/api/extract` still reads the shell's hydration payload (`PageShellError`
  carries the document) and `/api/text` refuses, having nothing to say.
- A static-only refusal says what the status means and quotes the server ("HTTP 403 -- the
  site refused this client; it said: …") instead of "HTTP 403"; the quote skips the block
  page's stylesheet, which used to be most of it.

### Changed (2026-09-14, PR #80) — docs
- `docs/SESSION-18-WHOLE-PAGE.md` closes the evening: PRs #71–#79 in the merge table, the
  standings at `main@f0b0ac4`, the fidelity suite on that commit recall 1.000 on 22 of 29 scored sites, sqlite.org 0.749 → 1.000, MDN extra 0.228 → 0.142; nothing below 0.945,
  and the open items with their sites. CONTRIBUTING names the rule the night taught:
  a change to table, code or Markdown rendering re-runs WebMainBench before merge.
- Recorded late for PR #76: the fidelity oracle reads open shadow roots' visible text
  beside `innerText` (a full DOM walk was measured and rejected — arngren.net recall
  0.99 → 0.877 under it), joins a frameset's frames, and reports `ORACLE BLOCKED`
  instead of a score when Chromium was served a wall.

### Changed (2026-09-14, PR #79)
- Benchmarks page: WCXB dev routed 0.861 → 0.862 (per type: article .945, docs .929,
  service .846, forum .801, collection .695, listing .706, product .637), WebMainBench
  overall 0.733 / table 0.395 after #78, measured at `main@19f601f`; the progression
  gains the whole-page step.

### Fixed (2026-09-14, PR #78)
- A pipe table's cells carry their links only when the caller asked for links; #68 had
  rendered `[text](href)` into every cell regardless of `include_links`, which cost
  WebMainBench (scored with links off) table_edit 0.390 → 0.338 unnoticed. Back to 0.395;
  overall 0.7284 → 0.7331.

### Fixed (2026-09-14, PR #75) — Markdown structure a reader sees
Found by a census of 25 old and plain pages against Chromium's own text.
- `<hr>` is a block (`BlockKind.RULE`, rendered `---`); it was dropped outright on 6 of
  the 14 census sites whose markup was inspected (catb.org, gutenberg.org, pgsql docs,
  ibiblio.org …). A rule has no text: it is not in `text`, not a block to the boundary
  step, the block model or the page-type router (each takes rules out and puts them back
  between kept neighbours), never content on its own, and never a duplicate. A rule the
  browser gave no box is not a line the reader sees and is left out. A page of rules and
  nothing else selects nothing (PR #77).
- `<dl>` renders as a definition list a reader can parse — `**term**` on one line, `:
  definition` on the next, the Markdown Extra / Pandoc / kramdown form — instead of
  alternating paragraphs (cl.cam.ac.uk's Unicode FAQ, every php.net parameter list). A
  `<dd>` holding paragraphs keeps them under its marker, a list inside one is indented.
- A table kept as its own markup (merged cells) fused the words on either side of a
  `<br>`, `<p>` or `<li>` inside a cell (`<td>a<br>b</td>` → `ab`); breaks are kept and
  block children get one, links stay, images in cells keep `src` and `alt` (both follow
  `include_links` / `include_images`, as everywhere else). Rendering
  such a table as pipes when its only span is a full-width title row was measured on
  WebMainBench and rejected (table_edit 0.3365 → 0.3305; the corpus's own truth writes
  that shape as HTML 6 times and as pipes once).
- An inline `<svg>` with `SVG_MIN_TEXT_NODES` (2) labels or `SVG_MIN_WORDS` (3) words is
  read for its `<text>` labels, in document order, joined with `·` (sqlite.org/lang.html's
  railroad diagrams: 206 → 267 words, a quarter of the page). An icon — a `<title>` and
  no text, or one word — still emits nothing, and leaves the sentence it sat in whole.

### Fixed (2026-09-14, PR #74)
- A skip link to the page's main region (`href="#content"` → `<main id="content">`) no
  longer makes every hidden container inside it count as "openable"; a reference to a
  region is not a control for a tray inside it, a reference to the tray itself still is.
  A page with a code editor keeps its hidden source listings for the editor's block.

### Added (2026-09-14, PR #73) — login walls
- A fetch redirected to a login page is refused as the wall it is, named as one:
  `PageBlockedError` says `redirected to a login page (<final url>)` and carries
  `login_url` and `kind` (`login` / `challenge` / `block`). The final URL has to hold a
  `LOGIN_PATH_MARKERS` segment (`/login`, `/uas/login`, `/signin`, `/sso`, `/auth`,
  `/session/new`, `/wp-login.php`, …) or a `LOGIN_RETURN_PARAMS` parameter naming the page
  that was asked for (`?dest=…`, `?session_redirect=…`, `?next=…`), and the document has
  to be a login page rather than a page with a login on it: a password field, or fewer
  than `MAX_LOGIN_PAGE_WORDS` (150) words. old.reddit.com's threads
  (`/login/?reason=lor2&dest=…`, 4 words) and www.linkedin.com/feed/
  (`/uas/login?session_redirect=…`, 52 words, two password fields) are refused;
  news.ycombinator.com (a "login" link, 711 words) and github.com/python/cpython are
  pages. A login redirect on one fetch beside the real page on the other is left out
  like a bot wall, and the page is read from the other side.

### Fixed (2026-09-14, PR #73) — code editors
- A browser-side code editor's DOM (CodeMirror 5 and 6, Monaco, Ace) is one `code` block:
  its lines in order, the gutter's line numbers, cursor and measuring layers left out,
  the language from the widget (`data-language`, `data-mode-id`, a `language=` attribute
  on the host). developer.mozilla.org's `<interactive-example>` came out as one
  paragraph per line number and one per line, with the other tab's lines scattered among
  them. An editor that draws only the lines in view (CodeMirror 6 shows 30 of MDN's 40)
  takes the whole text from the hidden `<pre>` the page holds beside it, once, so the
  demo's source appears whole and where the editor is (MDN's `<table>` page: 713 → 625
  rendered blocks; whole-page extra_share against Chromium's innerText 0.492 → 0.477,
  recall 1.0).

### Added (2026-09-14, PR #72)
- `benchmark/fidelity/run.py` (`make bench-fidelity`): the whole-page Markdown scored
  against Chromium on 32 old, plain and ugly pages — word recall (nothing lost), extra
  share (nothing added), order inversions, structure counts — with a cached oracle and
  `--compare`. It refuses to score a walled oracle and reads a frameset's frames. The PR
  template and CONTRIBUTING name it as the measure for changes to blocks, the union,
  ordering or rendering. `docs/SESSION-18-WHOLE-PAGE.md` records the session.

### Fixed (2026-09-14, PR #71)
- An old MediaWiki `editsection` strip (`[edit]` beside every heading and table row on
  cppreference.com, hidden by its stylesheet) is a heading control like `mw-editsection`:
  a quarter of that page's words, and the member-function tables emitted twice.
- A frameset's `<noframes>` body stands in only when no frame could be fetched; with the
  frames read it is not on the page (cs.cmu.edu repeated the title frame and a second
  table of contents).

### Fixed (2026-09-14, PR #69)
- A table or code block a page shows more than once stays more than once on a page the
  browser could not measure (a static fetch, a browser refused by a wall):
  columbia.edu/~fdc/sample.html shows one demo table four times and came out with one.
  A repeat sitting in a run that repeats the first copy's run — the mobile grid beside
  the desktop grid — is still a hidden twin and goes; so does a repeat with nothing
  between it and the first copy. Repeated *text* on an unmeasured page stays
  deduplicated: measured on WCXB and Zyte, keeping it by the same rule cost 0.0017 and
  0.003 (businessinsider.com carries its article three times, interleaved with different
  furniture); a rendered page keeps real repeats through their rectangles, as before.

### Fixed (2026-09-14, PRs #66, #68)
- `<li><p>…</p></li>` (DocBook, Sphinx, MediaWiki) yields list items: the item's first
  paragraph is the item, later paragraphs its continuation, indented under the bullet
  (catb.org's eight lists, tldp.org's HOWTO index) (#66; WCXB +0.0001).
- Links inside table cells survive into the pipe table (`Block.rich_rows`; craigslist's
  "best of" is a table of links) and a link that wraps nothing but an image keeps its
  target (`Block.link`, rendered `[![alt](src)](link)`; spacejam.com/1996's planets) (#68).

### Fixed (2026-09-14, PR #65)
- What the browser hid stays hidden through the static+rendered union: a block only the
  static fetch had, whose text the renderer laid out as `display: none` / `visibility:
  hidden`, is not "content the render lost" and stays out (php.net's hidden manual TOC,
  cppreference's hover menus, nasa.gov's mega-menu: 330 → 233, 254 → 135, 299 → 153
  blocks; live suite: allbirds precision 0.11 → 0.75, ikea 348 → 205 blocks, recall
  unchanged on every page).
- A fragment-href anchor whose text is only a permalink glyph (`¶`, `#`, `§`, `🔗`) is a
  permalink whatever its class; php.net's script-added `¶` no longer duplicates every
  heading.

### Added (2026-09-14, PR #65)
- `tools/runs_dashboard.py`: a dependency-free local page (`http://127.0.0.1:8765/`)
  showing every benchmark run on the machine — running / finished / failed, elapsed,
  a progress bar from the runner's own counter lines, the last output and the result
  tables. `tools/run_logged.py <label> -- <command>` starts a run with its command, pid,
  start and exit recorded beside the log so the state is exact.

### Fixed (2026-09-14, PRs #64, #67)
- A bot wall served to one of the two fetches (plain or browser) while the other got the
  real page is left out and named in `render_error`, instead of being merged into the
  page's text (columbia.edu/~fdc/sample.html: Cloudflare's "Performing security
  verification … Ray ID" sentences were presented as content). A wall beside a fetch
  with fewer than `MIN_PAGE_BESIDE_WALL_WORDS` (20) words of its own still raises
  `PageBlockedError` (old.reddit.com's login redirect: an empty logo and "Skip to main
  content" are not the page), as do walls on both sides.

### Fixed (2026-09-14, PR #63) — pre-CSS pages read whole
Found reading old and ugly pages against Chromium for the whole-page `markdown`, where
nothing may be lost. Boards: WCXB dev +0.0001, Zyte 0.945 → 0.945, WCEB 0.856 → 0.856
(cleaneval, the old-HTML corpus, 0.890 → 0.895), WebMainBench 0.7297 → 0.7319, live
suite unchanged.
- A `<frameset>` page was read as an empty JavaScript shell; its frames are fetched
  statically (same host, up to eight, two levels) and composed in frameset order
  (cs.cmu.edu/~rgs/alice-table.html: 0 → 307 words). `render_error` says so.
- Bare text under `<body>`, `<center>`, `<font>`, `<form>` and `<fieldset>` was emitted
  by nobody (textfiles.com word recall 0.787 → 1.0).
- `<br>` is a line break and `<br><br>` a paragraph break: an address keeps its lines
  (a Markdown hard break), a `<br><br>`-separated article becomes paragraphs, headings,
  captions and list items stay one line. Source newlines still collapse to spaces.
- A `<blockquote>` that holds structure (a table, a list, paragraphs) is walked into and
  each block inside carries `Block.quoted`, rendered `> ` per level, so an indented table
  is a table (columbia.edu/~fdc/sample.html).
- Found by measuring the above: split paragraphs came out reversed and, when the article
  sat inside one `<span>`, every heading ahead of every paragraph (AppleInsider); the
  orphan-run walk now goes through inline wrappers and flushes per container. Also on
  `main` all along: a data-table cell fused words across `<br>` and block children
  (`a<br>b` → `ab`).

### Fixed (2026-09-14, PRs #59, #60, #62)
- Hidden twins of visible text (CSS-module mobile/desktop copies) are matched as a group;
  screen-reader-only text is detected by its measured 1px box; deduplication keys ignore
  whitespace (linear.app 401 → 337 blocks) (#59).
- Opacity-0 elements are measured and ordered where they sit; text inside a collapsed
  `overflow: hidden` ancestor (an accordion) is slotted after its heading (#60).
- A closed `<dialog>` / `aria-hidden` modal is not on the page; hidden content nothing
  opens is dropped (karnataka.gov.in 9,270 → 726 words) (#62).

### Added (2026-09-14, PR #61)
- `tools/inspect_page.py`, `tools/inspect_corpus_page.py`, `benchmark/live/run.py` and
  `benchmark/wcxb/per_page.py`: the diagnostic commands the PR template's repro steps use.

### Added (2026-09-14, PRs #55, #57)
- `/api/text` and the page stream return `comments_markdown`: the comment thread found
  under the content, in page order, left out of `content_markdown` instead of thrown away.
  The extract view shows it as a collapsed section (#55).
- `include_hidden_text` on `/api/text` and `--include-hidden-text` on the CLI keep
  screen-reader-only labels, skip links and wiki edit controls for callers that want every
  string in the DOM; the default still strips them (#57).

### Changed (2026-09-14, PRs #54, #56)
- A single block contributes at most 400 words to the mean the adaptive block cost is
  drawn from; a 2,100-word contributor list no longer prices the page (#54).
- Product pages: seller, shop-policy, "Did you know?", payment and report-listing sections
  are pruned like reviews and related grids (#56; WCXB product +0.003).
- Benchmarks page: WCEB ranks the two output fields joined (0.883, first) and the content
  field alone (0.856, second); the diagnostic-variant row is gone.

### Changed (2026-09-13/14, PRs #48–#52)
- Extraction quality, measured on the corpus runners in `benchmark/`: WCXB dev routed
  0.855 → 0.861 (first of the published field, by 0.002), WCXB test 0.864 → 0.875, Zyte
  article-extraction 0.934 → 0.945, WCEB production path 0.852 → 0.856.
- A long block that restates what several other blocks already say (an `articleBody`
  microdata copy of the article, a reply quoting a whole post) is dropped (#48).
- Pre-HTML5 chrome names (`div#footer`, `div.nav`, `.main-menu`, …) are stripped; a rail
  never holds the page's `<h1>` or `itemprop="articleBody"`; camelCase cookie dialogs are
  consent (#49).
- The adaptive block cost ratio is 0.60 (was 0.70), re-swept after the structural steps
  changed what the boundary step sees (#50).
- A river of teasers at its own heading level ends where the article resumes, not at its
  first kicker (#51).
- The declared article body (`itemprop="articleBody"`, `entry-content`, `story-body`, …) is
  a structural scope after `<main>` and `<article>`; `Block.body_of` is new and `methods`
  gains `"article-body"` (#52).
- Benchmarks page: the WCEB row is the production path (0.856, second) rather than the
  comments-kept variant (0.874) it showed before; that variant is drawn as a reference
  line with the reason (Dragnet and cetd count comment threads as content).

### Changed (2026-09-13, PRs #13–#28)
- Extraction quality, measured on the corpus runners in `benchmark/`: WCXB dev routed
  0.820 → 0.853, WCXB test 0.856, Zyte article-extraction 0.895 → 0.928, reading-order
  discriminating pairs 0.505 → 0.936. `docs/SESSION-16-LIVE-HARDENING.md` lists every fix
  with its number and the experiments that were rejected.
- `Document.text` no longer includes image alt text or media placeholders; they remain in
  the Markdown. Callers that relied on alt text in `text` should read the Markdown.
- Screen-reader-only labels (`sr-only`, `visually-hidden`, …) are stripped at parse time.
- Comments under an article are stripped unless the comments are the page; forum pages keep
  them. `<aside>` landmarks are stripped unless they name themselves as callouts.
- Cookie-consent dialogs and named filter panels are stripped (`Block.widget`).
- Product pages get a sheet policy (reviews and related grids pruned, `Label: value` lines
  kept); product and collection pages refuse a run under a quarter of the page.
- The renderer marks floats (`data-wg-float`) and hidden elements (`data-wg-hidden`); floats
  are read as one unit and hidden twins dropped.
- MediaWiki pages are routed by namespace; edit-section strips are removed.
- Repository: pull request and issue templates, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  `SUPPORT.md`, `CODEOWNERS`, Dependabot; `CONTRIBUTING.md` states the test-per-fix and
  measurement rules.

### Added
- Extraction engine: geometric reading-order recovery, rich Markdown rendering, JSON-schema
  mapping with provenance, technology fingerprinting, unlimited route discovery and
  cross-page site-chrome removal.
- FastAPI service exposing single-page extraction and a streamed whole-site pipeline.
- Next.js 16 front end: photographic landing page and a dedicated `/extract` run view with
  Discovered / Queued / Extracted / Failed tabs over the live crawl.
- Benchmarks for extraction quality and for route discovery against a real-browser oracle.
