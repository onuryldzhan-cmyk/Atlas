"""Apprentice (owner 2026-10-03): learns from the AI-001 advisors' answers - predict first, then compare, then learn -
keeps an honest scorecard, never calls a model and never takes over without the owner."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from atlas_org import memory_records
from tools import apprentice as ap
from tools import atlas_org_cli as cli


def _add(d, rid, author, title="t", body=None, **extra):
    cli.add_memory_record(d, {"record_id": rid, "type": "OPERATIONS", "authority": "TEMPORARY", "title": title,
                              "body": json.dumps(body or {}, ensure_ascii=False), "author": author, "source": "t", **extra})


def _records(d, prefix):
    return [r for r in memory_records.replay(cli.read_log(d / cli.MEMORY_LOG)).values() if r["id"].startswith(prefix)]


def test_council_is_predicted_first_then_learned_and_improves_on_a_repeated_pattern(tmp_path):
    d = tmp_path / "records"
    props = {}
    plan = [("SA-1", "HIGH", "yetersiz", "OPPOSE"), ("SA-2", "HIGH", "yetersiz", "OPPOSE"),
            ("SA-3", "LOW", "kabul", "SUPPORT"), ("SA-4", "HIGH", "yetersiz", "OPPOSE")]
    for i, (pid, risk, view, outcome) in enumerate(plan):
        props[pid] = SimpleNamespace(fields={"risk_level": risk, "claims": [{"claim": "x"}]})
        _add(d, f"RT-{i:04d}", "red_team", title=f"Karşı görüş: {pid} — {'KANIT YETERSİZ' if view == 'yetersiz' else 'KANIT KABUL EDİLEBİLİR'}",
             related_proposal=pid)
        _add(d, f"MC-{i:04d}", "model_council", title=f"Model konseyi {pid}: {outcome}", body={"outcome": outcome},
             related_proposal=pid)
    out = ap.run(d, tmp_path / "research", proposals=props)
    state = json.loads((tmp_path / "research" / "apprentice" / ap.STATE_FILE).read_text(encoding="utf-8"))
    guesses = [(h["guess"], h["actual"], h["hit"]) for h in state["council"]["history"]]
    assert guesses == [(None, "OPPOSE", False),          # knew nothing yet: an honest miss
                       ("OPPOSE", "OPPOSE", True),
                       ("OPPOSE", "SUPPORT", False),     # never seen a SUPPORT before: missed, then learned
                       ("OPPOSE", "OPPOSE", True)]
    assert "konsey uyumu 2/4" in out["summary"] and "HAZIR DEĞİL" in out["summary"]
    assert len(_records(d, "AP-")) == 1 and _records(d, "AP-")[0]["author"] == "ai_model_research"
    again = ap.run(d, tmp_path / "research", proposals=props)
    assert "yeni cevap yok" in again["summary"] and len(_records(d, "AP-")) == 1   # nothing new: no record


def test_ceo_evidence_selection_is_learned_from_what_the_ceo_cited(tmp_path):
    d = tmp_path / "records"
    n = 0
    for brief in range(6):
        ids = []
        for j in range(4):                                # each round: 2 calibration warnings, 2 routine regime notes
            n += 1
            mv = j < 2
            rid = f"{'MV' if mv else 'MR'}-{n:04d}"
            _add(d, rid, "model_validation" if mv else "market_regime",
                 title="Model doğrulama: AŞIRI GÜVEN 60-70 bandında" if mv else "Piyasa rejimi: SIDEWAYS 5")
            ids.append(rid)
        _add(d, f"CEO-{brief:04d}", "ceo_ai", title="CEO özeti", body={"priorities": ["kalibrasyon"], "cited_records": ids[:2]})
    ap.run(d, tmp_path / "research", proposals={})
    history = json.loads((tmp_path / "research" / "apprentice" / ap.STATE_FILE).read_text(encoding="utf-8"))["ceo"]["history"]
    assert len(history) == 6 and history[-1]["overlap"] == 1.0          # it learned what the CEO picks
    card = json.loads(_records(d, "AP-")[0]["body"])
    assert card["what_the_ceo_values"][0]["feature"] in ("author=model_validation", "word=aşırı", "word=güven",
                                                          "word=doğrulama", "word=bandında", "word=model")


def test_readiness_needs_enough_evidence_and_only_ever_suggests(tmp_path):
    state = ap._load_state(tmp_path / "none.json")
    state["council"]["history"] = [{"hit": True}] * 29
    assert ap.scorecard(state, 0)["council"]["ready"] is False                 # 29 is not enough
    state["council"]["history"] = [{"hit": True}] * 30
    assert ap.scorecard(state, 0)["council"]["ready"] is True                  # 30/30: Wilson low ~0.89
    state["council"]["history"] = [{"hit": True}] * 25 + [{"hit": False}] * 5
    assert ap.scorecard(state, 0)["council"]["ready"] is False                 # 25/30: low bound < 0.80
    assert "owner's approval" in ap.scorecard(state, 0)["rule"]
    source = Path(ap.__file__).read_text(encoding="utf-8")
    assert "ai_gateway" not in source.split('"""', 2)[2]                       # it never asks a model itself


def test_scorecard_counts_the_teacher_examples(tmp_path):
    teacher = tmp_path / "research" / "apprentice" / ap.TEACHER_FILE
    teacher.parent.mkdir(parents=True)
    teacher.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    d = tmp_path / "records"
    _add(d, "MC-0001", "model_council", body={"outcome": "SUPPORT"}, related_proposal="SA-1")
    ap.run(d, tmp_path / "research", proposals={"SA-1": SimpleNamespace(fields={"risk_level": "LOW"})})
    assert json.loads(_records(d, "AP-")[0]["body"])["teacher_examples"] == 2


def test_an_unreadable_state_starts_over_instead_of_failing(tmp_path):
    state_file = tmp_path / "research" / "apprentice" / ap.STATE_FILE
    state_file.parent.mkdir(parents=True)
    state_file.write_text("{broken", encoding="utf-8")
    d = tmp_path / "records"
    _add(d, "MC-0001", "model_council", body={"outcome": "OPPOSE"}, related_proposal="SA-1")
    out = ap.run(d, tmp_path / "research", proposals={})
    assert out["verdict"] == "OK" and "konsey uyumu 0/1" in out["summary"]


def test_the_gateway_keeps_every_new_validated_answer_for_the_apprentice(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from tools import ai_gateway as ai

    monkeypatch.delenv("ATLAS_AI_WINDOW_CALLS", raising=False)
    now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    schema = {"type": "object", "additionalProperties": False, "required": ["a"], "properties": {"a": {"type": "string"}}}
    ledger = ai.UsageLedger(tmp_path / "research" / ai.USAGE_FILE)
    ok = lambda prompt, system, schema, model, effort: {"structured_output": {"a": "x"}, "total_cost_usd": 0.01}
    bad = lambda prompt, system, schema, model, effort: {"structured_output": {"b": 1}}
    ai.ask("sys", "soru api_key=sk-abc123456789abcdef", schema, ledger=ledger, now=now, agent="ceo_ai", runner=ok)
    ai.ask("sys", "soru api_key=sk-abc123456789abcdef", schema, ledger=ledger, now=now, agent="ceo_ai", runner=ok)  # cached
    ai.ask("sys", "başka", schema, ledger=ledger, now=now, agent="model_council", runner=bad)                       # malformed
    teacher = tmp_path / "research" / "apprentice" / ap.TEACHER_FILE
    lines = [json.loads(x) for x in teacher.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["agent"] == "ceo_ai" and lines[0]["answer"] == {"a": "x"}
    assert "sk-abc123456789abcdef" not in teacher.read_text(encoding="utf-8")            # what was sent, guarded


def test_the_trade_review_may_ask_and_the_apprentice_may_not():
    from tools import ai_gateway as ai

    assert "explainable_ai" in ai.AI_AGENTS and "ai_model_research" not in ai.AI_AGENTS
