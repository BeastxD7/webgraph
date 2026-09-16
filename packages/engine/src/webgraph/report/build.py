"""`build_site_report`: what a site shows people, what it shows machines, and how ready it
is for AI agents -- from the measurements the engine already makes.

One report is: the root probed both ways (`analyze.probe_site`: stack, robots.txt,
sitemaps), up to `pages` further pages resolved both ways (`resolve.resolve_page`), each
read for what the plain fetch missed, what was hidden and from whom, what was walled and
what was declared (`report.pages`); the robots.txt read for each well-known bot
(`report.bots`); what the site declares to machines -- `/llms.txt`, `Content-Signal`, RSL,
TDM, agent cards, feeds, JSON-LD, `security.txt` and the rest (`report.signals`); a score with its evidence (`report.score`); and a
suggested `robots.txt` and `llms.txt` (`report.suggest`).

What it refuses to do
---------------------
It never fetches as another bot. What GPTBot or Googlebot would be served is not measured
here and is not guessed at; the bots table is what the site's robots.txt *declares* for
each name, read as that bot would read it. The report's plain fetches identify themselves
as webgraph, its browser fetch is a real Chromium under its own User-Agent, and both obey
robots.txt like every other fetch the engine makes: a root the file
disallows for this client, or a root that is walled, ends the report with the engine's own
refusal and no score (`SiteReport.refusal`). The report's own requests -- the sampled
pages, `/llms.txt`, the link checks -- are spaced by `REPORT_REQUEST_INTERVAL_SECONDS`;
the root probe (root, robots.txt, sitemaps) is fetched as every crawl starts. A report is
a courtesy call, not a crawl.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from webgraph import config
from webgraph.analyze import probe_site
from webgraph.crawl.discovery import RobotsPolicy
from webgraph.fetch.render import PLAYWRIGHT_AVAILABLE, RenderConfig
from webgraph.fetch.static import FetchConfig
from webgraph.report.bots import BotPolicy, declared_policies
from webgraph.report.pages import (
    LinkChecker,
    Pacer,
    PageReport,
    internal_links,
    measure_page,
    section_of,
    site_host,
)
from webgraph.report.score import (
    Finding,
    SiteScore,
    integrity_findings,
    score_site,
)
from webgraph.report.signals import LlmsFile, Signals, collect_signals, read_llms_file
from webgraph.report.stack import StackEntry, stack_entries
from webgraph.report.suggest import (
    LLMS_TXT_NOTE,
    suggest_llms_txt,
    suggest_robots_txt,
    suggest_security_txt,
)
from webgraph.resolve import (
    PageBlockedError,
    PageDisallowedError,
    PageMissingError,
    Strategy,
    resolve_page,
)

__all__ = [
    "LlmsFile",
    "MeasuredHow",
    "RobotsReport",
    "SiteReport",
    "build_site_report",
    "choose_sample",
    "read_llms_file",
]

NO_IMPERSONATION: Final[str] = (
    "The engine never impersonates other bots. The plain fetches identified themselves as "
    "webgraph with a contact URL; the browser fetch was a real Chromium under its own "
    "User-Agent; nothing was fetched under another bot's name, and robots.txt was obeyed "
    "throughout. The bots table is what the site's robots.txt declares for each name, not "
    "what that bot would be served."
)

_ROBOTS_TEXT_CHARS: Final[int] = 8_000
_SITEMAP_LIMIT: Final[int] = 2_000


@dataclass(frozen=True, slots=True)
class RobotsReport:
    found: bool
    status: int
    text: str
    """The file as served, up to `_ROBOTS_TEXT_CHARS`."""
    group_for_us: str | None
    rules_for_us: tuple[str, ...]
    crawl_delay_for_us: float | None
    allows_us_root: bool
    sitemaps_declared: tuple[str, ...]
    bots: tuple[BotPolicy, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "status": self.status,
            "text": self.text,
            "group_for_us": self.group_for_us,
            "rules_for_us": list(self.rules_for_us),
            "crawl_delay_for_us": self.crawl_delay_for_us,
            "allows_us_root": self.allows_us_root,
            "sitemaps_declared": list(self.sitemaps_declared),
            "bots": [b.as_dict() for b in self.bots],
        }


@dataclass(frozen=True, slots=True)
class MeasuredHow:
    engine_version: str
    commit: str
    user_agent: str
    """The plain fetches' User-Agent. The browser fetch is Chromium under its own."""
    pages_requested: int
    pages_sampled: int
    request_interval_seconds: float
    duration_seconds: float
    render_available: bool
    statement: str = NO_IMPERSONATION

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine_version": self.engine_version,
            "commit": self.commit,
            "user_agent": self.user_agent,
            "pages_requested": self.pages_requested,
            "pages_sampled": self.pages_sampled,
            "request_interval_seconds": self.request_interval_seconds,
            "duration_seconds": round(self.duration_seconds, 1),
            "render_available": self.render_available,
            "statement": self.statement,
        }


@dataclass(frozen=True, slots=True)
class SiteReport:
    url: str
    """The root as requested."""
    root: str
    """The root as served, after redirects."""
    host: str
    generated_at: str
    reachable: bool
    refusal: str | None = None
    """The engine's own words when the root could not be read: walled, disallowed for this
    client, missing, unreachable. Set means no score and no pages."""
    stack: tuple[StackEntry, ...] = ()
    robots: RobotsReport | None = None
    sitemap_found: bool = False
    sitemap_urls: int = 0
    sitemap_attempts: tuple[dict[str, Any], ...] = ()
    llms_txt: LlmsFile | None = None
    llms_full_txt: LlmsFile | None = None
    signals: Signals | None = None
    """What the site declares to machines (`report.signals`): Content-Signal, llms.txt,
    RSL, TDM, agent cards, feeds, JSON-LD, security.txt ... each with who honours it."""
    pages: tuple[PageReport, ...] = ()
    score: SiteScore | None = None
    findings: tuple[Finding, ...] = ()
    suggested_robots_txt: str | None = None
    suggested_llms_txt: str | None = None
    suggested_security_txt: str | None = None
    llms_txt_note: str = LLMS_TXT_NOTE
    measured: MeasuredHow | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "root": self.root,
            "host": self.host,
            "generated_at": self.generated_at,
            "reachable": self.reachable,
            "refusal": self.refusal,
            "stack": [s.as_dict() for s in self.stack],
            "robots": self.robots.as_dict() if self.robots else None,
            "sitemap_found": self.sitemap_found,
            "sitemap_urls": self.sitemap_urls,
            "sitemap_attempts": list(self.sitemap_attempts),
            "llms_txt": self.llms_txt.as_dict() if self.llms_txt else None,
            "llms_full_txt": self.llms_full_txt.as_dict() if self.llms_full_txt else None,
            "signals": self.signals.as_dict() if self.signals else None,
            "pages": [p.as_dict() for p in self.pages],
            "score": self.score.as_dict() if self.score else None,
            "findings": [f.as_dict() for f in self.findings],
            "suggested_robots_txt": self.suggested_robots_txt,
            "suggested_llms_txt": self.suggested_llms_txt,
            "suggested_security_txt": self.suggested_security_txt,
            "llms_txt_note": self.llms_txt_note,
            "measured": self.measured.as_dict() if self.measured else None,
            "notes": list(self.notes),
        }


def engine_build() -> tuple[str, str]:
    """(version, commit) of the engine answering. The commit is `WEBGRAPH_COMMIT` when a
    deployment sets it, else the checkout's short SHA when the package runs from one,
    else `unknown` -- never a guess."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("webgraph")
    except PackageNotFoundError:
        installed = "unknown"
    commit = os.environ.get("WEBGRAPH_COMMIT", "").strip()
    if not commit:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path(__file__).resolve().parent,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            commit = out.stdout.strip() if out.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            commit = ""
    return installed, commit or "unknown"


def choose_sample(html: str, root_url: str, *, count: int, policy: RobotsPolicy | None = None) -> list[str]:
    """Up to `count` internal links from the root page to sample: one per path section
    first (`/admissions/…`, `/about`, `/blog/…`), in the order the page links to them, then
    the next links until the count is met. Links robots.txt disallows for this client are
    not chosen -- they would only be refused."""
    if count <= 0:
        return []
    root_key = root_url.rstrip("/")
    candidates: list[str] = []
    for link in internal_links(html, root_url):
        if link.rstrip("/") == root_key:
            continue
        if policy is not None and not policy.allows(link):
            continue
        candidates.append(link)
    # Prefer clean addresses: a query string usually names a variant of a page already chosen.
    candidates.sort(key=lambda u: bool(urlsplit(u).query))
    chosen: list[str] = []
    sections: set[str] = set()
    for link in candidates:
        section = section_of(link)
        if section in sections:
            continue
        sections.add(section)
        chosen.append(link)
        if len(chosen) >= count:
            return chosen
    for link in candidates:
        if link not in chosen:
            chosen.append(link)
            if len(chosen) >= count:
                break
    return chosen


def build_site_report(
    url: str,
    *,
    pages: int | None = None,
    fetch_config: FetchConfig | None = None,
    render_config: RenderConfig | None = None,
    today: date | None = None,
) -> SiteReport:
    """The report for the site at `url`. See the module docstring for what it does and
    refuses to do; `pages` is clamped to `1..REPORT_MAX_PAGES`."""
    started = time.monotonic()
    wanted = max(1, min(pages or config.REPORT_PAGES, config.REPORT_MAX_PAGES))
    fetch_config = fetch_config or FetchConfig()
    pacer = Pacer()
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    version, commit = engine_build()

    def measured(sampled: int) -> MeasuredHow:
        return MeasuredHow(
            engine_version=version,
            commit=commit,
            user_agent=fetch_config.user_agent,
            pages_requested=wanted,
            pages_sampled=sampled,
            request_interval_seconds=pacer.interval,
            duration_seconds=time.monotonic() - started,
            render_available=PLAYWRIGHT_AVAILABLE,
        )

    pacer.wait(url)
    probe = probe_site(
        url, fetch_config=fetch_config, render_config=render_config, sitemap_limit=_SITEMAP_LIMIT
    )
    analysis = probe.analysis
    if not analysis.reachable or probe.resolved is None or probe.policy is None:
        return SiteReport(
            url=url,
            root=analysis.root,
            host=site_host(analysis.root),
            generated_at=generated_at,
            reachable=False,
            refusal=analysis.error or "the root could not be read",
            measured=measured(0),
        )

    root = probe.resolved
    policy = probe.policy
    host = site_host(root.url)
    origin = f"{urlsplit(root.url).scheme}://{urlsplit(root.url).netloc}"
    notes = list(analysis.notes)

    robots = RobotsReport(
        found=policy.fetched,
        status=policy.status,
        text=policy.text[:_ROBOTS_TEXT_CHARS],
        group_for_us=policy.group,
        rules_for_us=policy.rules,
        crawl_delay_for_us=policy.crawl_delay,
        allows_us_root=policy.allows(root.url),
        sitemaps_declared=policy.sitemaps,
        bots=declared_policies(policy.text if policy.fetched else None),
    )
    sitemap_pages = {u.rstrip("/") for u in probe.sitemap_pages}
    sitemap_found = any(a.ok for a in probe.sitemap_attempts)

    # What the site declares to machines -- llms.txt among it -- fetched through the same
    # pacer, the same robots.txt, the same User-Agent (`report.signals`).
    signals = collect_signals(
        root.url,
        fetch_config=fetch_config,
        policy=policy,
        pacer=pacer,
        sitemap_found=sitemap_found,
        sitemap_urls=len(probe.sitemap_pages),
        sitemap_index=any(a.ok and a.index for a in probe.sitemap_attempts),
    )
    notes.extend(signals.notes)
    llms: dict[str, LlmsFile] = {"/llms.txt": signals.llms_txt, "/llms-full.txt": signals.llms_full_txt}

    checker = LinkChecker(fetch_config=fetch_config, policy=policy, pacer=pacer)
    reports: list[PageReport] = [measure_page(root, requested_url=url, host=host, checker=checker)]
    strategy = Strategy.UNION if PLAYWRIGHT_AVAILABLE else Strategy.STATIC_ONLY
    for candidate in choose_sample(root.document.html, root.url, count=wanted - 1, policy=policy):
        pacer.wait(candidate)
        try:
            resolved = resolve_page(
                candidate, strategy=strategy, fetch_config=fetch_config, render_config=render_config
            )
        except PageBlockedError as exc:
            reports.append(PageReport(requested_url=candidate, url=candidate, section=section_of(candidate), wall="both", error=str(exc)))
            continue
        except (PageMissingError, PageDisallowedError, ValueError) as exc:
            reports.append(PageReport(requested_url=candidate, url=candidate, section=section_of(candidate), error=str(exc)))
            continue
        reports.append(measure_page(resolved, requested_url=candidate, host=host, checker=checker))

    if sitemap_found:
        # A sitemap read up to the cap is not the whole sitemap: a page not in the part
        # read is unknown, not absent.
        truncated = len(probe.sitemap_pages) >= _SITEMAP_LIMIT

        def listed(p: PageReport) -> bool | None:
            if p.url.rstrip("/") in sitemap_pages or p.requested_url.rstrip("/") in sitemap_pages:
                return True
            return None if truncated else False

        reports = [replace(p, in_sitemap=listed(p)) if p.error is None else p for p in reports]

    stack = stack_entries(analysis.technologies, today=today)
    score = score_site(
        reports,
        bots=robots.bots,
        robots_found=robots.found,
        sitemap_found=sitemap_found,
        sitemap_urls=len(probe.sitemap_pages),
        llms_found=llms["/llms.txt"].found,
        llms_full_found=llms["/llms-full.txt"].found,
    )
    findings = integrity_findings(reports, stack)

    return SiteReport(
        url=url,
        root=root.url,
        host=host,
        generated_at=generated_at,
        reachable=True,
        stack=stack,
        robots=robots,
        sitemap_found=sitemap_found,
        sitemap_urls=len(probe.sitemap_pages),
        sitemap_attempts=tuple(a.as_dict() for a in probe.sitemap_attempts),
        llms_txt=llms["/llms.txt"],
        llms_full_txt=llms["/llms-full.txt"],
        signals=signals,
        pages=tuple(reports),
        score=score,
        findings=findings,
        suggested_robots_txt=suggest_robots_txt(
            policy.text if policy.fetched else None,
            origin=origin,
            sitemap_found=sitemap_found,
            sitemaps_declared=policy.sitemaps,
            content_signals=signals.content_signals,
            has_feed=any(s.key == "feeds" and s.present for s in signals.signals),
            today=today,
        ),
        suggested_llms_txt=suggest_llms_txt(reports, host=host),
        suggested_security_txt=(
            None
            if any(s.key == "security_txt" and s.present for s in signals.signals)
            else suggest_security_txt(origin=origin, today=today)
        ),
        measured=measured(len(reports)),
        notes=tuple(notes),
    )
