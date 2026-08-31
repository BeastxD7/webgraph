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
make lint        # ruff + mypy --strict (engine and API) + eslint + tsc
make test        # engine and API test suites
```

Both must be clean. `mypy` runs in strict mode and the web app builds with
`typescript.ignoreBuildErrors: false`, so a type error is a build failure, not a warning.

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
