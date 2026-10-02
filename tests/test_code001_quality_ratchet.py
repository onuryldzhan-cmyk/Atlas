"""CODE-001 baseline ratchet (registry v5.26): runtime code quality may only improve.

Numbers were measured on 2026-09-28 over the runtime closure. A change that
lowers one should lower the pinned ceiling in the same commit (tighten the
ratchet); raising a ceiling needs a successor registry record.
"""

from tools.code_health_report import measure

PRINT_CALLS_CEILING = 36  # v5.50: AI-module diagnostics moved to logging (was 128)
# 2026-10-02 T-0001/T-0002/T-0003: agent_fusion.fuse, scheduler._execute_task, execution_manager._execute_paper_buy split
# (behaviour pinned by golden/characterization tests), removed from the baseline.
# 2026-10-02 T-0013 (owner chose "B"): execution_manager._execute_decision (1237 lines) split into _decision_*
# phases, behaviour pinned by tests/test_execute_decision_golden.py (37 scenarios), removed from the baseline.
LONG_FUNCTIONS_BASELINE = {
    "core/execution_manager.py::risk_check",
    "core/market_loop.py::process_symbol",
    "web_app.py::create_app",
}

REPORT = measure()


def test_no_bare_except_in_runtime():
    assert REPORT["bare_except"] == []


def test_no_todo_or_fixme_in_runtime():
    assert REPORT["todo_fixme"] == []


def test_print_calls_never_increase():
    assert REPORT["print_calls"] <= PRINT_CALLS_CEILING


def test_no_new_overlong_functions():
    new = set(REPORT["long_functions"]) - LONG_FUNCTIONS_BASELINE
    assert not new, f"new function over 300 lines: {sorted(new)}"

