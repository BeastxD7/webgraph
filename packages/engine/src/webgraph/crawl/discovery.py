"""Seed discovery: robots.txt and sitemaps.

A crawler that only follows links wastes budget rediscovering a site's structure that the
site already published. Sitemaps give the URL set directly, which matters most on the sites
where link-following is worst -- paginated catalogues and JavaScript navigation.

robots.txt is honoured rather than merely parsed. An extraction engine that ignores it will
get blocked, and deserves to be.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from webgraph.crawl.frontier import reconcile_scheme
from webgraph.fetch.static import DEFAULT_USER_AGENT, FetchConfig, fetch_static

__all__ = [
    "RobotsPolicy",
    "discover_by_crawling",
    "discover_sitemap_urls",
    "extract_links",
    "load_robots",
]

_SITEMAP_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*sitemap:\s*(\S+)", re.IGNORECASE | re.MULTILINE)
_LOC: Final[re.Pattern[str]] = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.IGNORECASE)
_SITEMAP_INDEX: Final[re.Pattern[str]] = re.compile(r"<sitemapindex", re.IGNORECASE)

MAX_SITEMAP_DOCUMENTS: Final[int] = 20
"""Sitemap indexes can nest into thousands of files. Bounded so discovery cannot itself
become the crawl."""


@dataclass
class RobotsPolicy:
    """Fetch permissions and crawl delay for one origin."""

    origin: str
    parser: RobotFileParser | None = None
    sitemaps: tuple[str, ...] = ()
    crawl_delay: float | None = None
    fetched: bool = False
    """False when robots.txt was unreachable. A missing file means *allow*, per convention --
    but it is recorded so the distinction stays visible."""

    def allows(self, url: str, user_agent: str = DEFAULT_USER_AGENT) -> bool:
        if self.parser is None:
            return True
        try:
            return bool(self.parser.can_fetch(user_agent, url))
        except Exception:
            return True


def load_robots(root: str, *, config: FetchConfig | None = None) -> RobotsPolicy:
    """Fetch and parse robots.txt for the origin of `root`."""
    parts = urlsplit(root)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots_url = urljoin(origin, "/robots.txt")

    result = fetch_static(robots_url, config=config)
    if not result.ok or not result.html.strip():
        return RobotsPolicy(origin=origin, fetched=False)

    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.parse(result.html.splitlines())
    except Exception:
        return RobotsPolicy(origin=origin, fetched=True)

    sitemaps = tuple(
        urljoin(origin, match.group(1)) for match in _SITEMAP_LINE.finditer(result.html)
    )

    delay: float | None = None
    try:
        raw_delay = parser.crawl_delay(DEFAULT_USER_AGENT)
        if raw_delay is not None:
            delay = float(raw_delay)
    except Exception:
        delay = None

    return RobotsPolicy(
        origin=origin,
        parser=parser,
        sitemaps=sitemaps,
        crawl_delay=delay,
        fetched=True,
    )


def discover_sitemap_urls(
    root: str,
    *,
    policy: RobotsPolicy | None = None,
    config: FetchConfig | None = None,
    limit: int = 5000,
) -> list[str]:
    """Collect page URLs from a site's sitemaps.

    Tries the locations robots.txt advertises first, then the conventional `/sitemap.xml`.
    Sitemap indexes are followed one level, bounded by `MAX_SITEMAP_DOCUMENTS`.
    """
    parts = urlsplit(root)
    origin = f"{parts.scheme}://{parts.netloc}"

    candidates: list[str] = list(policy.sitemaps) if policy else []
    for conventional in ("/sitemap.xml", "/sitemap_index.xml"):
        candidate = urljoin(origin, conventional)
        if candidate not in candidates:
            candidates.append(candidate)

    found: list[str] = []
    visited: set[str] = set()
    queue = list(candidates)
    documents = 0

    while queue and documents < MAX_SITEMAP_DOCUMENTS and len(found) < limit:
        sitemap_url = queue.pop(0)
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)

        result = fetch_static(sitemap_url, config=config)
        documents += 1
        if not result.ok or "<loc" not in result.html.lower():
            continue

        # Sitemaps often advertise a scheme the site no longer serves. Reconcile against
        # the root, which was just fetched successfully.
        locations = [
            reconcile_scheme(match.group(1), root) for match in _LOC.finditer(result.html)
        ]
        if _SITEMAP_INDEX.search(result.html):
            # An index lists sitemaps, not pages.
            queue.extend(location for location in locations if location not in visited)
        else:
            found.extend(locations)

    return found[:limit]


MAX_ANCHOR_CHARS: Final[int] = 160
"""Anchor text longer than this is a card or a whole paragraph wrapped in a link, not a
label."""


@dataclass
class LinkSet:
    links: list[str] = field(default_factory=list)
    canonical: str | None = None

    anchored: list[tuple[str, str]] = field(default_factory=list)
    """(href, anchor text) pairs, in document order.

    The anchor is what the site's own author chose to call the target page. Graph-based
    retrieval systems normally pay a language model to invent a label for an edge; here the
    label was written by a human and comes free with the link.
    """


def extract_links(html: str, base_url: str) -> LinkSet:
    """Pull outbound links and the canonical URL from a parsed page.

    The canonical link matters for deduplication: many sites serve identical content at
    several URLs and declare which one is real. Following that declaration avoids extracting
    the same page repeatedly under different addresses.
    """
    from webgraph.dom.blocks import parse_html

    try:
        root = parse_html(html)
    except ValueError:
        return LinkSet()

    canonical: str | None = None
    for link in root.xpath("//link[@rel='canonical'][@href]"):
        href = (link.get("href") or "").strip()
        if href:
            canonical = urljoin(base_url, href)
            break

    hrefs: list[str] = []
    anchored: list[tuple[str, str]] = []
    for anchor in root.xpath("//a[@href]"):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        rel = (anchor.get("rel") or "").lower()
        if "nofollow" in rel:
            continue
        hrefs.append(href)
        label = " ".join((anchor.text_content() or "").split())[:MAX_ANCHOR_CHARS]
        if label:
            anchored.append((href, label))

    return LinkSet(links=hrefs, canonical=canonical, anchored=anchored)


def discover_by_crawling(
    root: str,
    *,
    max_urls: int = 500,
    max_depth: int = 3,
    concurrency: int = 6,
    config: FetchConfig | None = None,
    policy: RobotsPolicy | None = None,
    delay_seconds: float = 0.1,
) -> list[str]:
    """Harvest on-site URLs by following links, breadth-first.

    Deliberately lighter than a full crawl: it fetches and extracts links only, never
    building a `Document`. Discovery is about finding *what exists*, and paying extraction
    cost per candidate would make exploring a site more expensive than reading it.

    This exists because a sitemap is neither complete nor current. `ionidea.com` publishes
    89 URLs of which most 404, while linking from its own homepage to live pages -- such as
    `insurance-agentology.php` -- that the sitemap never mentions. Either source alone
    loses pages; only the union is trustworthy.
    """
    from concurrent.futures import ThreadPoolExecutor

    from webgraph.crawl.frontier import CrawlScope, Frontier

    scope = CrawlScope(root=root, max_depth=max_depth)
    frontier = Frontier(scope=scope)
    frontier.add(root, 0)

    found: list[str] = []
    visited: set[str] = set()

    def harvest(item: tuple[str, int]) -> tuple[str, int, list[str], str | None]:
        url, depth = item
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        result = fetch_static(url, config=config)
        if not result.ok or not result.is_html:
            return url, depth, [], None
        links = extract_links(result.html, result.url)
        return url, depth, links.links, links.canonical

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        while len(visited) < max_urls and len(frontier) > 0:
            batch: list[tuple[str, int]] = []
            while len(frontier) > 0 and len(batch) < concurrency:
                item = frontier.pop()
                if item is None:
                    break
                if policy is not None and not policy.allows(item[0]):
                    continue
                batch.append(item)

            if not batch:
                continue

            for url, depth, links, canonical in pool.map(harvest, batch):
                visited.add(url)
                # Reconcile here as well as for sitemaps: internal links frequently
                # hard-code a scheme the site no longer serves.
                canonical_url = reconcile_scheme(url, root)
                if canonical_url not in found:
                    found.append(canonical_url)
                frontier.add_many(
                    [reconcile_scheme(link, root) for link in links],
                    depth + 1,
                    base=canonical or url,
                )

    return found[:max_urls]
