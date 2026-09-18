"""What a page carries that is not on it: content drawn in a canvas, and the addresses its
own scripts hold.

bhavyadhanwani.dev/projects is one `<canvas>` and seven words -- "Click on the Project for
Details" and a link home. Its three projects, each with a repository and a live address,
exist only as a data array in a script bundle that a WebGL scene draws and reveals on a
click. Nothing on the page names them; a reader without JavaScript and a mouse, a search
engine, or a crawl sees the seven words. That is a fact about the page worth stating
(`canvas_verdict`), and the addresses are worth listing (`script_links`) -- *as found in
script*, never queued and never counted as content, because a URL in a bundle is a claim
the code makes, not a link the page offers.

The script read is bounded and same-origin, the same read the stack detector makes once
for the root, and it is made only for a page the verdict names: a page that carries its
content in markup has no such hidden data to look for, and reading every page's bundles
would cost a crawl a download per page for nothing.

Only URLs a script stores as a *named value* -- `github: "https://…"`, `live: "…"`,
`url: "…"` -- are taken. That is the shape of an author's data. A bare URL in a bundle is,
nearly always, a library's licence, docs or homepage, and listing those would attribute
core-js's provenance to the site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from webgraph.types import Document

__all__ = ["CanvasVerdict", "ScriptLink", "canvas_verdict", "script_links"]

CANVAS_MAX_WORDS: Final[int] = 40
"""A page with a canvas and fewer readable words than this is drawing its content, not
writing it. Forty covers a caption, a heading and a link home; an article with an embedded
chart has hundreds."""

MAX_SCRIPT_LINKS: Final[int] = 60

_PROVENANCE_KEYS: Final[frozenset[str]] = frozenset(
    {"license", "licence", "homepage", "bugs", "funding"}
)
"""Named values a library's banner stores about *itself* -- core-js ships
`{license: "https://github.com/zloirock/core-js/blob/…/LICENSE", source: …}` in every bundle
that includes it. A licence is never the site's own address."""

_LICENSE_PATH: Final[re.Pattern[str]] = re.compile(r"/LICEN[CS]E(\.\w+)?$", re.IGNORECASE)

_CANVAS: Final[re.Pattern[str]] = re.compile(r"<canvas\b", re.IGNORECASE)

# `key: "https://…"` or `"key": '…'` -- an identifier or quoted identifier, a colon, a quoted
# absolute URL. Minified code keeps this shape; what it drops is whitespace, which is optional
# here. `\3` closes with the quote that opened the value.
_KEYED_URL: Final[re.Pattern[str]] = re.compile(
    r"""(["']?)([A-Za-z_$][\w$]{0,40})\1\s*:\s*(["'])(https?://[^"'\s<>\\]{6,500})\3"""
)


@dataclass(frozen=True, slots=True)
class CanvasVerdict:
    """A page that draws its content."""

    canvases: int
    words: int
    script_bytes: int = 0
    """How much same-origin script was read looking for what the canvas shows; zero when
    none was read."""

    def as_dict(self) -> dict[str, Any]:
        return {"canvases": self.canvases, "words": self.words, "script_bytes": self.script_bytes}


@dataclass(frozen=True, slots=True)
class ScriptLink:
    """An address a script stores as a named value."""

    url: str
    key: str
    """The name the code gave it -- `github`, `live`, `href` -- which is often the only
    human-readable statement of what the address is."""

    def as_dict(self) -> dict[str, str]:
        return {"url": self.url, "key": self.key}


def canvas_verdict(document: Document) -> CanvasVerdict | None:
    """Whether this page's content is drawn rather than written: a `<canvas>` in the markup
    and fewer than `CANVAS_MAX_WORDS` readable words. None for every other page."""
    if not document.html:
        return None
    canvases = len(_CANVAS.findall(document.html))
    if canvases == 0:
        return None
    words = len(document.text.split())
    if words >= CANVAS_MAX_WORDS:
        return None
    return CanvasVerdict(canvases=canvases, words=words)


def script_links(source: str, *, page_url: str | None = None) -> tuple[ScriptLink, ...]:
    """The addresses `source` stores as named values, in order of first appearance,
    deduplicated by URL, capped. The page's own address is left out."""
    if not source:
        return ()
    own = _key_of(page_url) if page_url else None
    seen: dict[str, ScriptLink] = {}
    for match in _KEYED_URL.finditer(source):
        key, url = match.group(2), match.group(4)
        host = urlsplit(url).hostname or ""
        # A real host has a dot; `https://a` is a regular expression's test string.
        if "." not in host or len(host) < 4:
            continue
        if key.lower() in _PROVENANCE_KEYS or _LICENSE_PATH.search(urlsplit(url).path):
            continue
        if url in seen or _key_of(url) == own:
            continue
        seen[url] = ScriptLink(url=url, key=key)
        if len(seen) >= MAX_SCRIPT_LINKS:
            break
    return tuple(seen.values())


def _key_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{(parts.hostname or '').removeprefix('www.')}{parts.path.rstrip('/')}"
