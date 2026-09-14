<!--
Fill every section that applies; write "n/a" where one does not, rather than deleting it,
so a reviewer can see it was considered. Commit messages follow Conventional Commits and
carry the evidence (CONTRIBUTING.md). Link the issue with `Closes #123`.
-->

## Type of change

<!-- Tick one primary type. -->

- [ ] 🐛 Bug fix — a page, request or screen behaved wrongly and now does not
- [ ] ✨ Feature — a new capability of the engine, API or web app
- [ ] 📈 Quality — extraction / reading-order / routing accuracy, measured
- [ ] ⚡ Performance — faster or lighter, measured
- [ ] ♻️ Refactor — no behaviour change (say how you know)
- [ ] 🧪 Tests only
- [ ] 📝 Docs only
- [ ] 🔧 Build / CI / dependencies
- [ ] ⚠️ Breaking change — an API field, CLI flag, config name or output format changes (describe the migration below)

## Summary

<!-- Two or three sentences a release note could reuse: what a user of the engine, API or web app will notice. -->

Closes #

## The problem

<!--
What was wrong, from the user's side. For extraction work: the real page, what a reader sees
on it, and what webgraph produced instead. For a feature: what could not be done before.
-->

**Where it showed up:** <!-- URL(s), corpus page id(s), or the screen -->

**Expected:**

**Actual:**

## How to reproduce (before this change)

<!--
Exact steps a reviewer can run on `main`, from a fresh clone, to see the problem. Commands,
not prose, and only tools that are in this repository -- nothing from a local scratch
directory. Corpus paths are the `--corpus` clone the runner README names.
-->

```bash
# a live page, block by block through the production path (chosen / value / landmark / widget)
uv run python tools/inspect_page.py "https://example.com/page" --chosen
# a benchmark page against its ground truth (T = in the truth): WCXB by id, Zyte by id prefix
uv run python tools/inspect_corpus_page.py wcxb 0617 --corpus <wcxb clone> --disagree
uv run python tools/inspect_corpus_page.py zyte e372e42c --corpus <zyte clone>
# or the API
curl -s -X POST localhost:8000/api/text -H 'content-type: application/json' -d '{"url":"..."}' | jq .content_markdown
```

## Root cause

<!--
The mechanism, not the symptom. Which function, which assumption, which page shape.
"Kadane bridged into the comments because a comment's prose scores like an article's" —
not "content selection was wrong".
-->

## The fix

<!--
What changed and why this design. Mention what was tried first and rejected, with its
number, so nobody tries it again. Config knobs added go in packages/engine/src/webgraph/config.py.
-->

## Tests

<!--
Every behaviour this PR changes needs a test that fails without it. List them so the
reviewer can find them; a test that merely exercises the area is not enough.
-->

| test | what it proves |
|---|---|
| `tests/test_x.py::TestY::test_z` | |

- [ ] Each new test was run against `main` and **fails** there
- [ ] Each new test passes here

## Measurement

<!--
Required for extraction, reading-order, routing, discovery and performance changes.
"Not applicable" is fine for a docs or UI change; say so.

| benchmark | before | after |
|---|---:|---:|
| WCXB dev, routed — overall (`benchmark/wcxb/run.py`) | | |
| WCXB dev — the page types this touches (`benchmark/wcxb/per_page.py dump` on `main` and here, then `diff`) | | |
| Zyte article-extraction (anything touching articles; `benchmark/article_extraction/run.py`) | | |
| WCEB production path (anything touching comments, landmarks or the boundary; `benchmark/wceb/run.py`) | | |
| reading order — discriminating / stacked / side-by-side (`benchmark/reading_order/run.py`) | | |
| WebMainBench (anything touching tables, code, Markdown rendering) | | |
| Live suite (`benchmark/live/run.py` on `main` and here, then `--compare`): pages that moved | | |
| Whole-page fidelity (anything touching blocks, the union, ordering or Markdown rendering; `benchmark/fidelity/run.py` on `main` and here, then `--compare`): recall / extra / inversions on pages that moved | | |

Live pages re-checked (URL → what was verified):
-->

## Screenshots / output

<!--
Web UI: before and after, light and dark, phone width.
Extraction: the block list or Markdown before and after, trimmed to the relevant part.
-->

<details><summary>Before</summary>

</details>

<details><summary>After</summary>

</details>

## Risk and rollback

<!-- What else could this affect? How would we notice? Is there a config knob to turn it off? -->

## Checklist

- [ ] `make check` passes locally (ruff, mypy strict, engine + API + web tests, web build)
- [ ] Every changed behaviour has a test listed above that fails on `main`
- [ ] Measurements above are from the runners in `benchmark/`, on this commit, and the commit message carries them
- [ ] Rejected alternatives are recorded (commit message or "The fix")
- [ ] New config values are `NAME = value` with a comment in `config.py`, and appear in `/api/config`
- [ ] `MEMORY.md` updated if this overturns a recorded decision; `CHANGELOG.md` under Unreleased for anything user-visible
- [ ] Bundled assets recorded in `apps/web/public/ASSETS.md` with source and licence
- [ ] No secrets, personal data or scraped page content committed
- [ ] Branch will be deleted on merge (`gh pr merge --merge --delete-branch`)
