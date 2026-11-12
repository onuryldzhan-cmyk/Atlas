"""MEGA TASK 1 §1 / MEGA TASK 3 §16: only one execution authority in the runtime.

Legacy modules that can place or project trades directly (bypassing the
canonical ExecutionManager -> RiskEngine chain) must never enter the runtime
closure, and inside the closure only core/execution_manager.py may call the
PaperTrader's mutating projection methods.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOSURE = json.loads((ROOT / "packaging" / "atlas_runtime_closure.json").read_text(encoding="utf-8"))["modules"]
LEGACY_DIRECT_EXECUTION = {
    "core/execution_bridge.py",            # ExecutionBridge -> paper_trader.open_trade
    "intelligence/trading/paper_bridge.py",
    "portfolio/portfolio_manager.py",
}
PAPER_MUTATORS = {"open_trade", "close_trade", "apply_projection", "reproject_all"}


def test_no_legacy_direct_execution_module_in_runtime():
    assert not LEGACY_DIRECT_EXECUTION & set(CLOSURE)


def test_only_execution_manager_mutates_the_paper_trader():
    offenders = []
    for rel in CLOSURE:
        if rel in ("core/execution_manager.py", "core/paper_trader.py"):
            continue
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in PAPER_MUTATORS \
                    and isinstance(node.value, ast.Attribute) and "paper" in node.value.attr:
                offenders.append(f"{rel}:{node.lineno} {node.value.attr}.{node.attr}")
    assert offenders == [], offenders


def test_closure_is_not_empty():
    assert "core/execution_manager.py" in CLOSURE and "core/risk_engine.py" in CLOSURE
