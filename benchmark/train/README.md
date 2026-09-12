# Trained components: how they were trained, and the numbers that justify them

Two small models ship inside the engine as JSON and run in pure Python. Both are trained on
the **WCXB development split only** (1,497 pages, seven annotated page types, CC-BY-4.0).
Nothing here has seen the WCXB held-out test split, Zyte, CleanEval, WCEB or WebMainBench;
those remain untouched test sets. Every number below is **5-fold cross-validated**: each
page is predicted by a model that never trained on it. The shipped model is trained on all
of dev, and its *training* accuracy is deliberately not reported anywhere.

Features are generic by construction -- URL path words, JSON-LD types, Open Graph type,
block structure -- never a domain or a page id. `tests/test_pagetype.py` asserts the same
page on two hosts yields an identical vector.

## Page-type router (`webgraph/pagetype.py`, `models/router_gbdt.json`)

```
uv run --package webgraph python benchmark/train/router_train.py \
    --corpus <wcxb clone> --oof benchmark/train/artifacts/router_oof.json \
    --export packages/engine/src/webgraph/models/router_gbdt.json --class-weight balanced
uv run --package webgraph python benchmark/train/router_eval.py --corpus <wcxb clone>
```

HistGradientBoosting, 120 iterations, depth 4, class-weighted, **126 features**. Exported
994 KB; pure-Python inference reproduces sklearn's probabilities to `0.00e+00`; 0.76 ms per
page. The out-of-fold predictions it was scored on are committed beside it, so the schema
benchmark can route with them.

### How it is scored, and why that changed

Folds are grouped by **domain**. The corpus has 1,497 pages over 1,300 domains, and a page
must never be judged by a model that trained on its sibling. Ungrouped folds were tolerable
while every feature was a shape signal; they stopped being tolerable the day a `<title>`
became a feature, because a title carries the site's name and an ungrouped fold lets the
model learn *site → type* -- the fingerprint this router refuses to be. Under the grouped
protocol the previously shipped model scores 0.825, not the 0.838 the old README claimed.
Both numbers below are grouped.

Below 0.5 confidence the router says `unknown`. Measured on the out-of-fold predictions it
is right 86% of the time above that line and **44%** below it.

### Results

| | accuracy | macro-F1 | listing recall | service recall |
|---|---:|---:|---:|---:|
| previous (68 features), dev, grouped 5-fold | 0.825 | 0.746 | 0.44 | 0.67 |
| **this model** (126 features), dev, grouped 5-fold | **0.858** | **0.799** | 0.50 | 0.73 |
| previous, **test split**, once | 0.865 | 0.817 | 0.48 | 0.71 |
| **this model, test split, once** | **0.871** | **0.819** | 0.40 | 0.73 |

The dev gain is +3.3 points of accuracy and +5.3 of macro-F1, stable to ±0.1 across seeds.
**The test gain is +0.6 and +0.2, which on 511 pages is inside the noise**, and listing
recall on test went *down* (19 → 16 of 40). Both rows are here because reading only the
first would be the kind of claim this project does not make.

Two things make the test split a different distribution from dev, and neither favours the
new model: the archiver stripped every `<script>` from those files, so the JSON-LD features
are zero on all of them; and the class-name and title features were chosen against dev,
which is the only place their vocabulary was ever tuned. The honest summary is that the new
features help clearly on the distribution they were built on and slightly, at most, on a
held-out one. A second corpus would settle it.

| truth | N | recall | predicted as (dev, out of fold) |
|---|---:|---:|---|
| article | 793 | 0.942 | article 747, service 16, listing 14, documentation 6 |
| forum | 113 | 0.920 | forum 104, article 7, service 1, listing 1 |
| product | 119 | 0.849 | product 101, collection 11, service 3, article 3 |
| documentation | 91 | 0.846 | documentation 77, article 9, service 5 |
| collection | 117 | 0.744 | collection 87, listing 11, product 8, service 7 |
| service | 165 | 0.727 | service 120, article 29, listing 7, collection 4 |
| listing | 99 | 0.495 | listing 49, article 22, collection 12, service 11 |

### What the new features are, and what did not work

Three families, each kept only because it moved the grouped CV:

- **Arrangement, from block XPaths** -- how many `<section>`/`<article>` containers hold
  text, how spread the words are across top-level containers, facet/paging/pricing/Q&A
  vocabulary. Free: every block already carries its XPath.
- **Markup statistics, counted at build time** -- class-name buckets (`card`, `price`,
  `comment`, `pricing`...), element counts, `rel="next"`, `itemprop`, `data-*` share.
  Stored on the `Document` because the crawl drops the HTML.
- **The page's own words about itself** -- `<title>`, meta description, `og:title` and the
  first `<h1>`, with the site's name stripped via `og:site_name`, scored against seven
  hand-picked vocabularies.

Rejected: a 100-term TF-IDF over the same head text. It scored 0.4 points higher and its
top terms were *coffee, gym, headphones, insurance, cybersecurity* -- a model of what the
corpus happened to be about. Also a null result worth recording: the corpus defines
*service* pages by "content across multiple `<section>` elements", and `<section>` counts
alone do not separate them. Sites use `<div>` for everything.

The router's *worth* is measured downstream, not by its accuracy: `benchmark/schema/run.py`
routes with the out-of-fold predictions and reports how often an auto-selected schema
produces a wrong value. With this model and the 0.5 floor: 64.7% correct, 12.7% wrong
(lenient) and 49.4% / 28.0% (strict) on 869 pages -- against 58.7% / 23.4% and
44.2% / 37.9% for no routing at all.

## Per-block content classifier (`webgraph/blockmodel.py`, `models/block_gbdt.json`)

```
uv run --package webgraph python benchmark/train/blockmodel_data.py \
    --corpus <wcxb clone> --out <scratch>/blocks.jsonl.gz
uv run --package webgraph python benchmark/train/blockmodel_train.py \
    --data <scratch>/blocks.jsonl.gz \
    --export packages/engine/src/webgraph/models/block_gbdt.json
```

HistGradientBoosting, 150 iterations, depth 6, **47 features**, 212,373 blocks over the 1,497
dev pages. Exported 319 KB. Pure-Python inference reproduces scikit-learn to `1.11e-16` over
20,000 blocks; the model loads in 30 ms and predicts 1,000 blocks in 141 ms.

The model replaces `select_main_content`'s contiguous boundary with a per-block keep/drop
decision at **threshold 0.4**, behind the same fail-open guard: when the kept blocks hold
under 2% of the page's words, the whole page is returned rather than a sliver.

**It is opt-in** -- `select_content(blocks, model=SHIPPED_MODEL)`. The default is still the
boundary step. The section below on WebMainBench says why, and it is the more interesting
half of this file.

### The number, and why it is the out-of-fold one

The shipped model is fitted on all of dev, so running it over dev measures it on its own
training data. The honest number is out of fold -- each page scored by a model fitted on the
four folds that did not contain it -- and `blockmodel_oof.py` recomputes it from the fold
artefacts, reading the ground truth from the corpus and importing the corpus's own `word_f1`:

```
uv run --package webgraph python benchmark/train/blockmodel_oof.py \
    --corpus <wcxb clone> --train-dir <scratch>
```

| page type | N | boundary step | model, out of fold | delta |
|---|---:|---:|---:|---:|
| article | 793 | 0.920 | 0.927 | +0.007 |
| documentation | 91 | 0.906 | 0.903 | -0.002 |
| service | 165 | 0.777 | 0.836 | +0.059 |
| forum | 113 | 0.733 | 0.773 | +0.040 |
| collection | 117 | 0.555 | 0.615 | +0.060 |
| listing | 99 | 0.558 | 0.683 | +0.125 |
| product | 119 | 0.589 | 0.624 | +0.034 |
| **overall** | **1497** | **0.810** | **0.839** | **+0.029** |

Precision 0.815 -> 0.835, recall 0.864 -> 0.898. Twenty-three pages fail open. The gain is
concentrated exactly where a single contiguous boundary cannot work -- listings, collections,
services, forums -- which is the argument for the model rather than another hand-tuned rule.
Documentation is the one class that moves down, by 0.002.

Top features by permutation importance (AUC drop on fold 0's held-out blocks):
`kind_image` +0.062, `words` +0.022, `relative_position` +0.020, `group_word_share` +0.019,
`page_words` +0.011, `kind_list_item` +0.010, `digit_share` +0.010, `region_main` +0.009.

### Where it holds, and where it does not

Two untouched corpora, neither of which the model trained on and neither of whose annotators
ever saw WCXB.

**Zyte's article-extraction benchmark holds**: F1 0.895 -> 0.897, precision 0.838 -> 0.832,
recall 0.960 -> 0.973 over 181 pages. That is inside the benchmark's own bootstrap error of
+/-0.010, so it is "no worse", not "better". Articles are also the model's strongest class.

**WebMainBench's 545-page calibrated subset is worse, and it is the reason the model is
opt-in.** This one scores Markdown by edit distance and grades tables and code in their own
columns rather than pooling every token into one bag.

| column | boundary step | model | delta |
|---|---:|---:|---:|
| overall | 0.6224 | 0.5861 | -0.036 |
| text_edit | 0.7567 | 0.7249 | -0.032 |
| code_edit | 0.8099 | 0.7436 | -0.066 |
| table_edit | 0.3485 | 0.2456 | -0.103 |
| table_TEDS | 0.5558 | 0.4693 | -0.087 |

It is worse on every page slice, **including the 131 prose-only pages** with no table, code
or formula on them (0.7145 -> 0.6747). So it is not a story about structured content, and
two repairs confirmed that: re-inserting tables and code into the span the model kept is
worth +0.000, and filling the span completely is worth -0.045.

Reading the pages instead of the means gives the actual answer. Over 120 pages the model is
worse on 54 and better on 39, and its worst cases are two distinct failures:

* **It discards most of some long documents.** A 13,591-character recipe that the boundary
  step extracts at 0.996 comes back from the model as 1,715 characters, scoring 0.109. A
  20,789-character Chinese regulation comes back as 5,876.
* **It keeps comment and navigation furniture.** "Add your comments...", "User Name
  Required", "Go to Forum >> 0 Comments", a font-size control, a list of city links. The
  boundary step excludes these because they are not contiguous with the prose; the model
  scores each one alone and lets them through.

Both are invisible to a bag of words. Missing words cost a little recall, and the chrome the
boundary step dropped buys precision back, so on WCXB the two failures net out **positive**.
An edit distance charges for both immediately.

The lesson is about the metric, not the model: **WCXB's word-F1 cannot distinguish an
extractor that keeps the right run of text from one that keeps a scattered subset of the
right tokens.** A model tuned on it optimises the second. That is worth knowing before
anyone trains the next one on the same target.

WCXB's **test** split has never been opened, and there is no reason to open it now.
