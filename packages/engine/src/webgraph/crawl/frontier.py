"""URL normalisation, scoping and the crawl frontier.

Normalisation is the whole game for a crawler. `example.com/a`, `example.com/a/`,
`example.com/a#top` and `example.com/a?utm_source=x` are one page, and a crawler that treats
them as four will spend its budget four times over and produce four copies of every entity.
Getting this wrong is the difference between crawling a site and crawling a site's URL space.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

__all__ = [
    "CrawlScope",
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


@dataclass
class Frontier:
    """Breadth-first queue of URLs to visit, with deduplication.

    Breadth-first rather than depth-first so that a bounded budget is spent near the site
    root, where the pages that describe the site generally live. A depth-first crawl with a
    50-page budget can disappear into one blog archive and never see the pricing page.
    """

    scope: CrawlScope
    _queue: deque[tuple[str, int]] = field(default_factory=deque)
    _seen: set[str] = field(default_factory=set)

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
        self._queue.append((normalized, depth))
        return True

    def extend(self, urls: list[str], depth: int, *, base: str | None = None) -> list[str]:
        """Queue several URLs, returning the ones newly accepted.

        Callers that only need the count use `add_many`. The list matters to the streaming
        API, which reports discovery incrementally: sending the whole frontier on every
        event would be quadratic, while sending each event's *new* URLs lets a client
        rebuild the same set for a fraction of the bytes.
        """
        accepted: list[str] = []
        for url in urls:
            normalized = normalize_url(url, base=base)
            if normalized is not None and self.add(normalized, depth):
                accepted.append(normalized)
        return accepted

    def add_many(self, urls: list[str], depth: int, *, base: str | None = None) -> int:
        return len(self.extend(urls, depth, base=base))

    def pop(self) -> tuple[str, int] | None:
        return self._queue.popleft() if self._queue else None

    def __len__(self) -> int:
        return len(self._queue)

    @property
    def seen_count(self) -> int:
        return len(self._seen)
