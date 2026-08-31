"""Block 5F: reservation capital reclamation.

At 5E freeze, ``CapitalReservationLedger._encumbered`` counted RESERVED,
COMMITTED, and INDETERMINATE reservations alike as live encumbrance. RESERVED
and INDETERMINATE are genuinely live - capital that might still be spent or
whose outcome is unknown - but COMMITTED is durable settlement history: the
capital it once held is already accounted for through
``ExecutionPortfolioFoundation``'s own cash balance the instant a reservation
settles. Counting it a second time in the reservation ledger encumbered that
capital forever, so ``available`` shrank by the settled amount of every trade
the book ever closed and never came back - repeated turnover would eventually
exhaust ``available`` even though the real durable cash was nowhere near
exhausted.

The fix (``core/capital_reservation.py``) is a single definition of live
encumbrance - RESERVED + INDETERMINATE only - shared by ``available`` and
``active_reserved_capital`` so the two formulas cannot drift apart again.
Per the owner's ruling: COMMITTED still never transitions to RELEASED, a
reservation is still never linked to the position it funded, and partial or
full exit of that position never mutates the COMMITTED record - the
reclamation is achieved entirely by redefining what counts as encumbrance,
not by adding a lifecycle transition or a reservation/position link.

Explicitly NOT covered here (owner-scoped out of 5F):
- ``closed_positions`` being keyed and overwritten by ``position_id``, so
  only the most recent close of a reused position id survived, was
  identified here as accepted/deferred (5F evidence F3) and has since been
  closed by Block 5G: ``ExecutionManager`` now mints a deterministic
  ``long:<symbol>:<request_id>`` identity per lifetime instead of reusing a
  bare ``long:<symbol>`` constant, and ``ExecutionPortfolioFoundation._close``
  fails closed with ``CLOSED_POSITION_IDENTITY_CONFLICT`` rather than
  silently overwriting if a collision is ever produced. Section E's
  repeated-turnover cycles give each simulated lifetime its own id for this
  reason, rather than reproducing the old collision.
- Unbounded growth of the reservation store or of
  ``ExecutionPortfolioFoundation``'s ``applied_executions`` map - neither is
  ever compacted or pruned.
- Any Decimal/float finding unrelated to live-encumbrance semantics.

Every fixture writes into pytest's tmp_path. Nothing here may touch the
operator's real runtime state.
"""
from __future__ import annotations

from decimal import Decimal as D
import threading

import pytest

from core.application import AtlasApplication
from core.capital_reservation import (
    CapitalReservationLedger,
    JsonReservationStore,
    ReservationStatus,
)
from core.execution_models import ExecutionResult
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)

from tests.test_block2_risk_service_composition_wiring import (
    high_bucket_allocation,
    seed_valid_state,
)
from tests.test_block3_execution_exception_atomicity import (
    break_after_side_effect,
    execute,
    reservation_status,
)


# --------------------------------------------------------------------------
# shared fixtures - real production classes, isolated tmp_path state only
# --------------------------------------------------------------------------


def _ledger(tmp_path, *, name: str = "reservations", total: str = "1000"
            ) -> tuple[CapitalReservationLedger, JsonReservationStore]:
    store = JsonReservationStore(tmp_path / f"{name}.json")
    store.initialize_empty()
    return CapitalReservationLedger(store, D(total)), store


def _foundation(tmp_path, *, name: str = "financial", cash: str = "1000"
                 ) -> tuple[ExecutionPortfolioFoundation, FinancialStateStore,
                            AppliedExecutionArchiveStore, ClosedPositionArchiveStore]:
    store = FinancialStateStore(tmp_path / f"{name}.json")
    store.initialize(D(cash))
    applied_archive = AppliedExecutionArchiveStore(tmp_path / f"{name}-applied.jsonl")
    closed_archive = ClosedPositionArchiveStore(tmp_path / f"{name}-closed.jsonl")
    foundation = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    # No reservation<->position linkage (owner ruling): this foundation's
    # own reserved_capital tracking is independent of the reservation ledger
    # under test, and stays at zero throughout.
    foundation.set_reserved_capital(D("0"))
    return foundation, store, applied_archive, closed_archive


def _fill(action, *, base, price, fee, fee_ccy, execution_id,
          position_id="long:BTCUSDT") -> ExecutionResult:
    return ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id=execution_id,
        position_id=position_id, symbol="BTCUSDT", action=action,
        filled_price=price, filled_base_quantity=D(str(base)),
        filled_quote_notional=D(str(price)) * D(str(base)),
        fee_amount=D(str(fee)), fee_currency=fee_ccy,
        idempotency_key=execution_id, provenance_ref="test",
    )


# ===========================================================================
# A - BUY settlement reclaims capital at the moment it commits
# ===========================================================================


def test_buy_settlement_reclaims_reservation_capital_at_settled_amount(tmp_path):
    """The owner's worked example: approved 100, notional 95, fee 1. Block 5E
    already records the COMMITTED reservation at 96, not the full 100 (the
    unspent sub-quantum remainder). Block 5F's fix is that the 96 no longer
    encumbers ``available`` at all once committed - it returns to the full
    1000, not 1000 - 96."""
    ledger, _ = _ledger(tmp_path, total="1000")

    ledger.reserve("buy-1", "buy-1", D("100"))
    notional, fee = D("95"), D("1")
    committed = ledger.commit("buy-1", notional + fee)

    assert committed.status is ReservationStatus.COMMITTED
    assert committed.amount == D("96")

    # Still durable history: queryable, not purged.
    historical = ledger.get("buy-1")
    assert historical is not None
    assert historical.amount == D("96")
    assert historical.status is ReservationStatus.COMMITTED

    assert ledger.active_reserved_capital() == D("0")
    assert ledger.available == D("1000")


def test_real_execute_buy_reclaims_reservation_capital_through_full_pipeline(tmp_path):
    """Same claim as above, proven through the real composition root and
    ``ExecutionManager.execute()`` rather than direct ledger calls - the fix
    holds through the full production wiring, not only when the ledger is
    driven directly."""
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = AtlasApplication(state_directory=state_dir)
    app.execution.start()
    manager = app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee": 2.5, "fee_currency": "USDT",
    }
    decision = {
        "symbol": "BTCUSDT", "action": "BUY", "price": 10.0,
        "amount": str(high_bucket_allocation(app)), "confidence": 90.0,
        "risk": "HIGH", "request_id": "b1",
    }

    result = manager.execute(decision)

    assert result["commit_outcome"] == "COMMITTED"
    assert manager.reservation_ledger.get("b1").status.value == "COMMITTED"
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert manager.reservation_ledger.available == app.risk_policy.allocatable_capital


# ===========================================================================
# B/C/D - partial and full SELL never mutate reservation history, and every
# checkpoint survives a restart: BUY -> restart -> partial SELL -> restart ->
# full SELL -> restart, on one continuously-reused reservation ledger and
# portfolio foundation.
# ===========================================================================


def test_partial_and_full_sell_leave_committed_reservation_untouched_across_restarts(tmp_path):
    ledger, reservation_store = _ledger(tmp_path, total="1000")
    foundation, financial_store, applied_archive, closed_archive = _foundation(tmp_path, cash="1000")

    def assert_buy_checkpoint(ledger, foundation):
        reservation = ledger.get("flow-1")
        assert reservation.status is ReservationStatus.COMMITTED
        assert reservation.amount == D("96")
        assert ledger.available == D("1000")
        assert ledger.active_reserved_capital() == D("0")
        snapshot = foundation.snapshot()
        assert snapshot["cash"] == D("904")
        position = snapshot["positions"]["BTCUSDT"]
        assert D(position["base_quantity"]) == D("10")
        assert D(position["cost_quote"]) == D("95")
        assert D(position["entry_fees"]) == D("1")

    def assert_partial_sell_checkpoint(ledger, foundation):
        reservation = ledger.get("flow-1")
        assert reservation.status is ReservationStatus.COMMITTED
        assert reservation.amount == D("96")
        assert ledger.available == D("1000")
        assert ledger.active_reserved_capital() == D("0")
        snapshot = foundation.snapshot()
        assert snapshot["cash"] == D("963.5")
        position = snapshot["positions"]["BTCUSDT"]
        assert D(position["base_quantity"]) == D("5")
        assert D(position["cost_quote"]) == D("47.5")
        assert D(position["entry_fees"]) == D("0.5")

    def assert_full_exit_checkpoint(ledger, foundation):
        reservation = ledger.get("flow-1")
        assert reservation.status is ReservationStatus.COMMITTED
        assert reservation.amount == D("96")
        assert ledger.available == D("1000")
        assert ledger.active_reserved_capital() == D("0")
        snapshot = foundation.snapshot()
        assert "BTCUSDT" not in snapshot["positions"]
        assert snapshot["gross_exposure"] == D("0")
        # Durable cash reflects only realized PnL/fees - never the
        # reservation ledger, which this whole scenario never touches again
        # after the BUY committed.
        assert snapshot["cash"] == D("1000") + snapshot["realized_gross_pnl"] - snapshot["fees"]
        assert snapshot["cash"] == D("1018.1")

    # --- BUY: approved 100, notional 95 (10 @ 9.5), fee 1, settled 96.
    ledger.reserve("flow-1", "flow-1", D("100"))
    foundation.apply_confirmed(
        _fill("BUY", base="10", price="9.5", fee="1", fee_ccy="USDT", execution_id="flow-buy"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    ledger.commit("flow-1", D("96"))
    assert_buy_checkpoint(ledger, foundation)

    # --- D: restart after BUY.
    ledger = CapitalReservationLedger(reservation_store, D("1000"))
    foundation = ExecutionPortfolioFoundation(
        financial_store, applied_archive=applied_archive, closed_archive=closed_archive,
    )
    assert_buy_checkpoint(ledger, foundation)

    # --- B: partial SELL, 5 of 10 @ 12, fee 0.5. Cash/exposure move only
    # through the durable portfolio state; the reservation is never touched.
    foundation.apply_confirmed(
        _fill("SELL", base="5", price="12", fee="0.5", fee_ccy="USDT",
              execution_id="flow-sell-partial"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )
    assert_partial_sell_checkpoint(ledger, foundation)

    # --- D: restart after partial SELL.
    ledger = CapitalReservationLedger(reservation_store, D("1000"))
    foundation = ExecutionPortfolioFoundation(
        financial_store, applied_archive=applied_archive, closed_archive=closed_archive,
    )
    assert_partial_sell_checkpoint(ledger, foundation)

    # --- C: full SELL, remaining 5 @ 11, fee 0.4. Position closes.
    foundation.apply_confirmed(
        _fill("SELL", base="5", price="11", fee="0.4", fee_ccy="USDT",
              execution_id="flow-sell-full"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=2,
    )
    assert_full_exit_checkpoint(ledger, foundation)

    # --- D: restart after full SELL.
    ledger = CapitalReservationLedger(reservation_store, D("1000"))
    foundation = ExecutionPortfolioFoundation(
        financial_store, applied_archive=applied_archive, closed_archive=closed_archive,
    )
    assert_full_exit_checkpoint(ledger, foundation)


# ===========================================================================
# E - repeated turnover: the regression the pre-5F formula could not survive
# ===========================================================================


def test_repeated_buy_full_sell_cycles_do_not_decay_available_capital(tmp_path):
    """Under the pre-5F formula, ``available`` shrank by 96 - the settled
    amount - on every completed cycle and never recovered, even though each
    cycle's SELL fully exits and the real durable cash is barely touched (the
    12 USDT/cycle fee). Against a 1000 ceiling with reserve=100/commit=96,
    the old formula would compute ``available = 1000 - 96 * completed`` and
    refuse the 11th cycle's ``reserve(100)`` outright: after 10 completed
    cycles it is already down to 40, and 100 > 40. 12 cycles - one past that
    failure point - proves the new definition keeps admitting turnover the
    old one could not have survived, and that ``available`` never trends
    downward at all.
    """
    ledger, _ = _ledger(tmp_path, total="1000")
    foundation, _, _, _ = _foundation(tmp_path, cash="1000")
    cycles = 12

    for i in range(cycles):
        reservation_id = f"turnover-{i}"
        assert ledger.available == D("1000")

        # Block 5G: each simulated lifetime gets its own deterministic
        # identity - long:BTCUSDT reused across independent lifetimes is
        # exactly the collision ExecutionPortfolioFoundation._close now
        # refuses (CLOSED_POSITION_IDENTITY_CONFLICT).
        lifetime_position_id = f"long:BTCUSDT:{reservation_id}"

        ledger.reserve(reservation_id, reservation_id, D("100"))
        foundation.apply_confirmed(
            _fill("BUY", base="10", price="9.5", fee="1", fee_ccy="USDT",
                  execution_id=f"turnover-buy-{i}", position_id=lifetime_position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
        )
        ledger.commit(reservation_id, D("96"))

        assert ledger.available == D("1000")
        assert ledger.active_reserved_capital() == D("0")

        foundation.apply_confirmed(
            _fill("SELL", base="10", price="9.5", fee="0", fee_ccy="USDT",
                  execution_id=f"turnover-sell-{i}", position_id=lifetime_position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
        )
        assert "BTCUSDT" not in foundation.snapshot()["positions"]

    assert ledger.available == D("1000")
    assert ledger.active_reserved_capital() == D("0")
    # Real cash moved only by the one fee paid per cycle (bought and sold at
    # the same price) - proving the reservation ledger's non-decay is not
    # hiding an equivalent decay somewhere else.
    assert foundation.snapshot()["cash"] == D("1000") - D(cycles)

    for i in range(cycles):
        reservation = ledger.get(f"turnover-{i}")
        assert reservation is not None
        assert reservation.status is ReservationStatus.COMMITTED
        assert reservation.amount == D("96")


# ===========================================================================
# F - INDETERMINATE remains fully encumbering and recovery-blocking
# ===========================================================================


def test_indeterminate_reservation_still_encumbers_and_cannot_release_or_commit(tmp_path):
    ledger, store = _ledger(tmp_path, total="1000")
    ledger.reserve("ind-1", "ind-1", D("300"))
    marked = ledger.mark_indeterminate("ind-1")

    assert marked.status is ReservationStatus.INDETERMINATE
    assert ledger.available == D("700")
    assert ledger.active_reserved_capital() == D("300")

    # Survives restart, unlike a COMMITTED reservation's contribution to
    # available/active_reserved_capital, INDETERMINATE keeps encumbering.
    reloaded = CapitalReservationLedger(store, D("1000"))
    assert reloaded.get("ind-1").status is ReservationStatus.INDETERMINATE
    assert reloaded.available == D("700")
    assert reloaded.active_reserved_capital() == D("300")

    with pytest.raises(ValueError, match="invalid reservation transition"):
        reloaded.release("ind-1")
    with pytest.raises(ValueError, match="invalid reservation transition"):
        reloaded.commit("ind-1")


def test_indeterminate_from_a_real_interrupted_execution_halts_and_still_encumbers(tmp_path):
    """A post-side-effect interruption (Block 3) still marks the reservation
    INDETERMINATE and halts the runtime exactly as before Block 5F. The
    5F-specific claim added here: that INDETERMINATE amount still fully
    encumbers ``available``/``active_reserved_capital`` through the real
    runtime, unlike a COMMITTED reservation."""
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = AtlasApplication(state_directory=state_dir)
    app.execution.start()

    allocation = high_bucket_allocation(app)
    break_after_side_effect(app)

    execute(app)

    assert reservation_status(app, "r1") == ReservationStatus.INDETERMINATE.value
    assert app.execution.execution_halted is True
    assert app.execution.recovery_required is True

    ledger = app.execution.reservation_ledger
    assert ledger.active_reserved_capital() == allocation
    assert ledger.available == app.risk_policy.allocatable_capital - allocation


# ===========================================================================
# G - concurrent RESERVED capacity: total_allocatable still prevents
#     double-spend
# ===========================================================================


def test_concurrent_reservations_still_prevent_double_spend(tmp_path):
    ledger, _ = _ledger(tmp_path, total="100")
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def compete(name: str) -> None:
        barrier.wait()
        try:
            ledger.reserve(name, name, D("75"))
            outcomes.append("reserved")
        except ValueError:
            outcomes.append("blocked")

    threads = [threading.Thread(target=compete, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["blocked", "reserved"]
    assert ledger.available == D("25")


# ===========================================================================
# H - mathematical invariant across every status simultaneously
# ===========================================================================


def test_available_equals_allocatable_minus_active_across_every_status(tmp_path):
    ledger, _ = _ledger(tmp_path, total="1000")

    ledger.reserve("r-reserved", "r-reserved", D("50"))

    ledger.reserve("r-committed", "r-committed", D("70"))
    ledger.commit("r-committed", D("60"))

    ledger.reserve("r-released", "r-released", D("80"))
    ledger.release("r-released")

    ledger.reserve("r-indeterminate", "r-indeterminate", D("90"))
    ledger.mark_indeterminate("r-indeterminate")

    # Only RESERVED (50) and INDETERMINATE (90) are live; COMMITTED and
    # RELEASED contribute nothing.
    assert ledger.active_reserved_capital() == D("140")
    assert ledger.available == ledger.total_allocatable - ledger.active_reserved_capital()
    assert ledger.available == D("860")


# ===========================================================================
# I - history: N completed round trips remain queryable and exact
# ===========================================================================


def test_reservation_history_survives_n_round_trips_and_restart(tmp_path):
    ledger, store = _ledger(tmp_path, total="1000")
    trips = 5

    for i in range(trips):
        reservation_id = f"history-{i}"
        ledger.reserve(reservation_id, reservation_id, D("50"))
        ledger.commit(reservation_id, D("48"))

    reloaded = CapitalReservationLedger(store, D("1000"))
    assert reloaded.ready is True
    assert reloaded.available == D("1000")

    for i in range(trips):
        reservation = reloaded.get(f"history-{i}")
        assert reservation is not None
        assert reservation.status is ReservationStatus.COMMITTED
        assert reservation.amount == D("48")

    assert len(store.load()) == trips
