"""Whole-site extraction: analyse, enumerate, fetch every page, aggregate.

Implements stages 1-4 of the pipeline (stage 0 lives in `analyze.py`).

Two things measured on real sites shape this module:

**A sitemap count is a claim, not a fact.** `ionidea.com` advertises 90 URLs in its
sitemap; most return 404. Reporting "90 public pages" from the sitemap alone would be
wrong. Stage 1 therefore *verifies* the inventory and reports advertised, live and dead
separately.

**Aggregation is only worth what the pages publish.** Merging 90 pages that each carry the
same `Organization` block yields one entity, not ninety. The site view reports how many
distinct entities were actually found so the ceiling is visible rather than implied.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Any, Final

from webgraph import config
from webgraph.analyze import SiteAnalysis, SiteProbe, probe_site
from webgraph.boilerplate import MIN_PAGES as MIN_CHROME_PAGES
from webgraph.boilerplate import SiteChrome, detect_site_chrome
from webgraph.content import ContentSelection, select_content
from webgraph.crawl.discovery import (
    RobotsPolicy,
    discover_by_crawling,
    discover_sitemap_urls,
    extract_links,
    load_robots,
)
from webgraph.crawl.frontier import (
    CrawlScope,
    Discovery,
    Frontier,
    normalize_url,
    reconcile_scheme,
)
from webgraph.extract.schema import extract_facts, merge_facts
from webgraph.fetch.render import RenderConfig
from webgraph.fetch.static import FetchConfig, fetch_static
from webgraph.graph.build import GraphBuilder
from webgraph.pagetype import default_router, policy_for
from webgraph.render_markdown import MarkdownOptions, to_markdown
from webgraph.resolve import PageMissingError, ResolvedPage, Strategy, resolve_page
from webgraph.types import BlockKind, Document, Fact, PayloadSource

IDENTICAL_CONTENT_WARNING = config.IDENTICAL_CONTENT_WARNING

__all__ = [
    "IDENTICAL_CONTENT_WARNING",
    "PageExtraction",
    "PageInventory",
    "SiteConfig",
    "SiteEntity",
    "SiteExtraction",
    "build_inventory",
    "extract_site",
    "resolve_root",
    "stream_site",
    "verify_inventory",
]



@dataclass(frozen=True, slots=True)
class SiteConfig:
    max_pages: int = config.CRAWL_MAX_PAGES
    """0 means unbounded: crawl until the frontier is exhausted."""
    concurrency: int = config.CRAWL_CONCURRENCY
    delay_seconds: float = config.CRAWL_DELAY_SECONDS
    verify_inventory: bool = config.CRAWL_VERIFY_INVENTORY
    """Check each advertised URL before crawling it. Costs one cheap request per URL and
    prevents a stale sitemap from consuming the whole page budget on 404s."""

    follow_links: bool = config.CRAWL_FOLLOW_LINKS
    """Discover routes by following links in addition to reading the sitemap. Both run
    always -- a sitemap is frequently stale, incomplete, or both."""

    discovery_limit: int = config.CRAWL_DISCOVERY_LIMIT
    """Ceiling on URLs harvested by link-following before verification."""

    max_depth: int = config.CRAWL_MAX_DEPTH
    """How many links away from the root the crawl will go. 0 is the root alone.

    The crawl is breadth-first: every page at depth *n* is fetched before any page at depth
    *n + 1*, so a bounded page budget is spent near the root, where the pages that describe
    a site live. Depth 0 is the address given; depth 1 is everything the root page links to
    or its sitemap lists; depth 2 is everything those pages link to, and so on. High by
    default -- a deep site is still a finite one, and the page budget is the real bound."""

    strict_domain: bool = config.CRAWL_STRICT_DOMAIN
    """Stay on the root's host, or also follow its subdomains.

    Strict means `www.example.com` and `example.com` only -- they are the same site by
    universal convention. Off, `blog.example.com` and `shop.example.com` are followed too.
    Off by choice rather than default because subdomains are usually separate applications,
    and quietly following them turns a bounded crawl into an unbounded one. A redirect is
    not a scope question: a short link that lands on the real host is scoped to where it
    landed."""

    sitemap_limit: int = config.CRAWL_SITEMAP_LIMIT
    respect_robots: bool = config.CRAWL_RESPECT_ROBOTS

    remove_chrome: bool = config.CRAWL_REMOVE_CHROME
    """Emit `content_markdown` -- the page with landmarks, site chrome and boilerplate
    removed -- alongside the full Markdown. See `webgraph.content`.

    Landmarks apply from the first page. Cross-page chrome needs several pages to exist
    before it can say anything and is applied from then on. Costs nothing at crawl time --
    it is computed from blocks already extracted."""

    main_content: bool = config.CRAWL_MAIN_CONTENT
    """Also draw the main-content boundary (`webgraph.main_content`) when producing
    `content_markdown`. Off, the structural steps alone run: for a crawl whose pages are
    link hubs by design, where the list of links *is* the content."""

    strategy: Strategy | None = Strategy(config.CRAWL_STRATEGY) if config.CRAWL_STRATEGY else None
    """Overrides the strategy Stage 0 recommends. Leave unset to use the measured verdict."""

    fetch: FetchConfig = field(default_factory=FetchConfig)
    render: RenderConfig = field(default_factory=RenderConfig)

def resolve_root(root: str, *, config: FetchConfig | None = None) -> str:
    """Follow redirects from `root` and return the URL the site actually serves.

    Scoping to the requested URL rather than the landed one silently kills a crawl when the
    two differ in host. `docs.pydantic.dev/latest/` redirects to
    `pydantic.dev/docs/validation/latest/get-started/`; every link on the destination was
    then rejected as off-site (`docs.` is a subdomain, and subdomains are excluded by
    default), and the crawl finished after 2 pages on a site with hundreds.

    Falls back to the requested URL when the fetch fails -- an unreachable root is a
    separate problem, reported elsewhere.
    """
    normalized = normalize_url(root)
    if normalized is None:
        return root
    result = fetch_static(normalized, config=config)
    if not result.ok:
        return normalized
    landed = normalize_url(result.url)
    return landed or normalized


@dataclass(frozen=True, slots=True)
class PageInventory:
    """What pages a site has, separating what it claims from what actually responds."""

    advertised: tuple[str, ...] = ()
    live: tuple[str, ...] = ()
    dead: tuple[tuple[str, int], ...] = ()
    source: str = "none"
    """`sitemap`, `crawl`, or `sitemap+crawl`."""

    verified: bool = False
    from_sitemap: int = 0
    from_crawl: int = 0
    """How many URLs each discovery source contributed, before deduplication."""

    checked_count: int = 0
    """How many advertised URLs were actually probed. Large sitemaps are sampled rather than
    fully verified, and liveness must be reported against this number -- dividing live pages
    by the full advertised count reported 1% for a site whose sampled pages were 97% healthy."""

    @property
    def advertised_count(self) -> int:
        return len(self.advertised)

    @property
    def live_count(self) -> int:
        return len(self.live)

    @property
    def dead_count(self) -> int:
        return len(self.dead)

    @property
    def liveness(self) -> float:
        """Share of *checked* URLs that responded, not of all advertised ones."""
        return self.live_count / self.checked_count if self.checked_count else 0.0

    @property
    def fully_verified(self) -> bool:
        return self.checked_count >= self.advertised_count


@dataclass(frozen=True, slots=True)
class PageExtraction:
    url: str
    document: Document | None = None
    facts: dict[str, Fact] = field(default_factory=dict)
    error: str | None = None
    text_chars: int = 0
    strategy: Strategy | None = None

    markdown: str = ""
    """Structure-preserving output: headings, images, tables, code, in reading order."""

    content_markdown: str = ""
    """The same page reduced to its content -- see `webgraph.content.select_content`. Empty
    when nothing was removed, so a consumer need not hold two copies of one page; never a
    substitute for `markdown`, always an addition to it."""

    content_methods: tuple[str, ...] = ()
    """Which steps produced `content_markdown`: any of `landmarks`, `main-landmark`,
    `site-chrome`, `block-model`, `main-content`. Empty when it is empty."""

    page_type: str = "unknown"
    """What kind of page this is, from `webgraph.pagetype`. Reported so a consumer can group
    a crawl by page type; nothing in extraction branches on it."""

    page_type_confidence: float = 0.0

    page_type_reasons: tuple[tuple[str, float], ...] = ()
    """Why that type, strongest first: `(what it says, how much it was worth)`. Measured by
    withholding each signal from the model, not narrated."""

    page_type_runner_up: tuple[str, float] = ("", 0.0)
    """The type it nearly chose. Most of what "how sure" means is what came second."""

    images: tuple[str, ...] = ()
    tables: int = 0
    title: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and self.document is not None


@dataclass(frozen=True, slots=True)
class SiteEntity:
    """One distinct structured-data entity, with every page that published it."""

    entity_type: str
    data: dict[str, Any]
    source_pages: tuple[str, ...]

    @property
    def page_count(self) -> int:
        return len(self.source_pages)


@dataclass(frozen=True, slots=True)
class SiteExtraction:
    root: str
    analysis: SiteAnalysis
    inventory: PageInventory
    pages: tuple[PageExtraction, ...]
    entities: tuple[SiteEntity, ...]
    site_facts: dict[str, tuple[Any, ...]]
    """Schema path -> every distinct value found across the site."""

    fact_sources: dict[str, tuple[str, ...]]
    """Schema path -> the pages that contributed a value for it."""

    schema_supplied: bool = False
    duration_seconds: float = 0.0

    @property
    def successful(self) -> tuple[PageExtraction, ...]:
        return tuple(p for p in self.pages if p.ok)

    @property
    def total_chars(self) -> int:
        return sum(p.text_chars for p in self.pages)

    def report(self) -> str:
        lines: list[str] = []
        lines.append("=" * 70)
        lines.append(f"SITE EXTRACTION  {self.root}")
        lines.append("=" * 70)

        lines.append("")
        lines.append("  STAGE 0 - TECHNOLOGY")
        lines.append(f"    Frameworks       {', '.join(self.analysis.frameworks) or 'none detected'}")
        lines.append(f"    Strategy         {self.analysis.recommended_strategy.value}")
        if self.analysis.render_required:
            lines.append("    Rendering        REQUIRED (static HTML incomplete)")
        if self.analysis.render_loses_content:
            lines.append("    Warning          rendering drops content the static HTML has")

        inv = self.inventory
        lines.append("")
        lines.append("  STAGE 1 - PAGE INVENTORY")
        lines.append(f"    Source           {inv.source}")
        if inv.from_sitemap or inv.from_crawl:
            lines.append(
                f"    Discovered       {inv.from_sitemap} from sitemap, "
                f"{inv.from_crawl} by following links"
            )
        lines.append(f"    Advertised       {inv.advertised_count}")
        if inv.verified:
            scope = "all" if inv.fully_verified else f"sampled {inv.checked_count}"
            lines.append(f"    Checked          {inv.checked_count}  ({scope})")
            lines.append(f"    Live             {inv.live_count}")
            lines.append(f"    Dead (4xx/5xx)   {inv.dead_count}")
            if inv.checked_count:
                lines.append(f"    Liveness         {inv.liveness:.0%} of checked")
            if inv.dead_count:
                lines.append("    NOTE: the sitemap advertises pages that no longer exist.")
            if not inv.fully_verified:
                lines.append(
                    f"    NOTE: {inv.advertised_count} URLs advertised; only the first "
                    f"{inv.checked_count} were probed. Site is larger than this run."
                )
        else:
            lines.append("    Live             not verified")

        lines.append("")
        lines.append("  STAGES 2-3 - EXTRACTION")
        lines.append(f"    Pages fetched    {len(self.successful)}/{len(self.pages)}")
        lines.append(f"    Text extracted   {self.total_chars} chars")
        failed = [p for p in self.pages if not p.ok]
        if failed:
            lines.append(f"    Failed           {len(failed)}")
            for page in failed[:5]:
                lines.append(f"      {page.error} :: {page.url}")

        lines.append("")
        lines.append("  STAGE 4 - AGGREGATION")
        lines.append(f"    Distinct entities  {len(self.entities)}")
        for entity in self.entities[:10]:
            keys = ", ".join(list(entity.data)[:5])
            lines.append(f"      {entity.entity_type:<22} on {entity.page_count:>3} pages  [{keys}]")

        if self.site_facts:
            lines.append("")
            lines.append(f"    Schema fields found  {len(self.site_facts)}")
            for path, values in sorted(self.site_facts.items()):
                shown = ", ".join(repr(v)[:40] for v in values[:3])
                extra = f" (+{len(values) - 3} more)" if len(values) > 3 else ""
                pages = len(self.fact_sources.get(path, ()))
                lines.append(f"      {path:<24} {shown}{extra}  [{pages} pages]")
        elif self.schema_supplied:
            lines.append("")
            lines.append("    Schema fields found  0")
            lines.append("      No page published structured data matching the schema.")
            lines.append("      The page text was extracted; mapping prose to schema fields")
            lines.append("      requires the model extraction path.")
        else:
            lines.append("")
            lines.append("    No schema supplied -- pass --schema to map fields.")
            lines.append("      Entities above are the raw structured data each page published.")

        lines.append("")
        lines.append(f"  Completed in {self.duration_seconds:.1f}s")
        return "\n".join(lines)


def verify_inventory(
    urls: Iterable[str], *, concurrency: int = 8, config: FetchConfig | None = None
) -> tuple[tuple[str, ...], tuple[tuple[str, int], ...]]:
    """Split advertised URLs into live and dead.

    Uses a normal GET rather than HEAD: many servers answer HEAD incorrectly or not at all,
    and a wrong liveness verdict is worse than the bandwidth saved.
    """
    candidates = [u for u in dict.fromkeys(urls) if u]
    if not candidates:
        return (), ()

    def check(url: str) -> tuple[str, int, bool]:
        result = fetch_static(url, config=config)
        return url, result.status, result.ok and result.is_html

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(check, candidates))

    live = tuple(url for url, _status, ok in results if ok)
    dead = tuple((url, status) for url, status, ok in results if not ok)
    return live, dead


def build_inventory(
    root: str, *, config: SiteConfig | None = None, probe: SiteProbe | None = None
) -> PageInventory:
    """Stage 1: enumerate the site's pages from every available source, then verify.

    **Both** the sitemap and link-following are used, always, and their results unioned.
    Neither is sufficient alone, measured on ionidea.com:

    - its sitemap advertises 89 URLs, most of which 404 -- *stale*;
    - its homepage links to live pages the sitemap never mentions, such as
      `insurance-agentology.php` -- *incomplete*.

    An earlier version crawled only when a sitemap was absent, and therefore trusted a
    broken sitemap and found 4 pages where the site actually serves dozens.
    """
    config = config or SiteConfig()
    policy: RobotsPolicy
    if probe is not None and probe.analysis.reachable and probe.policy is not None:
        # Stage 0 already followed the redirect, read robots.txt and walked the sitemaps.
        root = probe.analysis.root
        policy = probe.policy
        sitemap_pages: Iterable[str] = probe.sitemap_pages
    else:
        root = resolve_root(root, config=config.fetch)
        policy = load_robots(root, config=config.fetch)
        sitemap_pages = discover_sitemap_urls(root, policy=policy, config=config.fetch)

    candidates: list[str] = []
    seen: set[str] = set()

    def add(urls: Iterable[str]) -> int:
        added = 0
        for url in urls:
            normalized = normalize_url(url)
            if normalized and normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)
                added += 1
        return added

    from_sitemap = add(sitemap_pages)

    from_crawl = 0
    if config.follow_links:
        from_crawl = add(
            discover_by_crawling(
                root,
                max_urls=config.discovery_limit,
                max_depth=config.max_depth,
                allow_subdomains=not config.strict_domain,
                concurrency=config.concurrency,
                config=config.fetch,
                policy=policy,
                delay_seconds=config.delay_seconds / 3,
            )
        )

    if from_sitemap and from_crawl:
        source = "sitemap+crawl"
    elif from_sitemap:
        source = "sitemap"
    elif from_crawl:
        source = "crawl"
    else:
        source = "none"

    if not candidates:
        return PageInventory(source=source)

    if not config.verify_inventory:
        return PageInventory(
            advertised=tuple(candidates),
            live=tuple(candidates),
            source=source,
            verified=False,
            checked_count=0,
            from_sitemap=from_sitemap,
            from_crawl=from_crawl,
        )

    # Verify enough to fill the page budget with headroom for dead URLs.
    to_check = candidates[: max(config.max_pages * 4, 40)]
    live, dead = verify_inventory(
        to_check, concurrency=config.concurrency, config=config.fetch
    )
    return PageInventory(
        advertised=tuple(candidates),
        live=live,
        dead=dead,
        source=source,
        verified=True,
        checked_count=len(to_check),
        from_sitemap=from_sitemap,
        from_crawl=from_crawl,
    )


def _page_from_resolved(resolved: ResolvedPage, schema: dict[str, Any] | None) -> PageExtraction:
    """Everything a crawl records about one page, from a page already resolved.

    Split from `_extract_one` so the root -- which Stage 0 has already fetched both ways --
    goes through exactly the same accounting as every other page instead of being fetched
    a second time to reach it.
    """
    document = resolved.document
    facts: dict[str, Fact] = {}
    if schema:
        facts = merge_facts(extract_facts(document.structured_data, schema, document.url))

    markdown = to_markdown(document, options=MarkdownOptions())
    images = tuple(
        b.href for b in document.blocks if b.kind is BlockKind.IMAGE and b.href
    )
    tables = sum(1 for b in document.blocks if b.kind is BlockKind.TABLE)
    heading = next(
        (b.text for b in document.blocks if b.kind is BlockKind.HEADING and b.level <= 2),
        "",
    ) or _page_title(document)

    router = default_router()
    routing = router.route(document, explain=True) if router is not None else None

    return PageExtraction(
        url=document.url,
        document=document,
        facts=facts,
        text_chars=len(document.text),
        strategy=resolved.strategy,
        markdown=markdown,
        images=images,
        tables=tables,
        title=heading,
        page_type=str(routing.page_type) if routing else "unknown",
        page_type_confidence=round(routing.confidence, 4) if routing else 0.0,
        page_type_reasons=(
            tuple((r.says, round(r.weight, 4)) for r in routing.reasons) if routing else ()
        ),
        page_type_runner_up=(
            (routing.runner_up[0], round(routing.runner_up[1], 4)) if routing else ("", 0.0)
        ),
    )


def _extract_one(
    url: str, schema: dict[str, Any] | None, strategy: Strategy, config: SiteConfig
) -> PageExtraction:
    try:
        resolved = resolve_page(
            url,
            strategy=strategy,
            fetch_config=config.fetch,
            render_config=config.render,
        )
    except PageMissingError as exc:
        return PageExtraction(url=url, error=f"HTTP {exc.status}")
    except ValueError as exc:
        return PageExtraction(url=url, error=str(exc))
    return _page_from_resolved(resolved, schema)


def _without_html(page: PageExtraction) -> PageExtraction:
    """The same page, minus the markup it was built from.

    The HTML is read exactly once after extraction -- for links -- and is the largest thing
    a page carries by an order of magnitude: on a 2 MB Wikipedia article the blocks hold
    1.1 MB, the HTML 2.1 MB, and a crawl that keeps every page's HTML for the aggregation at
    the end holds the whole site in memory to compute a handful of entity counts. The blocks
    stay, because chrome detection and aggregation read them; the markup goes.
    """
    if page.document is None or not page.document.html:
        return page
    return replace(page, document=page.document.model_copy(update={"html": ""}))


def _content_of(
    page: PageExtraction, chrome: SiteChrome | None, config: SiteConfig
) -> tuple[str, ContentSelection | None]:
    """`content_markdown` for one page, and the selection that produced it."""
    if not config.remove_chrome or page.document is None:
        return "", None
    # The page's own type decides how the boundary is drawn. On a listing this is the whole
    # result rather than a refinement: Hacker News's front page returns its *footer* under the
    # prose boundary (1 block of 94, no stories) and all 30 stories under the listing policy,
    # because a page whose content is links reads as navigation to a prose-seeking selector.
    selection = select_content(
        page.document.blocks,
        chrome=chrome,
        main_content=config.main_content,
        config=policy_for(page.page_type),
        title=page.document.title,
    )
    if not selection.changed:
        return "", selection
    markdown = to_markdown(
        page.document.model_copy(update={"blocks": tuple(selection.blocks)}),
        options=MarkdownOptions(),
    )
    return markdown, selection


def _chrome_for(pages: Iterable[PageExtraction], config: SiteConfig) -> SiteChrome | None:
    """Cross-page chrome, once enough pages exist to say anything; None before that."""
    if not config.remove_chrome:
        return None
    documents = [p.document for p in pages if p.document is not None]
    if len(documents) < MIN_CHROME_PAGES:
        return None
    return detect_site_chrome([d.blocks for d in documents])


_ENTITY_SOURCES: Final[frozenset[PayloadSource]] = frozenset(
    {PayloadSource.JSON_LD, PayloadSource.MICRODATA}
)
"""The payload sources whose nodes are entities: schema.org, however it is serialised."""


def _page_title(document: Document) -> str:
    """The `<title>` with the site's own name removed, for a page with no heading.

    Many app-shell pages have no `<h1>` at all, and a row that reads `/privacy-policy` when
    the page calls itself "Privacy Policy" is a row the reader has to decode. The site name
    is stripped only where Open Graph states it: guessing at what follows a pipe would
    mangle any title that contains one.
    """
    title = document.title.strip()
    if not title:
        return ""
    site = ""
    for payload in document.structured_data:
        if payload.source is PayloadSource.OPEN_GRAPH and isinstance(payload.data, dict):
            site = str(payload.data.get("og:site_name") or "").strip()
            break
    if site:
        for separator in (" | ", " - ", " \u2013 ", " \u2014 ", " :: ", " \u00b7 "):
            if title.endswith(separator + site) and len(title) > len(separator + site):
                return title[: -len(separator + site)].strip()
            if title.startswith(site + separator) and len(title) > len(site + separator):
                return title[len(site + separator):].strip()
    return title


def _aggregate_entities(pages: Iterable[PageExtraction]) -> tuple[SiteEntity, ...]:
    """Collapse structured payloads across pages into distinct entities.

    Identity is the payload's content. The same `Organization` block on 90 pages is one
    entity that appeared 90 times, not 90 entities -- which is the whole point of doing this
    at site level rather than per page.
    """
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    data_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for page in pages:
        if page.document is None:
            continue
        for payload in page.document.structured_data:
            if not isinstance(payload.data, dict):
                continue
            # Only vocabularies that describe *things*. A hydration payload (`__NEXT_DATA__`,
            # `__INITIAL_STATE__`) is the page's own state and differs on every page, so
            # keying it by content produced ten "initial-state" entities on ten pages of one
            # site -- one per page, each seen once, which is the opposite of what a site-level
            # summary is for. Open Graph is page metadata for the same reason.
            if payload.source not in _ENTITY_SOURCES:
                continue
            entity_type = str(payload.data.get("@type") or payload.source.value)
            fingerprint = repr(sorted(payload.data.items()))
            key = (entity_type, fingerprint)
            grouped[key].append(page.url)
            data_by_key.setdefault(key, payload.data)

    entities = [
        SiteEntity(
            entity_type=entity_type,
            data=data_by_key[key],
            source_pages=tuple(dict.fromkeys(urls)),
        )
        for key, urls in grouped.items()
        for entity_type, _ in [key]
    ]
    return tuple(sorted(entities, key=lambda e: (-e.page_count, e.entity_type)))


def extract_site(
    root: str,
    *,
    schema: dict[str, Any] | None = None,
    config: SiteConfig | None = None,
) -> SiteExtraction:
    """Run the full pipeline: analyse, enumerate, fetch every page, aggregate."""
    config = config or SiteConfig()
    started = time.monotonic()

    normalized_root = normalize_url(root)
    if normalized_root is None:
        raise ValueError(f"not a crawlable URL: {root}")

    probe = probe_site(normalized_root, fetch_config=config.fetch, render_config=config.render)
    analysis = probe.analysis
    if analysis.reachable:
        normalized_root = analysis.root
    strategy = config.strategy or analysis.recommended_strategy

    inventory = build_inventory(normalized_root, config=config, probe=probe)

    targets = [u for u in inventory.live if u != normalized_root][: max(config.max_pages - 1, 0)]

    with ThreadPoolExecutor(max_workers=max(1, config.concurrency)) as pool:
        others = list(pool.map(lambda u: _extract_one(u, schema, strategy, config), targets))

    # The root was fetched by Stage 0; it is the first page, not a fourth fetch of one URL.
    first = (
        _page_from_resolved(probe.resolved, schema)
        if probe.resolved is not None
        else _extract_one(normalized_root, schema, strategy, config)
    )
    pages = [_without_html(first), *(_without_html(p) for p in others)]

    chrome = _chrome_for(pages, config)
    pages = [
        replace(page, content_markdown=markdown, content_methods=selection.methods)
        if selection is not None and markdown
        else page
        for page in pages
        for markdown, selection in [_content_of(page, chrome, config)]
    ]

    entities = _aggregate_entities(pages)

    site_facts: dict[str, list[Any]] = defaultdict(list)
    fact_sources: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        for path, fact in page.facts.items():
            if fact.value not in site_facts[path]:
                site_facts[path].append(fact.value)
            fact_sources[path].append(page.url)

    return SiteExtraction(
        root=normalized_root,
        analysis=analysis,
        inventory=inventory,
        pages=tuple(pages),
        entities=entities,
        site_facts={k: tuple(v) for k, v in site_facts.items()},
        fact_sources={k: tuple(dict.fromkeys(v)) for k, v in fact_sources.items()},
        schema_supplied=schema is not None,
        duration_seconds=time.monotonic() - started,
    )


@dataclass(frozen=True, slots=True)
class _Fetched:
    """One page as the crawl loop consumes it: extracted, with its links already read."""

    page: PageExtraction
    depth: int
    links: list[str]
    canonical: str | None
    anchored: list[tuple[str, str]]
    requested: str


def _fetched(page: PageExtraction, depth: int, requested: str, root: str) -> _Fetched:
    """Read a page's links, then let go of its HTML -- the only thing that needed it."""
    links: list[str] = []
    anchored: list[tuple[str, str]] = []
    canonical: str | None = None
    if page.document is not None and page.document.html:
        found = extract_links(page.document.html, page.url)
        links = [reconcile_scheme(link, root) for link in found.links]
        anchored = [(reconcile_scheme(href, root), text) for href, text in found.anchored]
        canonical = found.canonical
    return _Fetched(_without_html(page), depth, links, canonical, anchored, requested)


def stream_site(
    root: str,
    *,
    schema: dict[str, Any] | None = None,
    config: SiteConfig | None = None,
    should_stop: Callable[[], bool] | None = None,
    builder: GraphBuilder | None = None,
) -> Iterator[dict[str, Any]]:
    """Crawl and extract continuously, yielding an event per page as it completes.

    Discovery and extraction are **interleaved**, not sequential. Enumerating an entire site
    before extracting anything means staring at no output for minutes on a large site, and it
    caps the crawl at whatever the sitemap happens to list. Here each extracted page's links
    extend the frontier, so the crawl reaches everything reachable and the first result
    arrives in seconds.

    With `max_pages = 0` the crawl is unbounded: it runs until the frontier is exhausted.
    Politeness still applies -- robots.txt, its Crawl-delay, and a bounded worker pool.

    Events carry a `type`: `stage`, `analysis`, `frontier`, `fetching`, `page`, `warning`, `done`,
    `error`.

    `builder`, when supplied, is filled in as pages arrive. It belongs to the caller rather
    than being returned, because a generator has no way to hand back an object mid-stream and
    the graph is most useful *during* a long crawl -- and remains useful after a stopped one.

    `should_stop` is polled between batches. A generator cannot be interrupted from another
    thread -- closing it only raises at the next `yield`, which never arrives while a batch
    of renders is in flight -- so an abandoned crawl needs a flag it checks itself. Without
    one, a client that disconnects leaves a full-speed crawl running for the life of the
    process, and a handful of those is enough to starve every later request.

    The root is fetched **once**. Stage 0 resolves it both ways to measure the site, and
    that resolved page is the crawl's first result rather than being discarded and fetched
    again. Before this the root cost three static fetches and two renders per crawl.
    """
    config = config or SiteConfig()
    started = time.monotonic()

    normalized_root = normalize_url(root)
    if normalized_root is None:
        yield {"type": "error", "message": f"not a crawlable URL: {root}"}
        return

    yield {"type": "stage", "stage": "analyze", "message": "Detecting technology stack"}

    probe = probe_site(
        normalized_root,
        fetch_config=config.fetch,
        render_config=config.render,
        sitemap_limit=config.sitemap_limit,
    )
    analysis = probe.analysis
    if not analysis.reachable or probe.resolved is None or probe.policy is None:
        yield {"type": "error", "message": analysis.error or "site unreachable"}
        return

    # Scope on the URL the site actually serves, not the one requested. A cross-host
    # redirect otherwise rejects every link as off-site.
    if analysis.root != normalized_root:
        yield {"type": "stage", "stage": "analyze", "message": f"Redirected to {analysis.root}"}
        normalized_root = analysis.root

    strategy = config.strategy or analysis.recommended_strategy
    yield {
        "type": "analysis",
        "root": analysis.root,
        "frameworks": list(analysis.frameworks),
        "technologies": [dict(t) for t in analysis.technologies],
        "payload_sources": list(analysis.payload_sources),
        "render_required": analysis.render_required,
        "render_loses_content": analysis.render_loses_content,
        "static_chars": analysis.static_chars,
        "rendered_chars": analysis.rendered_chars,
        "union_chars": analysis.union_chars,
        "static_coverage": round(analysis.static_coverage, 4),
        "strategy": strategy.value,
    }

    yield {"type": "stage", "stage": "enumerate", "message": "Seeding from sitemap"}

    policy = probe.policy
    scope = CrawlScope(
        root=normalized_root,
        max_depth=config.max_depth,
        allow_subdomains=not config.strict_domain,
    )
    frontier = Frontier(scope=scope)
    frontier.mark_seen(normalized_root)
    # The root is the one page nothing pointed at. Recorded so every page in the crawl has a
    # citation, including the one the crawl began from.
    frontier.origin.setdefault(
        normalized_root, Discovery(url=normalized_root, via="seed", depth=0)
    )
    # The root is the one page nothing pointed at. Recorded so every page in the crawl has a
    # citation, including the one the crawl began from.
    frontier.origin.setdefault(
        normalized_root, Discovery(url=normalized_root, via="seed", depth=0)
    )
    seeded = frontier.extend(list(probe.sitemap_pages), 1, via="sitemap", found_on=analysis.root)

    yield {
        "type": "frontier",
        "queued": len(frontier),
        "discovered": frontier.seen_count,
        "depth_counts": frontier.depth_counts(),
        "from_sitemap": len(seeded),
        "extracted": 0,
        # The root plus everything the sitemap contributed. Clients rebuild the discovered
        # set from these deltas rather than being sent the whole frontier each time.
        "new_urls": [normalized_root, *seeded],
    }

    unlimited = config.max_pages <= 0
    budget = float("inf") if unlimited else config.max_pages

    yield {
        "type": "stage",
        "stage": "extract",
        "message": "Crawling and extracting" + ("" if unlimited else f" up to {config.max_pages} pages"),
        "unlimited": unlimited,
    }

    delay = max(config.delay_seconds, policy.crawl_delay or 0.0)
    chrome: SiteChrome | None = None
    extracted = 0
    failed = 0
    # Content hash -> the URLs that produced it. A crawl where many distinct URLs yield the
    # same text is not extracting a site; it is extracting one gate, repeatedly.
    by_content: dict[str, list[str]] = defaultdict(list)
    identical_warned: set[str] = set()
    totals = {"chars": 0, "markdown": 0, "images": 0, "tables": 0}
    all_pages: list[PageExtraction] = []

    def work(item: tuple[str, int]) -> _Fetched:
        url, depth = item
        if delay > 0:
            time.sleep(delay)
        page = _extract_one(url, schema, strategy, config)
        return _fetched(page, depth, url, normalized_root)

    # The root is already in hand. It is the first batch, at no cost.
    pending: list[_Fetched] = [
        _fetched(_page_from_resolved(probe.resolved, schema), 0, normalized_root, normalized_root)
    ]
    stopped = False

    with ThreadPoolExecutor(max_workers=max(1, config.concurrency)) as pool:
        while extracted + failed < budget and (pending or len(frontier) > 0):
            if should_stop is not None and should_stop():
                stopped = True
                break

            if pending:
                results: Iterable[_Fetched] = pending
                pending = []
            else:
                batch: list[tuple[str, int]] = []
                while len(frontier) > 0 and len(batch) < config.concurrency:
                    if extracted + failed + len(batch) >= budget:
                        break
                    item = frontier.pop()
                    if item is None:
                        break
                    if config.respect_robots and not policy.allows(
                        item[0], config.fetch.user_agent
                    ):
                        continue
                    batch.append(item)
                if not batch:
                    break
                # Say what is going out *before* it goes, so a consumer can show work in
                # flight rather than only work finished. Without this the only observable
                # events are completions, and a live view can show a history and nothing
                # else -- there is no way to know a page is being fetched right now.
                yield {
                    "type": "fetching",
                    "urls": [url for url, _ in batch],
                    "queued": len(frontier),
                    "extracted": extracted,
                    "failed": failed,
                }
                results = pool.map(work, batch)

            for fetched in results:
                page = fetched.page
                depth = fetched.depth
                if page.ok:
                    extracted += 1
                    totals["chars"] += page.text_chars
                    totals["markdown"] += len(page.markdown)
                    totals["images"] += len(page.images)
                    totals["tables"] += page.tables
                else:
                    failed += 1
                all_pages.append(page)

                # The graph is built as the crawl runs, not afterwards. A crawl streams for
                # minutes; a graph that only exists once it finishes is unavailable during
                # the only period anyone is watching, and is lost entirely if it is stopped.
                if builder is not None and page.document is not None:
                    builder.add(
                        page.document,
                        depth=depth,
                        title=page.title,
                        anchored_links=fetched.anchored,
                        # Other sites link to the address they know, which is often the one
                        # that redirected here rather than the URL finally served.
                        requested_url=fetched.requested,
                        canonical_url=fetched.canonical,
                    )

                # Each page extends the frontier, which is what makes the crawl unbounded.
                discovered_here = frontier.extend(
                    fetched.links,
                    depth + 1,
                    base=fetched.canonical or page.url,
                    found_on=page.url,
                    via="link",
                    # The words a reader would have clicked. Often the only human-readable
                    # reason a link was followed, and the difference between "we crawled this
                    # because something pointed at it" and a citation.
                    anchors=dict(fetched.anchored),
                )

                # Chrome is knowable only once several pages exist. Compute it the first
                # time that is true, then reuse it -- recomputing per page would be
                # quadratic for no benefit, since the answer stabilises immediately.
                if chrome is None:
                    chrome = _chrome_for(all_pages, config)

                content_md, selection = _content_of(page, chrome, config)

                if page.ok and page.document is not None and page.text_chars:
                    group = by_content[page.document.content_hash]
                    if page.url not in group:
                        group.append(page.url)
                    if (
                        len(group) >= IDENTICAL_CONTENT_WARNING
                        and page.document.content_hash not in identical_warned
                    ):
                        identical_warned.add(page.document.content_hash)
                        yield {
                            "type": "warning",
                            "code": "identical-content",
                            "message": (
                                f"{len(group)} URLs returned byte-identical content "
                                f"({page.text_chars} chars). The site is probably serving an "
                                "interstitial the engine could not open -- a login, a consent "
                                "wall, or a gate that blocks the page from mounting."
                            ),
                            "urls": list(group),
                            "chars": page.text_chars,
                        }

                elapsed = max(time.monotonic() - started, 0.001)
                yield {
                    "type": "page",
                    "index": extracted + failed,
                    "url": page.url,
                    # How this address entered the crawl: which page, by what method, and
                    # through which link text. "Could not fetch X" is not actionable without
                    # it -- the next question is always what pointed at X, and only the
                    # frontier ever knew.
                    "citation": (
                        citation.as_dict()
                        if (citation := frontier.citation(fetched.requested)) is not None
                        else None
                    ),
                    "title": page.title,
                    "ok": page.ok,
                    "error": page.error,
                    "depth": depth,
                    "chars": page.text_chars,
                    "markdown": page.markdown,
                    "content_markdown": content_md,
                    "content_blocks": selection.kept if selection is not None else None,
                    "content_methods": list(selection.methods) if selection is not None else [],
                    "page_type": page.page_type,
                    "page_type_confidence": page.page_type_confidence,
                    "page_type_reasons": [
                        {"says": says, "weight": weight} for says, weight in page.page_type_reasons
                    ],
                    "page_type_runner_up": {
                        "type": page.page_type_runner_up[0],
                        "confidence": page.page_type_runner_up[1],
                    },
                    "blocks": len(page.document.blocks) if page.document is not None else 0,
                    "images": list(page.images),
                    "tables": page.tables,
                    "strategy": page.strategy.value if page.strategy else None,
                    "queued": len(frontier),
                    "discovered": frontier.seen_count,
                    "depth_counts": frontier.depth_counts(),
                    "extracted": extracted,
                    "failed": failed,
                    "newly_queued": len(discovered_here),
                    "new_urls": discovered_here,
                    "pages_per_minute": round(60 * (extracted + failed) / elapsed, 1),
                    "totals": dict(totals),
                    "graph": builder.graph.describe() if builder is not None else None,
                }

    entities = _aggregate_entities(all_pages)

    site_facts: dict[str, list[Any]] = defaultdict(list)
    fact_sources: dict[str, list[str]] = defaultdict(list)
    for page in all_pages:
        for path, fact in page.facts.items():
            if fact.value not in site_facts[path]:
                site_facts[path].append(fact.value)
            fact_sources[path].append(page.url)

    yield {
        "type": "done",
        "pages_ok": extracted,
        "pages_total": extracted + failed,
        "failed": failed,
        "discovered": frontier.seen_count,
        "remaining_queued": len(frontier) + len(pending),
        "exhausted": len(frontier) == 0 and not pending and not stopped,
        "stopped": stopped,
        "total_chars": totals["chars"],
        "total_markdown_chars": totals["markdown"],
        "total_images": totals["images"],
        "total_tables": totals["tables"],
        # The largest set of distinct URLs that produced identical text. 1 is healthy.
        "largest_identical_group": max((len(v) for v in by_content.values()), default=0),
        "identical_content_groups": [
            {"chars": len(k), "urls": v}
            for k, v in by_content.items()
            if len(v) >= IDENTICAL_CONTENT_WARNING
        ],
        "chrome_blocks": len(chrome.text.keys) if chrome else 0,
        "chrome_slots": len(chrome.slots) if chrome else 0,
        "entities": [
            {"type": e.entity_type, "pages": e.page_count, "keys": list(e.data)[:8]}
            for e in entities[:20]
        ],
        "site_facts": {k: [str(v) for v in vs] for k, vs in site_facts.items()},
        "fact_sources": {k: list(dict.fromkeys(v)) for k, v in fact_sources.items()},
        "graph": builder.graph.describe() if builder is not None else None,
        "duration_seconds": round(time.monotonic() - started, 1),
    }
