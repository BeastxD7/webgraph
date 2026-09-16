"""One sampled page of a site report: what the engine measured on it, read back out.

Nothing here fetches a page or renders one. A `ResolvedPage` arrives from `resolve_page`
carrying both fetches' character and word counts, the side that was walled, and the
document whose markup the renderer stamped (`data-wg-hidden`, see `markers.py`); this
module counts what those marks say -- words hidden by `display: none`, `visibility:
hidden` and a box parked off the page, links inside such elements grouped by host -- and
reads the page's own declarations: title, description, canonical, `lang`, JSON-LD and
microdata. On a page the renderer never measured (a plain fetch only) the one hiding
technique the markup itself gives away, an inline style at -999px or beyond, is read with
`dom.rich.styled_off_the_page`, the same rule the extraction applies.

The one thing that does fetch is `LinkChecker`: a HEAD (a GET when HEAD is refused) of the
page's internal links, paced, each address once per report.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urljoin, urlsplit

import httpx

from webgraph import config
from webgraph.crawl.discovery import RobotsPolicy, extract_links
from webgraph.dom.blocks import parse_html
from webgraph.dom.rich import styled_off_the_page
from webgraph.fetch import guard
from webgraph.fetch.static import FetchConfig
from webgraph.markers import HIDDEN_ATTRIBUTE
from webgraph.resolve import ResolvedPage
from webgraph.types import PayloadSource

__all__ = [
    "HIDDEN_KINDS",
    "HiddenHost",
    "LinkChecker",
    "Pacer",
    "PageReport",
    "internal_links",
    "measure_page",
    "registrable",
    "site_host",
]

HIDDEN_KINDS: Final[tuple[str, ...]] = ("display", "visibility", "offscreen")
"""The renderer's marks that mean a reader cannot see the element. `opacity`, `clipped`
and `overflow` are left out: an entrance animation starts at opacity 0, a screen-reader
label is meant to be unseen, and a collapsed tray opens."""

_SKIP_SCHEMES: Final[tuple[str, ...]] = ("mailto:", "tel:", "javascript:", "data:", "#")
_NOT_PAGES: Final[tuple[str, ...]] = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".mp4", ".mp3", ".css", ".js", ".xml", ".ico",
)


def site_host(url: str) -> str:
    """`www.example.com` and `example.com` are one site."""
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


_SECOND_LEVEL: Final[frozenset[str]] = frozenset({
    "ac", "co", "com", "edu", "gov", "net", "org", "nic", "res", "or", "ne", "gob", "mil", "ltd", "plc", "sch",
})


def registrable(host: str) -> str:
    """The domain a host was registered under: `vtu.ac.in` for `report.vtu.ac.in`,
    `python.org` for `peps.python.org`. Without a public-suffix list, the rule is the last
    two labels, or three when the second-last is a conventional second level (`ac`, `co`,
    `gov`, ...) under a two-letter country code. A subdomain of the site is the site's own,
    not a foreign host: vtu.ac.in's menus link to a dozen of its own services."""
    labels = host.lower().removeprefix("www.").split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


@dataclass(frozen=True, slots=True)
class HiddenHost:
    host: str
    links: int
    """Links to this host from any hidden element."""
    offscreen: int
    """Of those, links from an element parked off the page (`offscreen`), the kind an
    injection uses; a `display: none` dropdown is the other kind."""
    external: bool
    """Registered under another domain than the site (`registrable`)."""

    def as_dict(self) -> dict[str, Any]:
        return {"host": self.host, "links": self.links, "offscreen": self.offscreen, "external": self.external}


@dataclass(frozen=True, slots=True)
class DeadLink:
    url: str
    status: int

    def as_dict(self) -> dict[str, Any]:
        return {"url": self.url, "status": self.status}


@dataclass(frozen=True, slots=True)
class PageReport:
    """Everything the report says about one page. `error` set means the page could not be
    read at all and every number is zero; the message is the engine's own refusal."""

    requested_url: str
    url: str
    section: str
    """The first path segment (`/admissions/...` -> `admissions`), `/` for the root."""
    title: str = ""
    description: str = ""
    strategy: str = ""
    static_chars: int = 0
    rendered_chars: int = 0
    union_chars: int = 0
    static_words: int = 0
    rendered_words: int = 0
    union_words: int = 0
    static_coverage: float = 0.0
    render_error: str | None = None
    static_error: str | None = None
    wall: str | None = None
    """Which side was served a wall instead of the page: `browser`, `plain fetch`, or
    `both` (the page could not be read at all)."""
    hidden_words: dict[str, int] = field(default_factory=dict)
    """Words inside elements the reader cannot see, by how they are hidden (`HIDDEN_KINDS`);
    an element inside another hidden element is counted once, under the outer one."""
    hidden_links: int = 0
    """Links inside hidden elements of any kind."""
    hidden_hosts: tuple[HiddenHost, ...] = ()
    hidden_external_hosts: int = 0
    """Distinct foreign hosts linked from hidden elements of any kind -- a dropdown menu
    of partner sites is here, and is not a verdict."""
    offscreen_links: int = 0
    """Links inside elements parked off the page, the shape of an injection."""
    offscreen_external_hosts: int = 0
    """Distinct foreign hosts linked from off-screen elements. The spam verdict
    (`REPORT_SPAM_MIN_HOSTS`) reads this number and no other."""
    consent_words: int = 0
    total_words: int = 0
    canonical: str | None = None
    lang: str | None = None
    structured_data: tuple[str, ...] = ()
    """Sources of the machine-readable payloads the page carries, `json-ld` and
    `microdata` among them (`PayloadSource`)."""
    internal_links: int = 0
    links_checked: int = 0
    dead_links: tuple[DeadLink, ...] = ()
    links_unreachable: int = 0
    """Links whose check produced no HTTP answer at all: a timeout or a refused connection.
    Not counted as dead -- the fault may be on this side."""
    in_sitemap: bool | None = None
    error: str | None = None

    @property
    def consent_share(self) -> float:
        return self.consent_words / self.total_words if self.total_words else 0.0

    @property
    def dead_count(self) -> int:
        return len(self.dead_links)

    @property
    def has_schema(self) -> bool:
        return any(s in (PayloadSource.JSON_LD.value, PayloadSource.MICRODATA.value) for s in self.structured_data)

    @property
    def has_open_graph(self) -> bool:
        """`og:*` / `twitter:*` meta tags on the page (`PayloadSource.OPEN_GRAPH`)."""
        return PayloadSource.OPEN_GRAPH.value in self.structured_data

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_url": self.requested_url,
            "url": self.url,
            "section": self.section,
            "title": self.title,
            "description": self.description,
            "strategy": self.strategy,
            "static_chars": self.static_chars,
            "rendered_chars": self.rendered_chars,
            "union_chars": self.union_chars,
            "static_words": self.static_words,
            "rendered_words": self.rendered_words,
            "union_words": self.union_words,
            "static_coverage": round(self.static_coverage, 4),
            "render_error": self.render_error,
            "static_error": self.static_error,
            "wall": self.wall,
            "hidden_words": dict(self.hidden_words),
            "hidden_links": self.hidden_links,
            "hidden_hosts": [h.as_dict() for h in self.hidden_hosts],
            "hidden_external_hosts": self.hidden_external_hosts,
            "offscreen_links": self.offscreen_links,
            "offscreen_external_hosts": self.offscreen_external_hosts,
            "consent_words": self.consent_words,
            "total_words": self.total_words,
            "consent_share": round(self.consent_share, 4),
            "canonical": self.canonical,
            "lang": self.lang,
            "structured_data": list(self.structured_data),
            "has_schema": self.has_schema,
            "has_open_graph": self.has_open_graph,
            "internal_links": self.internal_links,
            "links_checked": self.links_checked,
            "dead_links": [d.as_dict() for d in self.dead_links],
            "dead_count": self.dead_count,
            "links_unreachable": self.links_unreachable,
            "in_sitemap": self.in_sitemap,
            "error": self.error,
        }


def section_of(url: str) -> str:
    path = urlsplit(url).path.strip("/")
    return path.split("/", 1)[0] if path else "/"


def _hidden_kind(element: Any) -> str | None:
    """How this element itself is hidden, by the renderer's mark or by its own inline style."""
    mark = element.get(HIDDEN_ATTRIBUTE)
    if mark in HIDDEN_KINDS:
        return str(mark)
    if isinstance(element.tag, str) and element.get("style") and styled_off_the_page(element):
        return "offscreen"
    return None


def _hidden_by(element: Any) -> str | None:
    """The kind hiding this element: its own, else the nearest hidden ancestor's."""
    own = _hidden_kind(element)
    if own is not None:
        return own
    for ancestor in element.iterancestors():
        kind = _hidden_kind(ancestor)
        if kind is not None:
            return kind
    return None


def _hidden_words(root: Any) -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(HIDDEN_KINDS, 0)
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        kind = _hidden_kind(element)
        if kind is None:
            continue
        if any(_hidden_kind(a) is not None for a in element.iterancestors()):
            continue  # counted under the outer hidden element
        counts[kind] += len(element.text_content().split())
    return counts


def _hidden_links(root: Any, page_url: str, host: str) -> tuple[int, int, tuple[HiddenHost, ...]]:
    """(hidden links, off-screen links, hosts) for every `<a href>` inside a hidden element."""
    by_host: Counter[str] = Counter()
    offscreen_by_host: Counter[str] = Counter()
    total = 0
    offscreen = 0
    own = registrable(host)
    for anchor in root.iter("a"):
        href = (anchor.get("href") or "").strip()
        if not href or href.lower().startswith(_SKIP_SCHEMES):
            continue
        kind = _hidden_by(anchor)
        if kind is None:
            continue
        target = urljoin(page_url, href)
        parts = urlsplit(target)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            continue
        name = parts.hostname.lower().removeprefix("www.")
        by_host[name] += 1
        total += 1
        if kind == "offscreen":
            offscreen_by_host[name] += 1
            offscreen += 1
    hosts = tuple(
        HiddenHost(host=name, links=count, offscreen=offscreen_by_host.get(name, 0), external=registrable(name) != own)
        for name, count in sorted(by_host.items(), key=lambda item: (-offscreen_by_host.get(item[0], 0), -item[1], item[0]))
    )
    return total, offscreen, hosts


def internal_links(html: str, page_url: str) -> list[str]:
    """The page's links to its own site, absolute, fragment dropped, in document order,
    each once; addresses that are files rather than pages are left out."""
    host = site_host(page_url)
    seen: set[str] = set()
    found: list[str] = []
    for href in extract_links(html, page_url).links:
        if href.lower().startswith(_SKIP_SCHEMES):
            continue
        absolute = urljoin(page_url, href).split("#", 1)[0]
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https") or site_host(absolute) != host:
            continue
        if parts.path.lower().endswith(_NOT_PAGES):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        found.append(absolute)
    return found


def measure_page(
    resolved: ResolvedPage,
    *,
    requested_url: str,
    host: str,
    checker: LinkChecker | None = None,
) -> PageReport:
    """Read the report's numbers off a resolved page. `checker`, when given, HEADs the
    page's internal links and records the dead ones."""
    document = resolved.document
    root = parse_html(document.html) if document.html.strip() else None

    hidden_words: dict[str, int] = dict.fromkeys(HIDDEN_KINDS, 0)
    hidden_count = 0
    offscreen_count = 0
    hidden_hosts: tuple[HiddenHost, ...] = ()
    lang: str | None = None
    if root is not None:
        hidden_words = _hidden_words(root)
        hidden_count, offscreen_count, hidden_hosts = _hidden_links(root, document.url, host)
        html_element = root if root.tag == "html" else root.getroottree().getroot()
        lang = (html_element.get("lang") or "").strip() or None

    total_words = sum(len(b.text.split()) for b in document.blocks)
    consent_words = sum(len(b.text.split()) for b in document.blocks if b.widget == "consent")

    wall: str | None = None
    if resolved.render_error and "served a wall" in resolved.render_error:
        wall = "browser"
    if resolved.static_error and "served a wall" in resolved.static_error:
        wall = "plain fetch"

    links = internal_links(document.html, document.url) if document.html else []
    checked = 0
    dead: tuple[DeadLink, ...] = ()
    unreachable = 0
    if checker is not None and links:
        checked, dead, unreachable = checker.check(links, exclude={document.url, requested_url})

    return PageReport(
        requested_url=requested_url,
        url=document.url,
        section=section_of(requested_url),
        title=document.title,
        description=document.description,
        strategy=resolved.strategy.value,
        static_chars=resolved.static_chars,
        rendered_chars=resolved.rendered_chars,
        union_chars=resolved.union_chars,
        static_words=resolved.static_words,
        rendered_words=resolved.rendered_words,
        union_words=resolved.union_words,
        static_coverage=resolved.static_coverage,
        render_error=resolved.render_error,
        static_error=resolved.static_error,
        wall=wall,
        hidden_words=hidden_words,
        hidden_links=hidden_count,
        hidden_hosts=hidden_hosts,
        hidden_external_hosts=sum(1 for h in hidden_hosts if h.external),
        offscreen_links=offscreen_count,
        offscreen_external_hosts=sum(1 for h in hidden_hosts if h.external and h.offscreen),
        consent_words=consent_words,
        total_words=total_words,
        canonical=extract_links(document.html, document.url).canonical if document.html else None,
        lang=lang,
        structured_data=tuple(dict.fromkeys(p.source.value for p in document.structured_data)),
        internal_links=len(links),
        links_checked=checked,
        dead_links=dead,
        links_unreachable=unreachable,
    )


class Pacer:
    """At most one request per `interval` seconds to each host, across everything the
    report does. Reads `config.REPORT_REQUEST_INTERVAL_SECONDS` at construction so a test
    can set it to zero."""

    def __init__(self, interval: float | None = None) -> None:
        self.interval = config.REPORT_REQUEST_INTERVAL_SECONDS if interval is None else interval
        self._last: dict[str, float] = {}

    def wait(self, url: str) -> None:
        host = site_host(url)
        now = time.monotonic()
        due = self._last.get(host, 0.0) + self.interval
        if due > now:
            time.sleep(due - now)
            now = time.monotonic()
        self._last[host] = now


class LinkChecker:
    """HEADs a page's internal links and says which are dead (status >= 400).

    Each address is checked once per report: a site's navigation repeats on every page,
    and checking it five times would be five times the requests for the same answer. A
    link robots.txt disallows for this client is not checked -- asking would be the
    request the site declined -- and is counted as neither checked nor dead. HEAD first;
    a server that refuses HEAD (405, 501) or answers it with an error is asked with GET,
    the body not read, before the link is called dead.
    """

    def __init__(
        self,
        *,
        fetch_config: FetchConfig | None = None,
        policy: RobotsPolicy | None = None,
        pacer: Pacer | None = None,
        per_page: int | None = None,
    ) -> None:
        self.fetch_config = fetch_config or FetchConfig()
        self.policy = policy
        self.pacer = pacer or Pacer()
        self.per_page = config.REPORT_DEAD_LINK_CHECKS_PER_PAGE if per_page is None else per_page
        self.statuses: dict[str, int] = {}
        """Every address checked this report and the status it answered; 0 for no answer."""

    def check(
        self, links: list[str], *, exclude: AbstractSet[str] = frozenset()
    ) -> tuple[int, tuple[DeadLink, ...], int]:
        """(links checked, the dead ones, links that gave no answer) for one page's links."""
        checked = 0
        dead: list[DeadLink] = []
        unreachable = 0
        for link in links:
            if checked >= self.per_page:
                break
            if link in exclude:
                continue
            if self.policy is not None and not self.policy.allows(link):
                continue
            if link not in self.statuses:
                self.pacer.wait(link)
                self.statuses[link] = self.status_of(link)
            status = self.statuses[link]
            if status == 0:
                unreachable += 1
                continue
            checked += 1
            if status >= 400:
                dead.append(DeadLink(url=link, status=status))
        return checked, tuple(dead), unreachable

    def status_of(self, url: str) -> int:
        """The status `url` answers; 0 when it does not answer. Through the same host guard
        every other request passes, so a link into a private address is refused, not fetched."""
        headers = {"User-Agent": self.fetch_config.user_agent, "Accept": "*/*"}
        try:
            with httpx.Client(
                http2=self.fetch_config.http2,
                follow_redirects=True,
                max_redirects=self.fetch_config.max_redirects,
                timeout=self.fetch_config.timeout_seconds,
                headers=headers,
                event_hooks={"request": [guard.hook]},
            ) as client:
                response = client.head(url)
                if response.status_code >= 400:
                    # HEAD is refused by some servers and mis-answered by others; the
                    # question is whether the page is there, and GET is what a reader sends.
                    with client.stream("GET", url) as confirmed:
                        return int(confirmed.status_code)
                return int(response.status_code)
        except httpx.HTTPError:
            return 0
