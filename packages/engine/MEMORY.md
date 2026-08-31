
### Reading order — two real bugs found by tests (2026-08-31)

- **Attempted:** XY-cut preferring a horizontal (row) cut before a vertical (column) cut,
  on the theory that a full-width header must emit before the columns below it.
  **Result:** wrong order on grid-aligned multi-column layouts — reads *across* the rows
  (`A1 B1 C1 A2 B2 C2`) instead of down the columns (`A1 A2 B1 B2 C1 C2`). The row gaps in a
  tidy grid qualify just as much as the column gutters do.
  **Instead:** measure the widest whitespace band on both axes and cut on whichever is
  **wider**. A real column gutter is wider than inter-paragraph leading; a section break
  under a spanning header is wider than any column gap (there usually isn't one, because
  the header bridges it).
  **Status:** fixed. `use_columns = bool(col_boundaries) and (not row_boundaries or col_gap > row_gap)`.

- **Attempted:** splitting at *every* qualifying gap on the chosen axis in one pass.
  **Result:** header-over-two-columns produced `HEADER L1 R1 L2 R2 FOOTER` instead of
  `HEADER L1 L2 R1 R2 FOOTER`. The row gaps *between the column rows* also qualified, so the
  columns were sliced into rows before the column structure was ever detected.
  **Instead:** cut at the widest band only (plus any within `_TIE_TOLERANCE = 0.95` of it),
  then recurse. The tie tolerance keeps uniformly-spaced single-column pages to one cut
  rather than recursing once per paragraph.
  **Status:** fixed. 21/21 reading-order tests pass.

**Lesson worth keeping:** both bugs produced *plausible-looking* output that a happy-path
test would have passed. The discriminating fixture is `test_naive_y_sort_would_have_failed`,
which asserts the naive algorithm gets it wrong — a test that guards the test. Keep writing
those for any ordering or ranking logic.

### libxml2 silently truncates deeply nested HTML (2026-08-31)

- **Attempted:** `lxml.html.document_fromstring(html)` with default parser.
  **Result:** documents nested deeper than **255 levels** parse to an empty document.
  `text_content()` returns `''`, **no exception, no warning**. Measured exactly: depth 250
  works, depth 255 and beyond returns nothing.
  **Why it matters:** utility-class CSS frameworks nest wrapper `<div>`s deeply. This would
  have silently dropped whole pages with no error anywhere in the pipeline — the worst
  possible failure mode for an extraction engine.
  **Instead:** `lxml.html.HTMLParser(huge_tree=True, recover=True)`. Verified working at
  depth 2000. **Must be `lxml.html.HTMLParser`, not `lxml.etree.HTMLParser`** — the latter
  returns plain `_Element` objects with no `.text_content()`, which fails confusingly.
  **Trade-off accepted:** `huge_tree` disables libxml2's resource guards, and crawler input
  is untrusted. Compensated with `MAX_DOCUMENT_BYTES = 32 MB` checked before parsing.
  **Status:** fixed and regression-tested at depths 300 and 800.

### D54 — The landing page scrolled sideways on a phone, and no screenshot showed it

Asserting `document.scrollWidth <= clientWidth` at 320, 390 and 768 pixels found a real
failure the desktop view could never show: the landing page rendered a **467-pixel document
inside a 390-pixel viewport**.

Cause, and it recurs: a grid or flex item defaults to `min-width: auto`, so it refuses to
shrink below its widest child. One `<pre>` of shell commands in a two-column section held the
whole page open. `min-w-0` on the grid children fixes it.

Now `make check-responsive` (`tools/check_responsive.py`), which names the offending elements
with their class lists and skips anything a clipping ancestor already contains -- a
decorative image scaled past its frame is not why a document scrolls.

Also fixed alongside: attrs' documentation puts the project name in every `<h1>`, so a whole
crawl arrived titled "attrs: Classes Without Boilerplate". A title shared by several pages
identifies none of them, and those rows now show their path as well.
