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
    assert len(km) == 1 and json.loads(km[0]["body"])["statuses"]["L-COIN-BTCUSDT"] == "PROPOSED"


def test_cycle_records_resources_and_flags_runaway_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "AGENT_BUDGET_S", -1.0)  # any duration exceeds it
    out = ac.run_cycle(tmp_path, (("a", "A", lambda _: {"verdict": "OK", "summary": "done"}),))
    assert out["results"][0]["verdict"] == "WARN" and "bütçe" in out["results"][0]["summary"]
    rec = memory_records.replay(cli.read_log(tmp_path / cli.MEMORY_LOG))[out["record_id"]]
    assert json.loads(rec["body"])["resources"]["llm_tokens"].startswith("N/A")


def test_invalid_or_leaky_agent_output_is_contained(tmp_path):
    agents = (("bad", "Bad", lambda _: {"verdict": "APPROVE_DEPLOY", "summary": "ok"}),
              ("none", "None", lambda _: None),
              ("leak", "Leak", lambda _: {"verdict": "OK", "summary": "api_key=sk-ABCDEF1234567890SECRET done"}))
    out = ac.run_cycle(tmp_path, agents)
    assert [r["verdict"] for r in out["results"]] == ["FAIL", "FAIL", "OK"]
    assert out["results"][0]["summary"] == "INVALID_AGENT_OUTPUT"
    assert "sk-ABCDEF1234567890SECRET" not in out["results"][2]["summary"]


def test_failed_agent_opens_one_incident_not_duplicates(tmp_path):
    boom = (("x", "X", lambda _: (_ for _ in ()).throw(RuntimeError("disk full"))),)
    ac.run_cycle(tmp_path, boom)
    ac.run_cycle(tmp_path, boom)
    inc = [r for r in memory_records.replay(cli.read_log(tmp_path / cli.MEMORY_LOG)).values() if r["type"] == "INCIDENTS"]
    assert len(inc) == 1 and inc[0]["incident"]["status"] == "OPEN" and inc[0]["incident"]["services"] == ["x"]


def test_task_runner_executes_rule_based_steps_and_flags_llm_steps(tmp_path, monkeypatch):
    from atlas_org import tasks as T

    monkeypatch.setattr(ac, "security", lambda _: {"verdict": "OK", "summary": "genel PASS"})
    sec = cli.request_task(tmp_path, "güvenlik taraması yap", at="2026-10-01T00:00:00+00:00")["task_id"]
    res = cli.request_task(tmp_path, "bu kütüphaneyi araştır", at="2026-10-01T00:00:00+00:00")["task_id"]
    out = ac.task_runner(tmp_path)
    state = T.replay(cli.read_log(tmp_path / cli.TASKS_LOG))
    assert any(s["status"] == "DONE" and s["result"]["verdict"] == "PASS" for s in state[sec]["steps"])
    assert state[res]["status"] == "BLOCKED" and "AI-001" in out["summary"]
    reason = next(st["block_reason"] for st in state[res]["steps"] if st["status"] == "BLOCKED")
    assert "AI-001" in reason and "onay" in reason  # marker atlas_self_review skips on; owner-approval wording
    for _ in range(5):  # one step per task per cycle; the log settles
        ac.task_runner(tmp_path)
    again = ac.task_runner(tmp_path)  # once settled, nothing is re-run or re-blocked
    assert again["summary"] == "yürütülen adım: yok; AI-001 bekleyen: yok"


def test_strategy_research_launches_in_background_then_records_result(tmp_path):
    rd, rec, launched = tmp_path / "research", tmp_path / "records", []
    rd.mkdir()
    first = ac.strategy_research(rec, research_dir=rd, launch=launched.append, now=1000.0)
    assert "başlatıldı" in first["summary"] and len(launched) == 1 and "--output" in launched[0]
    assert "sürüyor" in ac.strategy_research(rec, research_dir=rd, launch=launched.append, now=1100.0)["summary"]
    (rd / "strategy_compare_latest.json").write_text(json.dumps({
        "table": {"ref": [{"net_pnl": "1"}]}, "verdicts": {"ref": "-", "x": "BETTER"}, "dataset": {"dataset_sha256": "abc"}}), encoding="utf-8")
    done = ac.strategy_research(rec, research_dir=rd, launch=launched.append, now=1200.0)
    assert "hafızaya yazıldı" in done["summary"] and "x" in done["summary"]
    sc = [r for r in memory_records.replay(cli.read_log(rec / cli.MEMORY_LOG)).values() if r["id"].startswith("SC-")]
    assert len(sc) == 1
    assert "24 saatten yeni" in ac.strategy_research(rec, research_dir=rd, launch=launched.append)["summary"]
    assert len(launched) == 1


def test_overview_snapshot_records_only_on_change(tmp_path, monkeypatch):
    archive = tmp_path / "closed.jsonl"
    archive.write_text("", encoding="utf-8")
    monkeypatch.setattr(ac, "_archive_path", lambda: archive)
    records = tmp_path / "records"
    ac.overview_snapshot(records)
    ov = lambda: [r for r in memory_records.replay(cli.read_log(records / cli.MEMORY_LOG)).values()
                  if r.get("author") == "overview_snapshot"]
    assert len(ov()) == 1
    ac.overview_snapshot(records)
    assert len(ov()) == 1  # nothing changed -> no new record
    row = {"symbol": "BTCUSDT", "cost_quote": "1000", "gross_pnl": "5",
           "opened_at": "2026-09-29T10:00:00+00:00", "closed_at": "2026-09-29T10:30:00+00:00"}
    archive.write_text(json.dumps(row) + "\n", encoding="utf-8")
    ac.overview_snapshot(records)
    latest = ov()
    assert len(latest) == 2
    assert json.loads(sorted(latest, key=lambda r: r["id"])[-1]["body"])["changes"]


def test_self_review_does_not_loop_on_ai001_waits_or_its_own_tasks(tmp_path):
    from tools import atlas_self_review as sr

    state = {
        "T-1": {"id": "T-1", "status": "BLOCKED", "request": "refactor x",
                "steps": [{"status": "BLOCKED", "result": None, "block_reason": "needs AI-001 decision"}]},
        "T-2": {"id": "T-2", "status": "BLOCKED", "request": "araştır: T-1 görevinde ajan işi takıldı",
                "steps": [{"status": "BLOCKED", "result": None, "block_reason": "x"}]},
        "T-3": {"id": "T-3", "status": "BLOCKED", "request": "fix y",
                "steps": [{"status": "BLOCKED", "result": None, "block_reason": "disk full"}]},
    }
    import types
    orig = sr.task_log
    sr.task_log = types.SimpleNamespace(replay=lambda _: state, agent_scorecards=lambda _: {})
    try:
        orig_read = sr.cli.read_log
        sr.cli.read_log = lambda _: []
        out = sr.agent_findings(tmp_path)
    finally:
        sr.task_log = orig
        sr.cli.read_log = orig_read
    assert [f["evidence"]["task"] for f in out] == ["T-3"]


def test_model_validation_flags_overconfidence_once_and_never_changes_anything(tmp_path, monkeypatch):
    archive = tmp_path / "closed.jsonl"
    rows = [{"position_id": f"p{i}", "symbol": "BTCUSDT", "cost_quote": "1000", "gross_pnl": "-5",
             "opened_at": f"2026-10-01T{10 + i:02d}:00:00+00:00", "closed_at": f"2026-10-01T{10 + i:02d}:30:00+00:00"}
            for i in range(12)]
    archive.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(ac, "_archive_path", lambda: archive)
    approvals = {"BTCUSDT": [{"timestamp": r["opened_at"], "confidence": 75.0} for r in rows]}
    monkeypatch.setattr(ac, "_approvals", lambda: approvals)
    records = tmp_path / "records"
    first = ac.model_validation(records)
    assert "AŞIRI GÜVEN 70-80" in first["summary"]  # 0 % wins at 75 % stated confidence
    assert "değişmedi" in ac.model_validation(records)["summary"]
    mv = [r for r in memory_records.replay(cli.read_log(records / cli.MEMORY_LOG)).values() if r["author"] == "model_validation"]
    assert len(mv) == 1 and mv[0]["authority"] == "RESEARCH"
    assert "model_validation" in [name for name, _, _ in ac.AGENTS]


def test_formerly_planned_units_now_point_to_real_code():
    from observability.organization import ORGANIZATION, PARTIAL
    units = {u.unit_id: u for u in ORGANIZATION}
    for uid in ("strategy_lab", "digital_twin", "model_validation", "red_team"):
        assert units[uid].status == PARTIAL and units[uid].implemented_by and not units[uid].can_execute
