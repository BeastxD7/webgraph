"""Suggested `robots.txt` and `llms.txt` for a site, built from what the report measured.

robots.txt
----------
The site's existing file is kept byte for byte -- a suggestion that rewrites what the
owner already decided is not a suggestion -- and a block of *commented* lines follows it.
Every added line is a comment, so pasting the whole file back changes nothing until the
owner uncomments a variant. Two variants are offered and neither is recommended: allow
every well-known bot, or allow the search and assistant bots and disallow the training
crawlers. Blocking is the owner's call; the report never makes it for them.

llms.txt
--------
The format at llmstxt.org: an H1 with the site's name, a blockquote summary, then H2
sections of `- [title](url): description` lines. Built from the sampled pages' own
titles and descriptions, grouped by the section their path starts with. Marked optional
where it is offered (`SiteReport.llms_txt_note`): adoption is low and most such files get
no traffic (Ahrefs, June 2026: 97% of llms.txt files received no requests).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from urllib.parse import urlsplit

from webgraph.report.bots import BOTS, WellKnownBot
from webgraph.report.pages import PageReport

__all__ = ["LLMS_TXT_NOTE", "suggest_llms_txt", "suggest_robots_txt"]

_TITLE_SEPARATORS = (" | ", " \u2013 ", " \u2014 ", " - ", " :: ")
"""Pipe, en dash, em dash, hyphen, double colon: how a page's title carries the site's name."""

LLMS_TXT_NOTE = (
    "Optional. Adoption is low and most llms.txt files get no traffic: Ahrefs' June 2026 "
    "log study of 137,000 domains found 97% of them received no requests. Publish it if "
    "you like -- it costs nothing -- but do not expect it to change what agents read."
)


def _lines_for(bots: Iterable[WellKnownBot], rule: str) -> list[str]:
    lines: list[str] = []
    for bot in bots:
        lines.append(f"# User-agent: {bot.token}")
        lines.append(f"# {rule}")
        lines.append("#")
    return lines


def suggest_robots_txt(
    existing: str | None,
    *,
    origin: str,
    sitemap_found: bool,
    sitemaps_declared: Iterable[str],
    today: date | None = None,
) -> str:
    """The site's robots.txt with a commented block of choices appended. `existing` is
    kept verbatim; None or empty means there was no file and the suggestion starts with
    the conventional open group."""
    when = (today or date.today()).isoformat()
    head = existing if existing and existing.strip() else "User-agent: *\nAllow: /\n"
    if not head.endswith("\n"):
        head += "\n"

    search = [b for b in BOTS if b.purpose in ("search", "assistant")]
    training = [b for b in BOTS if b.purpose == "training"]

    block: list[str] = [
        "",
        f"# ---- Added by the webgraph site report, {when} ----",
        "# Everything below is a comment: pasting this file back changes nothing.",
        "# What to do about AI crawlers is the owner's choice, and this report does not",
        "# make it. Two variants; uncomment one, or neither. Bots read robots.txt like",
        "# any other crawler; a rule here is honoured by the bots that honour it.",
        "#",
        "# Variant A -- allow every well-known bot: search, assistants and training.",
        "#",
        *_lines_for(BOTS, "Allow: /"),
        "# Variant B -- allow AI search and assistant bots, disallow training crawlers.",
        "#",
        *_lines_for(search, "Allow: /"),
        *_lines_for(training, "Disallow: /"),
    ]
    declared = list(sitemaps_declared)
    if not declared:
        block += [
            "# No Sitemap: line was found. Once a sitemap exists, name it here:",
            f"# Sitemap: {origin.rstrip('/')}/sitemap.xml",
        ]
        if not sitemap_found:
            block.append("# (no sitemap was found at /sitemap.xml or /sitemap_index.xml either)")
    return head + "\n".join(block).rstrip("#\n") + "\n"


_GENERIC_PARTS = frozenset({"home", "homepage", "home page", "welcome", "index", "main"})


def _parts(title: str) -> list[str]:
    for separator in _TITLE_SEPARATORS:
        if separator in title:
            return [part.strip() for part in title.split(separator) if part.strip()]
    return [title.strip()] if title.strip() else []


def _site_name(pages: list[PageReport], host: str) -> str:
    """The site's name from its titles: the part that repeats across pages ("Acme College"
    in "Acme College | Home" and "Admissions | Acme College"); on a root alone, the part
    that is not a generic word; else the host."""
    root = next((p for p in pages if p.section == "/"), None)
    seen: dict[str, int] = {}
    for page in pages:
        for part in set(_parts(page.title)):
            seen[part] = seen.get(part, 0) + 1
    repeated = [part for part, count in seen.items() if count >= 2]
    if repeated:
        return max(repeated, key=lambda part: (seen[part], len(part)))
    if root is not None:
        parts = _parts(root.title)
        specific = [part for part in parts if part.lower() not in _GENERIC_PARTS]
        if specific:
            return specific[0]
        if parts:
            return parts[0]
    return host


def _label(page: PageReport, site_name: str, host: str) -> str:
    """The page's own title: its title without the site's name."""
    parts = [part for part in _parts(page.title) if part.casefold() != site_name.casefold()]
    if not parts:
        return page.title.strip() or urlsplit(page.url).path or host
    return max(parts, key=len)


def suggest_llms_txt(pages: Iterable[PageReport], *, host: str) -> str:
    """An llms.txt draft from the sampled pages, per llmstxt.org."""
    read = [p for p in pages if p.error is None]
    root = next((p for p in read if p.section == "/"), None)
    name = _site_name(read, host)
    lines: list[str] = [f"# {name}", ""]
    summary = (root.description.strip() if root else "") or f"Pages of {host}, as sampled by the webgraph site report."
    lines += [f"> {summary}", ""]

    by_section: dict[str, list[PageReport]] = {}
    for page in read:
        by_section.setdefault(page.section, []).append(page)
    for section, members in by_section.items():
        heading = "Pages" if section == "/" else section.replace("-", " ").replace("_", " ").strip().capitalize()
        lines.append(f"## {heading}")
        lines.append("")
        for page in members:
            label = _label(page, name, host)
            description = " ".join(page.description.split())
            entry = f"- [{label}]({page.url})"
            lines.append(f"{entry}: {description}" if description else entry)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
