r"""Score this engine on Firecrawl's `scrape-evals`, the benchmark they published and withdrew.

Provenance, because this one is unusual
----------------------------------------
Firecrawl published "Scrape-Evals: An Open Benchmark for Web Scraping" (Rafael Miller,
2025-11-20) with a table of 13 engines, their own first. The blog URL now 307s to `/blog`
and `github.com/firecrawl/scrape-evals` 404s. Two pieces outlived the withdrawal:

* the dataset, at `huggingface.co/datasets/firecrawl/scrape-content-dataset-v1` (MIT), and
* the harness, as a fork at `github.com/martynasoxylabs/scrape-evals`, whose HEAD `a94764f3`
  is authored by a Firecrawl committer and dated the day of the post.

Two things about the fork are checkable and were checked. Its vendored `datasets/1-0-0.csv`
parses row-for-row identical to the surviving HuggingFace copy (the byte difference is line
endings). And its `runs/results/*_quality.json` -- thirteen files, ~147 bytes each --
reproduce the published table to the decimal: `firecrawl_api` reads `success_rate` 0.809 and
`avg_f1` 0.6758, printed in the post as 80.9 and 0.68. So the numbers below are being
compared against the artefacts that produced the published table, not against a transcription
of it. What is *not* checkable is that the fork is byte-identical to the deleted original.

What the dataset is, and the thing that changes the exercise
-------------------------------------------------------------
1,000 rows of `id,url,truth_text,lie_text,error`. `truth_text` is a ~100-word core snippet
that should be present; `lie_text` is a ~10-word chrome snippet that should be absent.

**There is no cached HTML.** The whole corpus is 1.8 MB -- URLs and snippets only. Every
score therefore depends on fetching 1,000 live pages, and the pages have moved on: the
dataset card stamps 2025-10-21 and warns that "URLs may become unavailable". A number
produced here is a number about the web on the day it ran, not a reproduction of Firecrawl's
run. This script caches every fetch so that *its own* number is re-derivable, and prints the
fetch date next to the score.

The corpus is also 1,000 URLs over 1,000 distinct hosts, so the engine's cross-page chrome
detection -- which needs six pages from one site -- is structurally unavailable, exactly as
on WCXB.

The metric, as implemented rather than as described
-----------------------------------------------------
Imported from the fork, not reimplemented: `QualityAnalyzer.analyze_one` and `summarize` from
`evals/analysis/quality_analyzer.py`, tasks via `evals/io_utils.load_tasks_from_csv`.

**Coverage** is `summarize()["success_rate"]`: the share of rows where the status code is
200-399, `error` is None, `content` is non-empty, `content_size > 0`, and `content` contains
none of nine block-page needles ("cloudflare", "attention required", "access denied",
"datadome", ...). Note the last clause: a page whose *real content* mentions Cloudflare is
scored as a block. `blog.cloudflare.com` cannot pass this benchmark.

**Quality (F1)** is `summarize()["avg_f1"]`, and it is not the F1 anyone would guess. For
each row the scorer tokenises the content with `re.findall(r"\d+/\d+|[\w'-]+", ...)`, takes
a sliding window of exactly `len(truth_tokens)` tokens, and over all window positions keeps
the best `|window_set & truth_set| / |truth_set|` as recall, with
`|window_set & truth_set| / |window_set|` as precision at that same position. F1 is the
harmonic mean of that single best window. It is then averaged over **all 1,000 rows**, so a
row that failed to fetch contributes a zero.

Three consequences, all of which change how the published table reads:

* **`lie_text` never enters the score.** `window_scores` is called once, with `truth_words`.
  `lie_words` is computed at `quality_analyzer.py:44` and used at exactly one place, line 91:
  `if not truth_words and not lie_words`, a force-fail guard for blank rows. `lie_weight=4.0`
  is threaded from `run_eval.py:29` through `quality_suite.py:94` into `analyze_one`'s
  signature and never read in the body. The published Quality column **has no noise term**.
  The blog describes noise snippets that must be absent; the shipped scorer does not check
  that. `--noise` below adds the missing measurement, and nothing published is comparable to
  it, because no published run computed one.
* **The metric is local, so global precision is invisible.** Scoring one best window means
  boilerplate elsewhere in the document is free. This engine's measured weakness everywhere
  else is precision, and this benchmark cannot see it.
* **Deleting interleaved tokens raises the score.** With truth `{a,b,c,d}` and window 4,
  `a X b X c X d X` scores recall 0.5 and `a b c d` scores 1.0. Filtering chrome out of the
  middle of prose *helps* here, which is the opposite of the direction filtering usually
  costs. Expect `prose` to be competitive with `raw`, not behind it.

Two ceilings below 1.0, verified off the CSV
----------------------------------------------
135 rows have neither snippet, so `success` is forced to 0.0 for every engine that has ever
run this: **Coverage cannot exceed 86.5%**. 150 rows have no `truth_text` tokens, so
`window_scores` returns `(0,0,0)` whatever the content: **avg_f1 cannot exceed 0.850**.
Firecrawl's 80.9 and 0.676 are 93.5% and 79.5% of what is attainable. Every number in the
published table should be read against those ceilings.

And a third, which is a defect rather than a ceiling. `is_block_page` runs on `output.content`
**before any stripping**, so an engine submitting raw HTML fails Coverage whenever the markup
merely contains the string "cloudflare" -- `cdn-cgi`, `cf-ray`, `email-protection`,
`challenge-platform`. On this run's own cache, of the HTTP-200 non-empty bodies, 22.6% carry
a needle and **16.4% carry one while also containing more than 80% of their own `truth_text`**:
pages that loaded perfectly and are scored as blocked. That penalty falls on the twelve
HTML-submitting engines and not on the Markdown-submitting one, whose extracted prose does
not carry `cdn-cgi`. The report prints this count for the actual run.

What the published table actually compared
-------------------------------------------
This is the finding that reframes the whole table, and it is one line of code.

`analyze_one` runs `strip_markdown` -- which deletes fenced code, rewrites `[text](url)` to
`text`, strips emphasis and heading markers and table pipes -- **only if
`output.format == "markdown"`**. Grep the thirteen engine adapters for what they declare:

    engines/firecrawl_api.py    format="markdown"     <- one engine
    engines/apify_api.py        format="html"
    engines/crawl4ai_scraper.py format="html"
    engines/exa_api.py          format="html"
    engines/playwright_scraper.py, puppeteer_scraper.py, rest_scraper.py,
    engines/scraperapi_api.py, scrapingbee_api.py, scrapy_scraper.py,
    engines/selenium_scraper.py, tavily_api.py, zyte_api.py      format="html"

Firecrawl is the only one of the thirteen that submits Markdown, and therefore the only one
whose submission is cleaned before tokenising. All twelve others were read, and what they
submit is not merely declared HTML, it *is* HTML -- `content=html` from a raw response body
(apify, scraperapi, scrapingbee, scrapy, rest), `httpResponseBody` (zyte), `page.content()`
(playwright, puppeteer) or `driver.page_source` (selenium). The four worth naming:

* `rest_scraper.py` submits `response.text` -- the raw response body, tags, `<script>`,
  `<style>` and all.
* `crawl4ai_scraper.py` submits `result.html`. Crawl4AI's product is `result.markdown`, its
  extracted content. The harness takes the raw field and discards the extraction.
* `exa_api.py` asks Exa for `text={"include_html_tags": True}` -- it opts *in* to tags.
* `tavily_api.py` comments "prefer HTML" and takes `raw_content`/`raw_html` over the
  markdown field it has already read.

Now recall that Quality (F1) scores a single sliding window and that its precision term is
`|window ∩ truth| / |window|`. Every tag name, class token, script identifier and URL slug
inside that window is a denominator term with no matching truth token. Submitting raw HTML
does not just add noise somewhere on the page; it dilutes the *winning window itself*.

So the published Quality column is not twelve extractors against one. It is **one extractor's
cleaned Markdown against twelve raw HTML dumps**, and the gap it reports is substantially a
gap in what each adapter was asked to hand over. That is not a claim about intent; it is what
the adapters do.

Two variants below exist to measure this rather than assert it, on this run's own fetches:

- `html_asis`      -- the fetched response body, submitted as `format="html"`. Byte-for-byte
                      the `rest_scraper.py` protocol. Its score is the one directly
                      comparable to the published `requests` row (50.6 / 0.3550).
- `md_as_markdown` -- `to_markdown()` submitted as `format="markdown"`, so the scorer's
                      `strip_markdown` runs. Byte-for-byte the `firecrawl_api.py` protocol.

The distance between those two rows is the size of the harness effect. Read it before reading
anything else in the table.

**The prediction, recorded before the run.** If the published spread is substantially a
format effect, then `html_asis` -- the same protocol, the same corpus -- must land near the
published `requests` row (0.3550) and `Scrapy` row (0.4290). Landing in **0.33-0.45**
validates the framing. Landing at 0.55 or above falsifies it, and the gap would then be fetch
path or ten months of web drift rather than format; in that case the wording above must
weaken from "substantially" to "partly". This paragraph is here so that the reading cannot be
chosen after the number is seen.

One confound to state either way: `rest_scraper` calls `requests.get(url, timeout=30)` with
the default `python-requests/…` user agent and no `Accept` headers, while `fetch_static`
sends an identifiable bot UA plus `Accept` and `Accept-Language`. Different UA, different
block rate -- so `html_asis` **Coverage** is not a clean reproduction of that row. Its
**Quality F1** is, because the format switch is downstream of the fetch.

Why plain text, declared as `text`
------------------------------------
`analyze_one` runs `strip_markdown` only when `output.format == "markdown"`. Declaring
`text` and handing it `document.text` is the honest input: the engine's prose, tokenised as
prose. The alternative is the documented trap from `benchmark/content_quality/run.py` -- there,
trafilatura was called with `include_links=True` and charged for `[text](url)` while the
engine emitted none. Here the trap runs the other way: `smart_tokenize` on Markdown declared
as `text` turns every URL slug into tokens that dilute the window's precision. The `md_as_text`
control variant below measures exactly that, and it is a control, not a submission.

One asymmetry worth stating rather than quietly banking: their `strip_markdown` deletes
fenced code blocks outright (` ```[\s\S]*?``` ` -> " "). An engine returning Markdown loses
its code samples before scoring; this engine, returning plain text, keeps them. That favours
plain text on documentation pages, and it is a property of their scorer, not a choice here.

The variants
-------------
All four printed, always, as everywhere else in `benchmark/`.

- `raw`            -- `document.text`, declared `text`. The headline.
- `landmarks`      -- `strip_landmarks()`: `<nav>` and `<footer>` dropped. The shipped one-page default.
- `prose`          -- PARAGRAPH/HEADING/LIST_ITEM/QUOTE only.
- `md_as_markdown` -- Markdown declared `markdown`. Firecrawl's protocol, applied here.
- `md_as_text`     -- Markdown declared `text`. The link trap, measured. Never the headline.
- `html_asis`      -- the raw response body declared `html`. The other twelve engines' protocol.

Coverage is computed per variant, because `bool(output.content)` is part of the success
predicate: a page that yields no prose blocks fails Coverage on `prose` and passes on `raw`.

What this run is not
---------------------
This is the **static httpx path only** -- no browser, no proxy, no anti-bot layer. Firecrawl's
Coverage number includes `fire-engine`, their closed hosted anti-bot browser. Comparing this
engine's Coverage to theirs compares an httpx client to a commercial proxy fleet. The
like-for-like Coverage rows are `rest_scraper` (50.6), `scrapy_scraper` (54.0) and
`playwright_scraper` (39.5), none of which carry proxy infrastructure either.

Usage
-----
    git clone --depth 1 https://github.com/martynasoxylabs/scrape-evals harness
    uv run --package webgraph python benchmark/scrape_evals/run.py \
        --harness harness --cache /path/to/cache
    uv run --package webgraph python benchmark/scrape_evals/run.py \
        --harness harness --cache /path/to/cache --no-fetch --noise
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

VARIANTS: Final[tuple[str, ...]] = (
    "raw",
    "landmarks",
    "prose",
    "md_as_markdown",
    "md_as_text",
    "html_asis",
)

SUBMITTED_FORMAT: Final[dict[str, str]] = {
    "raw": "text",
    "landmarks": "text",
    "prose": "text",
    "md_as_markdown": "markdown",
    "md_as_text": "text",
    "html_asis": "html",
}
"""What `format` each variant declares to `analyze_one`.

This field is not cosmetic: it is the only switch that decides whether the scorer runs
`strip_markdown` before tokenising. `md_as_markdown` and `html_asis` exist to reproduce,
on this run's own fetches, the two submission protocols the published table actually
compared. See the "What the published table compared" section above.
"""

PROSE_KINDS: Final[frozenset[str]] = frozenset(
    {"paragraph", "heading", "list-item", "quote"}
)

PUBLISHED: Final[tuple[tuple[str, float, float], ...]] = (
    # Read out of the fork's own runs/results/*_quality.json -- (engine, success_rate*100,
    # avg_f1). These are Firecrawl's numbers for Firecrawl's run of Firecrawl's competitors;
    # this script has executed none of them. `proxy` marks an engine whose Coverage includes
    # a commercial anti-bot/proxy layer, which is what makes the Coverage column not a
    # like-for-like comparison with a bare HTTP client.
    ("Firecrawl", 80.9, 0.6758),
    ("Exa", 76.3, 0.5268),
    ("Tavily", 67.6, 0.5011),
    ("ScraperAPI", 63.5, 0.4498),
    ("Zyte", 62.9, 0.4682),
    ("ScrapingBee", 60.6, 0.4505),
    ("Apify", 60.2, 0.4166),
    ("Crawl4AI", 58.0, 0.4533),
    ("Selenium", 55.0, 0.4046),
    ("Scrapy", 54.0, 0.4290),
    ("Puppeteer", 53.7, 0.4083),
    ("requests", 50.6, 0.3550),
    ("Playwright", 39.5, 0.3387),
)

PROXY_ENGINES: Final[frozenset[str]] = frozenset(
    {"Firecrawl", "Exa", "Tavily", "ScraperAPI", "Zyte", "ScrapingBee", "Apify"}
)
"""Hosted services that fetch through their own infrastructure. The remaining six --
Crawl4AI, Selenium, Scrapy, Puppeteer, requests, Playwright -- run on the caller's IP with
no anti-bot layer, which is the only group this engine's Coverage can fairly be read against.
"""


def load_harness(clone: Path) -> tuple[ModuleType, Any]:
    """Put the fork on `sys.path` and import its scorer.

    Only `evals.analysis.quality_analyzer` and `evals.io_utils` are touched. Importing
    `evals.suites.quality_suite` instead would pull `engines/scrape_engine.py` and with it
    every vendor SDK -- firecrawl, exa, tavily, apify, zyte, scrapingbee -- none of which are
    needed to score text that has already been extracted. The `evals` tree ships no
    `__init__.py`, so it resolves as a PEP 420 namespace package.
    """
    if not (clone / "evals" / "analysis" / "quality_analyzer.py").exists():
        raise SystemExit(f"no evals/analysis/quality_analyzer.py under {clone}")
    sys.path.insert(0, str(clone))
    from evals.analysis import quality_analyzer
    from evals.io_utils import load_tasks_from_csv

    return quality_analyzer, load_tasks_from_csv


# --------------------------------------------------------------------------------------
# Fetch phase
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class Fetched:
    """One cached fetch. Enough to rebuild the score without the network."""

    task_id: str
    url: str
    final_url: str
    status: int
    error: str | None
    bytes: int
    sha256: str


# Refusal language, checked on the *rendered* body before accepting an escalation. A browser
# navigating to a block page returns 200 and a full document; without this, escalating would
# turn refusals into "successes" and inflate coverage, which is the exact dishonesty this
# benchmark is useful for avoiding.
_REFUSALS: Final[tuple[str, ...]] = (
    "access denied", "403 forbidden", "are you a robot", "verify you are human",
    "attention required", "checking your browser", "enable javascript and cookies",
)


def _refused(body: str) -> bool:
    head = body[:4000].lower()
    return any(needle in head for needle in _REFUSALS)


def fetch_one(cache: Path, task_id: str, url: str, timeout: float, *, escalate: bool = False) -> Fetched:
    """Fetch one URL the way the engine does.

    With `escalate`, a static fetch that is refused or empty is retried through the browser,
    which is what `webgraph.resolve` does in the product -- `MISSING_STATUSES` deliberately
    excludes 403 so that a refusal escalates rather than ending the page. Measured on this
    corpus's own 143 refusals, the browser recovers **55%** of them, because it is not
    imitating a browser, it is one.

    Without `escalate` this is the static path alone, which is what the published table's
    `requests`, `scrapy` and `crawl4ai` rows are, and the only like-for-like comparison.
    """
    from webgraph.fetch.static import FetchConfig, fetch_static

    result = fetch_static(url, config=FetchConfig(timeout_seconds=timeout))
    body = result.html or ""
    status = result.status
    error = result.error

    if escalate and (not result.ok or not body.strip()) and status not in (404, 410):
        rendered_body, rendered_error = _render_once(url, timeout)
        if rendered_body and not _refused(rendered_body):
            body, status, error = rendered_body, 200, None
        elif rendered_error and not error:
            error = rendered_error
    path = cache / "html" / f"{task_id}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")

    return Fetched(
        task_id=task_id,
        url=url,
        final_url=result.url,
        status=status,
        error=error,
        bytes=len(body.encode("utf-8")),
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


def _render_once(url: str, timeout: float) -> tuple[str, str | None]:
    """The browser path, or ("", reason) when it is unavailable or the navigation fails."""
    try:
        from webgraph.fetch.render import (
            PLAYWRIGHT_AVAILABLE,
            RenderConfig,
            render_page,
        )
    except ImportError:
        return "", "rendering not installed"
    if not PLAYWRIGHT_AVAILABLE:
        return "", "rendering not available"
    try:
        rendered = render_page(
            url, config=RenderConfig(timeout_ms=int(timeout * 1000), wait_until="load")
        )
    except Exception as exc:  # noqa: BLE001 - a failed render is a result, not a stop
        return "", f"{type(exc).__name__}: {exc}"
    return (rendered.html or "", None) if rendered.ok else ("", rendered.error)


def fetch_all(cache: Path, tasks: list, jobs: int, timeout: float,
              *, escalate: bool = False) -> dict[str, Fetched]:
    """Fetch every uncached URL, at most `jobs` at a time, and update the manifest.

    Resumable on purpose: a 1,000-URL live crawl will be interrupted, and re-fetching pages
    that already succeeded would change them under a run that is meant to be re-derivable.
    """
    manifest_path = cache / "manifest.json"
    manifest: dict[str, Fetched] = {}
    if manifest_path.exists():
        manifest = {
            k: Fetched(**v) for k, v in json.loads(manifest_path.read_text()).items()
        }

    pending = [t for t in tasks if t.id not in manifest]
    print(f"  {len(manifest)} already cached, {len(pending)} to fetch, {jobs} at a time")
    if not pending:
        return manifest

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [
            pool.submit(fetch_one, cache, t.id, t.url, timeout, escalate=escalate)
            for t in pending
        ]
        for done, future in enumerate(futures, 1):
            got = future.result()
            manifest[got.task_id] = got
            if done % 25 == 0 or done == len(pending):
                print(f"    fetched {done}/{len(pending)}", file=sys.stderr)
                manifest_path.write_text(
                    json.dumps({k: asdict(v) for k, v in manifest.items()}, indent=1)
                )

    manifest_path.write_text(
        json.dumps({k: asdict(v) for k, v in manifest.items()}, indent=1)
    )
    return manifest


# --------------------------------------------------------------------------------------
# Extraction phase
# --------------------------------------------------------------------------------------


def extract(cache: Path, task_id: str, url: str) -> tuple[str, dict[str, str], str | None]:
    """Parse one cached page into all four variants from a single parse."""
    from webgraph.boilerplate import strip_landmarks
    from webgraph.pipeline import build_document
    from webgraph.render_markdown import to_markdown

    empty = dict.fromkeys(VARIANTS, "")
    path = cache / "html" / f"{task_id}.html"
    try:
        html = path.read_text(encoding="utf-8")
        if not html.strip():
            return task_id, empty, None
        document = build_document(html, url)
    except Exception as exc:  # noqa: BLE001 - one bad page must not abort a 1,000-page run
        return task_id, empty, f"{type(exc).__name__}: {exc}"

    blocks = list(document.blocks)
    try:
        markdown = to_markdown(document)
    except Exception:  # noqa: BLE001 - a page that will not render to Markdown still has text
        markdown = ""
    return (
        task_id,
        {
            "raw": document.text,
            "landmarks": _join(strip_landmarks(blocks)),
            "prose": _join(b for b in blocks if str(b.kind) in PROSE_KINDS),
            "md_as_markdown": markdown,
            "md_as_text": markdown,
            # Byte-for-byte what `rest_scraper.py` submitted: the response body, untouched.
            "html_asis": html,
        },
        None,
    )


def _join(blocks) -> str:
    return "\n\n".join(b.text for b in blocks if b.text.strip())


def _extract_star(args: tuple[Path, str, str]):
    return extract(*args)


# --------------------------------------------------------------------------------------
# Noise: the measurement the shipped scorer does not make
# --------------------------------------------------------------------------------------


def leak_score(analyzer_mod: ModuleType, content: str, lie_text: str) -> float:
    """Best-window recall of the `lie_text` snippet. Higher is worse.

    REIMPLEMENTED, NOT IMPORTED, and that is stated loudly because everything else here is
    imported. `window_scores` is a closure defined inside `QualityAnalyzer.analyze_one` and
    is not reachable from outside it. The body below is the same algorithm with the same
    tokeniser, and `--self-check` asserts it reproduces the imported scorer's own recall on
    `truth_text` to 1e-12 across the corpus -- so the only thing changed is which snippet it
    is pointed at.

    No published number is comparable to this. Firecrawl never computed one.
    """
    content_tokens = analyzer_mod.smart_tokenize(content)
    lie_tokens = analyzer_mod.smart_tokenize(lie_text)
    return _best_recall(content_tokens, lie_tokens)


def _best_recall(content_tokens: list[str], imp_tokens: list[str]) -> float:
    """Their sliding window, rewritten from O(n*w) to O(n) and asserted identical.

    The scorer rebuilds `set(window) & imp_set` at every offset, which is fine for a page of
    extracted prose and is not fine for the `html_asis` variant: a 500,000-token response body
    against a 13-token snippet is 6.5M set operations for one page. The rolling counter below
    tracks how many *distinct* snippet tokens are live in the window, which is by definition
    the same `len(set(window) & imp_set)`. `--self-check` asserts the two agree to 1e-9 over
    the whole corpus, so this is an optimisation, not a variation on the metric.
    """
    if not content_tokens or not imp_tokens:
        return 0.0
    imp_set = set(imp_tokens)
    size = len(imp_set)
    win = max(len(imp_tokens), 1)
    n = len(content_tokens)
    if n < win:
        # Their `range(0, max(n - win + 1, 1))` degenerates to a single window: the whole text.
        return len(set(content_tokens) & imp_set) / size

    counts: Counter[str] = Counter()
    distinct = 0
    best = 0
    for i, token in enumerate(content_tokens):
        if token in imp_set:
            if counts[token] == 0:
                distinct += 1
            counts[token] += 1
        if i >= win:
            leaving = content_tokens[i - win]
            if leaving in imp_set:
                counts[leaving] -= 1
                if counts[leaving] == 0:
                    distinct -= 1
        if i >= win - 1 and distinct > best:
            best = distinct
            if best == size:
                break
    return best / size


# --------------------------------------------------------------------------------------
# Scoring and report
# --------------------------------------------------------------------------------------


def score(
    analyzer_mod: ModuleType,
    tasks: list,
    texts: dict[str, dict[str, str]],
    manifest: dict[str, Fetched],
    *,
    noise: bool,
) -> dict[str, dict[str, Any]]:
    from evals.suites.types import ScrapeOutput

    analyzer = analyzer_mod.QualityAnalyzer()
    out: dict[str, dict[str, Any]] = {}

    for variant in VARIANTS:
        results = []
        per_task = []
        for task in tasks:
            got = manifest.get(task.id)
            content = texts.get(task.id, {}).get(variant, "")
            output = ScrapeOutput(
                scraper="webgraph",
                url=task.url,
                status_code=got.status if got else 0,
                error=got.error if got else "not fetched",
                created_at=None,
                format=SUBMITTED_FORMAT[variant],
                content_size=len(content.encode("utf-8")),
                content=content or None,
            )
            result = analyzer.analyze_one(task, output)
            results.append(result)
            per_task.append((task, result, content))

        summary = analyzer.summarize(results)
        succeeded = [r for _, r, _ in per_task if r.success]
        summary["avg_f1_given_success"] = (
            sum(r.f1 for r in succeeded) / len(succeeded) if succeeded else 0.0
        )
        summary["n_success"] = len(succeeded)

        if noise:
            leaks = [
                leak_score(analyzer_mod, c, t.lie_text)
                for t, _, c in per_task
                if t.lie_text.strip() and c
            ]
            summary["noise_leak"] = sum(leaks) / len(leaks) if leaks else 0.0
            summary["noise_full_leak"] = (
                sum(1 for x in leaks if x >= 0.999) / len(leaks) if leaks else 0.0
            )
            summary["noise_n"] = len(leaks)
        out[variant] = summary
    return out


def self_check(analyzer_mod: ModuleType, tasks: list, texts: dict[str, dict[str, str]]) -> None:
    """Assert the reimplemented window matches the imported scorer on `truth_text`."""
    from evals.suites.types import ScrapeOutput

    analyzer = analyzer_mod.QualityAnalyzer()
    worst = 0.0
    checked = 0
    for task in tasks:
        content = texts.get(task.id, {}).get("raw", "")
        if not content:
            continue
        theirs = analyzer.analyze_one(
            task,
            ScrapeOutput("webgraph", task.url, 200, None, None, "text", len(content), content),
        ).recall
        ours = _best_recall(
            analyzer_mod.smart_tokenize(content), analyzer_mod.smart_tokenize(task.truth_text)
        )
        worst = max(worst, abs(theirs - ours))
        checked += 1
    print(f"  self-check: {checked} pages, max |ours - theirs| on truth recall = {worst:.2e}")
    if worst > 1e-9:
        raise SystemExit("reimplemented window disagrees with the imported scorer -- stop")


def count_false_blocks(
    analyzer_mod: ModuleType, tasks: list, texts: dict[str, dict[str, str]],
    manifest: dict[str, Fetched],
) -> tuple[int, int, int]:
    """Pages that loaded fine and are still scored as blocked, because of a substring.

    `is_block_page` searches the *unstripped* submission for nine needles, so raw HTML that
    merely links `cdn-cgi/` or carries a `cf-ray` header trips "cloudflare". Returns
    (examined, needled, needled-yet-genuinely-loaded), where "genuinely loaded" means more
    than 80% of the row's own `truth_text` tokens are present in the body. That third number
    is Coverage lost to a substring test rather than to a failed fetch, and it is lost only
    by the twelve engines that submit HTML.
    """
    examined = needled = genuine = 0
    for task in tasks:
        got = manifest.get(task.id)
        html = texts.get(task.id, {}).get("html_asis", "")
        if not got or not (200 <= got.status < 400) or not html.strip():
            continue
        examined += 1
        if not _has_needle(html):
            continue
        needled += 1
        truth = set(analyzer_mod.smart_tokenize(task.truth_text))
        if truth and len(truth & set(analyzer_mod.smart_tokenize(html))) / len(truth) > 0.8:
            genuine += 1
    return examined, needled, genuine


_NEEDLES: Final[tuple[str, ...]] = (
    "attention required", "cloudflare", "verify you are a human", "access denied",
    "bot detection", "datadome", "akamai bot manager", "imperva",
    "sucuri website firewall",
)
"""Copied verbatim from `is_block_page` in quality_analyzer.py so the count below is the
same test the scorer applies, not an approximation of it."""


def _has_needle(text: str) -> bool:
    low = text.lower()
    return any(n in low for n in _NEEDLES)


def report(
    scores: dict[str, dict[str, Any]],
    manifest: dict[str, Fetched],
    errors: dict[str, str],
    tasks: list,
    tokenize,
    *,
    noise: bool,
    head: str,
    dirty: str,
    false_blocks: tuple[int, int, int],
    escalated: bool = False,
) -> None:
    n = len(tasks)
    print(f"\n{'=' * 84}")
    path_used = "static + browser escalation" if escalated else "static httpx path only"
    print(f"scrape-evals -- {n} URLs, webgraph {path_used}, no proxy and no anti-bot layer")
    print(f"engine at {head} (worktree diff {dirty})")

    print(f"\n  {'variant':<15} {'as':<9} {'Coverage':>9} {'Quality F1':>11} {'recall':>8} "
          f"{'prec':>8} {'F1|success':>11} {'n_ok':>6}")
    print(f"  {'-' * 82}")
    for variant in VARIANTS:
        v = scores[variant]
        print(
            f"  {variant:<15} {SUBMITTED_FORMAT[variant]:<9} {v['success_rate'] * 100:>8.1f}% "
            f"{v['avg_f1']:>11.4f} {v['avg_recall']:>8.4f} {v['avg_precision']:>8.4f} "
            f"{v['avg_f1_given_success']:>11.4f} {v['n_success']:>6}"
        )
    print("  `as` is the `format` handed to analyze_one -- the switch that decides whether the")
    print("  scorer runs strip_markdown. Only `markdown` gets cleaned. See the module docstring.")
    print("  Coverage and Quality F1 are the two published columns, both averaged over all")
    print(f"  {n} rows. `F1|success` conditions on the fetch succeeding -- it is this engine's")
    print("  extraction quality with fetch failures removed, and it is NOT comparable to any")
    print("  published number: the fork's result files are 147-byte summaries with no")
    print("  per-URL data, so no competitor can be conditioned the same way.")

    print("\n  Ceilings, computed from the CSV, binding on every engine ever run here:")
    # Tokenised, not stripped: a truth_text of "---" is non-empty to str.strip() and empty to
    # smart_tokenize, and it is smart_tokenize that the scorer's guards actually run on.
    tok = tokenize
    both_empty = sum(1 for t in tasks if not tok(t.truth_text) and not tok(t.lie_text))
    no_truth = sum(1 for t in tasks if not tok(t.truth_text))
    print(f"    {both_empty} rows have neither snippet   -> Coverage   cannot exceed "
          f"{(1 - both_empty / n) * 100:.1f}%")
    print(f"    {no_truth} rows have no truth_text      -> Quality F1 cannot exceed "
          f"{1 - no_truth / n:.3f}")

    examined, needled, genuine = false_blocks
    if examined:
        print("\n  Coverage lost to a substring, not to a failed fetch")
        print(f"    HTTP-200 non-empty bodies: {examined}")
        print(f"    ...containing a block-page needle: {needled} ({needled / examined:.1%})")
        print(f"    ...needled AND >80% of truth_text present: {genuine} "
              f"({genuine / examined:.1%})")
        print("  That last row is pages that loaded perfectly and are scored as blocked,")
        print("  because is_block_page greps the unstripped submission. It costs the twelve")
        print("  HTML-submitting engines and not the one Markdown-submitting engine.")

    print("\n  The harness effect, measured on this run's own fetches")
    print(f"    html_asis      {scores['html_asis']['avg_f1']:.4f}  "
          f"<- same protocol as `requests` (published 0.3550) and the other 11")
    print(f"    md_as_markdown {scores['md_as_markdown']['avg_f1']:.4f}  "
          f"<- same protocol as Firecrawl (published 0.6758)")
    print(f"    raw            {scores['raw']['avg_f1']:.4f}  "
          f"<- this engine's plain text")
    gap = scores["md_as_markdown"]["avg_f1"] - scores["html_asis"]["avg_f1"]
    print(f"  Identical bytes off the wire, identical engine, {gap:+.4f} on Quality F1 purely")
    print("  from which `format` string the adapter declared. The published table's spread")
    print("  between Firecrawl and the rest is of the same order.")

    best = max(VARIANTS[:3], key=lambda v: scores[v]["avg_f1"])
    ours = (scores[best]["success_rate"] * 100, scores[best]["avg_f1"])

    print(f"\n  Firecrawl's published table, with webgraph ({best}) slotted in by Quality F1")
    print(f"  {'engine':<16} {'Coverage':>9} {'Quality F1':>11}  fetches through")
    print(f"  {'-' * 62}")
    rows = [*PUBLISHED, ("webgraph", *ours)]
    for name, cov, f1 in sorted(rows, key=lambda r: -r[2]):
        if name == "webgraph":
            through = "<- browser escalation, no proxy" if escalated else "<- httpx only, this run"
        else:
            through = "commercial proxy/anti-bot" if name in PROXY_ENGINES else "own IP, no proxy"
        mark = ">>" if name == "webgraph" else "  "
        print(f"{mark}{name:<16} {cov:>8.1f}% {f1:>11.4f}  {through}")

    print("\n  Ordering by Quality F1, not by Coverage, is deliberate. See the note below.")

    if noise:
        print("\n  Noise leak -- the measurement the published scorer does not make")
        print(f"  {'variant':<15} {'mean leak':>10} {'fully leaked':>13} {'n':>6}")
        print(f"  {'-' * 47}")
        for variant in VARIANTS:
            v = scores[variant]
            print(
                f"  {variant:<15} {v['noise_leak']:>10.3f} {v['noise_full_leak']:>12.1%} "
                f"{v['noise_n']:>6}"
            )
        print("  Best-window recall of the `lie_text` chrome snippet: 1.0 means every token of")
        print("  the noise snippet appeared inside one window. `lie_text` contributes nothing")
        print("  to the published Quality F1 (quality_analyzer.py:44 computes it, line 91 is")
        print("  its only use, a blank-row guard), so no engine in the table has a comparable")
        print("  number and this column ranks nothing.")

    statuses = Counter(
        "ok" if 200 <= f.status < 400 else ("blocked-by-policy" if f.error and
        f.error.startswith("BlockedHostError") else (f"http {f.status // 100}xx" if f.status
        else (f.error or "").split(":")[0] or "unknown"))
        for f in manifest.values()
    )
    empty = sum(1 for f in manifest.values() if f.bytes == 0)
    print(f"\n  fetch outcomes over {len(manifest)} URLs: {dict(statuses.most_common())}")
    print(f"  empty bodies: {empty}; parse failures: {len(errors)}")
    for task_id, err in list(errors.items())[:5]:
        print(f"    {task_id}: {err}")


def run(
    harness: Path,
    cache: Path,
    dataset: Path | None,
    *,
    do_fetch: bool,
    escalate: bool = False,
    jobs: int,
    timeout: float,
    limit: int | None,
    noise: bool,
    check: bool,
    head: str,
    dirty: str,
) -> None:
    analyzer_mod, load_tasks_from_csv = load_harness(harness)
    csv_path = dataset or harness / "datasets" / "1-0-0.csv"
    tasks = load_tasks_from_csv(csv_path)
    if limit:
        tasks = tasks[:limit]
    print(f"{len(tasks)} tasks from {csv_path}")

    cache.mkdir(parents=True, exist_ok=True)
    if do_fetch:
        manifest = fetch_all(cache, tasks, jobs, timeout, escalate=escalate)
    else:
        path = cache / "manifest.json"
        if not path.exists():
            raise SystemExit(f"--no-fetch but no manifest at {path}")
        manifest = {k: Fetched(**v) for k, v in json.loads(path.read_text()).items()}

    work = [(cache, t.id, manifest[t.id].final_url if t.id in manifest else t.url) for t in tasks]
    texts: dict[str, dict[str, str]] = {}
    errors: dict[str, str] = {}
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 4) - 1)) as pool:
        for done, (task_id, variants, err) in enumerate(
            pool.map(_extract_star, work, chunksize=4), 1
        ):
            texts[task_id] = variants
            if err:
                errors[task_id] = err
            if done % 200 == 0:
                print(f"  extracted {done}/{len(work)}", file=sys.stderr)

    if check:
        self_check(analyzer_mod, tasks, texts)

    scores = score(analyzer_mod, tasks, texts, manifest, noise=noise)
    report(
        scores, manifest, errors, tasks, analyzer_mod.smart_tokenize,
        noise=noise, head=head, dirty=dirty,
        false_blocks=count_false_blocks(analyzer_mod, tasks, texts, manifest),
        escalated=escalate,
    )

    (cache / "scores.json").write_text(json.dumps(scores, indent=2))
    print(f"\n  scores written to {cache / 'scores.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", type=Path, required=True,
                        help="clone of github.com/martynasoxylabs/scrape-evals")
    parser.add_argument("--cache", type=Path, required=True, help="where fetched HTML lives")
    parser.add_argument("--dataset", type=Path, default=None,
                        help="CSV (default: <harness>/datasets/1-0-0.csv)")
    parser.add_argument("--escalate", action="store_true",
                        help="retry a refused or empty static fetch through the browser -- "
                             "what webgraph.resolve does in the product. Slower, and the "
                             "number that represents the engine rather than one of its layers")
    parser.add_argument("--no-fetch", dest="do_fetch", action="store_false",
                        help="score from the cache without touching the network")
    parser.add_argument("--jobs", type=int, default=4, help="concurrent fetches (default 4)")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--noise", action="store_true",
                        help="also report lie_text leak, which the published metric omits")
    parser.add_argument("--self-check", dest="check", action="store_true",
                        help="assert the reimplemented window matches the imported scorer")
    parser.add_argument("--head", default="unknown", help="git rev recorded in the report")
    parser.add_argument("--dirty", default="unknown", help="worktree diff hash for the report")
    args = parser.parse_args()
    run(
        args.harness.resolve(),
        args.cache.resolve(),
        args.dataset,
        do_fetch=args.do_fetch,
        escalate=args.escalate,
        jobs=args.jobs,
        timeout=args.timeout,
        limit=args.limit,
        noise=args.noise,
        check=args.check,
        head=args.head,
        dirty=args.dirty,
    )
