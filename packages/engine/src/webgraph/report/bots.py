"""What a site's robots.txt declares for each well-known AI and search bot.

Declares, not does. The engine never fetches as another bot -- no GPTBot User-Agent, no
Googlebot -- because a client that borrows another operator's name is asking a site to
apply a policy it did not set for it, and the answer would be a measurement of the disguise
rather than of the site. What can be measured honestly is the file: the site wrote, in
public, a rule for each name it chose to mention, and this module reads those rules the
way the bot itself would (RFC 9309 §2.2.1): the groups whose `User-agent:` equals the bot's
product token, case-insensitively, combined; the `*` group when none names it; nothing
when there is no file. `Googlebot-Image` in the file does not govern Googlebot, and a
site that names no bot at all has said nothing about any of them.

The verdict per bot is read at the root, `/`, by the same longest-match rule the crawl's
own refusals use (`fetch.robots.rule_that_applied`): `blocked` when the root is disallowed,
`partly` (partly restricted) when content paths are, `allowed` otherwise -- where "content"
excludes the administrative paths nearly every file disallows (`ADMIN_PATHS`: `/wp-admin/`,
`/cgi-bin/`, `/login`, `/search`, a bare query string ...). Measured on vtu.ac.in, the
first version called every bot "restricted" because `*` disallowed `/wp-admin/`, which an
owner reads as "all AI bots restricted" and is false.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from webgraph.crawl.discovery import RobotsGroup, parse_groups

__all__ = [
    "ADMIN_PATHS",
    "BOTS",
    "BotPolicy",
    "WellKnownBot",
    "declared_policies",
    "is_administrative",
    "policy_for_bot",
]

Purpose = Literal["search", "assistant", "training"]
Access = Literal["allowed", "partly", "blocked"]
Via = Literal["named", "wildcard", "none"]

ADMIN_PATHS: Final[frozenset[str]] = frozenset(
    {
        "wp-admin",
        "wp-login.php",
        "wp-includes",
        "wp-json",
        "xmlrpc.php",
        "wp-content/plugins",
        "wp-content/cache",
        "cgi-bin",
        "admin",
        "administrator",
        "login",
        "logout",
        "signin",
        "signup",
        "register",
        "account",
        "my-account",
        "cart",
        "checkout",
        "search",
        "tmp",
        "cdn-cgi",
        "api",
        "_next",
        "static",
        "assets",
    }
)
"""First path segments (or `segment/segment`) that a robots.txt disallows for housekeeping,
not to keep content from anyone: the CMS back office, sign-in and account pages, the cart,
site search, build assets. A `Disallow` on one of these is not a restriction on reading the
site. Small and literal on purpose; a path not here is content until shown otherwise."""


@dataclass(frozen=True, slots=True)
class WellKnownBot:
    """A crawler a site owner is likely to have an opinion about.

    `purpose` is what the operator documents the bot as doing, and is data rather than a
    verdict: `search` indexes for a search product, `assistant` fetches a page a user asked
    an assistant about, `training` gathers text for model training. The suggested
    robots.txt's "allow search, disallow training" variant is built from it, and it will
    need correcting as operators change their documentation.
    """

    token: str
    operator: str
    purpose: Purpose


BOTS: Final[tuple[WellKnownBot, ...]] = (
    WellKnownBot("GPTBot", "OpenAI", "training"),
    WellKnownBot("ChatGPT-User", "OpenAI", "assistant"),
    WellKnownBot("OAI-SearchBot", "OpenAI", "search"),
    WellKnownBot("ClaudeBot", "Anthropic", "training"),
    WellKnownBot("Claude-Web", "Anthropic", "assistant"),
    WellKnownBot("anthropic-ai", "Anthropic", "training"),
    WellKnownBot("PerplexityBot", "Perplexity", "search"),
    WellKnownBot("Google-Extended", "Google", "training"),
    WellKnownBot("Googlebot", "Google", "search"),
    WellKnownBot("Bingbot", "Microsoft", "search"),
    WellKnownBot("CCBot", "Common Crawl", "training"),
    WellKnownBot("Applebot-Extended", "Apple", "training"),
    WellKnownBot("meta-externalagent", "Meta", "training"),
    WellKnownBot("Bytespider", "ByteDance", "training"),
    WellKnownBot("Amazonbot", "Amazon", "search"),
)


@dataclass(frozen=True, slots=True)
class BotPolicy:
    """What the file says about one bot, and the lines it says it in."""

    token: str
    operator: str
    purpose: Purpose
    via: Via
    """`named` when a group names the bot, `wildcard` when only `*` applies, `none` when
    the file has no group for it at all (or there is no file)."""
    access: Access
    """At the root: `blocked` when `/` is disallowed, `partly` when content paths are
    (`content_paths`), `allowed` when nothing is, only administrative paths are, or the
    file says nothing."""
    disallowed: int
    """How many `Disallow:` lines apply to it and decide something."""
    content_paths: tuple[str, ...]
    """The disallowed paths that are not administrative (`ADMIN_PATHS`), in file order."""
    crawl_delay: float | None
    lines: tuple[str, ...]
    """The directives that apply, verbatim from the file (Allow, Disallow, Crawl-delay)."""

    @property
    def mentioned(self) -> bool:
        return self.via == "named"

    def as_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "operator": self.operator,
            "purpose": self.purpose,
            "via": self.via,
            "mentioned": self.mentioned,
            "access": self.access,
            "disallowed": self.disallowed,
            "content_paths": list(self.content_paths),
            "crawl_delay": self.crawl_delay,
            "lines": list(self.lines),
        }


def _product_token(agent: str) -> str:
    """`GPTBot/1.0` in a file names `GPTBot`; the version is not part of the name."""
    return agent.split("/", 1)[0].strip().lower()


def _groups_for(groups: tuple[RobotsGroup, ...], token: str) -> tuple[list[RobotsGroup], Via]:
    wanted = token.lower()
    named = [g for g in groups if any(_product_token(a) == wanted for a in g.agents)]
    if named:
        return named, "named"
    wildcard = [g for g in groups if "*" in g.agents]
    if wildcard:
        return wildcard, "wildcard"
    return [], "none"


def _matches(path: str, pattern: str) -> bool:
    """robots.txt path matching: `*` is any run of characters, a trailing `$` anchors the
    end, and everything else -- `?` included -- is literal. Not `fnmatch`, whose `?` and
    `[` are wildcards: `Disallow: /*?` would have matched `/` and blocked the root."""
    anchored = pattern.endswith("$")
    body = pattern.rstrip("$")
    if "*" not in body:
        return path == body if anchored else path.startswith(body)
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.fullmatch(regex + ("" if anchored else ".*"), path) is not None


def decides(rules: tuple[tuple[str, str], ...], path: str) -> tuple[str, str] | None:
    """The `(allow|disallow, pattern)` that decides `path`: the longest matching pattern
    wins, `Allow` beats `Disallow` at equal length, an empty `Disallow:` matches nothing.
    None when no rule matches, which means allowed."""
    winner: tuple[str, str] | None = None
    for key, value in rules:
        if not value:
            continue
        if not _matches(path, value):
            continue
        if (
            winner is None
            or len(value) > len(winner[1])
            or (len(value) == len(winner[1]) and key == "allow")
        ):
            winner = (key, value)
    return winner


def _example_path(pattern: str) -> str:
    """A path the pattern matches, to ask whether the rule decides anything: the pattern
    itself, each `*` standing for one character, without `$` (`/*?` -> `/x?`)."""
    return pattern.rstrip("$").replace("*", "x") or "/"


def is_administrative(pattern: str) -> bool:
    """Whether a `Disallow` pattern names housekeeping rather than content: one of
    `ADMIN_PATHS` as its first segment (or first two), or a bare query-string pattern
    (`/*?`, `/?`, `/*?*`), which forbids URL variants and no page."""
    body = pattern.rstrip("$")
    literal = body.split("*", 1)[0].strip("/")
    if "?" in body and not literal.split("?", 1)[0]:
        return True
    head = literal.split("?", 1)[0]
    segments = head.split("/")
    first = segments[0].lower()
    two = "/".join(segments[:2]).lower()
    return bool(first) and (first in ADMIN_PATHS or two in ADMIN_PATHS)


def _crawl_delay(lines: tuple[str, ...]) -> float | None:
    for line in lines:
        key, _, value = line.partition(":")
        if key.strip().lower() == "crawl-delay":
            try:
                return float(value.strip())
            except ValueError:
                return None
    return None


def policy_for_bot(robots: str, bot: WellKnownBot) -> BotPolicy:
    """What `robots` declares for `bot`, read as the bot would read it."""
    applying, via = _groups_for(parse_groups(robots), bot.token)
    rules: tuple[tuple[str, str], ...] = tuple(r for g in applying for r in g.rules)
    lines: tuple[str, ...] = tuple(line for g in applying for line in g.lines)
    # A Disallow counts only where it decides something: `Disallow: /` beside `Allow: /`
    # forbids nothing, because the Allow wins every path at equal length.
    deciding = [
        value
        for key, value in rules
        if key == "disallow"
        and value
        and (decides(rules, _example_path(value)) or ("",))[0] == "disallow"
    ]
    content = tuple(dict.fromkeys(v for v in deciding if not is_administrative(v)))
    verdict = decides(rules, "/")
    if verdict is not None and verdict[0] == "disallow":
        access: Access = "blocked"
    elif content:
        access = "partly"
    else:
        access = "allowed"
    return BotPolicy(
        token=bot.token,
        operator=bot.operator,
        purpose=bot.purpose,
        via=via,
        access=access,
        disallowed=len(deciding),
        content_paths=content,
        crawl_delay=_crawl_delay(lines),
        lines=lines,
    )


def declared_policies(robots: str | None) -> tuple[BotPolicy, ...]:
    """One `BotPolicy` per well-known bot. No file (`None`) means every bot is allowed and
    none is mentioned -- the convention every crawler follows, recorded as such."""
    return tuple(policy_for_bot(robots or "", bot) for bot in BOTS)
