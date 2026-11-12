"""Agents page (registry v5.29): loopback-only, read-only shell; JS runs in node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import web_app
from observability.organization import ORGANIZATION, organization_public

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def test_agents_page_renders_and_links_back_to_dashboard():
    response = TestClient(web_app.create_app()).get("/agents")
    assert response.status_code == 200
    assert "Organizasyon şeması (2B)" in response.text
    assert 'href="/dashboard"' in response.text


def test_dashboard_links_to_agents_page():
    html = (ROOT / "templates/dashboard.html").read_text(encoding="utf-8")
    assert 'href="/agents"' in html


def _script() -> str:
    html = (ROOT / "templates/agents.html").read_text(encoding="utf-8")
    body = html[html.index("<script>") + len("<script>"):html.index("</script>")]
    return body


def _run(tail: str) -> dict:
    harness = (
        "global.window = { __ATLAS_TEST__: true };\n"
        "const els = {};\n"
        "global.document = { getElementById: (id) => (els[id] = els[id] || { innerHTML: '' }),"
        " querySelectorAll: () => [], addEventListener: () => {} };\n"
        + _script() + "\n" + tail
    )
    out = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
def test_org_chart_draws_every_unit_and_links_rows():
    org = organization_public()
    out = _run(
        f"const org = {json.dumps(org)}; const L = renderOrgChart(org.units, org.tiers);\n"
        "console.log(JSON.stringify({ svg: els['org-chart'].innerHTML, nodes: L.nodes.length, rows: L.rows.length }));\n"
    )
    assert out["nodes"] == len(ORGANIZATION)
    assert out["svg"].count('class="org-node ') == len(ORGANIZATION)
    assert out["svg"].count('class="org-link"') == len(ORGANIZATION) - 1  # every node below the owner row is linked
    assert 'org-node PLANNED' in out["svg"] and 'org-node ACTIVE' in out["svg"]


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
def test_live_monitor_counts_agreement_and_shows_exclusions():
    org = organization_public()
    signals = {"status": "SUCCESS", "signals": {
        "BTCUSDT": {"action": "SELL", "agents": {"technical": {"status": "EVALUATED", "action": "HOLD", "score": 0.45},
                                                 "macro": {"status": "EVALUATED", "action": "SELL", "score": 0.25},
                                                 "sentiment": {"status": "EXCLUDED", "reason": "UNAVAILABLE_NO_PROVIDER"}}},
        "ETHUSDT": {"action": "SELL", "agents": {"macro": {"status": "EVALUATED", "action": "SELL", "score": 0.25}}},
    }}
    out = _run(
        f"orgUnits = {json.dumps(org['units'])}; renderLiveAgents({json.dumps(signals)});\n"
        "console.log(JSON.stringify({ html: els['live-agents'].innerHTML }));\n"
    )
    html = out["html"]
    assert "karara uyum: 2/2" in html          # macro agreed on both symbols
    assert "karara uyum: 0/1" in html          # technical voted HOLD vs SELL
    assert 'title="UNAVAILABLE_NO_PROVIDER">hariç<' in html
    assert html.count('class="agent-tile"') == 5


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
def test_detail_panel_escapes_and_lists_limits():
    unit = dict(organization_public()["units"][0], name="<b>x</b>", mission="<script>")
    out = _run(f"renderDetail({json.dumps(unit)}); console.log(JSON.stringify({{ html: els['org-detail'].innerHTML }}));\n")
    assert "<b>x</b>" not in out["html"] and "&lt;script&gt;" in out["html"]
    assert "yapamaz" in out["html"]
