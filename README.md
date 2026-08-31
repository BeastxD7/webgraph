# webgraph

Universal web content extraction with **provenance** and **recovered reading order**.

Turns any web page into structured, citable data. Every extracted value records where it
came from and how confident the engine is; every extracted document records whether its
text order was *measured* from the rendered layout or merely assumed from source order.

---

## Why reading order is a first-class concern

**Source order is not reading order.** CSS reorders content freely — `order` on flex
children, `flex-direction: row-reverse`, explicit `grid-row`/`grid-column` placement, floats,
absolute positioning. A depth-first DOM walk therefore produces *silently* jumbled text on
exactly the pages where sequence matters most: news, documentation, academic papers, anything
multi-column.

Sorting blocks by their `y` coordinate does not fix it either — on a two-column page that
interleaves the columns line by line, which is worse than source order.

webgraph recovers reading order geometrically, using recursive XY-cut over measured bounding
boxes. Verified against a real browser:

| Layout | Source order | Recovered |
|---|---|---|
| `order:` on flex children | GAMMA, ALPHA, BETA | **ALPHA, BETA, GAMMA** |
| `flex-direction: row-reverse` | HEADER, RIGHT×3, LEFT×3 | **HEADER, LEFT×3, RIGHT×3** |
| explicit grid placement | B1, A1, B2, A2 | **A1, B1, A2, B2** |
| `column-count: 2` | ONE…SIX | **ONE…SIX** (correctly unchanged) |

When no geometry is available the engine falls back to source order and **says so** —
`reading_order_measured: false` — rather than presenting a guess as a measurement.

## The other design commitment: decline rather than guess

The engine never invents a value. `"contact us"` in a price field yields *no fact*, not `0`.
On the benchmark corpus this shows up as a **0% wrong-value rate** — every failure is a miss,
never a wrong answer — and that property is enforced by a test.

A missing value is recoverable downstream. A confidently wrong one poisons everything built
on it.

---

## Quick start

```bash
make install          # uv sync + playwright chromium + pnpm install
make test             # every suite
make bench            # score the engine against the benchmark corpus
```

Run the full stack in two terminals:

```bash
make api              # FastAPI on :8000  (docs at /docs)
make web              # Next.js on :3000
```

### CLI

```bash
# Page text in recovered reading order
webgraph text --render https://example.com/article

# Extract against a JSON Schema, with provenance on every value
webgraph extract https://example.com/product --schema schema.json

# Score against a labelled corpus; --min-page-success gates CI
webgraph bench benchmark/corpus-v0 --min-page-success 0.80
```

---

## How extraction works

Each stage is roughly an order of magnitude cheaper than the one below it. The pipeline
always tries the cheapest extractor that can read the content correctly.

```
Stage 0   profile        fingerprint the stack, decide whether a render is needed
   |
fetch     static HTTP    escalates to a browser only when the page is genuinely a shell
   |
FAST      structured     JSON-LD · microdata · OpenGraph · __NEXT_DATA__ ·
PATH      data           RSC flight data · Nuxt / initial state          [no model call]
   |
blocks    DOM -> text    innermost block-level elements; scripts and styles stripped
   |
order     XY-cut         geometric reading-order recovery from measured boxes
   |
map       JSON Schema    exact -> declared alias -> normalised -> bounded descent
   |
facts     provenance     source, extractor, modality, confidence, XPath
```

### Structured-data sources

| Source | Notes |
|---|---|
| JSON-LD | Arrays and `@graph` unwrapped; trailing commas recovered |
| Microdata | Nested scopes attach to their parent; machine-readable attributes preferred |
| OpenGraph | Scored lowest — written for social previews, not accuracy |
| `__NEXT_DATA__` | Next.js Pages Router; readable from raw HTML with no JS execution |
| RSC flight data | App Router; chunks reassembled from `self.__next_f.push(...)` |
| Nuxt / initial state | Object literals only; devalue function form is skipped, not guessed |

---

## Benchmark

`benchmark/corpus-v0` — snapshots across six site types (ecommerce, saas, news, spa-ssr,
spa-rsc, docs). Snapshots rather than live URLs: a benchmark whose answers change underneath
it measures nothing.

Current baseline, structured-data path only, **zero model calls**:

```
page_level_success = 83.3%   <- headline metric
field_accuracy     = 89.5%
missing            = 10.5%
wrong              =  0.0%
```

**Page-level success is the headline, deliberately.** Field-level accuracy overstates usable
quality — a page with one wrong field is a wrong page for an unattended pipeline, and the gap
between 89.5% and 83.3% is that effect in miniature.

The one failing case ships no structured data at all. It is included on purpose: it is the
evidence for where a selector or model path is actually required, rather than a case curated
away to flatter the number.

---

## Layout

```
packages/engine/     the extraction engine (Python, importable, no CLI deps)
  dom/               block extraction, reading-order recovery
  structured/        JSON-LD, microdata, hydration payloads
  profile/           stack fingerprinting, render decision
  extract/           JSON Schema mapping
  eval/              metrics and benchmark harness
  fetch/             static HTTP and browser rendering
apps/api/            FastAPI service over the engine
apps/web/            Next.js frontend
benchmark/           labelled corpus
docs/research/       evidence behind the design decisions
MEMORY.md            engineering journal — read before changing anything
```

## Tooling

Python via **uv** (workspace), frontend via **pnpm**. The engine is strict-typed
(`mypy --strict`), linted with ruff, and ships a `py.typed` marker so consumers get its types.

## Evidence

Design decisions trace to `docs/research/2026-08-31-findings.md`, which marks every finding
as verified or unaudited and lists six claims that were actively refuted. `MEMORY.md` records
the decisions taken, the approaches that failed, and why — read it before changing the
reading-order or extraction logic.

---

## The application

```bash
make install     # uv sync + playwright chromium + pnpm install
make api         # FastAPI on :8000
make web         # Next.js on :3000
```

- **`/`** — landing page with the URL prompt.
- **`/extract?url=…&mode=site`** — the whole-site run: live technology detection, a progress
  rail, and Discovered / Queued / Extracted / Failed tabs over the streaming crawl.
- **`/extract?url=…&mode=page`** — one page: provenance, Markdown, and JSON-schema mapping.

The front end is Next.js 16 (App Router, Turbopack) with Tailwind CSS v4; the API is FastAPI
over the engine package, streaming the crawl as server-sent events.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow, the commit convention, and why
[MEMORY.md](MEMORY.md) should be read before changing extraction, discovery or chrome
detection.

## Licence

MIT — see [LICENSE](LICENSE). Bundled third-party assets carry their own licences, recorded
in [apps/web/public/ASSETS.md](apps/web/public/ASSETS.md).
