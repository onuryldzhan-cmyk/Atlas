"""Task 8: model registry contract - no active model, no model may be a trading decision."""

import json
from pathlib import Path

REG = json.loads((Path(__file__).resolve().parents[1] / "config" / "model_registry.json").read_text(encoding="utf-8"))


def test_no_model_active_and_no_trading_authority():
    assert REG["active_models"] == []
    assert REG["routing_policy"]["trading_decision"].startswith("NONE")
    assert REG["output_pipeline"][-1] == "canonical_adapter" and "authority_validation" in REG["output_pipeline"]
    assert "ABSTAIN" in REG["failure_rule"]


def test_any_future_model_entry_must_be_complete():
    for m in REG["active_models"]:
        assert all(m.get(f) for f in REG["required_fields"]), m
