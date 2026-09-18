"""Shared test setup for the engine.

`resolve_page` asks a host's robots.txt before fetching a page (PR #83). Tests that stub
`resolve.fetch_static` to serve one page would otherwise reach the real host for its
robots.txt -- and a stubbed reddit.com wall was refused by the real reddit.com's
`Disallow: /` before the wall check ever ran. Here every host has no robots.txt unless a
test says otherwise (`test_page_robots.py` installs its own), and the per-host cache is
emptied around each test so one test's file is not another's.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from webgraph.fetch import robots
from webgraph.fetch.static import FetchConfig, FetchResult


@pytest.fixture(autouse=True)
def no_robots_on_the_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def missing(url: str, *, config: FetchConfig | None = None) -> FetchResult:  # noqa: ARG001
        return FetchResult(
            url=url,
            requested_url=url,
            status=404,
            html="",
            content_type="text/html",
            elapsed_seconds=0.0,
            ok=False,
            error="HTTP 404",
        )

    monkeypatch.setattr(robots, "fetch_static", missing)
    robots.forget()
    yield
    robots.forget()


@pytest.fixture(autouse=True)
def no_common_crawl_on_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """A crawl asks Common Crawl's index about the host at stage 0. Not from a test: the
    index is answered as unavailable, which is what a crawl reports when it does not
    answer, and `test_common_crawl.py` fakes the index itself when it wants an answer."""
    from webgraph import site as site_module
    from webgraph.crawl.discovery import CommonCrawlListing

    monkeypatch.setattr(
        site_module,
        "discover_common_crawl",
        lambda *_args, **_kwargs: CommonCrawlListing(
            status="unavailable", error="not asked in tests"
        ),
    )
