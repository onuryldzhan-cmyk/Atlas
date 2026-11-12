"""Every web route is read-only (Phase 2-3 item 3).

The status API may only read. A route that accepts a state-changing method
must be added to ALLOWED_NON_READ_ROUTES here, deliberately and with a
review, or this test fails.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import web_app

READ_METHODS = {"GET", "HEAD"}

# POST /login only redirects to /dashboard (web_app.py); it reads nothing
# from the runtime and writes nothing.
ALLOWED_NON_READ_ROUTES = {("POST", "/login")}


def _routes(app):
    for route in app.routes:
        inner = getattr(getattr(route, "original_router", None), "routes", None)
        if inner:
            yield from _routes_of(inner)
        else:
            yield from _routes_of([route])


def _routes_of(routes):
    for route in routes:
        for method in getattr(route, "methods", None) or ():
            yield method, getattr(route, "path", "")


def test_every_route_is_read_only_or_explicitly_allowed():
    offenders = {
        (method, path)
        for method, path in _routes(web_app.create_app(runtime=None))
        if method not in READ_METHODS and (method, path) not in ALLOWED_NON_READ_ROUTES
    }

    assert offenders == set(), f"state-changing routes need review: {sorted(offenders)}"


def test_the_inventory_sees_the_included_observability_router():
    paths = {path for _, path in _routes(web_app.create_app(runtime=None))}

    assert "/api/observability/governance" in paths
    assert "/api/execution-gates" in paths


class _UntouchableRuntime:
    def __getattr__(self, name):
        raise AssertionError(f"/login touched the runtime: {name}")


def test_login_never_touches_the_runtime():
    client = TestClient(
        web_app.create_app(runtime=_UntouchableRuntime()),
        base_url="http://127.0.0.1:8000",
    )

    response = client.post(
        "/login",
        headers={"Origin": "http://127.0.0.1:8000"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
