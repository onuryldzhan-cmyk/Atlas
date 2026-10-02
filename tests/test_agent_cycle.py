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
    assert "kesin: 70-80" in first["summary"]  # 0/12: even the top of the 95 % interval (~24 %) is below 75 %
    assert "değişmedi" in ac.model_validation(records)["summary"]
    mv = [r for r in memory_records.replay(cli.read_log(records / cli.MEMORY_LOG)).values() if r["author"] == "model_validation"]
    assert len(mv) == 1 and mv[0]["authority"] == "RESEARCH"
    assert "model_validation" in [name for name, _, _ in ac.AGENTS]


def test_model_validation_marks_small_sample_overconfidence_as_suspected(tmp_path, monkeypatch):
    archive = tmp_path / "closed.jsonl"
    rows = [{"position_id": f"p{i}", "symbol": "BTCUSDT", "cost_quote": "1000", "gross_pnl": "50" if i < 7 else "-5",
             "opened_at": f"2026-10-01T{10 + i:02d}:00:00+00:00", "closed_at": f"2026-10-01T{10 + i:02d}:30:00+00:00"}
            for i in range(12)]
    archive.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(ac, "_archive_path", lambda: archive)
    monkeypatch.setattr(ac, "_approvals", lambda: {"BTCUSDT": [{"timestamp": r["opened_at"], "confidence": 75.0} for r in rows]})
    out = ac.model_validation(tmp_path / "records")["summary"]
    assert "AŞIRI GÜVEN 70-80" in out and "şüpheli" in out  # 7/12 = 58 %: flagged, interval still reaches 75 %


def test_formerly_planned_units_now_point_to_real_code():
    from observability.organization import ORGANIZATION, PARTIAL
    units = {u.unit_id: u for u in ORGANIZATION}
    for uid in ("strategy_lab", "digital_twin", "model_validation", "red_team"):
        assert units[uid].status == PARTIAL and units[uid].implemented_by and not units[uid].can_execute


def test_market_regime_downloads_in_parallel(tmp_path):
    import time as _t

    def slow(sym):
        _t.sleep(0.3)
        return [100.0 + i * 0.1 for i in range(200)]
    started = _t.monotonic()
    out = ac.market_regime(tmp_path, [f"C{i}USDT" for i in range(5)], fetch_closes=slow)
    assert out["verdict"] == "OK" and _t.monotonic() - started < 1.2  # sequential would be >= 1.5 s


def test_ceo_does_not_call_the_model_on_thin_evidence(tmp_path):
    from tools import agent_cycle as ac

    cli.add_memory_record(tmp_path, {"record_id": "Q-0001", "type": "OPERATIONS", "authority": "TEMPORARY",
                                     "title": "0 trades", "body": "{}", "author": "quant_research", "source": "t"})

    def never(*a, **k):
        raise AssertionError("model must not be called")

    out = ac.ceo_brief(tmp_path, ask=never)
    assert "özet çıkarılmadı" in out["summary"]


def test_council_prompt_carries_the_proposal_risk_level(tmp_path):
    from tools import ai_gateway as ai
    from tools import experience_agent as xa

    lesson = {"action": "BUY", "regime": "TREND_UP", "confidence": "60-65", "n_older": 40, "n_newer": 35,
              "avg240_older_pct": 0.2, "avg240_newer_pct": 0.3, "win240_older": 0.6, "win240_newer": 0.6}
    xa.draft_proposals(tmp_path, [lesson], {xa._lesson_key(lesson): xa.STABLE_RUNS})
    prompts = []

    def ask(system, prompt, schema, **kw):
        prompts.append(prompt)
        return ai.AIResult(status="ABSTAIN", reason="test") if hasattr(ai, "AIResult") else None

    try:
        ac.model_council(tmp_path, ask=ask)
    except Exception:
        pass
    assert prompts and "Risk: HIGH" in prompts[0]


def test_busy_record_lock_waits_briefly_then_fails_only_that_agent(tmp_path, monkeypatch):
    """2026-10-02: a held log lock used to raise SystemExit straight through run_cycle and end the process."""
    import threading

    monkeypatch.setattr(cli, "LOCK_WAIT_S", 0.2)
    lock = tmp_path / (cli.MEMORY_LOG + ".lock")
    lock.write_text("held")

    def writer(_):
        cli.add_memory_record(tmp_path, {"record_id": "X-0001", "type": "OPERATIONS", "authority": "TEMPORARY",
                                         "title": "t", "body": "{}", "author": "quant_research", "source": "t"})
        return {"verdict": "OK", "summary": "wrote"}

    agents = (("a", "A", writer), ("b", "B", lambda _: {"verdict": "OK", "summary": "still runs"}))
    out = ac.run_cycle(tmp_path, agents)
    assert out["results"][0]["verdict"] == "FAIL" and "RecordLockBusy" in out["results"][0]["summary"]
    assert out["results"][1]["verdict"] == "OK"  # the next agent still ran
    assert out["record_id"] is None and "exists" in out["warning"]  # the cycle record waits for the next cycle
    assert issubclass(cli.RecordLockBusy, SystemExit)  # the CLI still exits with the same message

    # a lock released within the wait is simply taken
    monkeypatch.setattr(cli, "LOCK_WAIT_S", 2.0)
    threading.Timer(0.2, lock.unlink).start()
    assert writer(None)["verdict"] == "OK"


def test_cycle_reports_ai_calls_and_cost_from_the_usage_ledger(tmp_path, monkeypatch):
    from decimal import Decimal

    from tools.ai_gateway import UsageLedger

    ledger = UsageLedger(tmp_path / "usage.json")
    monkeypatch.setattr(ac, "_cycle_ai_usage", lambda start, end: ledger.between(start, end))

    def paid_agent(_):
        import time as _time
        ledger.add(_time.time(), Decimal("0.0206"), agent="ceo_ai")
        return {"verdict": "OK", "summary": "brief"}

    ledger.add(1.0, Decimal("5"), agent="old")  # outside the cycle: not counted
    out = ac.run_cycle(tmp_path, (("ceo_ai", "CEO", paid_agent),))
    assert out["resources"]["ai_calls"] == 1 and out["resources"]["ai_cost_usd"] == "0.0206"
    monkeypatch.setattr(ac, "_cycle_ai_usage", lambda start, end: None)
    out = ac.run_cycle(tmp_path, (("x", "X", lambda _: {"verdict": "OK", "summary": "x"}),))
    assert out["resources"]["ai_cost_usd"].startswith("UNKNOWN")  # never reported as zero
