"""The AI-readiness score, and the integrity findings beside it.

A number out of 100 is only worth showing when each part of it can be pointed at. The
score is the weighted sum of eight sub-scores, each built from one measurement the report
made, each carrying the evidence it was built from and, when it is short of full marks, a
recommendation in plain words. The weights are the order of what stops an agent reading a
site today, measured against the owner's brief and the demand research (`research/
DEMAND-VALIDATION.md` §3, `VOICE-OF-CUSTOMER.md` §5): whether the words are there without
JavaScript comes first; whether the file even exists that agents are told to look for
(`llms.txt`) comes last, with 5 points, because the research finds it near-worthless --
adoption is low and most such files get no traffic -- and the rationale says so.

A sub-score that could not be measured -- rendering unavailable, no link checked -- is
left out of the total rather than scored zero or full, and the total is rescaled to the
weight that *was* measured (`SiteScore.measured_weight`). `analyze.py` sets the precedent:
an unmeasured verdict is named as unmeasured.

Integrity is a separate section, not a sub-score: an injected link block is not a matter
of degree. The verdict "likely SEO-spam injection" is given only when at least
`REPORT_SPAM_MIN_HOSTS` distinct external hosts are linked from hidden or off-screen
elements on one page; below that the links are reported as what they are, hidden
external links, and the owner reads them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final, Literal

from webgraph import config
from webgraph.report.bots import BotPolicy
from webgraph.report.pages import PageReport
from webgraph.report.stack import StackEntry

__all__ = ["WEIGHTS", "Finding", "SiteScore", "SubScore", "integrity_findings", "score_site"]

WEIGHTS: Final[dict[str, int]] = {
    "readable_without_js": 25,
    "robots_ai_bots": 20,
    "no_walls": 15,
    "sitemap": 10,
    "structured_data": 10,
    "no_hidden_content": 10,
    "llms_txt": 5,
    "dead_links": 5,
}
"""Weights sum to 100. The keys are the sub-scores in the order they are reported."""

Severity = Literal["high", "medium", "low", "info"]


@dataclass(frozen=True, slots=True)
class SubScore:
    key: str
    label: str
    weight: int
    score: float | None
    """Points earned out of `weight`; None when the measurement could not be made."""
    evidence: str
    recommendation: str | None = None
    source: str | None = None
    """The page the evidence is quoted from, when it is one page."""

    @property
    def measured(self) -> bool:
        return self.score is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "score": None if self.score is None else round(self.score, 1),
            "measured": self.measured,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class SiteScore:
    total: int
    """0-100, the measured sub-scores rescaled to their combined weight."""
    measured_weight: int
    subscores: tuple[SubScore, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "measured_weight": self.measured_weight,
            "subscores": [s.as_dict() for s in self.subscores],
        }


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    kind: str
    title: str
    detail: str
    page: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "page": self.page,
        }


def _path(page: PageReport) -> str:
    from urllib.parse import urlsplit

    return urlsplit(page.requested_url).path or "/"


def _pct(share: float) -> str:
    return f"{share:.0%}"


def _readable(pages: list[PageReport]) -> SubScore:
    weight = WEIGHTS["readable_without_js"]
    label = "Readable without JavaScript"
    # Only a page whose render ran can say how much the plain fetch missed: with no render,
    # static equals union by construction and coverage is 100% of nothing measured.
    measured = [p for p in pages if p.error is None and p.rendered_chars > 0 and p.union_chars > 0]
    if not measured:
        return SubScore(
            key="readable_without_js", label=label, weight=weight, score=None,
            evidence="No page could be rendered, so what the plain fetch misses is unmeasured.",
        )
    mean = sum(p.static_coverage for p in measured) / len(measured)
    worst = min(measured, key=lambda p: p.static_coverage)
    evidence = (
        f"Across {len(measured)} rendered page{'s' if len(measured) != 1 else ''} the plain "
        f"fetch holds {_pct(mean)} of the text a browser sees."
    )
    if worst.static_coverage < 0.95:
        evidence += (
            f" Worst: {_path(worst)} has {worst.static_words:,} words without JavaScript and "
            f"{worst.rendered_words:,} with it."
        )
    recommendation = None
    if mean < 0.9:
        recommendation = (
            f"Agents that do not run JavaScript see {_pct(worst.static_coverage)} of "
            f"{_path(worst)}. Server-render or pre-render the main content so the words are "
            "in the HTML the server sends."
        )
    return SubScore(
        key="readable_without_js", label=label, weight=weight, score=weight * mean,
        evidence=evidence, recommendation=recommendation, source=worst.url,
    )


def _paths(bot: BotPolicy) -> str:
    shown = ", ".join(bot.content_paths[:2])
    more = f" and {len(bot.content_paths) - 2} more" if len(bot.content_paths) > 2 else ""
    return f"{len(bot.content_paths)} content path{'s' if len(bot.content_paths) != 1 else ''}: {shown}{more}"


def _robots(bots: Iterable[BotPolicy], found: bool) -> SubScore:
    weight = WEIGHTS["robots_ai_bots"]
    label = "robots.txt does not block AI bots wholesale"
    policies = list(bots)
    blocked = [b for b in policies if b.access == "blocked"]
    share = 1 - len(blocked) / len(policies) if policies else 1.0
    if not found:
        evidence = "No robots.txt: every bot is allowed everywhere, by the convention crawlers follow."
    else:
        named = [b for b in policies if b.via == "named"]
        wildcard = [b for b in policies if b.via == "wildcard"]
        parts: list[str] = []
        for verdict, word in (("blocked", "blocked"), ("partly", "partly restricted"), ("allowed", "allowed")):
            these = [b for b in named if b.access == verdict]
            if these:
                detail = f" ({_paths(these[0])})" if verdict == "partly" else ""
                parts.append(f"{word} by name: " + ", ".join(b.token for b in these) + detail)
        if wildcard:
            sample = wildcard[0]
            if sample.access == "blocked":
                fell = "blocked -- the root is disallowed"
            elif sample.access == "partly":
                fell = f"partly restricted ({_paths(sample)})"
            elif sample.disallowed:
                count = sample.disallowed
                fell = (
                    f"allowed -- the {count} disallowed path{'s are' if count != 1 else ' is'} "
                    "administrative (a back office, sign-in, search), not content"
                )
            else:
                fell = "allowed"
            parts.append(f"the other {len(wildcard)} fall under `User-agent: *`, {fell}")
        unmentioned = [b for b in policies if b.via == "none"]
        if unmentioned and not wildcard:
            parts.append(f"{len(unmentioned)} not mentioned, so allowed")
        evidence = f"robots.txt names {len(named)} of the {len(policies)} well-known bots; " + "; ".join(parts) + "."
    recommendation = None
    if blocked:
        recommendation = (
            "This measures reach, not virtue: blocking training crawlers is a legitimate "
            "choice and the report does not recommend against it. If the intent is to be "
            "found by AI search and assistants while declining training, the suggested "
            "robots.txt below has that variant; the other allows all."
        )
    return SubScore(
        key="robots_ai_bots", label=label, weight=weight, score=weight * share,
        evidence=evidence, recommendation=recommendation,
    )


def _walls(pages: list[PageReport]) -> SubScore:
    weight = WEIGHTS["no_walls"]
    label = "No walls to identified crawlers"
    if not pages:
        return SubScore(key="no_walls", label=label, weight=weight, score=None, evidence="No page sampled.")
    walled = [p for p in pages if p.wall is not None]
    share = 1 - len(walled) / len(pages)
    if not walled:
        evidence = f"All {len(pages)} sampled pages were served to both the plain fetch and the browser."
        recommendation = None
    else:
        named = "; ".join(
            f"{_path(p)}: {p.wall} -- " + (p.static_error or p.render_error or p.error or "").split(";")[0]
            for p in walled
        )
        evidence = f"{len(walled)} of {len(pages)} pages walled one side. {named}."
        recommendation = (
            "The client here identifies itself (webgraph, with a contact address). A wall "
            "served to it is served to every honest crawler; check the CDN or bot-management "
            "rules for the side that was refused."
        )
    return SubScore(
        key="no_walls", label=label, weight=weight, score=weight * share,
        evidence=evidence, recommendation=recommendation, source=walled[0].url if walled else None,
    )


def _sitemap(pages: list[PageReport], sitemap_found: bool, sitemap_urls: int) -> SubScore:
    weight = WEIGHTS["sitemap"]
    label = "Sitemap exists and lists the sampled pages"
    if not sitemap_found:
        return SubScore(
            key="sitemap", label=label, weight=weight, score=0.0,
            evidence="No sitemap: robots.txt names none and /sitemap.xml, /sitemap_index.xml did not parse as one.",
            recommendation="Publish a sitemap.xml and name it in robots.txt (`Sitemap: https://…/sitemap.xml`); crawlers and agents take the page list from it instead of guessing.",
        )
    known = [p for p in pages if p.in_sitemap is not None]
    listed = [p for p in known if p.in_sitemap]
    unknown = [p for p in pages if p.error is None and p.in_sitemap is None]
    coverage = len(listed) / len(known) if known else 1.0
    score = 6 + 4 * coverage
    evidence = f"Sitemap found with {sitemap_urls:,} URLs; {len(listed)} of {len(known)} sampled pages are listed."
    if unknown:
        evidence += f" {len(unknown)} could not be checked: only the first {sitemap_urls:,} URLs were read."
    recommendation = None
    if coverage < 1:
        missing = ", ".join(_path(p) for p in known if not p.in_sitemap)
        recommendation = f"Add the pages the site links to but the sitemap omits: {missing}."
    return SubScore(key="sitemap", label=label, weight=weight, score=score, evidence=evidence, recommendation=recommendation)


def _structured(pages: list[PageReport]) -> SubScore:
    weight = WEIGHTS["structured_data"]
    label = "Structured data and page metadata"
    read = [p for p in pages if p.error is None]
    if not read:
        return SubScore(key="structured_data", label=label, weight=weight, score=None, evidence="No page read.")
    with_schema = [p for p in read if p.has_schema]
    schema_share = len(with_schema) / len(read)
    meta = [
        (bool(p.title) + bool(p.description) + bool(p.lang)) / 3 for p in read
    ]
    meta_share = sum(meta) / len(meta)
    score = 6 * schema_share + 4 * meta_share
    missing_meta: list[str] = []
    for p in read:
        gaps = [name for name, ok in (("title", p.title), ("description", p.description), ("lang", p.lang)) if not ok]
        if gaps:
            missing_meta.append(f"{_path(p)} lacks {', '.join(gaps)}")
    evidence = (
        f"{len(with_schema)} of {len(read)} pages carry JSON-LD or microdata; title, "
        f"description and lang are present on {_pct(meta_share)} of page-fields."
        + (f" {'; '.join(missing_meta[:4])}." if missing_meta else "")
    )
    recommendation = None
    if schema_share < 1 or meta_share < 1:
        recommendation = (
            "Add JSON-LD (schema.org Organization, Article, Product, Course as fits) and a "
            "title, meta description and `<html lang>` to every page; agents read these "
            "before they read the prose."
        )
    return SubScore(key="structured_data", label=label, weight=weight, score=score, evidence=evidence, recommendation=recommendation)


def _hidden(pages: list[PageReport]) -> SubScore:
    weight = WEIGHTS["no_hidden_content"]
    label = "No hidden or injected content"
    read = [p for p in pages if p.error is None]
    if not read:
        return SubScore(key="no_hidden_content", label=label, weight=weight, score=None, evidence="No page read.")
    spam = [p for p in read if p.offscreen_external_hosts >= config.REPORT_SPAM_MIN_HOSTS]
    offscreen = [p for p in read if 0 < p.offscreen_external_hosts < config.REPORT_SPAM_MIN_HOSTS]
    hidden_total = sum(sum(p.hidden_words.values()) for p in read)
    menus = max((p.hidden_external_hosts for p in read), default=0)
    if spam:
        worst = max(spam, key=lambda p: p.offscreen_external_hosts)
        return SubScore(
            key="no_hidden_content", label=label, weight=weight, score=0.0,
            evidence=(
                f"{_path(worst)} links to {worst.offscreen_external_hosts} foreign hosts from "
                f"elements parked off the page ({worst.offscreen_links} off-screen links in all)."
            ),
            recommendation=(
                "This is the shape of an SEO-spam injection on a compromised site. Compare the "
                "theme and plugin files against clean copies, rotate credentials, and update the "
                "CMS; see the integrity section for the hosts."
            ),
            source=worst.url,
        )
    if offscreen:
        worst = max(offscreen, key=lambda p: p.offscreen_external_hosts)
        return SubScore(
            key="no_hidden_content", label=label, weight=weight, score=5.0,
            evidence=(
                f"{_path(worst)} links to {worst.offscreen_external_hosts} foreign host"
                f"{'s' if worst.offscreen_external_hosts != 1 else ''} from elements parked off "
                "the page: " + ", ".join(h.host for h in worst.hidden_hosts if h.external and h.offscreen)
            ),
            recommendation="Check that every off-screen link to another host is one the site meant to publish.",
            source=worst.url,
        )
    # Hidden words as such are not penalised: every dropdown, tab and accordion is hidden
    # text, and the count is in the pages table for the owner to read. The verdict is about
    # what is parked where no reader can scroll.
    menu_note = (
        f" Hidden menus link to up to {menus} foreign hosts per page (`display: none`), which is a dropdown, not a verdict."
        if menus else " No hidden links to foreign hosts."
    )
    return SubScore(
        key="no_hidden_content", label=label, weight=weight, score=float(weight),
        evidence=f"Nothing parked off the page on any sampled page; {hidden_total:,} hidden words in all." + menu_note,
    )


def _llms(found: bool, full_found: bool) -> SubScore:
    weight = WEIGHTS["llms_txt"]
    label = "llms.txt present"
    if found:
        evidence = "/llms.txt is present" + (" and so is /llms-full.txt" if full_found else "") + "."
    else:
        evidence = "No /llms.txt."
    rationale = (
        "Optional, and weighted at 5 because the file is close to worthless in practice: "
        "Ahrefs' server-log study of 137,000 domains (June 2026) found 97% of llms.txt files "
        "received no requests at all, and Google says it does not read them. It costs "
        "nothing to publish, and the draft below is built from the pages sampled."
    )
    return SubScore(
        key="llms_txt", label=label, weight=weight, score=float(weight) if found else 0.0,
        evidence=evidence, recommendation=None if found else rationale,
    )


def _dead(pages: list[PageReport]) -> SubScore:
    weight = WEIGHTS["dead_links"]
    label = "Internal links answer"
    checked = sum(p.links_checked for p in pages)
    dead = sum(p.dead_count for p in pages)
    if checked == 0:
        return SubScore(key="dead_links", label=label, weight=weight, score=None, evidence="No internal link was checked.")
    rate = dead / checked
    evidence = f"{dead} of {checked} internal links checked answered 4xx/5xx."
    sample = [d for p in pages for d in p.dead_links][:3]
    if sample:
        evidence += " " + "; ".join(f"{d.url} -> {d.status}" for d in sample) + "."
    return SubScore(
        key="dead_links", label=label, weight=weight, score=weight * (1 - rate),
        evidence=evidence,
        recommendation="Fix or remove the links above; an agent following them reads an error page." if dead else None,
    )


def score_site(
    pages: list[PageReport],
    *,
    bots: Iterable[BotPolicy],
    robots_found: bool,
    sitemap_found: bool,
    sitemap_urls: int,
    llms_found: bool,
    llms_full_found: bool,
) -> SiteScore:
    """Compose the eight sub-scores and the total."""
    subscores = (
        _readable(pages),
        _robots(bots, robots_found),
        _walls(pages),
        _sitemap(pages, sitemap_found, sitemap_urls),
        _structured(pages),
        _hidden(pages),
        _llms(llms_found, llms_full_found),
        _dead(pages),
    )
    measured = [s for s in subscores if s.score is not None]
    weight = sum(s.weight for s in measured)
    earned = sum(s.score or 0.0 for s in measured)
    total = round(100 * earned / weight) if weight else 0
    return SiteScore(total=total, measured_weight=weight, subscores=subscores)


def integrity_findings(pages: list[PageReport], stack: Iterable[StackEntry]) -> tuple[Finding, ...]:
    """What an owner should look at first, in order of severity. One finding per kind
    across the sampled pages, naming the pages: five pages sharing one injected block are
    one injection, not five."""
    findings: list[Finding] = []
    read = [p for p in pages if p.error is None]

    def hosts_across(selected: list[PageReport]) -> dict[str, int]:
        totals: dict[str, int] = {}
        for page in selected:
            for h in page.hidden_hosts:
                if h.external and h.offscreen:
                    totals[h.host] = totals.get(h.host, 0) + h.offscreen
        return dict(sorted(totals.items(), key=lambda item: (-item[1], item[0])))

    spam = [p for p in read if p.offscreen_external_hosts >= config.REPORT_SPAM_MIN_HOSTS]
    offscreen = [p for p in read if 0 < p.offscreen_external_hosts < config.REPORT_SPAM_MIN_HOSTS and p not in spam]
    if spam:
        hosts = hosts_across(spam)
        listed = ", ".join(f"{host} ({count})" for host, count in list(hosts.items())[:12])
        more = f" and {len(hosts) - 12} more" if len(hosts) > 12 else ""
        links = sum(p.offscreen_links for p in spam)
        findings.append(
            Finding(
                severity="high",
                kind="injected_links",
                title="Likely SEO-spam injection",
                detail=(
                    f"{links} links inside elements parked off the page across "
                    f"{len(spam)} of {len(read)} sampled pages, to {len(hosts)} foreign hosts: {listed}{more}. "
                    "A site's own off-canvas menu links to its own host; dozens of foreign hosts "
                    "positioned where no reader can scroll is the shape of an injection. Pages: "
                    + ", ".join(_path(p) for p in spam) + "."
                ),
                page=spam[0].url,
            )
        )
    if offscreen:
        hosts = hosts_across(offscreen)
        findings.append(
            Finding(
                severity="medium",
                kind="hidden_external_links",
                title="Off-screen links to other hosts",
                detail=(
                    f"{sum(hosts.values())} link{'s' if sum(hosts.values()) != 1 else ''} to "
                    + ", ".join(hosts)
                    + f" from elements parked off the page, on {len(offscreen)} of {len(read)} sampled pages. "
                    f"Below the {config.REPORT_SPAM_MIN_HOSTS}-host threshold for a spam verdict; check they are meant. Pages: "
                    + ", ".join(_path(p) for p in offscreen) + "."
                ),
                page=offscreen[0].url,
            )
        )
    for page in read:
        if page.wall is not None:
            said = page.static_error if page.wall == "plain fetch" else page.render_error
            findings.append(
                Finding(
                    severity="medium",
                    kind="wall",
                    title=f"The {page.wall} was served a wall",
                    detail=said or "",
                    page=page.url,
                )
            )
    for page in pages:
        if page.error is not None:
            findings.append(
                Finding(
                    severity="medium" if page.wall == "both" else "low",
                    kind="unreadable_page",
                    title="A sampled page could not be read",
                    detail=page.error,
                    page=page.requested_url,
                )
            )
    for entry in stack:
        if entry.age_years is not None and entry.age_years >= config.REPORT_STACK_OLD_YEARS:
            findings.append(
                Finding(
                    severity="medium",
                    kind="outdated_stack",
                    title=f"{entry.name} {entry.version} is {entry.age_years:g} years old",
                    detail=(
                        f"The {entry.version} branch was released "
                        f"{entry.released.isoformat() if entry.released else 'unknown'}. An old CMS "
                        "is the usual way an injection gets in; update it and its plugins."
                    ),
                )
            )
    failed = [p for p in read if p.render_error and p.wall is None and p.rendered_chars == 0]
    if failed:
        findings.append(
            Finding(
                severity="info",
                kind="render_failed",
                title=f"The browser render failed on {len(failed)} page{'s' if len(failed) != 1 else ''}",
                detail="; ".join(f"{_path(p)}: {p.render_error}" for p in failed),
                page=failed[0].url,
            )
        )
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda f: order[f.severity])
    return tuple(findings)
