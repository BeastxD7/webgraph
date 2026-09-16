"""Seed discovery: robots.txt and sitemaps.

A crawler that only follows links wastes budget rediscovering a site's structure that the
site already published. Sitemaps give the URL set directly, which matters most on the sites
where link-following is worst -- paginated catalogues and JavaScript navigation.

robots.txt is honoured rather than merely parsed. An extraction engine that ignores it will
get blocked, and deserves to be.

Both are also *reported*, not only consulted. The owner watched two whole-site crawls
(vtu.ac.in, sode-edu.in, 14 Sep 2026) whose only word on discovery was `from_sitemap: 0`:
nothing said whether robots.txt existed, what it asked, which sitemap addresses were tried
and what came back. So the policy keeps the file's text and the rules that apply to this
client, and the sitemap walk keeps a record of every address it tried (`SitemapAttempt`).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from webgraph import config
from webgraph.crawl.frontier import reconcile_scheme
from webgraph.fetch.static import DEFAULT_USER_AGENT, FetchConfig, FetchResult, fetch_static

ROBOTS_AGENT_TOKEN = config.ROBOTS_AGENT_TOKEN

MAX_SITEMAP_DOCUMENTS = config.MAX_SITEMAP_DOCUMENTS
MAX_ANCHOR_CHARS = config.MAX_ANCHOR_CHARS

__all__ = [
    "RobotsGroup",
    "RobotsPolicy",
    "SitemapAttempt",
    "discover_by_crawling",
    "discover_sitemap_urls",
    "discover_sitemaps",
    "extract_links",
    "group_for_client",
    "load_robots",
    "parse_groups",
    "policy_from",
]

_SITEMAP_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*sitemap:\s*(\S+)", re.IGNORECASE | re.MULTILINE)
_LOC: Final[re.Pattern[str]] = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.IGNORECASE)
_SITEMAP_INDEX: Final[re.Pattern[str]] = re.compile(r"<sitemapindex", re.IGNORECASE)

@dataclass(frozen=True, slots=True)
class RobotsGroup:
    """The `User-agent:` group of a robots.txt that applies to this client.

    `agents` are the lowercased names the group was declared for; `rules` the
    `(allow|disallow, path)` pairs `rule_that_applied` decides with; `lines` the same
    directives as the file wrote them -- Allow, Disallow and Crawl-delay, comments stripped
    -- so a screen can quote the site's own words rather than a paraphrase.
    """

    agents: tuple[str, ...] = ()
    rules: tuple[tuple[str, str], ...] = ()
    lines: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """The name the group was chosen by: the client's own if it was named, else `*`."""
        token = ROBOTS_AGENT_TOKEN.lower()
        return next((a for a in self.agents if token in a), None) or "*"


def parse_groups(robots: str) -> tuple[RobotsGroup, ...]:
    """Every `User-agent:` group of a robots.txt, in file order, comments stripped.

    One parser for three readers. `group_for_client` picks the group that governs this
    client; `fetch.robots.rule_that_applied` quotes the rule that refused a page; the site
    report (`report.bots`) reads what the file declares for each well-known AI and search
    bot. Each used to be, or would have been, a second copy of this loop.
    """
    groups: list[RobotsGroup] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    lines: list[str] = []

    def flush() -> None:
        if lines:
            groups.append(RobotsGroup(tuple(agents), tuple(rules), tuple(lines)))

    for raw in robots.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if lines:
                flush()
                agents, rules, lines = [], [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow"):
            rules.append((key, value))
            lines.append(line)
        elif key == "crawl-delay":
            lines.append(line)
    flush()
    return tuple(groups)


def group_for_client(robots: str) -> RobotsGroup | None:
    """The group of `robots` that governs this client, read the way `urllib.robotparser`
    reads it: the group naming the client first, `*` otherwise, None when neither exists."""
    groups = parse_groups(robots)
    token = ROBOTS_AGENT_TOKEN.lower()
    chosen = next((g for g in groups if any(token in a for a in g.agents)), None)
    if chosen is None:
        chosen = next((g for g in groups if "*" in g.agents), None)
    return chosen


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

    status: int = 0
    """The HTTP status the fetch of robots.txt returned; 0 when nothing came back at all.
    A 404 and a 503 both mean *allow* today and different things about the site."""

    text: str = ""
    """The file as served. Kept so a reader can see what the site asked, not only whether
    the engine obeyed; the trace drops it (`text` is output, not evidence) and keeps `rules`."""

    rules: tuple[str, ...] = ()
    """The Allow / Disallow / Crawl-delay lines of the group that governs this client,
    verbatim. Empty for a file with no group for us, or no file."""

    group: str | None = None
    """Which `User-agent:` the rules came from -- `webgraph` when the site names this
    client, `*` when it does not, None when no group applies."""

    def allows(self, url: str, user_agent: str = DEFAULT_USER_AGENT) -> bool:
        """Whether robots.txt lets this client fetch `url`.

        Asked by the client's name (`ROBOTS_AGENT_TOKEN`), whatever User-Agent header it
        sends: `urllib.robotparser` takes the first `/`-split token of the string it is
        given, and the browser-shaped header made every rule for `webgraph` a rule for
        `mozilla`, which no robots.txt names. `user_agent` is kept for callers that pass
        it and consulted only when it is not the engine's own -- a caller crawling under
        another name is asking about that name.
        """
        if self.parser is None:
            return True
        token = ROBOTS_AGENT_TOKEN if ROBOTS_AGENT_TOKEN in user_agent else user_agent
        try:
            return bool(self.parser.can_fetch(token, url))
        except Exception:
            return True


def load_robots(root: str, *, config: FetchConfig | None = None) -> RobotsPolicy:
    """Fetch and parse robots.txt for the origin of `root`."""
    parts = urlsplit(root)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots_url = urljoin(origin, "/robots.txt")
    return policy_from(origin, fetch_static(robots_url, config=config))


def policy_from(origin: str, result: FetchResult) -> RobotsPolicy:
    """The policy a fetched robots.txt implies. Shared with `fetch.robots.policy_for`, which
    fetches the file through its own per-host cache and must not construct a different
    policy from the same bytes."""
    robots_url = urljoin(origin, "/robots.txt")
    if not result.ok or not result.html.strip():
        return RobotsPolicy(origin=origin, fetched=False, status=result.status)

    text = result.html
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.parse(text.splitlines())
    except Exception:
        return RobotsPolicy(origin=origin, fetched=True, status=result.status, text=text)

    sitemaps = tuple(urljoin(origin, match.group(1)) for match in _SITEMAP_LINE.finditer(text))

    delay: float | None = None
    try:
        raw_delay = parser.crawl_delay(ROBOTS_AGENT_TOKEN)
        if raw_delay is not None:
            delay = float(raw_delay)
    except Exception:
        delay = None

    group = group_for_client(text)
    return RobotsPolicy(
        origin=origin,
        parser=parser,
        sitemaps=sitemaps,
        crawl_delay=delay,
        fetched=True,
        status=result.status,
        text=text,
        rules=group.lines if group is not None else (),
        group=group.label if group is not None else None,
    )


@dataclass(frozen=True, slots=True)
class SitemapAttempt:
    """One sitemap address the discovery walk tried, and what came of it.

    `source` says why it was tried: `robots` for a `Sitemap:` line, `conventional` for
    `/sitemap.xml` and `/sitemap_index.xml`, `index` for an address a sitemap index listed.
    `ok` means the response parsed as a sitemap -- fetched *and* carried a `<loc>`; a 200
    that serves the site's HTML 404 page is not ok. `urls` is what it contributed to the
    page set; an index contributes sitemaps, not pages, so its `urls` is 0 and `index` True.
    """

    url: str
    status: int
    ok: bool
    urls: int
    index: bool
    source: str

    def as_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "status": self.status,
            "ok": self.ok,
            "urls": self.urls,
            "index": self.index,
            "source": self.source,
        }


def discover_sitemap_urls(
    root: str,
    *,
    policy: RobotsPolicy | None = None,
    config: FetchConfig | None = None,
    limit: int = 5000,
) -> list[str]:
    """Collect page URLs from a site's sitemaps. `discover_sitemaps` with the record of
    what was tried left out, for callers that only want the pages."""
    return discover_sitemaps(root, policy=policy, config=config, limit=limit)[0]


def discover_sitemaps(
    root: str,
    *,
    policy: RobotsPolicy | None = None,
    config: FetchConfig | None = None,
    limit: int = 5000,
) -> tuple[list[str], list[SitemapAttempt]]:
    """Collect page URLs from a site's sitemaps, and the record of every address tried.

    Tries the locations robots.txt advertises first, then the conventional `/sitemap.xml`
    and `/sitemap_index.xml`. Sitemap indexes are followed one level, bounded by
    `MAX_SITEMAP_DOCUMENTS`.

    The attempts are the answer to "why is discovery by links only": on vtu.ac.in and
    sode-edu.in every address came back 404 and the crawl's report said `from_sitemap: 0`
    and nothing else. Each attempt records the status, whether it parsed, how many URLs it
    gave and whether it was an index, in the order they were tried.
    """
    parts = urlsplit(root)
    origin = f"{parts.scheme}://{parts.netloc}"

    candidates: list[tuple[str, str]] = [(url, "robots") for url in policy.sitemaps] if policy else []
    for conventional in ("/sitemap.xml", "/sitemap_index.xml"):
        candidate = urljoin(origin, conventional)
        if candidate not in {url for url, _ in candidates}:
            candidates.append((candidate, "conventional"))

    found: list[str] = []
    attempts: list[SitemapAttempt] = []
    visited: set[str] = set()
    queue = list(candidates)
    documents = 0

    while queue and documents < MAX_SITEMAP_DOCUMENTS and len(found) < limit:
        sitemap_url, source = queue.pop(0)
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)

        result = fetch_static(sitemap_url, config=config)
        documents += 1
        if not result.ok or "<loc" not in result.html.lower():
            attempts.append(
                SitemapAttempt(sitemap_url, result.status, ok=False, urls=0, index=False, source=source)
            )
            continue

        # Sitemaps often advertise a scheme the site no longer serves. Reconcile against
        # the root, which was just fetched successfully.
        locations = [
            reconcile_scheme(match.group(1), root) for match in _LOC.finditer(result.html)
        ]
        if _SITEMAP_INDEX.search(result.html):
            # An index lists sitemaps, not pages.
            queue.extend(
                (location, "index") for location in locations if location not in visited
            )
            attempts.append(
                SitemapAttempt(sitemap_url, result.status, ok=True, urls=0, index=True, source=source)
            )
        else:
            found.extend(locations)
            attempts.append(
                SitemapAttempt(
                    sitemap_url, result.status, ok=True, urls=len(locations), index=False, source=source
                )
            )

    return found[:limit], attempts


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
    allow_subdomains: bool = False,
    concurrency: int = 6,
    config: FetchConfig | None = None,
    policy: RobotsPolicy | None = None,
    delay_seconds: float = 0.1,
    fetch_files: bool = False,
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

    scope = CrawlScope(root=root, max_depth=max_depth, allow_subdomains=allow_subdomains)
    frontier = Frontier(scope=scope, fetch_files=fetch_files)
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
