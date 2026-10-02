"""AI-001 gateway + agents (Claude API, owner choice 2026-10-02). No network: a fake client stands in."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from tools import agent_cycle as ac
from tools import ai_gateway as ai
from tools import atlas_org_cli as cli

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["a"], "properties": {"a": {"type": "string"}}}


def fake(text, stop="end_turn", model="claude-opus-5-5", calls=None, raise_exc=None):
    def create(**kw):
        if calls is not None:
            calls.append(kw)
        if raise_exc:
            raise raise_exc
        return SimpleNamespace(stop_reason=stop, model=model, content=[SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=500))
    return lambda: SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_ok_answer_is_schema_validated_costed_and_ledgered(tmp_path):
    calls, ledger = [], ai.UsageLedger(tmp_path / "u.json")
    r = ai.ask("sys", "q api_key=sk-abc123456789abcdef", SCHEMA, ledger=ledger, client_factory=fake('{"a": "x"}', calls=calls), now=NOW)
    assert r.status == "OK" and r.data == {"a": "x"}
    assert r.cost_usd == Decimal("0.014")  # 1000*4 + 500*20 per 1M
    assert ledger.spent_today("2026-10-02") == Decimal("0.014")
    sent = calls[0]
    assert "sk-abc123456789abcdef" not in json.dumps(sent["messages"])          # SensitiveDataGuard
    assert sent["output_config"]["format"]["schema"] == SCHEMA and sent["fallbacks"] == "default"


def test_every_failure_abstains(tmp_path):
    ledger = ai.UsageLedger(tmp_path / "u.json")
    for factory, reason in ((fake("not json"), "MALFORMED"), (fake('{"b": 1}'), "MALFORMED"),
                            (fake('{"a": "x"}', stop="refusal"), "REFUSAL"),
                            (fake('{"a": "x"}', stop="max_tokens"), "TRUNCATED"),
                            (fake("", raise_exc=TimeoutError()), "UNAVAILABLE")):
        r = ai.ask("s", "q", SCHEMA, ledger=ledger, client_factory=factory, now=NOW)
        assert r.status == "ABSTAIN" and reason in r.reason and r.data is None


def test_budget_and_unreadable_ledger_stop_spending(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_AI_DAILY_BUDGET_USD", "0.01")
    ledger = ai.UsageLedger(tmp_path / "u.json")
    ledger.add("2026-10-02", Decimal("0.006"))  # 60 % of 0.01 already used
    assert "DAILY_BUDGET" in ai.ask("s", "q", SCHEMA, ledger=ledger, client_factory=fake('{"a":"x"}'), now=NOW).reason
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert "UNREADABLE" in ai.ask("s", "q", SCHEMA, ledger=ai.UsageLedger(tmp_path / "bad.json"),
                                  client_factory=fake('{"a":"x"}'), now=NOW).reason
    monkeypatch.setenv("ATLAS_AI_DAILY_BUDGET_USD", "abc")
    assert ai.daily_budget() == 0


def test_without_credentials_agents_abstain_honestly(tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    r = ai.ask("s", "q", SCHEMA, ledger=ai.UsageLedger(tmp_path / "u.json"), now=NOW)
    assert r.status == "ABSTAIN" and "NO_CREDENTIALS" in r.reason


def _records(tmp_path):
    d = tmp_path / "records"
    cli.add_memory_record(d, {"record_id": "MR-0001", "type": "EXPERIMENTS", "authority": "RESEARCH",
                              "title": "Piyasa rejimi", "body": "{}", "author": "market_regime", "source": "t"})
    return d


def test_ceo_brief_rejects_invented_citations_and_records_grounded_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "_research_dir", lambda: tmp_path)
    d = _records(tmp_path)
    ok = lambda *a, **k: ai.AIResult("OK", data={"priorities": ["rejimi izle"], "cited_records": ["MR-9999"]}, model="m")
    assert "reddedildi" in ac.ceo_brief(d, ask=ok)["summary"]
    good = lambda *a, **k: ai.AIResult("OK", data={"priorities": ["rejimi izle"], "cited_records": ["MR-0001"]}, model="m")
    assert "1 öncelik" in ac.ceo_brief(d, ask=good)["summary"]
    abstain = lambda *a, **k: ai.AIResult("ABSTAIN", reason="NO_CREDENTIALS")
    assert "çekimser" in ac.ceo_brief(d, ask=abstain)["summary"]


def test_council_records_disagreement_and_reviews_once(tmp_path, monkeypatch):
    from atlas_org import memory_records
    monkeypatch.setattr(ac, "_research_dir", lambda: tmp_path)
    d = _records(tmp_path)
    open_prop = SimpleNamespace(status="DRAFT", fields={"title": "t", "risk": "HIGH"})
    from atlas_org import proposals as P
    monkeypatch.setattr(P, "replay", lambda log: {"SA-1": open_prop})
    (d / cli.PROPOSALS_LOG).write_text("", encoding="utf-8")
    answers = iter([ai.AIResult("OK", data={"verdict": "SUPPORT", "reasons": ["a"]}),
                    ai.AIResult("OK", data={"verdict": "OPPOSE", "reasons": ["b"]})])
    out = ac.model_council(d, ask=lambda *a, **k: next(answers))
    assert out["summary"] == "SA-1: DISAGREEMENT"
    assert "yeni öneri yok" in ac.model_council(d, ask=lambda *a, **k: ai.AIResult("ABSTAIN", reason="x"))["summary"]
    mc = [r for r in memory_records.replay(cli.read_log(d / cli.MEMORY_LOG)).values() if r["author"] == "model_council"]
    assert len(mc) == 1 and mc[0]["authority"] == "TEMPORARY"


def test_gateway_stays_out_of_the_trading_runtime():
    import json as _j
    from pathlib import Path
    closure = _j.loads((Path(__file__).resolve().parents[1] / "packaging" / "atlas_runtime_closure.json").read_text())
    assert "tools/ai_gateway.py" not in _j.dumps(closure)


def test_owner_quota_rule_60_percent_total_split_by_task_size(monkeypatch):
    # Owner 2026-10-02: all agents together max 60 % of the daily budget, split by task size.
    monkeypatch.setenv("ATLAS_AI_DAILY_BUDGET_USD", "3.00")
    assert ai.agent_cap(None) == Decimal("1.80")
    assert ai.agent_cap("ceo_ai") == Decimal("0.60")        # weight 1 of 3
    assert ai.agent_cap("model_council") == Decimal("1.20")  # weight 2 of 3 (two models per run)
    assert sum(ai.agent_cap(a) for a in ai.AGENT_WEIGHTS) <= ai.agent_cap(None)
    assert ai.agent_cap("unknown_agent") == 0                # an unlisted agent cannot spend


def test_an_agent_stops_at_its_own_share_while_others_continue(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_AI_DAILY_BUDGET_USD", "3.00")
    ledger = ai.UsageLedger(tmp_path / "u.json")
    ledger.add("2026-10-02", Decimal("0.60"), "ceo_ai")
    blocked = ai.ask("s", "q", SCHEMA, ledger=ledger, client_factory=fake('{"a":"x"}'), now=NOW, agent="ceo_ai")
    assert blocked.status == "ABSTAIN" and "AGENT_QUOTA_REACHED" in blocked.reason
    ok = ai.ask("s", "q", SCHEMA, ledger=ledger, client_factory=fake('{"a":"x"}'), now=NOW, agent="model_council")
    assert ok.status == "OK" and ledger.spent_today("2026-10-02", "model_council") == Decimal("0.014")
