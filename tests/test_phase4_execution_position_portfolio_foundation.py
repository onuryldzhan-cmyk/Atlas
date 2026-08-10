from decimal import Decimal as D
import json

import pytest

from core.execution_models import ExecutionResult
from core.execution_portfolio_foundation import ExecutionPortfolioFoundation, FinancialStateStore


def foundation(tmp_path, cash="1000"):
    store = FinancialStateStore(tmp_path / "financial-state.json")
    store.initialize(D(cash))
    return ExecutionPortfolioFoundation(store), store


def execution(*, eid="e1", key="request-1", action="BUY", price="10", base="10",
              fee="1", position="p1", symbol="BTCUSDT", timestamp="2026-08-10T10:00:00+00:00"):
    return ExecutionResult(success=True, status="FILLED", execution_id=eid, order_id="o1",
        position_id=position, symbol=symbol, action=action, filled_price=price,
        filled_base_quantity=D(base), filled_quote_notional=D(price) * D(base),
        fee_amount=D(fee), fee_currency="USDT", timestamp=timestamp,
        idempotency_key=key, provenance_ref="paper-journal:1")


def apply(book, result, version=None):
    return book.apply_confirmed(result, risk_authorized=True,
        reservation_confirmed=True, expected_position_version=version)


def test_execution_contract_explicit_identities_quantities_and_utc():
    result = execution()
    result.validate_financial_evidence()
    assert result.execution_price == D("10")
    assert result.filled_base_quantity == D("10")
    assert result.filled_quote_notional == D("100")


@pytest.mark.parametrize("field", ["execution_id", "position_id", "idempotency_key", "symbol"])
def test_incomplete_financial_evidence_rejected(field):
    result = execution(); setattr(result, field, None)
    with pytest.raises(ValueError, match="Incomplete financial evidence"):
        result.validate_financial_evidence()


def test_ambiguous_amount_is_not_authoritative_evidence():
    result = ExecutionResult(success=True, status="FILLED", execution_id="e", position_id="p",
        symbol="BTCUSDT", action="BUY", filled_price=10, filled_amount=100,
        idempotency_key="k")
    with pytest.raises(ValueError, match="filled_base_quantity"):
        result.validate_financial_evidence()


@pytest.mark.parametrize("value", [D("NaN"), D("Infinity"), D("-1")])
def test_non_finite_and_negative_financial_values_rejected(value):
    with pytest.raises(ValueError): execution(base=value)


def test_float_financial_state_input_rejected(tmp_path):
    book, _ = foundation(tmp_path)
    with pytest.raises(ValueError, match="must not be float"):
        book.set_reserved_capital(1.5)


def test_long_open_accounting_and_observability(tmp_path):
    book, _ = foundation(tmp_path)
    snap = apply(book, execution())
    assert snap["cash"] == D("899")
    assert snap["committed_capital"] == D("100")
    assert snap["gross_exposure"] == D("100")
    assert snap["fees"] == D("1")
    assert snap["equity"] == D("999")
    assert snap["realized_net_pnl"] == D("-1")
    assert book.diagnostics()["recovery_required"] is False


def test_increase_preserves_identity_and_rejects_stale_mutation(tmp_path):
    book, _ = foundation(tmp_path); apply(book, execution())
    increased = execution(eid="e2", key="request-2", base="5", fee="0")
    with pytest.raises(ValueError, match="STALE"):
        apply(book, increased, version=0)
    # A failed durable transition requires reconciliation/recovery; no blind retry.
    assert not book.ready


def test_valid_increase_updates_weighted_position(tmp_path):
    book, _ = foundation(tmp_path); apply(book, execution())
    apply(book, execution(eid="e2", key="request-2", price="20", base="5", fee="0"), version=1)
    position = book.snapshot()["positions"]["BTCUSDT"]
    assert D(position["base_quantity"]) == D("15")
    assert D(position["cost_quote"]) == D("200")
    assert D(position["average_entry_price"]) == D("200") / D("15")
    assert position["version"] == 2


def test_duplicate_open_position_identity_rejected(tmp_path):
    book, _ = foundation(tmp_path); apply(book, execution())
    with pytest.raises(ValueError, match="DUPLICATE_OPEN_POSITION"):
        apply(book, execution(eid="e2", key="request-2", position="other"), version=1)


def test_short_and_partial_close_explicitly_rejected(tmp_path):
    book, _ = foundation(tmp_path); apply(book, execution())
    partial = execution(eid="e2", key="request-2", action="SELL", price="11", base="5", fee="0")
    with pytest.raises(ValueError, match="PARTIAL_CLOSE_DEFERRED"):
        apply(book, partial, version=1)
    other, _ = foundation(tmp_path / "other")
    short = execution(action="SELL")
    with pytest.raises(ValueError, match="POSITION_NOT_FOUND"):
        apply(other, short, version=0)


@pytest.mark.parametrize("exit_price,gross", [("12", "20"), ("8", "-20"), ("10", "0")])
def test_full_close_winning_losing_and_flat_pnl(tmp_path, exit_price, gross):
    book, _ = foundation(tmp_path); apply(book, execution(fee="1"))
    snap = apply(book, execution(eid="e2", key="request-2", action="SELL",
        price=exit_price, base="10", fee="1"), version=1)
    assert snap["positions"] == {}
    assert snap["realized_gross_pnl"] == D(gross)
    assert snap["fees"] == D("2")
    assert snap["realized_net_pnl"] == D(gross) - D("2")
    assert snap["cash"] == D("1000") + D(gross) - D("2")


def test_fee_only_loss(tmp_path):
    book, _ = foundation(tmp_path); apply(book, execution(fee="2"))
    snap = apply(book, execution(eid="e2", key="request-2", action="SELL", fee="3"), version=1)
    assert snap["realized_gross_pnl"] == 0 and snap["realized_net_pnl"] == D("-5")


def test_unrealized_pnl_and_equity(tmp_path):
    book, _ = foundation(tmp_path); apply(book, execution(fee="0")); book.mark("BTCUSDT", D("12"))
    snap = book.snapshot()
    assert snap["unrealized_pnl"] == D("20")
    assert snap["gross_exposure"] == D("120") and snap["equity"] == D("1020")


def test_execution_replay_is_idempotent_no_double_fee_or_cash(tmp_path):
    book, _ = foundation(tmp_path); result = execution(); first = apply(book, result); second = apply(book, result)
    assert second["replayed"] is True
    assert first["cash"] == second["cash"] and second["fees"] == D("1")
    assert len(second["positions"]) == 1


def test_execution_and_idempotency_identity_conflicts_rejected(tmp_path):
    book, _ = foundation(tmp_path); apply(book, execution())
    with pytest.raises(ValueError, match="EXECUTION_IDENTITY_CONFLICT"):
        apply(book, execution(key="changed"))
    with pytest.raises(ValueError, match="IDEMPOTENCY_IDENTITY_CONFLICT"):
        apply(book, execution(eid="different"))


def test_risk_and_reservation_cannot_be_bypassed(tmp_path):
    book, _ = foundation(tmp_path)
    with pytest.raises(PermissionError):
        book.apply_confirmed(execution(), risk_authorized=False, reservation_confirmed=True)
    with pytest.raises(PermissionError):
        book.apply_confirmed(execution(), risk_authorized=True, reservation_confirmed=False)
    assert book.snapshot()["cash"] == D("1000")


def test_reservation_and_available_capital_reconcile(tmp_path):
    book, _ = foundation(tmp_path); book.set_reserved_capital(D("200"))
    assert book.snapshot()["available_capital"] == D("800")
    with pytest.raises(ValueError, match="NEGATIVE_AVAILABLE_CAPITAL"):
        book.set_reserved_capital(D("1001"))


def test_execution_cannot_consume_capital_reserved_elsewhere(tmp_path):
    book, _ = foundation(tmp_path, cash="100")
    book.set_reserved_capital(D("10"))
    with pytest.raises(ValueError, match="NEGATIVE_AVAILABLE_CAPITAL"):
        apply(book, execution(base="9", fee="1"))


def test_restart_preserves_positions_cash_fees_and_realized_pnl(tmp_path):
    book, store = foundation(tmp_path); apply(book, execution())
    apply(book, execution(eid="e2", key="request-2", action="SELL", price="12"), version=1)
    restored = ExecutionPortfolioFoundation(store).snapshot()
    assert restored["cash"] == D("1018")
    assert restored["realized_gross_pnl"] == D("20")
    assert restored["fees"] == D("2")


def test_missing_and_corrupt_state_fail_closed(tmp_path):
    missing = ExecutionPortfolioFoundation(FinancialStateStore(tmp_path / "missing.json"))
    assert missing.diagnostics()["recovery_required"] is True
    path = tmp_path / "corrupt.json"; path.write_text("{}", encoding="utf-8")
    corrupt = ExecutionPortfolioFoundation(FinancialStateStore(path))
    assert corrupt.diagnostics()["recovery_required"] is True


def test_restart_mid_transition_blocks_ready(tmp_path):
    book, store = foundation(tmp_path)
    with pytest.raises(RuntimeError, match="persist failed"):
        apply_with_failure(book, execution())
    restarted = ExecutionPortfolioFoundation(store)
    assert not restarted.ready and restarted.diagnostics()["recovery_required"]


def apply_with_failure(book, result):
    def fail(): raise RuntimeError("persist failed")
    return book.apply_confirmed(result, risk_authorized=True, reservation_confirmed=True,
        before_final_persist=fail)


def test_journal_disagreement_and_indeterminate_execution_not_consumed(tmp_path):
    book, _ = foundation(tmp_path)
    indeterminate = execution(); indeterminate.success = False; indeterminate.status = "COMMIT_STATUS_UNKNOWN"
    with pytest.raises(ValueError, match="not confirmed"):
        apply(book, indeterminate)
    assert book.snapshot()["cash"] == D("1000")


def test_duplicate_position_in_persisted_state_fails_hydration(tmp_path):
    book, store = foundation(tmp_path); apply(book, execution())
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["positions"]["ETHUSDT"] = dict(payload["positions"]["BTCUSDT"])
    payload["positions"]["ETHUSDT"]["symbol"] = "ETHUSDT"
    store.save(payload)
    assert not ExecutionPortfolioFoundation(store).ready
