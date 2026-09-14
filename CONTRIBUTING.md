# Contributing to webgraph

## Getting set up

```bash
make install     # uv sync + playwright chromium + pnpm install
make api         # FastAPI on :8000
make web         # Next.js on :3000
```

Run `make api` and `make web` in two terminals for the full stack.

## Before every commit

```bash
make check       # lint + types + every test suite
```

`mypy` runs in strict mode and the web app builds with
`typescript.ignoreBuildErrors: false`, so a type error is a build failure, not a warning.

### If you touched dependencies, also run this

```bash
make check-clean   # clone to a temp directory and install from cold
```

A warm `node_modules` hides install failures completely. One did, through **26 consecutive
red CI runs**: pnpm refuses to install until every dependency with a build script is
explicitly allowed, and the approval already sat in the local tree from an earlier
interactive install. Every local check passed the whole time. `make check-clean` reproduces
what CI actually does.

## The three rules every change follows

1. **Every fix ships with the test that fails without it.** Not a test in the general area:
   a test of the specific page shape or behaviour that was wrong, named after it. A PR that
   changes behaviour and adds no test is sent back. (This was audited across fifteen PRs in
   September 2026 and three had slipped; they were backfilled in #28.)
2. **A claim is a measurement.** A change to extraction, reading order, routing or discovery
   carries before-and-after numbers from the runners in `benchmark/` — WCXB dev by page type
   at minimum, Zyte for anything touching articles, the reading-order benchmark for anything
   touching `dom/reading_order.py`. The PR template has the table. Neutral-to-negative
   results are recorded in the commit message as rejected, so the next person does not
   repeat them.
3. **One branch: `main`.** Work happens on a short-lived branch, lands through a pull request
   with green CI, is merged, and the branch is deleted in the same step. Nothing lives on a
   second long-running branch.

## Branch and pull request flow

```bash
git checkout -b <type>/<short-name>          # e.g. fix/aside-callouts
# ... commit with the conventions below ...
git push -u origin <branch>
gh pr create                                 # the template asks for what a reviewer needs
gh pr checks --watch                         # engine, api and web jobs
gh pr merge --merge --delete-branch
```

CI runs ruff and mypy (strict) over the engine, the engine and API test suites, a benchmark
gate over `benchmark/corpus-v0`, and the web app's lint, typecheck and build. Everything CI
runs is in `make check`; run it before pushing.

## Commit conventions

Commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types**

| type | use for |
|---|---|
| `feat` | a new capability |
| `fix` | a bug fix |
| `perf` | a change made for speed, with the measurement in the body |
| `refactor` | a change that alters neither behaviour nor performance |
| `test` | tests only |
| `docs` | documentation only |
| `build` | dependencies, packaging, tool configuration |
| `ci` | GitHub Actions and other automation |
| `chore` | anything else that touches no source |

**Scopes** are the workspace or module the change lands in: `engine`, `api`, `web`,
`bench`, `docs`, or a module path such as `engine/boilerplate`.

**Subject** is imperative, lower case, no trailing full stop, and under 72 characters.

A breaking change is marked with `!` after the scope (`feat(engine)!: …`) and explained
under a `BREAKING CHANGE:` footer.

### The body carries the evidence

This project's rule is that a claim is a measurement. If a commit says something is faster,
more complete or more accurate, the body says by how much and against what:

```
perf(engine): reuse one browser per crawl worker thread

Relaunching Chromium per page was a fixed cost on every render. Playwright's sync
API binds a driver to its creating thread, so the browser is thread-local rather
than pooled; each page still gets a fresh context for isolation.

Measured on 12 renders of persyn.ai:

  workers=1   8.5 -> 11.6 pages/min
  workers=6  21.9 -> 39.1 pages/min
```

## Reporting a page that reads wrongly

The most useful contribution is a URL. Open an
[extraction quality report](https://github.com/BeastxD7/webgraph/issues/new?template=extraction_quality.yml);
it asks for the page, what a reader sees, and what webgraph produced. Every extraction fix
in `docs/SESSION-16-LIVE-HARDENING.md` began as exactly that.

To diagnose one yourself: `uv run python tools/inspect_page.py <url>` prints a live page
block by block through the production path -- chosen or not, the value the boundary step
gave it, landmark, widget, whether the browser measured it; `tools/inspect_corpus_page.py`
does the same for a WCXB or Zyte page beside its ground truth; the web UI's "Copy run logs"
carries every decision the engine made for that page. To check a change against the web
rather than the corpora, `benchmark/live/run.py` scores a fixed set of live sites through
the production path against Chromium's own text and diffs two runs; a page that moves is
a page to open. These are the tools the pull-request template's "how to reproduce"
section expects -- nothing that lives only on one machine.

## Where decisions are recorded

`MEMORY.md` is the project's engineering journal: numbered decisions (`D1`…), what was
tried and failed, and the measurement behind every settled choice. **Read it before
changing extraction, discovery or chrome detection** — several obvious-looking improvements
in those areas have already been tried and measured as neutral or harmful, and the reasons
are written down.

If a change overturns something in `MEMORY.md`, update the entry in the same commit.

## Adding a bundled asset

Third-party images, fonts and data files go in `apps/web/public/` and **must** be recorded
in `apps/web/public/ASSETS.md` with source, author and licence in the same commit.
