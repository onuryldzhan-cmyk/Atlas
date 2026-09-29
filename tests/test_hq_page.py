"""Atlas HQ page (registry v5.38): presentation only, read-only data, works without 3D."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

import web_app

ALLOWED_APIS = {"/api/agent-states", "/api/organization", "/api/tasks", "/api/permissions", "/api/command-center", "/api/chat?q=", "/api/trades"}  # /api/trades added v5.82 (timeline)


def _page() -> str:
    response = TestClient(web_app.create_app()).get("/hq")
    assert response.status_code in (200, 403)
    return web_app.TEMPLATE_DIR.joinpath("hq.html").read_text(encoding="utf-8")


def test_hq_reads_only_the_read_only_apis_and_never_writes():
    html = _page()
    fetched = set(re.findall(r"getJSON\('([^']+)'", html))
    assert fetched and fetched <= ALLOWED_APIS
    assert "<form" not in html
    assert not re.search(r"method\s*:\s*['\"](POST|PUT|PATCH|DELETE)", html, re.I)
    assert "localStorage" not in html and "<script src=" not in html  # no new dependency


def test_hq_has_a_non_3d_mode_and_names_no_invented_values():
    html = _page()
    assert 'id="toggle-3d"' in html and 'id="hq-3d-off"' in html
    assert "Değer uydurulmaz" in html  # unavailable portfolio is stated, not filled in


def test_hq_route_is_loopback_guarded():
    client = TestClient(web_app.create_app(), base_url="http://evil.example")
    assert client.get("/hq").status_code == 403
