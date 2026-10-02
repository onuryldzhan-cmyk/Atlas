"""Task 8: model registry contract - no active model, no model may be a trading decision."""

import json
from pathlib import Path

REG = json.loads((Path(__file__).resolve().parents[1] / "config" / "model_registry.json").read_text(encoding="utf-8"))


# Test policy change 2026-10-02: the owner chose the Claude API for AI-001, so two ADVISORY
# models are registered. What must never change is pinned below: no trading authority.
def test_models_are_advisory_only_and_have_no_trading_authority():
    assert {m["model_id"] for m in REG["active_models"]} <= {"claude-opus-5-5", "claude-sonnet-5-5"}
    assert all(m["status"].startswith("ADVISORY_ONLY") for m in REG["active_models"])
    assert all("trad" not in t for m in REG["active_models"] for t in m["supported_tasks"])
    assert REG["routing_policy"]["trading_decision"].startswith("NONE")
    assert REG["output_pipeline"][-1] == "canonical_adapter" and "authority_validation" in REG["output_pipeline"]
    assert "ABSTAIN" in REG["failure_rule"]


def test_any_future_model_entry_must_be_complete():
    for m in REG["active_models"]:
        assert all(m.get(f) for f in REG["required_fields"]), m
