"""Outbound host policy -- which addresses this process is willing to fetch.

The engine fetches whatever URL it is handed. On a laptop that is exactly right: crawling
`http://localhost:8080` while developing a site is a normal thing to want. On a public
server it is a server-side request forgery hole, and a wide one, because the fetched body
is handed straight back to the caller. Every major cloud serves instance credentials over
plain HTTP from a link-local address -- `169.254.169.254` on AWS, GCP and Azure -- so an
unguarded extractor turns "paste a URL" into "read the host's service-account token".

The policy is process-wide rather than a `FetchConfig` field on purpose. A crawl reaches
`fetch_static` from a dozen call sites inside `site.py`, and a switch that has to be
threaded through every one of them is a switch that will eventually be missed at exactly
one of them. One process, one answer.

It is off by default. The library, the CLI and the test suite all legitimately fetch from
`127.0.0.1`, and a security control that breaks `make test` gets disabled rather than
fixed. The API turns it on -- see `webgraph_api.main` -- because that is the process that
takes URLs from strangers.

Known limitation: this resolves the hostname, and httpx then resolves it again. A DNS
entry that answers differently between the two lookups (a "rebinding" attack) slips past.
Closing that needs the connection pinned to the address that was checked, which means a
custom transport; it is a real hole but a much narrower one than the unguarded default,
and it is not worth the machinery until someone is actually a target.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Final
from urllib.parse import urlsplit

import httpx

__all__ = [
    "BlockedHostError",
    "check_url",
    "private_hosts_blocked",
    "set_block_private_hosts",
]

_blocked = False

_BLOCKED_NAMES: Final[frozenset[str]] = frozenset(
    {"localhost", "metadata.google.internal", "metadata.goog", "metadata"}
)
"""Names refused without asking DNS.

`metadata.google.internal` is the one that matters. It resolves to 169.254.169.254 only
from inside GCP, so a developer's laptop cannot resolve it at all -- and "does not resolve"
falls through to allowed. That is a hole that opens precisely on the host where it counts.
"""

_BLOCKED_SUFFIXES: Final[tuple[str, ...]] = (".internal", ".localhost", ".local")
"""Suffixes reserved for names that only mean something inside a network."""


class BlockedHostError(httpx.HTTPError):
    """A URL was refused by policy before any connection was made.

    Subclasses `httpx.HTTPError` so that `fetch_static`, which already turns transport
    errors into `ok=False` results, reports a blocked host the same way it reports an
    unreachable one -- as a value, not an exception that aborts a crawl of thousands.
    """


def set_block_private_hosts(enabled: bool) -> None:
    """Turn the policy on or off for this process."""
    global _blocked
    _blocked = enabled


def private_hosts_blocked() -> bool:
    return _blocked


def _as_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address a host string denotes on its own, or None if it is a name.

    Resolving literals rather than handing them to `getaddrinfo` is not an optimisation. It
    is what makes the answer the same on every platform: `127.1`, `0177.0.0.1` and
    `2130706433` all mean loopback to the C resolver, `ipaddress` rejects every one of them,
    and which of those two does the deciding is otherwise a property of the libc underneath.
    `inet_aton` accepts exactly the compressed forms an attacker would reach for, so it does
    the deciding here.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # `::ffff:127.0.0.1` is a loopback address wearing a v6 costume, and the v6 predicates
    # do not see through it. Unwrap before asking.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_global and not ip.is_multicast


def check_url(url: str) -> None:
    """Raise `BlockedHostError` if `url` must not be fetched. A no-op when the policy is off.

    Every address the host resolves to must be public: a name with one public and one
    private answer is a rebinding attempt, not a misconfiguration.
    """
    if not _blocked:
        return

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedHostError(f"refusing non-HTTP scheme: {parts.scheme or '(none)'}")

    host = parts.hostname
    if not host:
        raise BlockedHostError(f"refusing URL with no host: {url}")

    name = host.rstrip(".").lower()
    if name in _BLOCKED_NAMES or name.endswith(_BLOCKED_SUFFIXES):
        raise BlockedHostError(f"refusing to fetch a network-internal name: {host}")

    literal = _as_literal(name)
    if literal is not None:
        if not _is_public(literal):
            raise BlockedHostError(f"refusing to fetch a non-public address: {host}")
        return

    try:
        resolved = socket.getaddrinfo(host, parts.port or 0, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # Unresolvable. Let the fetch layer fail it -- its error message says more than
        # "blocked" would, and there is nothing here to protect.
        return

    for info in resolved:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if not _is_public(ip):
            raise BlockedHostError(
                f"refusing to fetch a non-public address: {host} resolves to {address}"
            )


def hook(request: httpx.Request) -> None:
    """httpx request event hook. Fires for redirect hops too, which is the point.

    Checking only the URL the caller passed is not enough: a public host is free to answer
    `302 Location: http://169.254.169.254/`, and httpx follows it. httpx runs this hook
    once per hop, so every hop is checked.
    """
    check_url(str(request.url))


def configure_from_env(default: bool = False) -> bool:
    """Read the policy from the environment and apply it. Returns what was applied.

    `WEBGRAPH_ALLOW_PRIVATE_HOSTS=1` opts out, for pointing a locally-run API at a site on
    localhost. `WEBGRAPH_BLOCK_PRIVATE_HOSTS=1` opts in. The opt-out wins when both are set,
    because the only reason to set it is that something is being blocked that should not be.
    """
    if os.environ.get("WEBGRAPH_ALLOW_PRIVATE_HOSTS") == "1":
        enabled = False
    elif os.environ.get("WEBGRAPH_BLOCK_PRIVATE_HOSTS") == "1":
        enabled = True
    else:
        enabled = default
    set_block_private_hosts(enabled)
    return enabled
