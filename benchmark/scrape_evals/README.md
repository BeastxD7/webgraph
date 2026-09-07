# scrape-evals

Firecrawl's own benchmark, published 2025-11-20 and withdrawn. This directory scores this
engine on it, against the artefacts that produced the published table.

## Getting the corpus

```bash
git clone --depth 1 https://github.com/martynasoxylabs/scrape-evals harness
uv run --package webgraph python benchmark/scrape_evals/run.py \
    --harness harness --cache /somewhere/with/2GB --noise --self-check
```

The first run fetches 1,000 live pages at 4 concurrent and caches every body, so re-scoring
is offline:

```bash
uv run --package webgraph python benchmark/scrape_evals/run.py \
    --harness harness --cache /somewhere/with/2GB --no-fetch --noise --self-check
```

## What survives and what does not

| Artefact | State |
| --- | --- |
| Blog post `firecrawl.dev/blog/introducing-scrape-evals` | **Gone.** 307 → `/blog`. Archived at `web.archive.org/web/20251213133157/…` |
| Repo `github.com/firecrawl/scrape-evals` | **Gone.** 404 |
| Dataset `huggingface.co/datasets/firecrawl/scrape-content-dataset-v1` | **Alive.** MIT, 1.8 MB, 1,000 rows |
| Harness, as a fork `github.com/martynasoxylabs/scrape-evals` | **Alive.** HEAD `a94764f3`, 2025-11-20 |
| The 13 engines' result files, in the fork's `runs/results/` | **Alive.** 13 files, ~147 bytes each |

Two checkable things were checked:

* the fork's vendored `datasets/1-0-0.csv` parses row-for-row identical to the HuggingFace
  copy (the byte diff is line endings), and
* its `runs/results/*_quality.json` reproduce the published table to the decimal —
  `firecrawl_api` reads `success_rate` 0.809, `avg_f1` 0.6758, printed as 80.9 and 0.68.

Not checkable: that the fork is byte-identical to the deleted original.

## The dataset has no HTML

1,000 rows of `id,url,truth_text,lie_text,error`. URLs and snippets only — the whole corpus
is 1.8 MB. Every score depends on fetching 1,000 live pages, ten months after the dataset
was cut (2025-10-21), and the card itself warns that "URLs may become unavailable". **A
number produced here is not a reproduction of Firecrawl's run**; it is a number about the
web on the day it ran. `run.py` caches every body so its own number is re-derivable.

1,000 URLs over 1,000 distinct hosts, so cross-page chrome detection — which needs six pages
from one site — is structurally unavailable, as on WCXB.

## The metric, as implemented

Imported from the fork, never reimplemented: `QualityAnalyzer.analyze_one` and `summarize`.

**Coverage** = `success_rate`: status 200–399, no error, non-empty content, `content_size > 0`,
and none of nine block-page needles present in the content.

**Quality (F1)** = `avg_f1`: per row, tokenise with `re.findall(r"\d+/\d+|[\w'-]+", …)`, slide
a window of exactly `len(truth_tokens)`, keep the best window's
`|window ∩ truth| / |truth|` (recall) and `|window ∩ truth| / |window|` (precision), take
their harmonic mean. Averaged over **all 1,000 rows**, so a failed fetch contributes 0.

Three things the blog does not say:

1. **`lie_text` never enters the score.** `window_scores` is called once, with `truth_words`.
   `lie_words` is computed at `quality_analyzer.py:44` and read at exactly one place, line 91,
   a blank-row guard. `lie_weight=4.0` is threaded from `run_eval.py:29` through
   `quality_suite.py:94` into the signature and never used in the body. **The published
   Quality column has no noise term.** `--noise` adds the missing measurement; nothing
   published is comparable to it.
2. **The metric is local.** One best window is scored, so boilerplate anywhere else on the
   page is free. Global precision — this engine's measured weakness everywhere else — is
   invisible here.
3. **Deleting interleaved tokens raises the score.** `a X b X c X d X` scores recall 0.5 where
   `a b c d` scores 1.0, so filtering chrome out of prose *helps*, the opposite of the usual
   direction.

## Two ceilings and one defect

* 135 rows have neither snippet → `success` forced to 0 → **Coverage ≤ 86.5%**.
* 150 rows have no `truth_text` tokens → `window_scores` returns `(0,0,0)` → **F1 ≤ 0.850**.
* `is_block_page` greps the **unstripped** submission, so raw HTML containing `cdn-cgi`,
  `cf-ray` or `challenge-platform` trips the `"cloudflare"` needle and fails Coverage even
  when the page loaded perfectly.

Firecrawl's 80.9 / 0.676 are 93.5% and 79.5% of what is attainable.

## What the published table actually compared

One line decides it: `analyze_one` runs `strip_markdown` **only if
`output.format == "markdown"`**. Of the thirteen adapters, `firecrawl_api.py` is the only one
that declares `markdown`. All twelve others declare `html` and submit raw HTML —
`content=html` from a response body (apify, scraperapi, scrapingbee, scrapy, rest),
`httpResponseBody` (zyte), `page.content()` (playwright, puppeteer), `driver.page_source`
(selenium). Three are worth naming:

* `crawl4ai_scraper.py` submits `result.html`. Crawl4AI's product is `result.markdown`; the
  harness takes the raw field and discards the extraction.
* `exa_api.py` asks for `text={"include_html_tags": True}` — it opts *in* to tags.
* `tavily_api.py` comments "prefer HTML" and takes `raw_content` over the markdown field it
  has already read.

Since the metric's precision term is `|window ∩ truth| / |window|`, every tag name, script
identifier and URL slug inside the winning window is an unmatched denominator term. Raw HTML
does not merely add noise to the page; it dilutes the winning window itself.

So the Quality column is **one extractor's cleaned Markdown against twelve raw HTML dumps**.
`run.py` measures this rather than asserting it, with two control variants that reproduce
both submission protocols on the same bytes: `html_asis` (the `rest_scraper` protocol) and
`md_as_markdown` (the `firecrawl_api` protocol).

## Variants

| Variant | Submitted as | What it is |
| --- | --- | --- |
| `raw` | `text` | `document.text`. The headline. |
| `landmarks` | `text` | `strip_landmarks()`. The shipped one-page default. |
| `prose` | `text` | PARAGRAPH/HEADING/LIST_ITEM/QUOTE only. |
| `md_as_markdown` | `markdown` | Markdown through their `strip_markdown`. Firecrawl's protocol. |
| `md_as_text` | `text` | Markdown *not* stripped. The link trap, measured. |
| `html_asis` | `html` | The raw response body. The other twelve engines' protocol. |

Coverage is per-variant, because `bool(output.content)` is part of the success predicate.

## Reading the comparison

**Coverage is not an extraction comparison.** Firecrawl's number includes `fire-engine`,
their closed hosted anti-bot browser. Seven of the thirteen rows (Firecrawl, Exa, Tavily,
ScraperAPI, Zyte, ScrapingBee, Apify) fetch through commercial proxy infrastructure. This
engine runs plain httpx from one IP with an identifiable bot UA. The only rows it can be read
against are the six that also run on the caller's own IP.

**Quality F1 is confounded by the format switch**, not by proxies — see above. The
`html_asis` and `md_as_markdown` rows quantify that confound directly.
