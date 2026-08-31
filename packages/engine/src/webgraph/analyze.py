"""Stage 0 site analysis: what is this site, and how big is it?

Answers the two questions that must come before any extraction:

1. **How is it built, and is its content server-rendered?** This decides the fetch strategy
   for every page that follows. Getting it wrong on the first page gets it wrong on all of them.
2. **How many public pages are there?** A crawl budget set without knowing the page count is
   a guess. Sitemaps give the real number when a site publishes one.

The render verdict here is *measured*, not predicted. The analyser fetches one page both
ways and compares, because heuristics scored 0/7 on partial content loss when tested against
real sites -- see `resolve.py`. One render at analysis time buys a verdict that applies to
the whole crawl.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from webgraph.crawl.discovery import RobotsPolicy, discover_sitemap_urls, load_robots
from webgraph.crawl.frontier import normalize_url
from webgraph.fetch.render import PLAYWRIGHT_AVAILABLE, RenderConfig
from webgraph.fetch.static import FetchConfig
from webgraph.profile.bundle import collect_bundle_source
from webgraph.profile.technology import (
    Technology,
    detect_technologies,
    merge_technologies,
)
from webgraph.resolve import PageMissingError, ResolvedPage, Strategy, resolve_page

__all__ = ["SiteAnalysis", "analyze_site"]


@dataclass(frozen=True, slots=True)
class SiteAnalysis:
    """What Stage 0 learned about a site."""

    root: str
    reachable: bool
    error: str | None = None

    frameworks: tuple[str, ...] = ()
    payload_sources: tuple[str, ...] = ()
    technologies: tuple[dict[str, Any], ...] = ()
    """Full technology profile: name, category, version, evidence."""

    static_chars: int = 0
    rendered_chars: int = 0
    union_chars: int = 0
    render_required: bool = False
    """Measured, not predicted: True when rendering revealed content the static fetch missed."""

    render_loses_content: bool = False
    """True when rendering *dropped* content -- a consent wall, paywall or lazy unmount."""

    robots_found: bool = False
    crawl_delay: float | None = None
    sitemap_urls: tuple[str, ...] = ()
    public_page_count: int | None = None
    """Pages advertised by the site's sitemaps. None when no sitemap was published, in which
    case the page count is unknown until a crawl discovers it by following links."""

    sample_pages: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def static_coverage(self) -> float:
        return min(self.static_chars / self.union_chars, 1.0) if self.union_chars else 0.0

    @property
    def recommended_strategy(self) -> Strategy:
        """The fetch strategy to use for this site's pages.

        UNION whenever either representation was shown to lose content. STATIC_ONLY only
        when a real comparison found the static HTML complete -- never on assumption.
        """
        if self.render_required or self.render_loses_content:
            return Strategy.UNION
        return Strategy.STATIC_ONLY

    def report(self) -> str:
        lines: list[str] = []
        lines.append("=" * 66)
        lines.append(f"SITE ANALYSIS  {self.root}")
        lines.append("=" * 66)

        if not self.reachable:
            lines.append(f"  UNREACHABLE: {self.error}")
            return "\n".join(lines)

        lines.append("")
        lines.append("  TECHNOLOGY")
        if self.technologies:
            current = None
            for tech in self.technologies:
                if tech["category"] != current:
                    current = tech["category"]
                    lines.append(f"    {current}")
                label = f"{tech['name']} {tech['version']}" if tech["version"] else tech["name"]
                lines.append(f"      {label}")
        else:
            lines.append("    none detected")
        lines.append(f"    Structured data   {', '.join(self.payload_sources) or 'none'}")

        lines.append("")
        lines.append("  RENDERING  (measured by fetching one page both ways)")
        lines.append(f"    Static HTML       {self.static_chars:>8} chars")
        lines.append(f"    Rendered          {self.rendered_chars:>8} chars")
        lines.append(f"    Union             {self.union_chars:>8} chars")
        lines.append(f"    Static coverage   {self.static_coverage:>8.1%}")
        if self.render_required:
            lines.append("    -> Rendering REQUIRED: static HTML is missing content")
        if self.render_loses_content:
            lines.append("    -> Rendering LOSES content: static HTML has text the render drops")
        if not self.render_required and not self.render_loses_content:
            lines.append("    -> Static HTML is complete for this page")
        if self.static_chars == 0 and self.rendered_chars > 0:
            lines.append("    -> Static fetch returned NOTHING (bot challenge or pure client render)")
        lines.append(f"    Strategy          {self.recommended_strategy.value}")

        lines.append("")
        lines.append("  SITE SIZE")
        lines.append(f"    robots.txt        {'found' if self.robots_found else 'not found'}")
        if self.crawl_delay:
            lines.append(f"    Crawl-delay       {self.crawl_delay}s")
        lines.append(f"    Sitemaps          {len(self.sitemap_urls)}")
        if self.public_page_count is None:
            lines.append("    Public pages      unknown (no sitemap; discoverable by crawling)")
        else:
            lines.append(f"    Public pages      {self.public_page_count}")

        if self.sample_pages:
            lines.append("")
            lines.append("  SAMPLE URLS")
            for url in self.sample_pages:
                lines.append(f"    {url}")

        if self.notes:
            lines.append("")
            lines.append("  NOTES")
            for note in self.notes:
                lines.append(f"    - {note}")

        return "\n".join(lines)


def analyze_site(
    root: str,
    *,
    fetch_config: FetchConfig | None = None,
    render_config: RenderConfig | None = None,
    sitemap_limit: int = 5000,
) -> SiteAnalysis:
    """Profile a site: technology, rendering behaviour, and public page count."""
    normalized = normalize_url(root)
    if normalized is None:
        return SiteAnalysis(root=root, reachable=False, error="not a crawlable URL")

    notes: list[str] = []

    try:
        resolved: ResolvedPage = resolve_page(
            normalized,
            strategy=Strategy.UNION if PLAYWRIGHT_AVAILABLE else Strategy.STATIC_ONLY,
            fetch_config=fetch_config,
            render_config=render_config,
        )
    except PageMissingError as exc:
        return SiteAnalysis(root=normalized, reachable=False, error=str(exc))
    except ValueError as exc:
        return SiteAnalysis(root=normalized, reachable=False, error=str(exc))

    if not PLAYWRIGHT_AVAILABLE:
        notes.append(
            "Playwright is not installed, so the render comparison was skipped. "
            "The rendering verdict below is unmeasured."
        )
    if resolved.render_error:
        notes.append(f"render failed: {resolved.render_error}")

    policy: RobotsPolicy = load_robots(normalized, config=fetch_config)
    sitemap_pages = discover_sitemap_urls(
        normalized, policy=policy, config=fetch_config, limit=sitemap_limit
    )

    origin = urlsplit(normalized).hostname or ""
    on_site = [url for url in sitemap_pages if origin in url]
    if len(on_site) < len(sitemap_pages):
        notes.append(
            f"{len(sitemap_pages) - len(on_site)} sitemap URLs point off-host and were excluded"
        )
    if len(sitemap_pages) >= sitemap_limit:
        notes.append(f"sitemap enumeration hit the {sitemap_limit}-URL cap; the site is larger")

    document = resolved.document

    # One more pass, with the site's own JavaScript in hand. Component libraries that mount
    # their attributes only on interaction -- Radix, shadcn -- leave no trace in the DOM, the
    # globals, the network log or the markup of a page that never opens one. They are named
    # in the bundle. This is affordable exactly once, here, and never per page.
    #
    # Merged rather than recomputed: the page profile already holds everything the headers
    # and the live page produced, and re-running the whole detector without them would trade
    # Cloudflare and HSTS for Radix.
    technologies = document.profile.technologies
    if resolved.runtime.present:
        source = collect_bundle_source(document.html, document.url, config=fetch_config)
        if source:
            from_page = [
                Technology(
                    name=str(entry["name"]),
                    category=str(entry["category"]),
                    version=entry["version"] if entry["version"] is None else str(entry["version"]),
                    confidence=int(entry["confidence"]),
                    evidence=str(entry["evidence"]),
                )
                for entry in technologies
            ]
            from_bundle = detect_technologies("", None, None, bundle_source=source)
            merged = merge_technologies(from_page, from_bundle)
            gained = len(merged) - len(from_page)
            technologies = tuple(
                {
                    "name": tech.name,
                    "category": tech.category,
                    "version": tech.version,
                    "confidence": tech.confidence,
                    "evidence": tech.evidence,
                }
                for tech in merged
            )
            if gained > 0:
                notes.append(f"{gained} further technologies identified from bundle source")

    return SiteAnalysis(
        root=normalized,
        reachable=True,
        frameworks=document.profile.frameworks,
        payload_sources=tuple(dict.fromkeys(p.source.value for p in document.structured_data)),
        technologies=technologies,
        static_chars=resolved.static_chars,
        rendered_chars=resolved.rendered_chars,
        union_chars=resolved.union_chars,
        # Derived from coverage, not only from the block delta. The block counts are zero
        # when the static fetch failed outright (nextjs.org blocks non-browser agents), and
        # reading them alone reported "static HTML is complete" for a page that yielded
        # nothing at all.
        render_required=(
            resolved.render_added_content
            or resolved.strategy is Strategy.RENDERED_ONLY
            or resolved.static_chars < resolved.union_chars
        ),
        render_loses_content=resolved.render_lost_content,
        robots_found=policy.fetched,
        crawl_delay=policy.crawl_delay,
        sitemap_urls=policy.sitemaps,
        public_page_count=len(on_site) if on_site else None,
        sample_pages=tuple(on_site[:8]),
        notes=tuple(notes),
    )
