# lakshx.in: our crawl against Firecrawl's (19 Sep 2026)

The owner crawled lakshx.in in Firecrawl's playground (24 pages, one Markdown file each,
downloaded as a zip) and in our web UI (7 pages, one Markdown file), and asked why the
counts differed and whose Markdown was better. This is what the comparison found and what
was done about it.

## Why 7 pages and not 24

Not the engine. The browser's saved settings (`localStorage["webgraph.options.v1"]`, the
Settings page) held `crawl.max_depth = 1`: the home page and what it links to directly,
which on lakshx.in is exactly changelog, docs, terms, privacy, refund-policy and pricing.
The 17 `/docs/*` pages are linked only from `/docs`, so they were depth 2 and turned away.
The API with default settings found the same 24 pages Firecrawl did -- the site's sitemap
lists only the home page, so both engines found everything by following links.

The run page did say "209 past the crawl's depth", in a collapsed panel, while the summary
line said "every reachable page crawled". PR #168 puts the options on the address box,
shows what is in force as chips before a run starts, and makes the summary name the cap.

## Whose Markdown is better

Word coverage each way, per page, on the same 24 pages, in the mode the web UI uses
(rendered + plain fetch, whole page):

| pages | Firecrawl words | ours | theirs found in ours | ours found in theirs |
|---|---|---|---|---|
| home, pricing, terms, privacy, refund, changelog | 444–3,465 | 436–3,438 | 0.97–0.99 | 0.99–1.00 |
| 18 docs pages | 337–643 | 333–635 | 0.95–0.98 | 0.97–1.00 |

Near-identical text. What each side has that the other does not:

- **Firecrawl only**: a YAML front-matter block (`url:` / `title:`) -- the zip export in
  #168 adopts the convention; the card grid's *links* (`[The Chat Panel\\ \\ Talk to the
  agent…](…/docs/chat)`, ugly but the href is there). Ours emitted the card's title and
  description as plain text with no link -- fixed in this branch: the first block under a
  block-level `<a href>` carries the link, cleanly (`[The Chat Panel](…/docs/chat)`).
- **Ours only**: reading order recovered from geometry (and, on this site, wrong: see
  below); provenance per page; spacing between inline spans ("Tool browser_act Scope
  localhost only" where Firecrawl runs them together as "Toolbrowser\_actScopelocalhost");
  no `\_` escapes in identifiers (`db_query`, `wait_for`).
- **In a crawl (static-only strategy)** ours also removes the sidebar and "On this page"
  lists repeated across every docs page; Firecrawl keeps them on each. By design for a
  crawl; a single-page request keeps them.

## Engine bugs the comparison found, and what was done

1. **Backdrop image breaks the column cut** (#167). Every docs page lays a decorative,
   alt-less image under the first screen; that one box touched every gutter, no column cut
   was possible, and the sidebar's lower entries were read between the article's
   paragraphs -- in the owner's own downloaded file. A textless block whose box holds three
   or more others is now taken out of the geometry. Reading-order board 0.9929 -> 0.9931,
   0.934 -> 0.939 on the pairs where order matters.
2. **A nav link with the same words as its group label was dropped as a duplicate**
   (this branch). "Slash Commands" the label and "Slash Commands" the link: the link, the
   copy a reader can follow, went. A plain label followed by a link with the same words
   is two things now. Keeping *every* differently-linked copy was tried first and rejected
   by measurement (WCXB 0.864 -> 0.863, forum 0.798 -> 0.790, repeated blocks 2.5% ->
   8.4%); the narrow rule leaves WCXB at 0.864 (collection and listing -0.001).
3. **Card links lost** (this branch), as above.
4. **A false note on the run page** ("the sitemap names a different host") when the
   sitemap lists only the already-fetched home page (#168: `sitemaps.in_scope`).

## Product changes the owner asked for

- Options at the prompt (max pages, depth, path scope, robots.txt, rendering switches),
  the same store as the Settings page, with chips showing what is in force (#168).
- ".zip, a file per page" beside the single `.md`, host/path names, `url` and `title`
  front matter (#168).
