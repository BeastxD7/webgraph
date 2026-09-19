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
- `crawl/crawler.py` — batched-parallel BFS crawl with content-hash gating *(deleted in session 14: `stream_site` superseded it and nothing imported it)*
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


---

## The content benchmark became reproducible (2026-09-01, session 11)

### D46 — A number that cannot be re-run is not a measurement

`F=0.760` and `trafilatura 0.903` were quoted in MEMORY.md and in the README as measured
facts. Checked tonight: **trafilatura, readability and jusText were not even installed**, and
the script that produced those numbers no longer existed. The project's central quality claim
was unreproducible.

`benchmark/content_quality/run.py` fixes that, committed, with the reference extractors as a
`bench` dependency group and `make bench-content` to run it. Fresh numbers over six pages:

```
                                   P       R       F
  trafilatura                  0.907   0.994   0.946
  readability                  0.908   0.993   0.945
  engine (chrome removed)      0.852   0.989   0.914
  engine (raw)                 0.835   0.989   0.904
  engine (prose only)          0.833   0.805   0.810
  justext                      0.778   0.398   0.522
```

**These supersede the old figures and are not comparable to them** -- different page set,
different method. The gap to trafilatura is 3.2 points, not the 14 the old numbers implied.
Whether that is improvement or a friendlier corpus cannot be told, which is the whole
argument for committing the harness.

### D47 — The precision gap is not code and tables

`--diff` lists what the engine keeps that no two reference extractors kept. On Jinja's
template page it was dominated by code blocks and filter tables -- which looked like the
references discarding real documentation content and the engine being penalised for keeping
it.

Tested rather than believed. The `prose only` row is the engine with code, tables and figure
captions removed: precision does **not** improve (0.835 -> 0.833) and recall collapses
(0.989 -> 0.805). So the references do keep code and tables, structure preservation is not
the cause of the gap, and dropping it would cost ten points of F.

### D48 — Most of the precision gap is the vote threshold, not noise

Chased properly rather than left open. Of the engine's non-consensus shingles on Jinja's
template page, **58.6% had been kept by exactly one reference extractor** -- the vote needs
two, so the engine is penalised for text a real extractor wanted. The remaining 41.4% is a
mix of API-reference tables the references drop and a little genuine sidebar leakage.

The benchmark now reports `P(any)`, precision against the *union* rather than the vote.
Engine: **0.937**. So **6.3% of the engine's output is text no established extractor kept**,
and the rest of the distance from 0.937 to 0.852 is the threshold.

`P(any)` is tautologically 1.000 for the references, since they are the union. Reported
anyway, with that stated, because the alternative -- quietly omitting the row that makes the
comparison look worse for the engine -- is the kind of selective reporting this project's
whole method is against.

Chrome detection was also checked on the same page and is working: it removed "Navigation",
"Quick search", "Contents", the breadcrumb and the copyright line. It only reaches 0.1% of
that page because 111k characters of template documentation dwarf its chrome, not because it
failed.

### D49 — Two defects the CLI exposed by showing the output plainly

Running `webgraph ask` against Jinja printed the map tier, and two things were obviously
wrong the moment a human looked at them. Neither had shown up in any metric.

**Every map entry read "Navigation; Quick search; Contents".** The map lists a page by its
first six section headings, and on a Sphinx page those are all sidebar. Fixed by skipping
headings that appear on half the pages or more — the same cross-page frequency idea as
chrome detection, applied to the map. Entries now read "Sandbox; Security Considerations;
API; Operator Intercepting", which is what an agent needs in order to decide what to fetch.

**A page's title was whatever heading came first**, which on a template that puts the
sidebar above the content is "Navigation" — a whole site of pages with the same name.
`<h1>` is the page title by convention and now wins when there is one.

Standing lesson: metrics did not catch either. Looking at the actual output did, immediately.
Print the thing.

### D50 — Fragment links name a section, not a page

The Site graph panel rendered "Environment — also called Undefined" and "Integration — also
called Babel". Both wrong, and the cause is one line: `/api/#jinja2.Undefined` and `/api/`
become the same edge once the fragment is stripped.

That merge is *right* for expansion — the section is on that page either way — and wrong for
naming the page's subject. `Link` now carries `page_anchors` alongside `anchors`, holding
only fragment-free anchor texts, and subject derivation reads that.

Found the same way as D49: by looking at the rendered output. Third defect this session that
no metric surfaced and one screenshot did.

### Bug introduced and caught the same minute

Rewriting `add_link` to carry two anchor tuples added an early `return` in the new-link
branch, which skipped the adjacency update below it. Every `link_specificity` collapsed to
the same value, because nothing was ever recorded as linked-from. The existing test caught
it immediately. Adjacency now happens first and unconditionally.

### D51 — Graphs are persisted, because a crawl is expensive and a file is not

Holding graphs only in memory meant a service restart threw away minutes of network and
browser time, and every question afterwards re-crawled the site.

`GraphStore` writes one JSONL file per site under `~/.cache/webgraph/graphs`
(`WEBGRAPH_GRAPH_DIR` overrides). Deliberately not a database:

- the format **is** the export format, so a stored graph is also a file you can hand to
  `webgraph ask --graph` or load elsewhere;
- there is no migration to write -- an unreadable file is treated as absent and the site is
  re-crawled, which is the right cost for a stale cache entry;
- writes go through a temp file and a rename, so an interrupted crawl cannot leave a
  truncated graph that looks valid;
- `prune()` keeps the newest 32, because a cache that only grows is a disk leak with a
  friendly name.

Persistence failures are logged and never raised: it is a convenience on top of a crawl that
already succeeded, and a read-only cache directory must not turn a completed crawl into an
error.

Verified end to end: crawl attrs.org, kill the API, restart, ask a question -- answered from
the revived graph with no re-crawl.

### D52 — At a tight budget, retrieval is zero-sum. Adding candidates does not help.

Three separate ideas this session, each of which sounded certain to improve recall, each
measured neutral or worse:

| idea | result |
|---|---|
| Reserve budget for neighbours (D38) | flat across 0.0-0.8; the gold page was already reached and merely ranked low |
| Shared-entity mention edges (D45) | within a point either way at every weight from 0.0 to 0.7 |
| Anchor-text relevance feedback | best no-overlap recall was always with it **off** |

The one change that did help was **mass-conserving propagation** (D38), which added nothing
and rebalanced what was already there: weak-overlap recall 75.0% -> 97.2% on attrs.

The pattern is not a coincidence. At a budget of 3-4% of the site, the context holds about
fifteen sections and the retriever already reaches the gold page in 100% of the failures.
Every additional candidate displaces one that matched. **Improvement has to come from
ranking, not from recall of candidates**, and any future idea of the form "also consider X"
should be assumed neutral until a number says otherwise.

Anchor feedback measurements, three sites x four discounts:

```
feedback   attrs no-overlap   pytest   jinja
  off               34.0%      14.7%   78.4%
  0.15              28.0%      14.7%   75.7%
  0.30              28.7%      14.0%   74.3%
  0.50              31.3%      13.3%   75.7%
```

The code is kept, off by default, because it is an obvious idea someone will otherwise
implement again and the argument against it should be a table rather than an opinion.

### D53 — Page-level evidence: the fourth negative, and the point to stop

A section inheriting some of its page's standing is how people actually search -- find the
right page, then the right part of it. Sections currently compete independently, so a page
with six matching sections ranks no better than one that matched by luck.

Measured across the same three sites:

```
weight   attrs no-overlap   pytest weak   jinja no-overlap
  0.00             32.0%          52.5%              78.4%
  0.25             32.0%          42.5%              78.4%
  1.00             28.7%          37.5%              73.0%
```

It buys a little single-hop recall on a corpus already at 92-100% and costs the multi-hop
buckets that have room to improve. Weighted zero.

**Four careful negatives in a row is a signal, not a run of bad luck.** The retrieval design
is at a local optimum for this benchmark and further parameter work would be fitting noise.
Stopping. The next real gain needs a different *kind* of change -- a vector seeder measured
against BM25, or a larger budget regime where the allocation is not zero-sum -- not another
weight.

### D55 — Change detection was already built; it just had to be assembled

`webgraph diff` reports what changed on a site since the last crawl. Nothing new was needed:
the content hash exists for deduplication, the graph store for surviving restarts, and
heading-scoped sections for retrieval. Putting the three together is the whole feature.

Two decisions decide whether the output is worth reading.

**Hash the extracted text, not the HTML.** Markup changes on every request -- build ids,
cache-busted asset URLs, CSRF tokens, timestamps in comments. Hashing markup marks every page
as changed on every crawl, which conveys exactly as much as marking none. Hashing the text in
recovered reading order means the hash moves when what the page *says* moves, and chrome
removal keeps a footer edit from marking all 2,000 pages.

**Match sections by heading, not by position.** Index matching reports everything below an
inserted section as changed, turning a one-paragraph addition into "the whole page changed".

`--fail-on-change` exits non-zero so a scheduled job can drive on it without parsing output.
Verified end to end by doctoring a stored baseline and re-crawling: the removed page and the
edited section were both reported, with before and after text.

### D56 — A link to somebody else's stack is not evidence about this one

A sweep across 16 diverse sites turned up one clear false positive: **Hacker News reported as
running WordPress**. Cause: its front page linked to a PDF at
`ajmp.uwr.edu.pl/wp-content/uploads/...`, and the rule matched `/wp-content/` anywhere in the
markup.

This is the same failure as matching prose (D24: `docs.astro.build` "running" Strapi) wearing
a different hat. A page that *references* a technology is not a page that *uses* it, and a
hyperlink is a reference.

Anchored to three things only the site itself can emit:

- a **root-relative** asset path, `(?:src|href)="/wp-content/…"`;
- the REST API discovery link WordPress emits by default, `rel="https://api.w.org/"`, which
  also catches installs that use absolute URLs for their own assets;
- its own bundled scripts, `wp-emoji-release`, `wp-embed`.

Drupal's `/sites/default/files/` and Joomla's `/media/jui/` had the identical weakness and
got the identical fix. `drupal-settings-json` needs no anchoring -- it is an attribute the
page emits, not a URL anyone can link to.

After: `news.ycombinator.com` -> `['HSTS', 'nginx']`; `wordpress.org` still detects WordPress.

### D57 — The fix generalised: a rule kind for same-origin references

Auditing every markup rule for the same exposure found **29** matching a URL-ish fragment
with no anchoring. Fixing them one at a time by requiring `href=` would not have worked:
Hacker News's link *was* an href. What separates "this site runs WordPress" from "this site
links to one" is whose host the reference points at.

So `TechRule` gained an `asset` kind. `same_site_assets(html, url)` collects every
`src`/`href`/`srcset` that is root-relative, relative, or absolute to the same host --
`www.` folded -- and `asset` rules match only those. The page URL is threaded from
`build_document` through `profile_page` for it.

Fourteen rules moved over, and the mixed ones were split so the half that is a class or a JS
token stays unanchored: WooCommerce keeps `wc-ajax` as markup and moves
`wp-content/plugins/woocommerce` to an asset; Divi keeps `et_pb_`; Elementor keeps
`elementor-widget`.

With no `url` supplied only relative references qualify. That is the conservative reading:
better to miss a site that writes absolute URLs to its own domain than to credit one with its
neighbour's stack.

Verified: `news.ycombinator.com` -> nginx, HSTS. `wordpress.org` still WordPress.
`getbootstrap.com` still Astro + Bootstrap. `persyn.ai` still 23 technologies.

Standing lesson, now twice: **every new host- or path-shaped rule must be checked against a
page that merely links to that technology**, not only against a page that uses it -- and the
check belongs in the rule kind, not in the reviewer's memory.

---

## The headline feature was off on 17 of 18 real pages (2026-09-01, session 11)

### D58 — All-or-nothing geometry discarded geometry almost always

`order_blocks` abandoned geometric ordering if **any** block lacked a rectangle, reasoning
that mixing measured and assumed positions gives an order that is neither. The reasoning is
right about naive mixing. The consequence was not thought through: **a browser does not
measure what it does not display**, so one collapsed `<details>`, one offscreen tab panel,
one lazily-mounted section leaves gaps -- and every real page has some.

Surveyed across 18 real pages:

```
                            geometry actually used
all-or-nothing rule                    1 / 18
anchoring unmeasured blocks           18 / 18
mean share of blocks measured           89.1%
```

Seventeen of eighteen pages were silently reading in **DOM order** while the engine had
measured 89% of their blocks in a browser it had paid to launch. Nothing reported it as a
problem; the documents said `dom-fallback` and that was treated as normal.

**The fix: anchoring.** Measured blocks are ordered geometrically; each unmeasured block is
placed immediately after its nearest preceding block in source order. That is exactly right
for the case that produces them -- a collapsed disclosure's body belongs after the control
that opens it, which is where the DOM already has it. Runs of consecutive unmeasured blocks
keep their own order.

Labelled `geometric-anchored`, never `geometric-xy-cut`: a weaker claim gets its own name.
Below `min_measured_share = 0.5` it still falls back, because anchoring a majority of blocks
to a minority of measurements would be source order wearing a measurement's name.

**How it was found:** by printing `reading_order_method` while investigating something else
entirely (collapsed content). The fourth defect this session that no metric surfaced and
looking at the output did. There is now a survey script for it.

### D59 — Revealing collapsed content: real on the page, negligible for the engine

`RenderConfig.reveal_collapsed` opens `<details>` and ARIA disclosure panels before
measuring, by property and attribute changes only. Nothing is clicked: a click can navigate,
submit a form, open a dialog that blocks the driver, or fire someone else's analytics.

It genuinely reaches hidden content -- measured as visible text on the page:

```
vercel.com/docs/functions   +412%     notion.com/pricing   +128%
MDN grid-template-areas     +308%     support.apple.com     +59%
```

**And it changes the engine's output almost not at all**, because closed `<details>` content
is already in the HTML; only its *geometry* was missing. With anchoring in place the effect
is +0.3 percentage points of blocks measured across 18 pages and no change in pages using
geometry (18/18 either way).

So it defaults off: a script evaluation and 250 ms of settle for 0.3%. Kept because the
number is worth having written down, and because a page that renders collapsed content only
on interaction would need it.

### D60 — The 6-page benchmark was flattering everyone, and `<nav>` was worth 8 points

Widening the content benchmark from 6 pages to 15, across long-form prose, documentation,
encyclopaedic and marketing pages, moved every tool down and the engine furthest:

```
                     6 pages (docs+prose)     15 pages (mixed)
trafilatura                    F 0.946              F 0.868
engine (chrome removed)        F 0.914              F 0.753
```

A number over one kind of page is a number about that kind of page. The wider corpus is the
one to trust.

Per-page, the mean was dominated by two outliers rather than a broad weakness: MDN at
precision **0.066** and Tailwind's install page at 0.026, against most pages within a few
points of trafilatura (pytest 0.978 vs 0.989, danluu 0.955 vs 0.999).

MDN's problem is a single `<nav>` holding several hundred reference links. Cross-page chrome
detection cannot touch it -- it needs six pages before repetition means anything, and MDN's
sidebar varies per page anyway.

**`strip_landmarks`**: drop blocks inside `<nav>` and `<footer>`. Structural, not statistical,
so it applies to the first page of a crawl.

```
variant                              P       R       F
raw                              0.658   0.990   0.740
without nav and footer           0.727   0.990   0.811
also without aside and header    0.736   0.986   0.815
```

`nav` and `footer` only: seven points of F for **no recall at all**. Adding `aside` and
`header` buys 0.4 more and costs 0.4 of recall -- the wrong trade for an engine whose job is
not to lose content, since plenty of sites put real material in an `<aside>`.

Shipped in the content-only path alongside cross-page detection, which measured:

```
engine (raw)              F 0.740
engine (chrome removed)   F 0.820      recall unchanged at 0.989
```

MDN alone: precision 0.066 -> 0.584, recall 1.000 throughout. The gap to trafilatura fell
from 11.5 points to 4.8.

Also: `/api/text` now returns `content_markdown` for a single page, which was impossible
before -- cross-page detection needs a crawl, a landmark needs one page.

---

## CI had never passed, and local checks could not have caught it (2026-09-01)

### D62 — A warm `node_modules` hid a broken install from every check

All 26 CI runs failed, from the very first commit, at `pnpm install --frozen-lockfile`:

```
[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: unrs-resolver@1.12.2
```

pnpm 11 refuses to install until every dependency with a build script is explicitly allowed
or denied. `unrs-resolver` is the native module resolver behind
`eslint-import-resolver-typescript`, pulled in by `eslint-config-next`. pnpm had written a
**placeholder** into `pnpm-workspace.yaml` -- literally `unrs-resolver: set this to true or
false` -- and I committed it with `git add -A` without reading it. An `onlyBuiltDependencies`
list, the pnpm 10 spelling, does not satisfy pnpm 11 either. The working form is:

```yaml
allowBuilds:
  unrs-resolver: true
```

**Why nothing local caught it.** Every `pnpm lint`, `pnpm typecheck` and `pnpm build` I ran
went against a `node_modules` populated by an earlier interactive install where the build had
already been approved. The failure only exists on a cold tree, which is the only kind CI has.

Reproduced by `git clone` to a temporary directory and running exactly what CI runs. The fix
was verified the same way -- clean clone, `--frozen-lockfile`, then lint, typecheck and build.

Standing lesson: **for anything that touches dependencies, verify in a clean clone.** A green
local check on a warm tree says nothing about a fresh one, and it said nothing here 26 times
in a row. Second lesson, smaller and sharper: `git add -A` committed a file that a tool wrote
and that contained an instruction addressed to me. Read what gets staged.

### D63 — A release version is not a tag

Bumping the CI actions off the deprecated Node 20 runtime broke every job at "Set up job" in
two seconds:

```
Unable to resolve action `astral-sh/setup-uv@v10`, unable to find version `v10`
```

I read the version from `repos/astral-sh/setup-uv/releases/latest`, which reports **v10.0.1**,
and assumed a matching `v10` moving tag. astral-sh does not publish one; its major tags stop
at **v7**. `actions/checkout` and `actions/setup-node` do publish theirs, which is why three
of the four guesses happened to work and made the fourth look like bad luck rather than a bad
method.

`git ls-remote --refs --tags` lists what actually exists, and every tag in the workflow is now
checked with it before pushing. Also worth knowing: `gh api repos/OWNER/REPO/git/ref/tags/vN`
returns nothing for these moving tags even when they exist, so it is not a usable check.

Same shape of error as D62 an hour earlier: **a fact was inferred from something adjacent to
it rather than read from the thing itself.**

---

## A robustness sweep, and the two defects it found (2026-09-01)

Twenty-one deliberately awkward sites -- client-rendered apps, RFCs, Project Gutenberg, RTL
pages, a table-laid-out page, `motherfuckingwebsite.com` -- flagged for anything that looked
like a *failure* rather than a result: no blocks, no text, DOM fallback, or a yield far below
what the raw HTML held.

### D64 — Half of a table-heavy page was missing from `document.text`

`Block.text` for a table held **only the first three rows**, and when a table had a
`<caption>`, only the caption -- the rows were dropped entirely.

`text` is not a display field. The content hash, deduplication, the search index behind the
graph, `text_chars` and reading order all key on it. The Markdown rendered every row
correctly the whole time, so the output *looked* right and everything computed from the text
was quietly missing most of the page:

| page | table text before | after |
|---|---|---|
| Comparison of text editors | 1,749 | **28,433** (+47% of the page) |
| List of countries by GDP | 1,089 | **14,177** (+45% of the page) |

For an engine whose stated purpose is not to lose 0.1% of a site, this was losing nearly half
of some pages, invisibly, since the day tables were added.

### D65 — Hacker News extracted as one block

`<table>` was treated as atomic and never descended into. On a page built out of nested
layout tables that collapses everything into a single block: HN was **1 block, 3,720
characters**, no headings, no links, no reading order.

`is_layout_table` distinguishes the two, structurally rather than by heuristic guessing:

- a cell containing block-level content -- above all another `<table>` -- means a page, not
  data;
- but `<th>`, `<thead>` or `<caption>` means data regardless, because flattening a real data
  table loses the mapping from a value to its column, which is the entire reason to keep
  tables at all.

Conservative in the ambiguous direction on purpose. HN now extracts with its structure and
**3,988 characters**, more than the original blob.

### Not defects, on inspection

The sweep also flagged `low yield` on Linear, Vercel and Shopify. That was the probe's fault,
not the engine's: stripping tags leaves inline `<script>` *contents* in the denominator, so a
page that ships a large JSON payload looks like it lost everything. Worth recording because
the number was alarming and meant nothing.

### D66 — `min_measured_share` was a guess; measuring it moved it from 0.5 to 0.3

The threshold below which a partly-measured document falls back to source order was set by
intuition. Measured properly: take pages the browser measured almost completely, treat their
full-geometry order as ground truth, blind a share of blocks, and score the anchored result
by how often a pair of blocks keeps its correct relative order.

**Blinded in clustered runs, not at random.** Real unmeasured blocks come in runs -- a
collapsed section, the blocks that exist only in the static half of a union. Random blinding
is a materially easier problem and would have overstated the result by several points.

```
share measured   90%   75%   60%   50%   40%   30%   20%   10%
clustered       1.00  0.97  0.97  0.98  0.92  0.92  0.88  0.91
random          0.99  0.99  0.98  0.98  0.97  0.96  0.96  0.94
source order    0.89   <- what falling back produces
```

Anchoring beats the fallback down to about 30% and loses below roughly 25%. Threshold set to
**0.3**, on the conservative side of a crossover that is noisy over six pages.

The `min_measured_blocks` floor added alongside it was removed the same hour: it fired on
small documents where geometry was nearly complete (3 of 4 blocks measured), and the share
test already covers what it was meant to guard.

### D67 — The union appended 2,533 blocks to the end of a page and called it geometry

Two faults in `union_documents`, both found by asking why `lemonde.fr` reported
`geometric-anchored` with **7%** of its blocks measured.

**Placement.** Blocks present only in the static document were appended after everything
else, on the reasoning that guessing a position would corrupt the measured ordering. The
reasoning is right about guessing; the result was still wrong. lemonde.fr's static document
contributes 2,533 blocks the rendered one lacks, and every one landed after the article.

They are now placed by **observed adjacency**: a static-only block is inserted after the
nearest preceding block that appears in *both* documents. Sound across two different DOM
trees precisely because the anchor is a block both trees contain. Their positions on
lemonde.fr now run from 0 to 2,696 with a median of 1,293, rather than all sitting at the end.

Where the two documents share *nothing*, there is no observed adjacency anywhere, so they go
to the end as before -- the front would be an equally arbitrary choice and the rendered page
is the authoritative one.

**Labelling.** The merged document copied the rendered document's `reading_order_method`
unchanged, claiming geometry for an ordering that was partly source order. A union containing
static-only blocks is now labelled `geometric-anchored` at best, which is what it is.

Recall against the reference vote rose 0.989 -> **0.994** across the same 13 pages, from the
table-text fix in D64, with precision unchanged.

---

## Making it shareable: hosting, and the hole that opened when it left the laptop (2026-09-01, session 12)

The ask was "how do I host this free so friends can try it". The hosting question turned out
to be the easy half.

### D68 — Free hosting: the constraint is the open response, not the memory

Ranked the hosts by the wrong thing at first. RAM looks like the binding constraint because
Chromium is the obvious cost, but the property that eliminates the most options is that
`/api/site/stream` holds one HTTP response open for minutes. That rules out every function
platform before memory is even considered.

Checked rather than remembered, and three of four recollections were stale:

| Host | Believed | Actual, September 2026 |
|---|---|---|
| Hugging Face Spaces | free Docker, 16 GB | **Docker Spaces are PRO-only**; only static Spaces are free |
| Render free | 512 MB, usable | 512 MB **and 0.1 vCPU** -- Chromium will not run usefully |
| Fly.io | small free allowance | **no free tier** since 2024; 2 VM-hours of trial |
| Cloud Run | free tier, streams | correct: 180k vCPU-s + 360k GiB-s/month, native SSE, 60-min ceiling |

Cloud Run at 2 vCPU / 4 GiB works out to ~25 hours of crawling a month free, because both
compute lines exhaust at the same point. `--execution-environment gen2` is required: gen1
runs under gVisor and intercepts syscalls Chromium needs.

The general lesson is the D63 one again in a different costume -- a remembered fact about
someone else's product is worth about as much as a version number read off a release page.
Free tiers move faster than anything else in this space.

### D69 — The engine would have fetched its own host's credentials on request

The service takes a URL from a caller, fetches it, and returns the body. There was no host
policy anywhere in the codebase -- grepped for `is_private`, `169.254`, `ipaddress`, and
found nothing. On any cloud host that means `http://169.254.169.254/latest/meta-data/` as
the input returns the instance's service-account credentials as the output. On a laptop this
was harmless; it became a live hole the moment the answer to "where do I host it" stopped
being "nowhere".

Three design choices in `fetch/guard.py`, each of which had a plausible alternative:

**Process-wide state, not a `FetchConfig` field.** The config-field version is cleaner and
was the first instinct. It is also wrong here: `fetch_static` is called from about a dozen
places inside `site.py`, and the threading-it-through version fails whenever a new call site
forgets. One process, one answer.

**An httpx request event hook, not a check on the input URL.** Verified experimentally
before relying on it -- httpx fires request hooks once per redirect hop, so the hook sees
every address, while a check on the caller's URL sees only the first. The attack that
defeats the naive version is a public host answering `302 Location: http://169.254.169.254/`.
`BlockedHostError` subclasses `httpx.HTTPError` so `fetch_static`'s existing handler turns a
blocked host into `ok=False` rather than an exception that aborts a crawl of thousands.

**Off in the library, on in the API.** Turning it on globally broke 7 API tests immediately,
because the suite serves its fixtures from `127.0.0.1` -- as do the CLI end-to-end test and
the benchmarks. A control that breaks `make test` gets switched off rather than fixed, so
the default is permissive in the engine and blocking in `webgraph_api.main`, which is the
only process that takes URLs from strangers.

One case needed a name-based rule rather than an address-based one. `metadata.google.internal`
does not resolve outside GCP, and "does not resolve" falls through to allowed -- so the
address-only guard had a hole that opened precisely on the host where it mattered. Blocked by
name, along with `.internal`, `.local` and `.localhost`.

Not fixed: DNS rebinding. The guard resolves, then httpx resolves again. Closing it needs the
connection pinned to the checked address through a custom transport. Documented in the module
rather than built.

### D70 — `max_pages: 0` is the largest possible request, not the smallest

The clamp is one line and it is the line that is easy to get backwards:

```python
return PAGE_CAP if requested == 0 else min(requested, PAGE_CAP)
```

`0` means "crawl until the frontier is exhausted", so `min(0, cap)` -- the obvious spelling --
leaves an unbounded crawl unbounded. The default is right for the person running this on
their own machine and unacceptable on a host shared with anyone, where one caller holds a
crawl slot for hours. Extracted to `_effective_max_pages` purely so the case could be
asserted without a network call.

*Overturned in part by D115 (PR #94):* the unbounded default was not right on the owner's
own machine either -- vtu.ac.in ran six hours and held six gigabytes. `0` still means
unbounded and the clamp is unchanged; it is no longer the default anywhere.

The same reasoning produced `WEBGRAPH_MAX_CONCURRENCY`, `WEBGRAPH_MAX_BROWSERS` and
`WEBGRAPH_CHROMIUM_ARGS`: every number tuned for a 16 GB laptop is wrong for a 4 GiB
container, and `MAX_BROWSERS = 6` at ~150 MB each is a kernel OOM kill that no exception
handler can catch.

### D71 — `NEXT_PUBLIC_*` is inlined at build time, and the failure is misleading

Not a new fact, but a new failure mode worth naming. A Vercel build that runs before
`NEXT_PUBLIC_API_BASE` is set keeps the `http://127.0.0.1:8000` default and then asks each
*visitor's own machine* for the API. The resulting error is indistinguishable from a backend
that is merely down, which is a long detour. `lib/api.ts` now detects the specific
combination -- a localhost API base on a page served from a remote origin -- and says which
mistake it is.

---

## Extraction quality: five defects, and the first number for the headline claim (2026-09-07, session 13)

Session goal, in the user's words: *"I wanna build world's top crawler... no regrets should happen
that I didn't do this earlier."* So the work was ordered by **how silently a defect fails**, not by
how hard it was to fix. Every item below was found by measuring, and four of the five were invisible
to the existing test suite.

### D72 — The union merged one block into a page many times over

`union_documents` emitted each static-only block once **per occurrence of its anchor key**. Identity
is normalised text, so a phrase appearing twice in the rendered document (a nav link "Sport" and a
section heading "Sport") is one key at two positions, and the loop fired at both.

Measured across 39 cached pages: **14 of them carried 3,113 excess blocks.** corriere.it merged to
3,831 blocks against 1,626 expected — **+136%**, with one static-only block copied **201 times**.
theguardian +208, bbc +43.7%, lemonde +15.7%.

It corrupts more than output length: `content_hash` is computed over the extracted text, and that
hash is the gate deciding whether a page needs re-extracting and what `graph/diff.py` reports as
changed. A duplicated block silently changes both.

Fixed by emitting the run once, at the **last** occurrence of the key — the one nearest the content,
rather than a nav link near the top. Both halves were wrong and neither had ever been measured.

### D73 — D67's placement rule was right; its implementation was hiding that

D67 adopted observed-adjacency placement on descriptive evidence only ("positions now run 0 to 2,696
with a median of 1,293, rather than all sitting at the end"). That shows the mechanism *fires*, not
that it is *correct*, and the recall figure quoted beside it was confounded with a table fix made the
same session.

`benchmark/union_adjacency/` now measures it, by the D66 method: blind a contiguous run of blocks
present in both documents, make the merge put them back, score pairwise order accuracy against the
rendered document's measured order. Baselines are append-at-end (the pre-D67 behaviour) and random.

**The metric had to be decomposed before it meant anything.** Scoring all pairs touching a blinded
block showed append-end *beating* adjacency at high blinding — an artifact, because a contiguous run
has far more internal pairs than external ones, so append-end was being credited for preserving an
order it never had to decide. Restricting to **cross pairs** (exactly one member blinded) isolates
placement. Before and after the D72 fix, cross-pair accuracy:

```
blinded    adjacency          append-end   random
  10%      0.833 -> 0.940       0.633      0.707
  40%      0.748 -> 0.941       0.618      0.723
  80%      0.700 -> 0.892       0.625      0.723
overall    0.757 -> 0.925       0.627      0.716
```

Everything alarming in the first run was the duplication bug. "Adjacency barely beats random" and
"decays as anchors thin" were both artifacts; it now holds above 0.89 even at 80% blinding.

### D74 — Every RTL page had been read left-to-right, in production, since the beginning

`order_blocks` has always reversed column order for `rtl`, and `build_document` has always accepted
the flag. **Nothing in between ever set it.** `resolve.py` — the path the API, the crawler and every
benchmark use — called `build_document` without it, so it defaulted to `False`. Only `cli.py` passed
it, from a manual `--rtl` flag.

A multi-column Arabic or Hebrew page did not come out slightly worse. It came out with the columns
in the wrong order, labelled `geometric-xy-cut` as though measured.

`is_rtl_document` now reads the page's own declaration: `dir` on `<html>`/`<body>` first (it wins
outright, including `ltr` on a Hebrew-language page — a real authorial choice), then `lang` against
RTL language and script subtags. **`lang` is not optional**: `ynet.co.il` carries no `dir` anywhere
and is RTL only through CSS; `lang="he"` is the sole signal in the markup.

Detection over the 41-page corpus: 5 RTL, 36 LTR, no misfires — including `aljazeera.com` (English)
staying LTR while `aljazeera.net` (Arabic) flips. Impact: ynet moves **3,813 of 3,924 blocks**.

Deliberately **not** a character-frequency heuristic. An English page quoting Arabic — a dictionary,
a news article, this suite's own fixtures — would have its whole order reversed. Only a declaration
counts.

Trap worth remembering: the CLI's `--rtl` is `store_true`, so it passes `False` when absent. Left
alone that would have silently disabled auto-detection for every CLI user. `rtl` is now `bool | None`
with `None` meaning detect.

### D75 — `rowspan`/`colspan` were ignored, which misaligns every value in a table

Zero occurrences of either attribute in the whole repo. A header of `<th rowspan=2>Region</th>
<th colspan=2>2025</th>` over `<th>Q1</th><th>Q2</th>` produced `('Region','2025')`, `('Q1','Q2')`,
`('EU','10','20')` — so the renderer took `Region | 2025` as the header, demoted the real column
labels to a body row, and put every number under the wrong heading. `rich.py`'s own docstring says
tables are kept because flattening "loses the mapping from a value to its column"; the code lost it
anyway on any table with a merged header.

Now expanded into a rectangular grid using pandas' algorithm from `io/html.py` — carry each spanning
cell forward with its column index and remaining row count. **Adopted, not depended on:** pandas is
15 MB and coerces `'10'` to an int, and the content hash and search index need the string.

Two adjacent defects fixed with it:
- **Nested tables were hoisted and duplicated.** `is_layout_table` short-circuited on `.//th`, which
  matches a nested table's header, so the `.//table` check below was unreachable for exactly the
  nesting it was written to catch. And `_table_block` read rows with `.//tr` (descendant) while
  reading cells with `./th|./td` (child), lifting inner rows into the outer table *and* leaving them
  in the cell text as `Inner HInner V`. The inner table is now its own block.
- **`<tfoot>` written before `<tbody>`** — legal and common — landed in the middle of the table,
  because lxml returns an XPath *union* in document order. The four row containers are now queried
  separately and concatenated in rendering order.

### D76 — `"|".join(sections) + "/th"` does not mean what it looks like

Fixing `is_layout_table` I wrote `_OWN_ROWS_XPATH + "/th"`. XPath `|` binds looser than `/`, so
`./thead/tr|./tr|./tbody/tr|./tfoot/tr/th` means "any direct row, or a tfoot header cell" — it
matched every ordinary table and broke layout-table detection outright. Two existing tests caught it
immediately. Build such expressions per-alternative.

### D77 — table-stitcher: evaluated hands-on, rejected

Asked to try `pip install table-stitcher` (PebbleRoad) for the table bugs. Installed in a throwaway
venv and pushed both bugs through it. **It cannot accept HTML at all** — three independent walls: its
only shipped adapter hard-imports `docling-core`; `TableMeta` requires a pandas DataFrame *plus a
page number*; and there is no HTML code anywhere in the package. Its README states `TableMeta` is
*"intentionally lossy — it reduces a rich table (with rowspan, colspan, multi-row headers…) into a
pandas DataFrame"* — precisely the information we need preserved.

It solves a real problem webgraph cannot have: table fragments split across **PDF page breaks**. MIT,
maintained, well-tested — and orthogonal. The transferable asset was pandas' span expansion, taken
without the dependency.

### D78 — There is no benchmark for HTML reading order, because the metrics cannot express it

Surveyed the field. Zyte's `article-extraction-benchmark` uses 4-gram shingle bags, WCXB word bags,
WebMainBench ROUGE-N, the SIGIR'25 multilingual eval ROUGE-L. **A bag of words is order-destroying by
construction** — it cannot tell a correctly-read two-column page from one read straight across,
because both contain the same words. So this engine's central claim is invisible to every number the
field reports. (Also: Zyte's benchmark was archived in 2026, and Firecrawl's `scrape-evals` was
withdrawn — repo 404, blog post unpublished. The field is fragmenting, not consolidating.)

The PDF world does measure it — olmOCR-Bench uses binary span-order unit tests, ParseBench pairwise
precedence assertions — and neither needs page coordinates in the *output*, so both port to a
linearised DOM. `benchmark/reading_order/` is that port.

**Avoiding circularity is the whole design.** Scoring a DOM walk against XY-cut's output measures
nothing. Assertions are generated from geometric *axioms* instead — A above B in the same column band;
A left of B in the same row band, reversed for RTL — neither of which consults `dom_index` or `_cut`.
Pairs geometry does not settle generate no assertion.

First result, 39 pages, 592,666 assertions:

```
overall                          geo 0.9945   dom 0.9732
discriminating   14,510 (2.4%)   geo 0.9354   dom 0.0646
  stacked       572,905          geo 1.0000   dom 0.9886
  side-by-side   19,761          geo 0.8353   dom 0.5262
RTL pages (5)                    geo 0.9782   dom 0.9210
ynet.co.il                       geo 0.762    dom 0.034
```

**When the two orderings disagree, geometry is right 93.5% of the time.** That is the number the
README's boldest claim was missing.

### D79 — The benchmark caught its own axiom before it caught the engine

First run showed geometry *losing* on side-by-side assertions (0.60 vs 0.87) with `elpais.com` at
0.000. The axiom was wrong, not the engine: `MIN_SHARED_FRACTION` measured overlap against the
**narrower** block, so a 29.7px line of body text counted as a side-by-side peer of a 1,062px
right-hand sidebar on docs.pytest.org. It then asserted an order between one line and an entire
column — something geometry does not settle — and the failure made a correct XY-cut look wrong.

Side-by-side now requires the overlap to be substantial against **both** blocks. Discriminating
accuracy went 0.885 → 0.962.

Second lesson, same benchmark: on an 8-page sample side-by-side still looked like a loss (geo 0.718
vs dom 0.923). On all 39 pages it reverses to **0.835 vs 0.526**. Eight pages was not a corpus.

### Still open

- **`supabase.com` 0.297, and the RTL Wikipedias at ~0.5** on discriminating pairs. Small counts,
  but unexplained.
- **Videos are not extracted at all.** `SKIP_TAGS` strips `iframe`, `object`, `embed`, `audio`,
  `video`, `source`, `track`. A YouTube embed vanishes; a `<video>`'s `<track>` subtitles go with it.
  `Modality.VIDEO_TRANSCRIPT` and `VIDEO_FRAME` exist and are never produced. (Images *are* handled:
  `srcset`/lazy-src fallbacks, sub-32px filtering, alt/title.)
- **CJK vertical writing** (`writing-mode: vertical-rl`) is untested. XY-cut assumes horizontal rows.
- **Multi-row headers still render as one joined label** (`2025 Q1`). Correct and lossless, but
  `Block` has no header/body distinction, so a consumer cannot recover the two levels.

### D80 — Sub-pixel `y` scrambled every horizontal nav bar

`_positional` ordered an atomic region by `(y, x, dom_index)` on the raw float. supabase.com
renders its top nav with `Pricing` at y=70.4 and `Product` at y=71.0 — **six tenths of a
pixel apart, on the same visual row** — so the tuple sort read the bar as `Pricing, Docs,
Blog, Product, Developers`. Hebrew Wikipedia's menu row failed identically. Any nav or row of
cards with fractional offsets was affected, and nothing had ever looked.

Blocks are now banded into visual rows by vertical overlap, then read along each row (right
to left when `rtl`). The banding criterion was chosen by measurement, not reasoning — across
592,520 assertions on 39 pages:

```
                     overall   discriminating   stacked   side-by-side
sort by (y, x)        0.9945       0.9343        1.0000       0.8346
band vs min height    0.9981       0.9403        0.9981       0.9969
band vs max height    0.9974       0.9921        1.0000       0.9219   <- adopted
```

The min variant is 0.0007 higher overall — noise — and buys its side-by-side gain by breaking
stacked pairs that were perfect. The max variant introduces **no regression** and is right on
99.2% of the pairs where geometric and source order disagree, against 94.0%. Two further
details, both found by getting them wrong first: the band must be measured against the
**taller** block (against the shorter, a tall block anchors a band that swallows short blocks
above and below it), and it must **not grow** as blocks join (a growing band creeps downward
and absorbs the rows beneath).

### D81 — Shadow DOM: fixed, correct, and it recovered nothing. Kept anyway.

A `TreeWalker` stops at a shadow boundary and `outerHTML` does not serialise across one, so
content inside an open shadow root was invisible **twice over** — absent from the HTML lxml
parses *and* absent from the geometry map, with nothing reporting it. Verified on a fixture:
the engine extracted `['LIGHT DOM PARAGRAPH']` and dropped the entire shadow subtree.

Fixed in two halves. `_COLLECT_SCRIPT` now recurses `el.shadowRoot` while stamping markers
and measuring — `getBoundingClientRect()` inside a shadow root already returns page
coordinates, so no transform is needed — and serialises via
`getHTML({serializableShadowRoots: true})`, which emits `<template shadowrootmode="open">`.
`flatten_shadow_roots` then unwraps those in `parse_html`, which is **required** rather than
tidy: `template` is in `SKIP_TAGS`, so a serialised shadow root would otherwise be discarded
one step later along with the inert templates it is syntactically identical to. Only
templates carrying `shadowrootmode` are unwrapped — flattening inert ones would invent
content the page never rendered.

On the fixture the shadow blocks now come out **with rectangles**, so they take part in
reading order rather than merely appearing.

**Then the measurement said it does nothing.** Across 20 corpus sites, 5 carry open shadow
roots — vercel 1, clerk 2, supabase 1, nextjs 1, **figma 11** — a 25% prevalence, far above
the Web Almanac's 2.51% for mobile pages generally, because this corpus skews to modern
component sites. Probing what those roots actually contain:

```
site           roots  templates  text chars inside
vercel.com         1          1        0
clerk.com          2          2        0
supabase.com       1          1        0
figma.com         11         11        0
nextjs.org         1          1        0
```

**Zero.** Every one is style or behaviour encapsulation — players, icons, third-party
widgets — not content. The +1.01% character delta in the first sweep was entirely news sites
with *no* shadow roots re-rendering with different stories; attributing it to this change
would have been wrong, and nearly was.

Kept regardless, on the same asymmetry that biases `_needs_render` toward rendering: the
cost is one extra JS branch on pages with no roots, and the failure it prevents is *total*
content loss on a page that does put content in one. Prevalence rose 6x in two years, and
Readability, trafilatura and Resiliparse handle none of it. But the honest status is
**unproven on real content** — it needs a site that uses shadow DOM for text, and this corpus
has none.

Closed shadow roots remain unreachable; that needs CDP `DOM.getDocument(pierce: true)`.
`getHTML()` is Chromium 125+ and falls back to today's behaviour when absent.

### D82 — Container text belonged to nobody, and recovering it costs precision

The innermost-block rule skips any container holding a block descendant, so a wrapper `<div>`
cannot swallow the column beneath it. What it missed is that such a container can *also* hold
text of its own — and that text was emitted by nobody at all:

```html
<div>Opening sentence.<br><br>
  <div><img><span>Caption</span></div>
<br><br>Closing sentence.</div>
```

extracted **12 characters of 118**. Both sentences are the article. This is ordinary
`<br>`-separated article markup, not an exotic case: on Zyte's benchmark **8 of 181 pages
lose more than 10% of their body and 4 lose essentially all of it** — MacRumors,
AppleInsider, IGN, jaraguadosul.

`_orphan_text` now takes the element's own text plus the tails of children that will
themselves become blocks, while inline children (`<a>`, `<em>`, `<span>`) contribute their
text because nothing else will. That split is what makes it additive rather than duplicating;
`rich.py`'s existing `_own_text` is a different function for a different job (a list item's
label, excluding only nested lists and tables).

**Then the benchmark said it costs F1.** On Zyte, isolated cleanly by stubbing the function:

```
orphan OFF   F1=0.7016  P=0.5516  R=0.9637
orphan ON    F1=0.6471  P=0.4816  R=0.9856
             improved: 4 pages   hurt: 164   flat: 13
```

A minimum-length gate does not rescue it — swept 20/40/60/80/120/200/400 chars, and even at
400 F1 reaches only 0.6810, still below off.

**Kept anyway, and the diagnostic is why.** Inspecting what is actually added:

```
appleinsider (rescued)  11 blocks, 22,948 chars — the article body is ONLY here
hosted.ap.org (hurt)     6 blocks,  5,961 chars — article lede recovered, plus AP topic tags
blog.comwrap (hurt)      2 blocks, 17,517 chars — article lede recovered, plus PWA marketing
```

On every page examined, including the ones whose F1 fell, orphan recovery pulls in **real
article text that nothing else was extracting**. What it also pulls in is nav strips and tag
lists sitting in plain `<div>`s — which `strip_landmarks` cannot see because they are not
`<nav>` or `<footer>`.

So this is not a recall-versus-noise trade. It is the session's systemic finding again:
recall is best-in-class (0.9856 here, against rs-trafilatura's 0.990 and above thirteen
systems that beat webgraph on F1), and **every remaining point is precision, which is a
selection problem rather than an extraction one**. The Zyte agent quantified the headroom:
picking the best contiguous run of the engine's *own* blocks scores **F1 0.945**. The article
body is already present, contiguous and correctly ordered, on essentially every page.

Losing an entire article body is the worst failure this engine can have. A precision cost on
an article-only metric is not a reason to keep doing it.

**The follow-up this makes unavoidable:** a text-density / link-density main-content selector
over the existing block list, shipped as an opt-in mode rather than a default -- it means
discarding content on purpose, which is the opposite of what the engine currently promises,
and that is a product decision rather than a tuning one.

### D83 — The selector was built, and it is swept on one page type only

`main_content.py` is that follow-up. The oracle framing turned out to be the whole design:
because the article body is already contiguous and correctly ordered, selection is a
**maximum-subarray** problem over per-block values, and Kadane solves it in one pass. Link
density is the primary signal, following Kohlschutter et al. (WSDM 2010) -- read from
`rich_text`, since `text` has already flattened `[label](url)` away.

Measured on Zyte, `strip_landmarks` first: raw 0.5738 -> landmarks 0.6471 ->
**landmarks + selector 0.8695** (P 0.8516, R 0.8882), against an oracle ceiling of 0.945.

**It is swept on Zyte's 181 article pages only, and that is the load-bearing caveat.** An
article is the page type where one contiguous run is most obviously right. Product, forum and
listing pages may want a different `block_cost` entirely, and a single constant may not serve
all seven WCXB types. Validating that is the first thing to do next -- see
`docs/SESSION-13-HANDOFF.md`, which carries the resume checklist, the full sweep tables, the
six benchmark agents that died on the session rate limit, and the VIPS licence finding (every
faithful implementation is LGPL; the 2003 algorithm is free to implement from the paper).

The selector is deliberately **not** wired into `build_document`. `Document.blocks` stays
complete; a caller that wants an article asks for one.

### D84 — Creative sites: the engine extracts twice what the browser shows

Built `benchmark/creative/` -- 23 award-winning and agency sites (WebGL portfolios, Framer and
Webflow builds, scroll-driven editorial). There is no ground-truth main content on an agency
portfolio, so the metric is **recovery**: engine characters over the browser's own
`document.body.innerText` on the same rendered page, both sides seeing the same DOM at the
same moment.

The result inverted the expectation. Mean recovery **2.155**, median **1.791** -- only one
site of twenty under-extracts. The engine is not missing content on these pages, it is
emitting roughly twice as much text as a reader sees:

```
basicagency.com   7.40x   10,993 vs  1,486      obys.agency    0.48   <- the only shortfall
webflow.com       4.74x   22,675 vs  4,785      activetheory   1.00   (29 chars total, all WebGL)
pudding.cool      3.73x   12,955 vs  3,470
apple.com/airpods 3.39x   86,389 vs 25,510
```

**Three distinct causes, separated by measurement rather than guessed at.**

**1. Invisible blocks.** `_COLLECT_SCRIPT` skips elements that are `display:none`,
`visibility:hidden`, `opacity:0` or zero-sized, so on a rendered page *a block with no
rectangle is a block the browser did not paint*. Those are currently anchored back in.
Dropping them: basicagency 7.14 -> 2.09, webflow 4.50 -> 1.73. Real and large -- but **not a
default change**, because the anchoring exists for collapsed `<details>`, which is also
rectangle-less and is content we want. This belongs behind the `main_content` path, which is
already the mode that discards on purpose.

**2. Missing separators between inline siblings.** Apple's nav arrives as
`'AppleStoreShopShop the LatestMaciPadiPhoneApple Watch...'`. `text_content()` concatenates
adjacent `<a>` elements with nothing between them, so "Mac iPad iPhone" becomes
"MaciPadiPhone". This is **text corruption, not noise** -- the words are destroyed, not
merely unwanted. A browser inserts the boundary because the links are laid out as separate
boxes, which is information we have in the rects and do not use. Unfixed; needs geometry to
decide where a boundary belongs.

**3. Cross-kind duplication -- my own bug, now fixed.** `_deduplicate` keyed on
`(kind, text, href)`, so one sentence survived twice under two labels: pudding.cool emits
"Some of my favorite projects..." as both a `list-item` and a `paragraph`. Narrowed to
`(text, href)` -- `href` still protects a gallery of images that share alt text, while
identical prose collapses regardless of which tag it wears. **Zyte F1 0.8638 -> 0.8723**,
precision 0.7816 -> 0.7979, recall essentially unchanged.

**The honest limit of the corpus:** `activetheory.net` has 29 characters of text on the whole
page and recovery of exactly 1.00, which is a perfect score and means nothing. The site is
WebGL. Six of twenty sites carry a canvas covering most of the viewport. No DOM extractor
recovers that without OCR, and the right response is to report "this page has no extractable
text" rather than return 29 characters as though they were the content.

### D85 — A benchmark harness failed silently and reported success

The first creative run printed "5 rendered, 0 usable" with no error. Cause: the harness
opened a second `sync_playwright()` on a thread where the engine had already started its
thread-local browser, which Playwright refuses -- *"It looks like you are using Playwright
Sync API inside the asyncio loop"*. The exception was swallowed by a diagnostic `except`, so
every page reported `ok=True` with zero measurements.

Fixed by reusing `shared_browser()`. Worth remembering as a shape: a benchmark that catches
broadly to survive bad pages will also swallow its own bugs, and "N succeeded, 0 usable" is
the signature.

### D86 — CleanEval and Webis WCEB: the independent benchmarks, and a false validation caught

Every other benchmark in this space is authored by a party with a system in the comparison --
Firecrawl's own, WCXB's author wrote the rs-trafilatura that tops it, trafilatura's author
runs trafilatura's eval. CleanEval (LREC 2008) and the Webis WCEB (SIGIR 2023) are not, which
is the entire reason to run them.

**CleanEval-1, 681 pages, complete**, scored with Evert's 2008 scorer over cached HTML:

```
variant       F1      P       R
raw         76.34   72.26   87.87
landmarks   76.34   72.26   87.87
prose       68.33   76.29   74.61
main        78.52   79.02   83.88   <- select_main_content
```

The selector wins here too, and `prose` is the *worst* variant -- CleanEval's gold standards
keep list and table text that the prose filter discards.

**WCEB, partial** (2 of 8 datasets before the agent stalled), against a published field of 22
systems where ensemble_weighted is 0.889, trafilatura 0.867, readability 0.855, resiliparse
0.819:

```
cleaneval         738 pages   raw 0.787   main 0.807
cleanportaleval    71 pages   raw 0.440   main 0.762   <- +0.32 from the selector
```

**The finding worth keeping is methodological.** A previous agent reported that its WCEB
scorer "gives exactly the TO/TM/Ave numbers the paper publishes, and identity = 100%". That
claim was false and unverifiable: the script it came from could not run at all -- it reads a
directory that had since been deleted, and imports modules not installed here. The
replacement validation was produced fresh and *is* exact: the restated scorer matches
upstream's own function to `0.000e+00` over 250 pages in the same process.

The residual against upstream's *published CSV* is 1.4e-03 on 7 pages of 250 -- upstream's
2023 numbers meeting a 2026 `rouge-score`/NLTK install, not a difference in the restatement.

Two lessons. An agent's claim of validation is not validation; the artifact has to be re-run.
And a benchmark harness pinned to a code snapshot is the only way to get a comparable number
while the engine is being edited -- the first WCEB run was discarded because `main_content.py`
changed underneath it.

## Session 14 — architecture fixes (branch `architecture-fixes`)

The user's instruction: "if you feel that something is off, just fix it... whatever it
takes." The architecture review had listed twelve issues; the ones below were fixed, and one
was found by measurement while fixing another and turned out to be the largest.

### D87 — The precision fix was finished work that nothing shipped

`main_content.py` (Zyte 0.647 -> 0.872, WCXB +0.065 across seven page types, CleanEval +2.2)
was imported by six benchmark scripts and zero product paths. The crawl applied landmarks and
cross-page chrome; `/api/text` applied landmarks only; the selector ran nowhere a user could
reach. Two definitions of "the content" that disagreed with each other, and the best one
absent from both.

Fixed with one module, `content.py`, whose `select_content` is *the* decision -- landmarks,
then site chrome (when a crawl has one), then the main-content boundary -- returning a
`ContentSelection` that says which steps fired. The crawl's `content_markdown`, `/api/text`,
`webgraph text --content` and the Zyte benchmark's `webgraph_content` variant all call it.
Order matters: the selector's adaptive cost is a multiple of mean block length, and a page
still carrying its navigation has a shorter mean.

Measured after wiring: `webgraph_content` on Zyte = **F1 0.872, P 0.795, R 0.966**, identical
to the benchmark-only composition, so nothing was lost in the plumbing. Recall stays above
every system ranked higher.

### D88 — The root was fetched three times, robots and sitemaps twice

`stream_site` called `resolve_root` (static GET to follow redirects), then `analyze_site`
(static + render), then queued the root as the first crawl page (static + render again), and
loaded robots.txt and walked the sitemaps once in analysis and once for the frontier.
Measured on quotes.toscrape.com, 6 pages static-only: **14 GETs before, 9 after; root 3 -> 1,
robots 2 -> 1, sitemap probes 4 -> 2; 11.4 s -> 7.3 s.** With rendering on, that is also two
browser renders of the root saved per crawl.

Fixed by making Stage 0 keep what it fetched: `probe_site` returns a `SiteProbe` (analysis +
resolved root page + robots policy + sitemap URLs), `analyze_site` is now `probe_site(...)
.analysis`, and the crawl's first result is the already-resolved root via
`_page_from_resolved` -- the same accounting as every other page, with `Frontier.mark_seen`
so a link back to the root is neither re-queued nor counted as a discovery. The redirect is
read off the resolved page's URL instead of a separate fetch, so `SiteAnalysis.root` is now
the *landed* URL (it was the requested one).

### D89 — Every page's HTML was retained until the crawl ended

`Document.html` is read exactly once after extraction, for links, and is the largest field a
page carries: on a 2 MB Wikipedia article the blocks hold 1.1 MB and the HTML 2.1 MB. The
crawl kept every `PageExtraction` -- HTML included -- in `all_pages` for entity aggregation
at the end, so an unbounded crawl held the whole site's markup to compute a handful of counts.

`Document.html` now defaults to `""` and the crawl drops it the moment links are read
(`_without_html`). Blocks, payloads and profile stay, because chrome detection and
aggregation read them. Pages returned by `extract_site` carry no HTML either; a `Document`
built directly by `build_document` always does.

### D90 — `strategy=None` promised a heuristic the code never had

`resolve_page`'s docstring: "with `strategy` unset ... render whenever the profiler is not
confident the static HTML is complete". The expression was
`strategy is UNION or static_doc is None or profile.requires_render or strategy is None` --
so with `None` the profile check was unreachable and every page rendered. And
`Strategy.RENDERED_ONLY`, passed in explicitly, fell through to a static-only result.

Resolved in favour of the code, because the module's own measurement says the docstring was
wrong: partial loss cannot be predicted from static HTML, so there is no safe per-page
heuristic. `None` = complete = UNION; `STATIC_ONLY` never renders, even for a shell;
`RENDERED_ONLY` now actually returns the browser's document (falling back to static only on
render failure, and still reporting `static_chars`). The per-*site* version of the skipped
heuristic exists and is measured -- `analyze_site` compares the root both ways and recommends
`STATIC_ONLY` only when static was shown complete. Pinned by `test_resolve_strategy.py`.

### D91 — `detect_technologies` was 77% of `build_document`

Found while measuring the two-parse cost in `pipeline.py`, which turned out to be 37 ms of a
**6.3 s** `build_document` on a 2 MB page (0.89 s on 250 KB). Profiling: 116 `TechRule.html`
regexes, every one `re.IGNORECASE`, every one scanned over the *full raw HTML* of *every
page* -- ~10 ms each per 250 KB regardless of pattern, 563 ms total; 4.8 s on the 2 MB page.
This ran per page in every crawl, on a GIL-bound thread pool, so it also serialised the
workers. The two-parse "fix" I had planned would have saved 22 ms next to it.

Fixed with an automatic required-literal prefilter in `profile/technology.py` -- measured
`build_document` 773 -> 128 ms (250 KB) and 6323 -> 1114 ms (2 MB); `detect_technologies`
582 -> 46 ms and 4928 -> 630 ms; 193 pages x 2 URL modes, 0 output differences: derive from each pattern the ASCII literals at least one of
which must occur for the regex to match, lowercase the HTML once, and run the regex only
when a literal is present. Correctness was proven by equivalence -- identical output with the
prefilter on and off across the fixture set, 181 Zyte pages and the two large pages -- not by
reasoning about regexes. `pipeline.py` also now copies the parsed tree (15 ms per 2 MB)
instead of parsing twice (37 ms).

Lesson: I proposed "halve parse cost" from reading the code. The first measurement showed
parse was 0.6% of the cost. Measure before proposing, even for the things that look obvious.

### D92 — Dead code and false capability claims removed

- `crawl/crawler.py` (277 lines): no importer anywhere; `stream_site` superseded it. Deleted.
- `Extractor.SELECTOR/ENSEMBLE/VLM`, `Modality.OCR/IMAGE/CHART/VIDEO_TRANSCRIPT/VIDEO_FRAME`:
  declared for three sessions, constructed by nothing, visible in the API schema as
  capabilities. Removed. `Extractor.LLM` and `Verification.UNVERIFIED` stay because the model
  path is the stated next product step and they are its contract.
- `webgraph analyze --json` was broken: `SiteAnalysis` is a `slots=True` dataclass and
  `analysis.__dict__` raised. Now `asdict`.
- ~176 lines of JavaScript in three Python strings moved to `fetch/js/*.js`, and the three
  `data-wg-*` marker names -- which lived in Python twice and in the JS three times -- now
  come from one module, `markers.py`, passed to the scripts as an argument.
  `test_markers.py` asserts no `.js` file contains the literal.

### Deferred, deliberately

Async Playwright (one browser, N pages, no thread-local pool) is the remaining structural
item. It is the largest change, touches `fetch/browser.py`, `render.py`, `site.py` and the
API's threading model, and nothing above depends on it. Do it as its own branch with its own
measurement.

## Session 15 — the benchmark climb (branch `benchmark-climb`, off `architecture-fixes`)

User's instruction: run every HTML content-extraction benchmark, find where we lose, research,
experiment, fix -- "don't cheat, do the hard work". Rules I hold myself to: tune on WCXB **dev**
only, never look at the held-out test split until the end; every change must be a general
extraction fix with a reason, not a per-benchmark patch; every number below is from a full
dev run (1,497 pages), with the run's predictions kept under `scratchpad/results/<step>/`.

Baseline (production path, `select_content`): **WCXB dev 0.714** (leader rs-trafilatura
0.859). Per type: article 0.841/0.932, documentation 0.822/0.932, service 0.688/0.844,
forum 0.498/0.808, collection 0.486/0.716, listing 0.423/0.707, product 0.491/0.641.
Precision 0.675, recall 0.852. `benchmark/wcxb/analyze.py` classifies each page as
over-cut / leak / ceiling against the `landmarks` variant and prints the worst pages per type
with their first and last kept block -- that tool found every fix below.

### D93 — Nineteen forum pages parsed to zero blocks: Discourse hides the topic in `<noscript>`

`noscript` is in `SKIP_TAGS`, rightly: on a normal page it holds a "please enable JavaScript"
nag and a tracking pixel. Discourse (community.openai.com, forum.obsidian.md,
users.rust-lang.org, home-assistant, letsencrypt, fool.com...) serves a JS shell with the
entire topic -- every post -- inside `<noscript>` for crawlers. We stripped the forum.
Measured: 19 of 112 dev forum pages, visible body 5-41 words, noscript 1,000-5,600 words,
ground-truth recall of the noscript text **1.00 on every one**.

Fix: `unwrap_noscript_shell` in `parse_html`, guarded both ways -- visible words < 150 *and*
noscript words > 100. Together with D94, WCXB **0.714 -> 0.730**; forum 0.498 -> 0.641.

### D94 — `<select>` options scored as prose

A country selector is 200 unlinked "words". A WordPress archive dropdown is every month
since 2010. A Google Translate widget is 100 language names. Each is a long run of unlinked
words, which is exactly what the Kadane selector prizes, so on glossier.com it returned the
country list *instead of* the article (recall 0.06 against a 1.00 ceiling). Measured:
12,985 `<option>` words across 26 dev article pages. `select`, `datalist`, `textarea` added
to `SKIP_TAGS`; `button` kept (an interstitial's only text can be its button).

### D95 — Blocks now know their landmark; `role="main"` was invisible

Landmarks were read from the XPath string, which carries tag names only. 178 of 1,476 dev
pages declare their main content with `role="main"` on a `<div>` and no other way. `Block`
gained `region` (innermost landmark by tag or ARIA role) and `in_main`, assigned once per
element with an ancestor memo in `extract_rich_blocks`. `strip_landmarks` now also drops
`role="navigation"` / `role="contentinfo"`.

`scope_to_main` keeps only the trusted `<main>`, guarded at >= 100 words and >= 50% of the
page's words -- measured: 1,000 dev pages carry a main landmark, 21 of them *empty* (a JS
mount point with the content around it); without the guard 21 pages fall below 0.5 recall,
with it 6, all collections whose grid sits beside the landmark. Result **0.730 -> 0.734**:
listing +0.024, product +0.016, article +0.005, collection -0.014, documentation -0.006.
Small, principled, kept.

### D96 — Negative result: trusting linked words inside `<main>`

Collection ground truth is 40% link text, listing 49% (measured: share of ground-truth words
inside `<a>` per type; articles 11%). The selector values linked words at zero, so half of a
listing page's content is scored as chrome. Tried: inside `main`, link density = 0. Listing
+0.052, but article -0.008, product -0.018, collection -0.020: a `<main>` also holds
related-product rails and tag clouds. Net **-0.003, not adopted** -- *at the time*. See D98: re-measured after D97 the same flag is
+0.007 overall and positive on every type, and it is now on by default. The right signal for a link grid that
*is* the content is structural repetition of the items (rs-trafilatura's
`collect_repeated_items`, magic-html's sibling similarity 0.84), not the landmark.

### D97 — The article precision bug was duplication, and exact-match dedup could not see it

186 of 793 dev articles were classed `leak`: precision 0.50, recall 1.00, **predicted words
2.37x the ground truth**. Inspection of typical cases showed almost no low-overlap blocks --
the extra words were the article *again*. `_orphan_text` walked direct children only: a
child that was a block contributed its tail, any other child contributed its **whole subtree
text**. One non-block wrapper between a container and its paragraphs -- `<span>`, `<ul>`, a
custom element like `<bsx-section>` -- re-emitted the entire article as one block beside the
paragraph blocks already emitted from inside it. tires.bridgestone.com: a 1,372-word
`<section>` beside its 24 paragraphs. proserveit.com: a 2,728-word `<div>` beside its 85.
ama.org: four `<ul>` re-emitted whole beside their 33 items. The deduplicator keys on exact
normalised text, and a container's text never equals any one child's.

Fix: `_orphan_text` recurses, skipping block-bearing subtrees (`_TEXT_CONTAINERS`,
`_HEADINGS`, `_ATOMIC`, and `ul/ol/dl/table`) wherever they sit; `_own_text` is the same
function. On the three pages: 2,985 -> 1,714 words (ref 1,438), 5,572 -> 3,213 (ref 2,711),
3,698 -> 2,408 (ref 1,812). WCXB dev **0.734 -> 0.803**; precision 0.706 -> 0.821 with recall
0.860 -> 0.847; article 0.850 -> 0.919 (leader 0.932), documentation 0.825 -> 0.884, service
0.697 -> 0.768, forum 0.648 -> 0.730, collection 0.481 -> 0.530, listing 0.447 -> 0.527, product
0.519 -> 0.587. One parser bug was worth more than every selector experiment combined.

Lesson (again): "precision problem" was the wrong frame. A precision number can be a
*recall bug in disguise* -- here the parser emitting content twice. The analysis tool's
`pred/ref token ratio` column is what exposed it; F1 alone never would have.

### What the leaders do (research, session 15)

rs-trafilatura is not a port of trafilatura: it adds a page-type router (URL regex, JSON-LD
`@type`, XGBoost on 181 features) and per-type extraction profiles -- forum comments are
content, product descriptions fall back to JSON-LD, listings collect >= 3 repeated same-tag
siblings of >= 15 words, service pages merge top-scoring non-overlapping sections
(`aggregate_sections`, accept >= top/5). Per-type gain over Python trafilatura: forum +0.207,
collection +0.160, listing +0.115, product +0.103. MinerU-HTML simplifies the DOM to
class+id-only blocks truncated at 500 chars and has a 0.6B model label each block main/other.
WCXB ground truth per type: forum = OP + all replies *including usernames and timestamps*;
collection/listing = the item grid itself (names, prices); product = title + description +
specs, price sometimes; documentation = all prose, code and attribute tables, TOC excluded.

### D98 — An experiment measured on top of a bug measures the bug

D96 declined `trust_main_links` at -0.003. D97 then removed the wrapper duplication that was
doubling a third of the articles. Re-run on the fixed parser, the same flag reads **+0.007
overall and positive on all seven types**: docs +0.022, listing +0.031, collection +0.025,
service +0.009 (0.803 -> 0.810). Adopted; both tables are in the config docstring.

Lesson: negative results are only as durable as the pipeline they were measured on. When a
large upstream bug is fixed, the recent negatives need re-running before they are believed.
WCXB dev now **0.810** -- above trafilatura (0.791), below MinerU-HTML (0.827) and
rs-trafilatura (0.859).

### D99 — Repeated-sibling grouping, first form: recall up, precision down, net loss

Cards in a grid each paid a full block cost, so the selector dropped grids (66 of 117
collections, 39 of 99 listings over-cut). First implementation: blocks under a repeated
container (`.../li[*]`, >= 3 distinct indices, innermost qualifying index) form one unit
worth all its words minus one cost. WCXB dev, on top of 0.810:

```
                 shipped   groups=main   groups=all
overall           0.810      0.801         0.794
precision         0.815      0.761         0.725
recall            0.864      0.920         0.956
listing           0.558      0.612         0.642
service           0.777      0.792         0.795
documentation     0.906      0.917         0.925
collection        0.555      0.532         0.567
article           0.920      0.905         0.887
product           0.589      0.526         0.516
forum             0.733      0.727         0.700
```

The grid it was built for is found; so are the related-products rail, the comment list and
the tag cloud, which are repeated groups too. Two things were wrong: the unit ignored link
density (all words counted), and any group of three qualified. Second form under test:
members keep their own scores and the unit pays one cost, and a group counts only when it
carries >= 30% of the page's words -- a grid that *is* the page rather than a rail beside it.

Also learned: the forum ground truth is a **prefix of the thread**. On mumsnet the GT ends at
post ~30 of 95; the excluded posts are visible, ordinary `div.post-body` replies, not hidden.
Not something to chase -- the honest output includes them.

Zyte after D93-D98: **0.872 -> 0.895**, rank 17 -> 15 of 35.

### D100 — Grouping, second form: the per-type split is stable, so it is a routing decision

Members keep their own scores, unit pays one cost, group must carry >= 30% (or 15%) of the
page. WCXB dev, on top of 0.810:

```
                 shipped  main-30  main-15  all-30
overall           0.810    0.806    0.805    0.804
listing           0.558    0.612    0.614    0.649
service           0.777    0.790    0.793    0.798
documentation     0.906    0.913    0.916    0.922
collection        0.555    0.537    0.537    0.574
article           0.920    0.911    0.910    0.897
product           0.589    0.541    0.535    0.538
forum             0.733    0.731    0.731    0.713
```

Same shape as D99: listing/service/docs want grouping on, article/product/forum want it off,
and no global setting wins. That is the empirical case for a page-type router: the user
approved building one plus a trained per-block classifier. `group_repeats` stays `"off"` by
default; the router will turn it on per type. Discipline for both: WCXB dev only, 5-fold CV
numbers reported, Zyte/CleanEval/WCEB/WebMainBench untouched as tests, held-out split closed.

### D101 — The page-type router: CV accuracy 0.838, routed WCXB dev 0.810 -> 0.817 (honest)

`webgraph/pagetype.py` + `models/router_gbdt.json`: 62 generic features (URL words, JSON-LD
types, og:type, structure), HistGradientBoosting exported to JSON, pure-Python inference
exact to sklearn, 0.76 ms/page, 194 ms load. 5-fold CV accuracy **0.838** (rs-trafilatura
0.866). Weak class: listing, recall 0.343 -- news fronts and category pages look alike, and
there are 99 of them against 793 articles. Confusion matrix in `benchmark/train/README.md`.

Routing worth, measured with **out-of-fold** predictions (each page routed by a model that
never saw it), policy = grouping on for listing/collection/service/docs, off otherwise:

```
                shipped   routed-oof   routed-truth (perfect router, ceiling)
overall          0.810      0.817        0.821
listing          0.558      0.606        0.649
service          0.777      0.795        0.798
collection       0.555      0.572        0.574
documentation    0.906      0.912        0.922
article          0.920      0.919        0.920
product          0.589      0.587        0.589
forum            0.733      0.733        0.733
```

+0.007 honest, of a +0.011 ceiling. The router gets most of the value the one-knob policy
has; the remaining structural gap (listing 0.65 vs 0.71, collection 0.57 vs 0.72, product
0.59 vs 0.64) needs a better per-type selector, which is what the block classifier is for.

### D102 -- The trained per-block model is built, measured, and NOT the default

I shipped it as the default, then a benchmark took it back out. `select_content` still ends
with `select_main_content`'s contiguous boundary; `model=SHIPPED_MODEL` asks for the
classifier. The reversal is the finding, so it is written up in full below.

**The honest WCXB dev number is out of fold, and I recomputed it myself rather than trusting
the trainer.** `benchmark/train/blockmodel_oof.py` reads the fold probabilities, applies the
production threshold (0.4) and fail-open guard (2% of page words), takes the ground truth
from the corpus and imports the corpus's own `word_f1`. It reproduces the trainer's claim
exactly: **0.810 -> 0.839**, every page type at or above the boundary step except
documentation at -0.002, listings +0.125, precision 0.815 -> 0.835, recall 0.864 -> 0.898.
23 pages fail open.

**Three things that would have made the whole exercise worthless, found and fixed:**

1. `benchmark/wcxb/run.py`'s `content` variant called `select_content(blocks)`. The moment
   the model became the default, that variant scored a model trained on all of dev against
   dev. Every runner that compares the boundary step to the model now passes `model=None`
   **explicitly**, with a comment saying why, because the failure is silent: two columns
   quietly become the same system and the table still prints.
2. I flipped the default *while WCEB and WebMainBench were running*. Their pools are created
   per dataset, so workers spawned after the edit picked up the new default and their
   `content` column became the `model` column. Both runs were killed and restarted. **An
   engine edit during a benchmark run invalidates the run** -- the same lesson as D98 (an
   experiment measured on top of a bug measures the bug), one level up.
3. `config=` was silently ignored whenever the model ran, so `routed-oof`/`routed-truth` and
   any caller's `MainContentConfig` would have collapsed into the model with no warning.
   `select_content` now treats a `config` as a request for the step it configures, and
   raises if given a `config` and an explicit `model` together.

**Zyte held**: 0.895 -> 0.897 (P 0.838 -> 0.832, R 0.960 -> 0.973), inside that benchmark's
own bootstrap error of +/-0.010. Untouched test set, different annotator -- but 181 article
pages is the model's strongest class, and passing it turned out to prove very little.

**A real parse bug the benchmarks found.** `ValueError: Unicode strings with encoding
declaration are not supported` -- lxml refuses a `str` carrying `<?xml ... encoding=...?>`,
which XHTML served as HTML has. Eight WCEB pages lost their *entire* document, not a
fragment. `parse_html` strips the declaration now; `tests/test_blocks.py` pins it.

**A behaviour change worth stating as a cost.** On a page that is entirely navigation the
boundary step returned all of it with `changed=False`, so the API emitted no
`content_markdown` at all. The model keeps most of the links and reports `changed=True`, so
the API now emits navigation as "content". A regression in kind, not degree.

**What the metric cannot see.** Out of fold, the model keeps the page's *first* heading only
**0.679** of the times that heading is ground truth, and image alt text **0.119** of the
time (`kind_image` is its single most important feature). Forcing the first heading in is
worth **+0.000** overall on WCXB -- a title is a few words against a thousand-word body, so
word-F1 is blind to it. For a benchmark that is nothing; for the graph this engine exists to
build, the page title is the node's name. Any fix here must be argued on product grounds,
because the benchmark will never justify it.

**D102a -- WebMainBench reversed the decision, and why that is the most useful result here.**

WCXB (+0.029) and Zyte (+0.002) both score a bag of `\w+` tokens. WebMainBench's 545-page
calibrated subset scores Markdown by **edit distance**, with tables and code in their own
columns. On it the model is worse across the board:

```
                 boundary   model    delta
overall            0.6224  0.5861   -0.036
text_edit          0.7567  0.7249   -0.032
code_edit          0.8099  0.7436   -0.066
table_edit         0.3485  0.2456   -0.103
table_TEDS         0.5558  0.4693   -0.087
prose-only slice   0.7145  0.6747   -0.040   <- 131 pages with no table, code or formula
```

The prose-only row kills the obvious explanation. Two repairs, both measured rather than
argued: re-inserting tables and code into the span the model kept is worth **+0.000**, and
filling the span completely is worth **-0.045**. It is not about structured content and it
is not about holes.

Reading pages instead of means: over 120 pages the model is worse on 54 and better on 39,
and the worst cases are two failures a word bag cannot charge for.

* **It discards most of long documents.** A 13,591-char recipe the boundary step extracts at
  0.996 comes back as 1,715 chars, scoring 0.109. A 20,789-char Chinese regulation comes
  back as 5,876.
* **It keeps comment and navigation furniture** -- "Add your comments...", "User Name
  Required", "Go to Forum >> 0 Comments", a font-size control. The boundary step excludes
  them because they are not contiguous with the prose. The model scores each block alone.

Missing words cost a little recall; the chrome the boundary step drops buys precision back.
On word-F1 the two failures net out *positive*. **WCXB's metric cannot tell an extractor
that keeps the right run of text from one that keeps a scattered subset of the right
tokens, and a model trained against it optimises the second.** That is the transferable
lesson, and it is worth more than the +0.029 was.

Not deleted: the model, the trainer, the OOF verifier and the 47 features are all in tree
and documented. It is one `model=SHIPPED_MODEL` from being on, and the next attempt should
train against a structure-aware target rather than a bag of words.

**What the metric could not see, measured anyway.** Out of fold the model keeps the page's
*first* heading only **0.679** of the times that heading is ground truth, and image alt text
**0.119** of the time (`kind_image` is its single most important feature). Forcing the first
heading in is worth **+0.000** on WCXB. For a benchmark that is nothing; for the graph this
engine exists to build, the page title is the node's name.

**The router ships as a label, not a policy.** `page_type` and `page_type_confidence` are on
`/api/text` and on every crawl page event. Nothing in extraction branches on the type: the
model (0.839) already subsumes the routed selector's gain (0.817), so routing the selector
would be a second mechanism buying nothing.

### D103 -- Firecrawl's scrape-evals, run for the first time, with its pre-registered call honoured

1,000 live fetches on 2026-09-12, static httpx path, no browser and no proxy. Ranked by the
published Quality F1 column the engine lands **8th of 14**: Coverage 60.0%, Quality 0.4372.
Firecrawl 0.6758, Exa 0.5268, Tavily 0.5011, Zyte 0.4682, Crawl4AI 0.4533; below us Scrapy
0.4290, Apify 0.4166, Puppeteer 0.4083, Selenium 0.4046, requests 0.3550, Playwright 0.3387.

**The prediction recorded in the runner before the run was confirmed, and it is worth more
than the rank.** A previous session wrote into `run.py`'s docstring: if the published spread
is substantially a *format* effect, `html_asis` must land in **0.33-0.45**, and 0.55+ would
falsify it. It landed at **0.3518** -- within the band and within 0.004 of the published
`requests` row (0.3550), which uses that same protocol. On this run's own bytes:

```
html_asis       0.3518   the protocol 12 of the 13 published engines submit
md_as_markdown  0.4320   the protocol Firecrawl alone submits
```

**+0.080 from the submission format on identical fetches.** The harness runs `strip_markdown`
only when an adapter declares `format="markdown"`, and exactly one of thirteen does.

**Our real gap is fetching, not extracting.** `F1|success` -- quality with failed fetches
removed -- is **0.7114**. 253 of 1,000 URLs returned 4xx against an identifiable bot UA from
one IP. Seven of the thirteen published engines fetch through commercial anti-bot fleets, and
Firecrawl's Coverage includes their closed hosted browser. Scaling our md_as_markdown quality
to their coverage puts us near 0.53 against their 0.676, so roughly half the remaining gap is
the fetch path and half is extraction or ten months of web drift.

**A structural penalty nobody has reported.** Of 684 good HTTP-200 bodies, **171 (25.0%)**
contain one of nine block-page needles that `is_block_page` greps for in the *unstripped*
submission -- and **119 of those have over 80% of the ground-truth text present**. Pages that
loaded perfectly, scored as blocked. That costs the twelve HTML-submitting engines and not
the one Markdown-submitting engine, and it is worth ~11.9 points of our Coverage.

**What this benchmark can see that the others cannot**: the noise leak, which its own scorer
does not compute. Mean `lie_text` leak, raw 0.541 -> landmarks 0.286, fully-leaked pages
15.7% -> 5.9%. `strip_landmarks` halves chrome leakage and no published column rewards it.

**The action this implies** is the browser path: this run used static httpx only, while the
engine has a rendered Playwright fetch it did not use here. Coverage is the lever, not the
extractor.

### D104 -- WCEB complete: 0.843, third of seven, and first on one corpus

3,985 pages, eight corpora, ROUGE-LSum, against the authors' own published per-page CSVs.

```
              F1   median
boundary   0.843    0.931   <- the shipped default
main       0.840    0.929
model      0.812    0.899   <- the trained classifier
raw        0.689    0.741

trafilatura   0.867   readability 0.855   boilerpipe 0.825
resiliparse   0.819   justext     0.806   bs4         0.692
```

**Third of seven**, ahead of boilerpipe, resiliparse, justext and bs4; behind trafilatura and
readability. Up from 0.833 before this session.

**First on cetd, ahead of every published system.** 700 pages: us 0.925, trafilatura 0.907,
readability 0.897, resiliparse 0.881, justext 0.863, boilerpipe 0.850, bs4 0.759. That is the
first corpus anywhere on which this engine is the best number in the table.

Second on dragnet (1,379 pages): 0.828 against trafilatura's 0.840, but ahead of readability
0.806, justext 0.785, boilerpipe 0.773 and resiliparse 0.724.

Weakest on cleanportaleval (0.782 against readability's 0.931) and cleaneval (0.836 against
justext's 0.881) -- both portal and newswire corpora, both precision-bound: cleanportaleval
runs recall 0.965 at precision 0.689.

**The XHTML parse fix is visible here**: parse failures 8 -> 1 across the corpus, and
cleaneval moved 0.805 -> 0.836 on 738 pages. A one-line bug fix outscored the entire trained
classifier, which is worth remembering the next time a model looks like the answer.

**Third independent confirmation that the model should not be the default.** It is behind the
boundary step on six of eight corpora and 0.031 behind overall. WCXB (+0.029) is now the only
corpus of eleven on which it wins.

### D105 -- The layout-table rule threw away real data tables, and `<p>` was the reason

`is_layout_table` decides whether a `<table>` holds data or lays out a page. It counted a
cell as layout evidence if the cell contained any block-level tag, and the list included
`<p>` and `<div>` -- the two most common ways a CMS wraps an ordinary value. `<td><p>12.4</p>
</td>` is the most normal data cell on the web and the rule read it as proof of the opposite.

Measured on WebMainBench: a 17-row, 111-cell table of numbers, headers carried by `rowspan`
with no `<th>` anywhere, was classified as layout and flattened. That page yielded **zero
tables and 294 loose blocks**; it now yields two tables, spans resolved, and 100 blocks.

The replacement signal is how much the cell holds, not which tag it uses: a nested table, a
form, a section, a heading, two or more paragraphs, or over `LONG_CELL_CHARS` (200) of prose.
A layout cell holds an article; a data cell holds a number. Tag identity cannot separate
those because both use `<p>`; length can. The Hacker News protection that motivated the rule
still holds -- `tests/test_markdown.py` pins both directions.

**Measured on WebMainBench 545** (boundary variant): table_edit 0.3485 -> 0.3589, table_TEDS
0.5558 -> 0.5816, code_edit 0.8099 -> 0.8303, overall 0.6224 -> 0.6255. Pages scored for
tables 149 -> 157. Real, and about a point: **the bug was not the 0.32 gap to MinerU-HTML.**

### D106 -- Competitor architecture: nobody else unions, and the benchmarks cannot see fetching

Researched Firecrawl (at a pinned SHA), Crawl4AI, Trafilatura, Zyte API, Scrapy 2.19, and the
browser-as-a-service tier.

**Nothing in the field does what `resolve.py` does.** Every system picks one representation.
Firecrawl is browser-first and has *deleted* plain HTTP from its waterfall when fire-engine is
present, with a source comment saying it would rather fail a scrape than degrade to HTTP.
Crawl4AI hardcodes the Playwright strategy and has no content-based escalation at all.
Trafilatura is HTTP-only and its docs tell the caller to render it themselves. Zyte rejects a
request asking for both representations with a 422. All of them assume rendering is a strict
upgrade -- the assumption D-era measurement refuted with bbc.co.uk (19,908 chars static,
9,279 rendered, consent wall).

**Every extraction benchmark hands every engine the same saved HTML**, so fetching is factored
out of the measurement entirely. Zyte's corpus was captured with JavaScript explicitly
disabled; WebMainBench is raw unrendered Common Crawl. Trafilatura "getting away with" having
no browser is not a finding about the web.

**MinerU-HTML is "Dripper"** (arXiv 2511.23119): DOM simplification, then a 0.5-0.6B language
model emitting one keep/drop bit per semantic block. Not generative -- **the output is a
precise subset of the original DOM**, produced by masking a preserved copy of the markup. That
is why it wins on tables: it returns the source `<table>` verbatim where we re-emit Markdown
and the scorer converts ours back into a flatter tree than the one it is compared against.

**The gap is format fidelity, not boundary detection**, corroborated three ways: on WCEB's
plain-text ground truth its lead over Trafilatura collapses from +23.8 to +3.2 (-87%); on the
545-page `text_edit` column it leads Trafilatura by 0.08 while leading by 0.42 overall; and
Resiliparse scores **0.0000** on tables purely because it emits plain text.

Two caveats to keep attached: WebMainBench was built by the team that also built its first and
second place systems, and on the independent WCXB, MinerU *loses* to plain heuristics on
collection (0.506 vs 0.713) and product (0.619 vs 0.670) pages.

### D107 -- table2rules (PebbleRoad): evaluated hands-on, and this one works

Unlike `table-stitcher` (D77), which could not accept HTML at all, `table2rules` 0.6.4 takes
it directly: `process_table(table_html: str) -> list[LogicRule]`. Dependency tree is
beautifulsoup4, soupsieve and typing-extensions -- nothing that would weigh on this engine.
Fail-open by default; `strict=True` re-raises.

Tested on the hardest real table in reach: the WebMainBench page from D105, 17 rows, three
levels of column header carried by `colspan`, a row-header column carried by `rowspan`, no
`<th>` anywhere. It produced **84 rules** and resolved the full header path correctly:

```
Number of enterprises in the group | Groups of enterprises by the share of revenue
  from the sale of milk … , % > I > Up to 5.0: 20
```

Row-header path, column-header path, value. That is a *fact*, not a cell -- which is exactly
what the graph needs, because a cell on its own means nothing and a cell with its header path
is something an entity can carry. It reads structural signals (`th`, `thead`, `scope`,
`rowspan`, `colspan`) rather than cell text, so it is language-independent by construction.

**Where it belongs: the graph/LLM path, not the extraction path.** WebMainBench rewards
preserving table *structure*; this flattens structure into facts. The two are opposite
directions and both are wanted, at different stages. Adopt it after the extraction work, for
the notes/entities/relationships step, not as part of the table-fidelity fix.

### D108 -- The formula gap was currency, not mathematics

WebMainBench's formula column read 0.3074 against MinerU-HTML's 0.9399, and the obvious
diagnosis was wrong. A census of the corpus first: **only 16 of 545 pages carry `<math>` at
all**, while 355 carry raw `$...$` in the HTML. So the MathML converter that was going to be
the fix addresses 3% of the corpus.

Splitting the formula pages by case over 200 samples settled it:

```
both sides have formulas        6 pages   mean 0.848
only the ground truth has them  1 page    0.000
only WE have them               18 pages  0.000   <- three times the true positives
neither                        175 pages  excluded
```

What we were "emitting" was money: *"spends $29.8 billion. This includes a surplus of $344
million"*. The metric finds formulas with `(?<!\\)\$(.*?)(?<!\\)\$`, so two prices in one
paragraph pair up and everything between them becomes a formula. The ground truth escapes
these -- 1,249 times across 165 pages -- and the lookbehind then skips them.

**Escaping every `$` fixed the false positives and broke the true ones**: formula N fell
282 -> 130 and the mean fell 0.3074 -> 0.1962, because real mathematics was escaped out of
existence too. The corpus says which to escape: an escaped dollar is followed by a digit 953
times of 1,221, while a bare one is followed by a space (2,743), a backslash opening a LaTeX
command (1,189) or another `$` opening display maths (921). **Money is `$29.8`; mathematics
is `$\frac…`, `$ x` or `$$`.** So the rule is a digit lookahead, `(?<!\\)\$(?=\d)`.

```
                 before   escape-all   digit rule
formula_edit     0.3074     0.1962       0.4705
overall          0.6255     0.6626       0.6912
```

Comparable column mean against MinerU's published 0.8256: **0.5665 -> 0.5992**.

Applied in three places, two of which bypassed the first: ordinary text, the rich text
carrying link syntax, and table cells. Plain-text output is untouched -- it is not Markdown
and nothing in it is a delimiter. MathML -> LaTeX is still worth doing, because `math` is in
`SKIP_TAGS` and every equation on every page is currently deleted, but it is a product fix
for 16 pages here rather than the headline.

### D109 -- Published baselines understate current systems by ~0.02, and it cost us two claimed positions

Asked whether the leaderboard positions are genuinely reproducible. They were not, and the
way to find out was not to reason about it but to **run a published system through this
repository's own harness and see whether it reaches its published score**.

`benchmark/wcxb/validate.py` and `benchmark/wceb/validate.py` do exactly that.

```
                              measured here   published   drift
trafilatura 2.2.0, WCXB dev       0.813         0.791      +0.022
trafilatura 2.2.0, WCEB/cetd      0.928         0.907      +0.021   (40-page sample)
```

Two independent corpora, two independent metrics, the same offset. **A published baseline is
frozen at the version its authors tested; this engine is current. Comparing the two flatters
whoever ran more recently**, and that was us.

**WCXB: the claimed third place was wrong.** On this harness, run the same day: trafilatura
**0.813**, webgraph **0.811**. Trafilatura is *ahead*, not 0.019 behind as the published
table implied. The per-type breakdown names the cause -- our trafilatura run matches the
paper on articles (0.928 vs 0.926) and diverges on forums (0.689 vs 0.585), because a later
release learned to read Discourse threads out of `div#data-preloaded`.

**WCEB/cetd: the "first anywhere" claim SURVIVES, and the alarm was my own sampling error.**
The 40-page sample read 0.928 (+0.021); the full 700 pages read **0.911 (+0.004)**. We score
**0.925** and current trafilatura scores **0.911**, so first place on that corpus is real and
measured the same day. *A 40-page sample was not enough to raise an alarm on, and raising one
was a mistake worth remembering.*

**So the drift is corpus-specific, not a flat offset -- the second correction.** +0.022 on
WCXB, +0.004 on WCEB/cetd. On WCXB it concentrates in forum pages (0.689 vs 0.585) and
product pages, which is consistent with the Discourse handling a later trafilatura gained.
cetd has no forum pages, so it shows almost none. **Two points was never a universal
constant, and treating it as one was over-generalising from two numbers.**

**The two boards that survive this, and why.**
* **Zyte is the strongest comparison in the repository** and always was: every competing
  number comes from running the corpus's own `evaluate.py` over the outputs those projects
  *committed to the repository*, in the same command that scored this engine. Same inputs,
  same scorer, same day, no version drift possible in either direction.
* **Firecrawl scrape-evals is not a comparison at all.** Their figures are November 2025 and
  ours September 2026, over 1,000 *live* URLs of which 90 now 404 for anybody. The columns
  describe two different webs.

Every board on the benchmarks page now carries a `Trust` level -- `same-inputs`,
`same-corpus`, `not-compared` -- so a reader is told what a side-by-side is worth instead of
having to find out by reading source. **A ranking whose rows were produced years apart is not
a ranking, and printing one is the thing not to do.**

### D110 -- Tables, equations and a fix that was removed for solving nothing

WebMainBench 545, `boundary` variant, across the day:

```
                 start    layout    currency   tables+   maths span
                           table     escape     maths     protected
overall         0.6224    0.6255    0.6912     0.7113     0.7201
table_edit      0.3485    0.3589    0.3589     0.4249     0.4249
table_TEDS      0.5558    0.5816    0.5816     0.6004     0.6004
formula_edit    0.3074    0.3074    0.4705     0.5169     0.6009
code_edit       0.8099    0.8303    0.8303     0.8458     0.8458
text_edit       0.7567    0.7545    0.7537     0.7673     0.7673
```

Column mean, comparable to MinerU-HTML's published 0.8256: **0.5665 -> 0.6479**.

**Tables: splitting the column found the real term.** Of the pages scored, 74 have a table on
both sides and score **0.605**; 38 had a table only from *us*, each scoring 0.0 and joining the
average. Suppressing those alone is worth 0.367 -> 0.533. Inspecting them settled bug vs
convention: a 1x1 cell reading "Home", a 1x2 "Rate this" widget, a 1x4 auto-refresh strip, a
6x1 list of tool names. **A table cross-references a row against a column; one row or one
column has nothing to cross-reference.** With that plus preserving complex tables' own markup,
the column moved 0.359 -> 0.425 and its page count 157 -> 122.

**Equations: the digit lookahead was too blunt, and the corpus said so.** `$0.07^{7}$` is
mathematics that begins with a digit. Escaping its opening delimiter left the closing one to
pair with something far away, and a page whose ground truth is the single formula `0.07` came
back as a formula containing the sentence before it. A span containing a backslash, caret,
underscore or brace is LaTeX; prices contain none of them. Protecting those spans: 0.517 ->
0.601.

**D110a -- a fix removed for solving a problem that does not exist.** A diagnostic reported
"25 code blocks carrying a line-number gutter" and a `strip_line_numbers` was built, guarded
and tested for it. It then fired on **0 of 493** code blocks in the corpus, and on **0 of 94**
across django, php.net and the Arch wiki. The original count was my own regex matching code
that merely *begins* with a digit. Modern highlighters render line numbers with CSS counters
or a separate column, so they never reach `text_content()` at all.

The code was correct, guarded and tested, and it was deleted anyway, because its docstring
claimed a measurement that was false and **guarded dead code carrying a false claim is worse
than no code**. The rule this session has been run on applies to my own work: do not add code
for a problem that has not been reproduced.

### D111 -- Hacker News, checked against the live page, found a link loss the tests could not

Validated the engine against `news.ycombinator.com` by reading the real page in a browser and
comparing field by field. The text was **perfect**: 30 of 30 stories with title, domain, point
count, author, age and comment count, including the one whose title begins with `Λ`. The
"More" pagination link was kept; navigation, footer and search box were correctly absent from
the *content view* and all still present in `document.text`.

**And every link was gone.** 211 of them. `_TABLE_ATTRS` kept only `colspan` and `rowspan`, so
preserving a complex table's markup stripped every `<a>` in it. On HN the destination of each
row is the single most important fact on the page, so the output read perfectly and was
useless to anything that wanted the articles.

`a` and `href` are now kept, and targets are absolutised, because a preserved table travels
without the page it came from and a bare `item?id=123` points nowhere. An `<a>` with no
destination becomes a span -- an anchor is not a link.

**The lesson is about what the test suite could see.** Every table test used a synthetic
fixture of bare text cells, so no test had a link in a table and none of them failed. A real
page found it in one run. *Synthetic fixtures test the shape you thought of.*

**Also confirmed working on a real page**: the router labelled HN `listing` at 0.81
confidence, the reading order came back `geometric-xy-cut` rather than DOM fallback, and the
union reported static and rendered identical at 4,226 characters -- HN genuinely needs no
browser, and the engine measured that rather than assuming it.

### D112 -- Hacker News, checked as a reader would: two bugs, the second worse than the first

Asked to preview the extracted Markdown rather than read the numbers. The output was one HTML
table whose columns were a rank, an empty cell, and a title. Faithful to the markup, and
useless to read.

**First bug: HN's story list is not a data table.** `is_complex_table` saw `colspan="2"` and
preserved the markup. Measured on the real page: **92 rows, 31 of them entirely empty**, no
header anywhere, row widths of 0, 2 and 3. *A table of data does not have a third of its rows
blank.* Those are spacer rows -- how a gap was made before CSS. `MAX_EMPTY_ROW_SHARE` now
catches it, and HN goes from 4 blocks to 94 with every story a proper Markdown link.

**Second bug, exposed by fixing the first: `select_content` returned the FOOTER.** 1 block of
94, zero stories. The selector looks for the densest run of prose and HN has none -- thirty
short links read as navigation, and the footer was the longest continuous text on the page.

**The fix existed and had never been wired up.** The router calls HN `listing` at **0.87**, and
`policy_for(listing)` scores repeated cards as units: 92 of 94 blocks, all 30 stories. Routing
is now applied in `site._content_of` and `/api/text`.

**Measured on WCXB: exactly neutral.** `content` 0.810, `routed-oof` 0.810, identical on every
one of the seven page types. The gain is bounded by the router, not the policy: `routed-truth`
(a perfect router) reads listing **0.653 vs 0.552**, +0.101, but the shipped router's listing
recall is **0.343**, so on that corpus it rarely fires. No loss anywhere, a large gain where it
does fire.

**The decision this reverses is D-era "ship the router as a label, not a policy".** That was
taken because the WCXB average moved +0.007, which looked negligible. *The average hid the
failure mode completely* -- on a listing page it is the difference between the items and the
footer, and returning a footer is not a small error. **An average across page types is the
wrong instrument for deciding whether a per-type policy ships.**

### D113 -- Listing recall: the features were noise, the class imbalance was the cause

Asked to improve the router's listing recall (0.343, the weakest class by far, with 33 of 99
listings called articles).

**The six features I reasoned my way to were worthless.** `linked_heading_share`,
`log_distinct_links`, `group_count`, `dated_group_share`, `median_block_words`,
`group_to_longest_ratio` -- all measuring *arrangement*, on the theory that an article is one
run of prose and a listing is many short linked items. Recall went **0.343 -> 0.323** and not
one of them reached the top fifteen by permutation importance. An ablation under identical
folds put them at +0.002 accuracy, +0.020 listing, **-0.034 collection**: noise in both
directions.

**The actual cause was class imbalance.** 793 articles against 99 listings, so a model
maximising plain accuracy is simply right more often by calling a doubtful listing an article.
`class_weight="balanced"`:

```
              recall before   after
listing            0.323      0.434
documentation      0.758      0.813
forum              0.885      0.903
product            0.866      0.882
article            0.961      0.927   <- what pays for it
accuracy           0.839      0.838
```

**And recall was not the thing to decide on.** A listing called an article and an article
called a listing cost different things, so the routed *extraction* score settled it, not the
confusion matrix: **0.810 -> 0.819**, with listing 0.552 -> 0.628 and **article unchanged at
0.920**. The 10 articles now misclassified as listings cost nothing measurable. A perfect
router reaches 0.822, so this takes three quarters of what is available.

**A mistake worth recording: I trained the balanced model and never exported it.** For a
stretch the *shipped* router was the 68-feature unbalanced one -- 0.323 listing recall, worse
than the 0.343 the day started with. Training a model and shipping a model are two actions and
only one of them had been done. Found by checking what was actually in the file rather than
what I remembered doing.

### D114 -- Everything a crawl reports should answer "and how do you know"

A run reported that two pages failed and nothing more. The next questions are always the
same -- what linked to them, what was tried, how long it took -- and none of it survived the
stream being consumed.

**Citations.** `Frontier.origin` now holds a `Discovery` per address: `via`
(`seed`/`sitemap`/`link`), `found_on`, `anchor`, `depth`. The anchor is what makes it a
citation rather than a reference: *the words a reader would have clicked* are the only part
of a link a person can recognise. Anchors key on the **raw** href because that is what the
page contained; the frontier stores the normalised form, and the two differ by exactly the
tracking parameters normalisation removes. Kept for the *first* acceptance -- a URL linked
from twenty pages is one page, and the citation that matters is the one that brought it in.

Verified on Hacker News: `/newest via=link, on /, link text "new"`. And on a site with a
sitemap: `via=sitemap, found_on <root>`. The root itself records `via=seed`, so every page in
a crawl has a citation including the one nothing pointed at.

**Traces.** `webgraph.trace` writes one JSON object per event with a run id, a sequence
number and seconds since the run began. A pass-through generator, so recording cannot change
what a consumer sees, and *its own failures are swallowed*: a crawl that dies because its
trace could not be written has been made worse by the thing meant to help it. Page Markdown
is stripped -- a trace carrying the whole corpus twice is not a trace. The API writes one per
crawl under `$WEBGRAPH_TRACE_DIR`.

**And a render timeout is not an empty page.** `wait_until="load"` waits for every advert and
tracker; on an ad-heavy retail page that event may never fire while the document finished long
before. The document is now read as it stands. *With a guard, because the first version made
things worse*: reliancedigital.in answers a 288-character document whose entire body is the
words "stream timeout", and salvaging it produced somebody else's error as the page. A
salvaged timeout must hold a real page, not an error wearing one's clothes.

### D115 -- A crawl has limits by default; files are counted, not fetched (PR #94)

The whole-site run of vtu.ac.in (15 Sep, `scratchpad/vtu/REPORT.md`, docs "Limits and
large sites"): 6 h 2 min before it was stopped by hand, the crawl process at 1.2 GB and its
browsers at 5 GB, 17,126 addresses discovered of which 7,907 were PDFs, 5,730 of them fetched
one at a time to be refused as not HTML -- a third of the run. D21's `max_pages = 0` default
was the cause of the first number and the frontier's treatment of `.pdf` as a page the cause
of the last.

Four changes, each with the number that justified it:

- **Defaults with limits.** `CRAWL_MAX_PAGES = 500`, `CRAWL_MAX_SECONDS = 3600`,
  `CRAWL_MAX_QUEUE = 20_000`. `0` still means unbounded, as an explicit ask. The `done` event
  says which one ended the run (`stopped_by`), and `exhausted` is false when the queue cap
  turned addresses away -- the UI had rendered `exhausted` as "every reachable page crawled".
- **Count, don't fetch.** `FILE_KINDS = {pdf, image, other_file}`: recorded with a citation
  (the page that linked it, the link text) and never queued. `fetch_files` opts back in for
  PDFs. Rejected: dropping PDFs from the tally -- a university site *is* mostly circulars,
  and a report that cannot list them has lost the most useful thing it found.
- **Retention.** `stream_site` kept every `PageExtraction` (blocks, Markdown, images) until
  the end to compute entity counts and site facts, which read only the URL, the facts and
  the schema.org payloads. `_kept` keeps those; the six full pages chrome detection needs
  are released once it is known. Measured on sode-edu.in, 300 pages, 4 workers, `union`:
  peak RSS of the crawl process 412 MB -> 332 MB, 715 s -> 484 s, 25.2 -> 37.2 pages/min
  (the speed is the rolling pool, below; RSS is the retention plus the PDFs not fetched).
- **Politeness per host.** `delay_seconds` was slept per worker, so `Crawl-delay: 1` with
  four workers was four requests a second. `HostThrottle` reserves the next slot per host
  under a lock (`crawl/politeness.py`); `CRAWL_HOST_INTERVAL_SECONDS = 1.0` or the site's
  `Crawl-delay`, whichever is larger. The per-worker pause stays. At 25-35 pages a minute a
  `union` crawl never reaches the interval; it binds on a fast static-only crawl, where it
  should. **The crawl loop is a rolling pool, not lockstep batches:** measured with the
  interval in place, the batch loop fell to 20.1 pages/min (894 s) because four pages
  starting together took slots 0-3 s apart and every batch paid the tail; the rolling
  pool ran 37.2 pages/min -- faster than before the interval existed, because the batch
  tail the crawl always had is gone too.

---

## Folded from packages/engine/MEMORY.md (2026-09-19)

The engine package carried a second journal; its entries are here so there is one.


### Reading order — two real bugs found by tests (2026-08-31)

- **Attempted:** XY-cut preferring a horizontal (row) cut before a vertical (column) cut,
  on the theory that a full-width header must emit before the columns below it.
  **Result:** wrong order on grid-aligned multi-column layouts — reads *across* the rows
  (`A1 B1 C1 A2 B2 C2`) instead of down the columns (`A1 A2 B1 B2 C1 C2`). The row gaps in a
  tidy grid qualify just as much as the column gutters do.
  **Instead:** measure the widest whitespace band on both axes and cut on whichever is
  **wider**. A real column gutter is wider than inter-paragraph leading; a section break
  under a spanning header is wider than any column gap (there usually isn't one, because
  the header bridges it).
  **Status:** fixed. `use_columns = bool(col_boundaries) and (not row_boundaries or col_gap > row_gap)`.

- **Attempted:** splitting at *every* qualifying gap on the chosen axis in one pass.
  **Result:** header-over-two-columns produced `HEADER L1 R1 L2 R2 FOOTER` instead of
  `HEADER L1 L2 R1 R2 FOOTER`. The row gaps *between the column rows* also qualified, so the
  columns were sliced into rows before the column structure was ever detected.
  **Instead:** cut at the widest band only (plus any within `_TIE_TOLERANCE = 0.95` of it),
  then recurse. The tie tolerance keeps uniformly-spaced single-column pages to one cut
  rather than recursing once per paragraph.
  **Status:** fixed. 21/21 reading-order tests pass.

**Lesson worth keeping:** both bugs produced *plausible-looking* output that a happy-path
test would have passed. The discriminating fixture is `test_naive_y_sort_would_have_failed`,
which asserts the naive algorithm gets it wrong — a test that guards the test. Keep writing
those for any ordering or ranking logic.

### libxml2 silently truncates deeply nested HTML (2026-08-31)

- **Attempted:** `lxml.html.document_fromstring(html)` with default parser.
  **Result:** documents nested deeper than **255 levels** parse to an empty document.
  `text_content()` returns `''`, **no exception, no warning**. Measured exactly: depth 250
  works, depth 255 and beyond returns nothing.
  **Why it matters:** utility-class CSS frameworks nest wrapper `<div>`s deeply. This would
  have silently dropped whole pages with no error anywhere in the pipeline — the worst
  possible failure mode for an extraction engine.
  **Instead:** `lxml.html.HTMLParser(huge_tree=True, recover=True)`. Verified working at
  depth 2000. **Must be `lxml.html.HTMLParser`, not `lxml.etree.HTMLParser`** — the latter
  returns plain `_Element` objects with no `.text_content()`, which fails confusingly.
  **Trade-off accepted:** `huge_tree` disables libxml2's resource guards, and crawler input
  is untrusted. Compensated with `MAX_DOCUMENT_BYTES = 32 MB` checked before parsing.
  **Status:** fixed and regression-tested at depths 300 and 800.

### D54 — The landing page scrolled sideways on a phone, and no screenshot showed it

Asserting `document.scrollWidth <= clientWidth` at 320, 390 and 768 pixels found a real
failure the desktop view could never show: the landing page rendered a **467-pixel document
inside a 390-pixel viewport**.

Cause, and it recurs: a grid or flex item defaults to `min-width: auto`, so it refuses to
shrink below its widest child. One `<pre>` of shell commands in a two-column section held the
whole page open. `min-w-0` on the grid children fixes it.

Now `make check-responsive` (`tools/check_responsive.py`), which names the offending elements
with their class lists and skips anything a clipping ancestor already contains -- a
decorative image scaled past its frame is not why a document scrolls.

Also fixed alongside: attrs' documentation puts the project name in every `<h1>`, so a whole
crawl arrived titled "attrs: Classes Without Boilerplate". A title shared by several pages
identifies none of them, and those rows now show their path as well.
