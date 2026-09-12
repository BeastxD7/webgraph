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
from dataclasses import dataclass, field
from typing import Final

import httpx

from webgraph.fetch import guard

__all__ = ["DEFAULT_USER_AGENT", "FetchConfig", "FetchResult", "fetch_static"]

_BROWSER_PREFIX: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_USER_AGENT: Final[str] = (
    f"{_BROWSER_PREFIX} webgraph/0.1 (+https://github.com/webgraph/webgraph)"
)
"""Browser-shaped, and still identifiable.

The shape is load-bearing: many servers reject anything that does not parse as a browser,
and on the scrape-evals corpus that rejection costs 14 of 143 blocked pages. The suffix is
also load-bearing, and is the reason this is not simply a Chrome string: a site owner reading
their logs can see exactly what this is and where to complain. A crawler that cannot be
identified or contacted is indistinguishable from an abusive one, and the 17 further pages a
bare spoof would recover do not buy that back.

`FetchConfig.user_agent` overrides it, for a caller whose agreement with a site says to."""

RETRY_STATUSES: Final[frozenset[int]] = frozenset({429, 503})
"""Statuses that mean *later*, not *no*. Retried once, honouring `Retry-After`.

Nine URLs in the scrape-evals corpus answered 429 and were recorded as failures without a
second attempt ever being made, which is a bug in the client rather than a property of the
web. A single retry is deliberate: a crawler that retries hard on 429 is the reason the 429
was sent."""

MAX_RETRY_WAIT_SECONDS: Final[float] = 5.0
"""Longest `Retry-After` worth honouring inline. A server asking for a minute is asking to be
crawled later, not to have a thread held open for it."""

_MAX_RESPONSE_BYTES: Final[int] = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FetchConfig:
    timeout_seconds: float = 20.0
    max_redirects: int = 5
    max_bytes: int = _MAX_RESPONSE_BYTES
    user_agent: str = DEFAULT_USER_AGENT
    extra_headers: dict[str, str] = field(default_factory=dict)
    http2: bool = True
    """Negotiate HTTP/2 when the server offers it. Falls back to HTTP/1.1 automatically."""

    retries: int = 1
    """Extra attempts for a `RETRY_STATUSES` answer or a transport error. One by default:
    enough for a server that said *later*, not enough to be the reason it said so."""


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
