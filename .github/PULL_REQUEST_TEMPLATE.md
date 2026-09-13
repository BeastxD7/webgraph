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

<!-- Exact steps a reviewer can run on `main` to see the problem. Commands, not prose. -->

```bash
# e.g.
uv run webgraph text "https://example.com/page" | head -40
# or
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
| WCXB dev, routed — overall | | |
| WCXB dev — the page types this touches | | |
| Zyte article-extraction (anything touching articles) | | |
| reading order — discriminating / stacked / side-by-side | | |
| WebMainBench (anything touching tables, code, Markdown rendering) | | |

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
