"""A corrupt or missing durable execution store never admits new risk.

Phase 2-3 item 1; audit MEDIUM-1/2 widened the corruption modes. Probed
2026-09-28: Atlas starts with a damaged store (no restart loop) and refuses
new risk - except the one known gap below.

KNOWN GAP (HIGH, owner decision pending): an *empty or deleted*
transaction journal is accepted as a fresh journal and trading continues.
Pinned as a strict xfail so the day it is fixed this test says so.
"""

from __future__ import annotations

import pytest

from core.application import (
    CAPITAL_RESERVATION_STATE_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    EXECUTION_IDEMPOTENCY_STATE_FILE,
    EXECUTION_TRANSACTION_JOURNAL_FILE,
    RISK_ACCOUNTING_STATE_FILE,
    AtlasApplication,
)
from tests.test_block5c_upstream_sizing_authority import execution_enabled_loop, seed_state

MODES = {
    "garbled": lambda p: p.write_text(p.read_text(encoding="utf-8")[:-20] + "garbage}\n", encoding="utf-8"),
    "truncated": lambda p: p.write_text(p.read_text(encoding="utf-8")[: len(p.read_text(encoding="utf-8")) // 2], encoding="utf-8"),
    "empty": lambda p: p.write_text("", encoding="utf-8"),
    "deleted": lambda p: p.unlink(),
}

STORES = [
    EXECUTION_IDEMPOTENCY_STATE_FILE,
    EXECUTION_TRANSACTION_JOURNAL_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    CAPITAL_RESERVATION_STATE_FILE,
    RISK_ACCOUNTING_STATE_FILE,
]

JOURNAL_GAP = pytest.mark.xfail(
    strict=True,
    reason="HIGH: an empty/deleted transaction journal is accepted as fresh "
           "(Phase 2-3 proposal item 1, owner decision pending)",
)


def _cases():
    for store in STORES:
        for mode in MODES:
            marks = [JOURNAL_GAP] if (
                store == EXECUTION_TRANSACTION_JOURNAL_FILE and mode in {"empty", "deleted"}
            ) else []
            yield pytest.param(store, mode, marks=marks, id=f"{store}-{mode}")


@pytest.mark.parametrize("store, mode", list(_cases()))
def test_new_risk_on_another_symbol_is_refused(tmp_path, store, mode):
    root = seed_state(tmp_path / "state")

    first = AtlasApplication(state_directory=root)
    first.execution.start()
    assert execution_enabled_loop(first, "BUY").process_symbol("BTCUSDT")["status"] == "PAPER_EXECUTED"
    first.stop()

    MODES[mode](root / store)

    try:
        app = AtlasApplication(state_directory=root)
    except RuntimeError:
        return  # refusing to start is fail-closed too

    app.execution.start()
    try:
        loop = execution_enabled_loop(app, "BUY", epoch=5)
        loop.symbols = ["ETHUSDT"]  # a symbol with no open position
        result = loop.process_symbol("ETHUSDT")

        assert result["status"] != "PAPER_EXECUTED"
        assert app.execution._risk_admissions == {}
    finally:
        app.stop()
