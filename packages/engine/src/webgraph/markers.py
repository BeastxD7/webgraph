"""The marker-attribute contract between the browser-side scripts and the lxml-side parser.

Rendering happens in two runtimes that never share memory. The browser (`fetch/js/*.js`,
evaluated by `fetch/render.py`) stamps attributes onto the live DOM *before* serialising it;
lxml (`fetch/render.py`, `dom/rich.py`) reads those attributes back off the parsed HTML.
The attribute names are the only thing the two halves agree on, and a mismatch fails
silently -- no geometry, no line breaks, no gate candidates -- rather than loudly.

So the names live here, once. The browser programs receive them as their single argument
(see `marker_arguments`) and never spell them out; the Python side imports them from this
module and never spells them out either. Nothing else may define these strings.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "BREAK_ATTRIBUTE",
    "FLOAT_ATTRIBUTE",
    "GATE_ATTRIBUTE",
    "HIDDEN_ATTRIBUTE",
    "MARKER_ATTRIBUTE",
    "PATH_ATTRIBUTE",
    "REVEALED_ATTRIBUTE",
    "marker_arguments",
]

MARKER_ATTRIBUTE: Final[str] = "data-wg-id"
"""Geometry key. The browser stamps every element with a fresh id before serialising the DOM,
so each element can be found again after parsing and rekeyed by whatever XPath lxml itself
produces (`fetch.render.geometry_by_xpath`). Recomputing an XPath in JavaScript to match
lxml's `getpath()` output would be fragile -- the formats differ over when an index is
emitted -- and a mismatch yields no geometry at all. Stamped by `fetch/js/collect.js`."""

PATH_ATTRIBUTE: Final[str] = "data-wg-path"
"""Each element's XPath in the tree *as parsed*, stamped by `dom.rich.extract_rich_blocks`
before anything is removed from that tree. The geometry map (`fetch.render.geometry_by_xpath`)
is keyed by the XPath of a fresh parse; the block walk removes hidden twins, clipped labels,
permalinks and unreachable trays before it computes a block's XPath -- and lxml's `getpath`
writes `div[2]` when there are sibling divs and plain `div` when the removal left one, so
every block below a removed sibling got a path the geometry map did not hold. On
allbirds.com/collections/mens, 641 `display: none` elements came out first and 161 of 217
blocks -- every product card -- had no rectangle; the page fell back to source order and
its repeated card titles were deduplicated as unmeasured text. Set by the Python side, not
the browser; never serialised into output (preserved tables whitelist their attributes)."""

BREAK_ATTRIBUTE: Final[str] = "data-wg-brk"
"""Stamped on elements the browser lays out as their own box, so the parser can tell a line
boundary from inline flow (`dom.rich.flowed_text`). Decided by the computed `display`, which
is the rule `innerText` follows -- a measurement of this page rather than an assumption about
markup. Absent on a static fetch, where `flowed_text` then behaves exactly as `text_content()`
did: a page nobody rendered gets no layout claims. Stamped by `fetch/js/collect.js`."""

GATE_ATTRIBUTE: Final[str] = "data-wg-gate"

REVEALED_ATTRIBUTE: Final[str] = "data-wg-revealed"
"""Stamped by `fetch/js/reveal.js` on a panel it opened -- a collapsed `<details>`, a
disclosure, a tab panel, a panel a control names -- so the page's own record says which
content was hidden until someone would have interacted. Read back by nothing yet; kept in
the serialised DOM so a trace can show what the reveal step did."""

FLOAT_ATTRIBUTE: Final[str] = "data-wg-float"
"""Stamped by the renderer on elements the browser floats, with the value `left` or `right`.

A float is taken out of the flow and text wraps around it, so the blocks inside one -- an
image and its caption, an infobox and its rows -- sit *beside* the paragraphs rather than
between them. Geometry alone then zips them with the paragraphs. The mark says which
blocks belong to a float, so they can be read as one thing."""

HIDDEN_ATTRIBUTE: Final[str] = "data-wg-hidden"
"""Stamped by the renderer on elements the browser is not showing.

The value names the mechanism -- `display`, `visibility` or `opacity` -- so a consumer can
treat `opacity: 0` (often a scroll-reveal animation's starting state, i.e. real content)
differently from the other two.

Not every hidden element is dropped -- a collapsed disclosure's body is hidden and is
content. What the mark enables is telling a hidden *twin* from the rest: two siblings with
the same text where one is hidden is one thing rendered twice for two screen widths."""
"""Interstitial dismissal candidates. `fetch/js/gate_probe.js` marks the controls most likely
to open a first-run gate, numbered in the order they should be tried, and
`fetch.render._open_gate` clicks them by this attribute."""


def marker_arguments() -> dict[str, str]:
    """The single argument every browser-side program receives.

    Each `fetch/js/*.js` file is an arrow function `(markers) => { ... }` and reads
    `markers.marker`, `markers.brk` and `markers.gate` instead of hard-coding the names.
    """
    return {
        "marker": MARKER_ATTRIBUTE,
        "brk": BREAK_ATTRIBUTE,
        "gate": GATE_ATTRIBUTE,
        "hidden": HIDDEN_ATTRIBUTE,
        "float": FLOAT_ATTRIBUTE,
        "revealed": REVEALED_ATTRIBUTE,
    }
