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


def fake(text, stop="end_turn", model="claude-sonnet-5-5", calls=None, raise_exc=None):
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
    assert r.cost_usd == Decimal("0.007")  # Sonnet 5.5: 1000*2 + 500*10 per 1M
    assert ledger.spent(NOW.timestamp()) == Decimal("0.007")
    sent = calls[0]
    assert "sk-abc123456789abcdef" not in json.dumps(sent["messages"])          # SensitiveDataGuard
    assert sent["output_config"]["format"]["schema"] == SCHEMA and sent["fallbacks"] == "default"
    assert sent["model"] == "claude-sonnet-5-5" and sent["output_config"]["effort"] == "high"  # owner choice


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
    ledger.add(NOW.timestamp() - 3600, Decimal("0.006"))  # 60 % of 0.01 used one hour ago
    assert "WINDOW_BUDGET" in ai.ask("s", "q", SCHEMA, ledger=ledger, client_factory=fake('{"a":"x"}'), now=NOW).reason
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert "UNREADABLE" in ai.ask("s", "q", SCHEMA, ledger=ai.UsageLedger(tmp_path / "bad.json"),
                                  client_factory=fake('{"a":"x"}'), now=NOW).reason
    monkeypatch.setenv("ATLAS_AI_DAILY_BUDGET_USD", "abc")
    assert ai.daily_budget() == 0


def test_without_credentials_agents_abstain_honestly(tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    r = ai.ask("s", "q", SCHEMA, ledger=ai.UsageLedger(tmp_path / "u.json"), now=NOW, backend="api")
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
    # min_gap_h=0 + a newer record: since 2026-10-02 the CEO waits CEO_MIN_GAP_H after a brief (tested below)
    monkeypatch.setattr(cli, "now", lambda: "2999-01-01T00:00:00Z")
    cli.add_memory_record(d, {"record_id": "MR-0002", "type": "EXPERIMENTS", "authority": "RESEARCH",
                              "title": "Yeni kanıt", "body": "{}", "author": "market_regime", "source": "t"})
    assert "çekimser" in ac.ceo_brief(d, ask=abstain, min_gap_h=0)["summary"]


def test_ceo_spaces_calls_and_skips_without_new_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "_research_dir", lambda: tmp_path)
    d = _records(tmp_path)
    calls = []
    good = lambda *a, **k: calls.append(1) or ai.AIResult(
        "OK", data={"priorities": ["rejimi izle"], "cited_records": ["MR-0001"]}, model="m")
    assert "1 öncelik" in ac.ceo_brief(d, ask=good)["summary"]
    later = datetime.now(timezone.utc).replace(microsecond=0)
    from datetime import timedelta
    assert "beklenir" in ac.ceo_brief(d, ask=good, now=later + timedelta(hours=1))["summary"]
    assert "yeni kayıt yok" in ac.ceo_brief(d, ask=good, now=later + timedelta(hours=3))["summary"]
    assert len(calls) == 1  # neither skip spent quota


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
    ledger.add(NOW.timestamp(), Decimal("0.60"), "ceo_ai")
    blocked = ai.ask("s", "q", SCHEMA, ledger=ledger, client_factory=fake('{"a":"x"}'), now=NOW, agent="ceo_ai")
    assert blocked.status == "ABSTAIN" and "AGENT_QUOTA_REACHED" in blocked.reason
    ok = ai.ask("s", "q", SCHEMA, ledger=ledger, client_factory=fake('{"a":"x"}'), now=NOW, agent="model_council")
    assert ok.status == "OK" and ledger.spent(NOW.timestamp(), "model_council") == Decimal("0.007")


def test_quota_is_a_rolling_five_hour_window(tmp_path, monkeypatch):
    # Owner 2026-10-02: "5 saatlik" - spend older than 5 hours no longer counts.
    monkeypatch.setenv("ATLAS_AI_WINDOW_BUDGET_USD", "1.00")
    ledger = ai.UsageLedger(tmp_path / "u.json")
    ledger.add(NOW.timestamp() - 5 * 3600 - 1, Decimal("0.60"))   # just outside the window
    assert ledger.spent(NOW.timestamp()) == 0
    assert ai.ask("s", "q", SCHEMA, ledger=ledger, client_factory=fake('{"a":"x"}'), now=NOW).status == "OK"
    ledger.add(NOW.timestamp() - 4 * 3600, Decimal("0.60"))       # inside the window
    assert "WINDOW_BUDGET" in ai.ask("s", "q", SCHEMA, ledger=ledger, client_factory=fake('{"a":"x"}'), now=NOW).reason



# ---------------- Claude Code backend (owner choice 2026-10-02: use the Pro subscription)

def cc(out=None, exc=None, seen=None):
    def run(prompt, system, schema, model, effort):
        if seen is not None:
            seen.append((prompt, system, model, effort))
        if exc:
            raise exc
        return out
    return run


def test_claude_code_default_backend_returns_structured_output(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_AI_WINDOW_CALLS", "10")
    seen, ledger = [], ai.UsageLedger(tmp_path / "u.json")
    r = ai.ask("sys", "q api_key=sk-abc123456789abcdef", SCHEMA, ledger=ledger, now=NOW, agent="ceo_ai",
               runner=cc({"structured_output": {"a": "x"}, "total_cost_usd": 0.01, "is_error": False}, seen=seen))
    assert ai.BACKEND == "claude_code" and r.status == "OK" and r.data == {"a": "x"}
    assert "sk-abc123456789abcdef" not in seen[0][0]                 # SensitiveDataGuard before the CLI
    assert seen[0][2] == "claude-sonnet-5-5" and seen[0][3] == "high"  # owner: Sonnet, effort high
    assert ledger.calls(NOW.timestamp(), "ceo_ai") == 1


def test_claude_code_failures_abstain(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_AI_WINDOW_CALLS", "100")
    ledger = ai.UsageLedger(tmp_path / "u.json")
    for runner, reason in ((cc(exc=FileNotFoundError()), "UNAVAILABLE"), (cc({"is_error": True}), "CLAUDE_CODE_ERROR"),
                           (cc({"structured_output": {"b": 1}}), "MALFORMED"), (cc({"result": "text only"}), "MALFORMED")):
        r = ai.ask("s", "q", SCHEMA, ledger=ledger, now=NOW, agent="model_council", runner=runner)
        assert r.status == "ABSTAIN" and reason in r.reason


def test_claude_code_quota_is_calls_per_5h_60_percent_split_by_task_size(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_AI_WINDOW_CALLS", "10")   # 60 % -> 6 calls: ceo 2, council 4
    assert ai.agent_call_cap(None) == 6 and ai.agent_call_cap("ceo_ai") == 2 and ai.agent_call_cap("model_council") == 4
    assert ai.agent_call_cap("unknown") == 0
    ledger = ai.UsageLedger(tmp_path / "u.json")
    ok = cc({"structured_output": {"a": "x"}})
    assert [ai.ask("s", "q", SCHEMA, ledger=ledger, now=NOW, agent="ceo_ai", runner=ok).status for _ in range(3)] == ["OK", "OK", "ABSTAIN"]
    later = datetime.fromtimestamp(NOW.timestamp() + 5 * 3600 + 1, tz=timezone.utc)
    assert ai.ask("s", "q", SCHEMA, ledger=ledger, now=later, agent="ceo_ai", runner=ok).status == "OK"  # window rolled
    monkeypatch.setenv("ATLAS_AI_WINDOW_CALLS", "x")
    assert ai.window_calls() == 0


def test_claude_code_runner_drops_api_keys_and_disables_tools(monkeypatch):
    import subprocess
    captured = {}

    def fake_run(cmd, **kw):
        captured.update(cmd=cmd, **kw)
        return SimpleNamespace(returncode=0, stdout='{"structured_output": {"a": "x"}}')

    monkeypatch.setattr("shutil.which", lambda name: "claude")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "<anahtarın>")
    out = ai._claude_code_runner("prompt", "sys", SCHEMA, "claude-sonnet-5-5", "high")
    assert out == {"structured_output": {"a": "x"}}
    cmd = captured["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--effort") + 1] == "high" and "--json-schema" in cmd and "--bare" not in cmd
    assert "ANTHROPIC_API_KEY" not in captured["env"] and captured["input"] == "prompt"
