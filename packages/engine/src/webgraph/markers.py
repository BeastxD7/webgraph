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
    "GATE_ATTRIBUTE",
    "HIDDEN_ATTRIBUTE",
    "MARKER_ATTRIBUTE",
    "marker_arguments",
]

MARKER_ATTRIBUTE: Final[str] = "data-wg-id"
"""Geometry key. The browser stamps every element with a fresh id before serialising the DOM,
so each element can be found again after parsing and rekeyed by whatever XPath lxml itself
produces (`fetch.render.geometry_by_xpath`). Recomputing an XPath in JavaScript to match
lxml's `getpath()` output would be fragile -- the formats differ over when an index is
emitted -- and a mismatch yields no geometry at all. Stamped by `fetch/js/collect.js`."""

BREAK_ATTRIBUTE: Final[str] = "data-wg-brk"
"""Stamped on elements the browser lays out as their own box, so the parser can tell a line
boundary from inline flow (`dom.rich.flowed_text`). Decided by the computed `display`, which
is the rule `innerText` follows -- a measurement of this page rather than an assumption about
markup. Absent on a static fetch, where `flowed_text` then behaves exactly as `text_content()`
did: a page nobody rendered gets no layout claims. Stamped by `fetch/js/collect.js`."""

GATE_ATTRIBUTE: Final[str] = "data-wg-gate"

HIDDEN_ATTRIBUTE: Final[str] = "data-wg-hidden"
"""Stamped by the renderer on elements with `display: none` or `visibility: hidden`.

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
    }
