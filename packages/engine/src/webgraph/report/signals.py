"""What a site declares to machines: the files, headers and tags it publishes for crawlers,
AI systems and agents, each read for what it says and reported with who honours it.

Almost none of this is enforced. A `Content-Signal` line, an `llms.txt`, an RSL licence, a
TDM reservation, a `noai` token are preferences a crawler chooses to read; a sitemap, a
feed, an agent card, JSON-LD are conventions a particular consumer -- a search engine, a
feed reader, an A2A client, a link unfurler -- actually acts on. Every `Signal` here carries
`who_honours` and a plain-words `meaning` so the owner can tell the two apart, and none of
them moves the score by itself: a site that says `ai-train=no` is not less ready, and a site
without an agent card is 99% of the web. The one place a signal reaches the score is the
existing metadata sub-score, which now counts OpenGraph beside title, description and lang
(`report.score._structured`).

How it fetches
--------------
Every probe goes through `fetch_capped`: one streaming GET that reads the status and
headers first and stops there on an error, else reads at most `cap` bytes -- HEAD and GET in
one request, because a server that refuses HEAD (405) or mis-answers it would cost a second
request anyway. A well-known file is small by nature; the cap is what keeps a catch-all site
from costing megabytes: vercel.com answers `/ai.txt`, `/rsl.xml`, `/humans.txt` and
`/manifest.json` with its 2.5 MB HTML shell and status 200 (16 Sep 2026). That soft 404 is
also why presence is never the status alone: each signal has a shape test -- an H1 for
llms.txt, the RSL namespace for rsl.xml, a JSON array for tdmrep.json, a `Contact:` line for
security.txt, a `name` for an agent card -- and an HTML body fails every one of them.

Probes are paced by the report's `Pacer`, skipped when robots.txt disallows the path for
this client (recorded as unchecked, not absent), and identified as webgraph like every other
request the engine makes. The root is fetched once more, plainly, for its response headers
(`X-Robots-Tag`, `Link`, `TDM-Reservation`, `Content-Usage`) and the HTML a machine that
runs no JavaScript sees; the rendered document the report already holds is the wrong
witness for that -- vercel.com's JSON-LD arrives with JavaScript. Advertised files are
followed from the root's `Link:` header and `<link>` elements (`rel="manifest"`,
`rel="license"`, `rel="describedby"`, `rel="api-catalog"`); hard-coded paths are tried only
for the conventions that have one.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from urllib.parse import urljoin, urlsplit

import httpx

from webgraph.crawl.discovery import RobotsPolicy, parse_groups
from webgraph.dom.blocks import parse_html
from webgraph.fetch import guard
from webgraph.fetch.static import FetchConfig, FetchResult
from webgraph.report.pages import Pacer

__all__ = [
    "GROUPS",
    "ContentSignal",
    "LlmsFile",
    "Signal",
    "SignalGroup",
    "Signals",
    "collect_signals",
    "fetch_capped",
    "parse_content_signals",
    "parse_content_usage",
    "parse_license_lines",
    "parse_link_header",
    "read_llms_file",
    "robots_tokens",
]

SignalGroup = Literal["ai", "discovery", "agents", "metadata", "trust"]

GROUPS: Final[dict[SignalGroup, str]] = {
    "ai": "Declarations to AI",
    "discovery": "Discovery",
    "agents": "Agents",
    "metadata": "Metadata",
    "trust": "Trust",
}
"""The five groups, in the order they are reported, with their headings."""

SMALL_CAP: Final[int] = 64 * 1024
"""Bytes read of a well-known file. Enough for any of them to show its shape."""
TEXT_CAP: Final[int] = 512 * 1024
"""Bytes read of llms.txt / llms-full.txt: enough to count sections and links."""
ROOT_CAP: Final[int] = 1024 * 1024
"""Bytes read of the root page: its `<head>` and the JSON-LD that follows it."""
LLMS_LINK_SAMPLE: Final[int] = 5
"""llms.txt links checked for an answer."""

_SPEC: Final[dict[str, str]] = {
    "content_signal": "https://contentsignals.org/",
    "content_usage": "https://datatracker.ietf.org/wg/aipref/documents/",
    "llms_txt": "https://llmstxt.org/",
    "ai_txt": "https://spawning.ai/ai-txt",
    "rsl": "https://rslstandard.org/rsl",
    "tdm": "https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240510/",
    "noai": "https://www.deviantart.com/team/journal/UPDATE-All-Deviations-Are-Opted-Out-of-AI-Datasets-934500371",
    "robots_meta": "https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag",
    "sitemap": "https://www.sitemaps.org/protocol.html",
    "feeds": "https://www.rssboard.org/rss-autodiscovery",
    "markdown_alternate": "https://llmstxt.org/",
    "indexnow": "https://www.indexnow.org/documentation",
    "agent_card": "https://a2a-protocol.org/latest/specification/",
    "agents_json": "https://agentprotocol.ai/",
    "mcp": "https://modelcontextprotocol.io/specification/",
    "api_catalog": "https://www.rfc-editor.org/rfc/rfc9727",
    "json_ld": "https://schema.org/docs/gs.html",
    "open_graph": "https://ogp.me/",
    "hreflang": "https://developers.google.com/search/docs/specialty/international/localized-versions",
    "canonical": "https://www.rfc-editor.org/rfc/rfc6596",
    "security_txt": "https://www.rfc-editor.org/rfc/rfc9116",
    "humans_txt": "https://humanstxt.org/",
    "manifest": "https://www.w3.org/TR/appmanifest/",
    "speculation_rules": "https://wicg.github.io/nav-speculation/speculation-rules.html",
}


@dataclass(frozen=True, slots=True)
class Signal:
    """One thing the site does or does not publish for machines."""

    key: str
    label: str
    group: SignalGroup
    present: bool | None
    """True when found and shaped like the thing; False when looked for and absent; None
    when it could not be looked for -- robots.txt disallows the path for this client, or
    (IndexNow) the file's name is the secret."""
    detail: str
    """What was found, in the file's own terms: `search=yes, ai-input=yes, ai-train=no`,
    `3 sections, 41 links, 5 of 5 sampled links answer`, `Organization, WebSite`."""
    meaning: str
    """Plain words for the owner: what this says to machines and whether anyone is bound."""
    who_honours: str
    spec_url: str
    source_url: str | None = None
    """Where it was read from: the file's URL, or the root for a header or tag."""
    status: int | None = None
    """The HTTP status of the probe, when one was made."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "group_label": GROUPS[self.group],
            "present": self.present,
            "detail": self.detail,
            "meaning": self.meaning,
            "who_honours": self.who_honours,
            "spec_url": self.spec_url,
            "source_url": self.source_url,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ContentSignal:
    """One `Content-Signal:` line, parsed: the group it sits in and its yes/no values."""

    agents: tuple[str, ...]
    values: dict[str, str]
    line: str

    def as_dict(self) -> dict[str, Any]:
        return {"agents": list(self.agents), "values": dict(self.values), "line": self.line}


@dataclass(frozen=True, slots=True)
class LlmsFile:
    path: str
    found: bool
    status: int
    bytes: int = 0
    """The file's size: `Content-Length` when the server says, else the bytes read."""
    sections: int = 0
    """H2 headings, the llmstxt.org sections."""
    links: int = 0
    """Markdown links, `[title](url)`."""
    title: str | None = None
    """The H1, when the file has one."""
    links_checked: int = 0
    links_answering: int = 0
    """Of `links_checked` (a sample of `LLMS_LINK_SAMPLE`), how many answered below 400."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "found": self.found,
            "status": self.status,
            "bytes": self.bytes,
            "sections": self.sections,
            "links": self.links,
            "title": self.title,
            "links_checked": self.links_checked,
            "links_answering": self.links_answering,
        }


@dataclass(frozen=True, slots=True)
class Signals:
    signals: tuple[Signal, ...]
    llms_txt: LlmsFile
    llms_full_txt: LlmsFile
    content_signals: tuple[ContentSignal, ...] = ()
    root_status: int = 0
    root_headers: dict[str, str] = field(default_factory=dict)
    """The root's response headers that are signals: `x-robots-tag`, `link`,
    `tdm-reservation`, `tdm-policy`, `content-usage`, `content-type`, `vary`."""
    requests: int = 0
    """Requests this collection made, the root included."""
    notes: tuple[str, ...] = ()

    def by_group(self) -> dict[SignalGroup, tuple[Signal, ...]]:
        return {g: tuple(s for s in self.signals if s.group == g) for g in GROUPS}

    @property
    def present(self) -> tuple[Signal, ...]:
        return tuple(s for s in self.signals if s.present)

    def as_dict(self) -> dict[str, Any]:
        return {
            "signals": [s.as_dict() for s in self.signals],
            "groups": [
                {"key": g, "label": GROUPS[g], "signals": [s.key for s in members]}
                for g, members in self.by_group().items()
            ],
            "llms_txt": self.llms_txt.as_dict(),
            "llms_full_txt": self.llms_full_txt.as_dict(),
            "content_signals": [c.as_dict() for c in self.content_signals],
            "root_status": self.root_status,
            "root_headers": dict(self.root_headers),
            "requests": self.requests,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------------------


def fetch_capped(url: str, *, config: FetchConfig, cap: int = SMALL_CAP) -> FetchResult:
    """One streaming GET: status and headers first, then at most `cap` bytes of body -- and
    no body at all when the status is an error. HEAD-then-GET in a single request. Through
    the same host guard every request passes, so a redirect into a private address is
    refused, not followed. Errors are values, as in `fetch_static`."""
    # A browser's Accept, not `*/*`: vercel.com answers a client it takes for an agent with
    # `text/markdown` when the request states no preference, and the root's `<head>` is
    # what is being read here. A text file comes back the same either way.
    headers = {
        "User-Agent": config.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }
    started = time.monotonic()
    try:
        with httpx.Client(
            http2=config.http2,
            follow_redirects=True,
            max_redirects=config.max_redirects,
            timeout=config.timeout_seconds,
            headers=headers,
            event_hooks={"request": [guard.hook]},
        ) as client, client.stream("GET", url) as response:
            status = int(response.status_code)
            got = {k.lower(): v for k, v in response.headers.items()}
            body = b""
            if status < 400 and cap > 0:
                chunks: list[bytes] = []
                read = 0
                for chunk in response.iter_bytes():
                    chunks.append(chunk)
                    read += len(chunk)
                    if read >= cap:
                        break
                body = b"".join(chunks)[:cap]
            text = body.decode(response.encoding or "utf-8", errors="replace") if body else ""
            return FetchResult(
                url=str(response.url),
                requested_url=url,
                status=status,
                html=text,
                content_type=got.get("content-type", ""),
                elapsed_seconds=time.monotonic() - started,
                ok=status < 400,
                error=None if status < 400 else f"HTTP {status}",
                headers=got,
            )
    except httpx.HTTPError as exc:
        return FetchResult(
            url=url, requested_url=url, status=0, html="", content_type="",
            elapsed_seconds=0.0, ok=False, error=f"{type(exc).__name__}: {exc}",
        )


def _is_html(result: FetchResult) -> bool:
    if "html" in result.content_type.lower():
        return True
    head = result.html.lstrip()[:2048].lower()
    return head.startswith("<") and ("<html" in head or "<!doctype html" in head)


def _size(result: FetchResult) -> int:
    length = result.headers.get("content-length", "")
    if length.isdigit():
        return int(length)
    return len(result.html.encode("utf-8", "replace"))


# ---------------------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------------------

_H1: Final[re.Pattern[str]] = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_H2: Final[re.Pattern[str]] = re.compile(r"^##\s+\S", re.MULTILINE)
_MD_LINK: Final[re.Pattern[str]] = re.compile(r"\[[^\]]+\]\(((?:https?://|/)[^)\s]+)\)")
_LICENSE_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*license:\s*(\S+)", re.IGNORECASE | re.MULTILINE)
_KEY_VALUE: Final[re.Pattern[str]] = re.compile(r"([a-z][a-z0-9-]*)\s*=\s*([a-z0-9-]+)", re.IGNORECASE)
_RSL_NS: Final[str] = "https://rslstandard.org/rsl"
_NOAI_TOKENS: Final[frozenset[str]] = frozenset({"noai", "noimageai"})
_SNIPPET_TOKENS: Final[tuple[str, ...]] = (
    "noindex", "nofollow", "none", "noarchive", "nosnippet", "noimageindex", "notranslate",
    "indexifembedded", "max-snippet", "max-image-preview", "max-video-preview", "unavailable_after",
)


def read_llms_file(result: FetchResult, path: str) -> LlmsFile:
    """Whether `result` is an llms.txt. A catch-all site answers `/llms.txt` with its HTML
    404 page and status 200, so a body has to look like the format -- plain text, an H1 on
    its first non-blank line -- before it counts as found."""
    body = result.html.lstrip("﻿")
    first = next((line for line in body.splitlines() if line.strip()), "")
    if not result.ok or not body.strip() or _is_html(result) or not first.startswith("# "):
        return LlmsFile(path=path, found=False, status=result.status, bytes=_size(result) if result.ok else 0)
    title = _H1.search(body)
    return LlmsFile(
        path=path,
        found=True,
        status=result.status,
        bytes=_size(result),
        sections=len(_H2.findall(body)),
        links=len(_MD_LINK.findall(body)),
        title=title.group(1) if title else None,
    )


def llms_links(text: str, base: str) -> list[str]:
    """The Markdown links of an llms.txt, absolute, in order, each once."""
    seen: dict[str, None] = {}
    for match in _MD_LINK.finditer(text):
        seen.setdefault(urljoin(base, match.group(1)), None)
    return list(seen)


def parse_content_signals(robots: str) -> tuple[ContentSignal, ...]:
    """Every `Content-Signal:` line of a robots.txt with the group it belongs to. The value
    is `key=yes|no` pairs separated by commas (`search=yes, ai-input=yes, ai-train=no`);
    keys are lowercased, values kept as written. A line before any `User-agent:` is
    recorded with no agents."""
    found: list[ContentSignal] = []
    for group in parse_groups(robots):
        for line in group.lines:
            key, _, value = line.partition(":")
            if key.strip().lower() == "content-signal":
                found.append(ContentSignal(agents=group.agents, values=_pairs(value), line=line))
    if not found:
        # A file with the line and no `User-agent:` at all: not a group, still a declaration.
        for raw in robots.splitlines():
            line = raw.split("#", 1)[0].strip()
            key, _, value = line.partition(":")
            if key.strip().lower() == "content-signal":
                found.append(ContentSignal(agents=(), values=_pairs(value), line=line))
    return tuple(found)


def _pairs(value: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2).lower() for m in _KEY_VALUE.finditer(value)}


def parse_content_usage(robots: str, headers: Mapping[str, str]) -> tuple[str, ...]:
    """IETF aipref `Content-Usage` as written: the robots.txt lines (`Content-Usage:
    [path] train-ai=n`) and the root's header (`content-usage: train-ai=n`)."""
    found: list[str] = []
    header = headers.get("content-usage", "").strip()
    if header:
        found.append(f"header: {header}")
    for raw in robots.splitlines():
        line = raw.split("#", 1)[0].strip()
        key, _, value = line.partition(":")
        if key.strip().lower() == "content-usage" and value.strip():
            found.append(f"robots.txt: {value.strip()}")
    return tuple(found)


def parse_license_lines(robots: str, origin: str) -> tuple[str, ...]:
    """RSL's `License: <absolute URL>` lines of a robots.txt, resolved against `origin`."""
    return tuple(dict.fromkeys(urljoin(origin, m.group(1)) for m in _LICENSE_LINE.finditer(robots)))


def parse_link_header(value: str, base: str) -> list[tuple[str, dict[str, str]]]:
    """An HTTP `Link:` header (RFC 8288) as `(absolute url, {param: value})` entries. The
    header may be several comma-joined links, each `<url>; rel="x"; type="y"`."""
    entries: list[tuple[str, dict[str, str]]] = []
    for part in re.split(r",(?=\s*<)", value):
        part = part.strip()
        if not part.startswith("<") or ">" not in part:
            continue
        target, _, rest = part[1:].partition(">")
        params: dict[str, str] = {}
        for param in rest.split(";"):
            if "=" not in param:
                continue
            key, _, val = param.partition("=")
            params[key.strip().lower()] = val.strip().strip('"').lower()
        entries.append((urljoin(base, target.strip()), params))
    return entries


def robots_tokens(values: Iterable[str]) -> tuple[str, ...]:
    """The directive tokens of `<meta name=robots>` / `X-Robots-Tag` values, lowercased,
    each once, in order. `X-Robots-Tag: googlebot: noindex` names a bot first; the bot
    prefix is dropped and the token kept."""
    seen: dict[str, None] = {}
    for value in values:
        body = value
        head, sep, tail = value.partition(":")
        if sep and "," not in head and " " not in head.strip() and not head.strip().lower().startswith(("max-", "unavailable_after")):
            body = tail
        for token in body.split(","):
            token = token.strip().lower()
            if token:
                seen.setdefault(token, None)
    return tuple(seen)


def _jsonld_types(root: Any) -> tuple[str, ...]:
    types: dict[str, None] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            declared = node.get("@type")
            if isinstance(declared, str):
                types.setdefault(declared, None)
            elif isinstance(declared, list):
                for t in declared:
                    if isinstance(t, str):
                        types.setdefault(t, None)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for script in root.xpath('//script[translate(@type, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")="application/ld+json"]'):
        text = (script.text or "").strip()
        if not text:
            continue
        try:
            walk(json.loads(text))
        except ValueError:
            for match in re.finditer(r'"@type"\s*:\s*"([^"]+)"', text):
                types.setdefault(match.group(1), None)
    return tuple(types)


@dataclass(frozen=True, slots=True)
class _Head:
    """What the root page's markup declares, read without JavaScript."""

    robots: tuple[str, ...] = ()
    """`<meta name=robots|googlebot|bingbot>` values as written."""
    tdm_reservation: str | None = None
    tdm_policy: str | None = None
    og: int = 0
    twitter: int = 0
    jsonld_types: tuple[str, ...] = ()
    hreflang: int = 0
    canonical: str | None = None
    feeds: tuple[tuple[str, str], ...] = ()
    """(type, url) of `rel=alternate` feed links: RSS, Atom, JSON Feed."""
    markdown: tuple[str, ...] = ()
    """`rel=alternate type=text/markdown` targets."""
    describedby: tuple[str, ...] = ()
    licenses: tuple[str, ...] = ()
    """`rel=license` targets, with ` (RSL)` appended where `type=application/rsl+xml`."""
    rsl_inline: bool = False
    manifest: str | None = None
    speculation_rules: bool = False


def _read_head(html: str, base: str) -> _Head:
    if not html.strip():
        return _Head()
    try:
        root = parse_html(html)
    except (ValueError, TypeError):
        return _Head()
    robots: list[str] = []
    tdm_reservation = tdm_policy = None
    og = twitter = 0
    for meta in root.xpath("//meta[@name or @property]"):
        name = (meta.get("name") or meta.get("property") or "").strip().lower()
        content = (meta.get("content") or "").strip()
        if name in ("robots", "googlebot", "bingbot") and content:
            robots.append(content)
        elif name == "tdm-reservation":
            tdm_reservation = content
        elif name == "tdm-policy":
            tdm_policy = content
        elif name.startswith("og:"):
            og += 1
        elif name.startswith("twitter:"):
            twitter += 1
    hreflang = 0
    canonical = None
    feeds: list[tuple[str, str]] = []
    markdown: list[str] = []
    describedby: list[str] = []
    licenses: list[str] = []
    manifest = None
    for link in root.xpath("//link[@rel]"):
        rels = {r.lower() for r in (link.get("rel") or "").split()}
        href = (link.get("href") or "").strip()
        kind = (link.get("type") or "").strip().lower()
        if "alternate" in rels and link.get("hreflang"):
            hreflang += 1
        if "canonical" in rels and href and canonical is None:
            canonical = urljoin(base, href)
        is_feed = kind in ("application/rss+xml", "application/atom+xml", "application/feed+json") or (
            kind == "application/json" and "feed" in href.lower()
        )
        if "alternate" in rels and href and is_feed:
            feeds.append((kind, urljoin(base, href)))
        if "alternate" in rels and href and kind == "text/markdown":
            markdown.append(urljoin(base, href))
        if "describedby" in rels and href:
            describedby.append(urljoin(base, href))
        if "license" in rels and href:
            licenses.append(urljoin(base, href) + (" (RSL)" if kind == "application/rsl+xml" else ""))
        if "manifest" in rels and href and manifest is None:
            manifest = urljoin(base, href)
    return _Head(
        robots=tuple(robots),
        tdm_reservation=tdm_reservation,
        tdm_policy=tdm_policy,
        og=og,
        twitter=twitter,
        jsonld_types=_jsonld_types(root),
        hreflang=hreflang,
        canonical=canonical,
        feeds=tuple(feeds),
        markdown=tuple(dict.fromkeys(markdown)),
        describedby=tuple(dict.fromkeys(describedby)),
        licenses=tuple(dict.fromkeys(licenses)),
        rsl_inline=bool(root.xpath('//script[@type="application/rsl+xml"]')),
        manifest=manifest,
        speculation_rules=bool(root.xpath('//script[@type="speculationrules"]')),
    )


def _json(result: FetchResult) -> Any | None:
    if not result.ok or _is_html(result):
        return None
    try:
        return json.loads(result.html.lstrip("﻿"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------------------

_HONOURS: Final[dict[str, str]] = {
    "content_signal": "Voluntary. Cloudflare's policy, inserted on 3.8 million managed robots.txt files; a crawler chooses to read it. Not a technical countermeasure.",
    "content_usage": "Nobody yet: an IETF draft (aipref, 2026). Detected so the owner knows when it lands.",
    "llms_txt": "No major crawler documents reading it; Google says it does not. Coding assistants and their users fetch it by hand.",
    "ai_txt": "Spawning's own tooling and datasets. No crawler operator documents reading it.",
    "rsl": "A licence to agree to, not a lock. RSL Collective members and CDNs that serve it; no crawler operator documents enforcing it.",
    "tdm": "Legally load-bearing in the EU (DSM Directive art. 4 opt-out); read by European TDM tooling. No US crawler documents it.",
    "noai": "DeviantArt's convention; a few art platforms and dataset tools. Not a standard.",
    "robots_meta": "Google, Bing and every search engine -- the one enforced control; nosnippet/max-snippet also bound what Google's AI answers may quote.",
    "sitemap": "Every search engine, and any crawler that takes its page list from it.",
    "feeds": "Every feed reader and aggregator; the cheapest 'what changed' a site can publish.",
    "markdown_alternate": "Assistants and coding agents that ask for Markdown; endorsed by llms.txt v2.",
    "indexnow": "Bing, Yandex, Naver, Seznam, Yep: push indexing. Not detectable without the key.",
    "agent_card": "A2A clients (Google ADK and the A2A SDKs) discover an agent here.",
    "agents_json": "A vendor proposal (agentprotocol.ai); read by tooling that knows it.",
    "mcp": "A convention, not part of the MCP specification, which defines no site-level discovery file.",
    "api_catalog": "RFC 9727; API tooling and agents that follow the Link header.",
    "json_ld": "Google and Bing rich results; every serious extractor and assistant reads it first.",
    "open_graph": "Every link unfurler -- Slack, iMessage, LinkedIn, X -- and assistants for titles and images.",
    "hreflang": "Google, Bing, Yandex: which language edition to show.",
    "canonical": "Every search engine: which URL is the page.",
    "security_txt": "Security researchers and scanners (RFC 9116).",
    "humans_txt": "People. No machine consumer.",
    "manifest": "Browsers, for installing the site as an app. No crawler needs it.",
    "speculation_rules": "Chromium, to prerender the next page. A performance hint.",
}

_LABELS: Final[dict[str, str]] = {
    "content_signal": "Content-Signal (robots.txt)",
    "content_usage": "Content-Usage (IETF aipref)",
    "llms_txt": "llms.txt",
    "ai_txt": "ai.txt",
    "rsl": "RSL licence",
    "tdm": "TDM reservation",
    "noai": "noai / noimageai",
    "robots_meta": "Indexing directives",
    "sitemap": "Sitemap",
    "feeds": "Feed (RSS / Atom / JSON)",
    "markdown_alternate": "Markdown twin",
    "indexnow": "IndexNow key",
    "agent_card": "A2A agent card",
    "agents_json": "agents.json",
    "mcp": "MCP advertisement",
    "api_catalog": "API catalog (Link header)",
    "json_ld": "JSON-LD",
    "open_graph": "OpenGraph / Twitter card",
    "hreflang": "hreflang",
    "canonical": "Canonical URL",
    "security_txt": "security.txt",
    "humans_txt": "humans.txt",
    "manifest": "Web app manifest",
    "speculation_rules": "Speculation rules",
}

_GROUP_OF: Final[dict[str, SignalGroup]] = {
    "content_signal": "ai", "content_usage": "ai", "llms_txt": "ai", "ai_txt": "ai", "rsl": "ai",
    "tdm": "ai", "noai": "ai", "robots_meta": "ai",
    "sitemap": "discovery", "feeds": "discovery", "markdown_alternate": "discovery", "indexnow": "discovery",
    "agent_card": "agents", "agents_json": "agents", "mcp": "agents", "api_catalog": "agents",
    "json_ld": "metadata", "open_graph": "metadata", "hreflang": "metadata", "canonical": "metadata",
    "security_txt": "trust", "humans_txt": "trust", "manifest": "trust", "speculation_rules": "trust",
}


def _signal(
    key: str,
    present: bool | None,
    detail: str,
    meaning: str,
    *,
    source: str | None = None,
    status: int | None = None,
) -> Signal:
    return Signal(
        key=key,
        label=_LABELS[key],
        group=_GROUP_OF[key],
        present=present,
        detail=detail,
        meaning=meaning,
        who_honours=_HONOURS[key],
        spec_url=_SPEC[key],
        source_url=source,
        status=status,
    )


_SIGNAL_WORDS: Final[dict[str, tuple[str, str]]] = {
    "search": ("index it for search and link back", "not build a search index from it"),
    "ai-input": ("use it as input to AI answers (retrieval, grounding)", "not feed it to AI answers"),
    "ai-train": ("train or fine-tune AI models on it", "not train AI models on it"),
}


def content_signal_meaning(values: Mapping[str, str]) -> str:
    """`{'search': 'yes', 'ai-input': 'yes', 'ai-train': 'no'}` -> the sentence an owner
    would say: "Your robots.txt tells AI systems they may index it for search and link back
    and use it as input to AI answers, but should not train AI models on it." """
    may: list[str] = []
    must_not: list[str] = []
    for key, (yes, no) in _SIGNAL_WORDS.items():
        value = values.get(key)
        if value == "yes":
            may.append(yes)
        elif value == "no":
            must_not.append(no)
    unspoken = [k for k in _SIGNAL_WORDS if k not in values]
    parts: list[str] = []
    if may:
        parts.append("they may " + _join(may))
    if must_not:
        parts.append(("but should " if may else "they should ") + _join(must_not))
    sentence = "Your robots.txt tells AI systems " + (", ".join(parts) if parts else "nothing definite")
    if unspoken:
        sentence += f"; it says nothing about {_join(unspoken)}, which grants and restricts nothing"
    return sentence + ". Honoured voluntarily by the bots that read Content-Signal; not enforced."


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


class _Probe:
    """The paced, robots-respecting fetch the collection uses, counting requests."""

    def __init__(self, *, fetch_config: FetchConfig, policy: RobotsPolicy | None, pacer: Pacer) -> None:
        self.fetch_config = fetch_config
        self.policy = policy
        self.pacer = pacer
        self.requests = 0
        self.skipped: list[str] = []

    def allowed(self, url: str) -> bool:
        return self.policy is None or self.policy.allows(url)

    def get(self, url: str, *, cap: int = SMALL_CAP) -> FetchResult | None:
        """None when robots.txt disallows the path for this client."""
        if not self.allowed(url):
            self.skipped.append(url)
            return None
        self.pacer.wait(url)
        self.requests += 1
        return fetch_capped(url, config=self.fetch_config, cap=cap)


def collect_signals(
    root: str,
    *,
    fetch_config: FetchConfig | None = None,
    policy: RobotsPolicy | None = None,
    pacer: Pacer | None = None,
    robots_text: str | None = None,
    sitemap_found: bool = False,
    sitemap_urls: int = 0,
    sitemap_index: bool = False,
) -> Signals:
    """Everything the site at `root` declares to machines. `policy` is the robots.txt the
    report already read (its text is `robots_text` when not given); the sitemap facts come
    from the probe the report already made, so no sitemap is fetched again here."""
    fetch_config = fetch_config or FetchConfig()
    pacer = pacer or Pacer()
    probe = _Probe(fetch_config=fetch_config, policy=policy, pacer=pacer)
    parts = urlsplit(root)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots = robots_text if robots_text is not None else (policy.text if policy is not None and policy.fetched else "")
    robots_url = urljoin(origin, "/robots.txt")
    notes: list[str] = []
    signals: list[Signal] = []

    # The root, plainly: headers and the HTML a machine without JavaScript sees.
    root_result = probe.get(root, cap=ROOT_CAP)
    root_headers: dict[str, str] = {}
    root_status = 0
    head = _Head()
    if root_result is not None:
        root_status = root_result.status
        root_headers = {
            k: v for k, v in root_result.headers.items()
            if k in ("x-robots-tag", "link", "tdm-reservation", "tdm-policy", "content-usage", "content-type", "vary", "crawler-price")
        }
        head = _read_head(root_result.html if root_result.ok and _is_html(root_result) else "", root_result.url)
        if root_result.status == 402:
            notes.append(
                f"the root answered 402 Payment Required{' with crawler-price ' + root_result.headers['crawler-price'] if 'crawler-price' in root_result.headers else ''}: "
                "a pay-per-crawl wall, shown to crawlers that did not offer a price"
            )
    links = parse_link_header(root_headers.get("link", ""), root) if root_headers.get("link") else []
    rels: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for url, params in links:
        for rel in params.get("rel", "").split():
            rels.setdefault(rel, []).append((url, params))

    # ---- Declarations to AI ----
    content_signals = parse_content_signals(robots)
    if content_signals:
        first = content_signals[0]
        where = f"under User-agent: {', '.join(first.agents)}" if first.agents else "outside any group"
        detail = ", ".join(f"{k}={v}" for k, v in first.values.items()) + f" ({where})"
        if len(content_signals) > 1:
            detail += f"; {len(content_signals)} lines in all"
        meaning = content_signal_meaning(first.values)
        if first.agents and "*" not in first.agents and len(content_signals) == 1:
            meaning += (
                f" Note: the line sits in the group for {', '.join(first.agents)}; robots.txt "
                "directives apply per group, so for every other bot the file states no signal."
            )
        signals.append(_signal("content_signal", True, detail, meaning, source=robots_url))
    else:
        signals.append(_signal(
            "content_signal", False, "no Content-Signal line",
            "robots.txt states no preference about search, AI answers or AI training in the Content-Signal vocabulary; per the policy, silence grants and restricts nothing. The suggested robots.txt has a commented example.",
            source=robots_url,
        ))

    usage = parse_content_usage(robots, root_headers)
    signals.append(_signal(
        "content_usage", bool(usage), "; ".join(usage) if usage else "no Content-Usage header or robots.txt line",
        "The IETF's draft AI-preference vocabulary (train-ai, ai-use, search: y/n)" + (" is declared here." if usage else " is not used; nothing is expected to read it yet."),
        source=root if usage and usage[0].startswith("header") else robots_url,
    ))

    # llms.txt, llms-full.txt, and a sample of the links.
    llms: dict[str, LlmsFile] = {}
    for path, cap in (("/llms.txt", TEXT_CAP), ("/llms-full.txt", TEXT_CAP)):
        target = urljoin(origin, path)
        result = probe.get(target, cap=cap)
        if result is None:
            llms[path] = LlmsFile(path=path, found=False, status=0)
            notes.append(f"{path} is disallowed for this client by robots.txt and was not fetched")
            continue
        parsed = read_llms_file(result, path)
        if parsed.found and path == "/llms.txt":
            checked = answering = 0
            for link in llms_links(result.html, result.url)[:LLMS_LINK_SAMPLE]:
                answer = probe.get(link, cap=0)
                if answer is None or answer.status == 0:
                    continue
                checked += 1
                if answer.status < 400:
                    answering += 1
            parsed = LlmsFile(
                path=parsed.path, found=True, status=parsed.status, bytes=parsed.bytes, sections=parsed.sections,
                links=parsed.links, title=parsed.title, links_checked=checked, links_answering=answering,
            )
        llms[path] = parsed
    main, full = llms["/llms.txt"], llms["/llms-full.txt"]
    if main.found:
        detail = f"{main.sections} section{'s' if main.sections != 1 else ''}, {main.links} link{'s' if main.links != 1 else ''}, {main.bytes:,} bytes"
        if main.links_checked:
            detail += f"; {main.links_answering} of {main.links_checked} sampled links answer"
        if full.found:
            detail += f"; llms-full.txt present ({full.bytes:,} bytes)"
        meaning = (
            "The site publishes a curated Markdown index for language models" + (f" titled '{main.title}'" if main.title else "") +
            ". Useful to a person pasting it into an assistant; near-worthless as discovery -- 97% of such files get no requests (Ahrefs, June 2026)."
        )
    else:
        detail = "no llms.txt" + (" (the answer was an HTML page, not the format)" if main.status == 200 else f" (HTTP {main.status})" if main.status else "")
        meaning = "No llms.txt. Optional: it costs nothing and changes little; the draft below is built from the pages sampled."
    signals.append(_signal("llms_txt", main.found, detail, meaning, source=urljoin(origin, "/llms.txt"), status=main.status or None))

    ai_txt = probe.get(urljoin(origin, "/ai.txt"))
    ai_present: bool | None = None if ai_txt is None else bool(
        ai_txt.ok and not _is_html(ai_txt) and re.search(r"^\s*(user-agent|disallow|allow)\s*:", ai_txt.html, re.I | re.M)
    )
    signals.append(_signal(
        "ai_txt", ai_present,
        "robots-shaped ai.txt present" if ai_present else "not checked (disallowed)" if ai_present is None else "no ai.txt",
        "Spawning's opt-out file for AI training datasets" + (" is published." if ai_present else " is absent; only Spawning's tooling reads it, so this is not a gap."),
        source=urljoin(origin, "/ai.txt"), status=None if ai_txt is None else ai_txt.status,
    ))

    # RSL: the License line, the Link header, the <link rel=license type=rsl>, the inline block, then /rsl.xml.
    rsl_sources: list[str] = []
    for url in parse_license_lines(robots, origin):
        rsl_sources.append(f"robots.txt License: {url}")
    for url, params in rels.get("license", []):
        if params.get("type") == "application/rsl+xml":
            rsl_sources.append(f"Link header: {url}")
    for url in head.licenses:
        if url.endswith(" (RSL)"):
            rsl_sources.append(f"<link rel=license>: {url[:-6]}")
    if head.rsl_inline:
        rsl_sources.append("inline <script type=application/rsl+xml> on the root")
    rsl_status: int | None = None
    if not rsl_sources:
        rsl = probe.get(urljoin(origin, "/rsl.xml"))
        if rsl is not None:
            rsl_status = rsl.status
            if rsl.ok and not _is_html(rsl) and _RSL_NS in rsl.html:
                rsl_sources.append(f"/rsl.xml ({_RSL_NS})")
    signals.append(_signal(
        "rsl", bool(rsl_sources), "; ".join(rsl_sources) if rsl_sources else "no License: line, RSL link or /rsl.xml",
        "The site publishes machine-readable licence terms for its content (what AI may do with it, and at what price)." if rsl_sources
        else "No Really Simple Licensing terms: the site states no price or licence for AI use in machine-readable form. A choice, not a gap.",
        source=urljoin(origin, "/rsl.xml") if not rsl_sources or rsl_sources[0].startswith("/rsl") else robots_url, status=rsl_status,
    ))

    # TDM reservation: header, meta, well-known file.
    tdm_sources: list[str] = []
    tdm_reserved = False
    if root_headers.get("tdm-reservation"):
        tdm_reserved = tdm_reserved or root_headers["tdm-reservation"].strip() == "1"
        tdm_sources.append(f"header tdm-reservation: {root_headers['tdm-reservation']}" + (f", tdm-policy: {root_headers['tdm-policy']}" if root_headers.get("tdm-policy") else ""))
    if head.tdm_reservation is not None:
        tdm_reserved = tdm_reserved or head.tdm_reservation.strip() == "1"
        tdm_sources.append(f"<meta tdm-reservation> {head.tdm_reservation}" + (f", policy {head.tdm_policy}" if head.tdm_policy else ""))
    tdmrep = probe.get(urljoin(origin, "/.well-known/tdmrep.json"))
    tdm_status = None if tdmrep is None else tdmrep.status
    rules = _json(tdmrep) if tdmrep is not None else None
    if isinstance(rules, list) and rules and all(isinstance(r, dict) and "tdm-reservation" in r for r in rules):
        reserved = sum(1 for r in rules if str(r.get("tdm-reservation")) == "1")
        tdm_reserved = tdm_reserved or reserved > 0
        tdm_sources.append(f"/.well-known/tdmrep.json: {len(rules)} rule{'s' if len(rules) != 1 else ''}, {reserved} reserving")
    signals.append(_signal(
        "tdm", bool(tdm_sources), "; ".join(tdm_sources) if tdm_sources else "no TDM-Reservation header, meta or tdmrep.json",
        ("The site reserves its text-and-data-mining rights under EU law: mining it for AI needs a licence." if tdm_reserved
         else "The site declares TDM rights unreserved (0): mining is permitted.") if tdm_sources
        else "No text-and-data-mining reservation: under the EU directive, the site has not opted out in machine-readable form.",
        source=urljoin(origin, "/.well-known/tdmrep.json"), status=tdm_status,
    ))

    # noai / noimageai and the indexing directives, from meta and X-Robots-Tag together.
    x_robots = [v for k, v in root_result.headers.items() if k == "x-robots-tag"] if root_result is not None else []
    tokens = robots_tokens([*head.robots, *x_robots])
    noai = tuple(t for t in tokens if t in _NOAI_TOKENS)
    signals.append(_signal(
        "noai", bool(noai), ", ".join(noai) if noai else "no noai / noimageai token",
        "The page asks AI dataset builders not to use its content (noai) or images (noimageai) -- DeviantArt's convention, read by a few tools." if noai
        else "No noai/noimageai token. Only a handful of tools read them; robots.txt is where AI crawlers look.",
        source=root,
    ))
    directives = tuple(t for t in tokens if t.split(":")[0] in _SNIPPET_TOKENS)
    where_from: list[str] = []
    if head.robots:
        where_from.append("meta")
    if x_robots:
        where_from.append("X-Robots-Tag")
    if directives:
        blocking = [t for t in directives if t in ("noindex", "none")]
        snippet = [t for t in directives if t.startswith(("nosnippet", "max-snippet", "max-image-preview", "max-video-preview"))]
        meaning = "The root " + ("asks search engines not to index it" if blocking else "is indexable")
        if snippet:
            meaning += f" and bounds what they may quote or preview ({', '.join(snippet)}) -- the one AI-related control Google enforces (its AI answers obey nosnippet/max-snippet)"
        meaning += "."
        detail = ", ".join(directives) + f" (from {' and '.join(where_from)})"
    else:
        detail = "none on the root" + (f" (values seen: {', '.join(tokens)})" if tokens else "")
        meaning = "No indexing directive on the root: search engines may index it and quote freely. Nothing is missing; nosnippet/max-snippet are there if the owner wants to bound AI answers."
    signals.append(_signal("robots_meta", bool(directives), detail, meaning, source=root))

    # ---- Discovery ----
    declared = policy.sitemaps if policy is not None else ()
    if sitemap_found:
        detail = f"found, {sitemap_urls:,} URL{'s' if sitemap_urls != 1 else ''} read" + (", an index of sitemaps" if sitemap_index else "") + (f", declared in robots.txt ({len(declared)})" if declared else ", not declared in robots.txt")
        meaning = "Crawlers and agents can take the page list from the sitemap instead of guessing." + ("" if declared else " Naming it in robots.txt (`Sitemap:`) lets them find it without trying the default path.")
    else:
        detail = "no sitemap parsed" + (f"; robots.txt names {len(declared)}" if declared else "; none declared")
        meaning = "No sitemap: crawlers discover pages only by following links. Publish one and name it in robots.txt."
    signals.append(_signal("sitemap", sitemap_found, detail, meaning, source=declared[0] if declared else urljoin(origin, "/sitemap.xml")))

    if head.feeds:
        names = {"application/rss+xml": "RSS", "application/atom+xml": "Atom", "application/feed+json": "JSON Feed", "application/json": "JSON Feed"}
        kinds = ", ".join(dict.fromkeys(names.get(k, k) for k, _ in head.feeds))
        detail = f"{len(head.feeds)} feed link{'s' if len(head.feeds) != 1 else ''} ({kinds}): " + ", ".join(u for _, u in head.feeds[:2])
        meaning = "The root advertises a feed: readers and aggregators, AI ones included, get what changed without crawling."
    else:
        detail = "no feed autodiscovery link on the root"
        meaning = "No RSS/Atom/JSON feed is advertised on the root. If the site publishes anything regularly, a feed is the cheapest 'what changed' it can offer machines."
    signals.append(_signal("feeds", bool(head.feeds), detail, meaning, source=root))

    md_sources: list[str] = []
    if head.markdown:
        md_sources.append(f"<link rel=alternate type=text/markdown> -> {head.markdown[0]}")
    for url, params in rels.get("alternate", []):
        if params.get("type") == "text/markdown":
            md_sources.append(f"Link header -> {url}")
    for url in head.describedby or [u for u, _ in rels.get("describedby", [])]:
        md_sources.append(f"rel=describedby -> {url}")
    if "text/markdown" in root_headers.get("content-type", ""):
        md_sources.append("the root itself answered text/markdown")
    signals.append(_signal(
        "markdown_alternate", bool(md_sources), "; ".join(md_sources) if md_sources else "no text/markdown alternate or describedby link",
        "The site offers pages as Markdown to machines that ask -- the form assistants read most cheaply (llms.txt v2 convention)." if md_sources
        else "No Markdown twin advertised. Optional; two of the five sites this was calibrated on (vercel.com, cloudflare.com) do it.",
        source=root,
    ))
    signals.append(_signal(
        "indexnow", None, "not measurable: the key file is named by the key",
        "Whether the site pushes URL changes to Bing/Yandex via IndexNow cannot be seen from outside; the key file /<key>.txt is only findable by whoever holds the key.",
        source=None,
    ))

    # ---- Agents ----
    card: dict[str, Any] | None = None
    card_url: str | None = None
    card_status: int | None = None
    for path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
        result = probe.get(urljoin(origin, path))
        if result is None:
            continue
        card_status = result.status
        data = _json(result)
        if isinstance(data, dict) and isinstance(data.get("name"), str) and ("skills" in data or "capabilities" in data or "url" in data):
            card, card_url = data, urljoin(origin, path)
            break
    if card is not None:
        raw_skills = card.get("skills")
        skills: list[Any] = raw_skills if isinstance(raw_skills, list) else []
        detail = f"'{card['name']}', {len(skills)} skill{'s' if len(skills) != 1 else ''}" + (f" (protocol {card['protocolVersion']})" if card.get("protocolVersion") else "") + f" at {urlsplit(card_url or '').path}"
        if card_url and card_url.endswith("/agent.json"):
            detail += " -- the pre-0.3 path; A2A 1.0 reads /.well-known/agent-card.json"
        meaning = f"The site publishes an A2A agent card: an AI agent can discover '{card['name']}' and what it can do here without a human reading the site."
    else:
        detail = "no agent card at /.well-known/agent-card.json or /.well-known/agent.json"
        meaning = "No A2A agent card: agents cannot discover a machine interface to this site by convention. Rare on the web today; not a gap unless the site runs an agent."
    signals.append(_signal("agent_card", card is not None, detail, meaning, source=card_url or urljoin(origin, "/.well-known/agent-card.json"), status=card_status))

    agents = probe.get(urljoin(origin, "/.well-known/agents.json"))
    agents_data = _json(agents) if agents is not None else None
    agents_ok = isinstance(agents_data, dict) and ("siteInfo" in agents_data or "capabilities" in agents_data or "$schema" in agents_data)
    if agents_ok and isinstance(agents_data, dict):
        raw_info = agents_data.get("siteInfo")
        info: dict[str, Any] = raw_info if isinstance(raw_info, dict) else {}
        raw_caps = agents_data.get("capabilities")
        caps: list[Any] = raw_caps if isinstance(raw_caps, list) else []
        detail = f"'{info.get('name', 'unnamed')}', {len(caps)} capabilit{'ies' if len(caps) != 1 else 'y'}" + (f", schema {agents_data['$schema']}" if isinstance(agents_data.get("$schema"), str) else "")
    else:
        detail = "no agents.json"
    signals.append(_signal(
        "agents_json", None if agents is None else bool(agents_ok), detail,
        "The site describes its AI-facing content and endpoints (llms.txt, Markdown pages, capabilities) in an agents.json." if agents_ok
        else "No agents.json. A vendor convention few sites use; not a gap.",
        source=urljoin(origin, "/.well-known/agents.json"), status=None if agents is None else agents.status,
    ))

    mcp_sources: list[str] = []
    mcp = probe.get(urljoin(origin, "/.well-known/mcp.json"))
    mcp_data = _json(mcp) if mcp is not None else None
    if isinstance(mcp_data, dict) and isinstance(mcp_data.get("mcpServers"), dict):
        servers = mcp_data["mcpServers"]
        names = [str(v.get("name") or k) for k, v in servers.items() if isinstance(v, dict)]
        mcp_sources.append(f"/.well-known/mcp.json: {len(servers)} server{'s' if len(servers) != 1 else ''} ({', '.join(names[:3])})")
    for url, params in rels.get("service-desc", []) + rels.get("ai-catalog", []):
        if "mcp" in url.lower():
            mcp_sources.append(f"Link rel={params.get('rel')} -> {url}")
    signals.append(_signal(
        "mcp", None if mcp is None and not mcp_sources else bool(mcp_sources), "; ".join(mcp_sources) if mcp_sources else "no mcp.json or MCP link",
        "The site advertises an MCP server or AI catalog: an assistant can be connected to it as a tool." if mcp_sources
        else "No MCP server advertised. MCP itself defines no site-level discovery file, so absence means only that the site follows no convention for it.",
        source=urljoin(origin, "/.well-known/mcp.json"), status=None if mcp is None else mcp.status,
    ))

    catalog = rels.get("api-catalog", [])
    extra = [(r, u) for r in ("agent-skills", "ai-catalog") for u, _ in rels.get(r, [])]
    signals.append(_signal(
        "api_catalog", bool(catalog or extra),
        "; ".join([f"rel=api-catalog -> {u}" for u, _ in catalog] + [f"rel={r} -> {u}" for r, u in extra]) if catalog or extra else "no api-catalog, ai-catalog or agent-skills Link on the root",
        "The root's Link header points machines at the site's API catalog" + (" and agent resources" if extra else "") + " (RFC 9727): an agent can find the API without reading the docs." if catalog or extra
        else "No API catalog link. Only relevant to a site with an API.",
        source=root,
    ))

    # ---- Metadata ----
    signals.append(_signal(
        "json_ld", bool(head.jsonld_types), ", ".join(head.jsonld_types[:8]) + (" …" if len(head.jsonld_types) > 8 else "") if head.jsonld_types else "no JSON-LD in the plain HTML",
        f"The root tells machines what it is in Schema.org terms ({', '.join(head.jsonld_types[:3])}) without JavaScript." if head.jsonld_types
        else "The plain HTML of the root carries no JSON-LD: an agent that does not run JavaScript learns what the site is only from the prose. Add Organization / WebSite at least." + (" (The pages table shows whether it arrives with JavaScript.)"),
        source=root,
    ))
    og_present = head.og > 0
    signals.append(_signal(
        "open_graph", og_present, f"{head.og} og:* tag{'s' if head.og != 1 else ''}, {head.twitter} twitter:* tag{'s' if head.twitter != 1 else ''}" if og_present or head.twitter else "no og:* or twitter:* tags",
        "Links to the site unfurl with a title, description and image in chat apps and assistants." + ("" if head.twitter else " No Twitter card tags; X falls back to OpenGraph.") if og_present
        else "No OpenGraph: a link to the root shows bare in Slack, iMessage and assistants. Add og:title, og:description, og:image.",
        source=root,
    ))
    signals.append(_signal(
        "hreflang", head.hreflang > 0, f"{head.hreflang} hreflang link{'s' if head.hreflang != 1 else ''}" if head.hreflang else "no hreflang links",
        f"The root names {head.hreflang} language editions so search engines show the right one." if head.hreflang
        else "No hreflang: fine for a single-language site.",
        source=root,
    ))
    signals.append(_signal(
        "canonical", head.canonical is not None, head.canonical or "no rel=canonical",
        "The root declares its one true URL, so duplicates are folded into it." if head.canonical
        else "No canonical URL on the root: search engines pick one themselves. Add <link rel=canonical>.",
        source=root,
    ))

    # ---- Trust ----
    sec_url: str | None = None
    sec_status: int | None = None
    sec_fields: dict[str, str] = {}
    for path in ("/.well-known/security.txt", "/security.txt"):
        result = probe.get(urljoin(origin, path))
        if result is None:
            continue
        sec_status = result.status
        if result.ok and not _is_html(result) and re.search(r"^\s*contact:", result.html, re.I | re.M):
            sec_url = urljoin(origin, path)
            for raw in result.html.splitlines():
                line = raw.split("#", 1)[0].strip()
                key, sep, value = line.partition(":")
                if sep and key.strip():
                    sec_fields.setdefault(key.strip().lower(), value.strip())
            break
    if sec_url:
        detail = f"Contact: {sec_fields.get('contact', '')}" + (f"; Expires: {sec_fields['expires']}" if "expires" in sec_fields else "; no Expires (RFC 9116 requires one)") + ("; Policy" if "policy" in sec_fields else "")
        if sec_url.endswith("/security.txt") and "/.well-known/" not in sec_url:
            detail += "; at the legacy root path only"
        meaning = "Security researchers know whom to tell about a vulnerability." + ("" if "expires" in sec_fields else " Add an Expires line to conform.")
    else:
        detail = "no security.txt at /.well-known/ or the root"
        meaning = "No security.txt: a researcher who finds a hole has no published address to report it to. The template below takes two minutes."
    signals.append(_signal("security_txt", sec_url is not None, detail, meaning, source=sec_url or urljoin(origin, "/.well-known/security.txt"), status=sec_status))

    humans = probe.get(urljoin(origin, "/humans.txt"))
    humans_ok = None if humans is None else bool(humans.ok and not _is_html(humans) and humans.html.strip())
    signals.append(_signal(
        "humans_txt", humans_ok, "present" if humans_ok else "not checked (disallowed)" if humans_ok is None else "no humans.txt",
        "The site credits the people who built it in humans.txt. For people; no machine reads it." if humans_ok else "No humans.txt. Nothing reads it; nothing is missing.",
        source=urljoin(origin, "/humans.txt"), status=None if humans is None else humans.status,
    ))

    manifest_ok: bool | None = False
    manifest_detail = "no <link rel=manifest> on the root"
    manifest_status: int | None = None
    if head.manifest:
        result = probe.get(head.manifest)
        if result is None:
            manifest_ok = None
            manifest_detail = f"linked ({head.manifest}) but disallowed for this client"
        else:
            manifest_status = result.status
            data = _json(result)
            if isinstance(data, dict) and (data.get("name") or data.get("short_name")):
                manifest_ok = True
                manifest_detail = f"'{data.get('name') or data.get('short_name')}'" + (f", display {data['display']}" if data.get("display") else "") + f", {len(data.get('icons') or [])} icons"
            else:
                manifest_detail = f"linked ({head.manifest}) but did not parse as a manifest (HTTP {result.status})"
    signals.append(_signal(
        "manifest", manifest_ok, manifest_detail,
        "The site can be installed as an app; the manifest names it for the browser." if manifest_ok
        else "No web app manifest. Only matters if the site wants to be installable.",
        source=head.manifest or root, status=manifest_status,
    ))
    signals.append(_signal(
        "speculation_rules", head.speculation_rules, "present on the root" if head.speculation_rules else "none on the root",
        "The root tells Chromium which pages to prerender next -- a speed hint, nothing declared to crawlers." if head.speculation_rules
        else "No speculation rules. A performance option, not a signal to machines.",
        source=root,
    ))

    if probe.skipped:
        notes.append(f"{len(probe.skipped)} probe{'s' if len(probe.skipped) != 1 else ''} not made: robots.txt disallows the path for this client ({', '.join(urlsplit(u).path for u in probe.skipped[:4])})")
    return Signals(
        signals=tuple(signals),
        llms_txt=main,
        llms_full_txt=full,
        content_signals=content_signals,
        root_status=root_status,
        root_headers=root_headers,
        requests=probe.requests,
        notes=tuple(notes),
    )
