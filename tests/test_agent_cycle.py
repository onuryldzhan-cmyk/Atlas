"""Agent cycle: every rule-based agent runs, one failure never stops the rest, the cycle is recorded."""

from __future__ import annotations

import json

from atlas_org import memory_records
from tools import agent_cycle as ac
from tools import atlas_org_cli as cli


def test_cycle_runs_all_agents_isolates_failures_and_records(tmp_path):
    def ok(_):
        return {"verdict": "OK", "summary": "done"}

    def boom(_):
        raise RuntimeError("archive locked")

    agents = (("a", "A", ok), ("b", "B", boom), ("c", "C", ok))
    out = ac.run_cycle(tmp_path, agents)
    assert [r["verdict"] for r in out["results"]] == ["OK", "FAIL", "OK"]
    assert "archive locked" in out["results"][1]["summary"]
    rec = memory_records.replay(cli.read_log(tmp_path / cli.MEMORY_LOG))[out["record_id"]]
    assert rec["type"] == "OPERATIONS" and rec["authority"] == "TEMPORARY"
    assert len(json.loads(rec["body"])["agent_cycle"]) == 3


def test_real_agents_on_a_small_book(tmp_path, monkeypatch):
    archive = tmp_path / "closed.jsonl"
    row = {"symbol": "BTCUSDT", "cost_quote": "1000", "gross_pnl": "0.5",
           "opened_at": "2026-09-29T10:00:00+00:00", "closed_at": "2026-09-29T10:30:00+00:00"}
    archive.write_text("".join(json.dumps(row) + "\n" for _ in range(12)), encoding="utf-8")
    monkeypatch.setattr(ac, "_archive_path", lambda: archive)
    monkeypatch.setattr(ac, "_approvals", lambda: {})
    records = tmp_path / "records"
    first = ac.quant_research(records)
    assert "12 işlem analiz edildi" in first["summary"]
    assert "yeni kapanan işlem yok" in ac.quant_research(records)["summary"]  # no duplicate report
    assert "SA-FEE-DRAG.1" in ac.strategy_lab(records)["summary"]
    assert "yeni öneri: yok" in ac.strategy_lab(records)["summary"]           # open proposal not refiled


def test_red_team_challenges_each_open_proposal_once(tmp_path, monkeypatch):
    archive = tmp_path / "closed.jsonl"
    row = {"symbol": "BTCUSDT", "cost_quote": "1000", "gross_pnl": "0.5",
           "opened_at": "2026-09-29T10:00:00+00:00", "closed_at": "2026-09-29T10:30:00+00:00"}
    archive.write_text("".join(json.dumps(row) + "\n" for _ in range(3)), encoding="utf-8")
    monkeypatch.setattr(ac, "_archive_path", lambda: archive)
    monkeypatch.setattr(ac, "_approvals", lambda: {})
    records = tmp_path / "records"
    ac.strategy_lab(records)
    first = ac.red_team(records)
    assert "SA-FEE-DRAG.1: KANIT YETERSİZ" in first["summary"]
    assert "yeni öneri yok" in ac.red_team(records)["summary"]
    recs = memory_records.replay(cli.read_log(records / cli.MEMORY_LOG))
    rt = [r for r in recs.values() if r["author"] == "red_team"]
    assert len(rt) == 1 and rt[0]["type"] == "REVIEWS" and rt[0]["claims"][0]["counter_evidence"]


def test_market_regime_agent_records_observation_and_never_guesses(tmp_path):
    up = [100 * 1.002 ** i for i in range(200)]
    out = ac.market_regime(tmp_path, ["UPUSDT", "BADUSDT"],
                           lambda s: up if s == "UPUSDT" else (_ for _ in ()).throw(OSError("net")))
    assert out["verdict"] == "OK" and "UNKNOWN 1" in out["summary"]
    rec = [r for r in memory_records.replay(cli.read_log(tmp_path / cli.MEMORY_LOG)).values() if r["author"] == "market_regime"]
    assert len(rec) == 1 and json.loads(rec[0]["body"])["coins"]["BADUSDT"]["regime"] == "UNKNOWN"
    down = ac.market_regime(tmp_path, ["X"], lambda s: (_ for _ in ()).throw(OSError("net")))
    assert down["verdict"] == "WARN"


def test_knowledge_manager_records_only_on_status_change(tmp_path, monkeypatch):
    archive = tmp_path / "closed.jsonl"
    row = {"symbol": "BTCUSDT", "cost_quote": "1000", "gross_pnl": "-3",
           "opened_at": "2026-09-29T10:00:00+00:00", "closed_at": "2026-09-29T10:30:00+00:00"}
    archive.write_text("".join(json.dumps({**row, "position_id": f"p{i}"}) + "\n" for i in range(3)), encoding="utf-8")
    monkeypatch.setattr(ac, "_archive_path", lambda: archive)
    records = tmp_path / "records"
    assert "durumu değişti" in ac.knowledge_manager(records)["summary"]
    assert "değişmedi" in ac.knowledge_manager(records)["summary"]
    km = [r for r in memory_records.replay(cli.read_log(records / cli.MEMORY_LOG)).values() if r["author"] == "knowledge_manager"]
    assert len(km) == 1 and json.loads(km[0]["body"])["statuses"]["L-COIN-BTCUSDT"] == "CANDIDATE"
