"""
Block 5 / Package 5L - Final Block 5 Hardening and Closure Gates.

Package 5L found no MUST-FIX correctness defect: every remaining Block 5
item classified as an accepted operational limitation, a future live-scale
requirement, or already resolved (see
``docs/evidence/block5_final_closure.md``).

What this module adds is therefore not a re-test of Blocks 5B-5K. It is the
set of *enforced gates* that keep the closure record honest - each one fails
the day a premise behind an accepted limitation stops being true, so the
limitation has to be re-decided rather than silently inherited.

Every test uses an isolated temporary state directory; none constructs a
runtime that could reach the repository's real state files.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal as D
from decimal import getcontext, localcontext
from inspect import signature
from pathlib import Path

import pytest

from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest, ExecutionResult
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
    mint_long_position_id,
    validate_closed_position_record,
)
from core.instrument_rules import InstrumentRules
from core.risk_engine import RiskEngine, RiskPolicy, RiskRequest, RiskState

_SYMBOL = "BTCUSDT"


def _foundation(directory: Path, *, cash: str) -> ExecutionPortfolioFoundation:
    directory.mkdir(parents=True, exist_ok=True)
    store = FinancialStateStore(directory / "execution_financial_state.json")
    store.initialize(D(cash))
    return ExecutionPortfolioFoundation(
        store,
        applied_archive=AppliedExecutionArchiveStore(
            directory / "execution_applied_executions.jsonl"
        ),
        closed_archive=ClosedPositionArchiveStore(
            directory / "execution_closed_positions.jsonl"
        ),
    )


def _fill(
    *, action: str, execution_id: str, position_id: str, request_id: str,
    price: str, base: str, fee: str = "0",
) -> ExecutionResult:
    # The test's own arithmetic runs at a precision high enough to be exact
    # for these operands, so that only Atlas's arithmetic is under test when
    # the ambient context is made hostile below.
    with localcontext() as exact:
        exact.prec = 60
        notional = D(price) * D(base)
    return ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id=execution_id,
        position_id=position_id, symbol=_SYMBOL, action=action,
        filled_price=price, filled_base_quantity=D(base),
        filled_quote_notional=notional,
        fee_amount=D(fee), fee_currency="USDT",
        idempotency_key=request_id, provenance_ref=f"transaction-journal:{request_id}",
    )


# ===========================================================================
# Gate 1 - venue upper bounds (Block 5D M4) stay unreachable
# ===========================================================================


def test_instrument_rules_still_model_no_upper_venue_bound() -> None:
    """The premise of the accepted M4 limitation, pinned.

    `LOT_SIZE.maxQty`, `NOTIONAL.maxNotional` and `MARKET_LOT_SIZE` are not
    modelled. This test fails the moment an upper bound *is* added, which is
    the moment the live-readiness gate in the closure record has to be
    re-decided rather than left standing as written."""

    modelled = {field.name for field in fields(InstrumentRules)}

    assert {"quantity_step", "min_quantity", "min_notional", "price_tick"} <= modelled
    assert not {
        name for name in modelled
        if name.startswith("max_") or "market_lot" in name
    }


def test_live_execution_cannot_reach_a_venue_while_upper_bounds_are_unmodelled(
    tmp_path: Path,
) -> None:
    """The safety coupling that makes M4 acceptable, enforced.

    An unmodelled venue maximum can only be *violated* by an order that
    actually reaches a venue. No such path exists: live execution is denied
    by default, and even with the flag explicitly enabled there is no
    approved adapter, so the request is refused rather than sent. This test
    fails the day a live adapter is wired in without upper bounds being
    modelled first."""

    for enabled in (False, True):
        manager = ExecutionManager(
            idempotency_file=str(tmp_path / f"idempotency-{enabled}.jsonl"),
            transaction_journal_file=str(tmp_path / f"journal-{enabled}.jsonl"),
            audit_enabled=False,
            live_execution_enabled=enabled,
        )

        outcome = manager.live_execute(
            ExecutionRequest(
                symbol=_SYMBOL, action="BUY", price=10.0, amount=100.0,
                confidence=90, request_id=f"req-live-gate-{enabled}",
            )
        )

        assert outcome["success"] is False

    # There is no live adapter seam to configure, so no request can be handed
    # to a venue however the manager is constructed. Adding one is what must
    # re-open the upper-bound decision, and that is what this fails on.
    parameters = set(signature(ExecutionManager.__init__).parameters)

    assert not {name for name in parameters if "adapter" in name or "venue_client" in name}


# ===========================================================================
# Gate 2 - the closed-position schema stays exactly canonical (5I L-4)
# ===========================================================================


def test_closed_position_schema_is_exact_and_refuses_unknown_fields() -> None:
    """The accepted L-4 limitation, enforced in both directions.

    Exact field-set equality is deliberate: the archive record is precisely
    what `_close` produces, and an unknown field in a record claiming to be
    closed-position history is unexplained state, not metadata to ignore.
    Migration of such a record fails closed and is an operator decision. This
    test fails if the schema is ever quietly widened to accept extras."""

    canonical = {
        "position_id": mint_long_position_id(_SYMBOL, "req-schema"),
        "symbol": _SYMBOL, "base_quantity": "0", "cost_quote": "100",
        "entry_fees": "0", "average_entry_price": "10", "mark_price": "10",
        "version": 2, "opened_at": "2026-08-25T00:00:00+00:00", "status": "CLOSED",
        "exit_price": "11", "gross_pnl": "10", "closed_at": "2026-08-25T01:00:00+00:00",
    }

    validate_closed_position_record(dict(canonical))

    with pytest.raises(ValueError, match="CORRUPT_CLOSED_POSITION_RECORD"):
        validate_closed_position_record({**canonical, "venue_note": "legacy"})

    with pytest.raises(ValueError, match="CORRUPT_CLOSED_POSITION_RECORD"):
        missing = dict(canonical)
        del missing["gross_pnl"]
        validate_closed_position_record(missing)


# ===========================================================================
# Gate 3 - financial arithmetic does not depend on the ambient Decimal context
# ===========================================================================


def test_financial_arithmetic_is_isolated_from_a_hostile_decimal_context(
    tmp_path: Path,
) -> None:
    """Block 5B's `localcontext()` discipline, proven by behaviour.

    Every financial quantization in the execution path runs inside an
    explicit local context. This drives a real open/close cycle whose values
    need far more than six significant digits, once under the default context
    and once under a deliberately hostile global precision, and requires the
    two books to be identical. An implementation that quantized or divided
    under the ambient context would round differently and diverge here."""

    # Enough significant digits that a prec=6 context would visibly round,
    # and few enough that each price survives ExecutionResult's documented
    # `filled_price` float mirror exactly (Block 5B: the mirror is lossy, so
    # a price needing more than float can carry is refused by
    # validate_financial_evidence rather than booked wrong).
    price = "12345.6789"
    base = "1.2345"
    exit_price = "23456.7891"

    def _run(directory: Path) -> dict[str, D]:
        foundation = _foundation(directory, cash="1000000000.123456789")
        position_id = mint_long_position_id(_SYMBOL, "req-ctx")

        foundation.apply_confirmed(
            _fill(action="BUY", execution_id="exec-open", position_id=position_id,
                  request_id="req-ctx-open", price=price, base=base, fee="0.987654321"),
            risk_authorized=True, reservation_confirmed=True,
            expected_position_version=None,
        )
        foundation.apply_confirmed(
            _fill(action="SELL", execution_id="exec-close", position_id=position_id,
                  request_id="req-ctx-close", price=exit_price, base=base, fee="1.23456789"),
            risk_authorized=True, reservation_confirmed=True,
            expected_position_version=1,
        )

        snapshot = foundation.snapshot()
        return {
            key: snapshot[key]
            for key in (
                "cash", "fees", "realized_gross_pnl", "realized_net_pnl",
                "committed_capital", "equity", "available_capital",
            )
        }

    default_context = _run(tmp_path / "default")

    with localcontext() as hostile:
        hostile.prec = 6
        # Sanity: the hostile context really is active and really is
        # destructive - an unguarded division here keeps six digits, not the
        # dozens these figures need.
        assert getcontext().prec == 6
        assert len((D(price) * D(base)).as_tuple().digits) <= 6
        hostile_context = _run(tmp_path / "hostile")

    assert hostile_context == default_context

    # And the values genuinely exceed what prec=6 could have carried.
    assert len(default_context["realized_gross_pnl"].as_tuple().digits) > 6
    assert len(default_context["cash"].as_tuple().digits) > 6


def test_risk_admission_is_isolated_from_a_hostile_decimal_context() -> None:
    """The same discipline on the capital-accounting authority.

    Risk ceilings are derived from `total_capital` by multiplication, and the
    approved allocation is the minimum of the request and those ceilings. A
    ceiling rounded *up* under a narrow ambient context would admit an
    allocation above the true policy limit - fail-open on capital, unlike the
    fail-closed evidence gate above - so the derivation runs in an explicit
    local context (Block 5L)."""

    policy = RiskPolicy(total_capital=D("1000000000.123456789"))
    state = RiskState(
        positions=(), committed_quote=D("0"), realized_daily_pnl=D("0"),
        peak_equity=D("1000000000.123456789"),
        current_equity=D("1000000000.123456789"),
        state_ready=True,
        accounting_day_utc=datetime.now(UTC).date().isoformat(),
        policy_version=policy.version,
    )
    # Below every ceiling, so the request is approved and the decision
    # actually carries the derived figures rather than a rejection's zeros.
    request = RiskRequest(
        symbol=_SYMBOL, action="BUY", confidence=D("0.9"),
        requested_quote_allocation=D("12345678.123456789"),
        execution_price=D("12345.6789"), risk_bucket="HIGH",
    )

    def _decide() -> tuple[str, D, D, D]:
        decision = RiskEngine(policy=policy).evaluate(request, state)
        return (
            decision.reason_code, decision.approved_allocation,
            decision.available_capital, decision.reserved_capital,
        )

    default_context = _decide()

    with localcontext() as hostile:
        hostile.prec = 6
        assert getcontext().prec == 6
        hostile_context = _decide()

    assert hostile_context == default_context
    assert default_context[0] == "RISK_APPROVED"

    # The figures this decision carries need far more than six significant
    # digits, so a context-dependent derivation would have moved them.
    assert len(default_context[1].as_tuple().digits) > 6
    assert len(default_context[3].as_tuple().digits) > 6
