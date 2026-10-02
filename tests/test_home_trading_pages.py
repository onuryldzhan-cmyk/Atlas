"""Start page and Trading page (registry v5.40): read-only, real data only, simple start page."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import web_app

READ_ONLY_APIS = {"/api/portfolio", "/api/command-center", "/api/trades", "/api/proposals", "/api/tasks", "/api/memory", "/api/permissions", "/api/status",
                  "/api/observability/test-results", "/api/observability/telemetry-summary",
                  "/api/chat?q=", "/api/security", "/api/roadmap", "/api/research", "/api/execution-gates", "/api/readiness", "/api/signals", "/api/candles?symbol=", "/api/learning",
                  "/api/experience"}  # GET-only, loopback-only experience_view (2026-10-02)


@pytest.mark.parametrize("name", ["home.html", "trading.html", "governance.html", "system.html", "security.html", "roadmap.html", "research.html", "decisions.html", "postmortem.html"])
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


@pytest.mark.parametrize("path", ["/home", "/trading", "/governance", "/system", "/security", "/roadmap", "/research", "/decisions", "/postmortem"])
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


def test_dashboard_v1_overview_layout_and_honesty():
    """Dashboard v1 (owner 2026-10-01): sidebar, status dots, 4 KPIs, no fake confidence, no invented data sources."""
    html = web_app.TEMPLATE_DIR.joinpath("home.html").read_text(encoding="utf-8")
    assert html.count('class="kpi"') == 4
    for part in ("OPERATIONAL", "PAPER", "DATA", "ENGINE", "RISK", "SECURITY", "Equity curve", "Market regime",
                 "Atlas View", "Signal strength", "Why / Why-not", "Open positions", "Attention center", "What changed",
                 "Güven kalibre edilmedi", "Açık pozisyon yok"):
        assert part in html
    assert "const ROSTER = 5" in html  # NB-5: votes are read against the full roster, missing agents shown as missing
    script = html.split("<script>", 1)[1]
    assert "toFixed(0))}%" not in script and "confidence).toFixed" not in script  # no raw confidence % on the overview
    rendered = TestClient(web_app.create_app()).get("/home").text.lower()  # Jinja comments are not rendered
    for absent in ("funding", "open interest", "order book", "orderbook", "correlation", "stress", "ai cost"):
        assert absent not in rendered


def test_dashboard_v1_sidebar_maps_only_to_existing_pages():
    client = TestClient(web_app.create_app())
    text = client.get("/home").text
    hrefs = re.findall(r'class="atlas-side".*?</aside>', text, re.S)[0]
    links = re.findall(r'href="([^"]+)"', hrefs)
    assert len(links) == 11  # 10 items + Command Center
    for link in links:
        assert client.get(link.split("#")[0]).status_code == 200
    assert 'href="/home" class="active"' in text


def test_theme_drops_glass_and_purple_and_uses_v1_palette():
    css = web_app.TEMPLATE_DIR.joinpath("_atlas_theme.html").read_text(encoding="utf-8").lower()
    assert "backdrop-filter" not in css and "#8b5cf6" not in css and "#a78bfa" not in css
    for colour in ("#0b0d10", "#11151a", "#171c22", "#242a31", "#f1f3f5", "#8b949e", "#5b8cff", "#35c98b", "#e5b95c", "#e56b6f", "#6ea8fe"):
        assert colour in css
    assert "http" not in css  # no CDN fonts


@pytest.mark.parametrize("path,active", [("/home", "/home"), ("/agents", "/agents"), ("/dashboard", "/dashboard"),
                                         ("/decisions", "/decisions"), ("/governance", "/governance#proposals"),
                                         ("/research", "/research"), ("/roadmap", "/system"), ("/security", "/system"),
                                         ("/system", "/system"), ("/trading", "/trading"),
                                         ("/postmortem", "/dashboard")])
def test_every_page_shares_the_sidebar_with_one_active_item(path, active):
    text = TestClient(web_app.create_app()).get(path).text
    assert 'class="atlas-side"' in text and 'href="/hq"' in text
    side = text[text.index('class="atlas-side"'):text.index("</aside>")]
    assert side.count('aria-current="page"') == 1
    assert f'<a href="{active}" class="active"' in text


def test_postmortem_shows_hindsight_as_evidence_and_unmeasured_as_such():
    html = web_app.TEMPLATE_DIR.joinpath("postmortem.html").read_text(encoding="utf-8")
    assert "hiçbir kararı değiştirmez" in html and "Ölçülmeyenler" in html and "N/A" in html
    assert 'href="/postmortem"' in web_app.TEMPLATE_DIR.joinpath("trading.html").read_text(encoding="utf-8")


def test_ctrl_k_palette_only_navigates():
    html = web_app.TEMPLATE_DIR.joinpath("_atlas_sidebar.html").read_text(encoding="utf-8")
    assert "atlas-pal" in html and "fetch(" not in html and "<form" not in html and "innerHTML = ''" in html


def test_density_toggle_is_a_local_view_preference_only():
    html = web_app.TEMPLATE_DIR.joinpath("_atlas_sidebar.html").read_text(encoding="utf-8")
    assert 'id="atlas-density"' in html and "atlas-compact" in html
    assert "try { localStorage" in html and "fetch(" not in html


def test_postmortem_shows_book_extras_with_na():
    html = web_app.TEMPLATE_DIR.joinpath("postmortem.html").read_text(encoding="utf-8")
    assert "book_extras" in html and "Coin bazında" in html and "Günlük gerçekleşen" in html and "per_exit_reason" in html


def test_home_reads_regime_records_by_their_real_id_field():
    # /api/memory returns replayed records keyed "id" (not "record_id"); the old lookup always showed N/A.
    html = web_app.TEMPLATE_DIR.joinpath("home.html").read_text(encoding="utf-8")
    assert "r.author === 'market_regime'" in html and "r.id || r.record_id" in html and "localTime" not in html
