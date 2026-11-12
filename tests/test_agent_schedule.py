"""Owner 2026-10-03: each agent on its own clock, only when its inputs changed, and no busywork records."""

from __future__ import annotations

import json
from types import SimpleNamespace

from atlas_org import memory_records
from tools import agent_cycle as ac
from tools import ai_gateway as ai
from tools import atlas_org_cli as cli


def _env(tmp_path, monkeypatch, schedule):
    records = tmp_path / "records"
    records.mkdir()
    monkeypatch.setattr(ac, "SCHEDULE", schedule)
    monkeypatch.setattr(ac, "_input_paths", lambda d: {
        "archive": tmp_path / "closed.jsonl", "audit": tmp_path / "audit.jsonl", "memory": d / cli.MEMORY_LOG,
        "proposals": d / cli.PROPOSALS_LOG, "tasks": d / cli.TASKS_LOG})
    monkeypatch.setattr(ac, "_cycle_ai_usage", lambda start, end: (0, 0))
    clock = {"t": 1_000_000.0}

    def tick(agents):
        return ac.run_scheduled(records, agents, state_path=tmp_path / "schedule.json", clock=lambda: clock["t"])
    return records, clock, tick


def _cycles(records):
    log = records / cli.MEMORY_LOG
    recs = memory_records.replay(cli.read_log(log)).values() if log.exists() else []
    return sorted((r for r in recs if str(r.get("id")).startswith("AC-")), key=lambda r: r["seq"])


def _writer(records, rid):
    cli.add_memory_record(records, {"record_id": rid, "type": "EXPERIMENTS", "authority": "RESEARCH",
                                    "title": rid, "body": "{}", "author": "quant_research", "source": "t"})


def test_every_real_agent_has_its_own_schedule():
    assert set(ac.SCHEDULE) == {unit for unit, _, _ in ac.AGENTS}
    assert all(minutes > 0 for minutes, _ in ac.SCHEDULE.values())
    assert ac.SCHEDULE["ceo_ai"][0] >= 60 * ac.CEO_MIN_GAP_H  # the paid brief is never asked for more often


def test_each_agent_runs_on_its_own_clock_and_only_on_new_input(tmp_path, monkeypatch):
    records, clock, tick = _env(tmp_path, monkeypatch, {"a": (10, ("archive",)), "b": (60, None)})
    archive = tmp_path / "closed.jsonl"
    archive.write_text("1\n", encoding="utf-8")
    calls = []
    agents = tuple((u, u.upper(), lambda d, u=u: calls.append(u) or {"verdict": "OK", "summary": f"{u} bitti"})
                   for u in ("a", "b"))
    assert tick(agents)["record_id"] and calls == ["a", "b"]          # first run of each
    clock["t"] += 5 * 60
    out = tick(agents)
    assert calls == ["a", "b"] and out["record_id"] is None            # nobody's turn: nothing runs, nothing recorded
    assert {s["unit"] for s in out["skipped"]} == {"a", "b"}
    clock["t"] += 6 * 60                                               # 11 min: a's turn, but its input is unchanged
    out = tick(agents)
    assert calls == ["a", "b"]
    assert "yeni girdi yok" in next(s for s in out["skipped"] if s["unit"] == "a")["summary"]
    archive.write_text("1\n2\n", encoding="utf-8")                     # a new closed trade
    tick(agents)
    assert calls == ["a", "b", "a"]
    clock["t"] += 50 * 60                                              # 61 min: b runs on its clock alone
    tick(agents)
    assert calls[-1] == "b"


def test_failed_or_unfinished_agents_are_retried_without_new_input(tmp_path, monkeypatch):
    records, clock, tick = _env(tmp_path, monkeypatch, {"f": (10, ("archive",)), "p": (10, ("archive",))})
    seen = {"f": 0, "p": 0}

    def flaky(_):
        seen["f"] += 1
        if seen["f"] == 1:
            raise RuntimeError("network")
        return {"verdict": "OK", "summary": "ok"}

    def backlog(_):
        seen["p"] += 1
        return {"verdict": "OK", "summary": "1 kaldı", "pending": seen["p"] == 1}

    agents = (("f", "F", flaky), ("p", "P", backlog))
    tick(agents)
    clock["t"] += 11 * 60
    tick(agents)                                                       # input unchanged, yet both come back
    assert seen == {"f": 2, "p": 2}
    clock["t"] += 11 * 60
    tick(agents)                                                       # now clean and finished: left alone
    assert seen == {"f": 2, "p": 2}


def test_quiet_ticks_are_not_recorded_but_an_hourly_heartbeat_is(tmp_path, monkeypatch):
    records, clock, tick = _env(tmp_path, monkeypatch, {"q": (10, None)})
    quiet = (("q", "Q", lambda _: {"verdict": "OK", "summary": "değişiklik yok"}),)
    assert tick(quiet)["record_id"]                                    # first tick: recorded
    for _ in range(4):                                                 # 10..40 min: ran, changed nothing
        clock["t"] += 10 * 60
        assert tick(quiet)["record_id"] is None
    clock["t"] += 20 * 60                                              # 60 min after the last record
    assert tick(quiet)["record_id"]
    assert len(_cycles(records)) == 2
    clock["t"] += 10 * 60
    writes = (("q", "Q", lambda d: _writer(d, "PR-0100") or {"verdict": "OK", "summary": "rapor yazıldı"}),)
    assert tick(writes)["record_id"]                                   # something changed: recorded at once
    clock["t"] += 10 * 60
    assert tick((("q", "Q", lambda _: {"verdict": "WARN", "summary": "veri yok"}),))["record_id"]  # and a warning


def test_cycle_record_keeps_skipped_agents_visible_on_the_dashboard(tmp_path, monkeypatch):
    from observability import agent_states

    records, clock, tick = _env(tmp_path, monkeypatch, {"quant_research": (10, None), "security": (60, None)})
    agents = (("quant_research", "Performans", lambda d: {"verdict": "OK", "summary": "12 işlem"}),
              ("security", "Güvenlik", lambda d: {"verdict": "OK", "summary": "genel PASS"}))
    tick(agents)
    clock["t"] += 11 * 60
    agents = (("quant_research", "Performans", lambda d: _writer(d, "PR-0200") or {"verdict": "OK", "summary": "13 işlem"}),
              agents[1])
    out = tick(agents)
    body = json.loads(_cycles(records)[-1]["body"])["agent_cycle"]
    sec = next(r for r in body if r["unit"] == "security")
    assert out["record_id"] and sec["ran"] is False and "sırası değil" in sec["summary"] and "genel PASS" in sec["summary"]
    memory = {"available": True, "records": memory_records.public_view(
        memory_records.replay(cli.read_log(records / cli.MEMORY_LOG)))}
    states = {a["id"]: a for a in agent_states.build({}, {}, memory, None)["agents"]}
    assert states["security"]["state"] == "IDLE" and states["quant_research"]["state"] == "IDLE"


def test_unreadable_schedule_or_a_clock_going_back_never_silences_an_agent(tmp_path, monkeypatch):
    records, clock, tick = _env(tmp_path, monkeypatch, {"a": (60, None)})
    calls = []
    agents = (("a", "A", lambda _: calls.append(1) or {"verdict": "OK", "summary": "ok"}),)
    tick(agents)
    (tmp_path / "schedule.json").write_text("{not json", encoding="utf-8")
    tick(agents)                                                       # unreadable: due again (old behaviour)
    clock["t"] -= 3600                                                 # clock went back an hour
    tick(agents)
    assert len(calls) == 3


def test_market_regime_records_only_when_the_map_changes(tmp_path):
    up = [100 * 1.002 ** i for i in range(200)]
    down = [100 * 0.998 ** i for i in range(200)]
    assert ac.market_regime(tmp_path, ["XUSDT"], lambda s: up)["verdict"] == "OK"
    again = ac.market_regime(tmp_path, ["XUSDT"], lambda s: up)
    assert "rejim değişmedi" in again["summary"]
    ac.market_regime(tmp_path, ["XUSDT"], lambda s: down)
    mr = [r for r in memory_records.replay(cli.read_log(tmp_path / cli.MEMORY_LOG)).values() if r["author"] == "market_regime"]
    assert len(mr) == 2 and json.loads(mr[0]["body"])["coins"] != json.loads(mr[1]["body"])["coins"]


def test_self_review_records_only_new_tasks_or_new_refusals(tmp_path, monkeypatch):
    from tools import atlas_self_review as sr

    def sr_records():
        return [r for r in memory_records.replay(cli.read_log(tmp_path / cli.MEMORY_LOG)).values()
                if str(r["id"]).startswith("SR-")]

    monkeypatch.setattr(sr, "collect", lambda records: [
        {"source": "code_health", "request": "refactor a.py (over 300 lines) into smaller tested functions"}])
    assert sr.run(tmp_path, apply=True)["filed"]                       # a new task: recorded
    assert sr.run(tmp_path, apply=True)["skipped_duplicates"]          # still open: not news, not recorded
    assert len(sr_records()) == 1
    monkeypatch.setattr(sr, "collect", lambda records: [{"source": "code_health", "request": "belirsiz istek"}])
    assert sr.run(tmp_path, apply=True)["refused"]                     # a refusal not seen before: recorded
    assert sr.run(tmp_path, apply=True)["refused"]                     # the same refusal again: not recorded
    assert len(sr_records()) == 2


def _evidence(tmp_path):
    d = tmp_path / "records"
    for n, body in ((1, {"total": {"trades": 40}, "reality": {"costs": {"edge_covers_costs": False}}}),
                    (2, {"bands": [], "overconfident_bands": ["70-75"]}), (3, {"counts": {"TREND_UP": 3}})):
        cli.add_memory_record(d, {"record_id": f"EV-000{n}", "type": "EXPERIMENTS", "authority": "RESEARCH",
                                  "title": f"Kanıt {n}", "body": json.dumps(body), "author": "quant_research", "source": "t"})
    return d


def test_ceo_reads_record_bodies_and_an_empty_answer_records_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "_research_dir", lambda: tmp_path)
    d = _evidence(tmp_path)
    prompts = []

    def nothing(system, prompt, *a, **k):
        prompts.append(prompt)
        return ai.AIResult("OK", data={"priorities": [], "cited_records": []}, model="m")

    out = ac.ceo_brief(d, ask=nothing)
    assert "kayıt yazılmadı" in out["summary"] and out.get("pending") is None
    assert "edge_covers_costs" in prompts[0] and "overconfident_bands" in prompts[0]   # bodies, not only titles
    assert "how many agents" in prompts[0]                                              # no trivia asked for
    assert not [r for r in memory_records.replay(cli.read_log(d / cli.MEMORY_LOG)).values() if r["author"] == "ceo_ai"]
    abstain = ac.ceo_brief(d, ask=lambda *a, **k: ai.AIResult("ABSTAIN", reason="WINDOW"))
    assert abstain["pending"] is True                                                    # the scheduler comes back


def test_council_reviews_what_waits_with_evidence_and_comes_back_for_the_rest(tmp_path, monkeypatch):
    from atlas_org import proposals as P

    monkeypatch.setattr(ac, "_research_dir", lambda: tmp_path)
    d = _evidence(tmp_path)
    cli.add_memory_record(d, {"record_id": "RT-0001", "type": "REVIEWS", "authority": "TEMPORARY",
                              "title": "Karşı görüş: SA-1 — KANIT YETERSİZ", "body": json.dumps({"challenge": "örnek küçük"}, ensure_ascii=False),
                              "author": "red_team", "related_proposal": "SA-1", "source": "t"})
    props = {f"SA-{i}": SimpleNamespace(status="DRAFT", fields={"title": f"öneri {i}", "risk_level": "HIGH"}) for i in range(1, 5)}
    monkeypatch.setattr(P, "replay", lambda log: props)
    (d / cli.PROPOSALS_LOG).write_text("", encoding="utf-8")
    prompts = []

    def support(system, prompt, *a, **k):
        prompts.append(prompt)
        return ai.AIResult("OK", data={"verdict": "SUPPORT", "reasons": ["kanıt yeterli"]})

    out = ac.model_council(d, ask=support)
    assert out["pending"] is True and "1 öneri sonraki çalışmaya kaldı" in out["summary"]
    assert "örnek küçük" in prompts[0] and "Kanıt 3" in prompts[0] and "Risk: HIGH" in prompts[0]  # newest report
    out = ac.model_council(d, ask=support)
    assert out["pending"] is False and out["summary"] == "SA-4: SUPPORT"
    mc = [r for r in memory_records.replay(cli.read_log(d / cli.MEMORY_LOG)).values() if r["author"] == "model_council"]
    assert sorted(r["related_proposal"] for r in mc) == ["SA-1", "SA-2", "SA-3", "SA-4"]  # each reviewed once
    props["SA-5"] = SimpleNamespace(status="DRAFT", fields={"title": "öneri 5", "risk_level": "LOW"})
    out = ac.model_council(d, ask=lambda *a, **k: ai.AIResult("ABSTAIN", reason="NO_QUOTA"))
    assert out["pending"] is True and "çekimser" in out["summary"]                        # retried later, not lost


def test_audit_m2_a_skipped_agent_keeps_showing_its_failure(tmp_path, monkeypatch):
    from observability import agent_states

    records, clock, tick = _env(tmp_path, monkeypatch, {"data_quality": (60, None), "quant_research": (10, None)})
    agents = (("data_quality", "Veri", lambda d: {"verdict": "FAIL", "summary": "disk dolu"}),
              ("quant_research", "Performans", lambda d: _writer(d, f"PR-{clock['t']:.0f}") or {"verdict": "OK", "summary": "ok"}))
    tick(agents)
    clock["t"] += 11 * 60                                              # quant runs again; data_quality is skipped
    tick(agents)
    body = json.loads(_cycles(records)[-1]["body"])["agent_cycle"]
    dq = next(r for r in body if r["unit"] == "data_quality")
    assert dq["ran"] is False and dq["verdict"] == "FAIL"
    memory = {"available": True, "records": memory_records.public_view(
        memory_records.replay(cli.read_log(records / cli.MEMORY_LOG)))}
    assert {a["id"]: a for a in agent_states.build({}, {}, memory, None)["agents"]}["data_quality"]["state"] == "ERROR"


def test_audit_m3_an_agent_cut_off_last_time_is_failed_and_does_not_block_the_others(tmp_path, monkeypatch):
    records, clock, tick = _env(tmp_path, monkeypatch, {"stuck": (60, None), "next": (10, None)})
    state = tmp_path / "schedule.json"
    state.write_text(json.dumps({"units": {"stuck": {"last_run": clock["t"] - 7200, "verdict": "OK",
                                                     "running_since": clock["t"] - 600}}}), encoding="utf-8")
    calls = []
    agents = (("stuck", "Stuck", lambda d: calls.append("stuck") or {"verdict": "OK", "summary": "ok"}),
              ("next", "Next", lambda d: calls.append("next") or {"verdict": "OK", "summary": "ok"}))
    out = tick(agents)
    assert calls == ["next"]                                            # the cut-off agent waits for its interval
    stuck = next(r for r in out["results"] if r["unit"] == "stuck")
    assert stuck["verdict"] == "FAIL" and "yarıda kaldı" in stuck["summary"]
    assert any(r["type"] == "INCIDENTS" for r in memory_records.replay(cli.read_log(records / cli.MEMORY_LOG)).values())
    saved = json.loads(state.read_text(encoding="utf-8"))["units"]
    assert all("running_since" not in e for e in saved.values())        # nothing is left marked as running
    clock["t"] += 51 * 60                                               # its own interval after the cut-off
    tick(agents)
    assert calls == ["next", "stuck", "next"]                            # retried once its interval has passed


def test_audit_l1_a_new_incident_is_still_new_input(tmp_path, monkeypatch):
    records, clock, tick = _env(tmp_path, monkeypatch, {"x": (10, None), "overview_snapshot": (10, ("memory",))})
    seen = []
    agents = (("x", "X", lambda d: {"verdict": "FAIL", "summary": "boom"}),
              ("overview_snapshot", "Özet", lambda d: seen.append(1) or {"verdict": "OK", "summary": "ok"}))
    tick(agents)                                                       # x fails: an incident is opened, then the AC
    clock["t"] += 11 * 60
    tick(agents)
    assert len(seen) == 2                                              # the incident counted as new memory input


def test_audit_l6_a_schedule_that_cannot_be_saved_is_reported(tmp_path, monkeypatch):
    records, clock, tick = _env(tmp_path, monkeypatch, {"a": (10, None)})
    monkeypatch.setattr(ac, "_save_schedule", lambda path, state: False)
    out = tick((("a", "A", lambda d: {"verdict": "OK", "summary": "ok"}),))
    assert out["schedule_save_failed"] is True and "zamanlama kaydedilemedi" in _cycles(records)[-1]["title"]


def test_audit_l3_every_must_be_a_sane_number_of_minutes():
    import argparse

    import pytest
    for bad in ("0", "-5", "nan", "inf", "abc", "2000"):
        with pytest.raises(argparse.ArgumentTypeError):
            ac.minutes(bad)
    assert ac.minutes("5") == 5.0 and ac.minutes("0.5") == 0.5


def test_audit_m3_sleep_beats_while_it_waits(monkeypatch):
    import threading
    now = {"t": 0.0}
    monkeypatch.setattr(ac.time, "monotonic", lambda: now["t"])
    beats = []

    class Clockwork(threading.Event):
        def wait(self, timeout=None):
            now["t"] += timeout or 0
            return False
    assert ac._sleep(Clockwork(), 300, beat=lambda: beats.append(now["t"])) is False
    assert len(beats) >= 4                                              # about once a minute over five minutes
