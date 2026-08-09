from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "data_layer" / "runtime_integration_inventory.json"


def test_runtime_integration_inventory_is_complete_and_fail_closed() -> None:
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    allowed = set(payload["classifications"])
    authorities = payload["authorities"]
    assert payload["migration_result"] == "SEMANTIC_CONTRACTS_STILL_BLOCKED"
    assert payload["migrate_now"] == []
    assert payload["dual_write_enabled"] is False
    assert payload["automatic_legacy_migration"] is False
    assert len(authorities) >= 18
    assert all(item["classification"] in allowed for item in authorities)
    assert all(item["reason"].strip() for item in authorities)
    assert payload["external_side_effect_contract"]["external_atomicity"] is False
    assert set(payload["authority_matrix"]) >= {"orders", "executions", "positions", "portfolio", "capital", "risk", "journal", "idempotency", "audit", "paper_state", "trade_memory", "strategy_state", "learning_state", "market_data"}


def test_specialized_execution_stores_remain_classified_and_imported() -> None:
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    specialized = {item["path"] for item in payload["authorities"] if item["classification"] == "KEEP_SPECIALIZED"}
    assert {"core/execution_transaction_journal.py", "core/execution_idempotency_store.py", "core/audit_event_store.py"} <= specialized
    source = (ROOT / "core" / "execution_manager.py").read_text(encoding="utf-8")
    imported = {node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom) and node.module}
    assert "core.execution_transaction_journal" in imported
    assert "core.execution_idempotency_store" in imported
    assert "core.audit_event_store" in imported


def test_deferred_callers_do_not_import_sqlite_backend() -> None:
    for relative in ("core/execution_manager.py", "core/position_controller.py", "portfolio/capital_manager.py", "core/risk_engine.py", "core/trade_memory.py", "core/paper_trader.py", "core/learning_engine.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        assert "sqlite3" not in names
        assert "data_layer.sqlite" not in modules
