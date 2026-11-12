"""A corrupt risk-accounting state never admits new risk (registry v5.11).

Atlas starts with it (no restart loop, see v5.09) but every BUY is refused
as RISK_STATE_RESTORATION_FAILED and nothing is opened.
"""

from __future__ import annotations

import pytest

from core.application import RISK_ACCOUNTING_STATE_FILE, AtlasApplication
from tests.test_block5c_upstream_sizing_authority import execution_enabled_loop, seed_state


@pytest.mark.parametrize("corrupt", [
    lambda p: p.write_text(p.read_text(encoding="utf-8")[:-15], encoding="utf-8"),
    lambda p: p.write_text("", encoding="utf-8"),
    lambda p: p.unlink(),
], ids=["truncated", "empty", "deleted"])
def test_buy_is_refused_and_nothing_opens(tmp_path, corrupt):
    root = seed_state(tmp_path / "state")
    corrupt(root / RISK_ACCOUNTING_STATE_FILE)

    app = AtlasApplication(state_directory=root)
    app.execution.start()
    try:
        result = execution_enabled_loop(app, "BUY").process_symbol("BTCUSDT")

        assert result["status"] == "REJECTED"
        reason = result.get("reason") or (result.get("data") or {}).get("reason")
        assert reason == "RISK_STATE_RESTORATION_FAILED"
        assert app.execution.last_risk_decision is None or \
            app.execution.last_risk_decision.get("reason_code") != "RISK_APPROVED"
        assert app.portfolio_foundation.snapshot()["positions"] == {}
        assert app.execution._risk_admissions == {}
    finally:
        app.stop()
