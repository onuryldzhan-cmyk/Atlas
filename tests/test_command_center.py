"""Command Center brief + Atlas Chat (registry v5.37): real state only, never acts."""

from __future__ import annotations

import pytest

from observability import command_center as cc

PROPOSALS = {"available": True, "awaiting_owner": ["P-0001"], "counts": {"READY_FOR_OWNER": 1},
             "proposals": [{"id": "P-0001", "title": "Reconnect", "status": "READY_FOR_OWNER",
                            "risk_level": "MEDIUM", "author": "code_engineering"}]}
TASKS = {"available": True, "counts": {"IN_PROGRESS": 2, "BLOCKED": 1},
         "agents": {"security": {"status": "WORKING"}, "code_review": {"status": "WAITING"}}}


def _brief(**over):
    kw = dict(health={"healthy": True, "state": "RUNNING"},
              account={"realized_net_pnl": "12.5", "fees": "1.2"},
              proposals=PROPOSALS, tasks=TASKS, memory={"available": True, "records": [1, 2]})
    kw.update(over)
    return cc.compose(**kw)


def test_summary_uses_only_real_values():
    out = cc.answer("Atlas, bugün ne oldu?", _brief())
    assert out["intent"] == "summary"
    for fact in ("sağlıklı", "security", "2 sürüyor", "1 engelli", "P-0001", "12.5", "PAPER"):
        assert fact in out["answer"]


def test_unavailable_sources_are_said_not_invented():
    b = _brief(health={"healthy": False, "state": "OFFLINE", "reason": "RUNTIME_NOT_ATTACHED"}, account=None,
               proposals={"available": False, "reason": "proposals.jsonl: record altered"},
               tasks={"available": False, "reason": "x"})
    text = cc.answer("özet", b)["answer"]
    assert "DEĞİL" in text and "RUNTIME_NOT_ATTACHED" in text
    assert "record altered" in text and "PORTFOLIO_NOT_ATTACHED" in text
    assert "12.5" not in text


@pytest.mark.parametrize("q, intent", [
    ("öneri P-0001 göster", "proposal_detail"), ("Proposal 1'i göster", "proposal_detail"),
    ("bekleyen kararlar", "proposals"), ("P-0001'i onayla", "approve"),
    ("görevler ne durumda", "tasks"), ("kim çalışıyor", "agents"),
    ("sistemde sorun var mı", "health"), ("portföy kârı", "trading"), ("hafıza", "memory"),
    ("xyz", "unknown"),
])
def test_intents(q, intent):
    assert cc.answer(q, _brief())["intent"] == intent


def test_proposal_detail_navigates_and_missing_is_reported():
    out = cc.answer("Proposal 1'i göster", _brief())
    assert out["navigate"] == "proposal:P-0001" and "Reconnect" in out["answer"]
    assert "bulunamadı" in cc.answer("öneri P-0099", _brief())["answer"]


def test_chat_cannot_approve():
    out = cc.answer("P-0001'i onayla", _brief())
    assert "onay veremez" in out["answer"] and "--owner-confirm" in out["answer"]


def test_routes_are_read_only():
    from fastapi.testclient import TestClient

    import web_app

    client = TestClient(web_app.create_app())
    for path in ("/api/command-center", "/api/chat?q=özet"):
        r = client.get(path)
        assert r.status_code in (200, 403)
        if r.status_code == 200:
            assert r.json()["available"] is True
    assert client.post("/api/chat").status_code == 405
