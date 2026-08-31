# MEMORY — working log & self-learning loop

Append-only engineering journal. **Read this first** on any new session before touching code.
Purpose: never repeat a failed approach, never re-derive a settled decision.

Format per entry: what was attempted → what happened → what was done instead → status.
Newest entries at the **bottom** of each section.

---

## Working agreement

- **Owner:** shashank@pebbleroad.com. Away from keyboard; authorised autonomous work until return.
- **Goal order:** engine (extraction) first → prove it works → *then* Next.js app + FastAPI backend.
- **Monetization is explicitly out of scope.** Innovation/quality first, by owner's instruction.
- **Everything evidence-backed.** Claims trace to `docs/research/2026-08-31-findings.md`, which marks
  every finding as `[V]` verified (3-vote adversarial) or `[U]` extracted-but-unaudited. Do not treat
  `[U]` as settled. Six claims were actively **refuted** — see §6 of that doc, do not reuse them.
- **Stack (fixed by owner):** Python + `uv`, Next.js + `pnpm`, production conventions throughout.

---

## Environment facts (verified 2026-08-31)

| Item | Value |
|---|---|
| Machine | Apple M2, 8 cores, 16 GB RAM, macOS (Darwin 25.5.0) |
| Python | 3.14.3 · uv 0.10.12 |
| Node | v24.17.0 · pnpm 11.13.1 |
| Docker | installed, **daemon not running** |
| LLM keys | **none present** — no `ANTHROPIC_API_KEY` or any provider key in env or shell profile |

### Gotchas already hit — do not rediscover these

1. **`timeout` does not exist on this macOS.** `timeout 12 du -sh …` returns *silently empty*, which
   looks exactly like a hang. It is `command not found`. Use `gtimeout` (coreutils) or no timeout.
   This cost one wasted diagnostic round and produced a wrong initial conclusion ("du is timing out").
2. **Disk was at 280 MB free of 245 GB.** Reclaimed to ~13 GB on 2026-08-31 via: `npm cache clean
   --force`, `uv cache clean` (3.9 GB), `pnpm store prune` (2.45 GB), and removal of VSCode/Cursor
   ShipIt installer caches, Google, node-gyp, electron, Homebrew, puppeteer caches.
   - **Left deliberately untouched:** `~/.cache/huggingface` (23 GB — model weights, expensive to
     re-download, likely tied to owner's Qwen3/Unsloth work) and `~/Library/Developer/CoreSimulator`
     (5.7 GB). These are the next reserves if space runs low again. Ask before taking them.
   - `docker system prune` **could not run** — daemon down. `~/Library/Containers/com.docker.docker`
     is 8.1 GB and still reclaimable if Docker Desktop is started.
3. **Watch disk continuously.** Playwright browsers (~500 MB) plus `node_modules` will eat into the
   13 GB fast. Check `df -H /System/Volumes/Data` before any large install.

---

## Settled decisions

Decisions that are closed. Reopen only with new evidence, and log the reason here.

| # | Decision | Rationale | Source |
|---|---|---|---|
| D1 | Build the **live-page extraction layer**; consume everything else | Best evaluated system reaches 48.58% F1 vs 86.60% human on LiveWeb-IE. Crawl, PDF, retrieval are commoditised. | findings §2, `[V]` |
| D2 | **Page-level success** is the headline metric, never field-level F1 | Field-level overstates usable quality ~3× (94.78% F1 → 70.73% page-level). | findings §3, `[V]` |
| D3 | Hydration-payload / structured-data fast path **before** any model call | Needs zero LLM. Highest ROI stage in the pipeline. | findings §5, `[U]` |
| D4 | Query-aware **DOM pruning** before extraction | ~96.5% context reduction, corroborated at 97.9% by a second group. Caveat: measured on static 2011-era HTML. | findings §3, `[V]` |
| D5 | Selector induction is **not one-shot** — validate every replay, detect drift | >15 absolute F1 decay on structurally evolved sites. | findings §3, `[V]` 2–1 |
| D6 | Extraction target is a **user-supplied JSON Schema**, not a fixed vertical schema | Owner chose general-purpose across all site types, superseding the B2B-SaaS schema in PRD v1 §2.6. | owner instruction |
| D7 | Every fact carries provenance: `source_url`, `source_span`, `extractor`, `modality`, `confidence` | Required for citations, and for never letting a low-confidence modality overwrite a high-confidence one. | PRD v3 §3.5 |
| D8 | **Do not** default to a graph for QA; route to it for multi-hop only | Graph costs 40–57× to index and wins only on multi-hop; HippoRAG2-class ~40× cheaper per query than community-summarization GraphRAG. | findings §4, `[U]` |
| D9 | Storage: **not KuzuDB** | Vendor abandoned it Oct 2025; Graphiti deprecates it. Owner mentioned a "LadybugDB" fork — **unverified, must check before relying on it.** | findings §5, `[U]` |

---

## Open questions blocking work

| # | Question | Blocks | Status |
|---|---|---|---|
| Q1 | Which constrained-decoding backend (Outlines / XGrammar / llguidance / vLLM)? | LLM extraction path | **Genuinely unknown** — all JSONSchemaBench evidence was refuted 0–3. Needs fresh primary measurement. |
| Q2 | Tech-stack fingerprinting accuracy | Stage 0 routing | Unevidenced. Building heuristics and measuring them locally. |
| Q3 | Is "LadybugDB" a real Kuzu successor? | Storage (far off) | Unverified. Research named Kineviz's "bighorn" fork instead. |

---

## Attempt log

Every non-trivial failure goes here with its replacement. This is the part that must not be lost.

### 2026-08-31

- **Attempted:** `du -sh` inventory of home dir with `timeout` guards.
  **Result:** all rows empty; misread as "disk so full that `du` hangs."
  **Cause:** `timeout` is not installed on macOS.
  **Instead:** ran `du -sxh` without guards; completed in seconds.
  **Status:** resolved. Recorded as gotcha #1.

- **Attempted:** `docker system prune -a -f --volumes` to reclaim 8.1 GB.
  **Result:** `failed to connect to the docker API … daemon not running`.
  **Instead:** reclaimed 12 GB from npm/uv/pnpm/installer caches, which was sufficient.
  **Status:** deferred, not failed. Docker space still available if needed.

---

## D10 — Reading-order preservation (owner requirement, 2026-08-31)

**Requirement (owner, verbatim intent):** extracted text must preserve *reading order*. Multi-column
and complex layouts must not produce jumbled paragraph sequences.

**Why this is hard — the core insight:** **DOM order ≠ visual reading order.** CSS can reorder content
relative to source: `order:` on flex children, `flex-direction: row-reverse`/`column-reverse`,
explicit `grid-row`/`grid-column` placement, floats, `position:absolute`, and `direction:rtl`.
A naive depth-first DOM walk therefore silently produces wrong order on exactly the pages that
matter most (news, docs, academic, magazine layouts).

**Consequences for the design:**
- Reading order must be recovered from **geometry** (bounding boxes) whenever a render is available,
  not from tree traversal alone.
- Multi-column pages need **column segmentation before vertical sort** — sorting all blocks by `y`
  alone interleaves columns, which is the classic failure.
- Static (non-rendered) HTML has no geometry. Fall back to DOM order, but *flag* the document as
  `reading_order: dom-fallback` so downstream consumers know the confidence is lower.
- This is the same problem PDF parsers solve; OmniDocBench measures it explicitly. Borrow the
  approach (XY-cut / column clustering), do not reinvent.

**Status:** implemented in `webgraph.dom.reading_order`. Must have direct tests with
synthetic reordered-CSS fixtures, not just happy-path DOM.

### Reading order verified against a real browser (2026-08-31)

Chromium + Playwright, four fixtures in `packages/engine/tests/fixtures/`. All four are
layouts where DOM order and visual order genuinely disagree, so a regression to a plain
tree walk fails loudly:

| Fixture | DOM order | Recovered reading order |
|---|---|---|
| `flex_order` (`order:` on flex children) | GAMMA, ALPHA, BETA | **ALPHA, BETA, GAMMA** ✓ |
| `two_column` (`flex-direction: row-reverse`) | HEADER, RIGHT×3, LEFT×3, FOOTER | **HEADER, LEFT×3, RIGHT×3, FOOTER** ✓ |
| `grid_placement` (explicit `grid-column`/`grid-row`) | B1, A1, B2, A2 | **A1, B1, A2, B2** ✓ |
| `css_columns` (`column-count: 2`) | ONE…SIX | **ONE…SIX** ✓ (unchanged, correctly) |

**Geometry binding — the design that avoided a whole class of bug.** Rects are produced in
the browser but consumed by lxml. Recomputing an XPath in JavaScript to match lxml's
`getpath()` is fragile: the two disagree about when to emit a positional index, and a
mismatch fails *silently* (zero geometry, silent fallback to DOM order). Instead the browser
stamps `data-wg-id` on every element **before** serialising the DOM; lxml then finds each
element by that attribute and generates the key itself. The key is produced by the same
library that consumes it, so mismatch is structurally impossible.

**Known limitation — CSS Grid is genuinely ambiguous.** For a 2×2 grid, "read across rows"
(table semantics) and "read down columns" (newspaper semantics) are both defensible, and
humans disagree too. The gap-width heuristic decides: wider gutter wins. `grid_placement`
lands on row-wise because its column gap and row gap are close. This is not a bug to fix
blindly — any fix must pick a side, and the current side (follow the wider gutter) is at
least principled. Revisit only with real-page evidence.

**Also confirmed:** `wait_until="networkidle"` is the right default for hydrated pages —
`load` fires before hydration completes, and measuring then captures the pre-hydration
layout. The fixtures use `load` only because they are static local files.

### Benchmark v0 baseline established (2026-08-31)

`benchmark/corpus-v0/` — 6 snapshots across 6 site types (ecommerce, saas, news, spa-ssr,
spa-rsc, docs). Snapshots not live URLs: a benchmark whose answers change underneath it
measures nothing.

**First run, structured-data path only, zero LLM calls:**

```
page_level_success = 83.3%   (5/6)   <- headline
field_accuracy     = 89.5%
missing            = 10.5%
wrong              =  0.0%   <- the safety property
```

Three things this establishes:

1. **The field-vs-page gap is real and reproduces here.** 89.5% field accuracy against
   83.3% page-level, on a 6-page corpus. This is the effect that makes field-level F1 the
   wrong headline metric (D2).
2. **`wrong_rate == 0.0` is the core safety property and is now a test**
   (`test_engine_never_emits_a_wrong_value`). Every failure is a *miss*, never an invented
   value. The `_coerce` function declining `"contact us"` rather than producing `0` is what
   buys this. If this number ever rises above zero, something started guessing.
3. **The one failure is `docs-static`, which ships no structured data at all.** That is not
   a bug — it is the evidence for exactly where the selector/model path is required, and it
   was included deliberately rather than curated away.

**Do not "fix" the docs-static case by widening the alias table.** Speculative aliases are
how a zero wrong-rate turns into a nonzero one. It needs the extraction path that does not
exist yet, not a looser matcher.

### App layer built and verified end-to-end (2026-08-31)

**Stack:** uv workspace (`packages/engine`, `apps/api`) + pnpm workspace (`apps/web`).
`make api` + `make web` runs the full stack. Verified live: API on :8000 returns
`render_available: true`, Next.js on :3000 serves the UI, and a live extraction against
`https://schema.org/Product` returned 390 blocks and multiple JSON-LD payloads.

**Gotchas hit and fixed — do not rediscover:**

1. **`--render` was silently ignored for local files.** `_load_source` returned early on any
   local path before reaching the render branch, so `webgraph text --render fixture.html`
   handed back DOM order — the wrong answer on a CSS-reordered page, with no error. Local
   files are valid `file://` URLs and Playwright loads them fine. Fixed; the render path now
   applies to local and remote alike.

2. **`requires_render` fired on any short page.** The heuristic was `text_length < 200`
   alone, so a genuinely brief page (a 404, a login form, a stub doc) triggered a needless
   browser launch — hundreds of ms and ~150 MB each. Now requires *corroborating* evidence
   that something is meant to run: an empty framework mount point, or sparse text alongside
   script bundles. Caught by a CLI test, not by the profiler's own tests.

3. **The engine shipped no `py.typed`.** mypy in `apps/api` reported the engine as untyped
   despite it being `mypy --strict` clean. Added the marker plus
   `artifacts = ["src/webgraph/py.typed"]` so it survives into the wheel.

4. **pnpm build-script approval.** `unrs-resolver` needs a build script; pnpm refuses to run
   `pnpm <script>` until approved. The `pnpm` key in `package.json` is **no longer read** —
   `onlyBuiltDependencies` belongs in `pnpm-workspace.yaml`, and **only pnpm >= ~11.24 reads
   it there**. The globally installed pnpm is 11.13.1, which does not. Fixed by pinning
   `"packageManager": "pnpm@11.24.0"` so corepack supplies a version that honours it.

5. **API renders are capped at 2 concurrent** (`MAX_CONCURRENT_RENDERS`). Browser launches
   are the memory bottleneck; without the semaphore a handful of simultaneous requests will
   exhaust a 16 GB laptop. Raise only with measurements.

**Status:** engine 186 tests + API 13 tests, all passing. ruff clean, `mypy --strict` clean
across both Python packages, `tsc --noEmit` and `next build` clean.

### Not yet built — the honest gap

The **selector induction / drift-detection path (D5)** and the **query-aware DOM pruning
stage (D4)** are designed and documented but not implemented, because both exist to feed a
model call and there is no API key in this environment (see Working agreement). The
`docs-static` benchmark case is exactly what they would fix. This is the next work.

---

## Completeness work — measured against 24 real sites (2026-08-31, session 2)

Owner requirement: *"I don't want to miss even 0.1% of data or contents."* That forced a
measurement rather than an opinion. Method: fetch each site statically and rendered, extract
both, and compare character counts. **The delta IS the missed content.**

### D11 — You cannot predict whether a page needs rendering. Stop trying.

First measurement, 19 sites reachable:

- 7 sites lost content on the static path.
- `requires_render` returned **False on all 7**. Detection accuracy: **0/7**.
- Worst: reddit at 1.8% coverage, nextjs.org at 0.0%.

After tightening thresholds, the catastrophic cases are caught but the partial ones are not:
`angular.dev` 68%, `python.org` 81%, `notion.com` 82%, `remix.run` 94% — all still reported
as complete. **This is not a tuning problem.** A page holding 2,078 characters carries no
signal that another 969 appear after hydration. There is nothing left to threshold on.

### D12 — Rendering is not a strict upgrade; it can DESTROY content.

`bbc.co.uk/news`: static 19,943 chars, rendered **832** chars. A consent wall replaces the
article. Choosing the rendered document loses ~95% of the page.

`nuxt.com`: 12 blocks unique to static AND 12 unique to rendered. Both modes lose content.

**Conclusion: on the sites measured, no single fetch mode is complete.** Hence `resolve.py`.

### D13 — The union strategy (`webgraph/resolve.py`)

Fetch both, merge by normalised block text, keep everything. Rendered order leads (it is
measured); static-only blocks are appended with `rect=None` because inventing a position
would corrupt the ordering the render was performed to obtain.

Measured result on 10 sites: **union beat static-alone on 8/10, and rendered-alone on 4/10.**

Coverage ratios are clamped to 1.0 — the union deduplicates, so a duplicate-heavy static doc
can exceed the union's character count (BBC showed 108% before clamping).

### Fixed bugs — do not reintroduce

1. **`wait_until="networkidle"` timed out on 5 of 24 sites (21%)** — Shopify, Squarespace,
   Stripe, python.org, Figma. `networkidle` waits for 500ms of network silence, which never
   arrives on sites with analytics beacons, polling or websockets. Changed to `load` +
   `settle_ms=900`. **All 24 sites now resolve.** Never set this back to `networkidle`.

2. **"Short page with no scripts is complete"** — this rule reported `nextjs.org`, which
   returns a zero-text bot-challenge page, as complete. **Zero text is never complete.**
   `_EMPTY_TEXT_CHARS = 50` now short-circuits before every other rule.

3. **A hydration payload does NOT mean no render is needed.** `nextjs.org` ships a payload
   and zero visible text. The old rule returned early on payload presence. Removed; there is
   now a regression test (`test_next_js_shell_requires_render_despite_payload`).

4. **`analyze.py` read only block deltas**, which are zero when the static fetch fails
   outright — so it reported "static HTML is complete" for a page that returned nothing.
   `render_required` is now derived from coverage as well.

### Licensing correction — supersedes PRD v3 §2.1

PRD v3 claimed the Wappalyzer fingerprint rulesets are MIT. **They are not.** Verified via
the GitHub API on 2026-08-31:

| Repo | License | Health |
|---|---|---|
| `enthec/webappanalyzer` | **GPL-3.0** | active, 571 stars |
| `HTTPArchive/wappalyzer` | **GPL-3.0** | active |
| `dochne/wappalyzer` | **GPL-3.0** | stale since Nov 2024 |
| `tunetheweb/wappalyzer` | — | **404, does not exist** |

There is no permissively-licensed fingerprint ruleset. Vendoring any of these would force
this Apache-2.0 engine to GPL-3.0. The hand-written rules in `profile/fingerprint.py` are
therefore the correct choice, for a licensing reason the original research missed.

### Built this session

- `crawl/frontier.py` — URL normalisation, scoping, BFS frontier
- `crawl/discovery.py` — robots.txt, sitemap enumeration, link/canonical extraction
- `crawl/crawler.py` — batched-parallel BFS crawl with content-hash gating
- `resolve.py` — the union strategy
- `analyze.py` + `webgraph analyze` — Stage 0: technology, measured render verdict, page count

Verified live: `nextjs.org` 728 public pages; `quotes.toscrape.com` 12/12 crawled, 85 URLs
discovered. 221 engine tests, ruff and `mypy --strict` clean.

### Still not built

Web search budget for the session is **exhausted (200/200)**, so further literature research
needs a new session. The LLM extraction path, DOM pruning and selector induction remain
unbuilt (no API key). The QA/retrieval layer remains entirely unbuilt.

---

## Site pipeline (2026-08-31, session 3) — architecture then implementation

Owner asked for the architecture to be settled before implementing. Agreed shape:

```
Stage 0  ANALYZE    technology + MEASURED render verdict -> strategy for the whole site
Stage 1  ENUMERATE  robots -> sitemap -> normalise -> scheme reconcile -> VERIFY -> inventory
Stage 2  FETCH      per page, using Stage 0's strategy (static | union), hash-gated
Stage 3  EXTRACT    payloads + blocks + reading order + schema mapping
Stage 4  AGGREGATE  dedupe entities across pages, track which pages contributed what
```

Every stage degrades rather than aborts: one dead page is a recorded error, not a failed run.

### D14 — Sitemaps advertise a scheme the site may not serve

`ionidea.com`'s sitemap lists **`http://`** URLs; the site serves only **`https://`**. Every
fetch failed with `ConnectError: Network is unreachable`. A crawl would have returned **zero
pages** while Stage 0 correctly reported 90 available.

Fix: `reconcile_scheme(url, root)` in `crawl/frontier.py` rewrites the scheme to match the
root **only when the hosts match**, so it can never redirect a crawl to another site. Applied
to every sitemap URL in `discover_sitemap_urls`.

### D15 — A sitemap count is a claim, not a fact. Verify it.

`ionidea.com` advertises 89 URLs. Probing them: **4 live, 56 dead (404)** — roughly 7% of
what was checked. Reporting "89 public pages" would have been simply wrong.

`PageInventory` therefore reports `advertised` / `checked` / `live` / `dead` separately, and
`build_inventory` probes with a real GET (not HEAD — many servers answer HEAD incorrectly,
and a wrong liveness verdict costs more than the saved bandwidth).

### D16 — Report liveness against what was checked, not what was advertised

First version divided live pages by the **advertised** count. On smashingmagazine.com, which
advertises 4,999 URLs while only 36 were sampled, it printed **"Liveness 1%"** for a site
whose sampled pages were ~97% healthy. Badly misleading.

`liveness` is now `live / checked_count`, the report states the sample size explicitly, and
`fully_verified` distinguishes a complete check from a sample. Regression test:
`test_liveness_is_measured_against_checked_not_advertised`.

Related honesty fix: with no `--schema` supplied the report used to say "No page published
structured data matching the schema", implying the site was at fault. It now says no schema
was supplied.

### Measured outcomes

| Site | Advertised | Checked | Live | Entities | Text |
|---|---|---|---|---|---|
| ionidea.com | 89 | 60 | **4** | 2 | 9,458 chars |
| smashingmagazine.com | 4,999 | 36 | 35 | 12 | 263,256 chars |

**IonIdea's ceiling is the site itself**: 4 live pages publishing one `Organization` block
plus OpenGraph. Aggregation across it yields 2 entities and 4 schema fields, and no amount of
engine work changes that without the model path. This was flagged to the owner before
building Stage 4, and they chose to proceed regardless — a legitimate call, since the
machinery is correct and pays off on healthier sites.

### State

`webgraph site <url> [--schema f.json]` runs all five stages. 253 engine tests, ruff and
`mypy --strict` clean. Still unbuilt: model extraction path, DOM pruning, selector
induction, and the entire QA/retrieval layer.

---

## Frontend site pipeline + rich Markdown (2026-08-31, session 4)

Owner clarified what "rich content extraction" meant all along: **rich output** -- Markdown
keeping images, headings, tables, links -- not multimodal, and not schema facts. Earlier
sessions built the wrong thing off that misreading. Correcting it needed no API key.

### D17 — Structure must survive extraction

`dom/rich.py` + `render_markdown.py`. Text-only extraction destroyed nearly everything a
page means: headings became indistinguishable lines, images were dropped entirely, tables
flattened into loose cells with no column association, links lost their targets.

Blocks now carry a `BlockKind` (heading/list-item/table/image/code/quote/figure-caption)
plus level, href, alt, rows, language. Reading order sequences them exactly as before.

Measured on ionidea.com: **2,948 chars of flat text -> 4,654 chars of Markdown, 13 headings,
27 images**, from the same fetch.

Handles: lazy-loaded images (`data-src`, `srcset`), tracking-pixel rejection by declared
dimensions, ragged table rows (padded, never dropped), code-block language detection,
nested list indentation.

**Bugs caught by its own tests:**
- `<li>outer<ul><li>inner</li></ul></li>` **lost "outer" entirely** -- the innermost-block
  rule skipped any list item containing a sub-list. Fixed with `_own_text()`, which takes an
  element's own text excluding nested lists/tables.
- Ragged table rows were dropped rather than padded, losing cells.

### D18 — The site pipeline must stream, not block

`stream_site()` yields `stage` / `analysis` / `inventory` / `page` / `done` events; the API
exposes it at `POST /api/site/stream` as SSE.

A blocking response is not viable: union extraction renders every page in a browser, so a
40-page site runs for minutes and any single HTTP request times out. Streaming also matches
the real shape of the work -- stack known in seconds, inventory shortly after, pages one at
a time.

Implementation notes worth keeping:
- **SSE, not websockets** -- one-directional, survives ordinary HTTP infrastructure.
- Frontend uses `fetch` + `ReadableStream`, **not `EventSource`** (GET-only; the request
  carries a JSON body). The SSE frame buffer must be carried across chunks -- a frame can
  split across TCP reads.
- The synchronous pipeline runs in an executor, handing events back through an
  `asyncio.Queue`, so the response flushes as they arrive.

### Gotcha — `pkill -f "next start"` does not kill it

The Next.js server survived `pkill` and kept port 3000, so a rebuilt frontend silently
served the **old build** while reporting HTTP 200. The log only showed
`EADDRINUSE` on the *new* process. Use `lsof -ti:3000 | xargs kill -9` and verify the port
is free before restarting.

### State

`webgraph site` (CLI) and the "Whole site" tab (UI) both run: detect stack -> enumerate and
verify public pages -> extract rich Markdown per route -> aggregate entities. 285 engine
tests + 13 API tests, ruff and `mypy --strict` clean, frontend typecheck/lint/build clean.

---

## Route discovery + technology detection (2026-08-31, session 5)

### D19 — A sitemap is neither complete nor current. Always crawl links too.

Owner reported the engine finding 4 pages on a site with 20+, naming
`insurance-agentology.php` specifically. Verified:

- that page returns **200, 42,865 bytes** — genuinely live;
- it is **absent from the sitemap**;
- it **is linked from the homepage**.

So ionidea.com's sitemap is *stale* (89 URLs, mostly 404) **and** *incomplete* (misses live
pages). The old `build_inventory` only link-crawled when a sitemap was **absent**, so it
trusted a broken sitemap and never followed a single link.

Fix: `discover_by_crawling()` in `crawl/discovery.py` — a lean BFS link harvester that
fetches and extracts links only, never building a `Document` (discovery should cost less
than reading). `build_inventory` now **always unions sitemap + link-crawl**, dedupes,
verifies, and reports each source's contribution.

| ionidea.com | before | after |
|---|---|---|
| URLs discovered | 89 | **362** (89 sitemap + 273 crawled) |
| Live pages | 4 | **44** |
| Content extracted | 9,458 chars | **180,704 chars** |

Also: `reconcile_scheme` now applies to crawled links, not just sitemap URLs — internal
links hard-code `http://` on https-only sites just as often.

### D20 — Technology detection needs headers and runtime globals, not just HTML

Owner compared against Wappalyzer, which reported Hotjar, Google Analytics, Google Font API,
Apache 2.4.37, PHP 7.4.33, OpenSSL 1.1.1k, GTM, jQuery 3.6.0, Bootstrap. The engine showed
**"none detected"**.

Two root causes:

1. **The profiler never read response headers.** `Server: Apache/2.4.37 (Rocky Linux)
   OpenSSL/1.1.1k` and `X-Powered-By: PHP/7.4.33` are invisible in markup. `FetchResult` now
   carries `headers`, threaded through `resolve` -> `pipeline` -> `profile_page`.
2. **No rules** for analytics, tag managers, JS libraries, UI frameworks or fonts. The old
   `FRAMEWORK_RULES` covered only JS frameworks and CMSs.

New `profile/technology.py`: ~90 hand-written rules across 18 categories, matching markup,
headers and cookies, with named `version` capture groups.

**Runtime globals close the last gap.** `jquery.min.js` carries no version in its filename;
`jQuery.fn.jquery` reports it exactly. The render script now probes ~12 library globals and
those versions are authoritative. This is how jQuery **3.6.0** and Bootstrap **5.3.2** are
obtained — the latter a version Wappalyzer did not report at all.

Result on ionidea.com now matches Wappalyzer item-for-item, with versions.

**Licensing constraint that forced hand-written rules:** every maintained Wappalyzer ruleset
(`enthec`, `HTTPArchive`, `dochne`) is **GPL-3.0**; vendoring one would relicense this
Apache-2.0 engine. See D-note in session 2.

### State

307 engine tests + 13 API tests, ruff and `mypy --strict` clean, frontend
typecheck/lint/build clean. Servers running on :8000 and :3000.

---

## Unlimited crawling + UI rework (2026-08-31, session 6)

### D21 — Interleave discovery and extraction; never enumerate first

`stream_site` used to enumerate the whole site, then extract. Two problems: nothing appeared
for minutes on a large site, and the crawl was capped at whatever enumeration happened to
find up front.

Rewritten as a **continuous BFS**: each extracted page's links extend the frontier, so the
first result arrives in seconds and the crawl reaches everything reachable. `max_pages = 0`
means unbounded — run until the frontier is exhausted.

Measured:

| Site | Result |
|---|---|
| quotes.toscrape.com | **428 pages, 0 failures, frontier exhausted**, 120s |
| ionidea.com | 471 URLs discovered, 75 pages OK, 518 KB Markdown, 1,467 images, 60s |

ionidea went from **4 pages -> 75** across sessions 5 and 6.

Page events now carry live crawl state — `queued`, `discovered`, `newly_queued`,
`pages_per_minute`, running `totals` — so a UI can show genuine progress rather than a
spinner. `done` reports `exhausted` so "finished" is distinguishable from "hit the budget".

Defaults changed: `max_pages` 40 -> **0 (unlimited)**, `discovery_depth` 3 -> **12**
(a deep site is still finite; the page budget is the real bound), `sitemap_limit` -> 50,000.

### UI

Rebuilt `SiteCrawler`: live stat grid (discovered / queued / extracted / failed / rate /
elapsed), animated progress rail, phase indicator, technology chips grouped by category with
version pills, newest-first streaming page list with per-page image galleries and Markdown,
a hide-failures filter, and a **Download .md** button that concatenates every page.

Elapsed time ticks from a local interval rather than from events, so the UI does not look
frozen during the analyze step, which takes several seconds.

### Note for future work

At genuinely large scale (the owner mentioned ~20,000 pages) the browser holds every page's
Markdown in React state — roughly 100 MB at 5 KB/page. It works, but the right answer at
that size is streaming to disk server-side and paging the UI. Not yet needed; revisit if a
crawl of that size is actually run.

### State

307 engine tests + 13 API tests, ruff and `mypy --strict` clean, frontend
typecheck/lint/build clean. Servers on :8000 and :3000.

---

## Route-discovery benchmark vs a real browser (2026-08-31, session 7)

Owner asked for the engine's route discovery to be verified against what a real browser can
see, across ~50 sites, iterating on failures. Built `benchmark/route_discovery/`
(`make bench-routes`).

**Method.** A real Chromium instance loads each homepage, executes its JavaScript, and
reports every same-site anchor. That set is the oracle. The engine discovers routes its own
way; recall against the oracle is the score. Homepage-only, deliberately — it bounds the
comparison to one page load and keeps the benchmark fast enough to run often.

*Playwright, not the Claude Chrome tools, drives the 50-site run: it is the same Chromium
engine and can be scripted without hundreds of tool round-trips. The approach was
spot-checked with Claude Chrome on persyn.ai first and gave an identical link set.*

### D22 — `www.` and the bare domain are the same site (catastrophic bug)

persyn.ai declares `<link rel="canonical" href="https://www.persyn.ai/">` while resolving at
the bare domain. `same_site` compared hostnames exactly, so **every link on the site was
rejected as off-site** and the crawl finished after one page.

`same_site` now strips a `www.` prefix from both sides before comparing. Other subdomains are
still excluded by default.

**persyn.ai: 1 page -> 54 pages, 0 failures, 240 KB Markdown, 30 blog posts.**

### Result — 50-site corpus

```
sites scored          49   (nginx.com blocks headless; no oracle)
perfect recall        49/49
mean recall (engine)  100.0%
mean recall (static)   93.4%   <- what static-only discovery would score
```

The static column is the argument for the union approach, and some rows are stark:

| Site | static recall | engine recall |
|---|---|---|
| nextjs.org | **0%** | 100% |
| webpack.js.org | **7%** | 100% |
| persyn.ai | **17%** | 100% |
| vuejs.org | 62% | 100% |

### Two benchmark bugs found and fixed (the harness lied before the engine did)

1. Counted the homepage's **self-link** as a miss — measuring the harness's own bookkeeping.
2. Seeded with the **requested** URL rather than the post-redirect one, so
   `flask.palletsprojects.com/` -> `/en/stable/` scored a false miss.

Both were fixed before trusting any number. Worth remembering: a benchmark that flatters or
punishes wrongly is worse than none.

### Also fixed this session

`SiteRequest.max_pages` had `ge=1` while the new frontend sends `0` for unlimited — that
mismatch returned **HTTP 422** for any site (owner hit it on persyn.ai). Now `ge=0`.

### State

309 engine tests + 13 API tests, ruff and `mypy --strict` clean. `make bench-routes` runs the
50-site corpus; `make bench-routes-quick` runs the first 10.

### D23 — Gate extraction on HTTP status; a browser renders 404 pages happily (2026-08-31)

Owner reported seeing `# Not Found / The requested URL was not found on this server` in
extracted content.

Cause: `resolve_page` ignored the HTTP status entirely. `fetch_static` correctly returned
`ok=False, status=404`, resolve fell through to `RENDERED_ONLY`, and Chromium rendered the
server's error page into 171 characters of perfectly good "content".

This mattered because ionidea.com's relative links resolve into hundreds of URLs that do not
exist (`.../ARTICLE/contact-us`, `.../ARTICLE/microservices`), so the engine was manufacturing
error-page documents by the dozen.

Fix: `MISSING_STATUSES = {404, 410}` checked **before** anything else in `resolve_page`,
raising `PageMissingError`. `site.py` records it as a clean per-page failure.

**403/429/5xx are deliberately excluded** — those mean *blocked* or *transient*, not
*absent*, and rendering frequently succeeds where a static fetch was refused. nextjs.org
returns 200 with an empty shell and depends on the render path; reddit likewise. Verified
both still resolve after the change.

| ionidea.com full crawl | before | after |
|---|---|---|
| "successful" pages | 75 | **66** |
| failures | 396 | 427 |
| markdown | 517,956 chars | 483,010 |

The drop is the fix: 9 pages were 404 error documents, ~35 KB of "Not Found" text.

Owner's specific page confirmed extracted throughout:
`.../dynatrace/blog/4-Factors-Why-Observability-Is-A-Key-Tool-for-Modern-Systems/` — 5,020
chars, 60 blocks.

**Open, not yet fixed:** ionidea.com emits relative links that resolve against the article
path rather than the section root, generating those hundreds of phantom URLs. The engine now
handles them correctly (records failures, extracts nothing) but still spends fetches on them
— 427 of 493 URLs. A "sibling-path 404 pattern" heuristic could prune them, but it risks
skipping real pages; not attempted without evidence it is safe.

### D24 — Astro detection, and two false-positive classes (2026-08-31)

Owner reported an Astro site going undetected. Two different things share the name and both
were broken:

**Astro (the framework).** The old rule was `astro-island|data-astro-|<astro-`. But a fully
static Astro build -- Astro's entire selling point, zero client JS -- ships **no island
marker at all**, so the most common Astro site was invisible. The reliable signals are
`<meta name="generator" content="Astro v7.2.6">` (with version) and the `/_astro/` asset
path. Both added; `astro.build` and `docs.astro.build` now report **Astro 7.2.6**, plus
**Starlight 0.41.8**.

**Astra (the WordPress theme).** No rule existed. Added, along with GeneratePress, OceanWP,
Divi, Elementor, WPBakery, Beaver Builder and Kadence -- WordPress builders are everywhere
and were entirely invisible.

Also added a generic **generator-meta** family (WordPress, Drupal, Hugo, Docusaurus, Gatsby,
Next.js, Nuxt, SvelteKit, VuePress, MkDocs, Sphinx, Wix) with version capture. Many CMSs and
SSGs declare themselves there and only a handful were hardcoded before.

#### FP class 1 — documenting a technology is not using it

`docs.astro.build` was reported as running **Strapi and Alpine.js**, purely because its
sidebar links to `/guides/cms/strapi/` and `/guides/integrations-guide/alpinejs/`. Bare-word
rules match prose.

#### FP class 2 — cookie-consent vendor tables

`wpastra.com` reported **35 technologies**, including four competing chat widgets (Crisp,
Drift, Intercom, Tawk.to) and five competing analytics tools. All came from an embedded
consent-manager lookup table:

```json
{"cdn.amplitude.com":["analytics","amplitude"],"client.crisp.chat":["functional","crisp"], ...}
```

Requiring a path after the host did **not** fix it -- the table contains paths too
(`"plausible.io/js"`). The working discriminator is **attribute context**: a loaded script
appears inside `src="..."`/`href="..."`, a consent entry is a bare JSON key. 22 host-based
rules were re-anchored accordingly.

**wpastra.com: 35 -> 15 technologies.** ionidea.com unchanged at 11 (no regression).

**Governing principle, now in the module docstring:** patterns must match *implementation*,
never prose. Anchor to a `src`/`href` attribute, a generator meta, a namespaced class, or a
JavaScript global. Executable signals (`fbq('init'`, `mixpanel.init(`, `_hjSettings`,
`grecaptcha.`) stay unanchored -- they are evidence of execution, not a URL.

**Gotcha for future edits:** these rules are one-per-line `_rule(...)` calls; a rewrite regex
must expect the line to end `),` not `,`. Two attempted bulk edits silently changed nothing
because the tail group was wrong, and the "fix" appeared to have no effect.

---

## 100-site route benchmark (2026-08-31, session 8)

`make bench-routes` — 100 sites, real-browser oracle. Baseline saved at
`benchmark/route_discovery/baseline-2026-08-31.txt`.

```
sites scored          93     (7 block headless: vercel, netlify, render,
perfect recall        85/93   behance, dribbble, workandco, etsy)
mean recall (engine)  97.7%
mean recall (static)  91.4%
```

Standout rows where rendering is decisive: nextjs.org static **0%**, webpack.js.org **7%**,
persyn.ai **17%**, remix.run **40%**, retool.com **78%**, vuejs.org **62%** — all 100% with
the engine.

### D25 — Deduplicate on a canonical key, not the raw URL

`solidjs.com` redirects to `www.solidjs.com`. `same_site` accepted both (fixed in D22) but the
frontier's `_seen` set keyed on the **raw string**, so every page was queued twice — once per
hostname form. Doubles the crawl and duplicates every extracted entity.

`canonical_key()` strips `www.` and a trailing slash. It is **only a key**: the queued URL
stays the one the site actually linked to, because some hosts serve just one form and
rewriting the request would 404.

solidjs missed routes: 7 -> 3. readymag.com went to perfect.

### The remaining gaps are mostly not engine defects — measured, not assumed

Investigated each rather than tuning against them:

| Site | Missed | Cause |
|---|---|---|
| neon.tech | 37 | `/unify?a=<uuid>` — a **fresh session UUID per load**. Unreproducible by construction. |
| notion.com | 2 | `?tid=<session>` — same. |
| awwwards.com | 11 | **Rotating featured links.** Two consecutive loads by the *same* crawler differ by 7 links. |
| solidjs.com | 3 | 1 is a Cloudflare `cdn-cgi/content?id=<token>` challenge URL; 2 genuine. |
| planetscale.com | 4 | `/legal/*`, likely a first-visit consent banner. |
| instrument.com, nuxt.com | 1 each | genuine. |

**Hypotheses tested and rejected** (do not retry these):
- *Longer settle time* — 900ms vs 3500ms produced byte-identical link sets.
- *Resource blocking suppressing JS* — blocking images/media/fonts vs blocking nothing gave
  identical counts on both suspect sites.

**Benchmark limitation now understood:** a single-load oracle has an irreducible error floor
on sites with rotating or session-scoped content. ~97.7% is close to the practical ceiling
for this method, not a defect to tune away. Chasing it would mean fitting the crawler to
benchmark noise.

### Benchmark bugs fixed (the harness lied twice more)

- Compared link sets by **raw string**, so the www/bare split scored solidjs as a near-total
  miss. Now compares on `canonical_key`.
- (Earlier) counted the homepage self-link as missed, and seeded pre-redirect.

Three of the benchmark's own bugs have now been found by using it. Distrust the harness at
least as much as the thing it measures.

---

## Depth-2 route benchmark, and what manual Chrome actually adds (2026-08-31, session 9)

Owner pushed repeatedly for manual Claude Chrome verification. I deflected twice on the
grounds that Playwright is the same Chromium. **That was wrong on one point that matters:**
Claude Chrome drives the user's real, non-headless browser, so it reaches sites that block
headless entirely. Measured:

| Site | Playwright oracle | Manual Chrome |
|---|---|---|
| vercel.com | no oracle (blocked) | **78 routes** |
| netlify.com | no oracle (blocked) | **51 routes** |

### Constraints discovered — why "all 100 manually" is not achievable as stated

1. **Per-site permission.** Claude Chrome refuses domains the user has not allowed
   (`render.com` -> "Navigation to this domain is not allowed"). Granting ~90 domains is the
   user's action, not something the agent can do.
2. **CSP blocks exfiltration.** A local collector on `127.0.0.1:8099` was built so payloads
   would bypass the agent's context; page CSP blocked `fetch` to it on both vercel.com and
   render.com. Not viable generally.
3. **Tool results truncate.** Returning a site's full path list hit truncation at ~169
   routes, so per-site path data cannot come back through Chrome at 100-site scale.

Net: manual Chrome is the right tool for the handful of bot-blocked sites, and impractical
as the primary oracle. The *algorithm* it proved is what transferred.

### D26 — Homepage-only discovery badly under-reports

The manual Chrome session proved depth-2 discovery in one round trip: fetch each nav target
**same-origin from inside the page** and read its links too. On render.com this took the
oracle from **51 routes to 169** (and to 624 once both sides used it).

Both oracle and engine now do depth-2. Effect on the same three sites:

| Site | homepage-only oracle | depth-2 oracle | static-only recall |
|---|---|---|---|
| render.com | 51 | **624** | 8% |
| linear.app | 46 | **128** | 36% |
| persyn.ai | 12 | 17 | 35% |

Mean static-only recall fell from 91.4% (depth-1) to **26.5%** (depth-2) -- the shallow
benchmark had been flattering static discovery enormously.

### Benchmark bug #4 — sub-page selection order

First depth-2 run scored 81.7%, with linear.app showing **70 misses**, all `/customers/*`.
Cause: the oracle picked its 14 sub-pages in **DOM order** while the engine picked them
**alphabetically**, so each explored a different subset. That measures ordering luck, not
capability. Both now sort before slicing; the same three sites went to **100%**.

Four of this benchmark's bugs have now been found by using it (self-link, pre-redirect seed,
raw-string comparison, selection order). Standing lesson: **distrust the harness at least as
much as the thing it measures.**

---

## Competitive research + experiments (2026-09-01, session 10)

Web *search* budget is exhausted; `WebFetch` on specific URLs still works. All figures below
are from primary sources.

### What the field actually does

**Trafilatura benchmark** (its own eval page, 990 documents, dated 2026-08-04):

| tool | precision | recall | F |
|---|---|---|---|
| html2text | 0.525 | 0.900 | 0.663 |
| beautifulsoup4 | 0.532 | 0.980 | 0.690 |
| inscriptis | 0.534 | 0.991 | 0.694 |
| readability-lxml | 0.898 | 0.764 | 0.826 |
| justext | 0.864 | 0.859 | 0.862 |
| **trafilatura 2.2.0** | **0.906** | **0.943** | **0.924** |

**This engine sits in the bottom cluster.** Extracting every text block is ~0.99 recall /
~0.53 precision -- the `inscriptis`/`html_text` profile, F ~= 0.69. Best-in-class is 0.924.

**Trafilatura is Apache-2.0 from v1.8.0** (GPLv3+ before). It is therefore *consumable* by
this Apache-2.0 engine -- unlike the Wappalyzer rulesets. Worth evaluating as the
main-content extractor rather than building one.

**Firecrawl does not use a research-grade extractor.** Its `apps/api/package.json` lists
`cheerio`, `jsdom`, `turndown` + `joplin-turndown-plugin-gfm`, `marked`. No
`@mozilla/readability`, no boilerplate library. So the commercial leader is *also* in the
"convert everything to Markdown" class. Core is AGPL-3.0.

### D27 — Cross-page boilerplate detection (new capability, no model)

A block appearing on nearly every page of a site is chrome. A single-page extractor cannot
know this; a whole-site crawler gets it free. `webgraph/boilerplate.py`.

Measured, static crawl, 40 pages each: **books.toscrape.com 37.0% of all text removed**,
**docs.pytest.org 8.8%**. Dropped items were verified as genuine chrome ("Home", "Books",
"Logo", "Get Started"); kept items were titles, prices, API reference.

**Thresholds of 50%, 70% and 90% produced identical block sets on both sites.** Chrome is
all-or-none, so there is nothing to tune -- use the conservative 90%. Pinned by a test so a
future session does not waste a day tuning it.

Two guards, both from real hazards: a page's own leading heading is never removed (a
category page titled "Travel" beside a sidebar link "Travel"), and a page that is >95%
chrome is left untouched (sitemaps and indexes genuinely are navigation).

### D28 — Inline links were being discarded entirely

Comparing against trafilatura on danluu.com exposed it: **engine 0 inline links, trafilatura
201.** `text_content()` throws away every `href`, so `<a href="x">text</a>` became bare
`text`. For an engine whose stated job is rich extraction, the URL is frequently the most
useful part of the line.

Fixed with `_inline_markdown()`: links, `**bold**`, `*italic*`, `` `code` ``. Now **207 links
vs trafilatura's 201** on the same page.

Stored in a **separate `Block.rich_text` field**, not folded into `text`. Deduplication, the
content hash and reading order all key on the plain form; injecting Markdown syntax would
change every hash and make two renderings of one sentence look like different content.

### Measurement lesson

The first engine-vs-trafilatura comparison reported danluu.com at "0.5x, 51.8% of content
missing". Both numbers were artefacts: trafilatura had been called with
`include_links=True` (inflating its char count with `[text](url)`) while the engine emitted
no links at all. Plain-vs-plain, the two were **8,945 vs 9,138 chars -- 98% agreement**.
Compare like with like before concluding anything.

### Next

Evaluate trafilatura as a main-content extractor behind a flag and measure the engine's own
precision against it. Cross-page boilerplate is not yet wired into `stream_site` or the UI.

### D29 — Template differencing shipped (2026-09-01)

`webgraph/boilerplate.py` now identifies site chrome two ways and unions them:

- **repeated text** -- catches a footer line that moves position between templates;
- **static slots** -- an exact XPath present on >=60% of pages that *never varies*.

Wired into `stream_site` behind `SiteConfig.remove_chrome` (default on). Each page event
gains `content_markdown` alongside `markdown`; the profile is computed once, the first time
`MIN_PAGES` documents exist, and reused. `done` reports `chrome_blocks` / `chrome_slots`.

**Exact XPath, never generalised.** Stripping positional indices to collapse equivalent slots
over-collapses: many distinct blocks land in one slot, which then holds many texts and never
qualifies as static. Measured +0.006 F -- nothing. Exact paths reached F=0.950 on
docs.pytest.org in isolation. Do not "improve" this by generalising.

Final measured effect on the shipped path, vs a majority vote of
trafilatura/readability/justext, four diverse sites:

```
raw              F=0.725
chrome-stripped  F=0.760      recall UNCHANGED on all four (0.903/0.986/0.991/0.995)
trafilatura      F=0.903
```

Precision gains +0.001 to +0.093. danluu.com has almost no chrome (2 blocks) and correctly
changes by ~0 -- the detector does not invent chrome where there is none.

### D30 — Near-duplicate corpora break chrome detection (guard added)

Crawling docs.pytest.org reached its **version archive** (`/en/8.2.x/`, `/en/8.1.x/`, ...),
which are near-identical pages. Their *shared real content* then looks exactly like chrome
and detection removed **60.3% of every page**.

`MAX_REMOVAL = 0.5`: if stripping would remove more than half a page, return it untouched.
Diverse corpora measure 9-37%, so the cap separates the cases cleanly. After the guard:

| corpus | pages stripped | removed |
|---|---|---|
| version archive (near-duplicate) | 12 -> **3** | 50.2% (at cap) |
| diverse | 11 | **8.6%** |

Rationale for failing open: a wrong removal is silent data loss; a missed removal is noise
the caller can still see and handle.

**Still imperfect** -- on the pytest sample, "Hide navigation sidebar" and "Toggle Light /
Dark / Auto color theme" survived stripping. UI affordances whose slots shift between
templates are not yet caught. Not a regression, just not solved.

---

## Serving the engine to more than one caller (2026-09-01, session 11)

### D31 — An abandoned crawl kept running until the process died

Symptom the user saw: `Discovered 1.6k / Extracted 1 / Rate 2/min`. The engine itself is
not that slow — measured directly, six workers on the same site do **33 pages/min**.

Cause: `loop.run_in_executor(None, produce)` followed by `task.cancel()`. Cancelling a
future whose function has already started **does nothing**; `produce()` kept iterating
`stream_site` and pushing into a queue nobody was reading. Every reloaded tab left another
full-speed crawl behind, and they were all competing for the same machine.

A Python generator cannot be interrupted from another thread — closing it only raises at
the next `yield`, which never arrives while a batch of renders is in flight. So the engine
has to poll: `stream_site(..., should_stop=Callable[[], bool])`, checked at the top of each
batch. The SSE generator's `finally` sets the flag, which fires on client disconnect.

Verified: client killed mid-crawl, **0 Chromium processes alive 25s later**.

Two related fixes in the same place:
- Crawls run on a dedicated `ThreadPoolExecutor`, not the default one. The default executor
  is shared with every `asyncio.to_thread` call, and a few parked crawls starve ordinary
  requests.
- `MAX_CONCURRENT_CRAWLS = 3` with a semaphore. Over the cap, callers **wait** and are told
  so via a `stage` event, rather than getting a 429 — a crawl is a long operation and a
  queue is friendlier than a rejection.

### D32 — Reuse one browser per worker thread (measured)

`render_page` launched and tore down a whole Chromium per page. Playwright's *sync* API
binds its driver to the creating thread, so a shared pool would need the async API; a
**thread-local** browser is the shape that fits. Each page still gets its own
`BrowserContext`, which costs milliseconds and keeps isolation.

12 renders of persyn.ai:

| workers | launch per page | reused |
|---|---|---|
| 1 | 8.5 pages/min | **11.6** |
| 6 | 21.9 pages/min | **39.1** |

`MAX_BROWSERS = 6` caps live browsers process-wide (~150 MB each). A thread that cannot get
a slot launches its own short-lived browser, so correctness never depends on the pool.

### D33 — Discovery is streamed as deltas, not as the frontier

The UI needed to list discovered and queued URLs, not just count them. Sending the frontier
on every event is quadratic — 1,600 URLs × 1,600 events. Instead `Frontier.extend()` returns
the URLs it newly accepted and every `frontier`/`page` event carries them as `new_urls`; the
client rebuilds the same set from the deltas.

The tab counters are computed from those client-side sets rather than from the server's own
tallies. The two differ by whatever is in flight when an event was emitted, and a tab
reading "1,612" above a list of 1,606 rows is worse than being a few behind.

### Front end rebuilt (Next.js 16 + Tailwind v4)

Landing page at `/`, run view at `/extract?url=…&mode=site|page`. Search parameters are read
in the **server** component and passed down, which sidesteps the `useSearchParams()`
Suspense requirement entirely.

Upgrade notes, each of which broke the build:
- `next.config.ts` no longer accepts an `eslint` key.
- `pnpm add typescript@latest` installs **TypeScript 7**, which `typescript-eslint` does not
  support. Pinned to `^6`.
- ESLint 10 breaks `eslint-plugin-react` 7.37 (`context.getFilename` removed). Pinned to `^9`.
- `eslint-config-next` v16 ships flat configs; the `@eslint/eslintrc` `FlatCompat` bridge is
  gone. Import `eslint-config-next/core-web-vitals` and `/typescript`.
- The new `react-hooks/purity` and `react-hooks/set-state-in-effect` rules reject
  `useRef(Date.now())` and `setState` in an effect body. Both were real: the wall-clock read
  during render is not idempotent, and the `setState`s were redundant given the component is
  keyed by URL.

**Dropped deliberately:** the "Limit pages" control. Unlimited is the point (D21); Stop
covers the rest, and `?max=` is still honoured for scripted use.

### D34 — Bundled frameworks have no global; read the DOM instead

persyn.ai reported four technologies where Wappalyzer reported seventeen. The interesting
misses were React and React Router, and the reason is structural: a Vite build exposes **no
`window.React`**, and the only mention of React anywhere in the markup was inside a
Content-Security-Policy *comment* — exactly the prose a rule must never match.

React does leave private properties on the DOM nodes it owns (`__reactContainer$…`,
`__reactFiber$…`). The browser-side collector now scans the first few dozen elements under
`body` / `#root` / `#app` for those keys, and does the same for Preact (`__preactattr_`),
Vue (`el.__vue_app__`), Svelte (`__svelte_meta`) and React Router
(`__reactRouterContext`, `data-discover`). That is evidence the framework is *running*.

Presence without a version needs a representation: the collector returns the sentinel
`"present"`, and any reported value not starting with a digit is treated as no version.

Markup rules added for libraries that ship as modules with no global — Lucide
(`class="lucide lucide-*"`), Lenis, Radix (`data-radix-*`), shadcn (`data-slot`), PostHog,
Tinybird — plus the standards Wappalyzer reports: Open Graph, PWA, Priority Hints, HTTP/3.

Tailwind is the one worth explaining. A keyword match fires on any page that writes the
word. The rule instead requires a **responsive-prefixed utility** inside a `class`
attribute (`md:grid-cols-3`); no other framework puts `md:` in a class name.

persyn.ai: 4 detected -> **15**, matching 13 of Wappalyzer's 17. The four still missed are
Radix, shadcn, Tinybird and Cloudflare Bot Management, all of which appear only after an
interaction or a later request rather than in the homepage's rendered DOM.

---

## Technology detection rebuilt around runtime evidence (2026-09-01, session 11)

### D35 — The gap with a browser extension was signal sources, not rules

persyn.ai: engine 4 detections, Wappalyzer 17. Adding markup rules moved it to 13 and then
stalled, because the remainder were **not in the markup at all**. Wappalyzer is an extension
— it sees the network log, the cookie jar, the live heap and the loaded script text.

An exploration script dumped everything persyn.ai actually exposes. The answer was that all
of it was reachable and none of it was being read:

```
window keys   fbq, Tinybird, lenisVersion, __reactRouterVersion,
              __PosthogExtensions__, __core-js_shared__
cookies       __cf_bm (Cloudflare bot management), _fbp, ph_phc_… (PostHog)
requests      us-assets.i.posthog.com, connect.facebook.net/…/fbevents.js,
              /_vercel/insights/script.js, *.r2.dev
versions      fbq.version = 2.9.390, __core-js_shared__.versions[0] = 3.32.2
```

Four new signal sources, each a new `TechRule` field:

| field | matched against | closes |
|---|---|---|
| `js` | the **name** of a global the page added | Tinybird, React Router, core-js, Lenis |
| `request` | any URL requested while loading | PostHog, Vercel Analytics, Cloudflare R2 |
| `cookie` | cookie names **from the jar**, not `Set-Cookie` | Cloudflare Bot Management |
| `source` | the page's own JS bundle text | Radix, Sonner, Zod |

**The global list is discovered, not enumerated.** A blank same-origin iframe provides a
pristine `window`; the diff against the real one yields every global the page added. Probes
only find what someone thought to name — the diff found `Tinybird` and `lenisVersion` with
nobody naming them first.

**Bundle fetching is once per site, never per page.** Bundles are megabytes; `analyze_site`
reads at most 4 same-origin scripts up to 3 MB total. Third-party scripts are skipped —
they are already identified by their request URL.

### D36 — Some technologies have no fingerprint and must be inferred

**shadcn/ui is not a dependency.** Its components are copied into the project's own source,
so there is no package name, no global, no request and no attribute that says "shadcn".
What there reliably is: the packages its registry installs.

Hence `IMPLICATIONS`: `requires` (all must be present) plus optional `any_of` (at least one),
producing a technology at **reduced confidence** with an evidence string naming what it was
inferred from. Also covers Next.js → React, Nuxt → Vue, Starlight → Astro, WooCommerce →
WordPress.

Implications must run over the **union of passes**, not inside one: shadcn needs Tailwind
from the markup pass and Radix from the bundle pass. Hence `merge_technologies()`.

### Result

| site | before | after | vs Wappalyzer |
|---|---|---|---|
| persyn.ai | 4 | **23** | **17/17**, versions matching exactly |

The 6 extra are real and Wappalyzer missed them: Cloudflare R2, Vercel Analytics, Vercel
Speed Insights, Sonner, Zod, HSTS — each verifiable in the network log or the bundle.

### Two false positives this created, and the fix

- **`data-slot` is not shadcn.** It is a plain web-component attribute; Vercel's Geist uses
  it, so nextjs.org was credited with shadcn/ui. The markup rule is gone; the attribute now
  counts only inside the bundle, next to shadcn's own packages.
- **`window.L` is Leaflet's global and also anybody's one-letter variable.** Likewise bare
  `ga`. Both replaced with request/source rules.

Standing lesson: a new signal source multiplies both true and false positives. Sweep a set
of sites with known stacks after every rule addition, and check the two-letter globals first.

---

## The graph layer (2026-09-01, session 11)

The question this answers: a 200-page crawl is millions of tokens. What goes in the context?

### D37 — A website already is a graph; do not pay a model to invent one

GraphRAG, LightRAG and their descendants spend an LLM pass to *infer* entities and relations
from flat text. A crawl does not need to, because the edges are already published:

| edge | observed from | what an inferred graph pays for it |
|---|---|---|
| page links to page | `<a href>` | an LLM pass over both pages |
| what the link *means* | the anchor text, written by a human | an LLM-written relation label |
| section belongs to page | heading structure, in recovered reading order | a chunker's guess |
| page describes entity | JSON-LD / microdata, typed and often `@id`-keyed | entity extraction |
| page is a child of page | the URL path | usually lost entirely |

Every edge is observed, deterministic, free and carries provenance. Same commitment as the
extraction engine, one layer up.

**Sections, not pages, are the retrieval unit.** A heading owns the text under it until the
next heading of equal or higher level -- the author's own idea of where a topic starts. This
is only correct because reading order was recovered first: on a multi-column page, source
order does not say which paragraphs sit under which heading.

### D38 — The experiment, and three wrong turns it caught

Harness: crawl a site, build the graph, generate three question types. **Single-hop** is a
control (query from page B's own rare vocabulary). **Multi-hop, no overlap** takes the query
from page A and requires the answer on a linked page B whose rare vocabulary the query does
not contain. **Multi-hop, weak overlap** allows 1-3 shared terms -- the realistic case.

Metric: gold-page recall at a fixed budget (3-4% of the site).

**Wrong turn 1 — the first result said the graph made things worse.** It did not; the
harness was wrong twice. The "multi-hop" queries included the link's anchor text, which is
usually the target's own title, so they were not multi-hop at all (BM25 scored 77.5%). And
the baselines had different content budgets. Fixed both; BM25 then scored **0.0%** on
no-overlap, which is what a correct harness must show.

**Wrong turn 2 — reserving budget for neighbours did nothing.** Sweeping the reservation
from 0 to 0.8 produced a flat line. Diagnosis, rather than more guessing, showed why: the
gold page was **reached in 100% of failures** and merely ranked too low -- median rank 86 of
~160 when the budget fits ~15. The reservation also had a genuine bug (seeds spilled into
the neighbour purse before neighbours were considered), so the parameter was inert.
Budget allocation was never the problem; ranking was.

**Wrong turn 3 — summing evidence helped one case and hurt the other.**

| site | combine | single | no-overlap | weak-overlap |
|---|---|---|---|---|
| attrs | max | 100.0% | 26.0% | 75.0% |
| attrs | sum | 100.0% | 27.5% | 52.8% |
| attrs | **sum + mass-conserving** | 100.0% | **27.5%** | **97.2%** |
| pytest | max | 97.5% | 17.4% | 50.0% |
| pytest | sum | 95.0% | 18.0% | 42.5% |
| pytest | **sum + mass-conserving** | **97.5%** | **18.6%** | **55.0%** |

Plain summing rewards hubs: a page linked from everywhere collects a little from every seed
and outranks the page that answers the question. Normalising each seed's outgoing
contribution so it spreads a fixed mass fixes it, and wins every bucket.

### D39 — Final measurement

Budget = 30,000 chars, 3-4% of the site.

**attrs.org** — 39 pages, 796k chars:

| bucket | naive | BM25 | graph |
|---|---|---|---|
| single-hop | 7.7% | 100% | 100% |
| multi-hop, no overlap | 8.6% | **0.0%** | **30.1%** |
| multi-hop, weak overlap | 16.7% | 58.3% | **100%** |

**docs.pytest.org** — 45 pages, 947k chars:

| bucket | naive | BM25 | graph |
|---|---|---|---|
| single-hop | 5.0% | 97.5% | 97.5% |
| multi-hop, no overlap | 10.6% | **0.0%** | **17.4%** |
| multi-hop, weak overlap | 12.5% | 30.0% | **60.0%** |

The no-overlap bucket is near the information-theoretic floor -- an average page links to
~14 others and the budget fits ~15 sections, so a page reachable only by link is close to a
coin toss. The honest claim is the weak-overlap row, which is what real questions look like:
recall roughly doubles.

### D40 — Three tiers, so a truncated context does not lie by omission

Budget is spent as: full sections, then section openings, then a **map** -- title, URL and
headings for every page that did not fit. The map is cheap and changes the failure mode:
instead of silently omitting the pricing page, the context says it exists and where it is,
which is what an agent needs in order to ask for it.

### Why BM25 and not embeddings

No model, no API key, no index build, deterministic -- so retrieval can be benchmarked the
same way extraction is. Seeding is isolated behind one function so a vector seeder can be
dropped in and *measured against* this one rather than assumed better.

### D41 — Permalink anchors are structure, not characters

Documentation generators attach a permalink to every heading: Sphinx `<a class="headerlink">¶</a>`,
Docusaurus `<a class="hash-link" aria-hidden="true">#</a>`. It reached the reader as
`Testimonials¶`, the index as a junk token, and the Markdown as a glyph on every heading of
every docs site.

Matched on the **class**, not on the character. A regex stripping a trailing `¶`/`#` from
headings would mutilate `The C# language`. Extraction benchmark unchanged after the fix
(83.3% page success, 0% wrong), so it removes only what it should.

### Live-run defects the graph work surfaced

- **Near-duplicate sections.** attrs.org's crawl reaches `/en/19.2.0/` beside `/en/stable/`,
  so three copies of one section took three of fourteen slots. An exact hash misses them —
  the copies differ in a version number — so dedup fingerprints the opening 300 characters
  plus a length bucket.
- **Budget overrun of 7%.** The per-section cost estimate ignored the provenance header each
  section is rendered with. Cost is now measured, and the map tier gives way until the whole
  thing fits: a caller who asks for 18,000 characters must not be handed 18,500.

---

## Cross-site: several websites, one graph (2026-09-01, session 11)

### D42 — Off-site links are out of scope for crawling, not for the graph

Every crawl sees hrefs pointing off-site and threw them away. They are the natural join
between two crawled sites: add the second site and an edge that pointed nowhere becomes an
edge between two crawled pages, labelled with the anchor text a human wrote.

`Corpus.merged()` returns an ordinary `SiteGraph`, so `ContextAssembler` and the exporters
work over several sites with no changes at all.

Measured on the Pallets documentation — Flask, Jinja and Click, 55 pages, 943 sections:

```
query                                   sections drawn from
render a template with autoescaping     jinja 21, flask 6, click 1
define a custom command line option     click 27, flask 3
escape untrusted html in output         jinja 18, flask 3, click 2
blueprint url prefix                    flask 25
```

One index over three sites, and lexical seeding routes each question to the right one.

### D43 — Two bugs the corpus work exposed

**`parent_path` had never fired.** `canonical_key` keeps the scheme, so partitioning a key
on its first slash produced a host of `https:` and a candidate that could never match a
page. One of the five expansion signals had been dead since it was written. Graph keys now
drop the scheme -- which is also correct on its own terms, since `http://x/a` and
`https://x/a` are one page and an edge between them should join rather than fork.

**Cross-site links resolved 1 out of 419.** Sites link to the address they *publish*
(`jinja.palletsprojects.com/templates`); the crawl files the page under the address it was
*served* (`/en/stable/templates`) after a redirect it never had cause to request.

Two fixes. `SiteGraph.aliases` records the requested URL and the `rel=canonical` for every
page, which covers redirects the crawl itself followed. `Corpus.resolve_external()` handles
the rest with one bounded request per unresolved target — only for hosts already in the
corpus, deduplicated, capped at 60. **4 lookups turned 1 cross-site link into 8**, with
anchors reading "Jinja", "Click", "Jinja Template Documentation", "BaseLoader",
"Jinja for loops", "Flask".

It is an explicit call, not part of `merged()`: a merge should not silently touch the
network.

### D44 — No fuzzy entity resolution

"Acme Inc." and "Acme Corporation" stay two entities. Identity comes from an `@id` both
sites published, or from the same type and the same name — never from a similarity
threshold. A wrongly merged entity silently fuses two subjects, which is the same failure
mode as a wrongly removed block of chrome, and gets the same answer: fail open.

Names shorter than four characters are ignored entirely. "API" appearing on two sites says
nothing about them being the same API.

### Open: the entity layer is empty on documentation sites

`entities: 0, mentions: 0` on attrs, pytest, Flask, Jinja and Click. Entities come only from
JSON-LD and microdata, which marketing sites publish and documentation sites do not. The
`MENTIONS` edge and the entity bridge are therefore inert on exactly the corpus where
cross-site linking was just demonstrated. Next.

### D45 — Derived entities: a mostly negative result, kept anyway

`entities: 0, mentions: 0` on every documentation site. Entities came only from JSON-LD and
microdata, which marketing sites publish and documentation sites do not.

Two derivations, both observed rather than inferred:

- **A page's subject is what other pages call it.** The anchor texts pointing *at* a page
  are the site's own names for it, agreed across many pages, written by its authors. Free.
- **A symbol is defined where it appears as a heading and used as inline code elsewhere.**
  Two independent pieces of evidence, which is what separates `Environment` the class from
  `Installation` the section.

It works, in the sense that it produces output: 0 -> 31/75/14 entities and 0 -> 185/115/139
mentions across attrs, pytest and Jinja. **Neither retrieval claim survived measurement.**

*Within a site*, sweeping the mention edge's weight from 0.0 to 0.7 moved mean gold-page
recall across three sites by under a point in either direction:

```
weight   single   no-overlap   weak
  0.00    97.5%       42.6%   74.9%
  0.25    97.5%       42.1%   75.8%
  0.70    97.5%       41.9%   75.8%
```

*Across sites*, on Flask + Jinja + Click: **shared entities: 0.** Subject keys are
page-scoped by design, and the symbols the three sites define do not overlap (Flask 0,
Jinja 6, Click 1, intersection empty).

**Kept as a descriptive feature, not a retrieval one.** The entity list is a genuinely
useful account of what a site is about, with the aliases its own authors use, and the
machinery is what makes structured-data-rich sites bridge on `@id` as intended. The mention
weight is set to 0.25, where it measured harmless.

**Not done: name-keying subjects so they would bridge.** Half the derived names are generic
-- "Introduction", "Getting Started", "Environment" -- and name-keying would declare every
site's introduction to be one subject. A bridge that wrong is worse than no bridge.

The working cross-site channel is the link one (D42/D43), which measured 8 real edges with
anchors naming each relationship. That is the answer to "how do the sites connect"; entities
are a weaker second channel that currently connects nothing.
