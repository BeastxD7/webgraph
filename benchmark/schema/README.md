# Auto-selected schemas: what they get right, and what they now decline

When the engine picks a schema on its own from the page type and fills it from the page's
structured data, the question that matters is not how many fields it fills. It is how many
of the values it reports are **wrong** — not missing, wrong. A missing field can be
escalated to a model or a selector. A wrong field is indistinguishable from a right one to
everything downstream, and it is still wrong after it has been written into a knowledge
graph and joined to something else.

## The result

869 WCXB dev pages that carry structured data, scored against human-annotated titles.
`routed` uses our own router's **out-of-fold** prediction, so no page was typed by a model
that had seen it. That row is what a user actually gets.

Two scorings, because they disagree about one specific thing and the disagreement matters:

| | | correct | **wrong** | missing |
|---|---|---|---|---|
| **lenient** | before: every payload, first key wins | 58.7% | **23.4%** | 18.0% |
| | after: gated, routed out of fold | **67.4%** | **13.6%** | 19.0% |
| **strict** | before | 44.2% | **37.9%** | 18.0% |
| | after: gated, routed out of fold | **49.8%** | **31.2%** | 19.0% |

**Better on both axes under both scorings**: more right answers *and* fewer wrong ones,
with coverage unchanged. That is the headline, and it is the only claim here that does not
need a caveat.

Lenient counts a value as correct when it is a prefix of the annotation or vice versa, which
forgives a title carrying a `| Site Name` suffix. Strict counts only exact matches. Run
both (`--strict`) before believing any source — the gap between the two rows is almost
entirely Open Graph titles with the site's name attached, and a source that looks strong
under one scoring and weak under the other is telling you something about its shape.

## What changed

**The page's own node, not the site's.** A product page from a WordPress shop ships
`Organization`, `WebSite`, `WebPage`, `BreadcrumbList` and `Product`, each with a `name`.
The old mapper matched them identically and the tie went to document order — so the answer
depended on which SEO plugin the shop installed. Yoast emits the subject node first; Rank
Math emits it last. Measured, `Organization` supplied the winning name on 46% of category
pages: `"IKEA"` for a page about shelving, `"Skullcandy"` for a page about headphones.

**Three tiers, each only filling what the one above left empty.** The node about the page,
then the page's own `WebPage` wrapper, then Open Graph. Open Graph is written for share
cards, so it never competes with a real answer — but 95% of article pages carry `og:title`
and 40% ship no article node at all, and on those the choice is Open Graph or nothing.
Every value taken from a lower tier says so in its provenance and carries reduced
confidence.

**Site names trimmed, but only when the page declares one.** `og:site_name` is what makes
`"What is Cloud Computing? | Google Cloud"` safe to shorten. Without it, trimming at a pipe
would mangle any headline that contains one.

## By page type, routed out of fold, lenient scoring

| page type | n | wrong before | wrong after | correct before | correct after |
|---|---|---|---|---|---|
| article | 437 | 16% | 13% | 81% | 81% |
| product | 86 | 36% | **16%** | 64% | **80%** |
| forum | 84 | 42% | **6%** | 49% | **81%** |
| collection | 57 | 65% | **26%** | 33% | **61%** |
| listing | 59 | 44% | **27%** | 53% | 54% |
| documentation | 45 | 7% | 2% | 18% | 24% |
| service | 101 | — | 9% | — | 19% |

**Forum and product are the clearest wins.** Forum: correct rises 49% → 81% while wrong
falls 42% → 6%, because what was being reported as a thread's title was usually one of its
replies — 212 `Comment` nodes across 91 pages. Product: 64% → 80% correct, 36% → 16% wrong,
because the shop's `Organization` stops answering for the product.

**Collection and listing still carry the highest wrong rates** (26–27%), and the reason is
structural rather than fixable here: 72–79% of those pages ship JSON-LD but only 16% ship a
node that is about the page. What answers on the rest is the page's own wrapper or its
share card, and on a category page those frequently name the shop. The DOM's repeat-group
detection, which the router already configures per page type, is the real source for these
and is not part of this measurement.

**Service reports no title, by design.** Every method measured — structured data, the DOM
`h1`, Open Graph — is about 50% wrong against the annotation, which reads as a disagreement
about what a marketing page's title *is* rather than a failure to find one. The service
schema answers what it can (`organizationName`, `telephone`, `address`) and declines the
rest, which is why its gold row is 100% missing. Its routed row is not, because the router
sometimes types a marketing page as an article or a product and those schemas do claim a
title — 19% of the time correctly, 9% of the time not. That 9% is the cost of routing
errors, stated rather than hidden.

## Reproducing

```
git clone https://github.com/Murrough-Foley/web-content-extraction-benchmark
uv run --package webgraph python benchmark/schema/run.py \
    --corpus <clone> --split dev --oof <oof.json> [--strict]
```

`--oof` takes the out-of-fold router predictions written by
`benchmark/train/router_train.py`; the ones for the shipped router are committed at
`benchmark/train/artifacts/router_oof.json`. Without it the routed column asks the shipped
router about pages it was trained on, which measures its memory rather than its judgement.
The runner applies the router's 0.5 confidence floor to those predictions, exactly as the
shipped router does.

With the current router (126 features, domain-grouped folds) the routed row reads
64.7% correct / 12.7% wrong / 22.7% missing lenient, and 49.4% / 28.0% / 22.7% strict.

## Two things about the corpus, both load-bearing

**1,081 of the 2,008 archived files have had every `<script>` tag stripped by the archiver.**
A page with no `<script>` reports no JSON-LD for reasons that have nothing to do with the
web. They are excluded, and the runner prints how many. Including them halves every
structured-data figure.

**The entire test split is in that cohort** (every file id ≥ 4000), so there is no held-out
split with structured data intact. Every number here is a dev number, and the only defence
against that is the out-of-fold routing above. A second corpus would be worth having, and
its absence is the largest caveat on this page.

## What is not measured here

Only the title. It is the one field with human-reviewed ground truth across all seven page
types; WCXB has no gold price, author or date. So the value fixes in `extract/schema.py` —
comma-decimal prices (`"19,99"` used to become `1999.0`), `AggregateOffer.lowPrice` no
longer passing as the price, `mpn` no longer passing as a SKU, HTML entities unescaped,
non-ISO dates declined — are covered by unit tests against observed real-world values
rather than by a corpus score. Their evidence is a census of how often each shape occurs,
not a measurement of how often we get it right. `TestDecimalSeparators` in
`packages/engine/tests/test_schema_extract.py` is where they live.
