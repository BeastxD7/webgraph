# Session 18: the whole page

The owner's brief, restated on 14 September: the product is the full-page `markdown` /
`text`. Nothing a reader sees may be lost — "not even a single character" — nothing the
browser hides may be added, the order is the page's, the structure stays, and the engine
must never present a false output: a page it cannot read is a refusal, not a guess. The
filtered `content_markdown` is secondary and must not regress. This is the record of the
evening of 14 September (PRs #63–#70 and the ones that followed), continuing
`SESSION-17-RESEARCH-LOOP.md`.

## 1. How the losses were found

None of the public boards measure the whole page. Two instruments did:

- **A census of old, plain and ugly pages** (25 sites, an agent run against Chromium's
  `innerText`: framesets, `<font>` pages, `<br><br>` paragraphs, DocBook manuals, RFCs,
  spacejam.com/1996): word recall 0.99–1.00 on 20 of 21 fetched, with the remaining
  losses ranked by the markup construct that caused them.
- **`benchmark/fidelity/run.py`** (this session): the same measure as a repo runner with a
  fixed set of 36 sites, cached oracle, and a `--compare` — word recall, extra share, order
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

## 5. Where it stands

Filtered content: WCXB dev 0.863 (first), WCXB test 0.875, Zyte 0.945 (10th of 35),
WCEB content+comments 0.883 (first), WebMainBench 0.732. Whole page: the numbers above.
Open: the structure losses (`<hr>`, `<dl>`, colspan tables, `<svg>`), login walls named
as such, editor widgets and closed `<details>` on dynamic pages — in flight as separate
PRs — and the fetch layer for sites that wall every headless fetch, which is an
infrastructure decision, not an extraction fix.
