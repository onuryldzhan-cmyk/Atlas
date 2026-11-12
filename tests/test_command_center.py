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
    ("sistemde sorun var mı", "health"), ("portföy kârı", "pnl"), ("hafıza", "memory"),
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


PORTFOLIO = {"available": True, "equity": "1002.33", "total_pnl": "2.33", "total_pnl_pct": "0.23",
             "realized_net_pnl": "1.68", "unrealized_pnl": "0.65", "fees": "0.32", "starting_capital": "1000.00",
             "prices_stale": False,
             "positions": [{"symbol": "BTCUSDT", "quantity": "0.001", "average_entry_price": "112000", "price": "112650.5",
                            "unrealized_pnl": "0.65", "unrealized_pct": "0.58"}],
             "market": [{"symbol": "BTCUSDT", "price": "112650.5", "action": "HOLD", "confidence": 55, "risk_level": "LOW"},
                        {"symbol": "ETHUSDT", "price": "4120.3", "action": "BUY", "confidence": 66, "risk_level": "MEDIUM"}]}


def test_chat_answers_with_the_real_portfolio_and_coins():
    b = _brief(portfolio=PORTFOLIO)
    out = cc.answer("toplam kâr ne kadar", b)
    assert out["intent"] == "pnl" and "2,33 $" in out["answer"] and "1.000,00 $" in out["answer"]
    out = cc.answer("BTC ne durumda?", b)
    assert out["intent"] == "coin" and "112650.5" in out["answer"] and "0,65 $" in out["answer"]
    out = cc.answer("eth", b)
    assert "BUY" in out["answer"] and "açık pozisyon yok" in out["answer"]
    assert "BTCUSDT 0.001" in cc.answer("pozisyonlarım neler", b)["answer"]
    assert "Sorabilecekleriniz" in cc.answer("yardım", b)["answer"]


def test_unknown_coin_or_missing_portfolio_is_not_invented():
    assert cc.answer("DOGE ne durumda", _brief(portfolio=PORTFOLIO))["intent"] != "coin"
    out = cc.answer("toplam kâr ne kadar", _brief(account=None, portfolio={"available": False}))
    assert "bilgi yok" in out["answer"]
