# Site Graph — PRD v2 (research-revised)

**Supersedes:** PRD v1
**What changed:** v1's market analysis stands. Its engineering design was my
judgment, unresearched. This version replaces it with techniques that have
published numbers attached, and reverses two v1 decisions.

---

## 0. Changes from v1 — read this first

| # | v1 said | Evidence | v2 says |
|---|---|---|---|
| 1 | Graph is the differentiator, full stop | GraphRAG-Bench (ICLR 2026): simple fact retrieval 60.9 chunks vs 60.1 graph — a tie. Complex reasoning 53.4 vs 42.9. Contextual summarization 64.4 vs 51.3. "Do We Still Need GraphRAG" (arXiv 2604.09666): +0.47 avg on general QA, **+27.23 on multi-hop** | Graph earns its cost **only** for cross-page/multi-hop queries. Added a mandatory query-class audit at M2. If <30% of real queries are multi-hop, the graph is overhead. |
| 2 | Per-page LLM extraction on every changed page | Automatic XPath generation (J. King Saud Univ., 2025): 80.23 correct ratio / 86.93 F1 on SWDE using an 8×7B model, explicitly framed because per-page LLM is "economically impractical" at scale | **Selector induction.** Learn XPaths once per site template, replay them for free, invoke the LLM only when a selector breaks. Bigger cost lever than the hash gate. |
| 3 | Postgres, defer temporal design | Graphiti/Zep (arXiv 2501.13956): four-timestamp bitemporal model, invalidate-don't-delete, incremental resolution with no graph recomputation. Apache-2.0, ~30k stars | Adopt the **model** immediately (it's the correct one). Adopting the **library** is now an open decision, since it wants Neo4j/FalkorDB. |
| 4 | "Embeddings + alias table" for canonicalization | GoldenMatch on Abt-Buy: embedding blocking alone 35.5% precision → **95.4% with a GPT-4o-mini judge on borderline pairs, $0.04 total** | Replaced with a specified three-tier cascade (§3.4). |
| 5 | ≥85% precision gate | AXE (arXiv 2602.01838): **88.10%** zero-shot page-level F1 on SWDE is current SOTA, ranging 80.90% (Auto) to 93.13% (Restaurant) | 85% was accidentally set at SOTA. Kept, but now known to be ambitious, and DOM pruning is how AXE gets there. |
| 6 | Precision on extracted facts | Structured Output Benchmark (arXiv 2604.25359): 16 of 21 models score ≥96% on Path Recall, Structure Coverage and Type Safety, while **Value Accuracy drops to 0.693–0.830 and Perfect Response Rate collapses to 0.376–0.526** | Schema validity is a vanity metric. Gate on **value accuracy** and **perfect-response rate**. |
| 7 | Fine-tuned small model "later, maybe" | Phi-4 (14B) 0.798 value accuracy **above GPT-5's 0.795**; Schematron-8B 0.754 beats GPT-OSS-20B 0.693 at 2.5× fewer params. NewsScope: LLaMA-3.1-8B + LoRA → 98.8% schema validity, 89.4% vs GPT-4o-mini 93.7%, **p=0.07, not significant**, ~$15 compute | Promoted. Model size does not predict structured-extraction quality. Your Qwen3-4B/Unsloth path is a first-class option, scheduled at M2b. |
| 8 | Full graph construction | KET-RAG (SIGKDD 2025): skeleton over PageRank-selected key chunks + text-keyword bipartite graph → **indexing cost cut by over an order of magnitude** vs MS GraphRAG at comparable retrieval quality; up to 32.4% better generation | Don't build a full graph over every page. Skeleton + bipartite. |
| 9 | Ask feature assumed to work | RAG vs GraphRAG systematic eval (arXiv 2502.11371): only **~65.8%** of answer entities appear in the constructed KG on HotpotQA (65.5% on NQ). Graph coverage is the dominant failure mode | Ask must be **hybrid** — graph + chunk retrieval with a router. Systematic studies converge on hybrid beating either alone. |

**Sobering context:** a 2026 analysis found **72–80% of enterprise RAG
implementations fail to reach production**, with graph construction overhead a
recurring contributor — hallucinated entities producing brittle structures needing
expensive manual correction. Microsoft GraphRAG's own discussion thread cites a
**$33K** indexing bill for a single 5GB legal case using GPT-4o-mini.

---

## 1. Vision, positioning, market

*Unchanged from v1 §2.1–2.3. Competitive landscape, pricing tiers, and vertical
choice (B2B SaaS competitor tracking) all stand. Re-read v1 for that section.*

The one addition: finding #1 sharpens the positioning. You are not selling "a graph."
You are selling answers to **cross-page questions** — which is the only query class
where the graph is measurably worth its cost. Market that, not the architecture.

---

## 2. Revised architecture

```
Scheduler
    │
    ▼
Crawler (Crawl4AI; Firecrawl fallback for JS/anti-bot)
    │
    ▼
Page store → normalized text + content_hash
    │  hash unchanged → STOP                              [gate 1: no work]
    ▼
DOM pruning to semantic core  (AXE-style)                 [cost: ~free]
    │
    ▼
Selector cache: does a learned XPath set exist for this template?
    │
    ├── YES → replay selectors → typed facts               [gate 2: no LLM]
    │           └── validation fails → fall through
    │
    └── NO / BROKEN → LLM induction on 2–3 seed pages
                      → emit reusable XPath set → cache
    │
    ▼
Entity resolution cascade (§3.4)                          [gate 3: LLM only on
    │                                                      borderline pairs]
    ▼
Bitemporal graph store (4 timestamps, invalidate-don't-delete)
    │
    ├──► Differ ──► digest / comparison matrix
    └──► Hybrid retriever (graph + chunks + router) ──► Ask
```

**Three cost gates instead of one.** v1 had only the content hash. Gate 2 is the
important addition: on a recurring monitor of the *same* sites, most re-crawls
should cost zero LLM tokens, because the template hasn't changed even when the
content has. A price changing from $49 to $59 does not need an LLM to notice.

---

## 3. Component specifications

### 3.1 DOM pruning

Prune the DOM to its semantic core before any model sees it. AXE reaches 88.10%
zero-shot F1 on SWDE this way — beating the best *supervised* baseline (WebLM-LARGE
at 87.57%, k=1) — because pruning generalizes where layout-fitting overfits.

Practical effect for you: fewer input tokens per page, and better accuracy. Do this
before measuring anything else.

### 3.2 Selector induction (the main cost lever)

1. Cluster pages by DOM template signature.
2. For a new template, send 2–3 pruned seed pages to a capable model. Ask it to emit
   **XPath expressions per schema field**, not the values.
3. Cache the XPath set keyed by template signature.
4. On subsequent crawls, execute the XPaths directly. No model call.
5. Validate every replay (type checks, range checks, non-null on required fields).
   On validation failure, mark the selector stale and re-induce.

Published baseline for this pattern: 80.23 correct ratio and 86.93 F1 on SWDE using
an 8×7B model — i.e. it works without a frontier model.

**Fallback:** free-text pages (blog posts, changelogs) have no stable template.
Route those to direct LLM extraction. Expect roughly 20–30% of pages in this bucket.

### 3.3 Graph construction — skeleton, not full

Follow KET-RAG's shape rather than Microsoft GraphRAG's:

- Build a KNN graph over chunk embeddings, run PageRank, select the top core chunks.
- LLM-extract a **skeleton** graph from those core chunks only.
- Build a cheap text-keyword bipartite graph over *all* chunks by tokenization alone.
- Retrieve from both channels with a tunable ratio θ.

KET-RAG reports comparable or superior retrieval quality to MS GraphRAG at over an
order of magnitude lower indexing cost. Its Skeleton-RAG component alone cuts
indexing cost ~20% with retrieval quality held.

For your typed schema this is a hybrid: the typed entities (Plan, Feature, Price)
come from selectors and are always fully extracted; the skeleton approach applies to
the unstructured remainder (positioning copy, blog, changelog).

### 3.4 Entity resolution cascade

Replaces v1's one-line hand-wave. This is the phantom-diff killer.

```
For each candidate Feature mention:
  embed (all-MiniLM-L6-v2 or similar), ANN blocking, top-20 candidates
  score ≥ 0.95   → auto-accept as same entity          (no LLM)
  0.75 ≤ s < 0.95 → batch 20 pairs → LLM judge: same entity? YES/NO
  score < 0.75   → auto-reject                          (no LLM)
```

Reference numbers on Abt-Buy (1,081 × 1,092 records, 1,097 true pairs): embedding
blocking alone gave 35.5% precision / 59.4% recall / 44.5% F1. Adding the LLM judge
on 1,757 borderline pairs gave **95.4% precision / 50.9% recall / 66.3% F1 at
$0.036 total**.

**Read the recall drop carefully.** The LLM raises precision by *rejecting*, not by
finding new matches — recall fell from 59.4% to 50.9%. For your product this
tradeoff is correct: a false merge produces a wrong comparison matrix, a missed merge
produces a duplicate row the user can see and report. Precision is the right thing
to optimize.

**Caveat worth respecting:** blocking design gets hard when records are messy with
multiple fields and combinations — a single whole-record vector "blurs everything
together." Your Feature records are simple (name + short description), which is why
this is tractable here. Don't assume it transfers if you later expand the schema.

### 3.5 Bitemporal store

Adopt Graphiti's model regardless of whether you adopt the library:

- Four timestamps per edge: `t_valid` / `t_invalid` (when the fact was true in the
  world) and `t_created` / `t_expired` (when your system learned/retired it).
- New conflicting information **invalidates** the old edge by closing its validity
  window. Never delete.
- This gives point-in-time queries for free: "what did this competitor's Pro plan
  include on March 15?" is your comparison feature's real moat, and it's a
  consequence of the data model, not a feature you build.
- Incremental integration without recomputing the graph.

### 3.6 Ask — hybrid, not graph-only

Given the ~65.8% entity-coverage finding, a graph-only Ask will confidently fail on
about a third of questions. Build:

- Graph channel for entity/relation queries
- Chunk channel over the pruned page text
- A router that classifies the query (single-hop factoid → chunks; multi-hop/
  comparative → graph; ambiguous → both, fused)

Note that agentic multi-round retrieval over dense RAG can partially close the gap to
GraphRAG, though the effect depends on agent design and sometimes *hurts*. Don't
build the agentic version in V1.

---

## 4. Revised metrics and gates

**Retire "schema validity" as a success metric.** It is nearly saturated and hides
the real failure: 16 of 21 models clear ≥96% on structural metrics while value
accuracy sits at 0.693–0.830 and perfect-response rate collapses to 0.376–0.526.

| Gate | Metric | Target | Why this number |
|---|---|---|---|
| M2a | **Value accuracy** on gold set (correct value in correct field) | ≥85% | AXE's SOTA is 88.10% on SWDE; 85% on a narrower fixed schema is ambitious but not fantasy |
| M2a | **Perfect page rate** (every field on a page correct) | ≥60% | Published range is 0.376–0.526; beating it requires the narrow schema to be doing real work |
| M2b | Query-class audit: % of 50 real user questions needing ≥2 pages | ≥30% | Below this, GraphRAG-Bench says the graph is overhead — pivot to chunks and ship faster |
| M3 | Phantom diffs on two identical crawls | 0 | ER cascade working |
| M3 | ER precision on hand-labelled feature pairs | ≥90% | GoldenMatch achieved 95.4%; 90% on cleaner data is reasonable |
| M4 | False-positive alerts | ≤2 / site / month | The churn driver: ~40% of CI tool users abandon within 12 months, alert fatigue cited |
| M6 | Paying users | 3 | Unchanged |

---

## 5. Revised milestones

| # | Weeks | Deliverable | Gate |
|---|---|---|---|
| M0 | 1 | Gold set: 10 sites, hand-labelled. **Also: write down 50 questions you'd actually ask.** | Both exist before code |
| M1 | 2–3 | Crawl + DOM prune + template clustering + content hash | Correctly identifies changed pages and stable templates |
| M2a | 4–5 | Selector induction + replay + validation | Value accuracy ≥85%, perfect-page ≥60%, **and measured cost per site per month** |
| M2b | 5–6 | Query-class audit + fine-tune spike | ≥30% multi-hop, or pivot. Qwen3-4B LoRA vs hosted baseline on the gold set |
| M3 | 7–8 | ER cascade + bitemporal store | Zero phantom diffs, ER precision ≥90% |
| M4 | 9–10 | Differ + weekly digest | You read it voluntarily |
| M5 | 11–12 | Comparison matrix + point-in-time query | Same engine, second axis |
| M6 | 13–15 | Auth, billing, landing page | 3 paying users |

**M2b is a real decision point, not a checkbox.** If the query audit comes back
under 30% multi-hop, the honest move is to ship a much simpler chunk-based product
and skip the graph entirely. That would be a good outcome discovered cheaply, not a
failure.

---

## 6. Cost model (revised)

```
per_site_monthly_cost =
      selector_induction_amortized        # once per template, ~2-3 pages
    + free_replay                          # ≈ 0
    + freetext_llm_extraction              # ~20-30% of pages, changed only
    + er_judge_calls                       # borderline pairs only, ~$0.04/1800 pairs
    + skeleton_construction_amortized      # core chunks only, KET-RAG shape
```

v1's model assumed every changed page costs a full LLM extraction. With gates 2 and
3, steady-state cost should fall roughly an order of magnitude. **Still measure it at
M2a** — the $33K legal-case figure exists precisely because someone didn't.

---

## 7. Risks (revised)

| Risk | Change from v1 | Mitigation |
|---|---|---|
| Query traffic isn't multi-hop → graph is dead weight | **New, and it's the top risk** | M2b audit before building the graph |
| Graph coverage gaps break Ask | **New** | Hybrid retriever with router; ~65.8% coverage is the published baseline to beat |
| Value accuracy plateaus below 85% | Sharpened | DOM pruning first; narrow the schema before lowering the bar |
| Selector rot on redesigns | **New** | Validation on every replay; re-induction is cheap and bounded |
| Extraction cost | Downgraded | Three gates now, not one |
| Small model underperforms | Downgraded | Evidence says size doesn't predict quality here; test at M2b |
| Employment contract | **Unchanged and still gating** | Read it before M0 |
| Solo momentum loss | Unchanged, still the likeliest failure | M4 ships something you use weekly |

---

## 8. Open decisions

1. **Graphiti library, or borrow the model into Postgres?** The bitemporal design is
   settled; the dependency is not. Graphiti wants Neo4j/FalkorDB. Adopting it makes
   your Text2Cypher work directly load-bearing; declining keeps you on one database.
2. **Extraction model at M2b** — hosted vs Qwen3-4B LoRA. The evidence now supports
   trying the fine-tune early rather than treating it as a later optimization.
3. **Vertical** — still unconfirmed. Fixes the schema, which fixes everything else.
4. **Contract check.**

---

## Appendix — papers and sources actually read this pass

- GraphRAG-Bench / "When to use Graphs in RAG" — arXiv 2506.05690, ICLR 2026
- "Do We Still Need GraphRAG?" — arXiv 2604.09666
- "RAG vs. GraphRAG: A Systematic Evaluation" — arXiv 2502.11371
- KET-RAG — arXiv 2502.09304, SIGKDD 2025; plus microsoft/graphrag discussion #1817
- AXE: Low-Cost Cross-Domain Web Structured Information Extraction — arXiv 2602.01838
- Automatic XPath generation agents — J. King Saud Univ. CIS, 2025
- Zep / Graphiti — arXiv 2501.13956
- The Structured Output Benchmark — arXiv 2604.25359
- LLMStructBench — arXiv 2602.14743
- NewsScope — arXiv 2601.08852
- GoldenMatch entity-resolution write-up (Towards AI, Mar 2026) — engineering blog,
  single dataset, not peer-reviewed; treat the cascade design as sound and the exact
  numbers as indicative
- Senzing critique of LLM-only entity resolution — vendor-published, read for the
  blocking-design argument, not the conclusion
- LinearRAG — arXiv 2510.10114 (graph retrieval introduces noise: context relevance
  36.86–54.61% vs vanilla RAG's 62.87%)

*Benchmark numbers come from different datasets under different protocols and do not
compose. Treat them as calibration for expectations, not as predictions of what your
pipeline will score.*
