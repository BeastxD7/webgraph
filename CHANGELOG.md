# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
