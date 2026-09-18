# Session 19: the overnight loop

The owner's brief, given late on 18 September: a deep read of Firecrawl's approach and
architecture, then "self-improve our engine until I come back tomorrow" — look at the
alternatives, compare, implement what is good. This is the record of that night (PRs
#132–#149), continuing `SESSION-18-WHOLE-PAGE.md`. Everything landed on `main` through a
PR with CI green; every engine change was checked on the real site that raised it and,
where a board could see it, on the board.

## 1. What started it

A whole-site run on `bhavyadhanwani.dev` read one page. The site has two. Its home page
links to `/projects` with a plain `<a href="/projects">` — and every page declares
`<link rel="canonical" href="https://bhavyaz-portfolio.vercel.app">`, the site's previous
host, which the crawl was using as the base for resolving relative links. `/projects`
became an address on another site and was dropped with nothing in the log to say so.
Three things followed from that one bug, and they set the night's direction:

- links resolve against the address a page was *served* at, never its canonical (#132);
- what a page declares about itself is a fact worth reading and showing — head metadata
  in stage 0, with `declared_elsewhere` for the declarations that name another site
  (#133), and the same three facts as Site Truth Report findings (#144);
- a crawl that turns an address away silently cannot be questioned — so every refused
  address now has a reason, on the events and on screen (#136).

`/projects` itself turned out to be one `<canvas>` and seven words, with three projects
and their repositories living only in a script bundle. The crawl now says so (#134).

## 2. The research

`docs/research/2026-09-19-firecrawl-and-alternatives.md` — Firecrawl (`7b0b0b9`) and
crawl4ai (`862f6bc`) read from their source, each claim tied to a file, set beside this
engine, sorted into what to take and what to leave. The short version: Firecrawl is a
scrape-as-a-service platform whose success test is "markdown non-empty and 2xx", whose
answer to a 403 is a stealth proxy, whose main-content is a selector blocklist patched
per domain from its customers' scrapes, and whose products after markdown are LLM
formats. What it does better than us is operations, file types, and one idea we took
first: a sentence for every URL it does not crawl. What we leave, by design: disguise,
LLM formats, a shared cross-customer index, blocklists, search-backed discovery.

## 3. What changed, in merge order

| PR | Change | Found on | Measured |
|---|---|---|---|
| #131 | isometric scene removed (808 lines) | — | — |
| #132 | links resolve against the page's own URL, never its canonical | bhavyadhanwani.dev | 1 page → 2 |
| #133 | head metadata read in stage 0 (`analysis.metadata`, page `resolve.metadata`); `declared_elsewhere`; browser snapshot keeps `<html>`'s attributes on shadow-root pages; MetadataPanel | bhavyadhanwani.dev (language was `null`) | — |
| #134 | canvas verdict; addresses held in scripts (named values only) and links to other sites, on the page event and as tree leaves; an empty render defers to the static markup | `/projects` | — |
| #135 | the research document | — | — |
| #136 | every refused address has a reason (`refused` on frontier/page/done; "Addresses turned away") | Firecrawl's denial reasons | the sitemap's two addresses show as `off-site` |
| #137 | gzipped sitemap bodies decompressed, bomb-safe | analysis §5.8 | unit |
| #138 | run page no longer mismatches on hydration | every run page in dev | — |
| #139 | `within_path`, `include_paths`, `exclude_paths` via config, API (bad pattern → 422) and settings | Firecrawl's scope options | gov.uk: 17,735 excluded, 17,092 not-included, named |
| #140 | image blocks carry `srcset`'s largest candidate | Firecrawl §2.4 | fidelity = (counts, not addresses) |
| #141 | what Common Crawl last saw on the host, background, report-only; opt-in seeding cited `via: common-crawl` | crawl4ai's URL seeder | vtu.ac.in 1,952 addresses (direct); the index refuses this IP after a burst — reported as such |
| #142 | the tree says depth is links from the root; shows path depth beside it | both alternatives count segments | — |
| #143 | share-card addresses absolute | — | unit |
| #144 | report findings: `canonical_elsewhere`, `sitemap_elsewhere`, `canvas_content` | bhavyadhanwani.dev | all three fire on its report |
| #145 | per-page `static_chars`/`rendered_chars`; "render was empty" | `/projects` | — |
| #146 | throttle tests assert on granted slots, not wake times | flaky beside every build | passes under a build ×3 |
| #147 | `#fragment` links are the page, not refusals | docs.astro.build (161 of them) | 32 → 0 on a 3-page run |
| #148 | a gate that hides the page is not a hidden menu: one outermost hidden element bigger than the visible render keeps the static page (`render_note`) | allbirds.com — which turned out *not* to be one (§4) | fidelity = on 21 sites; 4 unit shapes |
| #149 | an `<aside>` that carries the page's title is kept and read as main | allbirds.com's buy box | WCXB dev = to three decimals on every type |

## 4. What the surveys found, and what they did not

Fourteen sites were crawled through the API and read for anomalies (docs, a store, a
forum, two news sites, three government sites, a SPA, a wiki, a framework's site):

- **Refusal tallies are readable now.** Docs sites' hundreds of `not-a-page` refusals
  were `#fragment` links to the same page (#147). gov.uk with a path scope names its
  excluded and not-included addresses (#139).
- **allbirds.com looked like a gate and was not.** 90,361 static characters, 2,222
  rendered, 3,522 merged. The 88,000 hidden characters are Shopify template text in the
  `footer` landmark — cart drawer, size guide, returns copy — which the render correctly
  hides. The first cut of the gate guard fired on it; the shipped one (one *outermost*
  hidden element, holding the page's *prose*, outside chrome landmarks) does not, and
  fidelity is unchanged. The country picker is real, but it hides nothing the page
  shows.
- **allbirds.com's product page** keeps its `<h1>`, price, colour and sizes in an
  `<aside>`, which the landmarks step strips. #149 keeps the one aside that carries the
  title. The boundary step still prefers the page's newsletter modal to the sheet on that
  page: short option lines each pay the block cost, and the modal's paragraph is prose.
  Not fixed; the shape is noted for the product-sheet work.
- **The product `min_run_share` floor is right where it is.** ascolour.com's sheet is
  15% of a page of colour swatches, the boundary refuses a run under 25% and falls open to
  everything (F1 0.079). Swept on WCXB dev with the product-sheet prune in place:
  0.25 → 0.635, 0.15 → 0.629, 0.10 → 0.631, 0.05 → 0.621, 0.02 → 0.620. The floor stays.
- **Common Crawl's index** answered a direct query (1–2 s, 1,952 addresses for
  vtu.ac.in) and then refused every connection from this address for hours. The listing
  is report-only and says "index did not answer" when it does not; nothing waits on it.

## 5. Boards, at the end of the night

- **Fidelity** (`main@c125991`): mean recall 0.998 over 22 scored sites, nothing below
  0.979, extra 0.004; identical after #148 except MDN's live page drifting against its
  cached oracle. Two oracles (columbia, w3c) were Cloudflare-blocked.
- **WCXB dev** (`main@7a883bd`, corpus re-cloned to the scratchpad): overall 0.864;
  article 0.944, documentation 0.930, service 0.852, forum 0.798, collection 0.705,
  listing 0.720, product 0.635 — unchanged by the night's engine changes.

## 6. Left for the owner

- Three PRs the loop did not open because they need a decision: a PDF reader (files are
  refused by policy today); `seed_from_common_crawl` on by default (off: a stale listing
  is full of 404s); deleting the four old `webgraph-*` worktrees and the Docker disk image
  (the loop is not allowed to delete).
- The product-page boundary on pages whose sheet is short and whose furniture is prose
  (allbirds, ascolour) — a research item, with WCXB dev as the board and `--worst
  product` as the list.
- The `README` in `docs/research/` §6: what Firecrawl is simply ahead on.
