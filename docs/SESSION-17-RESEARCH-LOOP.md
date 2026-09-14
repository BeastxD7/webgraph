# Research loop: five merged fixes, one correction, measured on four boards

The brief: research → experiment → keep only what measures better → fix, test, benchmark,
PR, CI, merge, delete the branch. This is the record for 13–14 September 2026 (PRs #48–#52),
continuing `SESSION-16-LIVE-HARDENING.md`. It includes the correction to the benchmarks page
that the measurement forced.

## 1. Result

| board | before (#47) | after (#52) | field |
|---|---:|---:|---|
| WCXB dev, routed production path | 0.855 | **0.861** | rs-trafilatura 0.859 (author's own, tuned on this split), MinerU-HTML 0.827 |
| WCXB test (held out, no decisions) | 0.864 | **0.875** | rs-trafilatura reports 0.893 |
| Zyte article-extraction (181 pages) | 0.934 | **0.945** | rs-trafilatura 0.970, trafilatura 0.958, readability.js 0.947 — 10th of 35 |
| WCEB, production path (3,985 pages) | 0.852 | **0.856** | trafilatura 0.867, readability 0.855 — second |
| WCEB, comments kept (reference, not the API's output) | 0.876 | 0.874 | — |

WCXB by type, routed: article 0.944, documentation 0.929, service 0.842, forum 0.800,
collection 0.692, listing 0.706, product 0.636.

Every number for this engine is from the runners under `benchmark/` on one machine against
a local corpus clone; every other number is its authors' published figure.

## 2. The correction

The benchmarks page showed WCEB **0.871, first of seven**. That figure was the `main`
variant of the WCEB runner — landmark stripping and the boundary step — not the production
path the API returns. WCEB had last been run at PR #25; re-running it at #49 gave the
variant 0.876 and the production path 0.852.

The gap is one mechanism. Dragnet (1,379 pages) and cetd (700) count a page's comment
threads as content; the production path strips the comments under an article (#23), which
WCXB and Zyte reward. On Dragnet the production path scores 0.792 and the variant 0.849.
WCEB ran trafilatura with `include_comments=False`, so the production path is the honest
comparison. The page now ranks the production path (0.856, second) and draws the variant as
a dashed reference line with the reason. The same applies to the cetd board (0.897 ranked,
0.928 reference).

What would move it: returning comments as a labelled section rather than dropping them —
right for LLM consumers of a Hacker News or Slashdot page anyway. Not done this session.

## 3. What changed, in merge order

| PR | Fix | Found on | Effect |
|---|---|---|---|
| #48 | a 150+-word block whose six-word shingles are 70% present across *several* other blocks is the page restating itself, and is dropped | businessinsider.de (article twice: paragraphs, then one `articleBody` div), l-camera-forum (reply quoting the whole post), amazon.com (bullets repeated as a description) | Zyte 0.934 → 0.937; WCXB forum +0.002, product +0.001 |
| #49 | pre-HTML5 chrome names (`div#footer`, `div.nav`, `.main-menu`) are chrome; a rail never holds the `<h1>` or `itemprop=articleBody`; camelCase cookie dialogs are consent | jpost.com (0.00 on Zyte: story in `article-inner-content-breaking-news`, footer in `div.footer-wrap`), qburst.com (`cookieWrapper`) | Zyte → 0.942; WCXB service +0.004, listing +0.002, collection +0.002 |
| #50 | adaptive block cost ratio 0.70 → 0.60, re-swept on dev and test | everywomansmarathon.com, classcentral.com (a listicle beside a table kept only the table) | WCXB dev +0.0026, test +0.0032; Zyte −0.002; WCEB production ±0 |
| #51 | a river of kickers at its own heading level ends where the article resumes (prose, or two sentence-length paragraphs), 30-block cap | thesun.co.uk ("Most read" `h3` over `h3` kickers mid-article) | Zyte → 0.941 (the Sun 0.792 → 0.857), no other page moved |
| #52 | the declared article body (`itemprop=articleBody`, `entry-content`, `story-body`, …) is a structural scope after `<main>` and `<article>`; title and lead restored from outside it | smithsonianmag, nypost, hawaiinewsnow, ctvnews, cbsnews | Zyte → **0.945** (P 0.920 → 0.936); WCXB +0.0012; WCEB production 0.852 → 0.856 |

## 4. Rejected, with numbers

| experiment | result | why |
|---|---|---|
| restated-whole rule without the single-block cap | docs −0.023 (react.dev's revised code samples), service −0.097 (a second pricing table) | two blocks that nearly repeat each other are revisions, not restatements |
| rails exempted when they read as prose (≥40 words, <20% links) | article −0.050, −0.021; listing −0.079 | related-article teaser cards are prose too; the structural test (h1 / articleBody inside) does not leak |
| cost basis = all blocks before stripping | dev 0.8597, Zyte 0.931 | lower cost everywhere lets junk in |
| cost basis = the pre-scope list when a scope fired | +0.0004 WCXB, neutral on cetd | |
| trust the body element, skip the boundary step inside it | +0.0002 WCXB; cleaningservicesseattle −0.197 | share buttons and forms live inside body elements too |
| minimum run share inside a body of 50 / 60 / 70 % | +0.0000 / +0.0004 / +0.0000 | |
| river walk through same-level headings with no cap | listing −0.022, collection −0.008 | bbc.com/news under "Latest" and github.com/trending *are* the page |
| "two paragraphs ≥ 8 words" as the river's end, without link-share and punctuation tests | github's 1,073-word language menu and twelve-word headline paragraphs counted as sentences | |

## 5. The mechanism behind every remaining regression

Each loss this session — em360tech, cleverhiker, kierstenhickman, beardbrand, the Business
Insider briefing — has the same shape: a structural step (chrome, footer, body scope)
removes the short blocks around the content, the mean block length the adaptive cost is
calibrated against rises, and the boundary step then drops the content's own short lines
(checklist items, spec lines, a briefing's ten bullets). #50's re-sweep moved the constant;
it did not remove the coupling. Three basis variants and a minimum-share guard did not
either. This is the next thing to research properly — what boilernet, Web2Text and
DOM Distiller do with block length once a container is chosen — before another constant is
tried.

## 6. Live suite

`scratchpad/livesuite/run.py`: 23 live pages (BBC, Guardian, the Sun, simonwillison.net,
asahi.com, MDN, docs.python.org, Django docs, en/ar Wikipedia, Discourse meta, Hacker News,
a GitHub issue and repo, Allbirds, IKEA, Astro docs, the Rust book, a Substack,
wordpress.org/news, Stack Overflow, old.reddit, Amazon) through the production path, scored
by sentence recall and precision against Chromium's `innerText` of the page's main region,
diffed candidate against `main`. #52 moved no page. Two of the 23 do not resolve (old.reddit
redirects to a login wall; Stack Overflow blocks the headless oracle) and several baselines
are low for reasons worth their own look: a Substack post keeps 103 of 1,409 blocks,
wordpress.org/news 9 of 140, a GitHub issue 51 of 172 with precision 0.00 against the
oracle. Those are the next live cases.

## 7. Operational note

The 13th's WCEB runs stopped at 17:18 when the laptop entered low-power sleep on battery,
not because the engine hung; `pmset -g log` confirmed it and the runs were relaunched under
`caffeinate -i` the next morning. ROUGE-LSum over 3,985 pages × 2 variants takes about two
hours per run on this machine; the runner accepts `WCEB_VARIANTS=main,boundary` (a
scratchpad copy) to skip the four diagnostic columns.
