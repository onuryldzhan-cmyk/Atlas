"""Organization roster (registry v5.25): every vision unit, honest status, no authority."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from observability.organization import ACTIVE, ORGANIZATION, PLANNED, STATUSES, TIERS, organization_public

ROOT = Path(__file__).resolve().parents[1]

# The departments listed in docs/vision/01_nihai_vizyon.txt section 7.
VISION_DEPARTMENTS = (
    "Chief Architect AI", "Director AI", "Executive Assistant AI", "Quant Research Department",
    "Strategy Laboratory", "Macro Intelligence Center", "Risk Committee", "Capital Management",
    "Performance Audit", "Security Department", "Compliance Department", "Technology Research Center",
    "Open Source Research Team", "AI Model Research Team", "Code Review Team", "Experiment Manager",
    "Knowledge Manager", "Roadmap Planner", "Deployment Manager", "Web Design / UX Team",
    "Digital Twin Laboratory", "Incident Response Team", "Treasury Management", "Explainable AI Center",
)


def test_every_vision_department_is_present_and_the_vision_really_lists_it():
    vision = (ROOT / "docs/vision/01_nihai_vizyon.txt").read_text(encoding="utf-8")
    names = {unit.name for unit in ORGANIZATION}
    for department in VISION_DEPARTMENTS:
        assert department in vision
        assert department in names, department
    for extra in ("CEO AI", "Multi-Model Council", "Red Team / Karşı Görüş Ajanı", "Model Validation Department"):
        assert extra in names


def test_ids_unique_and_vocabulary_valid():
    ids = [unit.unit_id for unit in ORGANIZATION]
    assert len(ids) == len(set(ids))
    for unit in ORGANIZATION:
        assert unit.status in STATUSES and unit.tier in TIERS
        assert unit.mission and unit.cannot
        if unit.status == PLANNED:
            assert unit.phase is not None and 0 <= unit.phase <= 10
            assert unit.implemented_by == ()


def test_active_units_name_existing_code():
    for unit in ORGANIZATION:
        if unit.status == ACTIVE and unit.unit_id != "owner":
            assert unit.implemented_by, unit.unit_id
        for path in unit.implemented_by:
            assert (ROOT / path).exists(), (unit.unit_id, path)


def test_no_ai_unit_can_execute_and_live_is_denied_everywhere():
    executors = {unit.unit_id for unit in ORGANIZATION if unit.can_execute}
    assert executors == {"risk_committee", "capital_management"}  # deterministic core only
    for unit in ORGANIZATION:
        if unit.unit_id != "owner":
            assert any("live" in c for c in unit.cannot) or unit.unit_id in executors
        if unit.tier in ("CEO_AI", "DIRECTOR_AI", "EXECUTIVE_ASSISTANT", "WORKER_AGENT",
                         "SPECIALIZED_UNIT", "MICRO_AGENT"):
            assert unit.can_execute is False


def test_public_payload_counts_match():
    payload = organization_public()
    assert payload["available"] is True
    assert sum(payload["counts"].values()) == len(payload["units"]) == len(ORGANIZATION)
    json.dumps(payload)


def test_endpoint_serves_roster_and_is_loopback_only():
    from fastapi.testclient import TestClient
    import web_app

    body = TestClient(web_app.create_app()).get("/api/organization").json()
    assert body["available"] is True and len(body["units"]) == len(ORGANIZATION)


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
def test_panel_renders_roster_and_filter():
    html = (ROOT / "templates/dashboard.html").read_text(encoding="utf-8")

    def fn(name):
        start = html.index(f"        function {name}(")
        return html[start:html.index("\n        }\n", start) + 10]

    consts = html[html.index("        const ORG_STATUS"):html.index("        let orgPayload = null;")]
    script = "\n".join([fn("esc"), fn("badge"), consts, "let orgPayload = null;",
                        fn("orgStatusBadge"), fn("renderOrgUnit"), fn("renderOrganization")])
    harness = (
        "const els = {}; global.document = { getElementById: (id) => (els[id] = els[id] || { innerHTML: '' }) };\n"
        "const STATUS_TONE = {};\n" + script +
        f"\nrenderOrganization({json.dumps(organization_public())});\nconst all = els['org-units'].innerHTML;\n"
        "orgFilter = 'ACTIVE'; renderOrganization(orgPayload);\n"
        "console.log(JSON.stringify({ all, active: els['org-units'].innerHTML, summary: els['org-summary'].innerHTML,"
        " tiers: els['org-hierarchy'].innerHTML }));\n"
    )
    out = json.loads(subprocess.run([NODE, "-e", harness], capture_output=True, text=True, check=True).stdout)
    assert out["all"].count('data-org-status=') == len(ORGANIZATION)
    active = sum(1 for u in ORGANIZATION if u.status == ACTIVE)
    assert out["active"].count('data-org-status="ACTIVE"') == active
    assert 'data-org-status="PLANNED"' not in out["active"]
    assert "Risk Committee" in out["all"] and "Red Team" in out["all"]
    assert "CEO AI" in out["tiers"] and "Micro Agents" in out["tiers"]
