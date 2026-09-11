# Session 14 — architecture fixes: what changed, why, and what it costs

Branch: `architecture-fixes`, off `main` at `c17d3d4`. Every number below was measured on
this tree; commands are given so they can be re-run.

The architecture review of the extraction path found twelve issues. Seven are fixed here.
One of them — the fingerprint hot loop — was not on the list at all; it was found by
measuring the cost of an item that *was*, and it dwarfs everything else.

---

## 1. The precision fix is now shipped (`content.py`)

**What changed.** A new module, `webgraph/content.py`, with one function, `select_content`.
It is the single decision about what a page's *content* is, as opposed to its *text*:
landmarks (`<nav>`, `<footer>`) → cross-page site chrome (when a crawl has one) → the
main-content boundary from `main_content.py`. It returns a `ContentSelection` naming which
steps removed something. Four callers now use it:

| caller | before | after |
|---|---|---|
| crawl page event `content_markdown` | landmarks + chrome | landmarks + chrome + main content |
| `POST /api/text` `content_markdown` | landmarks only | landmarks + main content |
| `extract_site` (batch) | field never populated | populated |
| `webgraph text --content` (new flag) | did not exist | landmarks + main content |
| Zyte benchmark `webgraph_content` variant | did not exist | the production path, scored |

New fields: page events and `/api/text` carry `content_methods` (which steps fired) and
`content_blocks`; page events also carry `blocks` (the complete count). `SiteConfig.main_content`
(default on) switches the last step off for crawls of link hubs.

**Why.** `main_content.py` — the work that lifted Zyte from 0.647 to 0.87 — was imported by
six benchmark scripts and zero product paths. Two product paths had two different
definitions of "content" that disagreed with each other, and neither was the best one.

**Impact, measured.** Zyte article benchmark, 181 pages, run through the production
function:

```
webgraph_content   F1 0.872 ± 0.011   P 0.795 ± 0.018   R 0.966 ± 0.007   rank 17 of 35
webgraph_landmarks F1 0.654           P 0.490           R 0.985           (what /api/text shipped before)
```

Identical to the benchmark-only composition measured last session (0.8725), so nothing was
lost in the plumbing. Recall stays above every system ranked higher.

**Pros.** The measured gain reaches users. One definition of content, tested in one place
(`test_content.py`). The API tells the caller *how* the content was chosen. `markdown` is
untouched — the lose-nothing output is still there, and `content_markdown` is an addition.

**Cons.** `content_markdown` now discards more than before by design: comment threads,
related-article rails, bylines. A consumer that relied on it being "everything minus nav"
gets less. The selector fails open (returns the page when it would return a fragment), but
on pages whose real content is a link list it will sometimes cut; that is what
`main_content=False` is for. Zyte remains 17th — precision 0.795 is the remaining gap and it
is a selection problem, not an extraction one.

---

## 2. The root is fetched once (`SiteProbe`)

**What changed.** `analyze.py` gained `probe_site`, returning a `SiteProbe`: the analysis
verdict *plus* the resolved root page, the robots policy and the sitemap URLs. `analyze_site`
is now `probe_site(...).analysis`. `stream_site` and `extract_site` seed the crawl with the
already-resolved root (`_page_from_resolved`), mark it visited with the new
`Frontier.mark_seen`, and reuse the robots/sitemap results. `resolve_root`'s separate fetch is
gone from the crawl path; the redirect is read off the resolved page's URL.

**Why.** The crawl fetched the root three times (redirect check, analysis both ways, first
crawl page) and read robots.txt and every sitemap twice. The page the analysis measured *is*
the root page; discarding it carried no information.

**Impact, measured.** `quotes.toscrape.com`, 6 pages, static-only, rendering disabled so
both trees are comparable (`scratchpad/perf/crawl_cost.py`):

```
                     before (main)   after
total HTTP GETs          14            9
root fetched              3×           1×
robots.txt                2×           1×
sitemap probes            4×           2×
wall time              11.4 s        7.3 s
```

With rendering on, two browser renders of the root are also saved per crawl.

**Pros.** Every crawl starts faster and hits the target site less. Unit-tested without a
network (`test_site_pipeline.py`): the fake resolver counts, and the root is resolved zero
times after analysis.

**Cons.** `SiteAnalysis.root` is now the *landed* URL after redirects, not the requested one;
the `analysis` event's `root` changes for redirecting sites (it is more truthful, but it is a
change). The root page's `strategy` in the crawl is `union` even when the crawl strategy is
`static-only`, because analysis always resolves it both ways — strictly more complete, but
visible in the page event. `build_inventory` grew an optional `probe` parameter.

---

## 3. Page HTML is dropped after link extraction

**What changed.** `Document.html` now defaults to `""` (documented). The crawl reads it once
for links and drops it (`_without_html`) before the page is retained. `extract_site` pages
carry no HTML either. A `Document` built directly by `build_document` always has it.

**Why.** Every `PageExtraction` — HTML included — was kept in `all_pages` until the crawl
ended, to compute entity counts. On a 2 MB Wikipedia article the blocks hold 1.1 MB and the
HTML 2.1 MB; an unbounded crawl held the whole site's markup for a handful of numbers.

**Impact.** Retained memory per page drops by the HTML size (typically 50–70% of a page's
footprint; 2.1 of 3.2 MB on the Wikipedia page). Not visible on the 6-page toy crawl above
(3.1 → 2.9 MB peak) because those pages are tiny; it matters at the "1000 books" scale the
product is aimed at.

**Pros.** Unbounded crawls no longer grow with page size, only with block count.

**Cons.** Anything that later wants a crawled page's raw HTML has to re-fetch it. Nothing in
the repo did; if the graph builder ever wants it, it must take it before `_fetched` drops it.
`Document.html` being optional is a small weakening of the type — a `Document` with empty
HTML is now valid.

---

## 4. `resolve_page` strategies mean what they say

**What changed.** `strategy=None` is documented and implemented as UNION when a browser is
available. `STATIC_ONLY` never renders. `RENDERED_ONLY`, which previously fell through to a
static-only result when passed explicitly, now returns the browser's document and reports
`static_chars` for what it declined. Pinned by `test_resolve_strategy.py` against a fake
browser.

**Why.** The docstring promised "render whenever the profiler is not confident"; the
expression had `or strategy is None` beside the profile check, so the check was unreachable
and every page rendered. Two behaviours were possible and neither was tested.

**Impact.** No behaviour change on any production path — all of them pass an explicit
strategy — but a library caller passing `RENDERED_ONLY` now gets what they asked for.

**Pros.** The code, the docstring and the module's own measurement (partial loss cannot be
predicted from static HTML) now agree. The per-*site* heuristic that *is* measured lives in
`analyze_site` and is named as such.

**Cons.** Anyone who read the old docstring and expected a cheap adaptive default gets a
render per page. The cheap path is `STATIC_ONLY`, or letting site analysis choose.

---

## 5. The fingerprint hot loop (found, not planned)

**What changed.** `profile/technology.py` derives, for each `TechRule` regex, the set of
ASCII literals at least one of which must appear for the regex to match, and skips the regex
when none is present in the (once-lowercased) HTML. `pipeline.py` copies the parsed tree
(15 ms per 2 MB) instead of parsing twice (37 ms).

**Why.** Item 6 of the review was "single-tree parse in pipeline.py — halve parse cost".
Measuring it first: `build_document` took **6.3 s** on a 2 MB page and **0.89 s** on 250 KB,
and parsing was 37 ms of that. 77% was `detect_technologies`: 116 case-insensitive regexes,
each scanned over the full raw HTML of every page — ~10 ms each per 250 KB regardless of
pattern, 4.8 s total on the 2 MB page. Per page, in every crawl, on a GIL-bound thread pool,
so it also serialised the workers.

**Impact, measured.**

```
                          build_document          detect_technologies
mdn.html   (240 KB)      773 ms ->   128 ms       582 ms ->  46 ms
wiki.html  (2 MB)       6323 ms ->  1114 ms      4928 ms -> 630 ms
```

Equivalence: 193 pages (MDN, Wikipedia, 181 Zyte pages, 8 fixtures, 2 synthetic) x 2 URL
modes, comparing the full `Technology` list including evidence strings, `same_site_assets`
and the framework hits: **0 differences** (`scratchpad/perf/equivalence_prefilter.py`,
re-run by me after the agent that wrote it reported the same). The remaining time on the
2 MB page is ~200 substring tests plus 12 regexes that legitimately run because their
required literal is an English word in the prose (`react`, `ember`, `moment`).

**Pros.** Every page of every crawl gets this. Correctness is proven by equivalence, not
argument: identical detector output with the prefilter on and off across the fixtures, all
181 Zyte pages and the two large pages.

**Cons.** The literal extractor walks Python's private `re._parser` tree; a future Python
could change it (the code falls back to "no prefilter, run the regex" if parsing fails, so
the failure mode is slow, not wrong). Rules whose pattern has no ≥3-char required literal are
still scanned in full; the test names them.

---

## 6. Dead code and false capability claims

- `crawl/crawler.py` (277 lines): no importer; `stream_site` superseded it. **Deleted.**
- `Extractor.SELECTOR/ENSEMBLE/VLM` and `Modality.OCR/IMAGE/CHART/VIDEO_TRANSCRIPT/VIDEO_FRAME`:
  declared for three sessions, constructed by nothing, visible in the API schema. **Removed.**
  `Extractor.LLM` and `Verification.UNVERIFIED` stay: the model path is the stated next step
  and they are its contract. *Con:* any external consumer that switched on those strings
  must drop the branches (none exist in this repo).
- `webgraph analyze --json` crashed (`SiteAnalysis` is a slots dataclass; `.__dict__` raised).
  **Fixed** with `asdict`.

---

## 7. Renderer JavaScript is JavaScript (`fetch/js/`, `markers.py`)

**What changed.** The three browser programs (~176 lines) moved from Python strings to
`fetch/js/{reveal,gate_probe,collect}.js`, loaded once per process via
`importlib.resources`. The `data-wg-id` / `data-wg-brk` / `data-wg-gate` marker names — which
existed in Python twice and in the JS three times — now come from one module, `markers.py`,
and are passed to the scripts as an argument. `test_markers.py` asserts that no `.js` file
contains the literal. Verified end to end by the existing Playwright tests (gates, shadow DOM,
render integration) and the wheel build includes the files.

**Pros.** Syntax highlighting, linting and diffing on real JS; one contract for the three
attribute names. **Cons.** A packaging dependency on non-Python files being in the wheel
(verified, and tested by loading them).

---

## Not done, deliberately

**Async Playwright** — one browser, N pages, no thread-local pool. The largest change,
touching `fetch/browser.py`, `render.py`, `site.py` and the API's threading. Nothing above
depends on it. Its own branch, its own measurement.

**`stream_site` split** — partially: `_Fetched`, `_fetched`, `_content_of`, `_chrome_for`,
`_without_html`, `_page_from_resolved` were extracted; the event-emitting loop is still one
generator, because splitting a generator that yields mid-loop into functions costs
readability rather than buying it.

---

## Verification

```
cd packages/engine && uv run pytest tests -q          # 713 passed (was 620)
make lint                                             # ruff, mypy --strict, tsc, eslint: clean
uv run --package webgraph-api pytest apps/api/tests   # 24 passed
uv run --package webgraph python benchmark/article_extraction/run.py --corpus <zyte checkout>
```
