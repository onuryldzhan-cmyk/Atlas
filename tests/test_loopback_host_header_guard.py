"""DNS-rebinding defence: the loopback guard also validates the Host header.

``observability.panel_router.is_loopback_request`` is the single guard for the
whole operator surface. A loopback peer address is not enough on its own: a
DNS-rebinding page makes the victim's browser connect to 127.0.0.1 while still
sending ``Host: attacker.example``. These tests pin that such a request is
refused on every guarded route, that every legitimate loopback access pattern
still works, and - over a real socket, where the in-process TestClient identity
does not exist - that the refusal holds against real HTTP parsing too.

No test here attaches an Atlas runtime or writes any state.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from observability.panel_router import (
    build_observability_router,
    is_loopback_request,
)
from web_app import create_app


HOSTILE_HOSTS = [
    "attacker.example",
    "attacker.example:8000",
    "127.0.0.1.attacker.example",
    "localhost.attacker.example:8000",
    "evil-localhost",
    "0.0.0.0:8000",
    "127.0.0.2:8000",
    "[::2]:8000",
    "testserver:8000",
]

MALFORMED_HOSTS = [
    "",
    ":8000",
    "127.0.0.1:",
    "127.0.0.1:abc",
    "127.0.0.1:0",
    "127.0.0.1:65536",
    "127.0.0.1:8000:1",
    "127.0.0.1:+80",
    "127.0.0.1:٨٠",  # non-ASCII digits
    "user@127.0.0.1",
    "::1",
    "[::1",
    "[::1]8000",
    "[::1]:",
    "localhost.",
    " 127.0.0.1",
]

LEGITIMATE_HOSTS = [
    "127.0.0.1",
    "127.0.0.1:8000",
    "localhost",
    "localhost:8000",
    "LOCALHOST:8000",
    "[::1]",
    "[::1]:8000",
    "127.0.0.1:9000",  # a local port-forward changes the port, not the name
]

# Every route the guard protects on the web application, and the three
# observability panel routes it mounts. The completeness test below fails if
# a GET route is added without being listed here.
WEB_APP_GUARDED_ROUTES = [
    "/",
    "/dashboard",
    "/api/health",
    "/api/status",
    "/api/analysis",
    "/api/signals",
    "/api/trades",
    "/api/agent-evidence",
    "/api/organization",
    "/api/proposals",
    "/api/memory",
    "/api/permissions",
    "/api/tasks",
    "/api/command-center",
    "/api/chat",
    "/api/portfolio",
    "/agents",
    "/hq",
    "/home",
    "/trading",
    "/governance",
    "/system",
    "/security",
    "/api/security",
    "/roadmap",
    "/api/roadmap",
    "/research",
    "/decisions",
    "/postmortem",  # Dashboard v2 post-mortem page (2026-10-01), read-only
    "/api/agent-states",
    "/api/learning",
    "/api/events",  # Atlas Event Contract v1 (2026-10-01), read-only
    "/api/candles",
    "/api/research",
    "/api/experience",
    "/api/liveness",
    "/api/readiness",
    "/api/risk-accounting",
    "/api/system-integrity",
    "/api/execution-gates",
    "/assets/chart.umd.min.js",
    "/api/observability/test-results",
    "/api/observability/governance",
    "/api/observability/telemetry-summary",
    "/docs",
    "/redoc",
    "/openapi.json",
]

# FastAPI's own schema/documentation routes are switched off via
# docs_url=None/redoc_url=None/openapi_url=None in create_app(); this
# application defines its own guarded /docs, /redoc and /openapi.json
# instead (registry v4.86/v4.87 A2 backlog closure), so no auto-created
# oauth2-redirect route exists to exempt here.
FRAMEWORK_ROUTES: set[str] = set()


def _request(
    *,
    peer: tuple[str, int] | None = ("127.0.0.1", 50000),
    host_headers: list[str] | None = None,
) -> Request:
    headers = [
        (b"host", value.encode("utf-8")) for value in (host_headers or [])
    ]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": peer,
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
    }

    return Request(scope)


class _RecordingPriceProvider:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def __call__(self, symbol: str) -> float:
        self.requested.append(symbol)
        return 1.0


# =====================================================================
# PREDICATE
# =====================================================================


@pytest.mark.parametrize("host", LEGITIMATE_HOSTS)
@pytest.mark.parametrize("peer", ["127.0.0.1", "127.8.9.10", "::1", "::ffff:127.0.0.1"])
def test_loopback_peer_with_loopback_host_is_accepted(peer: str, host: str) -> None:
    assert is_loopback_request(_request(peer=(peer, 50000), host_headers=[host]))


@pytest.mark.parametrize("host", HOSTILE_HOSTS + MALFORMED_HOSTS)
def test_loopback_peer_with_foreign_or_malformed_host_is_refused(host: str) -> None:
    """The DNS-rebinding shape: a loopback peer under a non-loopback name."""

    assert not is_loopback_request(
        _request(peer=("127.0.0.1", 50000), host_headers=[host])
    )


def test_missing_host_header_is_refused() -> None:
    """HTTP/1.0 or a raw socket without Host: fail closed."""

    assert not is_loopback_request(_request(host_headers=[]))


@pytest.mark.parametrize(
    "hosts",
    [
        ["127.0.0.1:8000", "127.0.0.1:8000"],
        ["127.0.0.1:8000", "attacker.example"],
        ["attacker.example", "127.0.0.1:8000"],
    ],
)
def test_repeated_host_headers_are_refused(hosts: list[str]) -> None:
    assert not is_loopback_request(_request(host_headers=hosts))


@pytest.mark.parametrize("host", LEGITIMATE_HOSTS)
def test_non_loopback_peer_is_still_refused_with_a_loopback_host(host: str) -> None:
    """The Host check is added to the peer check, never substituted for it."""

    assert not is_loopback_request(
        _request(peer=("203.0.113.7", 44321), host_headers=[host])
    )


def test_request_without_a_peer_is_refused() -> None:
    assert not is_loopback_request(_request(peer=None, host_headers=["127.0.0.1"]))


def test_testserver_host_is_accepted_only_from_the_in_process_peer() -> None:
    assert is_loopback_request(
        _request(peer=("testclient", 50000), host_headers=["testserver"])
    )

    for peer in ("127.0.0.1", "::1"):
        assert not is_loopback_request(
            _request(peer=(peer, 50000), host_headers=["testserver"])
        )


@pytest.mark.parametrize("host", HOSTILE_HOSTS + MALFORMED_HOSTS)
def test_in_process_peer_does_not_relax_the_host_check(host: str) -> None:
    assert not is_loopback_request(
        _request(peer=("testclient", 50000), host_headers=[host])
    )


# =====================================================================
# EVERY GUARDED ROUTE
# =====================================================================


def test_route_list_covers_every_get_route_of_the_web_application() -> None:
    application = create_app()

    def _flatten(routes):
        for route in routes:
            # FastAPI wraps an included router instead of copying its routes.
            included = getattr(route, "original_router", None)
            if included is not None:
                yield from _flatten(included.routes)
            else:
                yield route

    get_paths = {
        route.path
        for route in _flatten(application.routes)
        if "GET" in (getattr(route, "methods", None) or set())
    } - FRAMEWORK_ROUTES

    # The wrapper must not hide routes from this check.
    assert "/api/observability/governance" in get_paths

    listed = {
        "/assets/{asset_name}" if path.startswith("/assets/") else path
        for path in WEB_APP_GUARDED_ROUTES
    }

    assert get_paths == listed


@pytest.mark.parametrize("route", WEB_APP_GUARDED_ROUTES)
@pytest.mark.parametrize("host", ["attacker.example", "attacker.example:8000"])
def test_every_guarded_route_refuses_a_rebinding_host(route: str, host: str) -> None:
    provider = _RecordingPriceProvider()
    client = TestClient(
        create_app(price_provider=provider),
        client=("127.0.0.1", 50000),
    )

    response = client.get(route, headers={"host": host})

    assert response.status_code == 403, route
    assert response.json()["status"] == "FORBIDDEN"
    assert response.json()["reason"] in {
        "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY",
        "OBSERVABILITY_PANEL_IS_LOCALHOST_ONLY",
    }

    # A refused request must not even induce a price lookup.
    assert provider.requested == []


@pytest.mark.parametrize("route", WEB_APP_GUARDED_ROUTES)
@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "[::1]:8000"])
@pytest.mark.parametrize("peer", ["127.0.0.1", "::1"])
def test_every_guarded_route_serves_a_loopback_host(
    route: str, host: str, peer: str
) -> None:
    client = TestClient(create_app(), client=(peer, 50000))

    response = client.get(route, headers={"host": host})

    assert response.status_code != 403, (route, response.text)

    if response.headers.get("content-type", "").startswith("application/json"):
        body = response.json()
        assert not (isinstance(body, dict) and body.get("status") == "FORBIDDEN")


def test_observability_router_refuses_a_rebinding_host(tmp_path: Path) -> None:
    application = FastAPI()
    application.include_router(build_observability_router(repository_root=tmp_path))
    client = TestClient(application, client=("127.0.0.1", 50000))

    for route in ("test-results", "governance", "telemetry-summary"):
        refused = client.get(
            f"/api/observability/{route}", headers={"host": "attacker.example"}
        )
        served = client.get(
            f"/api/observability/{route}", headers={"host": "127.0.0.1:8000"}
        )

        assert refused.status_code == 403
        assert refused.json()["reason"] == "OBSERVABILITY_PANEL_IS_LOCALHOST_ONLY"
        assert served.status_code != 403


# =====================================================================
# REAL SOCKET
# =====================================================================


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="module")
def live_port():
    """Serve ``create_app()`` over a real 127.0.0.1 socket, as web_app does."""

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app=create_app(),
            host="127.0.0.1",
            port=port,
            proxy_headers=False,
            forwarded_allow_ips=[],
            log_config=None,
            reload=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 20.0
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            server.should_exit = True
            pytest.fail("uvicorn did not start")
        time.sleep(0.05)

    try:
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=20.0)


def _raw_get(port: int, path: str, head: str) -> tuple[int, bytes]:
    request = f"GET {path} {head}\r\nConnection: close\r\n\r\n".encode("latin-1")

    with socket.create_connection(("127.0.0.1", port), timeout=10.0) as connection:
        connection.sendall(request)
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)

    response = b"".join(chunks)
    status = int(response.split(b" ", 2)[1])

    return status, response


@pytest.mark.parametrize("route", ["/dashboard", "/api/health", "/assets/chart.umd.min.js"])
def test_real_socket_rebinding_request_is_refused(live_port: int, route: str) -> None:
    status, body = _raw_get(
        live_port, route, f"HTTP/1.1\r\nHost: attacker.example:{live_port}"
    )

    assert status == 403
    assert b"ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY" in body


@pytest.mark.parametrize(
    "host", ["127.0.0.1:{port}", "localhost:{port}", "[::1]:{port}", "127.0.0.1"]
)
def test_real_socket_operator_access_is_served(live_port: int, host: str) -> None:
    status, _ = _raw_get(
        live_port, "/dashboard", f"HTTP/1.1\r\nHost: {host.format(port=live_port)}"
    )

    assert status == 200


def test_real_socket_cannot_reach_the_in_process_test_carve_out(live_port: int) -> None:
    """Over a socket the peer is 127.0.0.1, never "testclient"."""

    status, body = _raw_get(live_port, "/dashboard", "HTTP/1.1\r\nHost: testserver")

    assert status == 403
    assert b"ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY" in body


def test_real_socket_duplicate_host_headers_are_not_served(live_port: int) -> None:
    status, _ = _raw_get(
        live_port,
        "/dashboard",
        f"HTTP/1.1\r\nHost: 127.0.0.1:{live_port}\r\nHost: attacker.example",
    )

    # Refused before or at the guard; never served.
    assert status in {400, 403}


def test_real_socket_http10_without_host_is_refused(live_port: int) -> None:
    status, body = _raw_get(live_port, "/dashboard", "HTTP/1.0")

    assert status == 403
    assert b"ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY" in body
