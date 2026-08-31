# Site Graph — Market Analysis & Product Requirements

**Status:** Draft v1 for build kickoff
**Author:** (you)
**Context:** Solo, side-project alongside full-time employment. Target: side income, not salary replacement.

---

## Part 1 — Market Analysis

### 1.1 The four categories that already exist

The idea "turn a website into a queryable graph, watch it, compare it" touches four
distinct existing markets. It is important to know that none of them is empty.

**A. LLM-ready extraction / crawling infrastructure**

| Tool | Model | Price | Notes |
|---|---|---|---|
| Firecrawl | Managed API, AGPL core | ~$16/mo (3k credits) → ~$83–99/mo (100k) → ~$333–399/mo (500k) | LLM-ready markdown + JSON via schema or NL prompt. SDKs in 6 languages. Ships an MCP server and agent skills. |
| Crawl4AI | OSS library, Apache-2.0 | Free + your infra + your tokens | Python-first, Playwright-based, local LLM support (Ollama). ~2GB Docker image. |
| ScrapeGraphAI | OSS | Free | NL-described extraction via graph pipeline. |
| fastCRW / CRW | Rust, Firecrawl-compatible API | — | Lower memory footprint, built-in MCP. |
| Apify | Platform | Usage-based | Broad actor marketplace. |

**Takeaway:** clean HTML → markdown/JSON is a *solved, commoditized* layer. Do not
build it. Consume it. A common production pattern is Crawl4AI for bulk pages with
Firecrawl fallback for JS-heavy or anti-bot pages.

**B. Web-scale knowledge graph**

- **Diffbot** — the closest conceptual ancestor. Crawls ~1.2B websites, maintains a
  knowledge graph of ~10B entities and ~1T facts. Entity recognition, custom
  scheduled crawls, REST API. Free tier 10k credits; paid from **$299/mo**;
  enterprise custom.
- **Weakness to exploit:** Diffbot's graph is *generic web-scale schema* (people,
  companies, products, articles, discussions). It is not "your domain's schema over
  the specific sites you care about." It is also positioned for sales/lead-gen
  buyers and needs real technical investment to use.

**C. Competitive intelligence platforms**

| Tier | Tools | Price |
|---|---|---|
| Enterprise | Crayon, Klue, AlphaSense, Contify | ~$15k–45k/yr; Klue Compete entry ~$14k/yr; AlphaSense $10k–50k+/seat |
| Mid-market | Kompyte (owned by Semrush) | ~$300–800/mo |
| Founder-led / SMB | Analook, Visualping, Owler, Brand24 | $0–35/mo — *fastest-growing layer by account count (3–5× YoY), smallest by revenue* |

**Two facts that matter more than the pricing:**
1. **~40% of teams abandon CI tools within 12 months** — cited cause is alert
   fatigue, integration gaps, and no internal workflow to act on insights.
2. **Crayon shipped an MCP server in 2026**, the first CI platform to interconnect
   with external AI platforms. The category knows where it's going. You will not be
   first to "CI + agents"; you can still be better at it.

**D. Website change monitoring**

| Tool | Price | Method |
|---|---|---|
| changedetection.io | Free self-host / $8.99/mo SaaS | Text diff, OSS, large community |
| Wachete | $4.90/mo | Text diff |
| WatchDiff | $9/mo | Claims AI noise filtering on all paid tiers |
| Visualping | $13/mo (5 daily checks) → $41/mo Pro | Screenshot/visual diff, ~2M users, owns SEO for the category |
| Distill.io | $15/mo | Extension + cloud, advanced selectors |
| PageCrawl.io | $14/mo | AI change summaries |
| Fluxguard | $49–99/mo | Compliance/audit-trail positioning, CI/CD API |
| Context.dev | — | Exact diff per page + **semantic diff for whole-site** |

**Critical finding:** "AI semantic diff" is already a marketing claim across this
tier. Context.dev explicitly does semantic whole-site monitoring. If your pitch is
"semantic instead of pixel diff," you are entering a $9–15/mo commodity fight with
incumbents who own the search terms.

### 1.2 So where is the actual gap?

Every tool above is **stateless about meaning**. They compare *documents* — pixels,
text, or an LLM summary of a text delta. None of them maintains a **persistent,
typed entity graph of the site** across time.

That difference produces four capabilities nobody in the $10–100/mo tier has:

1. **Cross-page joins.** "Which plans include SSO *and* are available in the EU"
   requires facts from the pricing page, the security page, and the compliance page
   to be resolved into one entity. Chunked retrieval and page diffs cannot do this.
2. **Entity-level change.** Not "the pricing page changed" but "`Plan:Pro` →
   `price` 49 → 59, and `feature:SSO` moved from `Pro` to `Enterprise`." This is
   the direct answer to alert fatigue: a typed delta is triageable, a text delta is
   not.
3. **Cross-site comparison on one normalized schema.** Extract 5 competitors into
   the *same* entity types and you get a real comparison matrix, not 5 separate
   monitoring feeds. **Note: this is the same engine as #2** — change detection is
   a diff across time, comparison is a diff across domains.
4. **Machine-queryable output.** A hosted MCP server exposing typed tools
   (`get_plan_features`, `compare_pricing`) rather than a text blob. Crayon proved
   the demand direction at $15k/yr; nobody serves it at $99/mo.

### 1.3 The two hard constraints

**Cost.** Graph construction via LLM is genuinely expensive. GraphRAG-Bench measured
graph construction on a single corpus at ~80M tokens (Microsoft GraphRAG) and ~84M
tokens (LightRAG). Full re-extraction of a site on every check will destroy the unit
economics of any sub-$100/mo price point. **Incremental, content-hash-gated
extraction is not an optimization — it is the product's viability.**

**Accuracy at breadth.** "Any website" guarantees mediocre extraction. Accuracy comes
from a constrained schema over a constrained site category.

### 1.4 Build vs. buy

| Layer | Decision |
|---|---|
| Crawl + HTML→markdown | **Buy/consume.** Crawl4AI self-hosted, Firecrawl fallback. |
| Entity/relation extraction | **Build.** This is the differentiated layer. |
| Temporal graph store | **Evaluate Graphiti** (getzep) — temporally-aware KG, bitemporal by design. Otherwise plain Postgres + a versioned edge table. Neo4j only if you need real traversal depth. |
| NL → query | **Build, and you have a head start.** The DocuPrism-Text2Cypher LoRA work is exactly this layer if the store ends up being Neo4j/Cypher. |
| Graph construction framework | Do **not** adopt Microsoft GraphRAG wholesale — it is built for community-summary QA over documents, not typed domain entities, and it is the expensive end of the token benchmarks. |

---

## Part 2 — Product Requirements

### 2.1 Vision

A website is a database that has been flattened into pages. Site Graph un-flattens
it: crawl a site once, extract a typed entity graph, keep that graph current, and
expose it to humans and agents as something queryable, diffable, and comparable
across sites.

### 2.2 Positioning statement

> For product marketing and competitive intelligence teams who track competitor
> websites, Site Graph turns each site into a typed entity graph, so changes arrive
> as structured facts ("Pro plan lost SSO") rather than page diffs, and multiple
> competitors can be compared on one normalized schema. Unlike Visualping or
> changedetection.io, which diff documents, Site Graph diffs meaning. Unlike Crayon
> or Klue at $15k+/yr, it is self-serve and priced for teams without a CI budget.

### 2.3 Target user (V1)

**Primary:** product marketing / founder / competitive-intel owner at a B2B SaaS
company with 3–15 tracked competitors. Currently either using a $13/mo page monitor
and drowning in noise, or maintaining a manual comparison spreadsheet.

**Why this vertical first:** B2B SaaS marketing sites have exactly the structure this
approach needs — plans, prices, features, integrations, compliance certifications,
regions — with slow churn and high commercial stakes. You are also inside this
market and can recognize a good extraction from a bad one without domain research.

**Explicitly not V1:** e-commerce catalogs (volume kills the cost model), news
(no stable entities), regulatory/legal (high accuracy bar, slow enterprise sale).

### 2.4 The V1 job to be done

> "Tell me what actually changed about my competitors this week, at the level of
> facts I'd put in a battlecard, and let me see all of them side by side."

### 2.5 Scope

**In scope for V1**

| # | Feature | Detail |
|---|---|---|
| F1 | Site ingestion | User adds a domain. Crawl (sitemap-first, bounded page budget). Classify page types. |
| F2 | Typed extraction | LLM extraction into the fixed B2B SaaS schema (§2.6). Every fact carries a source URL + text span. |
| F3 | Graph storage | Bitemporal: each fact has `valid_from` / `valid_to`. Never hard-delete; supersede. |
| F4 | Scheduled re-crawl | Content-hash gate: only re-extract pages whose normalized content changed. |
| F5 | Entity-level diff | Typed deltas: entity added/removed, attribute changed, relation added/removed. |
| F6 | Digest | Weekly email + Slack webhook. Grouped by entity, not by page. |
| F7 | Comparison matrix | N sites, one schema, side-by-side table. Export CSV. |
| F8 | Ask | NL question → query over the graph → answer with per-fact citations. |

**Deliberately deferred (v2+, same core, do not build now)**

- Hosted MCP server per workspace (this is the highest-upside deferred item)
- Structured extraction API sold to agent developers
- Self-contradiction detection across a company's own surface
- Additional verticals
- Browser extension, CRM integrations, battlecards

**Non-goals, permanently**

- Being a general-purpose scraper (Firecrawl exists)
- Web-scale graph (Diffbot exists)
- Pixel/visual diff (Visualping exists and owns it)
- llms.txt scoring or GEO/AI-visibility optimization — the data does not support
  the value claim and the file generation is already free in Mintlify, GitBook, Wix

### 2.6 V1 schema (fixed, not user-defined)

A fixed schema is the whole accuracy strategy. Resist making it configurable in V1.

```
Company        name, domain, tagline, positioning_statement, hq_region
Plan           name, price_amount, price_currency, price_period, billing_note,
               seat_model, is_free_tier, is_custom_pricing
Feature        name, canonical_key, description
Integration    name, category
Certification  name (SOC2, ISO27001, HIPAA, GDPR-DPA, ...)
Region         name
Persona        name           (who the site says it's for)
Competitor     name           (who the site names as a rival)

Relations
  Plan        -[INCLUDES]->        Feature      {limit, note}
  Plan        -[AVAILABLE_IN]->    Region
  Company     -[OFFERS]->          Plan
  Company     -[SUPPORTS]->        Integration
  Company     -[HOLDS]->           Certification
  Company     -[TARGETS]->         Persona
  Company     -[NAMES_RIVAL]->     Competitor

Every node and edge carries:
  source_url, source_span, extracted_at, confidence, valid_from, valid_to
```

**`canonical_key` on Feature is the hardest problem in the product.** "SSO",
"Single Sign-On", and "SAML authentication" must resolve to one key or the
comparison matrix is worthless and every re-crawl generates phantom diffs. Plan for
an embedding-based canonicalization step plus a curated alias table, and expect to
hand-tune it. Budget real time here; this is where the product succeeds or fails.

### 2.7 Architecture

```
  Scheduler (cron)
        │
        ▼
  Crawler ─────────► Crawl4AI (self-hosted) ──► Firecrawl (fallback: JS/anti-bot)
        │
        ▼
  Page store ──► normalized text + content_hash
        │
        │  hash unchanged ──► STOP (no LLM call)  ◄── the cost gate
        ▼
  Page classifier (cheap model or heuristic: pricing / features / security / other)
        │
        ▼
  Typed extractor (LLM, schema-constrained JSON, page-type-specific prompt)
        │
        ▼
  Canonicalizer (embedding + alias table)
        │
        ▼
  Graph store (bitemporal)  ──► Differ ──► Digest / Matrix / Ask
```

**Stack recommendation (optimizing for solo maintenance, not elegance):**

- Python + FastAPI
- Postgres with `pgvector`. **Start relational, not Neo4j.** The V1 query patterns
  are shallow joins, and one database you can operate at 11pm beats two.
  Revisit Neo4j only when a real query needs multi-hop traversal — at which point
  the Text2Cypher work becomes directly reusable.
- Extraction model: start with a hosted mid-tier model for quality, measure the
  per-site cost, then evaluate whether a fine-tuned small model (your Qwen3-4B /
  Unsloth setup) can hold quality at lower cost. **This is the natural bridge from
  your fine-tuning learning to the product, but do not start here** — validate the
  extraction schema first with a strong model, then distill.
- Frontend: whatever you'll actually finish. Next.js or plain server-rendered.
- Queue: Postgres-backed (pgmq / SolidQueue-style). Do not add Redis+Celery yet.

### 2.8 Cost model — must be validated before writing feature code

Build this spreadsheet before Milestone 2:

```
pages_crawled_per_site         (target: 30–80 for a B2B SaaS marketing site)
pct_pages_changed_per_week     (assume 5–15%)
extraction_tokens_per_page     (measure, don't guess)
cost_per_extraction
─────────────────────────────
monthly_cost_per_site  =  initial_amortized + (recrawl_freq × pct_changed × pages × cost)
```

**Hard gate:** if monthly cost per tracked site exceeds ~$1.50, the $49/mo-for-5-sites
price point does not work and either the crawl budget, the re-crawl frequency, or
the price has to change. Find this out in week 3, not month 6.

### 2.9 Pricing hypothesis

| Tier | Price | Sites | Cadence |
|---|---|---|---|
| Free | $0 | 1 | Weekly, no history |
| Solo | $29/mo | 3 | Weekly + full history + matrix |
| Team | $79/mo | 10 | Daily + Slack + CSV export + API |

Positioned above the $9–15 page monitors (different job, more value) and far below
Kompyte's ~$300+/mo. Seat-independent, because seat-based pricing needs a sales
motion you cannot run while employed.

### 2.10 Success criteria

**Milestone gate, not vanity metrics.**

- **Technical:** on 10 hand-picked B2B SaaS sites, extraction achieves ≥85% precision
  on Plan/Feature/price facts against a manually labelled gold set. Build the gold
  set first.
- **Noise:** ≤2 false-positive change alerts per site per month. This is the metric
  that decides whether you beat the incumbents, since alert fatigue is the stated
  reason 40% of CI tool users churn.
- **Commercial:** 3 people paying $29 within 60 days of launch. Not 100 signups —
  3 payments.

### 2.11 Milestones (solo, evenings + weekends)

| # | Weeks | Deliverable | Gate |
|---|---|---|---|
| M0 | 1 | Gold set: 10 sites, manually labelled plans/features/prices in a spreadsheet | Exists before any code |
| M1 | 2–3 | Crawl + normalize + hash. No LLM yet. | Can re-crawl 10 sites and correctly detect which pages changed |
| M2 | 4–5 | Typed extraction + cost measurement | ≥85% precision on gold set AND cost/site/month known |
| M3 | 6–7 | Bitemporal store + canonicalizer | Two crawls of one site produce zero phantom diffs |
| M4 | 8–9 | Differ + weekly email digest | Digest for 3 real competitors that you'd actually read |
| M5 | 10–11 | Comparison matrix + CSV | Same engine as M4, different axis |
| M6 | 12–14 | Auth, billing, landing page, launch | 3 paying users |

**If M2's gate fails, stop and reconsider.** Do not proceed to M3 on hope.

### 2.12 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Extraction cost exceeds price point | **Kills product** | Hash gate; measure at M2; distill to a fine-tuned small model later |
| Feature canonicalization produces phantom diffs | **Kills product** | Alias table + embeddings; M3 gate explicitly tests this |
| Incumbents add entity-level diff | High | They're document-oriented by architecture; but Crayon's MCP move shows the direction — move fast on the deferred MCP feature |
| Employment contract / moonlighting clause | **Legal** | Read the agreement *before* M0. This tool is adjacent to document-intelligence work; confirm it is not competitive with your employer's business. |
| Scope creep back to all 5 original features | High | The deferred list in §2.5 is a commitment, not a wishlist |
| Anti-bot blocking on target sites | Medium | Firecrawl fallback; respect robots.txt; publish an identifiable user agent |
| Solo momentum loss around month 3 | **Most likely failure mode** | M4 ships something you personally use weekly — be your own first user |

### 2.13 Open decisions for you

1. **Vertical confirmation** — B2B SaaS competitor tracking, or something else? This
   choice fixes the schema, and the schema is the first real commit.
2. **Postgres vs Neo4j** — recommendation is Postgres for V1, but if you want the
   Text2Cypher work to be load-bearing from day one, that changes the call.
3. **Extraction model** — hosted for quality first, or fine-tuned small model from
   the start? Recommendation is hosted first, distill at M2 once the schema is stable.
4. **Contract check** — non-negotiable, and it gates everything above.

---

## Appendix — Sources consulted

Firecrawl (pricing/comparison pages, Jan 2026 benchmark), Crawl4AI, fastCRW
comparison (Jun 2026), Diffbot (Capterra/G2 listings, 2026), Improvado CI vendor
survey (Aug 2026), Klue CI market overview (Mar 2026), Unkover CI review (Mar 2026),
Analook CI market analysis (Jun 2026), Datashake CI comparison (Jul 2026),
PageCrawl.io monitoring comparison (Jul 2026), Context.dev change-detection
comparison (Aug 2026), Visualping alternatives roundups (Apr/Jul 2026),
GraphRAG-Bench (arXiv 2506.02404), Awesome-GraphRAG, SE Ranking llms.txt adoption
study, Limy llms.txt bot-traffic analysis.

*Vendor pricing changes frequently and several sources above are vendor-published
comparisons with obvious incentives. Verify pricing directly before relying on it.*
