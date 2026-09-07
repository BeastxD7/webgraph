"""Settings that only matter once this runs somewhere other than a laptop.

Every case here is something that is invisible in local development and expensive in
production: an open CORS policy, an uncapped crawl, a host that will fetch its own
metadata service. They are cheap to assert and impossible to notice by hand.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from webgraph.fetch import guard

from webgraph_api import main


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


class TestAllowedOrigins:
    def test_defaults_to_the_dev_frontend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WEBGRAPH_ALLOWED_ORIGINS", raising=False)
        assert main._origins_from_env() == [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]

    def test_reads_a_comma_separated_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "WEBGRAPH_ALLOWED_ORIGINS",
            "https://webgraph.vercel.app, https://webgraph.dev",
        )
        assert main._origins_from_env() == [
            "https://webgraph.vercel.app",
            "https://webgraph.dev",
        ]

    def test_blank_entries_are_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A trailing comma in a deploy script must not become an empty allowed origin."""
        monkeypatch.setenv("WEBGRAPH_ALLOWED_ORIGINS", "https://a.example,,")
        assert main._origins_from_env() == ["https://a.example"]

    def test_wildcard_is_never_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WEBGRAPH_ALLOWED_ORIGINS", raising=False)
        assert "*" not in main._origins_from_env()


class TestPageCap:
    def test_uncapped_host_passes_the_request_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(main, "PAGE_CAP", 0)
        assert main._effective_max_pages(0) == 0
        assert main._effective_max_pages(500) == 500

    def test_unbounded_request_clamps_to_the_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The case that matters: 0 means unbounded, so it must clamp *down*, not stay 0."""
        monkeypatch.setattr(main, "PAGE_CAP", 50)
        assert main._effective_max_pages(0) == 50

    def test_oversized_request_clamps_to_the_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main, "PAGE_CAP", 50)
        assert main._effective_max_pages(5000) == 50

    def test_smaller_request_is_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main, "PAGE_CAP", 50)
        assert main._effective_max_pages(10) == 10


class TestHealthReportsPosture:
    def test_health_exposes_the_host_policy(self, client: TestClient) -> None:
        """Without this, a deployment that fetches its own metadata service looks healthy."""
        body = client.get("/api/health").json()
        assert "private_hosts_blocked" in body
        assert "max_pages" in body

    def test_health_matches_the_live_policy(self, client: TestClient) -> None:
        body = client.get("/api/health").json()
        assert body["private_hosts_blocked"] is guard.private_hosts_blocked()


class TestMetadataAddressIsRefused:
    def test_crawling_the_metadata_service_fails_when_the_policy_is_on(
        self, client: TestClient
    ) -> None:
        """The whole reason the guard exists, asserted end to end through the API.

        The suite runs with the policy off (see conftest), so this turns it on for the
        one request that must be refused.
        """
        guard.set_block_private_hosts(True)
        try:
            response = client.post(
                "/api/text",
                json={"url": "http://169.254.169.254/latest/meta-data/", "render": False},
            )
        finally:
            guard.set_block_private_hosts(False)

        assert response.status_code == 502
        assert "non-public" in response.json()["detail"]
