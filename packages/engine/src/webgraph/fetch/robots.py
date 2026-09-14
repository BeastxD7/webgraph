"""robots.txt for a single page.

The crawl has read robots.txt since its first version (`crawl.discovery.load_robots`); a
single page never did, so `/api/text` fetched pages whose site had asked automated clients
to stay out -- Stack Overflow and The Sun both publish `User-agent: * / Disallow: /` (14 Sep
2026). The owner's rule for a site that does not want automated readers is to say so, not
to disguise the client: the refusal names the file, quotes the group and the rule that
matched, and points at what is sanctioned -- the site's own API when one is known, or the
HTML the caller already has.

One fetch of the file per host, trusted for `ROBOTS_CACHE_SECONDS`; a file that cannot be
fetched means *allow*, by the convention every crawler follows, and the policy records that
it was never read. Rules are asked for by the client's name (`ROBOTS_AGENT_TOKEN`), not by
its User-Agent header -- see `RobotsPolicy.allows`.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from webgraph import config
from webgraph.crawl.discovery import RobotsPolicy
from webgraph.fetch.static import FetchConfig, fetch_static

__all__ = ["allowed", "forget", "policy_for", "rule_that_applied", "sanctioned_source"]

_cache: dict[str, tuple[float, RobotsPolicy, str]] = {}
_lock = threading.Lock()


def forget() -> None:
    """Drop every cached robots.txt. Tests; a long-running process trusts the TTL."""
    with _lock:
        _cache.clear()


def policy_for(url: str, *, fetch_config: FetchConfig | None = None) -> tuple[RobotsPolicy, str]:
    """The robots policy for `url`'s origin and the file's text, fetched once per host.

    The file is fetched here rather than through `load_robots` because the refusal quotes
    the rule and `load_robots` keeps only the parser; the policy it returns is the same
    type the crawl uses, so `allows` is one function for both.
    """
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    now = time.monotonic()
    with _lock:
        cached = _cache.get(origin)
        if cached is not None and now - cached[0] < config.ROBOTS_CACHE_SECONDS:
            return cached[1], cached[2]
    result = fetch_static(urljoin(origin, "/robots.txt"), config=fetch_config)
    if result.ok and result.html.strip():
        parser = RobotFileParser()
        parser.set_url(urljoin(origin, "/robots.txt"))
        try:
            parser.parse(result.html.splitlines())
            policy = RobotsPolicy(origin=origin, parser=parser, fetched=True)
        except Exception:
            policy = RobotsPolicy(origin=origin, fetched=True)
        text = result.html
    else:
        policy, text = RobotsPolicy(origin=origin, fetched=False), ""
    with _lock:
        _cache[origin] = (now, policy, text)
    return policy, text


def allowed(url: str, *, fetch_config: FetchConfig | None = None) -> str | None:
    """None when robots.txt lets this client read `url`; otherwise the reason, ready to be
    the message of a refusal."""
    policy, text = policy_for(url, fetch_config=fetch_config)
    if policy.allows(url):
        return None
    origin = policy.origin
    group, rule = rule_that_applied(text, url) or ("User-agent: *", "Disallow: /")
    host = urlsplit(url).hostname or ""
    hint = sanctioned_source(host)
    offered = (
        f"the site offers {hint}; " if hint else ""
    ) + "or supply the HTML you already have (`html` on /api/text) and the engine reads that"
    return (
        f"{origin}/robots.txt disallows {urlsplit(url).path or '/'} for this client "
        f"(`{group}` / `{rule}`): the site does not want automated readers here. "
        f"{offered[0].upper()}{offered[1:]}."
    )


def rule_that_applied(robots: str, url: str) -> tuple[str, str] | None:
    """The `User-agent:` group and the `Disallow:` line that stop this client at `url`,
    quoted from the file. None when no rule in the file forbids it.

    `urllib.robotparser` decides but does not say why; this reads the file the way it does
    -- the group naming this client first, `*` otherwise, the longest matching path wins,
    `Allow` beating `Disallow` at equal length -- so the quoted rule is the one that decided.
    """
    path = urlsplit(url).path or "/"
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    for raw in robots.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow"):
            rules.append((key, value))
    if rules:
        groups.append((agents, rules))
    token = config.ROBOTS_AGENT_TOKEN.lower()
    chosen = next((g for g in groups if any(token in a for a in g[0])), None)
    if chosen is None:
        chosen = next((g for g in groups if "*" in g[0]), None)
    if chosen is None:
        return None
    winner: tuple[str, str] | None = None
    for key, value in chosen[1]:
        if not value and key == "disallow":
            continue  # `Disallow:` with nothing is "allow everything"
        pattern = value.rstrip("$")
        matches = path.startswith(pattern) if "*" not in pattern else _wildcard(path, pattern)
        if matches and (winner is None or len(value) > len(winner[1]) or (len(value) == len(winner[1]) and key == "allow")):
            winner = (key, value)
    if winner is None or winner[0] == "allow":
        return None
    label = next((a for a in chosen[0] if token in a), None) or "*"
    return f"User-agent: {label}", f"Disallow: {winner[1]}"


def _wildcard(path: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatchcase(path, pattern + "*")


def sanctioned_source(host: str) -> str | None:
    """Where this site offers its content to automated clients, when the engine can cite it."""
    host = host.lower()
    for domain, hint in config.ROBOTS_SANCTIONED_SOURCES.items():
        if host == domain or host.endswith("." + domain):
            return hint
    return None
