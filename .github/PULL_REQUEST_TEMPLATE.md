<!--
Thanks for contributing to webgraph. The sections below are what a reviewer needs to
approve without asking; please fill every one that applies and delete the ones that do not.
Commit messages follow Conventional Commits and carry the evidence (see CONTRIBUTING.md).
-->

## What this changes

<!-- One or two sentences. What a user of the engine, API or web app will notice. -->

## Why

<!--
The page, the bug, or the measurement that led here. Link the issue (`Closes #123`).
For extraction changes: which real page read wrongly, and what the mechanism was.
-->

## How it was measured

<!--
webgraph's rule: a claim is a measurement. Fill in what applies; "not measured" is an
acceptable answer only for changes that cannot affect extraction, routing or discovery.

| benchmark | before | after |
|---|---:|---:|
| WCXB dev, routed (`benchmark/wcxb/run.py`) | | |
| Zyte article-extraction (`benchmark/article_extraction/run.py`) | | |
| reading order (`benchmark/reading_order/run.py`) | | |

Per-type numbers for WCXB when the change is type-specific.
-->

## Rejected alternatives

<!-- What else was tried, with its number, so nobody tries it again. Delete if none. -->

## Checklist

- [ ] Every behaviour this PR changes has a test that fails without it
- [ ] `make check` passes locally (lint, types, engine + API + web tests)
- [ ] Extraction / routing / discovery changes carry before-and-after numbers above
- [ ] New config values live in `packages/engine/src/webgraph/config.py` as `NAME = value` with a comment
- [ ] `MEMORY.md` updated if this overturns a recorded decision
- [ ] Bundled assets recorded in `apps/web/public/ASSETS.md` with source and licence
- [ ] No secrets, personal data or scraped content committed

## Screenshots

<!-- For web UI changes: before and after, light and dark theme, phone width. Delete otherwise. -->
