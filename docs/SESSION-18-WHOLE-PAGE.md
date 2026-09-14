# Session 18: the whole page

The owner's brief, restated on 14 September: the product is the full-page `markdown` /
`text`. Nothing a reader sees may be lost — "not even a single character" — nothing the
browser hides may be added, the order is the page's, the structure stays, and the engine
must never present a false output: a page it cannot read is a refusal, not a guess. The
filtered `content_markdown` is secondary and must not regress. This is the record of the
evening of 14 September (PRs #63–#79), continuing
`SESSION-17-RESEARCH-LOOP.md`.

## 1. How the losses were found

None of the public boards measure the whole page. Two instruments did:

- **A census of old, plain and ugly pages** (25 sites, an agent run against Chromium's
  `innerText`: framesets, `<font>` pages, `<br><br>` paragraphs, DocBook manuals, RFCs,
  spacejam.com/1996): word recall 0.99–1.00 on 20 of 21 fetched, with the remaining
  losses ranked by the markup construct that caused them.
- **`benchmark/fidelity/run.py`** (this session): the same measure as a repo runner with a
  fixed set of 31 sites, cached oracle, and a `--compare` — word recall, extra share, order
  inversions, structure counts. It refuses to score a walled oracle and reads a
  frameset's frames.

## 2. What changed, in merge order

| PR | Fix | Found on | Measured |
|---|---|---|---|
| #63 | framesets composed; bare text under `body`/`center`/`font`; `<br>` a line break and `<br><br>` a paragraph; structural blockquotes walked into (`Block.quoted`); orphan runs walk through inline wrappers; data-table cells keep words apart | cs.cmu.edu (0 → 307 words), textfiles.com (recall 0.787 → 1.0), columbia.edu, AppleInsider (found by measuring: paragraphs reversed) | WCXB +0.0001, Zyte =, WCEB = (cleaneval +0.005), WebMainBench +0.002 |
| #64 | a wall served to one fetch is left out and named, not merged | columbia.edu: Cloudflare's "Performing security verification … Ray ID" presented as content | static corpora n/a; live suite = |
| #65 | what the browser hid stays hidden through the union (`hidden_matter`); glyph-only fragment anchors are permalinks; runs dashboard | php.net (330 → 233 blocks), cppreference (254 → 135), nasa.gov (299 → 153); allbirds live precision 0.11 → 0.75 | WCXB =, Zyte = |
| #66 | `<li><p>` lists are lists | catb.org, tldp.org, awk, postgres docs | WCXB +0.0001 |
| #67 | beside a wall, the other fetch must have 20 words | old.reddit login redirect (found by the live suite) | n/a |
| #68 | links inside table cells (`rich_rows`) and around images (`link`) | craigslist "best of", spacejam.com planets | WCXB =, Zyte = |
| #69 | a table or code block a page repeats stays, on an unmeasured page | columbia.edu (four demo tables → four; recall 0.979 → 0.995) | WCXB +0.0001, Zyte = |
| #70 | the runs dashboard pushes every second and lists the machine's engine processes | the owner: "it's junk and static" | tooling |
| #71 | MediaWiki `editsection` strips are heading controls; `<noframes>` only when no frame was fetched | cppreference (`[edit]` ×56, tables twice), cs.cmu.edu (title frame repeated) | fidelity cppref extra 0.257 → 0.034 |
| #72 | `benchmark/fidelity/run.py`, `make bench-fidelity`, this document | — | tooling |
| #73 | a login redirect is a wall, named (`login_redirect`); a code editor (CodeMirror/Monaco/Ace) is one code block, its windows completed from the hidden source | twitter/x.com, reddit, MDN interactive example (token-per-paragraph) | WCXB =, Zyte = |
| #74 | a skip link to `<main>` opens nothing inside it | MDN (every hidden tray became "openable") | WCXB = |
| #75 | `<hr>` a rule, `<dl>` a definition list, merged-cell tables keep `<br>`/`<p>` apart, inline `<svg><text>` diagrams read | census: 6 sites lost rules, 3 flattened `<dl>`, sqlite.org railroad labels (recall 0.749) | WCXB −0.00004, Zyte =, WMB table = (pipes variant rejected) |
| #76 | the fidelity oracle reads open shadow roots; a full DOM walk was rejected | arngren 0.99 → 0.877 under the walker, back with the hybrid | tooling |
| #77 | a page of rules and nothing else selects nothing | follow-up to #75 | n/a |
| #78 | table cells carry links only when the caller wants links | **a regression from #68 that no filtered board caught for six PRs**: WebMainBench table_edit 0.390 → 0.338 | WMB 0.7284 → 0.7331, table 0.395 |
| #79 | benchmarks page at `main@19f601f` | — | docs |

## 3. Rejected, with numbers

| experiment | result | why |
|---|---|---|
| keep every unmeasured repeat by the neighbour rule (text and headings too) | WCXB −0.0017, Zyte −0.003; businessinsider 0.998 → 0.471, ghostwares 1.000 → 0.720 | on a page nobody measured, repeated prose is a hidden copy far more often than a deliberate repeat |
| match only whole hidden elements in the union | php.net 103 → 38 static-only blocks (menu items are short) | hidden lines are matched exactly, wholes as substrings past 12 chars |
| hidden-matter substring match with no length guard | "Home", "Types" dropped wherever they appear | |
| `pyccwebgraph` (PyPI) as a source of anything | a py4j shim over Common Crawl's Java hyperlink graph; domain neighbours only, needs Java + 20 GB | name collision; for a random-tail test set use the CC host-ranks TSV + `cdx_toolkit` |

## 4. What the fidelity suite says on `main` after #70

Recall 1.000 on 24 of 34 scored sites; below 0.99 only sqlite.org (0.749, inline
`<svg><text>` diagram labels) and cameronsworld (0.992, a JS-shuffled marquee). Extra
share above 0.05: cppreference 0.257 (`editsection [edit]` ×56 and the table emitted
twice), mdn 0.490 (the interactive example's editor DOM and per-tab copies), arxiv 0.294,
berkshire 0.064, drudge 0.061. Order inversions: unicode-faq 6/745 (`<pre>` inside `<li>`
hoisted), mdn 7/187, columbia 3/192 (repeated list-item text). gnu.org times out from
this network; w3.org walls the oracle's Chromium (the engine gets the page through the
other fetch).

## 5. Where it stands (main@f0b0ac4, end of 14 September)

Filtered content: WCXB dev routed 0.862 (first; the official runner needs
`WCXB_ROUTER_OOF=benchmark/train/artifacts/router_oof.json` or its routed column
silently equals `content`, 0.838), WCXB test 0.875, Zyte 0.945 (10th of 35), WCEB
content+comments 0.883 (first), WebMainBench 0.7331 (table 0.395). WCXB was measured at
the #74 merge, WebMainBench at the #78 candidate; #75/#77 moved WCXB by −0.00004.

Whole page, the fidelity suite on this commit: recall 1.000 on 22 of 29 scored sites,
nothing below 0.945; sqlite.org 0.749 → 1.000 (#75), cppreference extra 0.257 → 0.034
(#71), MDN extra 0.490 → 0.142 (#73/#74). Still open, each with its site: arxiv extra 0.294 (the abstract
page's hidden bibliographic tooling), MDN recall 0.945 / extra 0.228 (Copy/Play labels,
compatibility-table icon labels, per-tab code copies), berkshire extra 0.064,
craigslist-best 0.040, unicode-faq's `<pre>` inside `<li>` hoisted (6 inversions),
cameronsworld's JS marquee, cppreference's C++ version-tab words (8 missing). Repeated
*prose* on an unmeasured page is still deduplicated — the measured trade-off in §3 — and
the fetch layer for sites that wall every headless fetch (Stack Overflow, sec.gov,
nyc.gov) is an infrastructure decision the owner has not yet taken, not an extraction fix.

Lesson of the night, now a rule in CONTRIBUTING: anything that touches table, code or
Markdown rendering re-runs WebMainBench before merge. Five PRs of "WCXB =, Zyte ="
said nothing about a link rendered into cells the corpus scores with links off.
