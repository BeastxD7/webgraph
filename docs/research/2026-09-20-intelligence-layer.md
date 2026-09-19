# The intelligence layer: where a model would make parsing better, and where it would not

Owner's question (20 Sep 2026): now that the parser is at parity with Firecrawl, should
we add an intelligence layer -- a model in the SDK (`llm=True, provider, model, api_key`)
that describes images when the model can see, decides things between parsing steps, and
makes extraction "robust and very high quality"? What would make the parser the best in
the world?

This is the analysis: what our own measurements say about where the remaining losses
are, what the alternatives do with models, and a ranked proposal with the experiments
that would decide each item. Nothing here is built yet.

## The rule that has to survive

**Parsing stays deterministic.** No model, no key, the same output for the same page every
time, and every word in the Markdown is a word that was on the page. That is what the
fidelity board measures (recall 0.998 mean over 22 sites; the random-web median 0.98) and
it is the promise the product makes ("the honest web reader"). A model in the parse loop
would break it three ways at once: cost per page, seconds per page, and the chance that
what comes out was never on the page.

So the layer is **optional, cited and budgeted**: off unless a `llm` is given; everything
it produces is marked as the model's and carries the quote or the image it came from;
every call counts against a budget the caller set. WebGraph (the knowledge graph and Ask)
already works this way -- bring-your-own key, a verbatim quote for every node and edge,
`max_usd` / `max_input_tokens` -- and is the first citizen of the layer, not a second
system beside it.

## Where the losses actually are

Every number below is from a board in this repository. The point of the table: most of
what we still lose, no model can recover, and the parts a model *can* help with are
specific and measurable.

| Loss | Measured | Can a model help? |
|---|---|---|
| Walls (Cloudflare, Akamai, "verify you are human") | 138 of 1,000 Firecrawl-dataset pages; 12 of 300 random pages | **No.** Policy: we do not disguise. The only honest levers are bring-your-own-HTML and the parked scripted-login PR. |
| Dead links, 404/410 | 79 of 1,000 | No. |
| Locale (the truth is Japanese, the page served in English) | 1 of 20 misses | No -- and the model would only guess. |
| Reading order | 0.9931 geometric vs 0.9726 source order; 0.939 on the pairs that disagree | **No.** Geometry beats any model here: it is exact, free, and instant. The backdrop rule (#167) came from measurement, not judgement. |
| Content-only boundary on product / listing pages | WCXB product 0.635, listing 0.720, collection 0.705 (article 0.944) | **Yes, plausibly.** Two heuristic sweeps found nothing; the shape ("which of these blocks is the product, which is the site selling it") is a judgement. Measurable today on WCXB dev. |
| Page-type router | 0.858 accuracy, 5-fold grouped; `ROUTER_MIN_CONFIDENCE = 0.5` | **Yes, cheaply.** A model asked only when the classifier is unsure. Measurable on the same 2,008 pages. |
| Images without alt text | lakshx.in: 23 of 23 images carry no alt (all decorative); the fidelity board counts images but cannot score their meaning | **Yes -- vision.** The one thing no DOM parser can do: say what a picture says. Needs its own oracle. |
| Canvas, charts, infographics | a Site Report finding (`canvas_content`) exists; no board | **Yes -- vision.** Same as above. |
| PDFs | 15 of 1,000 dataset pages; owner skipped the reader | Vision OCR would do it; parked by the owner. |
| The random-web tail (~10% of pages under 0.9 recall) | being re-scored tonight | Unknown until triaged; the last two triages found engine rules, not model gaps. |

The largest bucket a model *could* move is the content-only boundary on the hard page
types -- and only in content-only mode, which is no longer the default. The most
*visible* gap is images: a page whose meaning is in a chart, a screenshot or a product
photo comes out as `![](…)` and the reader's LLM sees nothing.

## What the others do with models

- **Jina Reader** captions images with a small VLM when asked (`X-With-Generated-Alt`),
  writing `![Image 3: a bar chart of …](src)` into the Markdown ([Jina Reader](https://jina.ai/en-US/reader/),
  [announcement](https://x.com/JinaAI_/status/1780094402071023926)). Off by default, a
  header turns it on. The right shape: the parser is unchanged, the alt is added.
- **Firecrawl** runs the model *after* parsing -- `/extract` takes a JSON schema or a
  prompt over the page's Markdown ([LLM Extract](https://www.firecrawl.dev/blog/launch-week-i-day-6-llm-extract),
  [Extract docs](https://docs.firecrawl.dev/v0/features/extract)); its 2026 "Agent"
  browses and extracts across pages without URLs. Its parser (`onlyMainContent`) is
  heuristic, like ours. No model in the parse loop.
- **crawl4ai** offers LLM extraction strategies over the cleaned HTML; same shape.
- **VLM page-to-Markdown** (Qwen3-VL, InternVL3, jina-vlm, the frontier APIs) reads a
  screenshot and writes Markdown in one pass. It is the right tool for scanned documents
  and defeats rule-based OCR there ([2026 field guide](https://www.johnsnowlabs.com/a-2026-field-guide-to-visual-document-processing/),
  [ranked VLMs](https://mixpeek.com/curated-lists/best-vision-language-models)). For a
  web page it is the wrong tool: it cannot see links, hidden tabs, collapsed panels or
  anything below the fold without scrolling, it drops and invents words at a rate no
  fidelity board would accept, it costs seconds and cents per page, and VLMs still fail at
  counting and dense layouts ([counting failures](https://arxiv.org/pdf/2510.04401)).

Nobody credible puts a model *inside* the parser. The pattern that works is: parse
deterministically, then let a model **add** (captions, structure) or **judge** (which
blocks are the content) -- never rewrite.

## The proposal, ranked by measured value against cost

### 1. Image descriptions when the model can see (vision) -- adds what no parser can

For every content image the parser kept (it already drops icons, spacers, tracking pixels
and decorative backgrounds), when the model has vision: ask for a one-sentence
description, write it as the alt, and mark it as the model's:

```
![Bar chart: monthly active users, Jan–Jun 2026, rising from 12k to 41k (described)](https://…/chart.png)
```

Rules: never replace an alt the site wrote (the author's words win); skip images under a
size threshold and known-decorative shapes; cache by image content hash so a crawl
describes each picture once; a per-page and per-run image budget; the description is
prefixed or suffixed so a reader can tell the site's alt from ours. Charts and screenshots
get a longer form on request (`describe="detail"`): the numbers a chart shows, the text in
a screenshot -- that is where the value is.

Measurement: there is no board for this. Build one: 50 images from the random-web sample
with a hand-written description each, scored by a rubric (does it name the subject, the
text in the image, the numbers). It is the only item here that needs a new oracle.

### 2. Structured extraction with quotes -- the feature people pay Firecrawl for

`page.extract(schema, llm=…)`: a JSON schema in, JSON out, **each field with the quote
that supports it** and `null` (never a guess) when the page does not say. Reuses the KG
extractor's provider code and its quote-or-nothing rule. Over the whole-page Markdown by
default, so a price in the buy box is found even though content-only would drop it.

Measurement: Firecrawl's public dataset carries a truth snippet per page (1,000 rows,
already in the scratchpad harness); a 30-page hand-labelled schema set for
price/title/date/author fields is a day's work.

### 3. A judge for the content-only boundary on hard pages -- the one measured gap

Only when the router says product / listing / collection, or the boundary step fails
open: show the model the block list with the parser's labels (region, in_main, page type,
what the boundary step kept) and ask for the first and last content block. The model
never sees or writes text; it picks indices. Deterministic fallback when it declines or
disagrees with itself.

Measurement: WCXB dev, product / listing / collection rows (1,497 pages, static HTML,
needs a key: ~$5–15 per sweep at Sonnet prices). This is the experiment to run first,
because it is the only one with a number already waiting: 0.635 on product. If it does
not move by more than the noise, the item is dropped.

### 4. The router's second opinion -- cheap, bounded

When the GBDT's confidence is under 0.5 (a small share of pages), ask the model for the
page type from the first ~60 blocks. Measurable on the same 2,008 pages; expected gain a
few points of accuracy on the unsure slice; cost only on that slice.

### 5. A self-check for the tail ("high-quality mode") -- expensive, for when it matters

After extraction, a vision model compares the page's screenshot with our Markdown and
lists regions of visible text we do not have; the parser re-measures with those regions
as hints (the click and reveal steps already accept targets). One screenshot and a few
thousand tokens per page, so opt-in per run. Measurable on the random-web tail as soon as
tonight's re-score says what the tail is.

### What not to do

- No model in reading order, block extraction or the union. Geometry and the rules win
  on every board, deterministically, at no cost.
- No rewriting of text the page said -- no "cleaning", no summarising in place. A
  summary is a separate, cited output (`page.summary(llm=…)`), never the Markdown.
- No screenshot-to-Markdown as the parser. Scanned documents only, if PDFs ever come back.
- No model choosing the fetch strategy; the root analysis measures that already.

## The interface

One object, everywhere:

```python
from webgraph import resolve_page, stream_site, Intelligence

llm = Intelligence(
    provider="anthropic",           # "openai-compatible" | "anthropic" | "gemini" | "local"
    model="claude-sonnet-5",
    api_key="…",                    # or from the environment; never traced or logged
    vision="auto",                  # "auto" asks the model; True/False overrides
    budget=Budget(max_usd=2.0, max_images=200, max_input_tokens=400_000),
)

page = resolve_page(url)                          # unchanged: deterministic
page = resolve_page(url, llm=llm)                 # + described images, if the model sees
page.extract({"price": "number", "sizes": ["string"]}, llm=llm)
page.summary(llm=llm)
stream_site(url, config=SiteConfig(...), llm=llm) # + knowledge graph, Ask, the boundary judge
```

`llm=None` changes nothing. Everything the layer adds is marked (`(described)` in an alt,
`"source": "model"` beside a field, the quote beside every fact) and every call is counted
against the budget and reported in the run's provenance. The API takes the same object as
`"llm": {…}`; the web UI keeps the key in the browser, as WebGraph does now. The KG's own
provider settings fold into `Intelligence`, so there is one way to say "which model".

## Order of work

1. **Experiment first, with the owner's key**: the boundary judge on WCXB dev (item 3)
   and the router second opinion (item 4) -- a day, and both come back with a number.
2. `Intelligence` + budget + provenance, folding in the KG's provider code.
3. Image descriptions (item 1) with its 50-image oracle.
4. Structured extraction with quotes (item 2).
5. The self-check (item 5) once the random-web tail says what it is.

What this needs from the owner: a key for one provider to run the experiments, and the
decision that the parser stays deterministic -- the layer adds and judges; it never
rewrites.
