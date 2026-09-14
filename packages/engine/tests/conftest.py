"""Shared test setup for the engine.

`resolve_page` asks a host's robots.txt before fetching a page (PR #84). Tests that stub
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
