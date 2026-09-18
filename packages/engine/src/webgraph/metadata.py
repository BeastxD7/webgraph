"""What a page declares about itself in its `<head>`: the metadata a crawler, a search
engine or a share card reads before any of the page's own text.

Read once, at Stage 0, from the root page the site served -- and once per single-page run
-- and reported beside the technology profile: it is the same kind of fact, what the site
*says* rather than what it is. The declarations are also where a site quietly contradicts
itself. bhavyadhanwani.dev declares its previous host as the canonical of every page and
lists that host in its sitemap; nothing on the page shows it, and a crawl that trusted it
finished after one page. So the declared addresses are compared with the address the page
was actually served at, and any that name another site are listed in `declared_elsewhere`
-- `www.` and the bare domain count as one site, as they do everywhere in the crawl.

Under the `union` strategy the head read is the rendered page's: the plain fetch's head is
not kept once the two are merged, and a framework may add tags on the client. Under
`static-only` it is the served head as is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urljoin

from lxml import etree
from lxml import html as lxml_html

from webgraph.crawl.frontier import same_site
from webgraph.types import PayloadSource, StructuredPayload

__all__ = ["PageMetadata", "read_metadata"]

MAX_VALUE_CHARS: Final[int] = 300
"""A declared value is a line, not a document: a description or an `og:description` past
this is cut, so one page cannot make the analysis event the size of its own body."""

MAX_ALTERNATES: Final[int] = 24
"""Language alternates run to fifty on a large site; the count is kept whole, the list is
capped."""

_ICON_RELS: Final[frozenset[str]] = frozenset({"icon", "shortcut icon", "apple-touch-icon"})
_ADDRESS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "og:url",
        "og:image",
        "og:image:url",
        "og:image:secure_url",
        "og:audio",
        "og:video",
        "twitter:image",
        "twitter:image:src",
        "twitter:url",
    }
)
"""Share-card properties whose value is an address. A relative `og:image` is legal and
common (`/og.png`), and a card renderer resolves it against the page; so does this."""
_FEED_TYPES: Final[frozenset[str]] = frozenset({"application/rss+xml", "application/atom+xml"})


@dataclass(frozen=True, slots=True)
class PageMetadata:
    """The `<head>` of one page, as declared. Every address is absolute against the address
    the page was served at; every text value is whitespace-folded and capped."""

    url: str
    """Where the page was served -- what the declarations are measured against."""

    title: str | None = None
    description: str | None = None
    canonical: str | None = None
    language: str | None = None
    """`<html lang>`."""
    charset: str | None = None
    robots: str | None = None
    """`<meta name="robots">`, verbatim: `noindex`, `nofollow`, `max-snippet:-1`..."""
    generator: str | None = None
    """`<meta name="generator">`: the CMS or site builder that wrote the page, by its own
    account -- WordPress, Hugo, Framer -- which is evidence the fingerprinter also reads."""
    author: str | None = None
    keywords: str | None = None
    theme_color: str | None = None
    viewport: str | None = None
    icons: tuple[str, ...] = ()
    """`<link rel="icon">`, `shortcut icon`, `apple-touch-icon`, in document order."""
    manifest: str | None = None
    open_graph: dict[str, str] = field(default_factory=dict)
    """Every `og:*` and `article:*` property. Multi-valued properties keep their first."""
    twitter: dict[str, str] = field(default_factory=dict)
    """Every `twitter:*` name or property."""
    alternates: tuple[dict[str, str], ...] = ()
    """`<link rel="alternate" hreflang>`: `{"hreflang": ..., "href": ...}`, capped."""
    alternate_count: int = 0
    feeds: tuple[str, ...] = ()
    """RSS and Atom feeds the page advertises."""
    schema_types: tuple[str, ...] = ()
    """The `@type`s of the page's JSON-LD and microdata, in order of first appearance --
    what the page claims to be about, in schema.org's terms."""
    declared_elsewhere: tuple[str, ...] = ()
    """Declarations that name a different site from the one that served the page, as
    `"canonical -> https://old-host.example"`. Empty is the normal case. Non-empty is the
    kind of misconfiguration nothing on the page shows and every crawler trips over."""

    def as_dict(self) -> dict[str, Any]:
        """Shape the streaming API and the trace both carry."""
        return {
            "url": self.url,
            "title": self.title,
            "description": self.description,
            "canonical": self.canonical,
            "language": self.language,
            "charset": self.charset,
            "robots": self.robots,
            "generator": self.generator,
            "author": self.author,
            "keywords": self.keywords,
            "theme_color": self.theme_color,
            "viewport": self.viewport,
            "icons": list(self.icons),
            "manifest": self.manifest,
            "open_graph": dict(self.open_graph),
            "twitter": dict(self.twitter),
            "alternates": [dict(a) for a in self.alternates],
            "alternate_count": self.alternate_count,
            "feeds": list(self.feeds),
            "schema_types": list(self.schema_types),
            "declared_elsewhere": list(self.declared_elsewhere),
        }


def _fold(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text[:MAX_VALUE_CHARS]


def _first(root: Any, xpath: str) -> str | None:
    found = root.xpath(xpath)
    if not isinstance(found, list):
        return None
    for value in found:
        text = _fold(value)
        if text:
            return text
    return None


def _elements(root: Any, xpath: str) -> list[Any]:
    """The elements an xpath selects -- lxml types the result as a union, and only the
    element list is wanted here."""
    found = root.xpath(xpath)
    return [e for e in found if hasattr(e, "get")] if isinstance(found, list) else []


def _absolute(href: str | None, base: str) -> str | None:
    if not href:
        return None
    try:
        return urljoin(base, href)
    except ValueError:
        return None


def _schema_types(
    payloads: tuple[StructuredPayload, ...] | list[StructuredPayload],
) -> tuple[str, ...]:
    """`@type` of every JSON-LD and microdata payload, walking `@graph` and nested nodes
    one level down, deduplicated in order of first appearance."""
    seen: dict[str, None] = {}

    def take(node: object) -> None:
        if not isinstance(node, dict):
            return
        kind = node.get("@type")
        for name in kind if isinstance(kind, list) else [kind]:
            if isinstance(name, str) and name.strip():
                seen.setdefault(name.strip(), None)
        graph = node.get("@graph")
        if isinstance(graph, list):
            for child in graph:
                take(child)

    for payload in payloads:
        if payload.source not in (PayloadSource.JSON_LD, PayloadSource.MICRODATA):
            continue
        data = payload.data
        for node in data if isinstance(data, list) else [data]:
            take(node)
    return tuple(seen)


def read_metadata(
    html: str,
    url: str,
    *,
    structured_data: tuple[StructuredPayload, ...] | list[StructuredPayload] = (),
) -> PageMetadata:
    """Read a page's `<head>` declarations. Never raises: unparseable markup gives a
    `PageMetadata` with only `url` set, the same as an empty head."""
    try:
        root = lxml_html.fromstring(html)
    except (ValueError, TypeError, etree.ParserError):
        # `ParserError` is what an empty or whitespace-only body raises: "Document is empty".
        return PageMetadata(url=url)

    canonical = _absolute(_first(root, "//link[@rel='canonical']/@href"), url)

    open_graph: dict[str, str] = {}
    twitter: dict[str, str] = {}
    for meta in _elements(root, "//meta[@property or @name]"):
        key = (meta.get("property") or meta.get("name") or "").strip().lower()
        value = _fold(meta.get("content"))
        if not key or value is None:
            continue
        if key in _ADDRESS_KEYS:
            # An address like any other in the head: absolute against the page's URL.
            value = _absolute(value, url) or value
        if key.startswith(("og:", "article:", "product:", "profile:")):
            open_graph.setdefault(key, value)
        elif key.startswith("twitter:"):
            twitter.setdefault(key, value)

    icons: list[str] = []
    feeds: list[str] = []
    alternates: list[dict[str, str]] = []
    alternate_count = 0
    manifest: str | None = None
    for link in _elements(root, "//link[@rel][@href]"):
        rels = {r.strip().lower() for r in (link.get("rel") or "").split(",")}
        rel_words = " ".join(sorted(rels)).strip()
        href = _absolute(link.get("href"), url)
        if href is None:
            continue
        kind = (link.get("type") or "").strip().lower()
        if rel_words in _ICON_RELS or "icon" in rels or "apple-touch-icon" in rels:
            if href not in icons:
                icons.append(href)
        elif "manifest" in rels:
            manifest = manifest or href
        elif "alternate" in rels:
            hreflang = (link.get("hreflang") or "").strip()
            if kind in _FEED_TYPES:
                if href not in feeds:
                    feeds.append(href)
            elif hreflang:
                alternate_count += 1
                if len(alternates) < MAX_ALTERNATES:
                    alternates.append({"hreflang": hreflang, "href": href})

    declared_elsewhere: list[str] = []
    for label, address in (("canonical", canonical), ("og:url", open_graph.get("og:url"))):
        if address and not same_site(address, url):
            declared_elsewhere.append(f"{label} -> {address}")

    return PageMetadata(
        url=url,
        title=_first(root, "//title/text()"),
        description=_first(root, "//meta[@name='description']/@content"),
        canonical=canonical,
        language=_first(root, "/html/@lang") or _first(root, "//html/@lang"),
        charset=_first(root, "//meta[@charset]/@charset")
        or _first(root, "//meta[translate(@http-equiv,'CT','ct')='content-type']/@content"),
        robots=_first(root, "//meta[@name='robots']/@content"),
        generator=_first(root, "//meta[@name='generator']/@content"),
        author=_first(root, "//meta[@name='author']/@content"),
        keywords=_first(root, "//meta[@name='keywords']/@content"),
        theme_color=_first(root, "//meta[@name='theme-color']/@content"),
        viewport=_first(root, "//meta[@name='viewport']/@content"),
        icons=tuple(icons),
        manifest=manifest,
        open_graph=open_graph,
        twitter=twitter,
        alternates=tuple(alternates),
        alternate_count=alternate_count,
        feeds=tuple(feeds),
        schema_types=_schema_types(structured_data),
        declared_elsewhere=tuple(declared_elsewhere),
    )
