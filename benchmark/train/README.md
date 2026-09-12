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
    --corpus <wcxb clone> --oof <scratch>/router_oof.json \
    --export packages/engine/src/webgraph/models/router_gbdt.json
```

HistGradientBoosting, 120 iterations, depth 4, 62 features. Exported 971 KB; pure-Python
inference reproduces sklearn's probabilities to `0.00e+00`; 0.76 ms per page.

**5-fold CV accuracy 0.838** (rs-trafilatura reports 0.866 for its XGBoost router).

| truth | N | recall | predicted as |
|---|---:|---:|---|
| article | 793 | 0.947 | article 751, service 23, listing 6, collection 4 |
| forum | 113 | 0.894 | forum 101, article 10, service 2 |
| product | 119 | 0.849 | product 101, article 7, service 7, listing 2 |
| documentation | 91 | 0.791 | documentation 72, article 14, service 5 |
| collection | 117 | 0.709 | collection 83, service 14, listing 7, product 6 |
| service | 165 | 0.679 | service 112, article 32, listing 8, product 5 |
| listing | 99 | 0.343 | listing 34, article 33, collection 16, service 11 |

Listing is the weak class: a news section front and a category page look alike in URL and
structure, and the corpus has 99 of them against 793 articles. Top features by permutation
importance: `doc_hits_per_100w`, `url_forum`, `url_slug_words`, `url_article`,
`cta_hits_per_100w`, `forum_hits_per_100w`, `url_product`, `link_density`,
`price_hits_per_100w`, `og_product`.

The router's *worth* is measured downstream, not by its accuracy: `benchmark/wcxb/run.py`
has a `routed-oof` variant that applies `policy_for(type)` using the out-of-fold prediction
for each page, and a `routed-truth` diagnostic that uses the annotated type -- the ceiling a
perfect router could reach. See MEMORY.md for the measured rows.

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
