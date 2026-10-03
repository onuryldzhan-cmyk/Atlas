"""Owner 2026-10-03: agents build on what they did before - follow-ups, learning from decisions, deltas -
instead of asking or reporting the same things again. Advice only: nothing here decides or changes a gate."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from atlas_org import memory_records
from tools import agent_cycle as ac
from tools import ai_gateway as ai
from tools import atlas_org_cli as cli


def _mem(d):
    return list(memory_records.replay(cli.read_log(d / cli.MEMORY_LOG)).values())


def _evidence(d, n, body=None, author="quant_research"):
    cli.add_memory_record(d, {"record_id": f"EV-{n:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
                              "title": f"Kanıt {n}", "body": json.dumps(body or {"n": n}, ensure_ascii=False),
                              "author": author, "source": "t"})


def test_ceo_builds_on_its_previous_brief_and_marks_new_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "_research_dir", lambda: tmp_path)
    d = tmp_path / "records"
    for n in (1, 2, 3):
        _evidence(d, n)
    first = lambda *a, **k: ai.AIResult("OK", data={"priorities": ["kenar maliyeti karşılamıyor: ücret modelini doğrula"],
                                                    "followups": [], "cited_records": ["EV-0001"]}, model="m")
    assert "1 öncelik" in ac.ceo_brief(d, ask=first)["summary"]
    monkeypatch.setattr(cli, "now", lambda: "2999-01-01T00:00:00Z")   # newer than the brief
    _evidence(d, 4, {"total": {"trades": 60, "verdict": "STRONG"}})
    prompts = []

    def follow(system, prompt, *a, **k):
        prompts.append(prompt)
        return ai.AIResult("OK", data={"priorities": [], "followups": ["ücret modeli: EV-0004 ile çözüldü, kapat"],
                                       "cited_records": ["EV-0004"]}, model="m")

    out = ac.ceo_brief(d, ask=follow, min_gap_h=0, now=datetime(3000, 1, 1, tzinfo=timezone.utc))
    assert "0 öncelik, 1 takip" in out["summary"]
    prompt = prompts[0]
    assert "Your previous brief CEO-" in prompt and "ücret modelini doğrula" in prompt     # it sees what it said
    assert "[EV-0004] NEW" in prompt and "[EV-0001] NEW" not in prompt                   # and what is new since
    assert "never an earlier priority again unchanged" in prompt
    briefs = sorted((r for r in _mem(d) if r["author"] == "ceo_ai"), key=lambda r: r["seq"])
    body = json.loads(briefs[-1]["body"])
    assert body["builds_on"] == briefs[0]["id"] and body["followups"] and body["priorities"] == []


def test_ceo_schema_asks_for_followups():
    assert "followups" in ac._CEO_SCHEMA["required"] and "followups" in ac._CEO_SCHEMA["properties"]


def test_council_learns_the_owners_bar_from_earlier_decisions(tmp_path, monkeypatch):
    from atlas_org import proposals as P

    monkeypatch.setattr(ac, "_research_dir", lambda: tmp_path)
    d = tmp_path / "records"
    _evidence(d, 1)
    cli.add_memory_record(d, {"record_id": "MC-0002", "type": "OPERATIONS", "authority": "TEMPORARY",
                              "title": "Model konseyi SA-1: SUPPORT", "author": "model_council", "related_proposal": "SA-1",
                              "body": json.dumps({"outcome": "SUPPORT"}), "source": "t"})
    props = {"SA-1": SimpleNamespace(status="REJECTED", fields={"title": "ücreti düşür"},
                                     owner_decision={"decision": "REJECTED", "note": "örnek 30 işlemden az"}),
             "SA-2": SimpleNamespace(status="DRAFT", fields={"title": "yeni öneri", "risk_level": "MEDIUM"})}
    monkeypatch.setattr(P, "replay", lambda log: props)
    (d / cli.PROPOSALS_LOG).write_text("", encoding="utf-8")
    prompts = []
    ac.model_council(d, ask=lambda system, prompt, *a, **k: prompts.append(prompt) or ai.AIResult(
        "OK", data={"verdict": "UNSURE", "reasons": ["örnek az"]}))
    assert prompts and "Proposal SA-2" in prompts[0]
    assert "SA-1 'ücreti düşür': owner REJECTED - örnek 30 işlemden az; council said SUPPORT" in prompts[0]
    assert "matched 0 of 1" in prompts[0]                                                # its own miss, shown to it


def test_performance_report_states_what_changed_since_the_previous_one(tmp_path, monkeypatch):
    archive = tmp_path / "closed.jsonl"
    row = {"symbol": "BTCUSDT", "cost_quote": "1000", "gross_pnl": "0.5",
           "opened_at": "2026-09-29T10:00:00+00:00", "closed_at": "2026-09-29T10:30:00+00:00"}
    monkeypatch.setattr(ac, "_archive_path", lambda: archive)
    monkeypatch.setattr(ac, "_approvals", lambda: {})
    records = tmp_path / "records"
    archive.write_text("".join(json.dumps(row) + "\n" for _ in range(12)), encoding="utf-8")
    ac.quant_research(records)
    archive.write_text("".join(json.dumps(row) + "\n" for _ in range(15)), encoding="utf-8")
    ac.quant_research(records)
    reports = sorted((r for r in _mem(records) if r["author"] == "quant_research"), key=lambda r: r["seq"])
    assert json.loads(reports[0]["body"])["since_last_report"] is None                  # first report: nothing before
    since = json.loads(reports[1]["body"])["since_last_report"]
    assert since["new_trades"] == 3 and since["net_change"] is not None
    assert "+3 yeni işlem" in reports[1]["title"]
