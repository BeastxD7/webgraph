# Article extraction: this engine vs 34 published systems

Zyte's [article-extraction-benchmark](https://github.com/scrapinghub/article-extraction-benchmark)
(archived, MIT, 181 cached news and blog pages from late 2019). Metric is 4-gram shingle
TP/FP/FN, normalised per document then macro-averaged; `accuracy` is the share of pages whose
token sequence matches the ground truth exactly.

```
git clone https://github.com/scrapinghub/article-extraction-benchmark
uv run --package webgraph python benchmark/article_extraction/run.py --corpus <checkout>
cd <checkout> && python3 evaluate.py
```

**Every number in this file was measured against commit `edff2ff`**, exported with
`git archive HEAD` and run via `PYTHONPATH=<export>/packages/engine/src`. That pin is not
ceremony: the first pass of this measurement was taken against a working tree that was being
edited concurrently, and a 377-line change to `dom/blocks.py`, `dom/rich.py` and `pipeline.py`
moved `webgraph_raw` from 0.623 to 0.643 underneath it. A benchmark number without a commit
attached is not a number. Re-run against a dirty tree and expect to disagree with this file.

181 of 181 pages parsed. **Zero failures, zero empty outputs** — which matters, because
`evaluate.py` averages precision only over documents where `tp + fp > 0` while averaging
recall over `tp + fn > 0`. An empty prediction silently leaves the precision mean and stays
in the recall mean, so a crashy extractor is rewarded. No asterisk is needed on the numbers
below.

## Result

| variant | F1 | precision | recall | accuracy | rank |
|---|---|---|---|---|---|
| `webgraph_prose_landmarks` | 0.709 ± 0.016 | 0.561 ± 0.018 | 0.963 ± 0.011 | 0.000 | 23rd of 35 |
| `webgraph_landmarks` | 0.689 ± 0.016 | 0.535 ± 0.018 | 0.968 ± 0.010 | 0.000 | 23rd of 35 |
| `webgraph_prose` | 0.642 ± 0.016 | 0.481 ± 0.017 | 0.963 ± 0.011 | 0.000 | 27th of 35 |
| `webgraph_raw` | 0.623 ± 0.018 | 0.459 ± 0.019 | 0.968 ± 0.011 | 0.000 | 27th of 35 |

Rank is against **the 34 published systems plus the one variant being ranked** — the honest
denominator. Ranking all four webgraph rows in a single table of 38 pads the count for the
weaker variants by making them compete against their own siblings.

Read the columns separately, because averaging them hides the whole story.

**Recall 0.968 is 14th of 35 — competitive, not exceptional.** Thirteen published systems
beat it: five whole-page text dumps that win by emitting *everything* (`html-text` and
`beautifulsoup` at 0.994, `inscriptis` and `xpath-text` at 0.992, `html2text` at 0.983), and
eight real article extractors including `rs_trafilatura` (0.990), `readability_js` (0.982) and
`trafilatura` (0.978). The useful reading is that the engine is within ~0.01–0.02 recall of
the extractors at the top of the table while making no attempt to select content — the
article body is present in its output on essentially every page.

**Precision 0.459–0.561 is bottom-quartile.** The engine also emits the masthead, the
section nav, the related-articles rail, the comment thread and the footer, because keeping
everything a reader would see is what it is for. Against an article-body ground truth that
is all false positives.

**Accuracy 0.000 is arithmetic, not a finding.** Exact token-sequence equality with the
ground truth requires an article-body extractor. Every non-article-extractor in the table
scores 0.000 too.

## Full leaderboard

```
(All four webgraph variants shown together for comparison; see the rank note above.)

rank system                         F1       P       R     acc
1    AutoExtract                 0.970   0.984   0.956   0.470
2    rs_trafilatura              0.970   0.951   0.990   0.287
3    go_trafilatura              0.960   0.940   0.980   0.287
4    trafilatura                 0.958   0.938   0.978   0.293
5    Diffbot                     0.951   0.958   0.944   0.348
6    newspaper                   0.949   0.964   0.934   0.326
7    news_please                 0.948   0.964   0.933   0.326
8    readability_js              0.947   0.914   0.982   0.166
9    go_readability_fork         0.947   0.914   0.982   0.166
10   go_readability              0.934   0.900   0.971   0.188
11   go_domdistiller             0.927   0.901   0.956   0.061
12   readability                 0.922   0.913   0.931   0.315
13   dragnet                     0.907   0.925   0.889   0.221
14   goose3                      0.896   0.940   0.856   0.232
15   readable_readability        0.884   0.886   0.881   0.177
16   readability_rs              0.873   0.906   0.843   0.227
17   dom_smoothie                0.865   0.785   0.963   0.055
18   boilerpipe                  0.860   0.850   0.870   0.006
19   readabilityrs               0.832   0.745   0.943   0.028
20   llm_readability             0.829   0.851   0.809   0.077
21   justext                     0.804   0.858   0.756   0.088
22   boilerpipe_rs               0.739   0.761   0.717   0.000
23   webgraph_prose_landmarks    0.709   0.561   0.963   0.000  <<<
24   webgraph_landmarks          0.689   0.535   0.968   0.000  <<<
25   inscriptis                  0.679   0.517   0.992   0.000
26   html-text                   0.665   0.500   0.994   0.000
27   beautifulsoup               0.665   0.499   0.994   0.000
28   html2text                   0.662   0.499   0.983   0.000
29   webgraph_prose              0.642   0.481   0.963   0.000  <<<
30   webgraph_raw                0.623   0.459   0.968   0.000  <<<
31   fast_html2md                0.515   0.351   0.967   0.000
32   august                      0.471   0.312   0.955   0.000
33   nanohtml2text               0.469   0.309   0.973   0.000
34   html2text_rs                0.438   0.283   0.965   0.000
35   mdka                        0.435   0.285   0.914   0.000
36   xpath-text                  0.394   0.246   0.992   0.000
37   htmd                        0.184   0.102   0.970   0.000
38   html2md_rs                  0.150   0.142   0.160   0.000
```

The engine sits with the whole-page text dumps (`inscriptis`, `html-text`, `html2text`) and
above them, which is where an engine with no main-content selector belongs. `strip_landmarks`
is worth **+0.066 F1** on its own — the largest single lever currently in the codebase.

## What the ceiling actually is

`--oracle` picks, for each page, the **contiguous run of the engine's own unfiltered blocks**
that scores best *using the ground truth*. Nothing about extraction changes; only selection
is credited.

```
$ uv run --package webgraph python benchmark/article_extraction/run.py --corpus <c> --oracle
oracle contiguous-block window (stride 1/60, so a LOWER bound):
  F1=0.945  P=0.929  R=0.960
```

**This is a ceiling, not a forecast.** An oracle that consults the answer is not a heuristic;
a real selector, which cannot, lands materially below 0.945. Nobody should read this as "add
density selection and rank 9th."

What it does establish, and this is the finding that matters: **on essentially every page the
article body is already present as one contiguous span of blocks in the correct order.** The
extractor and the reading order are not what is costing 0.235 F1 — the absence of any
main-content selection is. Selection is therefore possible in principle over the blocks the
engine already produces, which is not obvious a priori and is exactly what a whole-page
engine could have got wrong.

(Start and end candidates are sampled on a 1/60 stride rather than exhaustively, so 0.945 is
itself a lower bound on the true best window.)

## Worst five pages, by F1 on `webgraph_prose_landmarks`

| F1 | P | R | page | verdict |
|---|---|---|---|---|
| 0.000 | 0.000 | 0.000 | jaraguadosul.com.br | ENGINE DEFECT |
| 0.002 | 0.001 | 0.011 | macrumors.com | ENGINE DEFECT |
| 0.024 | 0.054 | 0.015 | appleinsider.com | ENGINE DEFECT |
| 0.040 | 0.021 | 1.000 | blog.givewell.org | SCOPE — no main-content selector |
| 0.187 | 0.210 | 0.168 | autoracing.com.br | VARIANT ARTEFACT — not the engine |

### 1–3. Bare text nodes in a mixed container are dropped

Three of the five are one bug — in fact all four of the catastrophic pages are. Each uses
markup where the article is a sequence of **bare text nodes inside a container that also has
an element child**. Usually the separator is `<br><br>` (AppleInsider, MacRumors,
jaraguadosul); on IGN it is a `<section class="article-page">` whose body text sits directly
under inline children. AppleInsider:

```html
</div><br><br>
We're not certain when Apple last issued four updates to the MacBook Pro within
18 months, or to any laptop it has ever produced. But, here we are.<br><br>
```

`extract_blocks` skips any BLOCK_TAG element whose `has_block_descendant` is true, deferring
to the children. But the skipped container's *own* text and its children's `tail` text are
then emitted by nobody. Three-line repro:

```python
h = ('<html><body><div>Alpha bravo charlie delta echo.<br><br>'
     '<div><img src=x><span>Caption text</span></div><br><br>'
     'Foxtrot golf hotel india juliet kilo lima.</div></body></html>')
build_document(h, 'http://x/').text
# 'Caption text'          <- both sentences gone
```

Blast radius on this corpus: **8 of 181 pages lose >10% of the article body, and 4 lose
essentially all of it** (jaraguadosul recall 0.000, MacRumors 0.011, AppleInsider 0.018, IGN
0.182 — all four verified against the raw HTML, all four the same mechanism). Because recall
is already 0.968, fixing it is worth roughly +0.02 F1 — small against the leaderboard, but it
is a *correctness* bug in the core parser rather than a tuning question, it is part of why
the oracle stops at 0.945 rather than ~0.97, and it means the engine currently returns almost
nothing for a whole class of older CMS output.

### 4. GiveWell open thread — no main-content selector

Ground truth is the 419-character post. The engine returns 20,825 characters: recall 1.000,
precision 0.021. The post is in there, verbatim and correctly ordered —

> September 10, 2018 | by Catherine
>
> Our goal with hosting quarterly open threads is to give blog readers an opportunity to
> publicly raise comments or questions about GiveWell or related topics…

— followed by the entire comment thread and a decade-deep date archive:

> Milan Griffes on September 12, 2018 at 4:47 pm said: Any update on how the Blattman et al.
> follow-up paper will affect GiveDirectly's recommendation?

Not a defect: the engine kept exactly what a reader sees, and `trafilatura` only scores 0.940
here because it is called with `include_comments=False`. But it is not a free pass either —
every competitor solves this, and the oracle shows the engine's own blocks contain the answer.

A secondary leak visible on this page: the comment is emitted **twice**, once as the whole
comment and once split into its constituent paragraphs. Corpus-wide — `run.py` prints this on
every run — **7.4% of output characters are duplicated block text**, with 7 of 181 pages more
than 25% duplicate. The metric counts shingles with multiplicity, so every second copy is pure
false positive. Worth a dedupe pass, though it is not the main precision story.

### 5. autoracing.com.br NASCAR standings — the prose filter, not the engine

The article *is* a results table, and the ground truth contains it as plain rows:

```
Pos. Piloto Pontos Vitórias Poles Top 5 Top 10
1 Kyle Busch 5040 5 1 17 27
```

The engine renders it correctly — `Pos. | Piloto | Pontos | …` / `1 | Kyle Busch | 5040 | 5
| 1 | 17 | 27` — and since `evaluate.py` tokenises on `\w+`, the `|` separators are invisible
to the metric and the cells match. `webgraph_landmarks` scores **0.756** here.

`webgraph_prose_landmarks` scores 0.187 because *this script's* prose filter drops TABLE
blocks. That is a defect in the measurement variant, not in the engine.

I assumed the table exclusion still paid for itself corpus-wide and then measured it. It does
not. Ablating one kind at a time on top of `strip_landmarks`:

| exclusion | F1 | delta |
|---|---|---|
| none (`webgraph_landmarks`) | 0.689 | — |
| minus IMAGE | 0.707 | **+0.018** |
| minus FIGURE_CAPTION | 0.693 | +0.005 |
| minus CODE | 0.689 | +0.000 |
| minus TABLE | 0.685 | **−0.004** |
| minus all four (`webgraph_prose_landmarks`) | 0.709 | +0.020 |

The entire prose-filter gain is image alt text and figure captions, which the ground truth
excludes. Dropping tables loses F1 outright, and dropping code does nothing on a news corpus.
The best kind filter available is therefore "drop IMAGE and FIGURE_CAPTION", measured at
**F1 0.712 / P 0.563 / R 0.970** — better than every variant reported above, and still 23rd.
Even that is the wrong instrument: a block-kind filter cannot tell a standings table from a
nav table. A density-based selector can. This is worth 0.003; selection is worth 0.235.

## Where the ground truth, not the engine, is the problem

Two format mismatches are quantified above rather than asserted:

**Captions and image alt text — worth +0.023 F1, measured.** The ablation shows FIGURE_CAPTION
(+0.005) and IMAGE (+0.018) exclusions paying off, which is the same statement as: Zyte's
annotators did not treat captions or alt text as `articleBody`, and the engine correctly keeps
both. `Apple's 16-inch MacBook Pro` under the AppleInsider photo is content by any reasonable
reading, and a false positive by this benchmark's. That is 0.023 F1 the engine can only win by
discarding something true.

**Paywall truncation in the ground truth — 3 pages.** Exactly three `articleBody` values end in
an ellipsis:

| chars | page |
|---|---|
| 369 | wsj.com/…/google-stadia-microsoft-xcloud-apple-arcade |
| 536 | wsj.com/…/is-football-violence-a-crime |
| 2570 | businessinsider.com/…/10-things-in-tech-you-need-to-know |

The first ends `…keep updating their biggest hits with new maps, missions and characters.\n\nAll...`
— the annotation captured the free preview, not the article. It is #10 in the worst list
(F1 0.271, recall 1.000, precision 0.157): the engine found the whole visible page, and was
marked down for it. Unwinnable, but only 3 of 181 pages, so this is a footnote, not an
explanation of the score.

## Honest read

**0.709 is a mediocre number honestly earned.** It is 23rd of 38 and 0.26 F1 behind
trafilatura. Anyone quoting it as "webgraph scores 0.709 on article extraction" is quoting a
measurement of something the engine does not attempt: it has no main-content selector, and
this benchmark scores nothing else.

What the run is actually worth is the three things underneath the number:

1. **Recall 0.968 with zero failures and zero empty outputs over 181 uncurated 2019 pages.**
   The block extractor and reading order hold up on real-world markup.
2. **A real parser bug found**, reproducible in three lines, that silently returns nothing for
   `<br><br>`-style article markup.
3. **Evidence that the article body is a contiguous block span on essentially every page**, so
   the missing capability is selection rather than extraction.

**The single highest-leverage change: a text-density / link-density main-content selector over
the existing block list** — the classic boilerpipe heuristic, which needs no corpus, no new
dependency and no change to extraction. Every alternative is an order of magnitude smaller:
the best possible block-kind filter is worth +0.023, `strip_landmarks` is already banked at
+0.066, and fixing the parser bug is worth ~+0.02. Selection is worth up to +0.235.

Two caveats on that recommendation, stated because the number is seductive. The 0.945 is an
oracle and a real heuristic will land well short of it. And a selector is a *different product
decision*, not just an improvement: it means throwing away content on purpose, which is the
opposite of what this engine currently promises. The right move is probably to add it as an
opt-in mode and keep the whole-page output the default — at which point this benchmark
measures the mode, and the 0.709 above stops being the relevant number.
