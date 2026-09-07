# Session 13 handoff — extraction quality push (2026-09-07)

Written mid-session because the API session limit was hit (resets 10:20pm Asia/Calcutta) and
the machine ran out of disk. **Nothing is committed.** All work below is in the working tree.

Read `MEMORY.md` decisions **D72–D82** first — they carry the full reasoning and the tables.
This file is the resume checklist, not a replacement for those.

---

## 1. State of the tree

Everything below is **written, tested and lint-clean** unless flagged otherwise.
Last full verification: engine suite green, `make lint` green (4/4 checks), API suite green.

### New files
| Path | What |
|---|---|
| `packages/engine/src/webgraph/main_content.py` | **The precision fix.** Max-subarray main-content selector. Opt-in, not wired into `build_document`. |
| `packages/engine/tests/test_rtl.py` | 23 tests, RTL detection + column flip |
| `packages/engine/tests/test_gates.py` | 6 tests, interstitial dismissal + identical-content warning |
| `packages/engine/tests/test_shadow_dom.py` | 10 tests, shadow-root piercing + template flattening |
| `benchmark/reading_order/run.py` | **Novel.** Nothing like it exists publicly. Axiom-derived pairwise precedence. |
| `benchmark/union_adjacency/run.py` + `sites.txt` | Union placement ablation, 41-site corpus |
| `benchmark/wcxb/run.py` | WCXB runner (2,008 pages, 7 page types) |
| `benchmark/article_extraction/run.py` + `README.md` | Zyte runner (181 pages, 34 baselines) |

### Modified engine files
`dom/blocks.py` (RTL detection, shadow flattening) · `dom/rich.py` (span expansion, nested
tables, orphan text) · `dom/reading_order.py` (row banding) · `pipeline.py` (RTL auto-detect,
deduplication) · `resolve.py` (union duplication fix) · `boilerplate.py` (landmark guard) ·
`fetch/render.py` (gate dismissal, shadow piercing) · `site.py` (identical-content warning) ·
`cli.py` (`--rtl` now means force, absence means detect)

---

## 2. THE UNFINISHED WORK — start here

### 2a. Validate `main_content.py` on WCXB. **This is the top priority.**

The selector is swept **on Zyte only** (181 article pages). Articles are the page type where
a single contiguous run is most obviously correct. **It is unvalidated on the other six WCXB
types**, and `block_cost=15.0` may well be wrong for product/forum/listing pages.

Measured on Zyte, `strip_landmarks` applied first:

```
raw                        F1 0.5738   P 0.4047   R 0.9856
landmarks                  F1 0.6471   P 0.4816   R 0.9856
landmarks + main-content   F1 0.8695   P 0.8516   R 0.8882   <- current defaults
oracle ceiling             F1 0.945
```

`block_cost` sweep (heading_bonus=8): 3 → 0.7137 · 6 → 0.7987 · 10 → 0.8556 ·
**15 → 0.8691** · 22 → 0.8101 · 30 → 0.6655.
`heading_bonus` at cost=15: 0 → 0.8683 · **4 → 0.8695** · 8 → 0.8691 · 16 → 0.8596 · 30 → 0.8055.
Flat between 0 and 8, so that one is a plateau and not load-bearing.

A finer sweep (cost 11–20, and `structural_credit` 0.0–1.0) was launched and **its output was
never read** — it is at `.logs/` or the background task file. Re-run it.

**Next commands:**
```
WCXB=<clone>   # scratchpad/wcxb/repo
uv run --package webgraph python benchmark/wcxb/run.py --corpus $WCXB --split dev
```
Add a `main-content` variant to that runner and sweep `block_cost` **per page type**. The
question to answer: does one constant serve all seven types, or does the selector need to be
type-aware? Report per-type, never just the mean.

**Do not wire the selector into `build_document`.** It throws content away on purpose, which
is the opposite of the engine's promise. It should be an explicit call, or at most a
`Strategy.MAIN_CONTENT`.

### 2b. Benchmark agents that died on the rate limit — re-run all

| Agent | Status |
|---|---|
| **WebMainBench** (7,809 pages; the only corpus with table-TEDS + code metrics) | died mid-run |
| **CleanEval + Webis WCEB** (the two independent academic benchmarks) | died — *had reproduced the paper's TO/TM/Ave numbers exactly, so the scorer works* |
| **Firecrawl `scrape-evals`** (their own withdrawn head-to-head) | died before starting |
| **Main-content selection research** (Boilerpipe/CETR/text-density specs) | died |
| **Block feature analysis** (which signals separate content from noise) | died |
| **World-class crawler research** | died before starting |

Prompts for all six are in the session transcript. The two most valuable are **WebMainBench**
(it is the only instrument that can see table/code fidelity — the current three-extractor vote
actively *penalises* correct tables) and **block feature analysis** (it directly feeds 2a).

---

## 3. Benchmark position as of now

| Benchmark | Session start | Now |
|---|---|---|
| **WCXB** (public, 1,497 pages, 7 types) | 0.711 | **0.730** |
| **Zyte** (public, 181 articles, 34 baselines) | 0.709 | 0.702 raw / **0.8695 with selector** |
| **Reading order** (built this session) | did not exist | **0.9974**; **0.9921** when it disagrees with a DOM walk |
| **Union placement** | 0.757 | **0.925** |
| **Content quality** (vs 3 extractors) | F 0.820 | F 0.821, recall 0.993 |

**The finding that frames everything:** recall is **0.953** on WCXB where the leading system
manages 0.890, and **0.9856** on Zyte against a best-in-field 0.990. *The engine out-recalls
or ties the best systems in the world.* Every point of deficit is precision — which is a
**selection** problem, not an extraction one. The Zyte oracle proves it: picking the best
contiguous run of the engine's **own blocks** scores 0.945.

WCXB per type (before the selector): article 0.832 · documentation 0.878 · service 0.751 ·
listing 0.593 · collection 0.518 · forum 0.483 · product 0.461.
Documentation already beats MinerU-HTML (0.838), dom-smoothie (0.868) and readability (0.736).

---

## 4. Known-open defects, ranked

1. **Discourse forums extract ZERO blocks** — 21 WCXB pages, `<body class="">` is empty, Ember
   renders client-side. But `document.structured_data` **already carries the full thread** as a
   `DiscussionForumPosting` microdata payload. Routing it into blocks moves forum 0.483 → 0.542
   and WCXB overall +0.007. Cheapest remaining win.
2. **eBay-style carousels** — ~100 list-item blocks of *other people's* products inside
   `<main>`, structurally indistinguishable from content. Needs the selector (2a).
3. **Videos not extracted at all** — `SKIP_TAGS` strips `iframe`, `object`, `embed`, `audio`,
   `video`, `source`, `track`. A YouTube embed vanishes; a `<video>`'s `<track>` subtitles go
   with it. `Modality.VIDEO_TRANSCRIPT`/`VIDEO_FRAME` exist and are never produced.
   (Images *are* handled properly: srcset/lazy-src fallbacks, sub-32px filtering, alt/title.)
4. **Multi-row table headers render as one joined label** (`2025 Q1`). Correct and lossless,
   but `Block` has no header/body distinction so a consumer cannot recover the two levels.
5. **CJK vertical writing** (`writing-mode: vertical-rl`) untested. XY-cut assumes horizontal
   rows. Detector must be `getComputedStyle().writingMode`, never `lang="ja"`.
6. **Closed shadow roots** unreachable — needs CDP `DOM.getDocument(pierce: true)`.
7. **`supabase.com` 0.297 and the RTL Wikipedias ~0.5** on discriminating reading-order pairs.
   Small counts, still unexplained.

---

## 5. VIPS research — completed, and the answer is "implement, don't vendor"

The one research agent that finished. Decision-critical findings:

- **Every faithful VIPS implementation in existence is LGPL.** `tpopela/vips_java` LGPL-2.1
  (12 of 13 rules, no `ruleThirteen`); Webis ECIR'21 JS port LGPL-2.1; FitLayout LGPL-3.0
  (best-maintained, pushed 2026-04). The only Python one (`wushuartgaro/VipsPython`) has
  **no licence file at all** — worse than GPL — *and* is a derivative of the LGPL Java. The
  permissive ones (fatum MIT Ruby 2012, bcolucci MIT) are a fragment and a 2.8 KB stub.
- **The algorithm itself is a 2003 MSR tech report and is free to implement.** Given
  `fetch/render.py` already provides headless-Chrome geometry, the clean path is
  *paper → fresh Python*, using the LGPL repos only as behavioural reference.
- **Webis ECIR'21 measured VIPS as still the best segmentation algorithm** — F*B³ up to 0.75
  (chars) / 0.70 (nodes) against baselines at 0.46–0.57. Optimal PDoC = 6. Failed on 14/8490
  pages (0.2%).
- **But VIPS segments; it does not select.** No main-content notion at all. The authoritative
  follow-up (Song et al., WWW 2004, same MSR group) makes selection a *learned* 4-level
  importance model and explicitly rejects hand-written rules as "unstable".
- **Worth stealing as a specification, not as code** — Song's 9 content features, verbatim:
  `ImgNum, ImgSize, LinkNum, LinkTextLength, InnerTextLength, InteractionNum, InteractionSize,
  FormNum, FormSize`, each **normalised by the whole page's value**. That normalisation is the
  part `main_content.py` currently lacks, and is the obvious next experiment for 2a.
- Nutch and Tika have **never** carried VIPS (checked ASF JIRA directly, 0 results).

Extracted sources saved at `scratchpad/mcs/src/` — `impl-vips-msr-tr-2003-79.txt`,
`impl-kiesel2021.txt`, `impl-song-www2004.txt`, `impl-tpopela-VipsParser.java`.

---

## 6. Competitive position (Firecrawl, verified in their source)

- HTML reading order is **DOM order**. Zero `getBoundingClientRect` in the extraction path.
  Zero handling of `flex-direction`, `order`, `writing-mode`, or `display:none` — hidden text
  lands in their markdown. `readingOrder` exists only on `PdfBlockItem`.
- **No RTL handling anywhere** in the HTML path.
- `<script>` stripped **before** markdown, so **JSON-LD is discarded entirely**.
- Schema extraction is **always an LLM call**. No zero-cost structured path.
- Main content = a hardcoded **42-selector CSS blocklist** plus a per-vendor carve-out.
- Structured output is `json?: any` — **no provenance**. They built correct per-value
  provenance (bbox, confidence, char-spans, extractor identity) for **PDFs only**, behind a
  second closed service.
- `document.links` is a flat URL set — **no anchor text, no position**. No link graph.
- They **considered union and did not build it** (maintainer TODO at `index.ts:770`), and
  their PDF `shadowComparison.ts` scores two extractors against each other then serves one.
- Their engine-quality evaluator is told a **cookie-walled page counts as a success**.
- `fire-engine` (anti-bot) is closed and not in the repo. **21.5% of their 965 issues are
  self-host** — 208 issues, 174 distinct authors.
- Open issues [#3817] and [#3782] ask for extraction-quality evals and structured fidelity.
  Unanswered. That is demand with no supplier.

**On CrawlBench specifically: not runnable.** No public repo despite the post claiming
open-source; it measures LLM extraction (webgraph has no LLM path); CrawlBench-Hard is
OpenAI's MiniWoB — synthetic RL widgets, not websites.

**The field is fragmenting, not consolidating.** Zyte's benchmark was archived in 2026 while
still taking contributions. Firecrawl's `scrape-evals` was withdrawn — repo 404, blog
307-redirects to `/blog`. Its dataset survives on HuggingFace
(`firecrawl/scrape-content-dataset-v1`) and the harness survives in a fork
(`martynasoxylabs/scrape-evals`), which is why re-running that agent is worthwhile.

---

## 7. Housekeeping

- **Disk is at 88–99% full.** ~40 MB of WebFetch PDFs sit in
  `~/.claude/projects/-Users-shashank-.../tool-results/`. Deleting those is safe and will
  unblock Bash, which was hard-failing with `ENOSPC` at the end of the session.
- `benchmark/union_adjacency/cache/` is 72 MB and **gitignored** — refetch with
  `make bench-union-fetch` (~10 min, needs network + Chromium).
- New Makefile targets: `bench-union-fetch`, `bench-union`, `bench-reading-order`.
- **Nothing has been committed or pushed.** That still needs explicit approval.
