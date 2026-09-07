"""Outbound host policy tests.

This is the control that makes the service safe to point at the public internet, so the
cases here are the ones an attacker would actually try: the cloud metadata address, the
RFC1918 ranges, loopback spelled six different ways, and a redirect used to launder a
public hostname into a private address.
"""

from __future__ import annotations

import http.server
import socket
import socketserver
import threading
from collections.abc import Iterator

import httpx
import pytest

from webgraph.fetch import guard
from webgraph.fetch.static import fetch_static


@pytest.fixture(autouse=True)
def _reset_policy() -> Iterator[None]:
    """The policy is process-wide. Leaking it between tests would be a silent disaster."""
    before = guard.private_hosts_blocked()
    yield
    guard.set_block_private_hosts(before)


class TestPolicyOff:
    """The default. The CLI, the benchmarks and most of this suite fetch from localhost."""

    def test_loopback_is_allowed(self) -> None:
        guard.set_block_private_hosts(False)
        guard.check_url("http://127.0.0.1:8000/page")

    def test_metadata_address_is_allowed(self) -> None:
        guard.set_block_private_hosts(False)
        guard.check_url("http://169.254.169.254/latest/meta-data/")


class TestPolicyOn:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8000/",
            "http://localhost/",
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://10.0.0.5/admin",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
            "http://0.0.0.0/",
        ],
    )
    def test_non_public_addresses_are_refused(self, url: str) -> None:
        guard.set_block_private_hosts(True)
        with pytest.raises(guard.BlockedHostError):
            guard.check_url(url)

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://example.com/", "ftp://x/"])
    def test_non_http_schemes_are_refused(self, url: str) -> None:
        guard.set_block_private_hosts(True)
        with pytest.raises(guard.BlockedHostError):
            guard.check_url(url)

    def test_public_literal_is_allowed(self) -> None:
        """An IP literal needs no DNS, so this case stays offline."""
        guard.set_block_private_hosts(True)
        guard.check_url("https://93.184.216.34/")

    def test_unresolvable_host_is_left_to_the_fetch_layer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Blocking here would replace a useful DNS error with a misleading security one.

        The failure is forced rather than reached through a real lookup: a resolver that
        hijacks NXDOMAIN would otherwise make this test's outcome depend on whose network
        it runs on.
        """

        def _fail(*_args: object, **_kwargs: object) -> None:
            raise socket.gaierror("forced")

        monkeypatch.setattr(guard.socket, "getaddrinfo", _fail)
        guard.set_block_private_hosts(True)
        guard.check_url("https://not-a-real-host.invalid/")

    @pytest.mark.parametrize("host", ["127.1", "0177.0.0.1", "2130706433"])
    def test_compressed_loopback_forms_are_refused_without_dns(
        self, host: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """These reach loopback through the C resolver but are not valid to `ipaddress`.

        DNS is disabled for the duration so this asserts the literal parser, not glibc:
        `127.1` resolving is a libc behaviour and the guard must not depend on it.
        """

        def _fail(*_args: object, **_kwargs: object) -> None:
            raise socket.gaierror("dns should not be consulted")

        monkeypatch.setattr(guard.socket, "getaddrinfo", _fail)
        guard.set_block_private_hosts(True)
        with pytest.raises(guard.BlockedHostError):
            guard.check_url(f"http://{host}/")


class TestRedirectsAreChecked:
    def test_hook_fires_on_a_private_hop(self) -> None:
        """`fetch_static` registers this per-request, which is what covers redirects.

        The attack is a public host answering `302 Location: http://169.254.169.254/`;
        httpx follows it, and only a per-hop check sees the second address.
        """
        guard.set_block_private_hosts(True)
        with pytest.raises(guard.BlockedHostError):
            guard.hook(httpx.Request("GET", "http://169.254.169.254/"))

    def test_blocked_host_is_an_httpx_error(self) -> None:
        """So a crawl of thousands reports it as a failed page, not an aborted run."""
        assert issubclass(guard.BlockedHostError, httpx.HTTPError)


class _Redirector(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body><p>local</p></body></html>")

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def local_server() -> Iterator[str]:
    server = socketserver.TCPServer(("127.0.0.1", 0), _Redirector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


class TestFetchStatic:
    def test_serves_localhost_with_the_policy_off(self, local_server: str) -> None:
        guard.set_block_private_hosts(False)
        result = fetch_static(f"{local_server}/page")
        assert result.ok
        assert "local" in result.html

    def test_refuses_localhost_with_the_policy_on(self, local_server: str) -> None:
        """A value, not an exception -- the crawl must survive a blocked URL."""
        guard.set_block_private_hosts(True)
        result = fetch_static(f"{local_server}/page")
        assert not result.ok
        assert result.error is not None
        assert "non-public" in result.error
        assert result.html == ""


class TestConfigureFromEnv:
    def test_defaults_to_the_argument(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WEBGRAPH_ALLOW_PRIVATE_HOSTS", raising=False)
        monkeypatch.delenv("WEBGRAPH_BLOCK_PRIVATE_HOSTS", raising=False)
        assert guard.configure_from_env(default=True) is True
        assert guard.configure_from_env(default=False) is False

    def test_opt_out_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both set means someone is trying to unblock something. Let them."""
        monkeypatch.setenv("WEBGRAPH_ALLOW_PRIVATE_HOSTS", "1")
        monkeypatch.setenv("WEBGRAPH_BLOCK_PRIVATE_HOSTS", "1")
        assert guard.configure_from_env(default=True) is False
