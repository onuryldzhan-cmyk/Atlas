"""Block 5I: durable financial-state sidecars.

``ExecutionPortfolioFoundation``'s working file (``execution_financial_state.json``)
held ``closed_positions`` and ``applied_executions`` inline (schema_version 1):
both grew by one entry for the runtime's entire lifetime, with the working
file rewritten in full on every single mutation regardless of which
collection actually changed. This package (schema_version 2) moves both out
into immutable, append-only JSON-Lines sidecars -
``AppliedExecutionArchiveStore`` (``execution_applied_executions.jsonl``) and
``ClosedPositionArchiveStore`` (``execution_closed_positions.jsonl``) - and
adds two small checkpoints (``applied_checkpoint`` / ``closed_checkpoint``)
to the working file that must agree exactly with each sidecar's durable tail
at every load. There is no runtime auto-migration from schema_version 1 -
``tools/migrate_execution_financial_state.py`` is the only supported path.

Every fixture writes into pytest's tmp_path. Nothing here may touch the
operator's real runtime state.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.execution_models import ExecutionResult
from core.execution_portfolio_foundation import (
    SCHEMA_VERSION,
    AppliedExecutionArchiveConflictError,
    AppliedExecutionArchiveCorruptError,
    AppliedExecutionArchiveStore,
    AppliedExecutionRecord,
    ClosedPositionArchiveConflictError,
    ClosedPositionArchiveCorruptError,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
    mint_long_position_id,
)
from core.financial_state_bootstrap import BootstrapOutcome, bootstrap_financial_state

import tools.migrate_execution_financial_state as migration_module

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MIGRATE_CLI_PATH = REPOSITORY_ROOT / "tools" / "migrate_execution_financial_state.py"


# --------------------------------------------------------------------------
# shared fixtures / helpers - real production classes, tmp_path state only
# --------------------------------------------------------------------------


def _foundation(tmp_path, *, name: str = "financial", cash: str = "1000"):
    store = FinancialStateStore(tmp_path / f"{name}.json")
    store.initialize(D(cash))
    applied_archive = AppliedExecutionArchiveStore(tmp_path / f"{name}-applied.jsonl")
    closed_archive = ClosedPositionArchiveStore(tmp_path / f"{name}-closed.jsonl")
    foundation = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    return foundation, store, applied_archive, closed_archive


def _fill(action, *, base, price, execution_id, position_id, fee="0", fee_ccy="USDT",
          idempotency_key=None, symbol="BTCUSDT") -> ExecutionResult:
    return ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id=execution_id,
        position_id=position_id, symbol=symbol, action=action,
        filled_price=price, filled_base_quantity=D(str(base)),
        filled_quote_notional=D(str(price)) * D(str(base)),
        fee_amount=D(str(fee)), fee_currency=fee_ccy,
        idempotency_key=idempotency_key or execution_id, provenance_ref="test",
    )


def _closed_record(position_id, *, symbol="BTCUSDT", cost_quote="100", entry_fees="0",
                    average_entry_price="10", mark_price="10", exit_price="11",
                    gross_pnl="10", version=2, opened_at=None, closed_at=None) -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "position_id": position_id, "symbol": symbol, "base_quantity": "0",
        "cost_quote": cost_quote, "entry_fees": entry_fees,
        "average_entry_price": average_entry_price, "mark_price": mark_price,
        "version": version, "opened_at": opened_at or now, "status": "CLOSED",
        "exit_price": exit_price, "gross_pnl": gross_pnl, "closed_at": closed_at or now,
    }


def _write_v1_file(path: Path, *, cash="1000", reserved_capital="0", realized_gross_pnl="0",
                    fees="0", transition=None, positions=None, closed_positions=None,
                    applied_executions=None) -> None:
    payload = {
        "schema_version": 1, "transition": transition,
        "cash": cash, "reserved_capital": reserved_capital,
        "realized_gross_pnl": realized_gross_pnl, "fees": fees,
        "positions": positions or {}, "closed_positions": closed_positions or {},
        "applied_executions": applied_executions or {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _clear_transition(store: FinancialStateStore) -> None:
    """Simulate an operator manually clearing a stuck transition marker
    without reconciling anything else - the exact gap checkpoint validation
    closes."""
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["transition"] = None
    store.save(payload)


def run_migrate_cli(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MIGRATE_CLI_PATH), *arguments],
        capture_output=True, text=True, cwd=str(REPOSITORY_ROOT),
    )


# ===========================================================================
# A - repeated full-close lifetimes: N closes -> N immutable closed records
# ===========================================================================


def test_a_repeated_full_close_lifetimes_produce_n_immutable_closed_records(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    ids = [mint_long_position_id("BTCUSDT", f"r{i}") for i in range(5)]
    for i, position_id in enumerate(ids):
        foundation.apply_confirmed(
            _fill("BUY", base="1", price="10", execution_id=f"buy-{i}", position_id=position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
        )
        foundation.apply_confirmed(
            _fill("SELL", base="1", price="11", execution_id=f"sell-{i}", position_id=position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
        )
    index = closed_archive.load_index()
    assert index.count == 5
    assert set(index.by_position_id) == set(ids)
    assert index.tail_sequence == 4
    # Each is its own immutable line - no overwrite, all 5 gross_pnl figures distinct-from-zero.
    for position_id in ids:
        assert D(index.by_position_id[position_id]["gross_pnl"]) == D("1")


# ===========================================================================
# B - partial SELL: no closed archive record
# ===========================================================================


def test_b_partial_sell_never_archives_a_closed_record(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    foundation.apply_confirmed(
        _fill("SELL", base="4", price="11", execution_id="e2", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )
    assert closed_archive.load_index().count == 0
    assert applied_archive.load_index().count == 2


# ===========================================================================
# C - add-to-position: same lifetime id, no premature archive
# ===========================================================================


def test_c_add_to_position_keeps_one_lifetime_id_and_archives_nothing(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    snap = foundation.apply_confirmed(
        _fill("BUY", base="5", price="11", execution_id="e2", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )
    assert snap["positions"]["BTCUSDT"]["position_id"] == position_id
    assert snap["positions"]["BTCUSDT"]["version"] == 2
    assert closed_archive.load_index().count == 0
    assert applied_archive.load_index().count == 2


# ===========================================================================
# D - financial totals: identical to the pre-sidecar arithmetic
# ===========================================================================


def test_d_financial_totals_match_pre_sidecar_arithmetic_exactly(tmp_path):
    """No line inside ``_open``/``_close`` changed - only where the closed
    record and applied identity live. cash/fees/realized_gross_pnl/live
    positions for this exact sequence are pinned to the same figures
    ``tests/test_phase4_execution_position_portfolio_foundation.py`` proves
    for the pre-5I shape."""
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    snap = foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", fee="1", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    assert snap["cash"] == D("899")
    assert snap["committed_capital"] == D("100")
    assert snap["fees"] == D("1")
    assert snap["equity"] == D("999")

    partial = foundation.apply_confirmed(
        _fill("SELL", base="5", price="11", execution_id="e2", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )
    assert partial["realized_gross_pnl"] == D("5")
    assert partial["cash"] == D("954")
    assert closed_archive.load_index().count == 0

    full = foundation.apply_confirmed(
        _fill("SELL", base="5", price="12", execution_id="e3", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=2,
    )
    assert full["positions"] == {}
    assert full["realized_gross_pnl"] == D("15")
    assert full["cash"] == D("1000") + D("15") - D("1")
    closed = closed_archive.load_index().by_position_id[position_id]
    assert D(closed["gross_pnl"]) == D("10")  # 60 - 50 on the second half


# ===========================================================================
# E - applied replay: same execution_id + same request_id -> replayed, no mutation
# ===========================================================================


def test_e_replay_same_execution_and_idempotency_key_is_idempotent(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    fill = _fill("BUY", base="10", price="10", fee="1", execution_id="e1", position_id=position_id)
    first = foundation.apply_confirmed(fill, risk_authorized=True, reservation_confirmed=True,
                                        expected_position_version=None)
    second = foundation.apply_confirmed(fill, risk_authorized=True, reservation_confirmed=True,
                                         expected_position_version=None)
    assert first["replayed"] is False and second["replayed"] is True
    assert first["cash"] == second["cash"]
    assert applied_archive.load_index().count == 1  # no second append


# ===========================================================================
# F - identity conflict: same execution_id + different request_id -> fail closed
# ===========================================================================


def test_f_same_execution_id_different_idempotency_key_is_identity_conflict(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id, idempotency_key="k1"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    with pytest.raises(ValueError, match="EXECUTION_IDENTITY_CONFLICT"):
        foundation.apply_confirmed(
            _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id, idempotency_key="k2"),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
        )
    assert applied_archive.load_index().count == 1  # rejected before any append


# ===========================================================================
# G - idempotency conflict: new execution_id + already-applied request_id -> fail closed
# ===========================================================================


def test_g_new_execution_id_reusing_idempotency_key_is_idempotency_conflict(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id, idempotency_key="shared"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    with pytest.raises(ValueError, match="IDEMPOTENCY_IDENTITY_CONFLICT"):
        foundation.apply_confirmed(
            _fill("BUY", base="1", price="10", execution_id="e2", position_id=position_id, idempotency_key="shared"),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
        )
    assert applied_archive.load_index().count == 1


# ===========================================================================
# H - restart: both indexes rebuild and all replay behavior survives
# ===========================================================================


def test_h_restart_rebuilds_both_indexes_and_preserves_replay_behavior(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    open_fill = _fill("BUY", base="10", price="10", fee="1", execution_id="e1", position_id=position_id)
    foundation.apply_confirmed(open_fill, risk_authorized=True, reservation_confirmed=True,
                                expected_position_version=None)
    foundation.apply_confirmed(
        _fill("SELL", base="10", price="12", execution_id="e2", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )

    restarted = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert restarted.ready is True
    # Replay of the BUY (its execution_id/idempotency_key) still short-circuits.
    replay = restarted.apply_confirmed(open_fill, risk_authorized=True, reservation_confirmed=True,
                                        expected_position_version=None)
    assert replay["replayed"] is True
    with pytest.raises(ValueError, match="IDEMPOTENCY_IDENTITY_CONFLICT"):
        restarted.apply_confirmed(
            _fill("BUY", base="1", price="10", execution_id="e3", position_id=position_id,
                  idempotency_key=open_fill.idempotency_key),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
        )


# ===========================================================================
# I/J/K/L - crash ordering: marker -> closed append -> applied append -> commit
# ===========================================================================


def test_i_crash_before_closed_archive_append_orphans_nothing(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )

    def fail(): raise RuntimeError("simulated crash before closed archive append")
    with pytest.raises(RuntimeError, match="simulated crash"):
        foundation.apply_confirmed(
            _fill("SELL", base="10", price="12", execution_id="e2", position_id=position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
            before_closed_archive_append=fail,
        )
    assert foundation.ready is False
    assert closed_archive.load_index().count == 0
    assert applied_archive.load_index().count == 1  # only the BUY

    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"] == "FINANCIAL_TRANSITION_RECOVERY_REQUIRED"


def test_j_crash_after_closed_append_before_applied_append_orphans_closed_only(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )

    def fail(): raise RuntimeError("simulated crash after closed archive append")
    with pytest.raises(RuntimeError, match="simulated crash"):
        foundation.apply_confirmed(
            _fill("SELL", base="10", price="12", execution_id="e2", position_id=position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
            before_applied_archive_append=fail,
        )
    assert foundation.ready is False
    assert closed_archive.load_index().count == 1  # durably orphaned
    assert applied_archive.load_index().count == 1  # never reached

    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"] == "FINANCIAL_TRANSITION_RECOVERY_REQUIRED"


def test_k_crash_after_applied_append_before_working_commit_orphans_both(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )

    def fail(): raise RuntimeError("simulated crash before final persist")
    with pytest.raises(RuntimeError, match="simulated crash"):
        foundation.apply_confirmed(
            _fill("SELL", base="10", price="12", execution_id="e2", position_id=position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
            before_final_persist=fail,
        )
    assert foundation.ready is False
    assert closed_archive.load_index().count == 1
    assert applied_archive.load_index().count == 2  # BUY's + this SELL's orphan

    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"] == "FINANCIAL_TRANSITION_RECOVERY_REQUIRED"


class _FailOnFinalSaveStore(FinancialStateStore):
    """A store whose transition-marker save succeeds normally but whose
    final commit save (``transition is None`` in the payload) fails - an
    I/O failure during the write itself, distinct from K's test-hook crash
    injected just before the call."""
    def save(self, payload):
        if payload.get("transition") is None:
            raise OSError("simulated disk failure during final working-state save")
        super().save(payload)


def test_l_crash_during_final_working_state_save_leaves_committed_data_unperturbed(tmp_path):
    path = tmp_path / "financial.json"
    store = FinancialStateStore(path)
    store.initialize(D("1000"))
    applied_archive = AppliedExecutionArchiveStore(tmp_path / "financial-applied.jsonl")
    closed_archive = ClosedPositionArchiveStore(tmp_path / "financial-closed.jsonl")
    foundation = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    before_bytes = path.read_bytes()

    foundation.store = _FailOnFinalSaveStore(path)
    with pytest.raises(OSError, match="simulated disk failure"):
        foundation.apply_confirmed(
            _fill("SELL", base="10", price="12", execution_id="e2", position_id=position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
        )
    assert foundation.ready is False
    # The transition-marker write DID land (that save succeeds in this
    # fake), so the file is not byte-identical to `before_bytes` - but the
    # prior committed financial state inside it is unperturbed, and both
    # sidecars already hold their now-orphaned records durably.
    assert closed_archive.load_index().count == 1
    assert applied_archive.load_index().count == 2
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["transition"] is not None
    assert on_disk["cash"] == json.loads(before_bytes)["cash"]


# ===========================================================================
# M/N - orphan sidecar record + manually cleared marker -> checkpoint divergence
# ===========================================================================


def test_m_orphan_applied_record_with_cleared_marker_fails_closed_divergent(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )

    def fail(): raise RuntimeError("simulated crash before final persist")
    with pytest.raises(RuntimeError, match="simulated crash"):
        foundation.apply_confirmed(
            _fill("BUY", base="1", price="10", execution_id="e2", position_id=position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
            before_final_persist=fail,
        )
    assert applied_archive.load_index().count == 2  # e2's applied record durably orphaned
    assert closed_archive.load_index().count == 0

    _clear_transition(store)  # operator "fixes" the marker without reconciling the checkpoint

    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"] == "FINANCIAL_APPLIED_AUTHORITY_DIVERGENT"


def test_n_orphan_closed_record_with_cleared_marker_fails_closed_divergent(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )

    # Crash between the closed append and the applied append: the closed
    # archive durably gains an orphan, but applied_checkpoint stays exactly
    # in sync with the (untouched) applied archive - isolating this test to
    # the closed-authority divergence path specifically.
    def fail(): raise RuntimeError("simulated crash after closed archive append")
    with pytest.raises(RuntimeError, match="simulated crash"):
        foundation.apply_confirmed(
            _fill("SELL", base="10", price="12", execution_id="e2", position_id=position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
            before_applied_archive_append=fail,
        )
    assert closed_archive.load_index().count == 1
    assert applied_archive.load_index().count == 1

    _clear_transition(store)

    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"] == "FINANCIAL_CLOSED_AUTHORITY_DIVERGENT"


# ===========================================================================
# O/P - torn/malformed archive -> fail closed
# ===========================================================================


def test_o_torn_applied_archive_fails_closed(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    with applied_archive.path.open("a", encoding="utf-8") as stream:
        stream.write("{not valid json\n")

    with pytest.raises(AppliedExecutionArchiveCorruptError, match="FINANCIAL_APPLIED_AUTHORITY_CORRUPT"):
        applied_archive.load_index()

    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"].startswith("FINANCIAL_APPLIED_AUTHORITY_CORRUPT")


def test_p_torn_closed_archive_fails_closed(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    foundation.apply_confirmed(
        _fill("SELL", base="10", price="12", execution_id="e2", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )
    with closed_archive.path.open("a", encoding="utf-8") as stream:
        stream.write("{not valid json\n")

    with pytest.raises(ClosedPositionArchiveCorruptError, match="FINANCIAL_CLOSED_AUTHORITY_CORRUPT"):
        closed_archive.load_index()

    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"].startswith("FINANCIAL_CLOSED_AUTHORITY_CORRUPT")


# ===========================================================================
# Q/R - conflicting duplicate line -> fail closed
# ===========================================================================


def test_q_conflicting_applied_duplicate_same_execution_id_fails_closed(tmp_path):
    archive = AppliedExecutionArchiveStore(tmp_path / "applied.jsonl")
    now = datetime.now(UTC).isoformat()
    archive.append(AppliedExecutionRecord(0, "e1", "k1", now))
    archive.append(AppliedExecutionRecord(1, "e1", "k2", now))
    with pytest.raises(AppliedExecutionArchiveConflictError, match="APPLIED_EXECUTION_CONFLICT"):
        archive.load_index()


def test_r_conflicting_closed_duplicate_same_position_id_fails_closed(tmp_path):
    archive = ClosedPositionArchiveStore(tmp_path / "closed.jsonl")
    archive.append(0, _closed_record("p1", gross_pnl="10"))
    archive.append(1, _closed_record("p1", gross_pnl="-5"))
    with pytest.raises(ClosedPositionArchiveConflictError, match="CLOSED_POSITION_ARCHIVE_CONFLICT"):
        archive.load_index()


# ===========================================================================
# S - same request_id under two execution_ids detected at index build
# ===========================================================================


def test_s_same_idempotency_key_under_two_execution_ids_fails_closed(tmp_path):
    archive = AppliedExecutionArchiveStore(tmp_path / "applied.jsonl")
    now = datetime.now(UTC).isoformat()
    archive.append(AppliedExecutionRecord(0, "e1", "shared", now))
    archive.append(AppliedExecutionRecord(1, "e2", "shared", now))
    with pytest.raises(AppliedExecutionArchiveConflictError, match="IDEMPOTENCY_IDENTITY_CONFLICT"):
        archive.load_index()


# ===========================================================================
# T - live position id also found in closed archive -> fail closed
# ===========================================================================


def test_t_live_position_id_also_in_closed_archive_fails_closed(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    # Tamper: archive a closed record for the still-live position_id, and
    # advance the checkpoint to match it exactly - isolating this test to
    # the live/closed overlap check, not a checkpoint mismatch.
    closed_archive.append(0, _closed_record(position_id))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["closed_checkpoint"] = {"sequence": 0, "position_id": position_id}
    store.save(payload)

    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"] == "FINANCIAL_CLOSED_POSITION_LIVE_CONFLICT"


# ===========================================================================
# AB/AC - checkpoint proves history must exist, but the sidecar is missing
# ===========================================================================


def test_ab_missing_applied_archive_while_checkpoint_exists_fails_closed(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    applied_archive.path.unlink()

    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"] == "FINANCIAL_APPLIED_AUTHORITY_MISSING"


def test_ac_missing_closed_archive_while_checkpoint_proves_history_fails_closed(tmp_path):
    foundation, store, applied_archive, closed_archive = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    foundation.apply_confirmed(
        _fill("SELL", base="10", price="12", execution_id="e2", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )
    closed_archive.path.unlink()

    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"] == "FINANCIAL_CLOSED_AUTHORITY_MISSING"


# ===========================================================================
# U - v1 runtime load -> FINANCIAL_MIGRATION_REQUIRED
# ===========================================================================


def test_u_v1_schema_load_raises_financial_migration_required(tmp_path):
    path = tmp_path / "financial.json"
    _write_v1_file(path)
    store = FinancialStateStore(path)
    with pytest.raises(ValueError, match="FINANCIAL_MIGRATION_REQUIRED"):
        store.load()

    applied_archive = AppliedExecutionArchiveStore(tmp_path / "applied.jsonl")
    closed_archive = ClosedPositionArchiveStore(tmp_path / "closed.jsonl")
    foundation = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert foundation.ready is False
    assert foundation.diagnostics()["reason"] == "FINANCIAL_MIGRATION_REQUIRED"


def test_u2_bootstrap_reports_financial_migration_required_for_v1_state(tmp_path):
    _write_v1_file(tmp_path / "execution_financial_state.json")
    result = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=D("10000"),
        allocatable_capital=D("8000"), policy_version="v1",
    )
    financial = result.result_for("execution_financial_state")
    assert financial.outcome is BootstrapOutcome.INVALID_EXISTING
    assert financial.reason_code == "FINANCIAL_MIGRATION_REQUIRED"


# ===========================================================================
# V - migration exactness
# ===========================================================================


def test_v_migration_preserves_financial_totals_closed_history_and_applied_mappings(tmp_path):
    now = datetime.now(UTC).isoformat()
    v1_positions = {"BTCUSDT": {
        "position_id": mint_long_position_id("BTCUSDT", "live-1"), "symbol": "BTCUSDT",
        "base_quantity": "3", "cost_quote": "30", "entry_fees": "0",
        "average_entry_price": "10", "mark_price": "10", "version": 1, "opened_at": now,
    }}
    closed_a = _closed_record(mint_long_position_id("ETHUSDT", "e-a"), symbol="ETHUSDT", gross_pnl="12")
    closed_b = _closed_record(mint_long_position_id("ETHUSDT", "e-b"), symbol="ETHUSDT", gross_pnl="-3")
    v1_closed = {closed_a["position_id"]: closed_a, closed_b["position_id"]: closed_b}
    v1_applied = {"exec-a": "key-a", "exec-b": "key-b", "exec-c": "key-c"}

    path = tmp_path / "execution_financial_state.json"
    _write_v1_file(
        path, cash="500", reserved_capital="0", realized_gross_pnl="9", fees="1",
        positions=v1_positions, closed_positions=v1_closed, applied_executions=v1_applied,
    )

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.MIGRATED
    assert result.applied_count == 3 and result.closed_count == 2
    assert result.applied_appended == 3 and result.closed_appended == 2

    working = json.loads(path.read_text(encoding="utf-8"))
    assert working["schema_version"] == SCHEMA_VERSION
    assert working["transition"] is None
    assert working["cash"] == "500" and working["fees"] == "1" and working["realized_gross_pnl"] == "9"
    assert working["positions"] == v1_positions
    assert working["applied_checkpoint"] == {"sequence": 2, "execution_id": "exec-c", "idempotency_key": "key-c"}
    # closed_a/closed_b's position_ids are SHA-256 digests (Block 5G) - their
    # relative sort order is not predictable from the input strings, so the
    # expected tail is whichever one actually sorts last, computed here
    # exactly the way the migration tool itself sorts (by position_id key).
    last_closed_id = sorted(v1_closed)[-1]
    assert working["closed_checkpoint"] == {"sequence": 1, "position_id": last_closed_id}

    applied_archive = AppliedExecutionArchiveStore(tmp_path / "execution_applied_executions.jsonl")
    closed_archive = ClosedPositionArchiveStore(tmp_path / "execution_closed_positions.jsonl")
    foundation = ExecutionPortfolioFoundation(
        FinancialStateStore(path), applied_archive=applied_archive, closed_archive=closed_archive,
    )
    assert foundation.ready is True
    snap = foundation.snapshot()
    assert snap["cash"] == D("500") and snap["fees"] == D("1") and snap["realized_gross_pnl"] == D("9")
    assert snap["positions"] == v1_positions
    assert foundation._closed_by_position_id == v1_closed
    assert {eid: rec.idempotency_key for eid, rec in foundation._applied_by_execution_id.items()} == v1_applied

    # A migrated applied identity still replays cleanly through the real path.
    replay_fill = ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id="exec-a", position_id="whatever",
        symbol="BTCUSDT", action="BUY", filled_price="1", filled_base_quantity=D("1"),
        filled_quote_notional=D("1"), fee_amount=D("0"), fee_currency="USDT",
        idempotency_key="key-a", provenance_ref="test",
    )
    replayed = foundation.apply_confirmed(replay_fill, risk_authorized=True, reservation_confirmed=True)
    assert replayed["replayed"] is True


# ===========================================================================
# W - migration refuses transition != null
# ===========================================================================


def test_w_migration_refuses_pending_transition(tmp_path):
    path = tmp_path / "execution_financial_state.json"
    _write_v1_file(path, transition={"stage": "interrupted"})
    before = path.read_bytes()

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.SOURCE_INVALID
    assert result.reason_code == "SOURCE_TRANSITION_PENDING"
    assert path.read_bytes() == before
    assert not (tmp_path / "execution_applied_executions.jsonl").exists()
    assert not (tmp_path / "execution_closed_positions.jsonl").exists()


# ===========================================================================
# X - interrupted migration resumes safely
# ===========================================================================


def test_x_interrupted_migration_resumes_safely(tmp_path):
    path = tmp_path / "execution_financial_state.json"
    closed_a = _closed_record(mint_long_position_id("BTCUSDT", "e-a"), gross_pnl="1")
    closed_b = _closed_record(mint_long_position_id("BTCUSDT", "e-b"), gross_pnl="2")
    _write_v1_file(
        path, closed_positions={closed_a["position_id"]: closed_a, closed_b["position_id"]: closed_b},
        applied_executions={"exec-a": "key-a", "exec-b": "key-b"},
    )

    # Simulate a resume where the applied sidecar already durably holds
    # every record this source would produce, but the closed sidecar holds
    # none yet - independent of which sidecar the tool itself appends
    # first (closed, then applied - see "Operator Migration Tool" in the
    # evidence doc), since a resumed run must tolerate either sidecar being
    # further ahead than the other: hand-construct only the applied
    # sidecar exactly as a real run would have produced it.
    applied_path = tmp_path / "execution_applied_executions.jsonl"
    applied_store = AppliedExecutionArchiveStore(applied_path)
    interrupted_at = datetime.now(UTC).isoformat()
    applied_store.append(AppliedExecutionRecord(0, "exec-a", "key-a", interrupted_at))
    applied_store.append(AppliedExecutionRecord(1, "exec-b", "key-b", interrupted_at))
    assert path.read_text(encoding="utf-8")  # v1 file untouched by the simulated partial run

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.MIGRATED
    assert result.applied_appended == 0  # both already durably present, resumed not re-appended
    assert result.closed_appended == 2

    working = json.loads(path.read_text(encoding="utf-8"))
    assert working["schema_version"] == SCHEMA_VERSION
    # The pre-existing applied records' own applied_at timestamps (from the
    # simulated earlier run) are preserved untouched, not re-stamped.
    index = applied_store.load_index()
    assert index.by_execution_id["exec-a"].applied_at == interrupted_at


# ===========================================================================
# Y - conflicting pre-existing sidecar refuses
# ===========================================================================


def test_y_conflicting_pre_existing_applied_sidecar_refuses(tmp_path):
    path = tmp_path / "execution_financial_state.json"
    _write_v1_file(path, applied_executions={"exec-a": "key-a"})

    applied_path = tmp_path / "execution_applied_executions.jsonl"
    AppliedExecutionArchiveStore(applied_path).append(
        AppliedExecutionRecord(0, "exec-a", "DIFFERENT-KEY", datetime.now(UTC).isoformat())
    )
    before_v1 = path.read_bytes()
    before_applied = applied_path.read_bytes()

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.REFUSED_SIDECAR_CONFLICT
    assert result.reason_code == "APPLIED_SIDECAR_DOES_NOT_MATCH_SOURCE"
    assert path.read_bytes() == before_v1
    assert applied_path.read_bytes() == before_applied
    assert not (tmp_path / "execution_closed_positions.jsonl").exists()


# ===========================================================================
# Z - dry-run changes nothing
# ===========================================================================


def test_z_dry_run_reports_counts_and_touches_nothing(tmp_path):
    path = tmp_path / "execution_financial_state.json"
    closed = _closed_record(mint_long_position_id("BTCUSDT", "e-a"))
    _write_v1_file(
        path, closed_positions={closed["position_id"]: closed},
        applied_executions={"exec-a": "key-a"},
    )
    before = path.read_bytes()

    result = migration_module.migrate(tmp_path, dry_run=True)
    assert result.outcome is migration_module.MigrationOutcome.WOULD_MIGRATE
    assert result.applied_count == 1 and result.closed_count == 1
    assert path.read_bytes() == before
    assert not (tmp_path / "execution_applied_executions.jsonl").exists()
    assert not (tmp_path / "execution_closed_positions.jsonl").exists()


def test_z2_cli_dry_run_end_to_end(tmp_path):
    path = tmp_path / "execution_financial_state.json"
    _write_v1_file(path)
    completed = run_migrate_cli("--state-directory", str(tmp_path), "--dry-run", "--json")
    assert completed.returncode == migration_module.EXIT_OK
    payload = json.loads(completed.stdout)
    assert payload["outcome"] == "WOULD_MIGRATE"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


# ===========================================================================
# AA - post-migration bootstrap/restart -> ready
# ===========================================================================


def test_aa_post_migration_bootstrap_and_restart_are_ready(tmp_path):
    path = tmp_path / "execution_financial_state.json"
    closed = _closed_record(mint_long_position_id("BTCUSDT", "e-a"))
    _write_v1_file(
        path, closed_positions={closed["position_id"]: closed},
        applied_executions={"exec-a": "key-a"},
    )
    migrated = migration_module.migrate(tmp_path)
    assert migrated.outcome is migration_module.MigrationOutcome.MIGRATED

    result = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=D("10000"),
        allocatable_capital=D("8000"), policy_version="v1", verify_only=True,
    )
    financial = result.result_for("execution_financial_state")
    assert financial.outcome is BootstrapOutcome.VALID_EXISTING

    foundation = ExecutionPortfolioFoundation(
        FinancialStateStore(path),
        applied_archive=AppliedExecutionArchiveStore(tmp_path / "execution_applied_executions.jsonl"),
        closed_archive=ClosedPositionArchiveStore(tmp_path / "execution_closed_positions.jsonl"),
    )
    assert foundation.ready is True

    # Re-running migration against the now-v2 source is a safe no-op.
    rerun = migration_module.migrate(tmp_path)
    assert rerun.outcome is migration_module.MigrationOutcome.ALREADY_MIGRATED


def test_aa2_cli_source_absent_then_migrated_then_already_migrated(tmp_path):
    absent = run_migrate_cli("--state-directory", str(tmp_path))
    assert absent.returncode == migration_module.EXIT_REFUSED
    assert "SOURCE_ABSENT" in absent.stdout

    _write_v1_file(tmp_path / "execution_financial_state.json")
    migrated = run_migrate_cli("--state-directory", str(tmp_path))
    assert migrated.returncode == migration_module.EXIT_OK
    assert "MIGRATED" in migrated.stdout

    already = run_migrate_cli("--state-directory", str(tmp_path))
    assert already.returncode == migration_module.EXIT_OK
    assert "ALREADY_MIGRATED" in already.stdout


# ===========================================================================
# AD/AE/AF - H-1: closed-sidecar identity is (sequence, payload), not just
# payload - a pre-existing archive must be a valid prefix of this run's
# deterministic output or migration refuses before any destructive rewrite.
# ===========================================================================


def test_ad_closed_sidecar_non_prefix_subset_refuses_before_rewrite(tmp_path):
    """The independent review's exact example: source [p1 seq0, p2 seq1,
    p3 seq2], pre-existing archive [p2 seq0]. p2's content is genuinely
    part of the source, but at the wrong sequence, so the archive is not a
    prefix of the deterministic output and must refuse - not silently
    accept and then append p1 at the now-colliding sequence 0."""
    path = tmp_path / "execution_financial_state.json"
    p1 = _closed_record(mint_long_position_id("BTCUSDT", "p1"), gross_pnl="1")
    p2 = _closed_record(mint_long_position_id("BTCUSDT", "p2"), gross_pnl="2")
    p3 = _closed_record(mint_long_position_id("BTCUSDT", "p3"), gross_pnl="3")
    closed_positions = {p1["position_id"]: p1, p2["position_id"]: p2, p3["position_id"]: p3}
    # position_ids are SHA-256 digests (Block 5G): resolve the real
    # deterministic order the same way the migration tool does, rather than
    # assuming p1/p2/p3 sort in that order.
    ordered_ids = sorted(closed_positions)
    _write_v1_file(path, closed_positions=closed_positions)
    before_source = path.read_bytes()

    closed_path = tmp_path / "execution_closed_positions.jsonl"
    ClosedPositionArchiveStore(closed_path).append(0, closed_positions[ordered_ids[1]])
    before_closed = closed_path.read_bytes()

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.REFUSED_SIDECAR_CONFLICT
    assert result.reason_code == "CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE"
    assert path.read_bytes() == before_source
    assert closed_path.read_bytes() == before_closed
    assert not (tmp_path / "execution_applied_executions.jsonl").exists()


def test_ae_closed_sidecar_exact_prefix_resumes_and_appends_remainder(tmp_path):
    """A pre-existing archive that IS a valid prefix - every record it
    holds matches this source exactly, at that record's own sequence -
    resumes safely and appends only the missing tail."""
    path = tmp_path / "execution_financial_state.json"
    p1 = _closed_record(mint_long_position_id("BTCUSDT", "p1"), gross_pnl="1")
    p2 = _closed_record(mint_long_position_id("BTCUSDT", "p2"), gross_pnl="2")
    p3 = _closed_record(mint_long_position_id("BTCUSDT", "p3"), gross_pnl="3")
    closed_positions = {p1["position_id"]: p1, p2["position_id"]: p2, p3["position_id"]: p3}
    ordered_ids = sorted(closed_positions)
    _write_v1_file(path, closed_positions=closed_positions)

    closed_path = tmp_path / "execution_closed_positions.jsonl"
    archive = ClosedPositionArchiveStore(closed_path)
    archive.append(0, closed_positions[ordered_ids[0]])
    archive.append(1, closed_positions[ordered_ids[1]])

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.MIGRATED
    assert result.closed_appended == 1  # only the third record was missing

    index = archive.load_index()
    assert index.count == 3
    assert set(index.by_position_id) == set(ordered_ids)
    assert index.tail_sequence == 2
    assert index.tail_position_id == ordered_ids[2]


def test_af_closed_sidecar_same_payload_wrong_sequence_refuses(tmp_path):
    """A record whose content exactly matches a real source position, but
    archived one slot early after an otherwise-correct leading prefix, is
    still a sequence mismatch - identity is (sequence, payload) together,
    not payload alone - and must refuse."""
    path = tmp_path / "execution_financial_state.json"
    p1 = _closed_record(mint_long_position_id("BTCUSDT", "p1"), gross_pnl="1")
    p2 = _closed_record(mint_long_position_id("BTCUSDT", "p2"), gross_pnl="2")
    p3 = _closed_record(mint_long_position_id("BTCUSDT", "p3"), gross_pnl="3")
    closed_positions = {p1["position_id"]: p1, p2["position_id"]: p2, p3["position_id"]: p3}
    ordered_ids = sorted(closed_positions)
    _write_v1_file(path, closed_positions=closed_positions)
    before_source = path.read_bytes()

    closed_path = tmp_path / "execution_closed_positions.jsonl"
    archive = ClosedPositionArchiveStore(closed_path)
    archive.append(0, closed_positions[ordered_ids[0]])  # correct
    archive.append(1, closed_positions[ordered_ids[2]])  # true sequence is 2, not 1
    before_closed = closed_path.read_bytes()

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.REFUSED_SIDECAR_CONFLICT
    assert result.reason_code == "CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE"
    assert path.read_bytes() == before_source
    assert closed_path.read_bytes() == before_closed


# ===========================================================================
# AG/AH - H-1: mandatory post-append verification gates the v1 -> v2 rewrite
# ===========================================================================


def test_ag_post_append_corruption_blocks_rewrite_and_preserves_v1(tmp_path, monkeypatch):
    """Damage landing on a sidecar file after its durable append but before
    the mandatory post-append verification must be caught by that
    verification, and must never let the v1 working file be rewritten."""
    path = tmp_path / "execution_financial_state.json"
    closed = _closed_record(mint_long_position_id("BTCUSDT", "e-a"))
    _write_v1_file(
        path, closed_positions={closed["position_id"]: closed},
        applied_executions={"exec-a": "key-a"},
    )
    before_source = path.read_bytes()

    real_append = migration_module.ClosedPositionArchiveStore.append

    def _append_then_corrupt(self, sequence, record):
        real_append(self, sequence, record)
        # Simulate damage landing between this durable append and the
        # migration tool's own post-append reload/verify.
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("{not valid json\n")

    monkeypatch.setattr(migration_module.ClosedPositionArchiveStore, "append", _append_then_corrupt)

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.FAILED
    assert result.reason_code == "POST_APPEND_VERIFICATION_FAILED:CLOSED_SIDECAR"
    assert path.read_bytes() == before_source
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_ah_post_append_verification_reloads_sidecars_from_disk(tmp_path, monkeypatch):
    """Verification must reload each sidecar through its own public
    load_index(), not merely trust that append() was called the expected
    number of times - a write that silently never reaches disk must still
    be caught before the v1 source is touched."""
    path = tmp_path / "execution_financial_state.json"
    _write_v1_file(path, applied_executions={"exec-a": "key-a", "exec-b": "key-b"})
    before_source = path.read_bytes()

    real_append = migration_module.AppliedExecutionArchiveStore.append
    calls = {"count": 0}

    def _append_but_drop_second(self, record):
        calls["count"] += 1
        if calls["count"] == 2:
            return  # pretend this append succeeded; nothing durable landed
        real_append(self, record)

    monkeypatch.setattr(migration_module.AppliedExecutionArchiveStore, "append", _append_but_drop_second)

    result = migration_module.migrate(tmp_path)
    assert result.outcome is migration_module.MigrationOutcome.FAILED
    assert result.reason_code == "POST_APPEND_VERIFICATION_FAILED:APPLIED_SIDECAR"
    assert path.read_bytes() == before_source
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1
    on_disk_count = AppliedExecutionArchiveStore(
        tmp_path / "execution_applied_executions.jsonl"
    ).load_index().count
    assert on_disk_count == 1  # only the first record actually landed


# ===========================================================================
# AI - M-1: bootstrap reason_code never leaks a raw sensitive identifier
# ===========================================================================


def test_ai_bootstrap_reason_code_never_leaks_raw_sensitive_identifiers(tmp_path):
    """ADR-0005 requires reason codes to be fixed tokens, never raw
    exception text. A conflicting applied-sidecar idempotency_key embeds
    the raw key in ExecutionPortfolioFoundation's internal diagnostic
    (see AppliedExecutionArchiveStore.load_index()) - that raw value must
    never reach bootstrap's operator-visible reason_code."""
    sensitive = "SECRET-EXEC-ID-12345"
    store = FinancialStateStore(tmp_path / "execution_financial_state.json")
    store.initialize(D("1000"))
    applied_store = AppliedExecutionArchiveStore(tmp_path / "execution_applied_executions.jsonl")
    now = datetime.now(UTC).isoformat()
    applied_store.append(AppliedExecutionRecord(0, "exec-a", sensitive, now))
    applied_store.append(AppliedExecutionRecord(1, "exec-b", sensitive, now))

    result = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=D("10000"),
        allocatable_capital=D("8000"), policy_version="v1", verify_only=True,
    )
    financial = result.result_for("execution_financial_state")
    assert financial.outcome is BootstrapOutcome.INVALID_EXISTING
    assert sensitive not in financial.reason_code
    assert financial.reason_code == "FINANCIAL_APPLIED_AUTHORITY_CONFLICT"


# ===========================================================================
# AJ - M-2: destructive migration refusal paths, direct coverage
# (CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE is covered above by test_ad/test_af;
# APPLIED_SIDECAR_DOES_NOT_MATCH_SOURCE by test_y - both intentionally
# excluded here rather than duplicated)
# ===========================================================================


def _corrupt_source_unreadable(directory: Path) -> None:
    (directory / "execution_financial_state.json").write_text("{not valid json", encoding="utf-8")


def _corrupt_source_unrecognized_schema(directory: Path) -> None:
    path = directory / "execution_financial_state.json"
    _write_v1_file(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")


def _corrupt_source_negative_cash(directory: Path) -> None:
    _write_v1_file(directory / "execution_financial_state.json", cash="-5")


def _corrupt_applied_sidecar_torn(directory: Path) -> None:
    _write_v1_file(directory / "execution_financial_state.json", applied_executions={"exec-a": "key-a"})
    applied_path = directory / "execution_applied_executions.jsonl"
    with applied_path.open("a", encoding="utf-8") as stream:
        stream.write("{not valid json\n")


def _corrupt_applied_sidecar_conflict(directory: Path) -> None:
    _write_v1_file(directory / "execution_financial_state.json", applied_executions={"exec-a": "key-a"})
    applied_store = AppliedExecutionArchiveStore(directory / "execution_applied_executions.jsonl")
    now = datetime.now(UTC).isoformat()
    applied_store.append(AppliedExecutionRecord(0, "exec-a", "key-a", now))
    applied_store.append(AppliedExecutionRecord(1, "exec-a", "key-b", now))


def _corrupt_closed_sidecar_torn(directory: Path) -> None:
    closed = _closed_record(mint_long_position_id("BTCUSDT", "e-a"))
    _write_v1_file(
        directory / "execution_financial_state.json",
        closed_positions={closed["position_id"]: closed},
    )
    closed_path = directory / "execution_closed_positions.jsonl"
    with closed_path.open("a", encoding="utf-8") as stream:
        stream.write("{not valid json\n")


def _corrupt_closed_sidecar_conflict(directory: Path) -> None:
    closed = _closed_record(mint_long_position_id("BTCUSDT", "e-a"))
    _write_v1_file(
        directory / "execution_financial_state.json",
        closed_positions={closed["position_id"]: closed},
    )
    closed_store = ClosedPositionArchiveStore(directory / "execution_closed_positions.jsonl")
    closed_store.append(0, closed)
    closed_store.append(1, _closed_record(closed["position_id"], gross_pnl="-99"))


_DESTRUCTIVE_REFUSAL_CASES = [
    (_corrupt_source_unreadable, migration_module.MigrationOutcome.SOURCE_INVALID, "SOURCE_UNREADABLE"),
    (_corrupt_source_unrecognized_schema, migration_module.MigrationOutcome.SOURCE_INVALID,
     "SOURCE_UNRECOGNIZED_SCHEMA"),
    (_corrupt_source_negative_cash, migration_module.MigrationOutcome.SOURCE_INVALID, "SOURCE_CORRUPT"),
    (_corrupt_applied_sidecar_torn, migration_module.MigrationOutcome.SIDECAR_INVALID, "APPLIED_SIDECAR_CORRUPT"),
    (_corrupt_applied_sidecar_conflict, migration_module.MigrationOutcome.SIDECAR_INVALID,
     "APPLIED_SIDECAR_CONFLICT"),
    (_corrupt_closed_sidecar_torn, migration_module.MigrationOutcome.SIDECAR_INVALID, "CLOSED_SIDECAR_CORRUPT"),
    (_corrupt_closed_sidecar_conflict, migration_module.MigrationOutcome.SIDECAR_INVALID,
     "CLOSED_SIDECAR_CONFLICT"),
]


@pytest.mark.parametrize(
    "setup, expected_outcome, expected_reason_code",
    _DESTRUCTIVE_REFUSAL_CASES,
    ids=[case[2] for case in _DESTRUCTIVE_REFUSAL_CASES],
)
def test_aj_destructive_migration_refusal_paths_touch_nothing(
    tmp_path, setup, expected_outcome, expected_reason_code,
):
    setup(tmp_path)
    path = tmp_path / "execution_financial_state.json"
    applied_path = tmp_path / "execution_applied_executions.jsonl"
    closed_path = tmp_path / "execution_closed_positions.jsonl"
    before_source = path.read_bytes()
    before_applied = applied_path.read_bytes() if applied_path.exists() else None
    before_closed = closed_path.read_bytes() if closed_path.exists() else None

    result = migration_module.migrate(tmp_path)

    assert result.outcome is expected_outcome
    assert result.reason_code == expected_reason_code
    assert result.outcome is not migration_module.MigrationOutcome.MIGRATED
    assert migration_module._exit_code(result) == migration_module.EXIT_REFUSED
    assert path.read_bytes() == before_source
    if before_applied is not None:
        assert applied_path.read_bytes() == before_applied
    else:
        assert not applied_path.exists()
    if before_closed is not None:
        assert closed_path.read_bytes() == before_closed
    else:
        assert not closed_path.exists()
