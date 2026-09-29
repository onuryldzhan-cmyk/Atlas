"""Start page and Trading page (registry v5.40): read-only, real data only, simple start page."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import web_app

READ_ONLY_APIS = {"/api/portfolio", "/api/command-center", "/api/trades", "/api/proposals", "/api/tasks", "/api/memory", "/api/permissions"}


@pytest.mark.parametrize("name", ["home.html", "trading.html", "governance.html"])
def test_pages_only_read_and_never_write(name):
    html = web_app.TEMPLATE_DIR.joinpath(name).read_text(encoding="utf-8")
    assert set(re.findall(r"getJSON\('([^']+)'", html)) <= READ_ONLY_APIS
    assert "<form" not in html and not re.search(r"method\s*:", html)
    assert "<script src=" not in html
    assert "Değer uydurulmaz" in html or "tahmin edilmez" in html or "kısmen gösterilmez" in html


def test_start_page_stays_simple():
    html = web_app.TEMPLATE_DIR.joinpath("home.html").read_text(encoding="utf-8")
    assert html.count('class="kpi"') <= 6  # essentials only; details live on /trading, /hq, /dashboard
    for link in ("/trading", "/hq", "/agents", "/dashboard"):
        assert f'href="{link}"' in html


@pytest.mark.parametrize("path", ["/home", "/trading", "/governance"])
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
