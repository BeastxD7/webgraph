# Site Graph — PRD v3

**Supersedes:** v2 (which superseded v1)
**What's new:** site-architecture profiling, multimodal extraction (images, charts,
video), revised vision, and a revised position on the accuracy ambition.

---

## 0. On the goal: "world's most accurate extractor"

I want to separate two things that sound the same and are not.

**Benchmark SOTA is a research output, not a product.** Topping SWDE means writing a
paper. AXE reached 88.10% zero-shot F1 with a research team, compute budget, and
publication as the deliverable. Competing there is a full-time job with no revenue,
and it is orthogonal to your actual constraint, which is three paying users while
holding down employment. A leaderboard entry does not sell a subscription, and no
competitive-intelligence buyer has ever asked for an F1 score.

**But the underlying instinct is right, just aimed too wide.** "Most accurate on any
website" is unwinnable and unnecessary. "Most accurate in the world at extracting
plan/price/feature facts from B2B SaaS marketing sites" is winnable, defensible, and
is exactly what a customer notices. Nobody holds that title because nobody has
bothered to build a gold set for it. You can, in a weekend.

So: **build your own benchmark for your own vertical, publish it, and beat everyone
on it.** That gets you the credibility of the ambition, the marketing asset, the
distribution you currently lack, and it costs weeks rather than years. If you later
want a leaderboard entry, the pipeline will be there.

The rest of this document is built on that framing. Every technique below is
included because it moves the vertical number, not the general one.

---

## 1. Revised vision

> A website is a database that has been flattened into pages, and increasingly into
> pixels — pricing in a rendered table, a comparison in an infographic, a capability
> claim only spoken in a demo video. Site Graph un-flattens all of it. It profiles
> how a site is built, routes each piece of content to the cheapest extractor that
> can read it correctly, and maintains a typed, temporal entity graph that is
> queryable, diffable across time, and comparable across competitors.

The operative phrase is **cheapest extractor that can read it correctly**. That is
the engineering thesis and the reason multimodal is a routing problem, not a
"send everything to a VLM" problem.

---

## 2. Site architecture profiling (new — Stage 0)

Before crawling, profile the site. The stack determines the extraction strategy, and
getting this wrong is where most naive crawlers lose accuracy.

### 2.1 How

Use the MIT-licensed community fingerprint rulesets (`enthec/webappanalyzer`,
`tunetheweb/wappalyzer`) rather than a paid API. They cover 6,000+ technologies
across 100+ categories. A single HTTP fetch, analyzing HTML, scripts, meta tags, and
response headers, resolves the stack for roughly 95% of sites; the remaining ~5%
need a Playwright pass because the signal only appears after client-side JS executes.

**Known limitation:** fingerprint libraries lag new frameworks. Astro reportedly took
about a year after release to become reliably detectable. Always fall back to
behavioral probing — if fingerprinting is inconclusive, render and observe.

### 2.2 What the profile drives

| Detected stack | Crawl strategy | Why |
|---|---|---|
| WordPress / Drupal / Ghost | Try the REST/JSON API first (`/wp-json/wp/v2/...`); templates are highly regular | Structured data without parsing HTML at all — cheapest possible path |
| Shopify / WooCommerce / BigCommerce | Product JSON endpoints; structured data markup | Same |
| Next.js / Nuxt / Remix | Look for embedded hydration payloads (`__NEXT_DATA__`, RSC flight data) | The page's own data layer is cleaner than its rendered DOM |
| Astro / Hugo / Jekyll / 11ty | Static HTML, no rendering needed | Fastest path; DOM pruning alone suffices |
| React / Vue / Angular SPA (no SSR) | Playwright render, wait for hydration, then prune | DOM is empty before JS runs |
| Webflow / Wix / Squarespace | Highly templated; selector induction generalizes exceptionally well across pages | One induction covers the whole site |
| Canvas-heavy / custom rendering | **Vision path required** | DOM analysis cannot capture HTML5 `<canvas>` content at all |

That last row is the real reason vision is not optional. DOM-based analysis
provably misses `<canvas>` elements, and computer-vision approaches struggle with
variable element detection — neither modality is sufficient alone.

### 2.3 Content census (also Stage 0)

Alongside the stack, produce a per-site census: page count, template count, and
counts of images, `<canvas>`, `<video>`, `<iframe>` embeds, tables, and SVG. This is
cheap (it's DOM counting) and it drives two things: the cost estimate shown to the
user before they add a site, and the decision about whether multimodal extraction is
worth running at all on that site.

---

## 3. Multimodal extraction

### 3.1 The routing principle

Every modality gets a **cheap path first, escalate on evidence**. This is not
cost-cutting at the expense of accuracy — for several modalities the cheap path is
also *more* accurate, because it avoids the failure modes of visual inference.

```
Asset encountered
   │
   ├── has alt text / aria-label / figcaption / adjacent caption?
   │        └── extract text → does it satisfy the schema field? → DONE, no model
   │
   ├── is it decorative? (hero image, icon, avatar, background)
   │        └── SKIP entirely — classify by size, position, filename, alt emptiness
   │
   ├── is it text-bearing? (screenshot, infographic, comparison table image)
   │        └── OCR first → if OCR yields schema-relevant text → DONE
   │        └── else → VLM description
   │
   ├── is it a chart? → chart pipeline (§3.3)
   │
   └── is it video? → video pipeline (§3.4)
```

### 3.2 Images

**Evidence for caution.** VLMs are consistently weaker on images than on text. In a
controlled medical exam study the best model answered 89.5% of text questions
correctly but only 66.0% of image-based ones. On structure extraction from images,
Image2Struct found best scores varying enormously by domain — 0.402 on sheet music
versus 0.830 on LaTeX — so "VLMs can read images" is far too coarse a claim to build
on.

**Evidence they work well enough on web screenshots specifically.** XBIDetective
evaluated a fine-tuned VLM across 1,052 websites and identified cross-browser
discrepancies at 79% accuracy, dynamic elements at 84%, and advertisements at 85%.
Good enough for classification and description; not good enough to be the sole source
of a price.

**Design rule:** a fact extracted from an image never overwrites a fact extracted
from text. It fills a gap, and it is stored with lower `confidence` and a
`modality: image` provenance tag. The bitemporal store already carries confidence per
fact, so this costs nothing structurally.

### 3.3 Charts — the highest-value and most dangerous modality

**The cheap path recovers most of the value.** On ChartQA, Claude 3.7 Sonnet scored
74.1% using only text extracted from the chart (titles, axis labels, annotated
values, legend text), versus 87.4% with the actual image. Only about 13 points of
that task is genuinely visual reasoning. So: **extract chart text and any underlying
data first** — from SVG elements, `<table>` fallbacks, `data-*` attributes, chart
library JSON configs (Chart.js, Highcharts, Recharts all leave the series data in the
page), and OCR. Most web charts are not raster images at all.

**When you must go visual, know the error profile.** In chart-to-table extraction,
errors are dominated by **Value Errors (19–40%)** and **Missing datapoints (22–42%)**,
while label errors are negligible (≤1.4%). Even GPT-5.1 is bottlenecked at 22.8%
value errors and over-generates datapoints (Extra 10.1%). Chart type matters
enormously: Llama 4 Scout scored 48.39 on grouped bars but collapsed to 13.94 on area
charts.

**Mitigation — self-ensembling.** Sample the same chart several times, align the
candidate tables, take **per-cell medians** over numeric values, use convergence
detection to stop sampling once the table stabilizes, and derive an **uncertainty
estimate from dispersion across samples**. Reported gains are 0.8–8.1 percentage
points, and the uncertainty estimate is arguably more valuable than the accuracy gain
— it tells you which extracted numbers to suppress rather than show.

**Model choice:** don't reach for chart-specialist models by default. In one
evaluation all six general VLMs beat the specialist DePlot regardless of provider or
size, with even the cheapest (Claude Haiku 4.5 at 88.5%) exceeding DePlot's 70.5% by
18 points. Chart-specialized models also produce many more spurious datapoints when
applied out of distribution.

**Hard rule:** any numeric fact whose only source is visual chart inference is
flagged `unverified` in the graph and is **excluded from change alerts**. A phantom
alert caused by a VLM misreading a bar height twice in a row is exactly the alert
fatigue that makes 40% of CI tool users churn.

### 3.4 Video

**The token arithmetic is brutal.** One minute of 30fps video at 224×224 with
ViT-B/16 patches is roughly 352K visual tokens before any text or audio; an hour is
around 21M tokens before compression. Even with sensible defaults, a ten-minute video
runs about 174,000 tokens — roughly five cents on a fast 2026 model, per video, per
re-check.

**So: transcript-first, always.**

1. **Audio transcript.** Batch speech-to-text is cheap — around $0.15–0.21 per hour
   on current async APIs, and Whisper remains a cost-effective default for batch
   work. For a product demo where the value proposition is spoken, this is 90% of
   the signal for ~1% of the cost.
2. **Scene-aware frame sampling, not uniform.** Detect scene boundaries (PySceneDetect
   / ffmpeg), then take 1–4 frames per scene depending on duration. For talking-head
   and screen-recording content — which is what B2B SaaS demo videos are — one frame
   per minute has been shown sufficient to reconstruct a 17-minute video's full
   storyline including on-screen text.
3. **OCR the sampled frames with de-duplication.** This is where UI walkthroughs and
   silent demos hide their information; transcripts are weak "when the answer is on
   screen but never spoken."
4. **Only then** send transcript excerpts + selected frames + OCR lines to a VLM for
   a scene-level summary, and condense scenes into a global summary.

**Never put a VLM in the per-frame path.** Budget roughly 150ms or more per sampled
frame and design around sampling plus a queue.

**Change detection on video:** hash the transcript, not the pixels. A re-encoded or
re-hosted video with an identical transcript is not a change.

### 3.5 What this means for the schema

Add to every fact:

```
modality       : text | dom-json | ocr | image | chart | video-transcript | video-frame
confidence     : float
verification   : verified | unverified          # unverified excluded from alerts
extractor      : selector | llm | vlm | ensemble
```

---

## 4. The honest cost warning

Section 6 of v2 established that this product lives or dies on steady-state cost per
site. **Multimodal extraction is the single largest threat to that model.** A site
with 40 pages, 200 images, 12 charts and 6 demo videos, processed naively on every
re-crawl, costs more than the subscription.

The three defenses, in order of impact:

1. **The census gate.** After the Stage 0 census, estimate multimodal cost and only
   enable those paths when the census says there's meaningful non-text content.
2. **Immutable-asset caching.** Images and videos change far less often than pages.
   Hash the asset URL and bytes; a re-crawl re-processes an asset only if the bytes
   changed. This should make steady-state multimodal cost approach zero.
3. **Cheap-path-first routing (§3.1).** Most assets never reach a model.

---

## 5. Revised milestones

M0–M6 from v2 are unchanged and remain the path to revenue. Multimodal is **Phase 2**,
gated on evidence, not on enthusiasm:

| # | Weeks | Deliverable | Gate |
|---|---|---|---|
| M0.5 | +2 days | Stage 0 profiler: tech fingerprinting + content census | Correctly identifies stack and asset counts on the 10 gold sites |
| M0.6 | +1 day | **Modality audit** — of the facts in your gold set, what % are available *only* in a non-text modality? | **This number decides Phase 2.** |
| M7 | Phase 2 | Image + chart pipeline | Only if the modality audit says >15% |
| M8 | Phase 2 | Video pipeline | Only if demo-video claims turn out to matter to users |

**My honest expectation on the modality audit:** for B2B SaaS marketing sites, the
answer will be low — probably under 10%. Pricing lives in HTML tables. Feature
matrices are HTML. Compliance badges have alt text. The hero video is marketing
copy, not fact. If that's what you find, **building the multimodal pipeline before
launch would be the most expensive mistake available to you** — months of work, a
broken cost model, and no additional facts.

That is not an argument against building it. It is an argument for building it when
the audit says it's needed, or when you move to a vertical where it obviously is
(hardware spec sheets, real estate listings, scientific publishers, e-commerce
catalogs — all image- and chart-heavy in ways SaaS pricing pages are not).

Design it now. That's what this document is. Build it on evidence.

---

## 6. The vertical benchmark (replaces the SOTA ambition)

Concrete plan, roughly three weekends:

1. **Corpus.** 30 B2B SaaS sites, snapshotted (store the HTML — sites change).
2. **Gold labels.** Every Plan, Price, Feature, Integration, Certification, Region,
   hand-labelled with source URL and span. This is the asset. It's tedious and it is
   the moat.
3. **Metrics.** Value accuracy and perfect-page rate (per v2 §4), plus per-modality
   breakdown once Phase 2 exists.
4. **Baselines.** Run Firecrawl's extract endpoint, Crawl4AI + schema, Diffbot's free
   tier, and a plain frontier-model call over raw HTML. Publish the table.
5. **Publish.** Repo, leaderboard page, a writeup. Invite others to submit.

This does three jobs at once: it's your development harness, it's the credibility
claim your ambition is reaching for, and it's the content-marketing asset that
solves the distribution problem I flagged in v1 as your weakest point. A public
benchmark that vendors want to appear on is a far better acquisition channel than
anything you could write about your own product.

---

## 7. Open decisions (updated)

1. Graphiti library vs borrowing the bitemporal model (from v2)
2. Extraction model: hosted vs Qwen3-4B LoRA at M2b (from v2)
3. Vertical confirmation (from v2) — **now also determines whether multimodal is
   core or peripheral.** A vision-heavy vertical would invert the priorities in §5.
4. Contract check (from v2, still gating)
5. **New:** does the public benchmark come before or after launch? Before gives you
   distribution and a dev harness; after keeps M6 closer.

---

## Appendix — sources for this pass

**Site profiling:** enthec/webappanalyzer and tunetheweb/wappalyzer (MIT rulesets);
Apify tech-detection actor docs (Mar–Jun 2026); Wappalyzer/BuiltWith comparison
guide (Aug 2026, fingerprint-lag observation).

**Images:** XBIDetective — arXiv 2512.15804 (1,052 sites, fine-tuned VLM);
Image2Struct — arXiv 2410.22456 (Stanford HELM); JNMBE VLM study (PMC12559035,
text-vs-image accuracy gap); VisualWebBench, WebSRC, WebMMU as the relevant
benchmark family.

**Charts:** ChartMuseum — arXiv 2505.13444 (text-only vs image ChartQA);
Self-Ensembling VLMs for Chart Data Extraction — arXiv 2605.27298 (error taxonomy,
per-cell median ensembling); PlotPick (VLMs vs DePlot); ChartQA — arXiv 2203.10244.

**Video:** "Efficient Video Intelligence in 2026" (token arithmetic); Video VLMs 2026
frame-sampling analysis; local frame-sampling benchmark (Jul 2026, 1 frame/min
sufficiency); AssemblyAI pricing (Jul 2026); scene-aware pipeline writeup (Apr 2026).

*Several sources here are engineering blogs and vendor pages rather than
peer-reviewed work, and are marked as such where the number matters. Benchmark
figures come from different datasets under different protocols and do not compose.*
