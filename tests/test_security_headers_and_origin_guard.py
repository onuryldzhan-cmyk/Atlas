"""Defense-in-depth: CSP/security headers, guarded docs, and Origin checks.

Closes three registry v4.86/v4.87 backlog items for the operator web
surface: (A2) no CSP/security headers on any response, (B) FastAPI's
/docs, /openapi.json and /redoc were unguarded, and (C) POST /login had no
Origin check even though the Host+peer guard alone does not stop a hostile
page on another local port from issuing the request (browser same-origin
policy still stops it from reading the response, but the server should not
rely on that alone).

No test here attaches an Atlas runtime or writes any state.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from observability.panel_router import is_same_origin_request
from web_app import SECURITY_HEADERS, create_app


def _client() -> TestClient:
    return TestClient(create_app(), client=("127.0.0.1", 50000))


# =====================================================================
# SECURITY HEADERS
# =====================================================================


@pytest.mark.parametrize(
    "route",
    ["/dashboard", "/api/health", "/docs", "/openapi.json", "/redoc"],
)
def test_security_headers_present_on_served_routes(route: str) -> None:
    response = _client().get(route, headers={"host": "127.0.0.1:8000"})

    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, (route, name)


def test_security_headers_present_even_on_a_refused_response() -> None:
    """A 403 is still a response from this operator surface."""

    response = _client().get("/dashboard", headers={"host": "attacker.example"})

    assert response.status_code == 403

    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value


def test_csp_denies_framing_and_third_party_script_sources() -> None:
    csp = SECURITY_HEADERS["Content-Security-Policy"]

    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "default-src 'self'" in csp


# =====================================================================
# GUARDED /docs, /openapi.json, /redoc
# =====================================================================


@pytest.mark.parametrize("route", ["/docs", "/openapi.json", "/redoc"])
def test_docs_routes_refuse_a_rebinding_host(route: str) -> None:
    response = _client().get(route, headers={"host": "attacker.example"})

    assert response.status_code == 403
    assert response.json()["reason"] == "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"


@pytest.mark.parametrize("route", ["/docs", "/openapi.json", "/redoc"])
def test_docs_routes_serve_a_loopback_host(route: str) -> None:
    response = _client().get(route, headers={"host": "127.0.0.1:8000"})

    assert response.status_code == 200


def test_openapi_json_is_the_real_schema_when_served() -> None:
    response = _client().get("/openapi.json", headers={"host": "127.0.0.1:8000"})

    body = response.json()

    assert body["info"]["title"] == "Project Atlas AI"
    assert "/dashboard" in body["paths"]


def test_fastapi_default_docs_routes_are_disabled() -> None:
    """No unguarded oauth2-redirect route should exist at all."""

    application = create_app()
    paths = {getattr(route, "path", None) for route in application.routes}

    assert "/docs/oauth2-redirect" not in paths


# =====================================================================
# ORIGIN VALIDATION ON THE ONE NON-GET ROUTE
# =====================================================================


def _post_request(
    *,
    peer: tuple[str, int] | None = ("127.0.0.1", 50000),
    host_headers: list[str] | None = None,
    origin_headers: list[str] | None = None,
) -> Request:
    headers = [(b"host", value.encode("utf-8")) for value in (host_headers or [])]
    headers += [
        (b"origin", value.encode("utf-8")) for value in (origin_headers or [])
    ]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/login",
        "raw_path": b"/login",
        "query_string": b"",
        "headers": headers,
        "client": peer,
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
    }

    return Request(scope)


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1",
        "http://127.0.0.1:9000",
        "https://127.0.0.1:8443",
        "http://localhost",
        "http://LOCALHOST:8000",
        "http://[::1]",
        "http://[::1]:8000",
    ],
)
def test_loopback_origin_is_accepted(origin: str) -> None:
    assert is_same_origin_request(
        _post_request(host_headers=["127.0.0.1:8000"], origin_headers=[origin])
    )


@pytest.mark.parametrize(
    "origin",
    [
        "http://attacker.example",
        "http://attacker.example:8000",
        "http://127.0.0.1.attacker.example",
        "null",
        "not-a-url",
        "",
    ],
)
def test_foreign_or_malformed_origin_is_refused(origin: str) -> None:
    assert not is_same_origin_request(
        _post_request(host_headers=["127.0.0.1:8000"], origin_headers=[origin])
    )


def test_missing_origin_header_is_refused() -> None:
    """A same-origin POST always carries an Origin header; absence fails closed."""

    assert not is_same_origin_request(
        _post_request(host_headers=["127.0.0.1:8000"], origin_headers=[])
    )


def test_repeated_origin_headers_are_refused() -> None:
    assert not is_same_origin_request(
        _post_request(
            host_headers=["127.0.0.1:8000"],
            origin_headers=["http://127.0.0.1", "http://attacker.example"],
        )
    )


def test_in_process_testclient_origin_is_accepted_only_from_the_in_process_peer() -> (
    None
):
    assert is_same_origin_request(
        _post_request(
            peer=("testclient", 50000),
            host_headers=["testserver"],
            origin_headers=["http://testserver"],
        )
    )

    for peer in ("127.0.0.1", "::1"):
        assert not is_same_origin_request(
            _post_request(
                peer=(peer, 50000),
                host_headers=["testserver"],
                origin_headers=["http://testserver"],
            )
        )


def test_login_refuses_a_rebinding_host_regardless_of_origin() -> None:
    response = _client().post(
        "/login",
        headers={"host": "attacker.example", "origin": "http://127.0.0.1"},
    )

    assert response.status_code == 403
    assert response.json()["reason"] == "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"


def test_login_refuses_a_mismatched_origin_on_a_loopback_host() -> None:
    response = _client().post(
        "/login",
        headers={"host": "127.0.0.1:8000", "origin": "http://attacker.example"},
    )

    assert response.status_code == 403
    assert response.json()["reason"] == "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"


def test_login_succeeds_with_a_loopback_host_and_matching_origin() -> None:
    response = _client().post(
        "/login",
        headers={"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_login_refuses_a_request_with_no_origin_header() -> None:
    response = _client().post(
        "/login",
        headers={"host": "127.0.0.1:8000"},
    )

    assert response.status_code == 403
    assert response.json()["reason"] == "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"
