"""Atlas HQ page (registry v5.38): presentation only, read-only data, works without 3D."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

import web_app

ALLOWED_APIS = {"/api/agent-states", "/api/organization", "/api/tasks", "/api/permissions", "/api/command-center", "/api/chat?q=", "/api/trades", "/api/events"}  # /api/trades added v5.82 (timeline); /api/events 2026-10-01 (event contract, read-only)


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


def test_hq_reads_contract_events_and_never_invents_activity():
    html = web_app.TEMPLATE_DIR.joinpath("hq.html").read_text(encoding="utf-8")
    assert "getJSON('/api/events')" in html and "hareket uydurulmaz" in html


def test_hq_shows_data_age_and_skipped_records():
    html = web_app.TEMPLATE_DIR.joinpath("hq.html").read_text(encoding="utf-8")
    assert 'id="hq-fresh"' in html and "sözleşmeye uymadı" in html and "henüz okunamadı" in html


def test_hq_draws_collaboration_lines_only_from_handoff_events():
    html = web_app.TEMPLATE_DIR.joinpath("hq.html").read_text(encoding="utf-8")
    assert "e.event_type === 'collaboration.handoff'" in html and "e.payload.source" in html


# 2026-10-02 (owner approved the three.js HQ): the only dependency is the vendored, hash-pinned three.js
# module, imported from the loopback /assets allowlist; still no <script src>, no CDN, no fetch of its own.
THREE_DIR = web_app.BASE_DIR / "static" / "vendor" / "three-0.185.1"


def test_hq_imports_only_the_vendored_three_module():
    html = _page()
    imports = re.findall(r"""\bimport\b[^;'"]*['"]([^'"]+)['"]""", html)
    assert imports == ["/assets/three.module.min.js"]
    assert "cdn" not in html.lower() and "https://" not in html
    module = html.split('<script type="module">', 1)[1]
    assert "fetch(" not in module and "getJSON(" not in module and "XMLHttpRequest" not in module
    assert "window.atlasHQ" in html and "hq.useWebGL()" in module  # canvas fallback stays when WebGL fails


def test_three_module_resolves_its_core_through_the_allowlist():
    module = (THREE_DIR / "three.module.min.js").read_text(encoding="utf-8")
    assert set(re.findall(r'from"([^"]+)"', module)) == {"./three.core.min.js"}
    for name in ("three.module.min.js", "three.core.min.js"):
        assert web_app.VENDORED_ASSETS[name][0] == THREE_DIR / name
    client = TestClient(web_app.create_app(), base_url="http://127.0.0.1")
    response = client.get("/assets/three.core.min.js")
    assert response.status_code == 200 and "javascript" in response.headers["content-type"]
    assert response.content == (THREE_DIR / "three.core.min.js").read_bytes()


def test_vendored_three_has_no_dynamic_code_and_fetch_only_in_unused_loaders():
    for name in ("three.module.min.js", "three.core.min.js"):
        script = (THREE_DIR / name).read_text(encoding="utf-8")
        for forbidden in ("XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "importScripts", "Worker(",
                          "import(", "eval(", "new Function", "document.cookie", "window.open", "localStorage",
                          "sessionStorage", "indexedDB"):
            assert forbidden not in script, (name, forbidden)
    # FileLoader + ImageBitmapLoader (x2); the HQ never constructs a loader.
    assert (THREE_DIR / "three.core.min.js").read_text(encoding="utf-8").count("fetch(") == 3
    assert "Loader" not in _page().split('<script type="module">', 1)[1]
