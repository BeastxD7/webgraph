"""Read a site's own JavaScript to find libraries that leave no other trace.

Why this is needed
------------------
A component library is invisible until one of its components opens. Radix UI writes
`data-radix-*` attributes when a popper or portal mounts; a homepage that ships a dialog but
never opens it exposes none of them, and neither the DOM, the globals, the network log nor
the markup mentions Radix at all. Wappalyzer finds it because a browser extension can read
the loaded script text. So can we.

Cost, and how it is bounded
---------------------------
Application bundles are large -- a megabyte is unremarkable. This therefore runs **once per
site** during analysis, never per page, and:

- only same-origin scripts are fetched, since third-party ones are already identified by
  their request URL and fetching them would mostly download other people's frameworks;
- at most `MAX_SCRIPTS` are read, largest-path-first being no better than source order, so
  it takes them in document order (the entry bundle is nearly always first);
- reading stops at `MAX_TOTAL_BYTES`.

The result is matched only against `source` rules, which are written to hit package names
and attribute literals -- strings a bundler preserves -- rather than prose.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urljoin, urlsplit

from webgraph.dom.blocks import parse_html
from webgraph.fetch.static import FetchConfig, fetch_static

__all__ = ["MAX_SCRIPTS", "MAX_TOTAL_BYTES", "collect_bundle_source"]

MAX_SCRIPTS: Final[int] = 4
MAX_TOTAL_BYTES: Final[int] = 3_000_000


def collect_bundle_source(
    html: str,
    base_url: str,
    *,
    config: FetchConfig | None = None,
    max_scripts: int = MAX_SCRIPTS,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> str:
    """Concatenated text of the page's own script bundles, bounded.

    Returns an empty string when there is nothing same-origin to read, which makes every
    `source` rule decline rather than guess.
    """
    if not html:
        return ""

    try:
        root = parse_html(html)
    except ValueError:
        return ""

    origin = urlsplit(base_url).hostname or ""
    if not origin:
        return ""

    sources: list[str] = []
    total = 0

    for element in root.xpath("//script[@src]"):
        if len(sources) >= max_scripts or total >= max_total_bytes:
            break
        raw = element.get("src")
        if not raw:
            continue
        absolute = urljoin(base_url, raw)
        # Same-origin only. A third-party script is already identifiable from the request
        # URL, and downloading it would mostly mean downloading someone else's framework.
        if (urlsplit(absolute).hostname or "") != origin:
            continue

        try:
            result = fetch_static(absolute, config=config)
        except Exception:
            continue
        if not result.ok or not result.html:
            continue

        body = result.html[: max_total_bytes - total]
        sources.append(body)
        total += len(body)

    return "\n".join(sources)
