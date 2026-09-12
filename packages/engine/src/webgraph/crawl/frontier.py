"""URL normalisation, scoping and the crawl frontier.

Normalisation is the whole game for a crawler. `example.com/a`, `example.com/a/`,
`example.com/a#top` and `example.com/a?utm_source=x` are one page, and a crawler that treats
them as four will spend its budget four times over and produce four copies of every entity.
Getting this wrong is the difference between crawling a site and crawling a site's URL space.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

__all__ = [
    "CrawlScope",
    "Discovery",
    "Frontier",
    "canonical_key",
    "normalize_url",
    "reconcile_scheme",
    "same_site",
]

TRACKING_PARAMS: Final[frozenset[str]] = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src",
    "_ga", "_gl", "yclid", "dclid", "twclid", "s_kwcid", "hsa_acc", "hsa_cam",
})
"""Stripped during normalisation. These change per visitor and never change the page."""

NON_PAGE_SUFFIXES: Final[frozenset[str]] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".ico", ".bmp", ".tiff",
    ".css", ".js", ".mjs", ".map", ".json", ".xml", ".rss", ".atom",
    ".zip", ".gz", ".tar", ".rar", ".7z", ".dmg", ".exe", ".pkg", ".deb", ".rpm",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".webm", ".ogg", ".wav", ".m4a",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
})
"""Skipped by the crawler. PDFs are deliberately absent -- they are documents worth
extracting, and belong to the document pipeline rather than being discarded here."""

_DEFAULT_PORTS: Final[dict[str, str]] = {"http": "80", "https": "443"}
_INDEX_FILE: Final[re.Pattern[str]] = re.compile(r"/index\.(html?|php|aspx?)$", re.IGNORECASE)


_JS_HOLE: Final[re.Pattern[str]] = re.compile(r"/(?:undefined|null|NaN|\[object Object\])(?:/|$)")


def normalize_url(url: str, *, base: str | None = None) -> str | None:
    """Canonicalise a URL, or return None when it is not a crawlable page.

    Resolves against `base`, lowercases scheme and host, drops the fragment, removes the
    default port, strips tracking parameters, sorts the remaining query, and collapses
    `/index.html` to `/`. Query order is normalised because many servers emit the same page
    with parameters in different orders.
    """
    if not url or url.startswith(("#", "javascript:", "mailto:", "tel:", "data:", "blob:")):
        return None

    try:
        resolved = urljoin(base, url) if base else url
        parts = urlsplit(resolved)
    except ValueError:
        return None

    if parts.scheme not in {"http", "https"}:
        return None
    if not parts.hostname:
        return None
    # `/undefined` and `/null` are a template interpolating a missing value, not addresses.
    # Every crawl of a Vue or React storefront finds one, and fetching it costs a render.
    if _JS_HOLE.search(parts.path):
        return None

    host = parts.hostname.lower()
    if parts.port and str(parts.port) != _DEFAULT_PORTS.get(parts.scheme):
        host = f"{host}:{parts.port}"

    path = _INDEX_FILE.sub("/", parts.path) or "/"

    suffix = path.rsplit("/", 1)[-1]
    if "." in suffix:
        extension = "." + suffix.rsplit(".", 1)[-1].lower()
        if extension in NON_PAGE_SUFFIXES:
            return None

    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMS
        )
    )

    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def reconcile_scheme(url: str, root: str) -> str:
    """Rewrite `url` to use `root`'s scheme when they share a host.

    Sitemaps routinely advertise `http://` URLs for sites that only serve `https://` --
    ionidea.com does exactly this, and fetching its sitemap URLs verbatim fails with
    `Network is unreachable` on every one of them. Taking the scheme from the root, which
    was just fetched successfully, turns a total crawl failure into a working one.

    Only the scheme is changed, and only when the hosts match, so this cannot redirect a
    crawl to a different site.
    """
    try:
        target = urlsplit(url)
        origin = urlsplit(root)
    except ValueError:
        return url

    if not target.hostname or not origin.hostname:
        return url
    if target.hostname.lower() != origin.hostname.lower():
        return url
    if target.scheme == origin.scheme:
        return url

    return urlunsplit((origin.scheme, target.netloc, target.path, target.query, target.fragment))


def same_site(url: str, root: str, *, allow_subdomains: bool = False) -> bool:
    """Whether `url` belongs to the same site as `root`.

    `www.` is stripped from both sides before comparing. `www.example.com` and
    `example.com` are the same site by universal convention, and treating them as different
    is catastrophic rather than merely conservative: persyn.ai declares
    `<link rel="canonical" href="https://www.persyn.ai/">` while resolving at the bare
    domain, so an exact-hostname comparison rejected **every** link on the site and the
    crawl finished after one page.

    Other subdomains are still excluded by default: `blog.example.com` and
    `shop.example.com` are usually separate applications, and quietly following them turns a
    bounded crawl into an unbounded one.
    """
    try:
        target = urlsplit(url).hostname
        origin = urlsplit(root).hostname
    except ValueError:
        return False
    if not target or not origin:
        return False

    target = target.lower().removeprefix("www.")
    origin = origin.lower().removeprefix("www.")

    if target == origin:
        return True
    if not allow_subdomains:
        return False

    return target.endswith(f".{origin}")


def canonical_key(url: str) -> str:
    """Identity for deduplication, distinct from the URL used to fetch.

    Strips a `www.` prefix and a trailing slash. `solidjs.com` redirects to
    `www.solidjs.com`, so a crawl that keys on the raw string queues every page twice --
    once per hostname form -- doubling the work and duplicating every extracted entity.

    Deliberately *only* a key. The original URL is what gets fetched, because some hosts
    serve only one of the two forms and rewriting the request would 404.
    """
    normalized = normalize_url(url)
    if normalized is None:
        return url
    parts = urlsplit(normalized)
    host = (parts.hostname or "").removeprefix("www.")
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, host, path, parts.query, ""))


@dataclass(frozen=True, slots=True)
class CrawlScope:
    """Rules deciding which discovered URLs are followed."""

    root: str
    allow_subdomains: bool = False
    include_patterns: tuple[re.Pattern[str], ...] = ()
    """When non-empty, a URL must match at least one to be crawled."""

    exclude_patterns: tuple[re.Pattern[str], ...] = ()
    max_depth: int = 3

    def permits(self, url: str, depth: int) -> bool:
        if depth > self.max_depth:
            return False
        if not same_site(url, self.root, allow_subdomains=self.allow_subdomains):
            return False
        if any(pattern.search(url) for pattern in self.exclude_patterns):
            return False
        if self.include_patterns:
            return any(pattern.search(url) for pattern in self.include_patterns)
        return True


@dataclass(frozen=True, slots=True)
class Discovery:
    """How one address came to be in a crawl. The evidence behind a page being here.

    Everything a crawl reports should be answerable with "and how do you know" -- this is that
    answer for the existence of a page. `via` is `seed`, `sitemap` or `link`; `anchor` is the
    text a reader would have clicked, which is often the only human-readable reason a link was
    followed at all.
    """

    url: str
    via: str
    found_on: str | None = None
    anchor: str | None = None
    depth: int = 0

    def as_dict(self) -> dict[str, object]:
        """Shape the streaming API and the trace both use."""
        return {
            "via": self.via,
            "found_on": self.found_on,
            "anchor": self.anchor,
            "depth": self.depth,
        }



@dataclass
class Frontier:
    """Breadth-first queue of URLs to visit, with deduplication.

    Breadth-first rather than depth-first so that a bounded budget is spent near the site
    root, where the pages that describe the site generally live. A depth-first crawl with a
    50-page budget can disappear into one blog archive and never see the pricing page.
    """

    scope: CrawlScope
    _lanes: dict[int, deque[str]] = field(default_factory=dict)
    """One FIFO per depth. `pop` drains the shallowest non-empty lane, so the crawl is
    breadth-first by construction rather than by the accident of arrival order: a
    depth-2 address queued while depth-1 addresses are still arriving waits behind all of
    them, whichever thread found it first."""
    _seen: set[str] = field(default_factory=set)
    _depths: dict[str, int] = field(default_factory=dict)
    """Link distance from the root for every accepted address, by canonical key."""

    origin: dict[str, Discovery] = field(default_factory=dict)
    """How each address came to be in this crawl, for whoever accepted it first.

    Public, because the crawl reports it and a failed page is not actionable without it --
    "could not fetch X" leaves you hunting for which page linked to X, and only the frontier
    ever knew. Kept for the *first* acceptance: a URL linked from twenty pages is one page,
    and the citation that matters is the one that brought it into the crawl."""

    def add(self, url: str, depth: int, *, base: str | None = None) -> bool:
        """Queue a URL. Returns whether it was newly accepted.

        Membership is tested on `canonical_key`, so `example.com/a` and `www.example.com/a/`
        count as one page, while the queued URL stays the one the site actually linked to.
        """
        normalized = normalize_url(url, base=base)
        if normalized is None:
            return False
        key = canonical_key(normalized)
        if key in self._seen:
            return False
        if not self.scope.permits(normalized, depth):
            return False
        self._seen.add(key)
        self._lanes.setdefault(depth, deque()).append(normalized)
        self._depths[key] = depth
        return True

    def extend(
        self,
        urls: list[str],
        depth: int,
        *,
        base: str | None = None,
        found_on: str | None = None,
        via: str = "link",
        anchors: Mapping[str, str] | None = None,
    ) -> list[str]:
        """Queue several URLs, returning the ones newly accepted.

        Callers that only need the count use `add_many`. The list matters to the streaming
        API, which reports discovery incrementally: sending the whole frontier on every
        event would be quadratic, while sending each event's *new* URLs lets a client
        rebuild the same set for a fraction of the bytes.

        The citation is recorded here and nowhere else. `via` says how the address was
        found, `found_on` which page produced it, and `anchors` maps a raw href to the text
        of the link that carried it -- so a crawl can answer "why is this page here" with the
        page, the method and the words a reader would have clicked, rather than an assertion.

        Anchors are keyed by the *raw* href because that is what the page contained; the
        normalised form is what the frontier stores, and the two differ by exactly the
        tracking parameters and trailing slashes that normalisation removes.
        """
        accepted: list[str] = []
        for url in urls:
            normalized = normalize_url(url, base=base)
            if normalized is not None and self.add(normalized, depth):
                accepted.append(normalized)
                label = (anchors or {}).get(url)
                self.origin.setdefault(
                    normalized,
                    Discovery(
                        url=normalized,
                        via=via,
                        found_on=found_on,
                        anchor=(label or None),
                        depth=depth,
                    ),
                )
        return accepted

    def citation(self, url: str) -> Discovery | None:
        """How this address entered the crawl, or None if it was never recorded."""
        return self.origin.get(url)

    def add_many(self, urls: list[str], depth: int, *, base: str | None = None) -> int:
        return len(self.extend(urls, depth, base=base))

    def mark_seen(self, url: str) -> bool:
        """Record `url` as visited without queuing it. Returns whether it was new.

        For a page the caller already holds -- the root, which site analysis fetched before
        the crawl began -- so the frontier neither re-queues it nor counts it as undiscovered
        when a later page links back to it.
        """
        normalized = normalize_url(url)
        if normalized is None:
            return False
        key = canonical_key(normalized)
        if key in self._seen:
            return False
        self._seen.add(key)
        # The page the caller holds is the root, and the root is depth 0.
        self._depths.setdefault(key, 0)
        return True

    def pop(self) -> tuple[str, int] | None:
        """The next address to fetch: the oldest one at the shallowest depth."""
        for depth in sorted(self._lanes):
            lane = self._lanes[depth]
            if lane:
                return lane.popleft(), depth
        return None

    def depth_counts(self) -> dict[int, int]:
        """How many addresses were accepted at each link distance from the root.

        The shape of a site as the crawl sees it: `{0: 1, 1: 98, 2: 1,340}` says the root
        links to 98 pages and those link to 1,340 more. Reported on every event so a reader
        can watch a breadth-first crawl finish one depth before it starts the next."""
        counts: dict[int, int] = {}
        for depth in self._depths.values():
            counts[depth] = counts.get(depth, 0) + 1
        return dict(sorted(counts.items()))

    def __len__(self) -> int:
        return sum(len(lane) for lane in self._lanes.values())

    @property
    def seen_count(self) -> int:
        return len(self._seen)
