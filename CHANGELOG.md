# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Web UI (2026-09-19, PR #170)
- Removed: the example-site chips (vtu.ac.in, docs.python.org, …) under the address box.
  Owner's request; the prompt is the address, the mode and the run's options.

### Engine (2026-09-19, PR #169) -- a link is not its label; card links
- Fixed: a plain label followed by a link with the same words is two blocks, not a
  duplicate -- lakshx.in's sidebar says "Slash Commands" as a group label and again as the
  link under it, and the link was the copy dropped. Only that shape: two links with the
  same words and different targets stay one (keeping both cost WCXB 0.864 -> 0.863 and
  tripled repeated blocks). WCXB dev 0.864 unchanged (collection, listing -0.001).
- Fixed: a card -- an `<a href>` around a title and a description in blocks of their own
  -- gives its link to the first block under it (`[The Chat Panel](…/docs/chat)`); the
  address a reader clicks to was lost before.

### Web UI, engine (2026-09-19, PR #168) -- options at the prompt; a file per page
- Added: an **Options** button on the address box opens the run's options -- max pages,
  max depth, within path, exact host, include/exclude paths, respect robots.txt, the
  rendering switches, the fetch timeout -- with the engine's defaults as placeholders,
  saved to the same store as the Settings page. What is changed shows as chips under the
  address ("runs with · max depth 1 ×") before the run starts. The owner crawled
  lakshx.in with a saved depth of 1 and got 7 pages of 24 with nothing on the prompt to
  say why.
- Added: **.zip, a file per page** beside **Download .md**: one Markdown file per page,
  named by host and path, with `url` and `title` front matter. Written in the browser
  (`lib/zip.ts`, stored entries, no dependency).
- Fixed: the run summary names a depth cap that applied -- "every page within depth 1
  crawled · 209 addresses were past the depth cap" -- instead of "every reachable page
  crawled"; the `done` event's `limits` carry `max_depth`.
- Fixed: a sitemap that lists only the home page no longer reads as "names a different
  host": the `discovery` event's `sitemaps.in_scope` counts what the scope admits,
  apart from what was queued (`seeds`).

### Engine (2026-09-19, PR #167) -- a backdrop is not a column
- Fixed: a textless block whose box holds three or more other blocks -- a decorative
  background image laid under the first screen -- is taken out of the geometry before the
  reading order is cut. lakshx.in/docs/* read the sidebar's lower entries between the
  article's paragraphs on every page; reading-order board 0.9929 -> 0.9931 overall,
  0.934 -> 0.939 on the pairs the two orderings disagree on.

### Engine (2026-09-19, PR #166) -- slides are not hidden menus; a 404 to the browser
- Fixed: a hidden element with a *showing* twin under the same parent (same tag, same
  leading class, outside `nav`/`header`/`footer`) is a carousel slide, not hidden matter,
  and its static copy stays in the union. blueheroncap.com's three testimonials, of which
  the render showed one: 300 -> 468 words, truth recall 0.478 -> 0.991.
- Fixed: a 404/410 served to the browser is a page that does not exist (`PageMissingError`)
  unless the plain fetch was served the page, in which case the browser was the refused
  side. es.ogs.ny.gov/veterans came back as the four words of an nginx 404 page.
- Fixed: HTTP 402 and "experiencing an access issue" are refusals (investopedia.com).

### Engine, API, Settings (2026-09-19, PR #165) -- robots.txt is honoured on request
- Changed: `respect_robots` defaults to **off** for a single page (`PAGE_RESPECT_ROBOTS`,
  `FetchConfig`, the API's `fetch`) and for a crawl (`CRAWL_RESPECT_ROBOTS`, `SiteConfig`,
  the API's `crawl`, Settings). The engine explores and reads every page it can reach; a
  caller who wants the site's rules obeyed sets the switch. Unchanged: politeness (one
  page a second per host, `Crawl-delay`), the robots file being read for its sitemaps,
  and the Site Report, which always obeys the file because it measures what the site
  declares. Owner's decision.

### Web UI and SDK (2026-09-19, PR #164) -- the whole page is the default
- Changed: the extract views open on **Full page**; "Content only" is the opt-in. The SDK
  docs, the package README and the `webgraph` docstring show `to_markdown(page.document)`
  and `event["markdown"]` as the default and `select_content` / `content_markdown` as the
  reduction a caller opts into. The API is unchanged: `/api/text` and the crawl carry both.

### Engine (2026-09-19, PRs #152-#155)
- Added: `from webgraph import resolve_page, build_document, to_markdown, select_content,
  stream_site, read_metadata` is the package's stable surface; `webgraph.__version__`. The
  engine builds as a wheel with its licence, README and data files, and
  `.github/workflows/publish.yml` publishes a `v*` tag to PyPI by trusted publishing (#155).
  The distribution name is still open: `webgraph` on PyPI belongs to another project.
- Changed: a static-only block under a client-template directive (`v-if`, `x-show`,
  `ng-if`, ...) that the browser did not build stays out of the union -- never built, not
  lost (`Block.templated`). Hidden tables are matched cell-wise against the render's hidden
  matter; a frame the browser gave no box, or hid, is a beacon (#152). The fourth rule
  of #152 -- a `position: fixed` box wholly outside the viewport is off-screen -- was
  withdrawn the same day: on the 300-page random-web sample it cost a store that keeps its
  size chart, delivery and payment in slide-in panels 60% of its words. An off-canvas panel
  a button opens is a collapsed tray, not hidden matter (#160).
- Added: `click_collapsed` (RenderOptions / `RenderConfig` / Settings, on by default): after
  the page is measured, tabs, accordions and "show more" panels wired in JavaScript alone
  are clicked open with the page's own `click()` and the page measured again, on the same
  page -- a control that navigates, empties the page or opens a popup costs nothing but the
  click, and everything opened is forced visible so a tab set ends with every panel showing.
  Every measurement's marks are cleared before the next. w3schools' JS tabs open (+2
  panels), amazon.com's review sections open (+1,240 words); fidelity board unchanged (#163).
- Changed: `reveal_collapsed` (RenderOptions / `RenderConfig`) opens tab panels
  (`role="tab"` → `aria-controls`) and panels a control names (`data-bs-target`,
  `data-target`, `href="#id"`) as well as `<details>` and ARIA disclosures, never inside
  `nav`/`header`/`footer` or a menu, and stamps each opened panel `data-wg-revealed`. **On
  by default** (was off, "until measured"): fidelity board recall unchanged, extra +0.001
  mean, +0.027 at most on arxiv.org's own bibliographic-tools tabs (#162).
- Changed: a `<select>`'s choices are one block of the whole page (`Block.widget ==
  "select"`, tag `select`, choices joined by ` · `) and never part of the content:
  Chromium shows them, and dclt.co.uk's news listing kept 118 of its 734 words in two
  filter dropdowns. WCXB unchanged; fidelity board php.net and cppreference 0.99 -> 1.00.
  `content_hash` changes once for pages that carry a dropdown (#161).
- Changed: cards nest in the reading order. Inside a card, a row of side-by-side cards is
  read one card at a time; stacked or overlapping siblings are left to geometry (#153).
- Style: the engine is `ruff format`ted, and CI checks it (#154).

### Changed (2026-09-17, PR #128) -- the brand displays as "WebGraph"
- Asked directly to capitalize the site's own brand name, having earlier confirmed the
  lowercase "webgraph" style was a deliberate, consistent choice (site title/metadata,
  header wordmark, docs) distinct from the already-capitalized "WebGraph" naming the
  specific graph feature at `/graph`. Overridden on request.
- Changed: `app/layout.tsx`'s title/OG metadata, the header `Wordmark`, the docs sidebar's
  wordmark, `useTabTitle`'s tab-title suffix, the OG image's alt text, and the opening
  sentence of the three main "what is this" doc pages (`docs/index.mdx`,
  `getting-started/index.mdx`, `how-it-reads-a-page/index.mdx`).
- Deliberately did **not** touch the much larger set of lowercase `webgraph` mentions
  across the docs corpus, code comments and benchmark data: CLI commands (`webgraph site`,
  `webgraph diff`), Python module paths (`webgraph/config.py`, `webgraph.resolve`),
  storage/env keys (`webgraph.options.v1`, `WEBGRAPH_KG`), and -- the ones that would be
  an actual accuracy bug to capitalize -- literal quotes of the real, lowercase
  `ROBOTS_AGENT_TOKEN` this client sends in its own User-Agent and robots.txt group name.
  Distinguishing "this sentence names the product" from "this sentence quotes a real
  lowercase value" correctly, one at a time, across ~40 files was a much larger and more
  error-prone task than the brand-display surfaces actually asked for.
- Flagged, not resolved here: the site's own general brand and the specific "WebGraph"
  graph feature (`/graph`, its own nav entry and docs section) are now the same word.
  Real products do share a name with their flagship feature, but it's worth knowing this
  PR created that overlap rather than discovering it as a surprise.
- Verified visually: header wordmark, docs sidebar wordmark, tab title and the docs
  landing page's own heading all confirmed rendering "WebGraph" together in a live build.
  `tsc --noEmit`, `eslint`, `next build` all clean.

### Changed (2026-09-17, PR #126) -- tech-stack marks show each brand's own colour
- Asked directly: monochrome, tinted like the surrounding text, was a deliberate choice
  (`TechIcon.tsx`'s own docstring: "so a stack of eight technologies reads as one list and
  not eight logos shouting"). Overridden on request -- eight technologies should show as
  eight recognisable logos, with their own names beside them.
- `lib/tech-icons.ts`: `TechMark` carries Simple Icons' own `hex` now (`null` for the
  generic glyph, which has no brand colour). `TechIcon.tsx` fills a real mark with it
  instead of `currentColor`.
- Checked rather than assumed that this wouldn't quietly break in dark mode: 15 of the
  102 mapped marks (Next.js, Vercel, Three.js, shadcn/ui, Mapbox, ... -- computed
  programmatically by luminance, not eyeballed) are pure or near-black, a deliberate choice
  by those brands themselves, who invert to white against a dark background everywhere they
  show it, their own docs included. Left as literal black here they would have vanished
  into this site's own dark theme. `lib/theme.ts` gained `resolvedTheme()` -- light or dark
  as actually rendered right now, resolving "system" the same way the boot script already
  does for the `data-theme` attribute -- and `TechIcon` substitutes a light near-white for
  any mark this dark specifically when the page is in its dark theme, unchanged in light
  mode and unchanged for every mark with real colour to show.
- Verified visually, not just by inspecting hex values: a small standalone harness
  (esbuild-bundled, not part of the repo) rendered a dozen real marks -- including several
  of the near-black ones -- through the actual `TechIcon` component, toggled through the
  site's real theme mechanism (`localStorage` + a dispatched `storage` event, the same path
  a real toggle click takes) to confirm both directions: real brand colours unchanged and
  legible in both themes, and the near-black marks switching to the light substitute only
  in dark mode, side by side with the unaffected coloured ones so the two behaviours are
  visibly distinguishable from each other, not just individually correct.
- 1 new test (`tech-icons.test.ts`): every real mark carries a valid `#rrggbb` hex; the
  generic glyph carries none. `tsc --noEmit`, `eslint`, `next build`, and the existing
  8-test `tech-icons` suite all clean.

### Added (2026-09-17, PR #127) -- the light-theme hero's clouds drift on their own
- The day scene has always textured its globe with a real cloud layer (`clouds-2k.jpg`,
  bound as `uClouds`), but it turned rigidly with the ground beneath it -- a `uRot` that
  itself barely moves outside an interaction (hovering an example site, typing an address),
  so the deck read as painted onto the planet rather than weather moving over it.
- `field/shaders.ts`: the cloud texture (and its shadow-offset sample, kept relative to the
  now-drifted deck rather than the terrain under it) is read at its own longitude, `uRot`
  plus a slow, independent `uTime`-driven term -- real weather has no fixed longitude to
  share with a rotating planet. The rate is deliberately gentle: perceptible over the time
  someone actually looks at the hero, not a visibly spinning texture.
- Verified visually rather than assumed: the WebGL scene pauses itself when the tab isn't
  the OS-focused window (`document.visibilityState`), which an automated browser reports as
  backgrounded even while dispatching real input -- confirmed directly
  (`document.visibilityState === "hidden"` while `hasFocus()` was still `true`), so a
  temporary, uncommitted bypass of that one check was the only way to get a real animated
  screenshot out of this tool chain; reverted before committing, and the two before/after
  crops it produced (10+ seconds apart, cloud detail visibly shifted, base terrain
  unchanged) are what confirmed the drift works rather than just compiles. No shader
  compile errors in the browser console; `tsc --noEmit`, `eslint`, `next build` clean.

### Added (2026-09-17, PR #125) -- both containers, one VM: a frontend Dockerfile and a `docker-compose.yml`
- Asked directly for a Docker path to a plain VM (Oracle Cloud's free tier named as the
  motivating example) rather than Cloud Run + Vercel, for both the API and the frontend.
  The API side already existed in full (root `Dockerfile`, `deployment/docker.mdx`); the
  frontend had no container story at all.
- `apps/web/Dockerfile`: tried `output: "standalone"` first, for the same "install once,
  copy only the minimum" shape as the root Dockerfile -- but under this project's pnpm
  workspace, Next.js's file tracer silently dropped two of its own runtime dependencies
  (`@swc/helpers`, then `@next/env`, found one after the other by running the traced
  server and reading which `Cannot find module` came back each time), even with
  `outputFileTracingRoot` pointed at the workspace root. A tracer that must be hand-patched
  dependency by dependency as they turn up missing at container start is not something to
  ship, so the image instead does a full `pnpm install --prod`, using the exact dependency
  resolution `pnpm build` already proves correct -- a larger image, deliberately, for one
  that starts correctly the first time.
- Confirmed directly, and now documented in the Dockerfile itself: `WEBGRAPH_API_PROXY`
  looks like a runtime setting but has to be a build `ARG` like `NEXT_PUBLIC_API_BASE` --
  Next.js resolves `rewrites()` once into `.next/routes-manifest.json` at `next build` and
  never re-reads it at `next start`. Verified with a real reverse-proxy round trip (a stub
  HTTP server standing in for the API): built without the arg, `/api/*` fell through to
  Next's own 404 page regardless of what was set at `docker run`; rebuilt with it set, the
  same route proxied correctly, and the app's own `/api/search` (docs search) still won
  where it should.
- `docker-compose.yml` (repository root): both containers with one command, `web` built
  with `WEBGRAPH_API_PROXY` pointing at `api`'s address on Docker's own network so the
  browser only ever talks to `web`'s port -- `api` is not published to the host at all,
  and the two never need CORS between them. A named volume persists `WEBGRAPH_GRAPH_DIR`
  across restarts. `apps/web/Dockerfile.dockerignore` -- not the root `.dockerignore`,
  written for the *other* Dockerfile and excludes `apps/web` entirely -- keeps the frontend
  build context small; both images build from the repository root, since the pnpm
  workspace's lockfile lives there.
- `content/docs/deployment/vm.mdx`: a walkthrough for a generic VM, Oracle Cloud's Always
  Free Ampere shape as the concrete no-credit-card example (with its one real gotcha noted:
  free capacity sometimes runs out in a given Availability Domain). Cross-linked from the
  existing `docker.mdx`. New Makefile targets `docker-build-web`, `compose-up`, `compose-down`.
- Verified without a real `docker build` -- the host had under 1.2 GB free disk for most of
  this work, and a Node base image plus a fresh `node_modules` was not a safe thing to
  attempt there. Instead: a `pnpm install --prod` into an isolated directory (using pnpm's
  own content-addressable store, so it cost megabytes rather than the ~500 MB `du` reports
  for `node_modules`) plus an APFS copy-on-write clone (`cp -c`) of the real `.next` build
  output, assembled into the exact layout the final Docker stage produces, then run for
  real with `next start` -- which is how the two packaging bugs above were actually caught
  and fixed, not guessed at. `docker compose config` resolved the compose file's final,
  merged configuration cleanly (this needs no running daemon). A real `docker build`/`docker
  compose up` end-to-end run is flagged as not yet done, explicitly, rather than silently
  skipped -- worth doing once there's headroom to try it safely.

### Fixed (2026-09-17, PR #124) -- the docs sidebar's own theme toggle no longer disagrees with the rest of the site
- Reported live: "theming is not working in docs sidebar." Reproduced by switching theme
  from the docs shell's own light/dark control and reading `<html>`'s attributes directly:
  the docs shell's `class` (`.../.dark`) and `localStorage` both updated correctly, but
  `data-theme` -- the attribute `lib/theme.ts` and every one of the site's own dark-mode
  styles actually key off -- stayed on its old value. Fumadocs' `RootProvider` wraps
  `next-themes`, and `next-themes` defaults to writing a `class`, which nothing else in
  this app reads; the docs shell had never told it to use `data-theme` instead.
- `app/docs/layout.tsx`: `RootProvider`'s `theme` now sets `attribute: "data-theme"` and
  `storageKey: "theme"` explicitly, so the docs shell's provider and the rest of the site's
  own toggle (`lib/theme.ts`) read and write one shared preference through one shared
  attribute, in both directions, instead of two mechanisms that could silently disagree.
- `app/docs/docs.css`: the dark palette's own gate moved from `.dark:has(#nd-docs-layout)`
  to `[data-theme="dark"]:has(#nd-docs-layout)`, matching the new attribute. Checked that
  nothing else depended on the old `.dark` class: fumadocs' shipped component CSS themes
  entirely through `--color-fd-*` custom properties (no `dark:` Tailwind utility classes in
  its compiled output), and grep found no `dark:` utility used anywhere in this project's
  own docs-scoped source (`components/docs`, `content/docs`, `app/docs`) -- so retargeting
  the one selector that does key off it is the complete fix, not a partial one.
- Verified against a production build (`next build && next start`, not `next dev`, to rule
  out the dev-mode CSS reordering PR #122 already fixed as a confound): cleared storage,
  confirmed system-default dark rendered correctly on `/docs`; switched to light from the
  docs sidebar's own control and confirmed `data-theme` updated immediately (previously
  stuck); navigated to `/` and confirmed the main site picked up light too; switched back to
  dark from the *site's own* header toggle on `/` and confirmed `/docs` opened dark as well
  -- both directions verified, not just the one originally reported. `tsc --noEmit`,
  `eslint`, `next build` all clean.

### Fixed (2026-09-17, PR #123) -- a `>` starting a line no longer reads as a blockquote it never was
- Asked directly: does the engine handle `>`/`&gt;` correctly? Traced through `dom/blocks.py`
  (lxml decodes both a raw `&gt;` entity and a literal `>` to the same character while
  parsing -- no divergence there) and `render_markdown.py` (the general escape pass,
  `_ESCAPE`, is gated behind `escape_text`, which defaults off and is never turned on
  anywhere in the real pipeline). A page's own paragraph text that happens to start with a
  literal `>` -- "&gt; 90% pass on the first try" is common phrasing -- was written straight
  into the output Markdown with no escaping at all. A leading `>` is Markdown's blockquote
  marker unconditionally, so any downstream reader, this repo's own web preview included,
  cannot tell that paragraph apart from an actual quote.
- `render_markdown.py`: `_escape_leading_gt` backslash-escapes a `>` only when it opens a
  line (`^(\s*)>`, multiline), leaving every other `>` alone -- unambiguous in Markdown, so
  escaping it would only add a visible backslash with nothing to prevent. Applied
  unconditionally in `_text`/`_body` (both the plain and the rich-inline paths), the same way
  the currency-dollar escape already is, and not gated behind `escape_text`: this is not a
  style choice, it prevents a structural misread. A genuine blockquote is unaffected --
  `_render_block` adds its own literal `> ` prefix from `block.quoted` *after* this runs, on
  a block whose own content never starts with the marker, so the two never collide.
- 7 new tests (`TestLeadingGreaterThan`): a leading `&gt;`/literal `>` escaped in a paragraph,
  a heading, a list item and the rich-inline form; a mid-line `>` left untouched; a real
  `<blockquote>` still renders as a plain `> `, not doubled. Full engine suite (1516) and API
  suite (95), ruff and mypy all green. No corpus re-score: unlike the currency-dollar escape,
  there is no false-positive/true-positive trade-off to tune here -- a `>` opening a line
  outside an actual quote is never legitimate Markdown, so there is nothing to measure a
  trade-off against.

### Fixed (2026-09-17, PR #122) -- the header's pill loses its curve after a long dev session
- Reported live: the "Light"/"Run a site" grouped pill in the floating landing header rendered
  with a squared-off corner where "Run a site" sat, instead of one smooth pill boundary --
  worst and most obvious in dark mode, and reproducible after navigating to `/docs` and back.
- Root cause: `rounded-pill` and `rounded-md` are both generated from this project's own
  `--radius-*` theme keys (`app/globals.css`), landing in the same Tailwind `utilities` layer.
  A clean production build ordered them correctly (`rounded-pill` after `rounded-md`, so it
  wins the tie), but the dev server's incremental Tailwind/Turbopack compilation had, after
  enough edits and route visits in one long session, re-emitted `.rounded-md{...}` a second
  time *after* `.rounded-pill{...}` -- so `rounded-md`'s 6px radius won the cascade tie on the
  button that carried both classes, and Turbopack loading `/docs`'s own stylesheet triggered a
  fresh round of this reordering, explaining why it broke specifically after that navigation.
- `app/globals.css`: added `.pill-shape { border-radius: var(--radius-pill); }` as plain,
  unlayered CSS (not `@utility`, not a `--radius-*` theme key) -- per the CSS Cascade Layers
  spec, unlayered rules always beat anything in a `@layer` block regardless of source or
  generation order, so this is immune to the dev-mode reordering by construction rather than
  by hoping the generator behaves consistently. All nine `rounded-pill` call sites (`Chip.tsx`,
  `SitePrompt.tsx`, `BuildPanel.tsx`, `SiteHeader.tsx`) now use `pill-shape` instead.
- `app/docs/layout.tsx`: the docs sidebar's wordmark used `font-extrabold` with no explicit
  text colour, one step heavier than the landing header's `Wordmark` component
  (`font-bold text-ink`) -- reported as "the docs sidebar logo looks off" from the landing
  page's. Matched to `font-bold text-ink`.
- Verified visually: an isolated `next dev` instance on a spare port (the owner's own :3000
  left untouched), dark theme, before/after zoomed screenshots of the pill showing a clean
  curve with no squared corner, confirmed stable across a `/` → `/docs` → `/` round trip: and
  the docs sidebar wordmark's weight matching the landing header's side by side. `tsc --noEmit`,
  `eslint`, `next build` all clean.

### Fixed (2026-09-17, PR #121) -- `\label`/`\eqref` no longer show up as visible garbage in the preview
- Reported live, right after #120 shipped: a numbered `\begin{equation}...\label{eq:eq2}\end{equation}`
  rendered its `\label{...}` as KaTeX's own red "unknown command" text followed by its argument
  parsed as stray math variables ("eq : eq2"), and an `\eqref{eq:eq2}` elsewhere in the prose
  rendered the same way. Both are correct, faithful LaTeX -- MathJax's numbering/cross-reference
  system understands them; bare KaTeX has no notion of either, since it renders one formula in
  isolation with no page-wide label registry.
- `lib/markdown.tsx`: `resolveEquationLabels` scans a page's full Markdown once for `\label{X}`
  in document order and numbers them 1, 2, 3... (the same numbers the page's own MathJax
  assigned, since our extraction faithfully preserves order); `resolveLabelsAndRefs` then strips
  `\label{...}` before a formula reaches KaTeX (the number it defines is already carried as
  separate extracted text right next to the formula -- MathJax writes it as its own DOM node --
  so also drawing it via a KaTeX `\tag` would draw it a second time, exactly the "shown once raw,
  once rendered" failure #119 fixed for MathJax's own duplicate) and rewrites `\eqref{X}`/`\ref{X}`
  to the resolved number as plain upright text (`\text{(N)}`), falling back to the raw label
  (`(eq:eq2)`) for a dangling reference to something outside the extracted page rather than
  guessing a number.
- A small "ⓘ" next to the "Σ LaTeX math" badge (`components/ui/MathBadge.tsx`, now shared by
  `SinglePageRun.tsx` and `PageRow.tsx` rather than duplicated inline) names KaTeX as the
  renderer on hover, since the site's own math renderer (often MathJax) and ours can differ in
  what LaTeX they support.
- Verified with the same esbuild+jsdom harness as #120, rebuilt against the real Lamar page
  content (both labelled equations plus the `\eqref` referencing the first one, plus a synthetic
  dangling reference): no visible `\label`/`\eqref` text or stray math-mode garbage, the two
  references resolve to "(1)" and "(2)" in document order, the dangling one falls back to its
  raw label, and no `katex-error` spans appear. `tsc --noEmit`, `eslint`, `next build` all clean.

### Added (2026-09-17, PR #120) -- the web app's own Markdown preview now typesets `$...$` math
- The engine has extracted correct LaTeX for `$...$`/`$$...$$` math since #118/#119, but the
  web app's own preview (`lib/markdown.tsx`) had no math renderer at all -- it is a
  hand-written, `dangerouslySetInnerHTML`-free React renderer, so `$\pi r^2$` passed through
  as the literal six characters. Reported live: a website's own MathJax rendering looked
  right, but our preview showed raw LaTeX source "left, right and all". Two independent
  external Markdown previewers were checked as a control -- markdownlivepreview.com (no math
  support, same raw-text failure) and StackEdit.io (KaTeX-based, rendered correctly) -- which
  confirmed the extraction was already correct and the gap was specific to our own preview.
- `lib/markdown.tsx`: `inline()` now recognises `$$...$$` and `$...$` (an unescaped opener,
  `\$` stays literal, matching this file's existing backslash-escape convention) and typesets
  them with KaTeX, `trust: false` -- the default -- so commands that could reach outside the
  page (`\includegraphics`, `\href`, `\url`) are refused and rendered as inert text rather
  than acted on. Invalid LaTeX renders as KaTeX's own error span rather than throwing.
- KaTeX's `renderToString` returns an HTML *string*, which would otherwise be the one place
  this file breaks its own "no `dangerouslySetInnerHTML`, ever" rule. Instead that string is
  walked with the same DOMParser-plus-allowlist approach already used for tables -- the
  allowlist here is just `<span>`, `<svg>` and `<path>`, the only elements KaTeX's default
  (non-`trust`) HTML output emits -- so no HTML string reaches the DOM unchecked, for math
  any more than for tables.
- A small "Σ LaTeX math" indicator now appears next to the Markdown/Preview toggle
  (`SinglePageRun.tsx`, `PageRow.tsx`) whenever a page's Markdown contains math, explaining
  in the raw "Markdown" view that the `$...$` seen there is LaTeX source, not garbled text,
  and pointing at the "Preview" toggle where it now renders typeset.
- Verified against a throwaway esbuild+jsdom harness (not part of the repo) exercising the
  real KaTeX/DOMParser path end to end: inline and display math typeset correctly, an
  escaped `\$5` stays literal, `\href{javascript:...}` is refused rather than becoming a real
  anchor, malformed LaTeX renders KaTeX's error span instead of throwing, and the actual
  formula extracted from tutorial.math.lamar.edu (the page this was reported against)
  renders as KaTeX rather than visible raw LaTeX. `tsc --noEmit`, `eslint`, and `next build`
  all clean; this project's own `node --test` runner cannot execute `.tsx`/JSX today, so
  this is not (yet) a committed automated test -- flagged as a gap, not silently skipped.

### Fixed (2026-09-17, PR #119) -- a formula no longer appears once as raw source and once converted
- A page that ships mathematics as literal LaTeX -- almost every MathJax- or KaTeX-rendered
  page does, since that source is what the library scans the DOM for -- writes it directly
  into its static HTML as plain text: `\(x = a\)`, `\[\frac{a}{b}\]`. A static fetch, or a
  render whose JavaScript never ran, saw exactly that: not math, a paragraph with odd
  backslash punctuation. Once a browser *did* run and #118 converted the rendered side to
  `$x = a$`, the two disagreed on delimiter -- and, since the rendered side was a
  reconstruction from a hidden MathML tree rather than the real source, sometimes on the
  LaTeX itself too -- so the union's block matching (identity by normalised text) saw two
  different blocks and kept both. Found live on tutorial.math.lamar.edu, reported by the
  owner while validating #118: every formula in the article appearing twice, the raw
  `\(...\)`/`\[...\]` source once and the engine's own `$...$` once.
- `dom/blocks.py`: `normalize_math_delimiters` rewrites a page's own `\(...\)`/`\[...\]`
  as `$...$`/`$$...$$` in plain text (skipping `<code>`, `<pre>`, `SKIP_TAGS`, so an
  example of the syntax itself is not mistaken for math), independent of whether a render
  happens at all.
- `dom/math.py`: `mathjax_source_latex` reads MathJax v3's own `data-latex` attribute --
  the exact, unreconstructed source the author wrote, sitting right there on the visible
  `<mjx-math>` sibling of the hidden assistive copy -- in preference to walking that
  hidden copy's MathML. Confirmed live: `data-latex="x = a"`, character for character the
  page's own source. This is both more faithful on its own (the reconstruction produced
  working but uglier LaTeX -- `\underset{h\to0}{lim}` for what the author wrote as
  `\mathop {\lim} \limits_{h \to 0}`) and, paired with the delimiter normalisation above,
  what lets the union recognise the static paragraph and the rendered one as the same
  formula instead of keeping both. KaTeX has no `data-latex` and is unaffected -- its
  `<annotation>` cascade already read the author's TeX.

### Fixed (2026-09-17, PR #118) -- formulas keep their structure, and MathJax/KaTeX stop doubling every equation
- **Plain `<sup>`/`<sub>` are no longer stripped to bare text.** `H<sub>2</sub>O` and
  `cm<sup>2</sup>` -- the overwhelming majority of chemistry and mathematics notation on
  the web, which uses neither MathML nor an equation editor -- were rendered as "H2O" and
  "cm2", the formatting silently lost. `dom/rich.py` now maps a script's content to the
  exact Unicode superscript/subscript character where the "Superscripts and Subscripts"
  block (U+2070-U+209F) or the 2010 Latin Subscript Small Letters define one (digits,
  `+ - = ( )`, `n`, and that letter set): the formula survives as plain, portable text --
  `H₂O`, `cm²`, an ion's charge (`Fe³⁺`), an isotope's mass number before its
  symbol (`²³⁵U`) -- correct in a terminal or a search index, not only where the
  Markdown is rendered as HTML. A character with no exact form (most letters, `x<sup>k</sup>`)
  keeps its tag verbatim as inline HTML rather than losing the distinction, the same choice
  a preserved table's own markup already made for a cell's formula. Case is never folded --
  a Unicode subscript exists for `a`, not `A`, and guessing they mean the same thing is
  exactly what this must not do. Docs: `/docs/how-it-reads-a-page/markdown#scripts`.
- **`<math>` gains two MathML constructs it previously dropped to plain concatenation:**
  `mmultiscripts`/`mprescripts` (nuclear notation -- an isotope's mass and atomic number
  both preceding the element, `{}_{92}^{235}U` -- and multi-index tensors) and `menclose`
  (`\sqrt{}`/`\boxed{}` where the notation has a plain-LaTeX equivalent; the content is kept
  even where it does not, without claiming an enclosure -- `longdiv` -- that was not drawn).
- **MathJax v3 and KaTeX each keep a real, hidden `<math>` beside a visible HTML/SVG
  rendering of the identical formula**, for screen readers. Converting only the hidden copy
  -- the obvious fix, and previously what happened -- left the visible half standing next
  to it: every formula on a MathJax- or KaTeX-rendered page appeared twice. Found live on
  tutorial.math.lamar.edu (17 Sep 2026): the definition of the derivative read once as the
  page's own (already-imperfect) Unicode rendering and a second time as a phantom
  `\underset{h\to0}{lim}...` reconstructed from the hidden copy, malformed in ways neither
  the author nor MathJax's own output ever produced (`f^'` for `f'`; a fraction with no
  bar). `dom/math.py` now walks up from a converting `<math>` to find the ancestor that
  holds *both* halves (MathJax's `<mjx-container>`, KaTeX's `.katex` span) and replaces
  that instead, so the visible duplicate goes with it. The hidden copy is still the
  preferred source when it is one -- KaTeX's carries the author's own TeX in an
  `<annotation>`, the most faithful source there is -- only the extra rendering is removed.

### Fixed (2026-09-17, PR #117) — an empty page after a render is described as what it is
- `resolve.py`: when the browser ran and the document still has no readable text, the
  refusal now says so -- "a browser rendered the page and it still has no readable text
  (N bytes of markup); the site is serving an empty page to automated browsers -- most
  often a silent bot check" -- instead of the shell message's "rendering was not used for
  this request", which was untrue on that path (amazon.in through the share link: an
  11.6 KB static shell and an empty rendered document). `PageShellError.rendered` records
  which case it was. The static-only wording is unchanged
  (`TestEmptyAfterRender`, 2 tests).

### Fixed (2026-09-17, PR #116) — link previews get a real image URL
- `metadataBase` is set from `NEXT_PUBLIC_SITE_URL` (build time; default the dev server), so
  `og:image` / `twitter:image` are absolute URLs on the public origin. Without it Next wrote
  `http://localhost:3000/opengraph-image.png`, and Discord's embed asked the reader's own
  machine for the picture and showed none (the owner's report). `openGraph.siteName`,
  the full title and `twitter.card=summary_large_image` are set; the social image is a
  156 KB JPEG instead of a 726 KB PNG. Docs: `/docs/deployment/configuration`.

### Added (2026-09-17, PR #115) — technology marks beside detected names
- Wherever the UI names a technology the engine detected, its mark now sits beside the name:
  the Site Report's Stack section (`ReportView`), the crawl's "Technology detected" panel
  and the pipeline's "Technologies identified" row (`TechnologyPanel`, `LivePipeline`), and a
  page run's framework chips (`SinglePageRun`). The rules: one style for every mark -- Simple
  Icons (CC0, 24-unit grid, one colour) tinted with our tokens (`text-muted` beside ink text),
  never the official multicolour logos; icon + name always, the icon decorative
  (`aria-hidden`) and never alone; a technology with no mark in the set gets one neutral
  glyph, a cube outline in the site's 1.5 px stroke, never a neighbouring brand (Framer's for
  Framer Motion, Astro's for Starlight, LottieFiles' for Lottie were each declined); only
  where *we* name a technology, never inside extracted page content; and a one-line note
  under each list -- "Marks are trademarks of their owners, shown to identify the detected
  technology." -- repeated in `public/ASSETS.md`. The landing names vendors only in prose
  ("Vendor named: Cloudflare, AWS WAF, …" in `RefusesDrops`) and is another agent's, so it
  is untouched.
- `lib/tech-icons.ts` maps 154 names -- every name the engine can emit from
  `profile/technology.py` (rules, implications, runtime categories), `fetch/js/collect.js`
  (runtime probes) and `profile/fingerprint.py` (the lowercase framework hints) plus the
  usual variants (Next / Next.js, Wordpress, HTML / HTML5, Vanilla JavaScript, GA4,
  Tailwind, jQuery UI, the Cloudflare and Vercel products) -- to 102 Simple Icons marks
  and 52 explicit generics; lookup is case- and space-insensitive. `tech-icons.test.ts`
  (7 tests, `node --test`) reads those engine sources and fails on any name that is neither
  a mark nor an explicit generic, and on two canonical names sharing a mark unless one is
  a declared alias. `components/ui/TechIcon.tsx` renders the path inline (`TechIcon`,
  `TechName`, `TrademarkNote`).
- Bundle: only the mapped icons are imported (the built chunk carries exactly 102 `hex:`
  fields, not the set's 3,460), but Simple Icons paths are heavy -- 114 KB of path data for
  the 102, OpenSSL alone 6.4 KB -- so `lib/tech-icons` is a dynamic import behind
  `TechIcon`: its own chunk, 137.8 KB raw / 57.2 KB gzipped, fetched once on the first page
  that can show a stack and never on first load. Measured on the production build
  (`next build`, Turbopack): initial client JS for `/extract` 129,174 → 130,794 B
  (+1.6 KB), `/report/[domain]` 59,854 → 61,331 B (+1.5 KB), the landing unchanged
  (46,083 B); total client JS 1,701,640 → 1,844,081 B, of which 137,753 B is the deferred
  icon chunk. Every place a mark renders is downstream of a fetch or a stream, so the
  chunk is there before the names are; until it is, the name renders alone with the mark's
  space held. The heaviest paths are OpenSSL 6.4 KB, Preact 5.1, GSAP 4.6, Docusaurus 4.4,
  TanStack Query 4.1; a core set of the 40 names in the brief would be 41 KB raw / 17 KB
  gzipped with every other name on the cube -- one edit to `ICONS` if the owner prefers
  that trade. `tools/check_responsive.py --theme both` on this build: every route this
  touches is green; the six failures are `/settings` phone text at 12.5 px, present on
  `main` and not touched here.
### Changed (2026-09-17, PR #114) — the mark, round three: the star in the open corner, in a soft-3D style
- The owner's two references folded in. Placement: the w's top-right corner is opened -- the
  terminal node removed, the last ribbon stopping short -- and the brightest star, a
  four-point sparkle, sits detached in the gap, its right edge flush with the w's right
  extent (`docs/design/logo-refinement-4.png` compares this with the node kept and the star
  floating above, each at two star sizes). Style: the "World Makers" treatment in our hue --
  the four edges as thick rounded ribbons on a gradient of the hero's atmosphere, each
  tucking under a spherical node with a soft dark halo at the join, the nodes lit from the
  star's side, the star brighter than everything with a soft glow; vector only (linear and
  radial gradients, two Gaussian blurs, no rasters, 2.3 KB). Light grounds take the deeper
  end (`#2b5a91 → #6aa6e6`), dark grounds the pastel end (`#9cc4f2 → #dcefff`), on
  `--brand-*` tokens so the inline header mark follows the theme. `docs/design/logo-style-3d.png`
  shows the style on the w and on two orbit-ring alternates (both fail at 32 px: the ring
  collides with the nodes) and the header at 28 px styled against flat. Under ~24 px the flat
  form takes over: the favicon is the flat w and star on the accent tile; 180/512 icons carry
  the styled mark on a navy tile; the OG image the styled mark over the sunrise. A second
  pass after the owner's look (`docs/design/logo-style-3d-b.png`, before/after): the nodes
  matte -- no specular, a ≤ 12 % lift toward the star -- the ribbons 13 % thinner, the tuck
  halo softer, the star's glow tighter, and the light gradient one step deeper
  (`#234b7c → #5b95d6`) so the mark has weight on paper.

### Changed (2026-09-17, PR #113) — the mark, round two: the constellation w
- The #112 mark (an arc over lines) read as a signal glyph and said nothing of the graph.
  The owner's vision -- the site becomes a knowledge graph, and the graph travels -- drove a
  second round: eight directions on one sheet (`docs/design/logo-explorations-2.svg`), each
  tested against the share icon, the Wi-Fi glyph, the hex mesh, the atom and the Neo4j /
  GraphQL marks, then five refinements of the pick judged on true 16 px rasters at 8×
  (`logo-refinement-2.svg`). The mark is the constellation w: five nodes and four edges, a
  knowledge graph that spells the initial, hubs at the ends and smaller nodes within so it
  still reads at 16 px; a constellation, so it belongs with the hero's space. Its brightest
  star, at the top right, is a four-point star -- the owner's ask for the AI and agents who
  will consume the graph; the edge ends at its centre, so it is still a node of the w
  (`logo-refinement-3.svg` compares the node-as-star, a companion sparkle and this). At
  16 px the star's arms merge, so the favicon (`favicon.svg`, `app/icon.svg`) carries a
  larger dot there instead; every other size has the star. Same asset set as before,
  replaced in place: `public/logo/{mark,mark-mono,lockup}.svg`, `favicon.svg`,
  `icon-32/180/512.png`, `app/icon.svg`, `app/apple-icon.png`, `app/opengraph-image.png`
  over the sunrise, and the inline glyph in `<Wordmark>`.

### Changed (2026-09-17, PR #112) — theme: "Atmosphere" site-wide, and the mark
- The palette follows the hero. The study (contact sheets of eight views × two themes for
  the green control and three candidates -- Atmosphere, Sunrise, Ink -- the hand-off seams,
  contrast tables and the decision are in the PR) found the green botanical against the
  astronomical hero and doing two jobs, accent and "measured". The winner, Atmosphere:
  the accent is the limb's blue sampled from the frame (`#3568a3` / `#2b5a91`; dark `#7ea9dc`
  / `#93bbea`), the light ground a cool paper from the day sky (`#f4f6f9`), the dark ground
  the hero's own space lifted a step (`#080c14`), ink a navy-black; green stays as `good` and
  is no longer the accent, the flare's amber is `warn`, oxide red is `bad`. Every value in
  `globals.css` §1/§1b, the docs bridge (`docs.css`'s dark block now reads the tokens
  instead of its own greens; success and diff-add are `good`), the light hero's `--scene-*`
  ink, `themeColor`, and a faint graticule (96 px majors, 24 px minors) where the grid was;
  the hero frame keeps a 1 px hairline so its edge holds on the near-space ground. Contrast:
  ink 16.7 / 16.2, muted 7.2 / 8.7, faint 4.4 / 5.5, accent-ink 6.5 / 9.8, flags ≥ 5.6 on the
  ground and ≥ 5.2 on their tints (light / dark). No layout changes.
- The mark: the limb over the reading lines -- the web seen whole, the page read in order,
  nothing hidden -- from six directions explored as one SVG sheet and judged at 16 px.
  White on an accent tile (`public/logo/mark.svg`, `favicon.svg`, `app/icon.svg`), a
  one-colour glyph (`mark-mono.svg`), the lockup with the Manrope wordmark, 32/180/512 PNGs,
  `app/apple-icon.png`, and a 1200×630 `app/opengraph-image.png` of the mark and wordmark
  over the hero's own space. `<Wordmark>` draws the same glyph inline on the accent tile.
### Added (2026-09-17, PR #111) — one origin for web and API
- `NEXT_PUBLIC_API_BASE=/` means "this origin": the web app calls `/api/...` on itself,
  and `WEBGRAPH_API_PROXY=http://127.0.0.1:8000` (build and start) makes `next` forward
  `/api/*` to the API (`afterFiles` rewrite, so the app's own `/api/search` still wins).
  One host serves both -- one tunnel, one domain, no CORS. SSE streams through unbuffered
  (measured: events at 0 s, 2 s on a two-page crawl). The default (an absolute API origin)
  is unchanged. Docs: `/docs/deployment/configuration`.

### Fixed (2026-09-17, PR #110) — the prompt submits without JavaScript
- The hero/closing prompt is a real GET form (`action="/extract"`, the field named `url`,
  hidden `mode` and `complete`): before React attaches -- a slow phone, a script that
  failed to load -- pressing Enter or the arrow now opens `/extract?url=…` instead of
  reloading `/?` with nothing. With JavaScript the handler still routes as before
  (`/report` for the report mode, the camera push first in the scene).

### Fixed (2026-09-17, PR #109) — the phone sheet hangs from a solid header
- Opening the phone menu on `/` un-floats the header (solid bar, row back at the top) so the
  sheet hangs from it instead of overlapping the dropped row from #108. The owner's "menu,
  nav and theme button don't work on the phone" was the *dev* server: on a throttled phone
  the unminified landing never finished hydrating (measured: never in 60 s on `next dev`,
  interactive after 1.3 s on `next start`), so taps did nothing. Phone and shared links are
  served from a production build from now on.

### Changed (2026-09-17, PR #108) — the header sits inside the hero frame
- On the landing page the floating header row drops by `--frame-margin + 0.625rem`
  (a transform, so the sticky header's box never changes height) instead of straddling the
  frame's top edge; the hero copy starts `clamp(5.5rem, 13svh, 9rem)` down to keep its
  distance. The owner noticed the pill cutting the frame's corner.

### Changed (2026-09-17, PR #107) — every route responsive
- The owner's brief: the website on every device. Every route now lays out at 320, 390 and
  430 px (phones), 768 and 1024 (tablet portrait and landscape), 1280, 1440 and 1920, and a
  short 1440×640, in both themes, and `tools/check_responsive.py` asserts it in CI
  (`make check-responsive`). The check grew from two routes at three widths to fourteen
  routes at nine viewports: `/`, `/products`, `/report`, `/report/example.com` (its
  no-API state), `/watch`, `/graph`, `/extract?…` (its error state), `/benchmarks`,
  `/how-it-works`, `/settings`, `/docs`, `/docs/getting-started`, `/docs/api/errors` (the
  widest tables) and `/docs/api/text` (the longest code). It keeps the horizontal-overflow
  rule and adds two for phones: fixed and sticky elements may cover at most 35% of the
  viewport's height (measured at the top and after a scroll), and body text -- paragraphs,
  list items, cells, controls -- is at least 14 px, with short captions and labels exempt at
  the type scale's own 13 and 11 px. Tap targets under 44 px are counted and printed, not
  failed. `--out` writes a full-page screenshot per route and viewport, `--theme both` takes
  the dark set too, `--only`/`--sizes` narrow a run, `--verbose` names every offender. The
  API-dependent routes settle on their `role=alert` instead of a fixed wait, so the full
  matrix runs in about four minutes. Before: 21 of 126 route×viewport checks failed per
  theme, all on phones (no route overflowed); after: 0, with two findings on the landing
  waived by name (below). CI runs the light theme; the layout is the same CSS in both.
- Header: eight items, the wordmark, the theme control and the button need ~1,060 px in a
  line, so the fold to the "Menu" button moves from 900 px to 1,152 px -- at 1024 the bar
  wrapped "How it works" and "GitHub" onto a second line. On the landing the floating pill
  was centred on the page and ran under the controls at every width (by 10 px even at
  1440); it now sits in the flow between the wordmark and the controls, centred in the room
  they leave. Items no longer wrap inside a link; the open menu sheet scrolls on a short
  viewport instead of running under the fold.
- Docs: below 1024 px a table takes the width its content asks for (capped at 56 rem) inside
  the scroll wrapper Fumadocs gives it, instead of squeezing its columns into the 358 px a
  phone leaves -- the three request-options tables on `/docs/api/text` stood 1,924, 1,922
  and 1,461 px tall at 390 px (and the same at 768, beside the sidebar); they are 556, 694
  and 643 px now and scroll sideways. The errors table's `code` spans already held it at
  1,015 px, so it scrolled before and scrolls the same now.
- `/products`, `/report`, `/watch`: the closing note under each page is caption size on a
  laptop and body-small on a phone.
- `/benchmarks`: every paragraph of prose (a board's question, its caveat, "How the rows
  were produced", the type-table copy, the not-run reasons, the chart captions) moves from
  12–13.5 px arbitrary sizes to the `text-small`/`text-caption` tokens, 14 px on a phone;
  the type table's header row takes `text-label`. Forty-eight elements were under 14 px on a
  phone; none are.
- `/how-it-works`: the nine stage chips are a nav on a phone -- `text-caption`, 40 px tall
  under a coarse pointer; the stage prose, rescues, failure rows, notes and the principles
  cards take `text-small` (23 elements were under 14 px).
- `/extract`: the timeline's step titles, descriptions and the "Show all details" toggle,
  the stage rows (which no longer truncate "0s ela…" at 320 px), the phase line, the Stop /
  Extract-another / view buttons and the empty and error notices take the tokens, and the
  buttons are 40–44 px tall under a coarse pointer; `CopyButton` likewise (`text-caption`,
  40 px). `/settings`: the lede takes `text-small`.
- Not fixed here, waived by name in the checker's `WAIVED` table and reported to the owner
  of `components/landing/**`: the story stage is sticky under the header on phones and the
  two together cover 45–48% of the viewport (the rule allows 35%), and seven chapter notes
  are `text-caption` prose at 13 px. Overflow stays enforced on the landing. Also out of
  scope: `RankChart`'s rotated labels clip at the SVG's left edge at every width (its
  `PAD.left`, not a layout matter).
- After #105 replaced the sticky story stage, the landing needed no waivers: the two
  `WAIVED` entries are gone and the note paragraphs under the story cards, proof strip and
  standings (and `EvidenceRow`'s source line) are `text-small` (14px) instead of
  `text-caption` (13px). 126 route × viewport checks pass with no waiver.

### Changed (2026-09-17, PR #106) — hero: the Earth by day and by night
- The hero follows the page's theme, both photoreal, from the same orbit. Dark: the night
  scene as before, with the sun now rising from behind the limb -- half hidden, the rays and
  core occluded where the planet stands in front (the scene pass writes the ground into
  alpha; the post pass reads it), the rim warmest at the sun and blue along the limb. Light:
  the same Earth in full day -- the sun high behind the viewer, bright ocean (the water a
  little bluer and deeper than the map's), cloud decks with their shadows, the thick pale-
  blue air at the limb fading into a light sky (deep blue-grey at the top, near-white at the
  limb); no stars, no flare; the country marker a green pin with a ring instead of the warm
  glow. Switching the theme (the toggle or the system) crosses the scene over 600 ms --
  the light's direction, the sky, the sun, the exposure, the grain and the vignette all
  interpolate on `uTheme` -- while the frame's own palette (`--scene-*`, now defined light
  first and overridden in the dark blocks like the site's tokens) transitions in step: ink
  copy and light glass by day, light copy and dark glass by night. Two stills,
  `public/earth/still-1440-light.jpg` and `-dark.jpg` (80 / 100 KB), rendered by
  `tools/render_hero_still.py` (now one run per theme), chosen by the stylesheet.
- The run card can no longer touch the sub-line: the copy, the card's room and the prompt
  are three rows over the scene, the middle one a size container, and the card shows only
  where that row is tall enough (`@container (min-height: 19.5rem)`); the card itself is
  shorter (a header and three rows). The sub-line and the credit carry a soft shadow in
  the ground's colour so they hold their contrast beside the flare (measured 8:1 dark,
  9:1 light against the sampled ground).
- Fixed: the country turn took the wrong of the two tilt solutions and hit the clamp, so a
  country could end at the limb rather than beside the prompt (India did); it now takes
  the solution nearer the resting tilt, and the frame point moved a little inward.
- Bytes and frames: the hero chunk 23.4 KB / 8.8 KB gz (was 8.0); p50 16.7 / p95 18.7 ms
  in both themes and across the switch, headed Chromium on an M2 at DPR 2 → 1.5.

### Changed (2026-09-17, PR #105) — landing: how it reads a page, as one panel
- Chapters 01–03 of the landing (the pain, the turn, the result) were a sticky Canvas-2D
  stage the copy scrolled past; the owner's verdict was that the illustrations and their
  animations were not good. Replaced, after the way LlamaIndex and landing.ai do it, by one
  framed panel (`components/landing/Story.tsx`): the three steps as an accordion on the
  left -- Fetch twice · Refuse the walls, drop the hidden · Reading order, then Markdown --
  and on the right an isometric illustration that changes with the open step
  (`how/Scene.tsx`, inline SVG rendered on the server; `how/iso.ts` is the 30° projection).
  One page stands on a ruled floor with a cast shadow; step one adds the plain and the
  rendered fetch as two sheets with their real word counts (react.dev/learn: static 2,108 ·
  rendered 2,195 · union 2,198) and dotted paths that draw themselves; step two peels the
  page into labelled layers -- Heading / Paragraph / Table / Code in ink, and in oxide red
  the cookie banner, the login modal, the off-screen links and the display:none block,
  which lift off and dissolve, with the refusal tagged in the engine's words; step three
  draws the XY-cuts, numbers the blocks in reading order, slides out the Markdown with the
  same numbers and `reading_order: geometric_xy_cut`, and stands the Site Truth Report
  beside it. Springs are overshoot curves in CSS; the pieces rise in with a stagger when the
  panel scrolls into view, switching steps cross-morphs (the page stays, the rest
  re-sorts), the layers parallax a few pixels with the pointer on a damped spring
  (`how/HowMotion.tsx`, which also keeps one step open, advances them every 6.5 s until
  touched, and does nothing under reduced motion). Without JavaScript the accordion is the
  browser's own and the scene stands complete at step one. `how/how.css` holds the sheet.
- Below the panel, three cards with pieces of the real output where the old chapter copy
  had prose: word recall 1.000 on sqlite.org/lang.html (was 0.749) with the bar filling;
  three refusals stamped in as `resolve.py` words them (login redirect, HTTP 503,
  robots.txt); three `url#xpath` anchors from docs.python.org/3/tutorial/ with their quotes,
  typed in. Headline "Reads the page the way a *person* does." -- Manrope with one Instrument
  Serif italic word -- over a pill eyebrow.
- Removed: `Stage.tsx`, `StoryStill.tsx`, `scene/scene.ts` and the `.story-stage` /
  `--story-heat` / `data-chapter` rules in `globals.css` §7. Hero untouched. Landing client
  JS 14.6 KB / 5.9 KB gz in total (Motion, the prompt and HowMotion together), the panel's
  sheet 10.6 KB / 2.8 KB gz; frame times while assembling, switching with the pointer moving
  and idle: p50 16.7 / p95 17.7 / max 17.8 ms at DPR 2 on an M2, production build.

### Changed (2026-09-17, PR #104) — hero: the Earth from orbit at sunrise
- The landing opens on the Earth, from orbit, at sunrise -- the owner's brief: websites are
  worldwide, so a universe with the Earth, and HD, realistic. The frame is always dark (space
  in both themes; the page below keeps its theme). Hand-written WebGL2, lazy-loaded
  (`components/landing/hero/field/`): a star field with a magnitude distribution (many faint,
  a few bright, slight colour temperature, a barely perceptible scintillation) and a faint
  Milky Way; the planet in the lower third as an analytic sphere textured with NASA's public
  domain Blue Marble (day), Black Marble (city lights) and cloud map, downsampled to 2k
  (`public/earth/`, 1.4 MB, recorded in `ASSETS.md`, credited at the frame's edge), lit by the
  sun with a soft terminator, the clouds' shadow on the ground, a glint on the ocean (from
  a mask derived from the day map), the night side's lights; a Rayleigh-style rim -- a thin
  bright line at the surface, a blue glow thickening and warming toward the sun; the sun
  rising just above the limb beside the prompt with long soft rays, a tight core and a halo,
  plus bloom (a bright pass and two Gaussian passes at quarter size), ACES tone mapping,
  film grain, a vignette and FXAA. The 512-px textures load first and the 2k ones replace
  them, so the first frame is never blank; before JavaScript the page shows the resting
  frame as a JPEG rendered by the same code (`tools/render_hero_still.py`).
- Motion: the planet turns once in five minutes; the camera settles in from further out over
  1.5 s while the copy and the prompt rise in staggered, parallaxes with the pointer on a
  spring, drifts when idle, and tilts down as the frame scrolls away. Websites are worldwide:
  typing an address or hovering an example turns the planet (spring-damped, ~1.2 s) so the
  site's country sits beside the prompt on the night side, with a warm marker glowing there;
  pressing Run pushes the camera in for 620 ms before the app opens the run. The country
  comes from the hostname's country-code domain alone (`lib/country.ts`, 70 countries, with
  `.ac.in`/`.co.uk` and the US-only `.edu`/`.gov`/`.mil`; `pnpm --filter @webgraph/web test`);
  nothing is looked up anywhere, so the landing's promise -- the only requests made are to the
  site you name -- stands. A generic domain leaves the planet turning.
- The prompt is dark glass over space; the run card the same. `prefers-reduced-motion`
  draws one still frame per state. Frame time in headed Chromium on an M2 at DPR 2 (capped
  1.5), 1440×900: p50 16.7 ms, p95 17.7 ms (60 fps) at every quality tier; tiers (DPR, star
  octaves, bloom, FXAA) drop after a second over budget. The vertical fov is capped by a
  62-degree horizontal so 1440×700 does not stretch, and the sun sits at 62% of the
  half-width on any aspect so a phone keeps the sunrise in frame.

### Added (2026-09-16, PR #91) — the random-web sample
- `benchmark/random_web/`: `sample.py` draws domains uniformly over Tranco's top-1M ranks
  and takes one random 200/HTML Common Crawl capture per domain (seeded), so the pages are
  nobody's choice; `sample-2026-09.txt` is 300 of them (seed 1, CC-MAIN-2026-34);
  `report.py` turns a `benchmark/fidelity/run.py --sites` score into outcomes (scored /
  refused / oracle blocked / oracle failed), recall and extra bands, and the worst pages
  with their missing and extra words. `make bench-random-web` runs both.
- `REPORT-2026-09.md`: the baseline on main@b618443 -- 258 scored, recall median 0.986 /
  mean 0.916, 27 pages under 0.80, `extra > 0.30` on 53 (consent dialogs lead), 16
  honest refusals. The report also names two gaps in `report.py`'s own classification --
  an oracle that rendered an HTTP error page is scored as a page, and a zero-word
  non-refusal output has no bucket of its own -- and one page (gokitetours.com) where the
  engine returned nothing without refusing. The tail is the work list; nothing in it is
  diagnosed by this PR.

### Added (2026-09-16, PR #100) — WebGraph page: the graph, and the query path lit in real time (behind WEBGRAPH_KG)
- `/graph?url=` (`apps/web/app/graph/page.tsx`, client components under
  `components/graph/`): the site, a model panel (presets for Ollama, LM Studio, vLLM,
  OpenAI, Anthropic, Gemini, Groq, OpenRouter, Together, DeepSeek, Mistral, xAI, or a
  custom OpenAI-compatible endpoint; the key is typed in the browser, sent only in the
  body of each request, never stored server-side, and kept in page memory unless the reader
  ticks "remember in this browser"), a build panel that shows the `estimate` first and
  streams progress, caps and the final stats, the graph, an ask box, export and Neo4j sync.
- The graph: sigma 3 (WebGL) + graphology, ForceAtlas2 in a worker for a bounded time;
  colour by type in a fixed eight-slot categorical order that passes the dataviz palette
  checks on both grounds (the light one warns on contrast, answered by labels and the list),
  size by
  evidence count; hover and selection dim the rest; clicking a node shows every mention with
  its quote and `url#xpath`, attributes and relations each with their quote. Phone width
  falls back to a filterable list; the page never scrolls sideways.
- The path in real time: a store outside React (`pathStore`) receives each query event and
  sigma's reducers read it on refresh -- seeds amber, hop edges blue with a 350 ms particle
  on an overlay canvas, evidence nodes enlarged, answer nodes green with a camera pan;
  everything else ghosted. Answer sentences carry `[n]` superscripts to a numbered source
  list; an uncited sentence is rendered flagged.
- npm: `sigma`, `graphology`, `graphology-layout-forceatlas2`, `@react-sigma/core` (the
  four the design allows; nothing else). `lib/api.ts` exports `streamFrames` and a
  `requestJson` so the WebGraph client (`lib/kg.ts`) shares one SSE parser and one failure
  vocabulary. `/api/health` type gains `webgraph`; when it is false the page says how to
  turn the flag on.
- API: `no_model: true` on `POST /api/graph/query` forces the extractive answer even when
  the server has `WEBGRAPH_LLM_MODEL`; the extractive answer is one quoted sentence per
  row so the sentence splitter keeps their citations apart.
- `/products`: the WebGraph card is "Available — preview, behind a flag" with CTAs to
  `/graph` and the docs; the footer gains WebGraph; `/docs/webgraph` gains "The page".
- Measured only with the fake provider (no key in the environment; Ollama has no models),
  in headless Chromium: the fixture site (35 entities) builds, the path streams and lights,
  every citation resolves to `url#xpath`, both themes, 1440 px and 400 px with no sideways
  scroll, no console errors; the sode-edu.in crawl's fake-provider graph (4,490 entities,
  954 relations; 1,500 shown by degree) draws in 1.5 s, answers in 0.8 s and holds 61 fps
  after the path lands. Not measured: a real model's answers.

### Changed (2026-09-16, PR #103) — hero: a field of pages
- The landing opens on a scene, not a grid: a rounded full-bleed frame (`hero/Hero.tsx`) of a
  meadow of ~1,000 small paper pages -- the web, as a reader meets it -- under a golden-hour
  sky, with the prompt standing on a low plinth in the mid-ground and the nearest pages rising
  past its foot. Hand-written WebGL2, no library (`hero/field/`): the sky, ground and plinth
  are one ray-cast full-screen pass that also writes depth (a low sun with bloom and a warm
  horizon band, two fbm cloud layers lit from below, atmospheric fade, film grain, a soft
  vignette; at dusk in the dark theme the sun is under the horizon and there are stars); the
  pages are instanced 2×5 strips bent by a noise wind in the vertex shader, with procedural
  text lines; the graph's threads are additive. Two canvases share one simulation so the
  pages between the camera and the plinth draw over the prompt's foot, as the reference's
  grass overlaps its card. The plinth is placed by unprojecting the prompt's DOM box onto the
  ground, so it stands there at every frame size. The pointer's gust bends nearby pages.
- The prompt is the hero's centrepiece (`hero/SitePrompt.tsx`): a wide field with a round
  dark submit, a segmented mode row (Read a page · Run a site · Site report) and example
  chips inside the box; it normalises with `lib/url` and routes to `/extract` or `/report`.
  `Closing` renders the same component plain; `UrlPrompt.tsx` is gone. Hovering an example or
  pressing Run drives the field through the frame's `data-hero-state`: a lightly under-damped
  spring per page follows targets that are a function of that state, so the scattered pages
  align into rows spaced one page-height apart on screen (reading order), the oxide-red and
  dark ones (what a naive reader emits; what the site hides) sink under the ground, nine lift
  and thread into a graph, and the run card rises above the prompt as what the address
  becomes. Leaving scatters them again.
- The site header floats over the sky on `/` -- transparent, items in a pill, controls in a
  pill -- until the frame has scrolled past; `Story` starts at "01 · The problem" (the promise
  is the hero's, verbatim) and `Stage` reads chapter numbers from `data-panel`, not index.
  The ruled ground begins below the frame.
- Complete without JavaScript: the still is inline SVG from the same seed and camera
  (`hero/geometry.ts`, `HeroStill.tsx`), hidden only once the renderer draws. Reduced motion
  draws one settled frame and each state change as a new still; no WebGL2 or a lost context
  leaves the still. Bytes: the field is its own lazy chunk, 25.8 KB raw / 10.5 KB gz, loaded
  after mount; the landing's initial JS is 185.4 KB gz (183.5 on main). Frame times in
  headed Chromium on an Apple M2 at DPR 2 (capped to 1.5), 1440×900, idle, organising and
  under the gust: p50 16.7 ms in every run; p95 17.6 ms in the quiet runs and 33 ms in runs
  on the shared machine (56–60 fps mean), once the per-frame instance upload re-specified
  its buffer instead of patching one still in flight (p95 34 ms before, every run). Phones
  draw 450 pages and three cloud octaves.
### Added (2026-09-16, PR #97) — WebGraph v1 (behind WEBGRAPH_KG)
- **The inferred layer over a crawl**, `packages/engine/src/webgraph/kg/`: a language
  model reads every heading-scoped section and states what it says -- entities of twelve
  core types plus open ones, typed attributes (price, date, phone, email) and relations --
  and every row is kept only if the model's verbatim quote is found in a block of that
  section. The row then cites `url#xpath` and a character span (`Evidence`); a quote not
  found is rejected and counted by reason. No unverified tier exists in the store.
  `Section.blocks` (`BlockRef(xpath, kind, start, end)`) is the one change inside `graph/`
  that makes this possible; section text is byte-identical to before.
- **Bring your own key.** Three raw-`httpx` adapters (`kg/providers.py`): OpenAI-compatible
  with a `base_url` (OpenAI, Groq, Together, OpenRouter, DeepSeek, Mistral, xAI, Ollama,
  LM Studio, vLLM, any custom endpoint), Anthropic (`output_config` json_schema) and Gemini
  (`responseJsonSchema`), with a `json_schema` → `json_object` → prompt ladder and retries
  on 408/409/429/5xx. Config per request or from `WEBGRAPH_LLM_*`; the key is excluded from
  `repr`, never persisted, never traced, and the API's new 422 handler redacts `api_key`
  and `password` from validation errors (FastAPI echoes the whole body on a missing field).
  A deterministic `FakeProvider` runs the tests and the CI benchmark.
- **Build with the bill visible** (`kg/build.py`): the first event is `estimate` (sections,
  cached sections, input tokens, output at a quarter, USD when prices are configured);
  caps on pages, sections, input tokens (2M) and dollars stop the build cleanly with
  `truncated: true`; the LLM cache (`llm_cache` in the site's SQLite file, keyed on prompt
  version, model, section text and known entities) makes a second build free. Sections
  are read by page in-degree, then depth. No gleaning, no build-time summaries.
- **Deterministic merge** (`kg/merge.py`): `(type, norm(name))`, model-declared aliases,
  open type into same-name core type, MinHash/LSH 3-gram Jaccard ≥ 0.9; JSON-LD/microdata
  entities enter first and win on a type conflict; a name on more than 60% of pages is
  `generic` and never expanded through. No LLM-judged dedup.
- **Store**: one SQLite file per site under `WEBGRAPH_KG_DIR` (`kg/store.py`) with FTS5
  over entity names and facts (pure-Python scan when FTS5 is missing), in-memory
  adjacency, `build_runs`, a versioned schema.
- **Ask, with the path streamed** (`kg/retrieve.py`): FTS5 BM25 seeds ∪ the crawl's
  section BM25 → two mass-normalised hops → evidence with 35% of slots reserved for rows
  reached by expansion → one answer call; every factual sentence carries `[n]` citations
  to `url#xpath`, an uncited sentence is returned `unsupported: true` (never silently
  kept), "Not stated on this site." is recognised as abstention. Events: `seeds`, `hop`,
  `evidence`, `answer_delta`, `answer`.
- **Exports and Neo4j**: JSONL, a portable `MERGE`-only Cypher script, JSON-LD with
  `prov:wasQuotedFrom` and `oa:XPathSelector` + `oa:TextPositionSelector` per assertion
  (`kg/export.py`); `kg/neo4j.py` pushes `UNWIND $rows MERGE` batches of 1,000 over bolt
  (`RELATED {predicate, evidence_ids}` edges, typed edges behind a flag, no APOC) with the
  official driver as the optional extra `webgraph[kg-neo4j]`.
- **API** (`apps/api/src/webgraph_api/kg_routes.py`, `WEBGRAPH_KG=1`, otherwise 404
  naming the flag): `POST /api/graph/build`, `POST /api/graph/query`, `GET
  /api/graph/stats`, `GET /api/graph` (nodes and edges), `GET /api/graph/entity`, `GET
  /api/graph/export?fmt=jsonl|cypher|jsonld`, `POST /api/graph/sync/neo4j` (credentials per
  request, never stored), `DELETE /api/graph`; `/api/health` reports `webgraph`.
- **CLI**: `webgraph kg build <site>` (from the stored crawl, `--graph` JSONL, `--pages`
  a directory of saved HTML, or a fresh crawl), `kg ask <site> "question"`, `kg export
  --format jsonl|cypher|jsonld`, `kg sync-neo4j` (password from `NEO4J_PASSWORD` only).
- **Benchmark** `benchmark/kg/`: `generate.py` derives typed questions from a site's own
  JSON-LD with the gold page and block located verbatim; `run.py` scores answer
  correctness by type, citation precision/recall at page *and block* level,
  unsupported-sentence rate, abstention, graph statistics and cost, in three modes
  (`bm25` baseline, `kg`, `kg+sections`); a six-page fixture site with 23 questions
  (three 2-hop, two not-on-site). **On the fixture with the fake provider the BM25
  baseline beats the KG on answer correctness (0.86 vs 0.62)** -- the fake's quotes are
  six-word windows -- and no real model was measured in this PR (no key in the
  environment, Ollama up with no models). The flag stays on until `kg+sections` beats
  `bm25` on typed and two-hop questions on three real sites.
- Docs: `/docs/webgraph` (what it is, the provenance rule, cost controls, the benchmark,
  what v1 does not do), `/docs/webgraph/providers`, `/docs/webgraph/neo4j`; the
  deployment configuration table gains `WEBGRAPH_KG`, `WEBGRAPH_KG_DIR`, `WEBGRAPH_LLM_*`.
- Config: `KG_*` in `config.py` (section "WebGraph"), `DEPLOY_KG`, `DEPLOY_KG_DIR`;
  `Settings.kg_enabled`, `Settings.kg_dir`.
- Not in this PR: the web UI (`/graph` with the sigma graph and the live query path) is
  the next PR; the `/products` WebGraph card stays "coming".
- Key hygiene over the API: `api_key_env` in a request body may name only the conventional
  key variables (`kg.providers.KEY_ENVS_A_CALLER_MAY_NAME`; the CLI is unrestricted) -- a
  free choice plus a caller-chosen `base_url` would have read any variable off the server
  and posted it as a bearer token; and a preset's key resolves by the `base_url`'s scheme
  and host, not a string prefix, so `https://api.openai.com.evil.example/v1` gets no key
  (`TestProviders::test_a_preset_key_goes_only_to_the_preset_host`,
  `::test_an_untrusted_body_may_not_name_an_arbitrary_variable`,
  `test_kg_api.py::…::test_api_key_env_cannot_point_at_an_arbitrary_server_variable`).
### Added (2026-09-16, PR #102) — machine-readable site signals in the report
- **What the site declares to machines** (`report/signals.py`; `SiteReport.signals`, the
  CLI's SIGNALS section, `signals` in `POST /api/site/report`, a section of `/report`, a
  docs section). Twenty-four signals in five groups, each with `present` (true / false /
  null for not measurable), the detail in the file's own terms, who honours it, the spec
  URL and a plain-words meaning for the owner ("Your robots.txt tells AI systems they may
  index it for search and link back and use it as input to AI answers, but should not
  train AI models on it. Honoured voluntarily by the bots that read Content-Signal; not
  enforced."). *Declarations to AI*: robots.txt `Content-Signal` read per `User-agent`
  group (www.cloudflare.com's line sits in its `Cohere-ai` group, and the report says so),
  IETF aipref `Content-Usage` (header and robots line), `llms.txt` / `llms-full.txt` with a
  sample of five links checked, `ai.txt`, RSL (`License:` line, `Link rel=license`,
  `<link>`, inline block, `/rsl.xml`), TDM reservation (header, meta, `tdmrep.json`),
  `noai` / `noimageai`, the indexing directives from `X-Robots-Tag` and meta robots.
  *Discovery*: sitemap, feed autodiscovery, Markdown twin (`text/markdown` alternate,
  `describedby`), IndexNow (not measurable). *Agents*: A2A agent card at
  `agent-card.json` and the pre-0.3 `agent.json`, `agents.json`, MCP (`mcp.json`, MCP
  `Link` rels), RFC 9727 `api-catalog` plus `ai-catalog` / `agent-skills`. *Metadata*:
  JSON-LD `@type`s in the plain HTML, OpenGraph / Twitter, `hreflang`, canonical. *Trust*:
  `security.txt` (both paths, `Expires` checked), `humans.txt`, web app manifest,
  speculation rules. A `402` on the root is noted as pay-per-crawl.
- Every probe is one streaming GET that reads status and headers first and at most a small
  cap of body (`fetch_capped`: 64 KB, 512 KB for the llms files, 1 MB for the root), paced
  with the report, skipped when robots.txt disallows the path for this client, under the
  engine's own User-Agent. Presence is never the status alone: vercel.com answers
  `/ai.txt`, `/rsl.xml`, `/humans.txt`, `/manifest.json` with its 2.5 MB HTML shell and
  200, so each signal has a shape test. Typically 12-18 requests.
- The suggested `robots.txt` gains a commented `Content-Signal` block -- search and AI
  input yes / training no; or all yes -- with the note that it is a declaration, not
  enforcement, shown back rather than proposed when the file already has one, and a
  comment when no feed is advertised. `suggested_security_txt` (RFC 9116 template) is
  offered when the site has none.
- `crawl.discovery.parse_groups` keeps `Content-Signal` and `Content-Usage` lines in the
  group they sit in. `PageReport.has_open_graph`; `LlmsFile` gains `links_checked` /
  `links_answering` and moves to `report/signals.py` (re-exported).

### Changed (2026-09-16, PR #102) — the metadata sub-score counts OpenGraph
- The 10-point *Structured data and page metadata* sub-score's 4 page-field points now
  count OpenGraph beside title, description and `lang` (four fields; a page with the
  older three and no `og:*` earns 3 of 4). Weights unchanged; total stays 100. No new
  sub-score: declarations to AI are choices, not virtues, and agent cards are too rare to
  score. `llms.txt` stays at 5.

### Added (2026-09-16, PR #101) — Watch
- `webgraph.watch`: change monitoring on top of the crawl. A watch is a root and a
  config; `run_watch` / `stream_watch` crawl it again with the previous run's URL set as
  seeds (`stream_site(..., seeds=)`), compare every page against the last finished run by
  the engine's `content_hash` first and section by section second
  (`graph.diff.diff_sections`, now public, over sections cut from the content Markdown),
  and record `added` / `removed` / `changed` with the section heading and the text on each
  side. The first run is a baseline. `removed` is claimed only on an HTTP 4xx; a page the
  cap never reached is `unverified`. No model anywhere: two runs over the same two versions
  of a site produce the same changes. The `page` event now carries `content_hash`.
- Noise rules, documented and configurable (`config.WATCH_NOISE_PATTERNS`,
  `WATCH_NOISE_MIN_WORDS`; per watch `noise_patterns`, `noise: false`): a block whose text
  *is* a date, a time or a counter -- patterns removed, fewer than three alphabetic words
  left -- is left out before two versions of a section are compared; a sentence that
  contains one is compared; query strings are stripped from link and image targets.
  Navigation, footers and comments are already gone (the content Markdown); the
  main-content boundary is off for a watch unless asked, because a watched page is as
  likely a list of circulars as an article. A page whose blocks all survive and merely sit
  under different headings is suppressed too -- measured on vtu.ac.in's front page, two
  static fetches 11 minutes apart put the same social-links list under different headings.
  Every run reports how many pages it `suppressed`.
- Storage: one SQLite file, standard library only, `~/.cache/webgraph/watch.sqlite3`
  (`XDG_CACHE_HOME`, `WEBGRAPH_WATCH_DB`): `watches(id, root, config_json, created_at,
  schedule_seconds)`, `runs(id, watch_id, started_at, finished_at, pages_ok, pages_failed,
  stopped_by)`, `pages(run_id, url, content_hash, title, markdown, fetched_at, strategy,
  error, sections_json)`, `changes(id, run_id, watch_id, url, kind, before_hash,
  after_hash, diff_json, detected_at)`.
- `export_changes(fmt="json" | "md" | "rss" | "atom")`: an RSS 2.0 or Atom 1.0 feed of
  changes, one entry per change titled with the page and its section headings -- the
  cheapest "notify me" there is, and a university's circulars as a feed (the research
  found VTU's reach 16,600 people through a volunteer Telegram channel that reposts them
  by hand).
- CLI: `webgraph watch create <url> [--max-pages] [--complete] [--no-noise] [--config]`,
  `watch list`, `watch run <id> [--fail-on-change]` (non-zero on change, for a scheduled
  job), `watch changes <id> [--since 12h|ISO|epoch] [--format md|json|rss|atom]`.
  `webgraph diff --fail-on-change` remains. `.github/workflows/example-watch.yml` is an
  Action that runs a watch and opens an issue with the digest; shipped with a manual
  trigger only and its six-hourly `schedule` commented out, so it never runs unattended.
- API: `POST /api/watch`, `GET /api/watch`, `GET /api/watch/{id}`, `DELETE /api/watch/{id}`,
  `POST /api/watch/{id}/run` (SSE: the crawl's events plus `watch`, `change`, `done`;
  the same crawl slot, trace and caps as `/api/site/stream`), `GET /api/watch/{id}/changes?since=`,
  `GET /api/watch/{id}/feed.xml[?format=atom]`.
- Web: `/watch` -- the watches, a URL to add one, "Run now" streaming the run, and the
  changes per watch (kind, page, section heading, before and after, when), in the design
  system, both themes, phone width. "Watch" in the header; a fifth product card, marked
  available (the grid's odd last card spans the row). Docs: `/docs/watch`.
- Tests (fail on the base branch): `packages/engine/tests/test_watch.py` (47: store round
  trip; two versions of a local site -- one page added, one gone, two changed with the
  section heading and the text on each side, the front page's bumped timestamp and
  counter suppressed; a 500 is not a removed page; a page behind the cap is unverified;
  noise rules on 19 blocks; RSS and Atom well-formed with every required element; the CLI
  end to end), `apps/api/tests/test_api.py::TestWatch` (4).

### Changed (2026-09-16, PR #98) — landing page motion and docs alignment
- The landing page is a scroll-driven story on one sticky, code-drawn stage
  (`components/landing/Story.tsx`, `Stage.tsx`, `scene/scene.ts`): the promise (the hero;
  eight blocks drop in, settle, are numbered in reading order and typed out as Markdown), the
  pain (a cookie banner, a login modal, a 503, off-screen links and a `display:none` dialog
  fall onto the page in oxide red; what a naive reader emits is listed beside them), the turn
  (a plain fetch and a Chromium render converge, a scan refuses each wall in the engine's own
  words and leaves the XY-cut behind), the result (Markdown in reading order, `recall 1.000
  on 22 of 29 sites · floor 0.945` from `FIDELITY`, a graph of the site, the Site Truth
  Report card, linking to `/report`), then the proof and the prompt. The scene is hand-written
  Canvas 2D -- gravity and a bounce for falling blocks, critically damped springs to their
  slots, an impulse and fade for refused ones -- with no library; the landing route's JS
  grows 176.7 → 183.5 KB gz (+6.8). Without JavaScript the stage is a server-rendered SVG of
  the final frame; under `prefers-reduced-motion` it is four still frames and nothing on the
  page is hidden. Reveals, count-ups and the standings' score bars come from one
  IntersectionObserver (`Motion.tsx`). The ground is CSS: a green field and a warm glow that
  travel with the stage, edge blobs, a 48px ruled grid and a 0.04 grain, kept off the copy
  columns and measured (dark ≥ 7.6:1; light `muted` 6.9:1 at the darkest grain pixel, 7.1:1
  on the mean ground). `Hero.tsx` and `Pipeline.tsx` are folded into the story with their
  copy; the URL prompt closes the page as `#start`.
- Docs: the article is centred between the sidebar and the table of contents --
  `#nd-page` capped at 76ch plus padding inside Fumadocs' centred `main`, `.prose` at 76ch,
  `--docs-max` 87.5rem (the owner's ~1400px, over DESIGN.md's 90rem). Content unchanged.


### Changed (2026-09-16, PR #94) — a crawl has limits by default
- `CRAWL_MAX_PAGES` is 500, not 0. `0` still means unbounded and now has to be asked for:
  the API's `SiteRequest.max_pages` defaults to the engine's cap, and the web app leaves
  the field out unless a cap was given, so the API's default applies rather than `0`. Two
  new limits beside it: `CRAWL_MAX_SECONDS` (3,600; `SiteRequest.max_seconds`) ends a run
  by wall time, checked between batches; `CRAWL_MAX_QUEUE` (20,000; `crawl.max_queue`)
  stops the frontier accepting addresses past that many queued -- a refused address is not
  marked seen, so it is taken if linked again once the queue has drained. The `done` event
  says which limit ended the run in `stopped_by` (`"pages"`, `"time"`, `"queue"`, or
  `null` when the frontier ran dry or the caller stopped it), repeats the caps in `limits`,
  and counts `queue_refused`; `exhausted` is now false for a run whose frontier had turned
  addresses away. The reason: a whole-site run of vtu.ac.in with the old defaults ran six
  hours, held six gigabytes, and was stopped by hand (#87).
- Files are counted, not fetched. A link whose `url_kind` is `pdf`, `image` or `other_file`
  (`FILE_KINDS`) is tallied in `discovered_kinds`, recorded with the page that linked to it
  and the link's text (the frontier's `skipped`, `skipped_urls` and a citation in
  `origin`), and never requested. The `done` event carries `skipped` by kind,
  `skipped_total`, and the first `CRAWL_SKIPPED_URLS_REPORTED` (200) addresses with their
  citations -- a university's circulars as a list, none fetched. `SiteConfig.fetch_files`
  (`crawl.fetch_files`) queues `.pdf` links as before, for a caller that wants the refusals
  on record. vtu.ac.in spent a third of six hours fetching 5,730 PDFs to refuse each.
- `stream_site` no longer holds every page until the end of the run. The full pages are
  kept only until cross-page chrome is known (six of them, released the moment it is); after
  that each page keeps its URL, its facts and its schema.org payloads -- what
  `_aggregate_entities` and the site facts read -- and its blocks, Markdown and images go
  (`_kept`). The `page` event already carried each of them to the consumer. Measured on
  sode-edu.in, 300 pages, four workers, `union`, same machine and hour: peak RSS of the
  crawl process 412 MB -> 332 MB, 715 s -> 484 s, 25.2 -> 37.2 pages/min, 25 PDFs fetched
  and refused -> 199 counted and not fetched.
- The crawl loop keeps its pool full and refills it as each page lands, instead of running
  batches of `concurrency` pages that start together and end when the slowest does. With
  the per-host interval a batch of four took slots 0-3 s apart and paid that tail every
  time -- measured 20.1 pages/min against 25.2 before -- and the rolling pool removed it
  along with the tail the batches always had (37.2). `fetching` events now carry
  everything in flight, sent whenever that set changes; the time limit and the caller's
  stop are checked as each page lands, and pages already in flight are finished and
  reported.
- Politeness is per host, not per worker. `CRAWL_HOST_INTERVAL_SECONDS` (1.0;
  `crawl.host_interval_seconds`) is a minimum interval between two pages from the same host
  across every worker of a crawl, enforced by a shared throttle that reserves the next slot
  under a lock (`crawl/politeness.py`); the site's `Crawl-delay` replaces it when larger.
  Before, `max(delay_seconds, crawl_delay)` was slept per worker, and `Crawl-delay: 1` with
  four workers was four requests a second. `delay_seconds` (0.3) is still the per-worker
  pause. Under `union` a page is two requests made together; the interval spaces pages.
- API: `SiteRequest.max_seconds`; `CrawlOptions.fetch_files`, `max_queue`,
  `host_interval_seconds` (all in `/api/config`'s `overridable.crawl`); the `run` header
  reports the five limits applied. Web: `DoneEvent.stopped_by`, `limits`, `skipped`,
  `skipped_urls`; the run summary says which limit ended the run and how many files were
  counted and not fetched, instead of inferring "the page cap" from `!exhausted`.
- Tests: `packages/engine/tests/test_crawl_limits.py` (defaults; `stopped_by` for each
  limit, for a cap that lands on the last page, and for the caller's stop; a `.pdf` link is
  never resolved but is counted and cited, and `fetch_files` restores the fetch; retention
  keeps entity payloads and facts and drops blocks; the throttle spaces two real workers);
  `apps/api/tests/test_api.py::TestCrawlLimits` (request defaults, `/api/config`, `done`
  carries `stopped_by`, a local server records that the PDF was never requested).

### Added (2026-09-16, PR #95) — Site Report
- `webgraph report <url> [--pages N] [--json]`, `POST /api/site/report` and `/report` in
  the web app: what a site shows people, what it shows machines, and how ready it is for
  AI agents, from the measurements the engine already makes. For the root and up to four
  more pages (one per path section the root links to), each fetched plainly and in a real
  browser: words without JavaScript against words with it (`ResolvedPage` now carries
  `static_words / rendered_words / union_words` beside the character counts, and
  `static_error` says why the plain fetch gave nothing -- an HTTP error, a wall left out);
  which side was walled; words and links a reader cannot see, by kind, with links parked
  off the page and the foreign hosts they point at counted apart from `display: none`
  dropdowns; consent words; dead internal links (HEAD, 30 per page, each address once per
  report); title, description, canonical, `lang`, JSON-LD / microdata. Site-wide: the
  stack with versions dated against a verified release table (WordPress 4.0-7.1, Drupal
  7-11, Joomla 3-6, Next.js 13-16), `robots.txt`, sitemaps, `/llms.txt`.
- **What robots.txt declares per bot.** The engine never fetches as another bot. For
  fifteen well-known AI and search bots (GPTBot, ChatGPT-User, OAI-SearchBot, ClaudeBot,
  Claude-Web, anthropic-ai, PerplexityBot, Google-Extended, Googlebot, Bingbot, CCBot,
  Applebot-Extended, meta-externalagent, Bytespider, Amazonbot) the report reads the site's
  file as that bot would (RFC 9309: the groups naming it, combined; `*` otherwise) and
  says allowed / restricted / blocked at the root, how many `Disallow` lines decide
  something, any `Crawl-delay`, and the lines verbatim. `crawl.discovery.parse_groups` is
  the one robots.txt group parser, shared with `group_for_client`.
- **An AI-readiness score out of 100** from eight documented sub-scores -- readable
  without JavaScript 25, robots does not block AI bots wholesale 20, no walls 15, sitemap
  10, structured data and metadata 10, no hidden or injected content 10, llms.txt 5, dead
  links 5 -- each with its evidence and a recommendation in plain words; an unmeasured
  part is left out and the total rescaled to the measured weight. llms.txt's five points
  and its "optional" label cite the reason: 97% of such files get no requests (Ahrefs,
  June 2026). The robots sub-score says it measures reach, not virtue, and never
  recommends blocking.
- **Integrity**: "Likely SEO-spam injection" only when `REPORT_SPAM_MIN_HOSTS` (5) or more
  foreign hosts are linked from elements parked off the page on one page -- vtu.ac.in: 174
  off-screen links to 170 foreign hosts on every sampled page, beside 187 legitimate
  affiliated-college hosts in its hidden dropdowns, which are not a verdict; an outdated
  CMS (WordPress 5.1.1, released 2019-02-21, 7.6 years); walls; unreadable pages. One
  finding per kind across the sampled pages.
- **Suggested files**: a `robots.txt` that keeps the site's existing file byte for byte
  and appends only comments -- two variants, allow all or allow search/assistant bots and
  disallow training crawlers, the owner's choice -- and an `llms.txt` draft per
  llmstxt.org from the sampled titles and descriptions, marked optional.
- A walled or disallowed root ends the report with the engine's own refusal and no score.
  The plain fetches identify themselves as webgraph, the browser fetch is a real Chromium
  under its own User-Agent, both obey robots.txt, and the report's own requests are spaced
  `REPORT_REQUEST_INTERVAL_SECONDS` (1 s) apart per host; the report's footer says so,
  with the engine version and commit, pages sampled and duration.
- Web: `/report?url=…` and `/report/<domain>`; "Report" in the nav; the `/products` Site
  Truth Report card is now available with a "Run a report" CTA. Docs:
  `/docs/site-report`. Config: `REPORT_PAGES`, `REPORT_MAX_PAGES`,
  `REPORT_REQUEST_INTERVAL_SECONDS`, `REPORT_DEAD_LINK_CHECKS_PER_PAGE`,
  `REPORT_SPAM_MIN_HOSTS`, `REPORT_STACK_OLD_YEARS`.
- Measured on five live sites (2026-09-16): vtu.ac.in 74/100 (injection + WordPress
  5.1.1), sode-edu.in 74, vercel.com 90, docs.python.org 83, gov.uk 81; the numbers and
  their evidence are in the pull request. Extraction is untouched.

### Changed (2026-09-16, PR #93) — landing page, products page, design tokens
- The landing page is rebuilt from the design spec. The hero photograph, its glass prompt,
  its CC BY credit and the light-only commitment are gone; the page is the ground colour,
  one display line ("The honest web reader."), the URL prompt, and four measured numbers
  with their caveats beside them (WCXB 0.862 dev split, first of seven by a margin the
  board calls a tie; WCEB 0.883 with content and comments joined, content alone 0.856;
  route recall 98.1% on 96 sites against a real-browser oracle, static alone 31.0%; 0%
  wrong-value rate). Two columns list what the engine refuses, in its own error messages,
  and what it drops because a reader would not have seen it; three steps say how a page is
  read; a five-board table gives this engine's score, the leader's and the place in words,
  scrape-evals marked "not a ranking". Every figure is read from `lib/benchmarks.ts`
  (`selfScore`, `leaderScore`, new `ROUTE_RECALL`, `FIDELITY`, `WCXB_TEST`,
  `RENDER_PREDICTION`); the earlier `Pipeline.tsx` copy with 132 rules across 18
  categories is replaced.
- `/products`: one composed 2×2 grid. Crawler and CLI are marked available (a filled dot);
  WebGraph -- an LLM-built knowledge graph of a site with every node and edge cited to its
  page and block -- and Site Truth Report -- what a site shows people against what it sends
  crawlers, grounded in vtu.ac.in's ~60 off-screen gambling links per page (#88) -- are
  marked coming soon (a hollow ring). The chip carries the state in word and form; nothing
  coming soon is described as existing.
- Design tokens: `globals.css` now carries the spec's `tokens.css` -- light values on
  `:root`, a system-dark block and a `data-theme="dark"` block that wins over it, mapped
  onto Tailwind with `@theme inline` so utilities follow the theme; a type scale as
  utilities (`text-display` … `text-stat`); three radii (4 / 6 / 10px, replacing the
  Tailwind ramp so the run view's `rounded-2xl` panels flatten to 10px); one shadow, for
  things that float; reduced motion collapses every transition and turns the running dot
  into a static ring. The `--color-fd-*` bridge for the docs shell is in place. The run
  view, benchmarks, how-it-works and settings keep their earlier utility names through an
  alias block (`ink-soft`→`muted`, `ink-faint`→`faint`, `haze`→`ground`,
  `line`/`line-soft`→`rule`, `line-strong`→`rule-strong`, `leaf-*`→`accent`/`accent-ink`/
  `accent-soft`, `clay`/`flag-warn`→`warn`, `flag-bad`→`bad`, `shadow-lift`→`shadow-float`);
  `shadow-card` and `shadow-glass` are not aliased and now emit nothing.
- One header and footer for every page, from `layout.tsx`: Home, Products, Docs (the route
  is being built alongside), Benchmarks, How it works, GitHub; a theme toggle cycling
  System → Light → Dark, written to `data-theme` on `<html>` and remembered in
  `localStorage` under next-themes' key so the docs shell can share it; a "Run a site"
  button to `/#start`. Below 900px the items fold behind a "Menu" button that opens a
  full-width sheet with 48px rows. The bar takes the surface colour and a rule after 8px of
  scroll. The run view's banner loses the photograph band and its duplicate back link.
  Under `/docs` the header and footer step aside (`SiteChrome`): the docs shell draws its
  own bar and sidebar, and two navigations on one page is one too many.
- Known and open: `app/docs/docs.css` is a second Tailwind entry, and its utilities land
  after `globals.css`'s in the shared `utilities` layer. Once `/docs` has been visited the
  stylesheet stays loaded across client-side navigation, and any `hidden md:flex`-style
  pair on the rest of the site then loses to the docs copy of `.hidden` (measured: the
  nav collapsed to "Menu" at 1280px after visiting the docs). The new components write
  symmetric `max-md:` / `md:` pairs so no base utility is left to be overridden; the
  older pages (`/benchmarks`, `/how-it-works`, `/settings`, the run view) still carry
  such pairs. The fix is one Tailwind entry -- the Fumadocs preset imported from
  `globals.css`, as DESIGN.md §4c has it -- and belongs with the docs shell.
- Measured with Playwright at 1280 and 400px, light and dark: no page scrolls
  horizontally; the phone gutter is 16px; buttons are 44px under a coarse pointer; a
  remembered theme is on `<html>` at DOMContentLoaded (a `next/script` beforeInteractive
  variant was measured to set it after, and was not used).

### Added (2026-09-16, PR #92) — documentation site
- The web app serves documentation at `/docs`, built with Fumadocs from MDX files under
  `apps/web/content/docs/`. The sidebar has seven sections in a fixed order -- getting
  started, API, how it reads a page, crawling, benchmarks, deployment, contributing --
  each a placeholder page for now; the content follows in this pull request series. The
  landing page carries the README's opening and a card per section. Built-in full-text
  search (`/api/search`), a table of contents per page, light and dark themes, and a
  "Docs" link in the site header.
- The docs use the site's own palette and type (haze, ink, leaf; Manrope, JetBrains Mono,
  Instrument Serif for the title) and are styled by a stylesheet loaded only under
  `/docs`; the dark palette applies only while the docs layout is on the page, so the
  rest of the site renders exactly as before, also after navigating away from the docs.
  `apps/web/content/docs/_authoring.md` says how to add a page, what frontmatter it takes
  and which components are available.

### Fixed (2026-09-15, PR #90) — a block's XPath is the geometry map's
- The browser's measurements are keyed by each element's XPath in a fresh parse; the
  block walk removes hidden twins, clipped labels, permalinks and unreachable trays and
  only then computes a block's XPath -- and lxml writes `div[2]` while there are sibling
  divs and plain `div` once a removal leaves one, so every block below a removed sibling
  got a path the map did not hold. allbirds.com/collections/mens: 641 `display: none`
  elements first, 161 of 217 blocks without a rectangle, the page in source order, and the
  repeated product-card titles deduplicated as unmeasured text. Every element's path is now
  stamped (`PATH_ATTRIBUTE`) before the tree is edited and blocks read the stamp.
- Measured, whole page: nextjs.org/docs 0.940 → 0.979 recall, flipkart.com/mobiles 0.470
  → 0.975, allbirds collection 0.685 → 0.887 (219 of 304 blocks measured, all 34 cards),
  react.dev 0.996 → 1.000; fidelity suite cppreference 0.985 → 0.990, w3schools 0.994 →
  0.998, cameronsworld 0.992 → 1.000. Live suite: simonwillison.net R 0.75 → 0.92 / P 0.74
  → 0.84, discourse R 0.31 → 0.38, github issue P 0.00 → 0.25, astro +0.02. Boards (no
  geometry in the corpora): WCXB 0.8632 = 0.8632, Zyte 0.945 = 0.945, WebMainBench 0.7335
  → 0.7336.
- Known and open: ar.wikipedia's "القاهرة" now measures its 16-picture mid-article
  gallery, and the content boundary ends the article there (kept 654 → 274; whole-page
  output unaffected). Scoring a run of pictures and short captions as one unit fixed it
  and was rejected twice on the boards -- any short caption: WCXB −0.0016, WebMainBench
  −0.009; unlinked captions only: WCXB −0.0006, WebMainBench −0.005 (product-variant and
  related-story strips are galleries by that shape too).

### Fixed (2026-09-15, PR #89) — a browser answered with a server error is not a page
- flipkart.com/mobiles: the plain fetch returned the listing (200, 560 KB) and Chromium,
  seconds later, a 503 "No server is available to handle this request". The render
  reported `ok` -- it navigated and measured -- and the union merged the error page's
  sentence into the listing. `RenderResult.status` now carries the response's status
  (None for a salvaged timeout), and `resolve_page` treats a 5xx render as a failed side:
  the static page stands alone with `render_error` saying what the browser was told; both
  sides 5xx is a refusal. A 4xx render is still judged on its words, as before.

### Fixed (2026-09-15, PR #88) — text pushed off the page is not on the page
- vtu.ac.in (the owner's first live whole-site test) carries ~60 injected gambling links
  on every page, each in `<div style="position:absolute; left:-20914565266523px">`. The
  browser reports a box for them -- twenty trillion pixels to the left -- and the collector
  read "has a box" as "visible", so the whole-page Markdown opened with sixty lines of
  spam before "About VTU" and the reading order put them first. A box lying entirely at
  negative page coordinates is now hidden the way `display: none` is (`offscreen` in
  `collect.js`, an `_ABSENT_KINDS` member, honoured by `hidden_matter` so the union does
  not put the static copy back). Not inside a scroll container, though: w3schools' fixed
  sidebar and php.net's manual index scroll themselves to the current entry, and the
  entries above it have negative boxes while being one wheel tick away -- the first
  version dropped a heading on each. On a plain fetch the inline style that puts an
  element there (`position:absolute` with `left`/`top` ≤ -999px, or `text-indent` that
  far) is the same signal (`_drop_offscreen_styled`); `include_hidden_text` keeps it, as
  it keeps every other screen-reader-only string.
- Measured: vtu.ac.in/about-vtu 202 → 148 blocks, zero spam tokens, opens with "Online
  Fee Payment" as the screen does. Fidelity suite: unchanged except arxiv's off-screen
  "Skip to main content" link (now dropped, as the class rule already drops it elsewhere).
  Live suite: bbc's skip link likewise; every other column identical or page noise. WCXB
  0.8632 = 0.8632 (jococups.com's colour swatches, `text-indent:-9999px` labels a reader
  sees as coloured squares, move −0.074 on one page and +0.018 on another); Zyte
  0.945 = 0.945.

### Added (2026-09-15, PR #87) — discovery is visible
- The site run shows what robots.txt said and which sitemaps were tried. Two whole-site
  crawls the owner watched (vtu.ac.in, sode-edu.in, 14 Sep) reported `from_sitemap: 0`
  and nothing else: neither site publishes a sitemap, and no event said whether robots.txt
  existed, what it asked, or which addresses had been tried. `stream_site` now emits a
  `discovery` event after `analysis` -- `robots` (found, url, fetched_status, group,
  rules_for_us, crawl_delay, the file's text capped at `DISCOVERY_ROBOTS_TEXT_CHARS` with
  `text_truncated`/`text_chars`), `sitemaps` (every attempt with url / status / ok / urls /
  index / source, plus `found` and `total_urls`) and `seeds`. `RobotsPolicy` keeps `text`,
  `status`, `rules` and `group`; `discover_sitemaps` returns `(urls, attempts)` beside the
  unchanged `discover_sitemap_urls`; `SiteAnalysis` carries `robots_rules` and
  `sitemap_attempts` and prints them. One robots parser for both readers: the group
  selection in `fetch.robots.rule_that_applied` moved to `crawl.discovery.group_for_client`
  and `policy_for` builds its policy with the same `policy_from` the crawl uses.
- `frontier` and `page` events carry `discovered_kinds`: a running tally of discovered
  addresses by `url_kind` -- page, pdf, image, other_file, archive (`/2024/06/`,
  `/date/…`; a dated post permalink is a page), category, tag. On vtu.ac.in 7,907 of the
  17,126 discovered URLs were PDFs, which the crawl fetched one at a time to refuse each as
  not HTML -- a third of six hours -- and nothing on screen said so. Images and other files
  are counted once even though `normalize_url` never queues them, so the tally says what
  the site is rather than what the frontier holds. O(new URLs) per event.
- Web: a **How the site can be discovered** panel under the technology panel, three
  collapsed rows that open to their evidence -- "robots.txt · found · 1 rule applies to us
  · crawl-delay 1s" (the rules, then the file, monospace and scrollable), "Sitemaps · none
  published — discovery is by links only" (the table of attempts), "URLs found by kind"
  (live counts with a warning line when files outnumber pages). Extraction output is
  untouched: WCXB, Zyte, WCEB and WMB cannot move.

### Fixed (2026-09-15, PR #86) — prose before a code block
- A paragraph of four words or fewer directly before a `<pre>` was dropped as MDN's
  language-and-copy strip ("js Copy"). perldoc.perl.org/perlre lost "is made equivalent
  to", "For example, this program" and "will output the following:" -- sixty words of
  prose; pubs.opengroup.org's awk page lost its example lead-ins the same way. The strip
  is now a container that holds a button, or one whose words are all labels (a language
  name, the block's own declared language, "Copy"); a `<p>` is never the strip. Fidelity:
  perldoc 0.997 → 1.000, posix-awk 0.999 → 1.000. WebMainBench 0.7331 → 0.7335 (code_edit
  0.8468 → 0.8500, 12 pages up, none down); WCXB 0.8632 = 0.8632; Zyte 0.945 = 0.945.
- Reading those captions at all moved the content boundary on one tutorial: a dozen
  "Start the service:" lines each paid the block cost and Kadane ended the run before the
  last commands (WebMainBench 0ed88efa code_edit 1.000 → 0.874). A prose caption of at
  most `CODE_CAPTION_MAX_WORDS` before a code block is floored at zero like the code, and a
  run extends forward over the neutral code that closes it. Not a link strip: exploit-db's
  "« Previous Paper Next Paper »" above a `<pre>` bridged a metadata table into the run
  until captions were required to be prose (`link_density` ≤ 0.5).
- phpBB's `<p>Code: <a href="#">Select all</a></p>` is still the strip: a paragraph with a
  control that goes nowhere counts, one without does not.
- A highlighter's `language-undefined` (highlight.js on a block it could not classify)
  is no language: perldoc's fences came out as ```undefined, a word the page never
  showed. `none`, `plaintext`, `text`, `nohighlight` likewise.
### Fixed (2026-09-15, PR #85) — shadow DOM composed the way the browser paints it
- A serialised shadow root (`<template shadowrootmode>`, how the browser hands over what
  `outerHTML` omits) was unwrapped and the host's own children left behind it. That is not
  what a reader sees: a `<slot>`'s fallback text ("Untitled card", "Nothing was slotted
  here") came out although the browser had replaced it with the slotted content --
  invented text -- the slotted children landed after the whole component instead of at
  their slot, a title slotted into an `<h2>` stopped being a heading, and light children
  assigned to no slot, which the browser never renders, were read as paragraphs. The flat
  tree is now composed as the browser composes it: each slot replaced by what is assigned
  to it (`slot="name"` to the first `<slot name>`, the rest and the light text to the
  first unnamed slot), its fallback kept only when nothing is; what no slot takes is
  dropped; nested components inside out. `flatten_shadow_roots`, `_compose_slots`. No
  corpus page carries a shadow root (WCXB, Zyte, WCEB, WebMainBench: 0 files), so the
  boards cannot move; measured on the live and fidelity suites: github.com's `<relative-time>`
  no longer reads twice ("on Dec 5, 2022on Dec 5, 2022" → "on Dec 5, 2022", one duplicate
  block gone), MDN and every other page unchanged.

### Added (2026-09-14, PR #84) — bring your own HTML
- `/api/text` and `/api/text/stream` take `html`: the page as the caller already has it,
  from their own signed-in browser, an extension or a saved file. Nothing is fetched or
  rendered; the engine reads the paste (`resolve_supplied`, `Strategy.SUPPLIED`) and
  returns the same `text` / `markdown` / `content_markdown`. For the sites that refuse
  every automated fetch — stackoverflow.com answers both fetches with a Cloudflare
  challenge, nyc.gov with Akamai's, a login wall serves nothing to anyone signed out. The
  owner's decision is not to disguise the client to get past them; the reader who has the
  page hands it over instead.
- Never a false output: a pasted wall is refused as a fetched one is — a Cloudflare block
  page, a challenge script, an empty document all raise the same `PageBlockedError` /
  `ValueError` (502 on the API, an `error` event on the stream). A pasted login page has
  no redirect to be caught by, so its own `<link rel="canonical">` / `og:url` stands in
  for where the fetch ended: www.linkedin.com/login declares both as itself (measured
  2026-09-14), and a paste of it with the feed's URL is refused as a login redirect. `url`
  stays required (422 without
  it, or when not http(s)): links and images are made absolute against it. `render` is
  ignored. HTML over `FETCH_MAX_BYTES` (32 MB, the fetch limit) is refused with the limit
  named.
- The supplied path makes no request at all — a pasted `<frameset>` is parsed as the
  markup it is, not composed by fetching its frames, since a caller who can name frame
  URLs in a paste would otherwise be naming URLs for this process to fetch from inside its
  network. The stream skips the private-host guard for a supplied page (there is nothing
  for it to stop) and its `run` header says `strategy: supplied`, `render: false`.
- The result says what it is: `rendered_chars` 0, `static_chars` = `union_chars`, and
  `render_error` "HTML supplied by the caller; not fetched or rendered -- reading order
  is source order, and what the browser would have hidden may appear".
- Web: the single-page run has a "Paste the page's HTML instead" disclosure, opened for
  the reader when the fetch failed; the resolve stage then reads "Read the HTML you
  supplied" and the strategy "supplied by you". Schema mapping still fetches on its own
  and is off for a supplied run, and says so.
- Fetched output is unchanged: `resolve_page` gains only a guard refusing
  `strategy=SUPPLIED` (it would have fallen through to the union branch). Whole-page
  fidelity on columbia-sample, stallman.org and catb.org: identical recall / extra /
  inversions / blocks before and after.
### Changed (2026-09-14, PR #83) — a single page honours robots.txt
- `resolve_page` -- and so `/api/text`, `/api/text/stream`, `/api/extract` -- asks the
  host's robots.txt before fetching a page, as the crawl has since its first version. A
  page the file disallows for this client is not fetched; the refusal
  (`PageDisallowedError`) names the file, quotes the group and rule that decided
  (`User-agent: *` / `Disallow: /`), and says what the site offers instead -- its API
  where the engine can cite one (`ROBOTS_SANCTIONED_SOURCES`: Stack Overflow, Reddit) and
  the caller's own HTML. One fetch of the file per host per hour
  (`fetch/robots.py`); a file that cannot be fetched means allow. Per request:
  `FetchConfig.respect_robots` / `fetch.respect_robots` on the API, the same switch the
  crawl has always had. Measured on the live suite (24 sites, main@8b49391 vs this): two pages flip to a
  refusal -- thesun.co.uk (`User-agent: * / Disallow: /`, 189 blocks read before) and
  old.reddit.com (disallowed now, a login wall before); every other page identical
  (amazon's recall moved 0.69 → 0.27 on an oracle that served 566 vs 1,548 words to the
  two runs; our 1,163 words were the same). Fidelity suite: no page moved.
- Rules are asked for by the client's name. `urllib.robotparser` matches the first
  `/`-split token of the string it is given, and the engine's browser-shaped User-Agent
  made every rule for `webgraph` a rule for `mozilla`, which no robots.txt names; the crawl
  had the same bug (`RobotsPolicy.allows`, `crawl_delay`). `ROBOTS_AGENT_TOKEN`.

### Added (2026-09-14, PR #82) — a declared client for sites that ask who is calling
- sec.gov answers the engine's browser-shaped User-Agent with HTTP 403 and a page saying
  "Your Request Originates from an Undeclared Automated Tool … declare your traffic by
  updating your user agent to include company specific information". That is not a wall
  against automation, it is a question, and it is now answered: when a refusal says so
  (`declaration_demanded`) and the deployment has `WEBGRAPH_CONTACT` set
  (`Name contact@example.com`), the page is fetched again — static and browser — as
  `<contact> webgraph/0.1`, the form the site documents (measured: a URL in the string is
  refused, `Name email webgraph/0.1` is admitted). The contact goes only to a site that
  asked; every other page gets the ordinary fetch. Without a contact the refusal names the
  setting and quotes the demand (`PageBlockedError.kind == "undeclared"`); a site that keeps
  refusing a declared client is refused as such. `ResolvedPage.identity_declared` and the
  stream's `resolve` event say when a page was served to the declared client.

### Fixed (2026-09-14, PR #81) — the blocking API routes see walls
- `/api/text` and `/api/extract` resolve the page through `resolve_page`, the path the
  streaming route and the crawl already used. They fetched and parsed on their own, with
  none of the wall checks (#64, #67, #73): a Cloudflare block page served with a 200, or a
  login redirect, came back as a page of text with a green tick. Now both answer 502 with
  the wall's own words. `render=false` still escalates a JavaScript shell to the browser;
  without one, `/api/extract` still reads the shell's hydration payload (`PageShellError`
  carries the document) and `/api/text` refuses, having nothing to say.
- A static-only refusal says what the status means and quotes the server ("HTTP 403 -- the
  site refused this client; it said: …") instead of "HTTP 403"; the quote skips the block
  page's stylesheet, which used to be most of it.

### Changed (2026-09-14, PR #80) — docs
- `docs/SESSION-18-WHOLE-PAGE.md` closes the evening: PRs #71–#79 in the merge table, the
  standings at `main@f0b0ac4`, the fidelity suite on that commit recall 1.000 on 22 of 29 scored sites, sqlite.org 0.749 → 1.000, MDN extra 0.228 → 0.142; nothing below 0.945,
  and the open items with their sites. CONTRIBUTING names the rule the night taught:
  a change to table, code or Markdown rendering re-runs WebMainBench before merge.
- Recorded late for PR #76: the fidelity oracle reads open shadow roots' visible text
  beside `innerText` (a full DOM walk was measured and rejected — arngren.net recall
  0.99 → 0.877 under it), joins a frameset's frames, and reports `ORACLE BLOCKED`
  instead of a score when Chromium was served a wall.

### Changed (2026-09-14, PR #79)
- Benchmarks page: WCXB dev routed 0.861 → 0.862 (per type: article .945, docs .929,
  service .846, forum .801, collection .695, listing .706, product .637), WebMainBench
  overall 0.733 / table 0.395 after #78, measured at `main@19f601f`; the progression
  gains the whole-page step.

### Fixed (2026-09-14, PR #78)
- A pipe table's cells carry their links only when the caller asked for links; #68 had
  rendered `[text](href)` into every cell regardless of `include_links`, which cost
  WebMainBench (scored with links off) table_edit 0.390 → 0.338 unnoticed. Back to 0.395;
  overall 0.7284 → 0.7331.

### Fixed (2026-09-14, PR #75) — Markdown structure a reader sees
Found by a census of 25 old and plain pages against Chromium's own text.
- `<hr>` is a block (`BlockKind.RULE`, rendered `---`); it was dropped outright on 6 of
  the 14 census sites whose markup was inspected (catb.org, gutenberg.org, pgsql docs,
  ibiblio.org …). A rule has no text: it is not in `text`, not a block to the boundary
  step, the block model or the page-type router (each takes rules out and puts them back
  between kept neighbours), never content on its own, and never a duplicate. A rule the
  browser gave no box is not a line the reader sees and is left out. A page of rules and
  nothing else selects nothing (PR #77).
- `<dl>` renders as a definition list a reader can parse — `**term**` on one line, `:
  definition` on the next, the Markdown Extra / Pandoc / kramdown form — instead of
  alternating paragraphs (cl.cam.ac.uk's Unicode FAQ, every php.net parameter list). A
  `<dd>` holding paragraphs keeps them under its marker, a list inside one is indented.
- A table kept as its own markup (merged cells) fused the words on either side of a
  `<br>`, `<p>` or `<li>` inside a cell (`<td>a<br>b</td>` → `ab`); breaks are kept and
  block children get one, links stay, images in cells keep `src` and `alt` (both follow
  `include_links` / `include_images`, as everywhere else). Rendering
  such a table as pipes when its only span is a full-width title row was measured on
  WebMainBench and rejected (table_edit 0.3365 → 0.3305; the corpus's own truth writes
  that shape as HTML 6 times and as pipes once).
- An inline `<svg>` with `SVG_MIN_TEXT_NODES` (2) labels or `SVG_MIN_WORDS` (3) words is
  read for its `<text>` labels, in document order, joined with `·` (sqlite.org/lang.html's
  railroad diagrams: 206 → 267 words, a quarter of the page). An icon — a `<title>` and
  no text, or one word — still emits nothing, and leaves the sentence it sat in whole.

### Fixed (2026-09-14, PR #74)
- A skip link to the page's main region (`href="#content"` → `<main id="content">`) no
  longer makes every hidden container inside it count as "openable"; a reference to a
  region is not a control for a tray inside it, a reference to the tray itself still is.
  A page with a code editor keeps its hidden source listings for the editor's block.

### Added (2026-09-14, PR #73) — login walls
- A fetch redirected to a login page is refused as the wall it is, named as one:
  `PageBlockedError` says `redirected to a login page (<final url>)` and carries
  `login_url` and `kind` (`login` / `challenge` / `block`). The final URL has to hold a
  `LOGIN_PATH_MARKERS` segment (`/login`, `/uas/login`, `/signin`, `/sso`, `/auth`,
  `/session/new`, `/wp-login.php`, …) or a `LOGIN_RETURN_PARAMS` parameter naming the page
  that was asked for (`?dest=…`, `?session_redirect=…`, `?next=…`), and the document has
  to be a login page rather than a page with a login on it: a password field, or fewer
  than `MAX_LOGIN_PAGE_WORDS` (150) words. old.reddit.com's threads
  (`/login/?reason=lor2&dest=…`, 4 words) and www.linkedin.com/feed/
  (`/uas/login?session_redirect=…`, 52 words, two password fields) are refused;
  news.ycombinator.com (a "login" link, 711 words) and github.com/python/cpython are
  pages. A login redirect on one fetch beside the real page on the other is left out
  like a bot wall, and the page is read from the other side.

### Fixed (2026-09-14, PR #73) — code editors
- A browser-side code editor's DOM (CodeMirror 5 and 6, Monaco, Ace) is one `code` block:
  its lines in order, the gutter's line numbers, cursor and measuring layers left out,
  the language from the widget (`data-language`, `data-mode-id`, a `language=` attribute
  on the host). developer.mozilla.org's `<interactive-example>` came out as one
  paragraph per line number and one per line, with the other tab's lines scattered among
  them. An editor that draws only the lines in view (CodeMirror 6 shows 30 of MDN's 40)
  takes the whole text from the hidden `<pre>` the page holds beside it, once, so the
  demo's source appears whole and where the editor is (MDN's `<table>` page: 713 → 625
  rendered blocks; whole-page extra_share against Chromium's innerText 0.492 → 0.477,
  recall 1.0).

### Added (2026-09-14, PR #72)
- `benchmark/fidelity/run.py` (`make bench-fidelity`): the whole-page Markdown scored
  against Chromium on 32 old, plain and ugly pages — word recall (nothing lost), extra
  share (nothing added), order inversions, structure counts — with a cached oracle and
  `--compare`. It refuses to score a walled oracle and reads a frameset's frames. The PR
  template and CONTRIBUTING name it as the measure for changes to blocks, the union,
  ordering or rendering. `docs/SESSION-18-WHOLE-PAGE.md` records the session.

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
