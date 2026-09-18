"""What Common Crawl's index says about a host, as its own fact in the run's `discovery`:
seen (with distinct same-site addresses), not seen (the index's 404), or unavailable
(the index did not answer) -- and never an exception the crawl could die of.
"""

from __future__ import annotations

from typing import Any

import pytest

from webgraph.crawl import discovery as discovery_module
from webgraph.crawl.discovery import discover_common_crawl
from webgraph.fetch.static import FetchResult

ROOT = "https://www.example.test/"
COLLINFO = '[{"id": "CC-MAIN-2026-34", "name": "August 2026 Index"}, {"id": "CC-MAIN-2026-30"}]'
CDX = "\n".join(
    [
        '{"url": "https://www.example.test/"}',
        '{"url": "https://www.example.test/"}',  # captured twice: one address
        '{"url": "https://example.test/about"}',  # bare domain: the same site
        '{"url": "https://www.example.test/docs/a?utm_source=x"}',  # tracking stripped
        '{"url": "https://other.example/x"}',  # off-site: left out
        "not json",
    ]
)


def result(url: str, status: int, body: str) -> FetchResult:
    return FetchResult(
        url=url,
        requested_url=url,
        status=status,
        html=body,
        content_type="application/json",
        elapsed_seconds=0.01,
        ok=status < 400,
        error=None if status < 400 else f"HTTP {status}",
    )


@pytest.fixture
def index(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A fake index: `answers` maps a URL substring to (status, body)."""
    state: dict[str, Any] = {"answers": {}, "asked": []}

    def fake_fetch(url: str, **_: Any) -> FetchResult:
        state["asked"].append(url)
        for needle, (status, body) in state["answers"].items():
            if needle in url:
                return result(url, status, body)
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(discovery_module, "fetch_static", fake_fetch)
    return state


def test_seen(index: dict[str, Any]) -> None:
    index["answers"] = {"collinfo.json": (200, COLLINFO), "CC-MAIN-2026-34-index": (200, CDX)}
    listing = discover_common_crawl(ROOT)
    assert listing.status == "seen"
    assert listing.index == "CC-MAIN-2026-34" and listing.index_name == "August 2026 Index"
    assert listing.records == 5
    assert listing.urls == (
        "https://www.example.test/",
        "https://example.test/about",
        "https://www.example.test/docs/a",
    )
    assert listing.as_dict()["urls"] == 3 and listing.as_dict()["sample"][0] == ROOT
    # The newest index was the one queried, for this host, status 200 only.
    assert "url=www.example.test/*" in index["asked"][1] and "status:200" in index["asked"][1]


def test_not_seen_is_the_indexs_404(index: dict[str, Any]) -> None:
    index["answers"] = {"collinfo.json": (200, COLLINFO), "-index": (404, "")}
    listing = discover_common_crawl(ROOT)
    assert listing.status == "not-seen" and listing.index == "CC-MAIN-2026-34"
    assert listing.urls == () and listing.error is None


def test_unavailable_is_never_an_exception(index: dict[str, Any]) -> None:
    index["answers"] = {"collinfo.json": (503, "")}
    listing = discover_common_crawl(ROOT)
    assert listing.status == "unavailable" and "503" in (listing.error or "")

    index["answers"] = {"collinfo.json": (200, "not json at all")}
    assert discover_common_crawl(ROOT).status == "unavailable"

    index["answers"] = {"collinfo.json": (200, COLLINFO), "-index": (500, "")}
    listing = discover_common_crawl(ROOT)
    assert listing.status == "unavailable" and listing.index == "CC-MAIN-2026-34"
