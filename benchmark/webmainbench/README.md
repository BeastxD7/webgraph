# WebMainBench: the only corpus here that scores tables and code apart

[WebMainBench](https://github.com/opendatalab/WebMainBench) (Apache-2.0, opendatalab), 7,809
human-annotated pages over 5,434 domains and 46 languages, with a **545-page subset whose
ground truth was manually calibrated to Markdown**. Only that subset carries
`groundtruth_content`, and only that subset can be scored per content type. Everything below
is the 545.

```
git clone --depth 1 https://github.com/opendatalab/WebMainBench
huggingface-cli download opendatalab/WebMainBench --repo-type dataset \
    --include 'WebMainBench_545.jsonl' --local-dir <clone>/data

uv run --package webgraph --group bench python benchmark/webmainbench/run.py \
    --corpus <clone> --calibrate --worst table_TEDS --scores-dir .scores
```

## Why this corpus and not the sibling benchmarks

Every other content measurement in this tree scores one number over one blob of text, and all
three are actively misleading about the part of the engine that handles structure:

* `benchmark/content_quality` scores against a **vote of trafilatura, readability and
  jusText**. jusText drops `<pre>` entirely, so a code block the engine correctly keeps is a
  *precision loss*.
* `benchmark/article_extraction` scores 4-gram shingles against a prose `articleBody`, and
  `benchmark/wcxb` scores a bag of `\w+` tokens. Neither can tell `| a | b |` from `a b`, so
  getting a table's **structure** right earns exactly nothing and getting it wrong costs
  exactly nothing.

WebMainBench splits the score into `text_edit`, `code_edit`, `formula_edit`, `table_edit` and
`table_TEDS`. It is the instrument that can see the work. That turns out to matter: on the
columns the sibling benchmarks are blind to, this engine beats both calibration baselines by
2-20x, while on the one column they *can* see it loses.

## Result — 545 pages, engine offline over cached HTML

**Every number here was measured against commit `edff2ff` plus an uncommitted working tree**
(934 insertions across 11 files under `packages/engine/src/webgraph`), snapshotted to a
scratch directory and run through `PYTHONPATH`. Snapshot content hash
`9096c08b0b45eed4c343c1c4a922fb0f4ec06b0c`
(`find <snap> -name '*.py' | sort | xargs shasum | shasum`). The sibling
`benchmark/article_extraction/README.md` records why the pin matters — a concurrently edited
tree moved a headline by 0.02 underneath the last measurement. **This tree is not a commit**,
so re-running against `edff2ff` alone will not reproduce these numbers.

545 of 545 pages parsed. Zero failures, zero empty outputs, and **zero pages excluded** — no
page hit the 90-second scoring budget.

```
  system                  overall    text_edit    code_edit formula_edit   table_edit   table_TEDS
  ------------------------------------------------------------------------------------------------
  webgraph raw             0.4570       0.5243       0.8168       0.2764       0.2778       0.4989
  webgraph landmarks       0.4804       0.5613       0.8168       0.2764       0.2816       0.5057
  webgraph prose           0.3344       0.4505       0.0000       0.2808       0.0000       0.0000
  webgraph main-content    0.5116       0.6270       0.6904       0.2843       0.3154       0.4998
  trafilatura(md)          0.5695       0.7382       0.3278       0.2994       0.1663       0.2537
  resiliparse              0.5081       0.7435       0.0422       0.2997       0.0000       0.0000
  N (scored)                  545          544           91          286          149          149
```

`trafilatura(md)` and `resiliparse` were run **through this same harness**, not quoted. That
is what licenses reading the engine's rows at all, and it is the only comparison in this file
that is like-for-like. See "Does the harness work" below.

The four variants are `document.blocks` as parsed (`raw`), that with `<nav>`/`<footer>`
subtrees dropped (`landmarks`), PARAGRAPH/HEADING/LIST_ITEM/QUOTE only (`prose`), and
`select_main_content(strip_landmarks(blocks))` (`main-content`).

`code_edit` and `formula_edit` are **byte-identical between `raw` and `landmarks`**. That is
correct, not a copy-paste: `strip_landmarks` removed no CODE block and no formula-bearing
block on any of the 545 pages, so the extracted buckets are the same strings.

## Read the columns separately — the mean hides the entire finding

| column | webgraph best | trafilatura(md) | resiliparse | read |
|---|---|---|---|---|
| `code_edit` | **0.8168** | 0.3278 | 0.0422 | 2.5x / 19x the baselines |
| `table_TEDS` | **0.5057** | 0.2537 | 0.0000 | 2x trafilatura; resiliparse cannot score at all |
| `table_edit` | **0.3154** | 0.1663 | 0.0000 | 1.9x trafilatura |
| `formula_edit` | 0.2843 | 0.2994 | 0.2997 | a wash — and see the protocol note |
| `text_edit` | 0.6270 | **0.7382** | **0.7435** | −0.11 behind a *plain-text* extractor |
| `overall` | 0.5116 | **0.5695** | 0.5081 | between the two baselines |

**The engine wins every structural column and loses the unstructured one.** `text_edit` is
not "text minus code and tables" despite the metric class saying so — with no `content_list`
on either side the splitter falls through to `_extract_from_markdown`, whose `text` key is
the *whole markdown, unmodified*. So `text_edit` is whole-document character similarity, the
engine emits 1.63x the ground truth's characters (median, `landmarks`), and every extra
character is inserted edit cost. `overall` is a per-sample mean dominated by that column,
which is why it reads as "middling" while the columns underneath it are bimodal.

The per-slice breakdown makes it unambiguous. `overall`, sliced by the annotators' own `meta`
(slices overlap):

```
  system                       simple          mid         hard    has table     has code  has formula   prose only
  -----------------------------------------------------------------------------------------------------------------
  webgraph landmarks           0.6190       0.4749       0.3498       0.4185       0.6266       0.4676       0.4516
  webgraph main-content        0.5797       0.5392       0.4072       0.4402       0.6386       0.5195       0.4543
  trafilatura(md)              0.7117       0.5523       0.4511       0.4187       0.5745       0.5028       0.7473
  resiliparse                  0.6711       0.4780       0.3860       0.3442       0.4427       0.5069       0.6398
  N (pages)                       163          218          164          179          127          257          131
```

On **code-bearing pages the engine leads trafilatura 0.6386 to 0.5745**, on table-bearing
pages 0.4402 to 0.4187, on formula-bearing pages 0.5195 to 0.5028. On **prose-only pages it
loses 0.4543 to 0.7473** — a 0.29 deficit against trafilatura and 0.19 against resiliparse,
the largest gap between the engine and any baseline anywhere in this file. This is the same
engine on both rows. The difference is entirely whether the page has structure worth
preserving.

`prose` scores 0.0000 on `code_edit`, `table_edit` and `table_TEDS` because the variant
excludes CODE and TABLE blocks by construction. That is arithmetic, not a finding — it is the
same shape as published `resiliparse`, and it makes `prose`'s `overall` incomparable. It is
reported because the cost of that filter should be visible rather than hidden.

## Does the harness work? — calibration against two published rows

Without this the engine's numbers are unfalsifiable: a low `table_TEDS` could equally mean
weak tables or a scorer fed the wrong shape.

| | ours | published | |
|---|---|---|---|
| resiliparse `text_edit` | 0.7435 | 0.7435 | **exact** |
| resiliparse `code_edit` | 0.0422 | 0.0422 | **exact** |
| resiliparse `table_edit` / `table_TEDS` | 0.0000 / 0.0000 | 0.0000 / 0.0000 | **exact** |
| trafilatura(md) `text_edit` | 0.7382 | 0.7826 | −0.044 |
| trafilatura(md) `table_TEDS` | 0.2537 | 0.2999 | −0.046 |
| both, `formula_edit` | 0.2994 / 0.2997 | 0.6237 / 0.6631 | **−0.33 / −0.36** |

Four of resiliparse's five columns reproduce to the digit. The trafilatura columns land
within 0.05, consistent with a version or flag difference. **`formula_edit` collapses for
both baselines, not just for webgraph** — which settles what that column means here (below).

## The published table is a reference, not the comparison

Two independent reasons, both structural:

1. **Its per-column N is not published, and N is not 545.** A column counts pages where
   *either side* produced that content type, and empty-vs-empty returns `success=False`,
   which `aggregate_results` drops. So `table_TEDS` is a mean over 149 pages for
   `webgraph raw` and 112 for `webgraph main-content` — because the selector removed 37 pages
   of engine-invented tables — and over some unpublished number for the starred rows.
   Comparing them is the same class of error as the ROUGE splice below.
2. **The published rows were produced with `USE_LLM=true`**, routing spans through DeepSeek
   to strip currency (`$1,150.00`) out of the formula bucket. This runner is offline and
   forces `use_llm: False`.

Scope of that deviation, stated precisely: `CodeSplitter.extract` and `TableSplitter.extract`
never call the LLM path (both call `extract_basic`, and their `_llm_enhance` is the identity),
and `text_edit` is unaffected. **Only `formula_edit` changes**, and it changes symmetrically —
`split_content` is called without `field_name`, so disabling the LLM disables it on prediction
and ground truth alike. The calibration above measures the size of that change: it costs
trafilatura 0.33 and resiliparse 0.36. Read `formula_edit` as "regex-delimited math-ish spans,
offline", compare it only across the six unstarred rows, and never against the published
column. On that basis webgraph's 0.2843 against trafilatura's 0.2994 is a wash, not a defect.

### The leaderboard splice

The project README publishes **two tables that are not comparable**, and quoting across them
is easy and wrong:

| table | metric | corpus | rows |
|---|---|---|---|
| ROUGE-N F1 | whole-document similarity, N=5, jieba | full 7,809 | Dripper 0.8779, magic-html 0.7138, Readability 0.6543, trafilatura 0.6402, resiliparse 0.6290 |
| fine-grained edit distance | five type columns + mean | 545 subset | mineru-html 0.8256, magic-html 0.4996, trafilatura(md) 0.4013, trafilatura(txt) 0.3718, resiliparse 0.2898 |

`overall` in this runner is the second table. **Comparing it to 0.7138 or 0.6402 compares a
five-way type average to a ROUGE score.** Of the four numbers usually quoted as "the
WebMainBench leaderboard" — 0.8256, 0.7138, 0.6402, 0.6290 — only the first belongs anywhere
near this runner's output, and even it carries the two caveats above.

One more trap in the authors' own text: the README describes `overall` as the "arithmetic mean
of the five sub-metrics". It is not. It is a per-sample mean over that page's *surviving*
columns, then averaged. mineru-html's published row proves it — its five columns average
0.8656 while its published `overall` is 0.8256. A runner whose `overall` equalled its column
mean would be wrong.

## Markdown in, links off — the opposite of the sibling runners

`benchmark/article_extraction` and `benchmark/wcxb` feed the scorer `document.text`, because
their metrics tokenise on `\w+` and Markdown syntax would be charged as false-positive words.
**Here the reverse holds.** The metric is character-level Levenshtein, the ground truth is
Markdown, and the splitters key on exactly that syntax: `CodeSplitter` finds ``` fences and
4-space indents; `TableSplitter` finds `|` rows and `<table>`. Feed this scorer plain text and
`code_edit`, `table_edit` and `table_TEDS` are **0.0 by construction** — which is precisely
how resiliparse, the one TEXT-mode system on the board, scores 0.0000 on both table columns.

So all four variants go through the engine's own `to_markdown()`, with
`include_links=False, include_images=False`. That is not a guess: the ground truth contains a
Markdown link in **1 of 545 documents** and an image in 4, every `](https://…)` is pure
inserted cost under a character metric, and because `text_edit` is the whole document it moves
`overall` rather than a side column. Confirmed independently against the clone's own
`TrafilaturaExtractor`, which produced the published 0.4013 row and sets
`include_images=False, include_links=False, output_format="markdown"`. `--ablate-links`
measures the cost rather than asserting it.

## `select_main_content`: helps on hard pages, and destroys CJK ones

`main-content` is `select_main_content(strip_landmarks(blocks))` — the composition the
selector was tuned as. Against `landmarks`:

| column | landmarks | main-content | delta |
|---|---|---|---|
| `overall` | 0.4804 | **0.5116** | **+0.031** |
| `text_edit` | 0.5613 | **0.6270** | **+0.066** |
| `table_edit` | 0.2816 | **0.3154** | +0.034 |
| `formula_edit` | 0.2764 | 0.2843 | +0.008 |
| `table_TEDS` | 0.5057 | 0.4998 | −0.006 |
| `code_edit` | **0.8168** | 0.6904 | **−0.126** |

A second win is hidden in the N row rather than the means: `table_edit`/`table_TEDS` are
scored over **149 pages for `raw`, 147 for `landmarks` and 112 for `main-content`**. N can only
fall if the prediction stopped emitting a table on a page where the ground truth never had
one, so the selector removed **37 pages' worth of engine-invented tables** — nav grids, layout
tables, spec rails — without being credited for it in any column mean.

**Net positive, and much larger than the +0.031 headline suggests once sliced.** It is worth
+0.064 on `mid`, +0.057 on `hard` and +0.052 on formula-bearing pages. It moves `prose only`
by +0.003, i.e. not at all. And it is **−0.039 on `simple`** — the one slice where it goes
backwards, and the one that most resembles the article pages it was tuned on.

That regression is not the selector failing on its home turf. It is the CJK bug below,
concentrated:

```
simple   collapses  22/163 (13.5%)   of which CJK: 19
mid      collapses  12/218 ( 5.5%)   of which CJK: 8
hard     collapses  10/164 ( 6.1%)   of which CJK: 4
```

`simple` collapses at **2.5x the rate of `mid` and `hard`**, and 19 of its 22 collapses are
CJK pages. The annotators' "simple" is short single-article pages, and this corpus draws a lot
of those from Chinese government and news portals. Fix the word count and the `simple`
regression should go with it — untested, but that is where the evidence points.

The gain is nothing like the Zyte figure (F1 0.647 → 0.8695), and the two are not in conflict.
Zyte is 181 news and blog article pages. This corpus is forums, product pages, Q&A threads,
CNN transcripts, terms-of-use pages, government notices and a Chinese web novel. Tuned on
articles, it transfers partially.

The selector engages on **523 of 545 pages (96%)** and brings the median length ratio from
1.63x the ground truth to **0.99x** — dead on. But that median hides a bimodal failure:

```
COLLAPSES (kept <25% of ground-truth length while landmarks kept >=50%): 44/545 (8.1%)
  mc/gt=0.003 lm/gt=  1.01     73 -> 1    blocks  http://smccpit.cn/ztShow.Asp?ArticleID=149&ClassID=7
  mc/gt=0.005 lm/gt=  1.03    435 -> 1    blocks  https://www.theorychina.org.cn/c/2024-05-05/1499615.shtml
  mc/gt=0.011 lm/gt=  1.04      6 -> 1    blocks  http://guoxue.whu.edu.cn/index.php/teacher/show/id/167
  mc/gt=0.015 lm/gt=  1.04     58 -> 5    blocks  http://www.bibmath.net/forums/viewtopic.php?pid=62876
  mc/gt=0.015 lm/gt=  0.82    216 -> 1    blocks  http://gpls.cns.umass.edu/nsb/alumns/ms
  mc/gt=0.018 lm/gt=  2.02    143 -> 1    blocks  https://magazine.tabelog.com/articles/373020
  mc/gt=0.018 lm/gt=  1.00     31 -> 1    blocks  http://sjgswj.lishui.gov.cn/art/2024/10/1/art_1229677813_588
  mc/gt=0.019 lm/gt=  1.36     79 -> 1    blocks  http://www.pinhuba.com/health/101545.htm
```

On 44 pages the selector threw away a **correct** extraction — `lm/gt` is already near 1.0 —
and returned a single block. Look at the hosts.

### The mechanism: `\S+` cannot count CJK words

```
collapsed pages: 44   CJK-majority (>15% CJK chars in ground truth): 70%
other pages:     501   CJK-majority:  9%
median CJK share  collapsed 0.769   other 0.000
```

`main_content.py` scores every block in **whitespace-delimited words**:

```python
_WORD: Final[re.Pattern[str]] = re.compile(r"\S+")
...
free = words * (1.0 - link_density(block))
return free - config.block_cost          # block_cost = 13.0
```

Chinese and Japanese do not delimit words with whitespace, so an entire CJK paragraph counts
as **one or two "words"** and lands at roughly `1 - 13.0 = -12` — the same value as a nav
link. Every block on the page is negative, Kadane returns the single least-negative one, and
the article is gone. The tuning constant `block_cost = 13.0` was swept on Zyte, which is
entirely English.

`min_run_share = 0.02` is supposed to be the fail-open guard for exactly this, but at 2% of
document *words* — themselves miscounted by the same regex — it never fires. A selection
keeping 0.3% of the page's characters passed it.

This is a defect in `main_content.py`, not in the benchmark. Two fixes suggest themselves and
neither is measured here: count CJK codepoints as words (roughly, `len(re.findall(r'\S+', t))
+ cjk_chars / 1.5`), and raise `min_run_share` or express the guard in characters. **44 of 545
pages is 8% of this corpus and a much larger share of the non-English web.**

### The `code_edit` regression is a different 13 pages, and it is English

Tempting to blame the collapses for the −0.126, and wrong. Differencing the two cached score
files page by page: of the 90 pages scored on `code_edit` by both variants, **13 lose more
than 0.2 and none gain more than 0.2**, and those 13 account for **99% of the total drop**.
Eight of them go to 0.000 — the code is gone, not degraded:

```
  -1.000  https://stackoverflow.com/questions/21784641
  -1.000  http://rosalind.info/problems/suggested/423/
  -1.000  https://rosalind.info/problems/perm/
  -1.000  http://www.orafaq.com/wiki/Controlfile
  -1.000  https://packagist.org/packages/flarum-lang/icelandic
  -1.000  https://docs.gtk.org/gdk4/enum.CrossingMode.html
  -1.000  https://bbs.nanshengbbs.top/detail/171
  -0.993  http://demo.designwall.com/dwqa/question/a-few-quick-pre-sale-question
```

These are English developer documentation and Q&A, not the CJK portals above; the two failure
sets are essentially disjoint, and `overall` on code-bearing pages actually *rose* 0.6266 →
0.6386. The mechanism is different: on a docs page the code sample sits outside the densest
contiguous prose run, so Kadane's boundary cuts it off. That is the `structural_credit = 0.5`
knob failing to buy a `<pre>` its place in the run — a separate, and separately fixable,
problem from the word count.

## What this benchmark cannot see

```
  parse failures: 0; parsed to zero blocks: 0
  reading_order_method: {'dom-fallback': 542, 'single-block': 3}
  distinct hosts: 395 over 545 pages; 7 host(s) reach the 6-page threshold
```

Cached static HTML, no network, one page at a time. That switches off two of the three things
this engine does that a single-pass DOM extractor does not:

* **Geometric reading order is never exercised.** It needs a browser render for box geometry.
  `dom-fallback` on 542 pages and `single-block` on 3 — **zero** geometric orderings. Whatever
  `dom/reading_order.py` is worth, none of it is in the numbers above.
* **Cross-page chrome detection is structurally unavailable.** It needs six or more pages from
  one site; the 545 are spread over 395 hosts and only 7 reach that threshold. The engine's
  boilerplate removal here is `strip_landmarks` alone, which is why `landmarks` is the honest
  single-page baseline and `raw` is below it.

A third gap is the corpus's, not the harness's: annotators labelled **code on 127 pages but
`code_edit` scores 91**, and **table on 179 but `table_edit` scores 149**. The splitters are
regex and BeautifulSoup over Markdown and do not agree with the annotators. `code_edit
0.8168` is a mean over 91 pages, not over every code-bearing page in the subset.

## Honest read

**The headline is not `overall`.** At 0.5116 the engine sits between resiliparse (0.5081) and
trafilatura (0.5695) on a column dominated by whole-document text similarity, which is a
restatement of what `benchmark/article_extraction` already found: the engine keeps chrome and
is punished for it. Nothing new.

What is new, and what this corpus was the only way to measure:

1. **`code_edit` 0.8168 against trafilatura's 0.3278 and resiliparse's 0.0422.** Fenced code
   survives this engine substantially intact. The sibling benchmarks score that as a
   *precision loss* because jusText drops `<pre>` and trafilatura collapses newlines inside
   it, so this is the first measurement in the tree that credits it.
2. **`table_TEDS` 0.5057 against 0.2537 and 0.0000** — table *structure*, not just cell text,
   scored by tree edit distance. `benchmark/wcxb`'s `\w+` bag is incapable of seeing this.
3. **On code-, table- and formula-bearing pages the engine beats trafilatura outright**
   (0.6386/0.4402/0.5195 vs 0.5745/0.4187/0.5028) and loses only on prose-only pages, by
   0.29. The engine's weakness is precisely and only unstructured prose.
4. **A reproducible defect in `main_content.py`**: 8.1% of pages collapse to a single block,
   70% of them CJK, because `\S+` cannot count words in a language without spaces.

The single highest-leverage change remains the one `benchmark/article_extraction` identified —
main-content selection — and this run says it is real (+0.031 `overall`, +0.066 `text_edit`)
but not yet safe outside English. Fix the CJK word count before anyone ships
`select_main_content` as a default.

## Runner notes

* **The metric is imported, never reimplemented.** `MetricCalculator` comes out of the clone.
  Importing `webmainbench` naively fails — its package `__init__` pulls the extractor registry,
  which imports trafilatura, resiliparse, magic_html and torch — so `load_calculator` registers
  a stub parent with the right `__path__`. Licence chain inherited: apted (MIT), rapidfuzz
  (MIT), beautifulsoup4 (MIT), jieba (MIT). Deliberately **not** IBM's PubTabNet `TEDS.py`
  (NOASSERTION) and **not** `table-recognition-metric` (pulls GPL-2.0 `Levenshtein`). All are
  `bench`-group deps; the engine's runtime dependencies are untouched.
* **`openai` is stubbed, and the stub raises.** `base_content_splitter` imports it at module
  level but constructs a client only under `use_llm and llm_base_url and llm_api_key`. Rather
  than add an LLM SDK to a deliberately offline benchmark, the stub stands in and raises if
  anything ever reaches for it — so "offline" is checkable rather than asserted. Passing
  `use_llm: False` explicitly also stops `enhance_with_llm` seeding the clone's `.cache/` with
  files a later run *with* a key would read back as genuine LLM output.
* **Scoring has a 90-second per-page wall-clock budget**, because APTED is superlinear and one
  ground-truth "table" (`hcqyfuwu.com/261.html`) parses to a 24,216-node tree. The metric's own
  `_tree_edit_distance` already intends a fallback for this — its docstring names "excessive
  nesting" — but keys it on an exception APTED never raises. No page tripped the budget on this
  run. **Pages that do trip it are excluded from every system's columns or from none**, decided
  after all systems have run: an earlier version dropped them per system, which both raised the
  mean and made the table load-dependent (the `main-content` row read 0.3396 and 0.3315 on
  back-to-back invocations of identical code over identical pages).
* **`--resume` and `--scores-dir`.** Each system's per-page scores are written the moment it
  finishes. A full `--calibrate` run is six systems over 545 pages and the report prints only at
  the end; without this, dying on the last system loses all six.
* **`--rouge`** scores the full 7,809 file on the corpus's *other* protocol (ROUGE-N, N=5,
  jieba) against `convert_main_content`. Different file, different field, different metric,
  never averaged with the above — and still not identical to the paper's pipeline, which
  normalises every extractor through `html2text` first.
