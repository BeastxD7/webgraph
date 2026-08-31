"""Static HTTP fetching -- the cheap path, tried before any browser is started.

Most pages do not need a browser. Starting one costs hundreds of milliseconds and ~150 MB
of RSS, so the pipeline fetches statically first and escalates only when the profiler says
the returned HTML is a shell rather than the content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import httpx

__all__ = ["DEFAULT_USER_AGENT", "FetchConfig", "FetchResult", "fetch_static"]

DEFAULT_USER_AGENT: Final[str] = (
    "webgraph/0.1 (+https://github.com/webgraph/webgraph; structured-extraction bot)"
)
"""Identifiable by design. An anonymous or spoofed agent string makes a crawler
indistinguishable from an abusive one and gives site owners no way to contact us."""

_MAX_RESPONSE_BYTES: Final[int] = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FetchConfig:
    timeout_seconds: float = 20.0
    max_redirects: int = 5
    max_bytes: int = _MAX_RESPONSE_BYTES
    user_agent: str = DEFAULT_USER_AGENT
    extra_headers: dict[str, str] = field(default_factory=dict)


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
    return {
        "User-Agent": config.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # Explicitly not requesting brotli/zstd beyond what httpx handles natively.
        "Accept-Encoding": "gzip, deflate",
        **config.extra_headers,
    }


def fetch_static(url: str, *, config: FetchConfig | None = None) -> FetchResult:
    """Fetch a URL over plain HTTP, returning a result rather than raising.

    Errors are values here, not exceptions: a crawl walks thousands of URLs and a single
    unreachable host must not abort the run. Callers inspect `ok` and `error`.
    """
    config = config or FetchConfig()

    try:
        with httpx.Client(
            follow_redirects=True,
            max_redirects=config.max_redirects,
            timeout=config.timeout_seconds,
            headers=_headers(config),
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
