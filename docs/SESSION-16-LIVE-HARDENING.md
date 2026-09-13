# Live hardening: fourteen merged fixes, measured twice each

The brief for this session: test the engine against live pages with a real browser as the
oracle, break it, fix it; then research what the leading extractors do, experiment, and keep
only what measures better -- fix, test, benchmark, PR, CI, merge, delete the branch. This is
the record, including the experiments that were rejected.

## 1. Result

WCXB dev (1,497 human-reviewed pages, seven page types, the corpus's own word-level F1),
production path -- the page-type router's out-of-fold prediction choosing the per-type
policy -- went **0.820 -> 0.848** (unrouted `content` 0.811 -> 0.821). The published field:
rs-trafilatura 0.859 (its author's, tuned on this split), MinerU-HTML 0.827, trafilatura
2.2.0 0.813 (run here). Second of seven, from fourth.

| type | N | start | end | best published |
|---|---:|---:|---:|---:|
| article | 793 | 0.920 | **0.934** | 0.932 (rs-trafilatura) |
| documentation | 91 | 0.923 | 0.925 | 0.931 |
| service | 165 | 0.794 | 0.823 | 0.843 |
| forum | 113 | 0.734 | 0.763 | 0.794 (MinerU-HTML) |
| collection | 117 | 0.569 | 0.673 | 0.713 |
| listing | 99 | 0.636 | **0.708** | 0.710 (MinerU-HTML) |
| product | 119 | 0.594 | 0.616 | 0.670 |

WCXB **test** split, opened once at the end and used for no decision: **0.856** routed,
0.851 unrouted. Zyte article-extraction: **0.895 -> 0.928** (15th -> 11th of 35).
WebMainBench 545: 0.631 -> 0.646 column mean (tables 0.425 -> 0.404, not diagnosed).
Reading-order benchmark, discriminating pairs: **0.505 -> 0.936**.

Every row for this engine was produced by the runners under `benchmark/` on one machine
against a local clone; every other number is its authors' published figure.

## 2. What changed, in merge order

Each PR carries its measurement in the commit message. The pattern throughout: a page read
wrongly, the mechanism found, the fix measured on the corpus before it shipped.

| PR | Fix | Found on | Effect |
|---|---|---|---|
| #13 | bridged column cut; card-atomic ordering; heading/main copy wins dedup; hidden twins | MDN, Allbirds, docs.python.org | side-by-side axiom 0.818 -> 0.962 |
| #14 | orphan text placed where it sits; **measured copy stays where drawn**; gutter rails; line unit = lower-quartile height; hidden buttons; lead restoration | Discourse, python.org, docs.python.org | discriminating 0.534 -> 0.937 |
| #15 | floats read whole (`data-wg-float`); MediaWiki edit strips; platform page type (`ns-0` = article) | en/ar/he Wikipedia | Wikipedia routed article, was unknown/listing |
| #16 | product sheet policy (prune reviews/grids by heading and shape, keep `Label: value` lines); named filter panels | thomann.de, newegg.com | product 0.586 -> 0.601 |
| #17 | cookie-consent dialogs stripped | gamefaqs.com (OneTrust centre chosen as content) | forum +0.010, listing +0.007 |
| #18 | `<aside>` stripped (re-measured on 1,497 pages, not 13) | mspoweruser.com | forum +0.013; Zyte 0.898 -> 0.911 |
| #19 | story rivers pruned by heading, stopping at prose; headline beats kicker as title | cbsnews.com, jpost.com | small, never negative |
| #20 | **text is text**: no alt text or placeholders in `Document.text`; screen-reader-only labels stripped | ikea.com | collection 0.586 -> 0.685, listing 0.663 -> 0.728, Zyte -> 0.920 |
| #21 | language/copy strip above code blocks | MDN | -- |
| #22 | product/collection refuse a run under a quarter of the page | lttlabs.com | product +0.009, collection +0.006 |
| #23 | comments under an article stripped (not forums, not products) | Slashdot | article 0.926 -> 0.932; Zyte -> 0.928 |
| #24 | innermost landmark wins over the `/nav/` path | protiviti.com (unclosed `<nav>` swallowed `<main>`) | service +0.005 |
| #25 | comments kept when they are the page | Hacker News item, GitHub issue (found live) | no corpus change |
| #26 | callout asides are content | docs.astro.build (found live) | no corpus change |

Two of the largest gains were one line each. #14's dedup line moved a measured block into
the slot of an earlier unmeasured copy, which put python.org's whole footer inside its
header; #20's `Document.text` had counted image alt text as prose since the beginning.

## 3. Rejected, with numbers

Recorded so that nobody runs them again as-is.

| experiment | result | why |
|---|---|---|
| return only the dominant repeated record group on collection/listing pages | collection 0.576 -> 0.496, listing 0.653 -> 0.555 | WCXB's collection truth is the category page minus chrome, not the grid; and it is inconsistent (newegg excludes facets, bombas includes them) |
| prune sections by heading on every page type (FAQ, Q&A, Related, Comments...) | article -0.001, forum -0.015, service -0.011 | annotators count an article's own FAQ and Q&A as content; "Share this page" above an article swallowed it |
| prefer the heaviest run *through* the title block | +0.0002 WCXB, 0.000 Zyte | not worth its code |
| images at half or no block cost | worse on product, collection, listing, service | -- |
| `min_run_share` 0.25 as the global default | article +0.001 on WCXB, Zyte 0.920 -> 0.916 | kept type-specific |
| meta-description fallback for JavaScript shells | -- | conflicts with the shell refusal, which is worth more than 232 characters |
| retrained per-block classifier on the new pipeline | 0.852 vs 0.851 out of fold; +0.018 service, +0.020 forum, worse elsewhere | its old +0.029 advantage is gone now the boundary step has the structure it lacked; the pure-Python exporter also fails sklearn equivalence with the current sklearn (max diff 0.63) and needs fixing before any hybrid |

## 4. How the live testing worked

`scratchpad/live/oracle.py` takes Chromium's own `innerText` of the page's main region;
`compare.py` splits both sides into sentences and reports recall (page sentences we lost)
and precision (sentences we emitted that no reader saw). It is crude -- it strips code
blocks from our side and not the page's, so documentation pages read low -- but every real
bug this session was found by reading its MISSING and EXTRA lists on a page and then the
blocks. Pages checked: BBC, Hacker News (front and item), MDN, docs.python.org, Discourse,
en/ar/he Wikipedia, Allbirds, amzn.in, Django docs, Rust book, Docusaurus, Starlight,
GitHub (repo and issue), Reddit and Amazon (refused as block pages, correctly).

## 5. What is still behind, and what it would take

- **product** (0.616 vs 0.670): the remaining pages are Steam-style sheets where annotators
  kept a curated subset of a sidebar, and spec tables split into dozens of two-word lines.
  A per-type per-block model is the honest next step; see the exporter note above.
- **collection** (0.673 vs 0.713): annotation-inconsistent; the filter-panel rule is as far
  as rules go.
- **forum** (0.763 vs 0.794): six of the 113 dev pages are Discourse app shells with no
  post text at all (the corpus's crawler was served the shell), a hard floor of ~0.947.
- **WebMainBench tables** dipped 0.425 -> 0.404 this round; the worst pages are layout
  tables on 1990s news markup. Not diagnosed.
- **CrawlBench** (Firecrawl) is LLM schema extraction on live pages with no public dataset;
  Hydrafetch's benchmark is the WCXB dev split with the same metric. Neither is a separate
  run; the benchmarks page says so.
