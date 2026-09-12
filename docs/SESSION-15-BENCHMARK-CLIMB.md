# The benchmark climb: what moved, what was built, and the result that reversed a decision

The brief was to run the engine on every public content-extraction benchmark, find where it
was behind, and fix the causes rather than the scores. "Please don't cheat. Do the hard
work." This is what happened, including the part that did not work.

## 1. Extraction fixes, each from a diagnosed bug

WCXB dev (1,497 human-reviewed pages, seven page types, word-level F1) went **0.714 ->
0.810** across five fixes. None of them is a tuned constant; each is a bug that a page-level
diagnostic (`benchmark/wcxb/analyze.py`) surfaced.

| # | Bug | Evidence | Result |
|---|---|---|---|
| 1 | `<noscript>` was stripped, but Discourse forums put the whole thread inside it | 19 of 112 forum pages parsed to **zero blocks**, each with 1,000-5,600 words of ground truth in the `<noscript>` | `unwrap_noscript_shell`, guarded both ways |
| 2 | `<select>` options scored as prose | 12,985 words of `<option>` text across 26 article pages; on glossier.com the selector returned a 200-country list *instead of* the terms | form controls added to `SKIP_TAGS` |
| 3 | `role="main"` was invisible | landmarks were read from XPath, which carries tag names only; **178 of 1,476 pages** declare main content by ARIA role alone | blocks carry their landmark region |
| 4 | A wrapper element re-emitted its own children | a `<section>` wrapping 24 paragraphs was emitted as one 1,372-word block **and** as 24 paragraphs; precision 0.48 at recall 1.00, invisible to exact-text dedup | `_orphan_text` made recursive |
| 5 | `<main>` was never used to scope | -- | `scope_to_main`, with a share guard so a `<main>` holding a filter panel is not trusted |

A methodological point that cost real time and is worth keeping: **an experiment measured on
top of a bug measures the bug.** The `trust_main_links` change read as -0.003 before fix 4
and +0.007 after it. Nothing about the change had altered.

## 2. Two trained models, both honest about their numbers

Neither is a heuristic with a threshold. Both are gradient-boosted ensembles trained on WCXB
**dev only**, exported to JSON, and run in pure Python -- the engine's runtime dependencies
are still httpx, lxml, pydantic and jsonschema. Both are cross-validated so that every page
is scored by a model that never trained on it.

**Page-type router** (62 features, 971 KB): 5-fold CV accuracy **0.838**, against 0.866 for
the router in rs-trafilatura, which tops WCXB. Listing is the weak class at 0.343 recall --
a news section front and a category page look alike.

**Per-block content classifier** (47 features, 319 KB, 212,373 blocks): out of fold on WCXB
dev, **0.810 -> 0.839**, better on six of seven page types, listings **+0.125**. Pure-Python
inference reproduces scikit-learn to 1.1e-16 over 20,000 blocks.

I did not take the trainer's word for that 0.839. `benchmark/train/blockmodel_oof.py`
recomputes it from the fold probabilities, reading ground truth from the corpus and
importing the corpus's own `word_f1`. It agrees to three decimals.

## 3. The result that reversed the decision

The classifier shipped as the default for about an hour. Then WebMainBench ran.

WCXB and Zyte both score a **bag of `\w+` tokens**. WebMainBench's calibrated 545-page
subset scores Markdown by **edit distance**, with tables and code in their own columns.

```
                 boundary   model    delta
overall            0.6224  0.5861   -0.036
text_edit          0.7567  0.7249   -0.032
code_edit          0.8099  0.7436   -0.066
table_edit         0.3485  0.2456   -0.103
table_TEDS         0.5558  0.4693   -0.087
prose-only slice   0.7145  0.6747   -0.040   <- 131 pages, no table, code or formula
```

The prose-only row rules out the easy explanation, and two measured repairs confirm it:
re-inserting tables and code into the span the model kept is worth **+0.000**; filling the
span completely is worth **-0.045**.

Reading pages rather than means gives the answer. Over 120 pages the model is worse on 54
and better on 39, and its worst cases are two failures:

* **It discards most of long documents.** A 13,591-character recipe that the boundary step
  extracts at 0.996 comes back as 1,715 characters, scoring 0.109.
* **It keeps comment and navigation furniture** -- "Add your comments...", "User Name
  Required", a font-size control. The boundary step excludes these because they are not
  contiguous with the prose; the model scores each block alone and lets them through.

Missing words cost a little recall, and the chrome the boundary step drops buys precision
back, so on word-F1 the two failures **net out positive**.

> WCXB's metric cannot distinguish an extractor that keeps the right *run* of text from one
> that keeps a scattered *subset* of the right tokens. A model trained against it optimises
> the second.

So the classifier is opt-in (`select_content(blocks, model=SHIPPED_MODEL)`) and the
contiguous boundary is still the default. Nothing was deleted: the model, its trainer, its
verifier and its documentation are in tree, and the next attempt should train against a
structure-aware target.

## 4. Three ways this nearly became a fake result

1. **`benchmark/wcxb/run.py` would have scored a dev-trained model against dev.** Its
   `content` variant called `select_content(blocks)`; the moment the model became the
   default, that variant was the model measured on its own training data. Every runner now
   passes `model=None` **explicitly**, with a comment, because the failure is silent: two
   columns quietly become one system and the table still prints.
2. **I flipped the default while two benchmarks were running.** Their worker pools are
   created per dataset, so workers spawned after the edit picked up the new default. Both
   runs were killed and restarted. An engine edit during a benchmark run invalidates the
   run.
3. **`config=` was being silently ignored** whenever a model ran, which would have collapsed
   the router's own variants into the model with no warning. `select_content` now raises.

## 5. Everything else that shipped

* **A real parse bug**, found by WCEB: lxml refuses a `str` carrying `<?xml ... encoding?>`,
  which XHTML served as HTML has. Eight pages lost their *entire* document, not a fragment.
* **`page_type` and `page_type_confidence`** on `/api/text` and every crawl page event. The
  router labels the page; nothing in extraction branches on it, because the classifier
  already subsumed the routed selector's gain.
* **`benchmark/webmainbench/run.py` was scoring three variants and hiding its best.** Its
  full-set ROUGE path looped over the three base variants, so `main-content` -- the engine's
  strongest variant on every other corpus -- was absent from the 7,809-page table entirely.

## 6. Where the engine stands

| benchmark | metric | engine | rank | field |
|---|---|---:|---|---|
| WCXB dev | word F1 | 0.810 | -- | rs-trafilatura 0.859 |
| Zyte article-extraction | shingle F1 | 0.895 | 15 of 35 | AutoExtract 0.970, trafilatura 0.958 |
| WCEB, 3,985 pages | ROUGE-LSum | **0.843** | **3 of 7** | trafilatura 0.867, readability 0.855, boilerpipe 0.825, resiliparse 0.819, justext 0.806 |
| WebMainBench 545 | edit distance | 0.622 | 2 of 5 | mineru-html 0.826, magic-html 0.500, trafilatura 0.401 |
| Firecrawl scrape-evals | best-window F1 | 0.437 | 8 of 14 | Firecrawl 0.676, Exa 0.527, Crawl4AI 0.453 |

**One corpus where this engine is first anywhere: cetd, inside WCEB.** 700 pages, 0.925
against trafilatura 0.907, readability 0.897, resiliparse 0.881, justext 0.863, boilerpipe
0.850. Second on dragnet's 1,379 pages at 0.828, ahead of four of the six published systems.

Weakest where precision binds: cleanportaleval runs recall 0.965 at precision 0.689.

On Firecrawl's benchmark the constraint is not extraction. Quality conditioned on a
successful fetch is **0.711**; 253 of 1,000 URLs returned 4xx to an honest bot user agent
from a single address, while seven of the thirteen published engines fetch through commercial
anti-bot fleets. That run used the static path and never touched the browser renderer.

Not top overall, and this document is deliberately explicit about which gaps are real.
