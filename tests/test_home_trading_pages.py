"""Start page and Trading page (registry v5.40): read-only, real data only, simple start page."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import web_app

READ_ONLY_APIS = {"/api/portfolio", "/api/command-center", "/api/trades", "/api/proposals", "/api/tasks", "/api/memory", "/api/permissions", "/api/status",
                  "/api/observability/test-results", "/api/observability/telemetry-summary",
                  "/api/chat?q=", "/api/security", "/api/roadmap", "/api/research", "/api/execution-gates", "/api/readiness", "/api/signals", "/api/candles?symbol="}


@pytest.mark.parametrize("name", ["home.html", "trading.html", "governance.html", "system.html", "security.html", "roadmap.html", "research.html", "decisions.html"])
def test_pages_only_read_and_never_write(name):
    html = web_app.TEMPLATE_DIR.joinpath(name).read_text(encoding="utf-8")
    assert set(re.findall(r"getJSON\('([^']+)'", html)) <= READ_ONLY_APIS
    assert "<form" not in html and not re.search(r"method\s*:", html)
    # no CDN or external script: only vendored, hash-pinned assets from the /assets allowlist (v5.72)
    sources = re.findall(r'<script src="([^"]+)"', html)
    assert all(src.startswith("/assets/") and src.removeprefix("/assets/") in web_app.VENDORED_ASSETS for src in sources)
    assert "Değer uydurulmaz" in html or "tahmin edilmez" in html or "kısmen gösterilmez" in html or "asla \"sağlıklı\" sayılmaz" in html or "Okunamadı" in html


def test_start_page_stays_simple():
    html = web_app.TEMPLATE_DIR.joinpath("home.html").read_text(encoding="utf-8")
    assert html.count('class="kpi"') <= 6  # essentials only; details live on /trading, /hq, /dashboard
    for link in ("/trading", "/hq", "/agents", "/dashboard"):
        assert f'href="{link}"' in html


@pytest.mark.parametrize("path", ["/home", "/trading", "/governance", "/system", "/security", "/roadmap", "/research", "/decisions"])
def test_pages_are_served_and_loopback_guarded(path):
    assert TestClient(web_app.create_app()).get(path).status_code == 200
    assert TestClient(web_app.create_app(), base_url="http://evil.example").get(path).status_code == 403


def test_root_leads_to_the_start_page():
    assert 'href="/home"' in TestClient(web_app.create_app()).get("/").text


def test_governance_page_separates_recommendation_review_owner_and_applied():
    html = web_app.TEMPLATE_DIR.joinpath("governance.html").read_text(encoding="utf-8")
    for cls in ("stage rec", "stage rev", "stage own", "stage app"):
        assert cls in html
    assert "kendisi onaylayamaz" in html


def test_security_api_scans_the_runtime_without_writing(tmp_path):
    from observability import security_view

    out = security_view.read_security()
    assert out["available"] and set(out["checks"]) >= {"SECRETS", "SUBPROCESS", "NETWORK"}
    assert out["overall"] in ("PASS", "REVIEW_REQUIRED", "FAIL") and out["files_reviewed"] > 50
    assert out["authority"]["live_authority"] == "DENIED"


def test_roadmap_parses_the_canonical_record_and_claims_nothing_done():
    from observability import roadmap_view

    out = roadmap_view.read_roadmap()
    assert out["available"] and [p["phase"] for p in out["phases"]] == list(range(11))
    assert all("complete" not in p["status"].lower() or "not a completion" in p["status"].lower() for p in out["phases"])
    assert out["phases"][10]["status"].startswith("LOCKED")


def test_research_list_reads_titles_only():
    from observability import research_view

    out = research_view.read_research()
    assert out["available"] and any("Trading strategy" in d["title"] or "strategy" in d["title"].lower() for d in out["documents"])
    assert all(set(d) == {"file", "title", "bytes"} for d in out["documents"])


def test_decisions_page_explains_from_recorded_sources_only():
    html = web_app.TEMPLATE_DIR.joinpath("decisions.html").read_text(encoding="utf-8")
    assert set(re.findall(r"getJSON\('([^']+)'", html)) == {"/api/signals", "/api/execution-gates"}
    for part in ("Ajan oyları", "Güven eşikleri", "Risk motorunun son sonucu", "NB-5", "gates.experiment", "elde olmayan coin için SAT"):
        assert part in html
