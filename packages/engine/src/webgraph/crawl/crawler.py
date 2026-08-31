"""Whole-site crawling.

Walks a site breadth-first from a root URL, extracting each page into a `Document`.

Three decisions worth stating:

**Breadth-first, not depth-first.** With a bounded page budget, depth-first can disappear
into a single blog archive and never reach the pricing page. Breadth-first spends the budget
near the root, where the pages that describe a site actually live.

**Batched parallelism rather than a worker pool.** Each depth level is fetched concurrently,
then the frontier is extended from the results. This keeps the frontier single-threaded and
lock-free, and makes a crawl reproducible for a given site -- a shared mutable queue would
make page order depend on thread scheduling.

**The content hash gates re-extraction.** Passing `known_hashes` from a previous crawl skips
parsing for pages whose text has not changed. Fetching is cheap; extraction is not, and on a
recurring crawl most pages are unchanged.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Final

from webgraph.crawl.discovery import RobotsPolicy, discover_sitemap_urls, extract_links, load_robots
from webgraph.crawl.frontier import CrawlScope, Frontier, normalize_url
from webgraph.fetch.static import FetchConfig, fetch_static
from webgraph.pipeline import build_document
from webgraph.types import Document

__all__ = ["CrawlConfig", "CrawlReport", "CrawledPage", "crawl_site"]

_MAX_SITEMAP_SEEDS: Final[int] = 500


@dataclass(frozen=True, slots=True)
class CrawlConfig:
    max_pages: int = 50
    max_depth: int = 3
    allow_subdomains: bool = False
    concurrency: int = 4
    """Parallel fetches per depth level. Kept modest by default -- an extraction engine that
    hammers a site is one that gets blocked."""

    delay_seconds: float = 0.3
    """Politeness pause before each fetch. Overridden upward by robots.txt Crawl-delay."""

    respect_robots: bool = True
    use_sitemap: bool = True
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    fetch: FetchConfig = field(default_factory=FetchConfig)


@dataclass(frozen=True, slots=True)
class CrawledPage:
    url: str
    depth: int
    status: int
    document: Document | None = None
    error: str | None = None
    unchanged: bool = False
    """True when the content hash matched a previous crawl and extraction was skipped."""

    elapsed_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None and self.document is not None


@dataclass(frozen=True, slots=True)
class CrawlReport:
    root: str
    pages: tuple[CrawledPage, ...]
    duration_seconds: float
    robots_fetched: bool
    sitemap_seeds: int
    skipped_by_robots: int
    frontier_seen: int

    @property
    def successful(self) -> tuple[CrawledPage, ...]:
        return tuple(page for page in self.pages if page.ok)

    @property
    def failed(self) -> tuple[CrawledPage, ...]:
        return tuple(page for page in self.pages if not page.ok)

    @property
    def unchanged_count(self) -> int:
        return sum(1 for page in self.pages if page.unchanged)

    def hashes(self) -> dict[str, str]:
        """Content hashes by URL, for gating the next crawl of this site."""
        return {
            page.url: page.document.content_hash
            for page in self.pages
            if page.document is not None
        }

    def summary(self) -> str:
        return (
            f"crawled {len(self.successful)}/{len(self.pages)} pages from {self.root} "
            f"in {self.duration_seconds:.1f}s "
            f"(unchanged={self.unchanged_count}, failed={len(self.failed)}, "
            f"robots-skipped={self.skipped_by_robots})"
        )


def _fetch_one(
    url: str,
    depth: int,
    config: CrawlConfig,
    delay: float,
    known_hashes: dict[str, str],
) -> tuple[CrawledPage, list[str], str | None]:
    """Fetch and extract one page. Returns (page, discovered links, canonical URL)."""
    if delay > 0:
        time.sleep(delay)

    started = time.monotonic()
    result = fetch_static(url, config=config.fetch)

    if not result.ok:
        return (
            CrawledPage(
                url=url,
                depth=depth,
                status=result.status,
                error=result.error,
                elapsed_seconds=time.monotonic() - started,
            ),
            [],
            None,
        )

    if not result.is_html:
        return (
            CrawledPage(
                url=url,
                depth=depth,
                status=result.status,
                error=f"not HTML ({result.content_type})",
                elapsed_seconds=time.monotonic() - started,
            ),
            [],
            None,
        )

    link_set = extract_links(result.html, result.url)

    try:
        document = build_document(result.html, result.url)
    except ValueError as exc:
        return (
            CrawledPage(
                url=url,
                depth=depth,
                status=result.status,
                error=f"parse failed: {exc}",
                elapsed_seconds=time.monotonic() - started,
            ),
            link_set.links,
            link_set.canonical,
        )

    unchanged = known_hashes.get(url) == document.content_hash

    return (
        CrawledPage(
            url=url,
            depth=depth,
            status=result.status,
            document=document,
            unchanged=unchanged,
            elapsed_seconds=time.monotonic() - started,
        ),
        link_set.links,
        link_set.canonical,
    )


def crawl_site(
    root: str,
    *,
    config: CrawlConfig | None = None,
    known_hashes: dict[str, str] | None = None,
) -> CrawlReport:
    """Crawl a site from `root`, returning every page extracted.

    `known_hashes` maps URL to the content hash from a previous crawl; matching pages are
    marked `unchanged` so a caller can skip downstream work on them.
    """
    config = config or CrawlConfig()
    known_hashes = known_hashes or {}
    started = time.monotonic()

    normalized_root = normalize_url(root)
    if normalized_root is None:
        raise ValueError(f"not a crawlable URL: {root}")

    policy = (
        load_robots(normalized_root, config=config.fetch)
        if config.respect_robots
        else RobotsPolicy(origin=normalized_root, fetched=False)
    )

    delay = max(config.delay_seconds, policy.crawl_delay or 0.0)

    scope = CrawlScope(
        root=normalized_root,
        allow_subdomains=config.allow_subdomains,
        include_patterns=tuple(re.compile(p) for p in config.include_patterns),
        exclude_patterns=tuple(re.compile(p) for p in config.exclude_patterns),
        max_depth=config.max_depth,
    )
    frontier = Frontier(scope=scope)
    frontier.add(normalized_root, 0)

    sitemap_seeds = 0
    if config.use_sitemap:
        seeds = discover_sitemap_urls(
            normalized_root, policy=policy, config=config.fetch, limit=_MAX_SITEMAP_SEEDS
        )
        # Sitemap URLs enter at depth 1: they are known-good pages but should not displace
        # the root's own links from the budget.
        sitemap_seeds = frontier.add_many(seeds, 1)

    pages: list[CrawledPage] = []
    skipped_by_robots = 0

    with ThreadPoolExecutor(max_workers=max(1, config.concurrency)) as pool:
        while len(pages) < config.max_pages and len(frontier) > 0:
            batch: list[tuple[str, int]] = []
            while len(frontier) > 0 and len(batch) < config.concurrency:
                if len(pages) + len(batch) >= config.max_pages:
                    break
                item = frontier.pop()
                if item is None:
                    break
                url, depth = item
                if config.respect_robots and not policy.allows(url, config.fetch.user_agent):
                    skipped_by_robots += 1
                    continue
                batch.append((url, depth))

            if not batch:
                continue

            results = list(
                pool.map(
                    lambda item: _fetch_one(item[0], item[1], config, delay, known_hashes),
                    batch,
                )
            )

            for page, links, canonical in results:
                pages.append(page)
                if page.document is None:
                    continue
                base = canonical or page.url
                frontier.add_many(links, page.depth + 1, base=base)

    return CrawlReport(
        root=normalized_root,
        pages=tuple(pages),
        duration_seconds=time.monotonic() - started,
        robots_fetched=policy.fetched,
        sitemap_seeds=sitemap_seeds,
        skipped_by_robots=skipped_by_robots,
        frontier_seen=frontier.seen_count,
    )
