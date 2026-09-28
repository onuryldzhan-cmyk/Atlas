"""A corrupt durable execution store never admits new risk (Phase 2-3 item 1).

Probed 2026-09-28 (registry v5.09): Atlas starts with a corrupt store (no
restart loop) but refuses every new BUY. The append logs and the financial
state halt execution (RECOVERY_REQUIRED); a corrupt reservation store
refuses admission (CAPITAL_RESERVATION_STATE_NOT_READY).
"""

from __future__ import annotations

import pytest

from core.application import (
    CAPITAL_RESERVATION_STATE_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    EXECUTION_IDEMPOTENCY_STATE_FILE,
    EXECUTION_TRANSACTION_JOURNAL_FILE,
    AtlasApplication,
)
from tests.test_block5c_upstream_sizing_authority import execution_enabled_loop, seed_state


def _garble(path):
    text = path.read_text(encoding="utf-8")
    path.write_text(text[:-20] + "garbage}\n", encoding="utf-8")


@pytest.mark.parametrize("store, expected_status, halts", [
    (EXECUTION_IDEMPOTENCY_STATE_FILE, "RECOVERY_REQUIRED", True),
    (EXECUTION_TRANSACTION_JOURNAL_FILE, "RECOVERY_REQUIRED", True),
    (EXECUTION_FINANCIAL_STATE_FILE, "RECOVERY_REQUIRED", True),
    (CAPITAL_RESERVATION_STATE_FILE, "REJECTED", False),
])
def test_new_risk_is_refused_after_the_store_is_corrupted(tmp_path, store, expected_status, halts):
    root = seed_state(tmp_path / "state")

    first = AtlasApplication(state_directory=root)
    first.execution.start()
    assert execution_enabled_loop(first, "BUY").process_symbol("BTCUSDT")["status"] == "PAPER_EXECUTED"
    first.stop()

    _garble(root / store)

    app = AtlasApplication(state_directory=root)  # starts: no restart loop
    app.execution.start()
    try:
        result = execution_enabled_loop(app, "BUY", epoch=5).process_symbol("BTCUSDT")

        assert result["status"] == expected_status
        assert app.execution.execution_halted is halts
        assert app.execution._risk_admissions == {}
    finally:
        app.stop()
