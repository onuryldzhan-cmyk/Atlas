"""T-0016 (owner 2026-10-02): golden characterization of web_app.create_app.

Generated on the pre-refactor code (one 1051-line body). The split must reproduce:
the route table
(exact=True, used by the differential check, also hashes full bodies) in registration order (path, methods, endpoint name, response class,
schema inclusion), the OpenAPI document, the middleware stack, and for every route the
status, content type, security headers and normalized body, called both from loopback and
from a non-loopback client, with no runtime attached. Runtime-backed behaviour stays
covered by the existing web tests; this pins the wiring the split moves.

Regenerate ONLY for an intended, approved behaviour change:
    python -c "import json; from tests.test_create_app_golden import collect, GOLDEN; \
GOLDEN.write_text(json.dumps(collect(), indent=1, sort_keys=True))"
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.test_execute_decision_golden import norm

GOLDEN = Path(__file__).with_name("golden") / "create_app_golden.json"
_PARAM = re.compile(r"\{[^}]+\}")
_NUM = re.compile(r"\b\d+(\.\d+)?\b")  # durations, ages and counters drift between runs


def _shape(value: Any) -> Any:
    """Keys and types only: values come from governance records that legitimately change over time."""
    if isinstance(value, dict):
        return {str(k): _shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted({json.dumps(_shape(v), sort_keys=True) for v in value})
    return type(value).__name__


def _body(response, exact: bool = False) -> Any:
    ctype = response.headers.get("content-type", "")
    if "json" in ctype:
        return norm(response.json()) if exact else _shape(response.json())
    if not exact:
        return "html" if "html" in ctype else ctype
    text = norm(response.text)
    return "sha256:" + hashlib.sha256(_NUM.sub("<n>", text).encode()).hexdigest()


def collect(exact: bool = False) -> dict[str, Any]:
    from web_app import create_app

    app = create_app()
    routes = []
    flat = []
    for r in app.router.routes:
        flat.extend(r.original_router.routes if not hasattr(r, "path") else [r])  # include_router()
    for r in flat:
        routes.append({"path": r.path, "name": r.name, "methods": sorted(getattr(r, "methods", None) or []),
                       "response_class": getattr(getattr(r, "response_class", None), "__name__", None),
                       "in_schema": getattr(r, "include_in_schema", None), "api": isinstance(r, APIRoute)})
    calls = {}
    for host in ("127.0.0.1", "203.0.113.9"):
        client = TestClient(app, base_url="http://127.0.0.1", client=(host, 50000))
        for r in routes:
            path = _PARAM.sub("BTCUSDT", r["path"])
            for method in r["methods"]:
                if method == "HEAD":
                    continue
                resp = client.request(method, path, **({"json": {}} if method == "POST" else {}))
                calls[f"{host} {method} {path}"] = {
                    "status": resp.status_code,
                    "content_type": resp.headers.get("content-type"),
                    "security_headers": sorted(k for k in resp.headers if k.lower().startswith(("x-", "content-security",
                                                                                               "referrer", "permissions"))),
                    "body": _body(resp, exact),
                }
    return norm({
        "routes": routes,
        "openapi": app.openapi(),
        "middleware": [type(m.cls).__name__ if not isinstance(m.cls, type) else m.cls.__name__
                       for m in app.user_middleware],
        "calls": calls,
    })


def test_create_app_matches_golden():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = collect()
    assert actual["routes"] == expected["routes"], "route table changed"
    assert actual["middleware"] == expected["middleware"]
    assert actual["openapi"] == expected["openapi"]
    assert sorted(actual["calls"]) == sorted(expected["calls"])
    for key in sorted(expected["calls"]):
        assert actual["calls"][key] == expected["calls"][key], f"{key!r} diverged from the golden record"


def test_golden_covers_every_route():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert len(expected["routes"]) >= 40
    assert any(c["status"] == 403 for c in expected["calls"].values())
    assert any(c["status"] == 200 for c in expected["calls"].values())
