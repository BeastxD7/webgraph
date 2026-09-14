# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed (2026-09-14, PR #71)
- An old MediaWiki `editsection` strip (`[edit]` beside every heading and table row on
  cppreference.com, hidden by its stylesheet) is a heading control like `mw-editsection`:
  a quarter of that page's words, and the member-function tables emitted twice.
- A frameset's `<noframes>` body stands in only when no frame could be fetched; with the
  frames read it is not on the page (cs.cmu.edu repeated the title frame and a second
  table of contents).

### Fixed (2026-09-14, PR #69)
- A table or code block a page shows more than once stays more than once on a page the
  browser could not measure (a static fetch, a browser refused by a wall):
  columbia.edu/~fdc/sample.html shows one demo table four times and came out with one.
  A repeat sitting in a run that repeats the first copy's run — the mobile grid beside
  the desktop grid — is still a hidden twin and goes; so does a repeat with nothing
  between it and the first copy. Repeated *text* on an unmeasured page stays
  deduplicated: measured on WCXB and Zyte, keeping it by the same rule cost 0.0017 and
  0.003 (businessinsider.com carries its article three times, interleaved with different
  furniture); a rendered page keeps real repeats through their rectangles, as before.

### Fixed (2026-09-14, PRs #66, #68)
- `<li><p>…</p></li>` (DocBook, Sphinx, MediaWiki) yields list items: the item's first
  paragraph is the item, later paragraphs its continuation, indented under the bullet
  (catb.org's eight lists, tldp.org's HOWTO index) (#66; WCXB +0.0001).
- Links inside table cells survive into the pipe table (`Block.rich_rows`; craigslist's
  "best of" is a table of links) and a link that wraps nothing but an image keeps its
  target (`Block.link`, rendered `[![alt](src)](link)`; spacejam.com/1996's planets) (#68).

### Fixed (2026-09-14, PR #65)
- What the browser hid stays hidden through the static+rendered union: a block only the
  static fetch had, whose text the renderer laid out as `display: none` / `visibility:
  hidden`, is not "content the render lost" and stays out (php.net's hidden manual TOC,
  cppreference's hover menus, nasa.gov's mega-menu: 330 → 233, 254 → 135, 299 → 153
  blocks; live suite: allbirds precision 0.11 → 0.75, ikea 348 → 205 blocks, recall
  unchanged on every page).
- A fragment-href anchor whose text is only a permalink glyph (`¶`, `#`, `§`, `🔗`) is a
  permalink whatever its class; php.net's script-added `¶` no longer duplicates every
  heading.

### Added (2026-09-14, PR #65)
- `tools/runs_dashboard.py`: a dependency-free local page (`http://127.0.0.1:8765/`)
  showing every benchmark run on the machine — running / finished / failed, elapsed,
  a progress bar from the runner's own counter lines, the last output and the result
  tables. `tools/run_logged.py <label> -- <command>` starts a run with its command, pid,
  start and exit recorded beside the log so the state is exact.

### Fixed (2026-09-14, PRs #64, #67)
- A bot wall served to one of the two fetches (plain or browser) while the other got the
  real page is left out and named in `render_error`, instead of being merged into the
  page's text (columbia.edu/~fdc/sample.html: Cloudflare's "Performing security
  verification … Ray ID" sentences were presented as content). A wall beside a fetch
  with fewer than `MIN_PAGE_BESIDE_WALL_WORDS` (20) words of its own still raises
  `PageBlockedError` (old.reddit.com's login redirect: an empty logo and "Skip to main
  content" are not the page), as do walls on both sides.

### Fixed (2026-09-14, PR #63) — pre-CSS pages read whole
Found reading old and ugly pages against Chromium for the whole-page `markdown`, where
nothing may be lost. Boards: WCXB dev +0.0001, Zyte 0.945 → 0.945, WCEB 0.856 → 0.856
(cleaneval, the old-HTML corpus, 0.890 → 0.895), WebMainBench 0.7297 → 0.7319, live
suite unchanged.
- A `<frameset>` page was read as an empty JavaScript shell; its frames are fetched
  statically (same host, up to eight, two levels) and composed in frameset order
  (cs.cmu.edu/~rgs/alice-table.html: 0 → 307 words). `render_error` says so.
- Bare text under `<body>`, `<center>`, `<font>`, `<form>` and `<fieldset>` was emitted
  by nobody (textfiles.com word recall 0.787 → 1.0).
- `<br>` is a line break and `<br><br>` a paragraph break: an address keeps its lines
  (a Markdown hard break), a `<br><br>`-separated article becomes paragraphs, headings,
  captions and list items stay one line. Source newlines still collapse to spaces.
- A `<blockquote>` that holds structure (a table, a list, paragraphs) is walked into and
  each block inside carries `Block.quoted`, rendered `> ` per level, so an indented table
  is a table (columbia.edu/~fdc/sample.html).
- Found by measuring the above: split paragraphs came out reversed and, when the article
  sat inside one `<span>`, every heading ahead of every paragraph (AppleInsider); the
  orphan-run walk now goes through inline wrappers and flushes per container. Also on
  `main` all along: a data-table cell fused words across `<br>` and block children
  (`a<br>b` → `ab`).

### Fixed (2026-09-14, PRs #59, #60, #62)
- Hidden twins of visible text (CSS-module mobile/desktop copies) are matched as a group;
  screen-reader-only text is detected by its measured 1px box; deduplication keys ignore
  whitespace (linear.app 401 → 337 blocks) (#59).
- Opacity-0 elements are measured and ordered where they sit; text inside a collapsed
  `overflow: hidden` ancestor (an accordion) is slotted after its heading (#60).
- A closed `<dialog>` / `aria-hidden` modal is not on the page; hidden content nothing
  opens is dropped (karnataka.gov.in 9,270 → 726 words) (#62).

### Added (2026-09-14, PR #61)
- `tools/inspect_page.py`, `tools/inspect_corpus_page.py`, `benchmark/live/run.py` and
  `benchmark/wcxb/per_page.py`: the diagnostic commands the PR template's repro steps use.

### Added (2026-09-14, PRs #55, #57)
- `/api/text` and the page stream return `comments_markdown`: the comment thread found
  under the content, in page order, left out of `content_markdown` instead of thrown away.
  The extract view shows it as a collapsed section (#55).
- `include_hidden_text` on `/api/text` and `--include-hidden-text` on the CLI keep
  screen-reader-only labels, skip links and wiki edit controls for callers that want every
  string in the DOM; the default still strips them (#57).

### Changed (2026-09-14, PRs #54, #56)
- A single block contributes at most 400 words to the mean the adaptive block cost is
  drawn from; a 2,100-word contributor list no longer prices the page (#54).
- Product pages: seller, shop-policy, "Did you know?", payment and report-listing sections
  are pruned like reviews and related grids (#56; WCXB product +0.003).
- Benchmarks page: WCEB ranks the two output fields joined (0.883, first) and the content
  field alone (0.856, second); the diagnostic-variant row is gone.

### Changed (2026-09-13/14, PRs #48–#52)
- Extraction quality, measured on the corpus runners in `benchmark/`: WCXB dev routed
  0.855 → 0.861 (first of the published field, by 0.002), WCXB test 0.864 → 0.875, Zyte
  article-extraction 0.934 → 0.945, WCEB production path 0.852 → 0.856.
- A long block that restates what several other blocks already say (an `articleBody`
  microdata copy of the article, a reply quoting a whole post) is dropped (#48).
- Pre-HTML5 chrome names (`div#footer`, `div.nav`, `.main-menu`, …) are stripped; a rail
  never holds the page's `<h1>` or `itemprop="articleBody"`; camelCase cookie dialogs are
  consent (#49).
- The adaptive block cost ratio is 0.60 (was 0.70), re-swept after the structural steps
  changed what the boundary step sees (#50).
- A river of teasers at its own heading level ends where the article resumes, not at its
  first kicker (#51).
- The declared article body (`itemprop="articleBody"`, `entry-content`, `story-body`, …) is
  a structural scope after `<main>` and `<article>`; `Block.body_of` is new and `methods`
  gains `"article-body"` (#52).
- Benchmarks page: the WCEB row is the production path (0.856, second) rather than the
  comments-kept variant (0.874) it showed before; that variant is drawn as a reference
  line with the reason (Dragnet and cetd count comment threads as content).

### Changed (2026-09-13, PRs #13–#28)
- Extraction quality, measured on the corpus runners in `benchmark/`: WCXB dev routed
  0.820 → 0.853, WCXB test 0.856, Zyte article-extraction 0.895 → 0.928, reading-order
  discriminating pairs 0.505 → 0.936. `docs/SESSION-16-LIVE-HARDENING.md` lists every fix
  with its number and the experiments that were rejected.
- `Document.text` no longer includes image alt text or media placeholders; they remain in
  the Markdown. Callers that relied on alt text in `text` should read the Markdown.
- Screen-reader-only labels (`sr-only`, `visually-hidden`, …) are stripped at parse time.
- Comments under an article are stripped unless the comments are the page; forum pages keep
  them. `<aside>` landmarks are stripped unless they name themselves as callouts.
- Cookie-consent dialogs and named filter panels are stripped (`Block.widget`).
- Product pages get a sheet policy (reviews and related grids pruned, `Label: value` lines
  kept); product and collection pages refuse a run under a quarter of the page.
- The renderer marks floats (`data-wg-float`) and hidden elements (`data-wg-hidden`); floats
  are read as one unit and hidden twins dropped.
- MediaWiki pages are routed by namespace; edit-section strips are removed.
- Repository: pull request and issue templates, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  `SUPPORT.md`, `CODEOWNERS`, Dependabot; `CONTRIBUTING.md` states the test-per-fix and
  measurement rules.

### Added
- Extraction engine: geometric reading-order recovery, rich Markdown rendering, JSON-schema
  mapping with provenance, technology fingerprinting, unlimited route discovery and
  cross-page site-chrome removal.
- FastAPI service exposing single-page extraction and a streamed whole-site pipeline.
- Next.js 16 front end: photographic landing page and a dedicated `/extract` run view with
  Discovered / Queued / Extracted / Failed tabs over the live crawl.
- Benchmarks for extraction quality and for route discovery against a real-browser oracle.
