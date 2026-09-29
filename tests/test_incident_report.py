"""Incident management (registry v5.59): detect from readiness, versioned history, resolution requires answers."""

from __future__ import annotations

import pytest

from atlas_org import memory_records
from tools import atlas_org_cli as cli
from tools import incident_report as ir

NOT_READY = {"ready": False, "checks": [{"check": "market_data", "ok": False, "detail": "stale: XRPUSDT"},
                                        {"check": "runtime", "ok": True, "detail": "ok"}]}


@pytest.fixture(autouse=True)
def _records_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "RECORDS_DIR", tmp_path)


def test_detect_opens_once_and_dedupes():
    first = ir.detect(fetch=lambda url: NOT_READY)
    assert first["opened"] == "INC-0001.1"
    assert ir.detect(fetch=lambda url: NOT_READY)["already_open"] == "INC-0001"
    assert ir.detect(fetch=lambda url: {"ready": True, "checks": []}) == {"opened": None, "ready": True}
    rec = ir.current_incidents()["INC-0001"]
    assert rec["incident"]["severity"] == "MEDIUM" and rec["incident"]["services"] == ["market_data"]


def test_unreachable_atlas_is_an_incident_not_silence():
    def down(url):
        raise OSError("connection refused")
    out = ir.detect(fetch=down)
    assert out["opened"] and ir.current_incidents()["INC-0001"]["incident"]["severity"] == "HIGH"


def test_lifecycle_keeps_history_and_resolution_needs_answers():
    ir.open_incident("feed down", "HIGH", ["market_data"])
    ir.change("INC-0001", "CONTAINED", "incident_response", note="trading halted fail-closed")
    with pytest.raises(memory_records.MemoryLogError, match="resolved incident needs"):
        ir.change("INC-0001", "RESOLVED", "incident_response", root_cause="x")
    ir.change("INC-0001", "RESOLVED", "incident_response", root_cause="provider timeout",
              actions="reconnect verified", prevention="timeout alarm")
    records = memory_records.replay(cli.read_log(cli.RECORDS_DIR / cli.MEMORY_LOG))
    assert [r["id"] for r in records.values() if r["type"] == "INCIDENTS"] == ["INC-0001.1", "INC-0001.2", "INC-0001.3"]
    assert records["INC-0001.1"]["superseded_by"] == "INC-0001.2"
    assert ir.current_incidents()["INC-0001"]["incident"]["status"] == "RESOLVED"


def test_incidents_are_never_authoritative():
    with pytest.raises(memory_records.MemoryLogError, match="evidence, not policy"):
        memory_records.next_record([], record_id="INC-9.1", type="INCIDENTS", authority="AUTHORITATIVE",
                                   title="t", body="b", author="owner", source="s", at="2026-09-29T00:00:00Z",
                                   owner_key=b"k" * 32,
                                   incident={"what": "w", "detected_at": "d", "severity": "LOW", "services": ["x"],
                                             "status": "OPEN"})
