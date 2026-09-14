"""Static HTTP fetching -- the cheap path, tried before any browser is started.

Most pages do not need a browser. Starting one costs hundreds of milliseconds and ~150 MB
of RSS, so the pipeline fetches statically first and escalates when the static fetch does not
produce the page.

Speaking HTTP the way a browser speaks it
-----------------------------------------
Measured on Firecrawl's scrape-evals corpus, 1,000 live URLs on 2026-09-12: **143 answered
403**. Those refusals are not about the content; they are about the client. Two things here
address that, and one deliberately does not.

* **HTTP/2 and brotli.** An earlier version negotiated HTTP/1.1 only and asked for
  `gzip, deflate`, explicitly declining brotli. Every browser on the web does the opposite.
  A CDN does not need to fingerprint anything clever to notice.
* **The header set a navigation actually carries** -- `Sec-Fetch-*`, `Upgrade-Insecure-
  Requests`, a real `Accept`. Their absence is what tells a server this is not a page load.
  Four URLs answered `406 Not Acceptable` to the old `Accept` header alone.
* **The user agent still says what this is.** Tested on those same 143 URLs: the shipped bot
  string recovers 2, a browser-shaped string that still names the crawler and carries a
  contact URL recovers 16, and a bare Chrome string with nothing identifying recovers 33.
  This module takes the middle one. The remaining 17 are the price of being contactable, and
  they are not worth a crawler that a site owner cannot identify or reach.

None of it matters as much as escalating to the real browser, which recovers **55%** of the
same 403s because it is not imitating a browser, it is one. See `webgraph.resolve`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

import httpx

from webgraph import config
from webgraph.fetch import guard

_BROWSER_PREFIX = config.USER_AGENT_BROWSER
DEFAULT_USER_AGENT = config.USER_AGENT
RETRY_STATUSES = config.RETRY_STATUSES
MAX_RETRY_WAIT_SECONDS = config.MAX_RETRY_WAIT_SECONDS
_MAX_RESPONSE_BYTES = config.FETCH_MAX_BYTES

__all__ = ["DEFAULT_USER_AGENT", "FetchConfig", "FetchResult", "fetch_static"]


def _deployment_contact() -> str:
    """`WEBGRAPH_CONTACT` as the process sees it. Read per configuration rather than at
    import so a test, or a deployment that sets it late, is not stuck with the import-time
    value."""
    from webgraph.settings import Settings

    return Settings.from_env().contact


@dataclass(frozen=True, slots=True)
class FetchConfig:
    timeout_seconds: float = config.FETCH_TIMEOUT_SECONDS
    max_redirects: int = config.FETCH_MAX_REDIRECTS
    max_bytes: int = config.FETCH_MAX_BYTES
    user_agent: str = config.USER_AGENT
    extra_headers: dict[str, str] = field(default_factory=dict)
    http2: bool = config.FETCH_HTTP2
    """Negotiate HTTP/2 when the server offers it. Falls back to HTTP/1.1 automatically."""

    retries: int = config.FETCH_RETRIES
    """Extra attempts for a `RETRY_STATUSES` answer or a transport error. One by default:
    enough for a server that said *later*, not enough to be the reason it said so."""

    respect_robots: bool = config.PAGE_RESPECT_ROBOTS
    """Ask the host's robots.txt before fetching a page (`resolve_page`). The crawl has its
    own switch, `SiteConfig.respect_robots`; this one is for a single URL."""

    contact: str = field(default_factory=lambda: _deployment_contact())
    """Who runs this client, `Name contact@example.com`, for a site that asks (see
    `declared`). From `WEBGRAPH_CONTACT`; empty means there is nothing to declare."""

    def declared(self) -> FetchConfig:
        """This configuration speaking as a declared automated client.

        The User-Agent becomes `<contact> webgraph/0.1` -- the operator first, in the form
        sec.gov documents, then the software's own name. The browser prefix goes: a client
        declaring itself has no reason to look like Chrome. Only meaningful with a contact;
        callers check `contact` before asking.
        """
        return replace(self, user_agent=f"{self.contact} {config.DECLARED_AGENT_SUFFIX}")

@dataclass(frozen=True, slots=True)
class FetchResult:
    """Outcome of a fetch. `ok` is False for transport errors as well as HTTP errors."""

    url: str
    """The final URL after redirects -- relative links must resolve against this, not the
    requested URL."""

    requested_url: str
    status: int
    html: str
    content_type: str
    elapsed_seconds: float
    ok: bool
    error: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    """Response headers, lowercased. The only place server-side technology is visible --
    `Server` and `X-Powered-By` carry Apache, PHP and OpenSSL versions that appear nowhere
    in the markup."""

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type.lower() or not self.content_type


def _headers(config: FetchConfig) -> dict[str, str]:
    """The headers a browser sends on a top-level navigation, in a browser's order.

    `Sec-Fetch-*` are the ones that matter and the ones that were missing. A server reading
    `Sec-Fetch-Mode: navigate` sees a page load; a request without them is visibly a script
    asking for a document, and several CDNs answer that differently.
    """
    return {
        "User-Agent": config.user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        # brotli included: httpx decodes it (the `brotli` dependency), and declining it was
        # both a bandwidth cost and a signal. Not zstd -- httpx does not decode it.
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        **config.extra_headers,
    }





def fetch_static(url: str, *, config: FetchConfig | None = None) -> FetchResult:
    """Fetch a URL over plain HTTP, returning a result rather than raising.

    Errors are values here, not exceptions: a crawl walks thousands of URLs and a single
    unreachable host must not abort the run. Callers inspect `ok` and `error`.
    """
    config = config or FetchConfig()
    attempts = max(1, config.retries + 1)
    last: FetchResult | None = None
    for attempt in range(attempts):
        last = _attempt(url, config)
        if last.ok or attempt == attempts - 1:
            return last
        # A transport error is worth one immediate retry; a 429 or 503 is worth one after the
        # wait the server asked for, and is not worth retrying at all when it asked for
        # longer than this call should block.
        if last.status in RETRY_STATUSES:
            wait = _retry_after_seconds(last)
            if wait is None:
                return last
            time.sleep(wait)
        elif last.status != 0:
            return last  # a definite answer: 403, 404, 500. Asking again changes nothing.
    return last if last is not None else _attempt(url, config)


def _retry_after_seconds(result: FetchResult) -> float | None:
    raw = result.headers.get("retry-after", "").strip()
    if not raw.isdigit():
        return 0.5  # no guidance, or an HTTP-date: one short, polite pause
    seconds = float(raw)
    # `Retry-After: 0` is a server saying "now" -- a legal answer, and one an earlier version
    # of this guard read as "never" because it tested `0 < seconds`. None means give up.
    return seconds if seconds <= MAX_RETRY_WAIT_SECONDS else None


def _attempt(url: str, config: FetchConfig) -> FetchResult:
    """One request. `fetch_static` decides whether there is another."""

    try:
        # The host policy runs as an event hook rather than a check on `url`, because
        # httpx calls the hook once per redirect hop. A public host answering
        # `302 Location: http://169.254.169.254/` is the whole attack, and checking only
        # the URL the caller passed would walk straight into it.
        with httpx.Client(
            http2=config.http2,
            follow_redirects=True,
            max_redirects=config.max_redirects,
            timeout=config.timeout_seconds,
            headers=_headers(config),
            event_hooks={"request": [guard.hook]},
        ) as client:
            response = client.get(url)
            body = response.content[: config.max_bytes]
            # httpx picks the encoding from headers; fall back to the declared charset in
            # the markup, then to a lossy utf-8 rather than losing the page entirely.
            try:
                text = body.decode(response.encoding or "utf-8", errors="replace")
            except (LookupError, TypeError):
                text = body.decode("utf-8", errors="replace")

            return FetchResult(
                url=str(response.url),
                requested_url=url,
                status=response.status_code,
                html=text,
                content_type=response.headers.get("content-type", ""),
                elapsed_seconds=response.elapsed.total_seconds(),
                ok=response.status_code < 400,
                error=None if response.status_code < 400 else f"HTTP {response.status_code}",
                headers={k.lower(): v for k, v in response.headers.items()},
            )
    except httpx.HTTPError as exc:
        return FetchResult(
            url=url,
            requested_url=url,
            status=0,
            html="",
            content_type="",
            elapsed_seconds=0.0,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
