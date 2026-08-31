"""Block 6B - venue upper-bound safety (readiness gate V1).

Block 5D modelled only the venue's *lower* bounds - `quantity_step`,
`min_quantity`, `min_notional`, `price_tick` - and recorded limitation M4
against the missing upper ones. `docs/evidence/block5_final_closure.md`
carried M4 forward as readiness gate V1 (`LOT_SIZE.maxQty`,
`NOTIONAL.maxNotional`, `MARKET_LOT_SIZE`), REQUIRED before a live adapter is
wired because the adapter is what makes an unmodelled maximum reachable.

These tests hold the contract that closes it. Each one discriminates against
the pre-6B behaviour: every admission below is one the parent commit approved
and this one refuses, or one whose refusal reason the parent commit could not
produce at all.

What is *not* retested here: the lower bounds and quantization
(`tests/test_block5d_instrument_precision_contract.py`), and rule freshness
(`tests/test_block6a_venue_rule_freshness.py`) - including the pinned digest
of a rule that models no upper bound, which is what proves 6B left the
identity of every unbounded rule exactly as it was.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext
from typing import Any

import pytest

from core.application import DEFAULT_INSTRUMENT_RULES_PATH, AtlasApplication
from core.execution_models import ExecutionRequest
from core.instrument_rules import (
    FULL_EXIT_ABOVE_VENUE_MAXIMUM,
    NOTIONAL_ABOVE_VENUE_MAXIMUM,
    QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM,
    QUANTITY_ABOVE_VENUE_MAXIMUM,
    VENUE_UPPER_BOUNDS_UNAVAILABLE,
    InstrumentRules,
    InstrumentRulesConfigError,
    InstrumentRuleset,
    load_instrument_ruleset,
)
from core.venue_rule_freshness import (
    REASON_STALE,
    VenueRuleFreshnessService,
)

from tests.test_block5d_instrument_precision_contract import (
    application,
    buy,
    position_of,
    seed_state,
    sell,
    settle,
)


# Every synthetic rule below is stamped at this instant, so a freshness
# service frozen near it evaluates FRESH and the freshness gate can never be
# what a bounds test is actually observing.
OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)
SHIPPED_OBSERVED_AT = datetime(2026, 8, 19, 18, 0, tzinfo=UTC)


def rule(**overrides: Any) -> InstrumentRules:
    defaults: dict[str, Any] = dict(
        venue="BINANCE",
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity_step="0.00001",
        min_quantity="0.00001",
        min_notional="5",
        price_tick="0.01",
        source="test-fixture",
        source_version="v1",
        retrieved_at="2026-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    return InstrumentRules(**defaults)


def bounded(**overrides: Any) -> InstrumentRules:
    """A rule modelling all three venue upper bounds."""
    defaults: dict[str, Any] = dict(
        max_quantity="1000",
        max_notional="1000000",
        market_max_quantity="1000",
    )
    defaults.update(overrides)
    return rule(**defaults)


def ruleset(*entries: InstrumentRules) -> InstrumentRuleset:
    return InstrumentRuleset({entry.symbol: entry for entry in entries})


def frozen_freshness(at: datetime) -> VenueRuleFreshnessService:
    return VenueRuleFreshnessService(clock=lambda: at)


def order(
    *,
    symbol: str = "BTCUSDT",
    action: str = "BUY",
    price: str = "10.00",
    amount: str = "100",
    order_type: str = "MARKET",
    request_id: str = "b6b",
) -> ExecutionRequest:
    """A sized request; `buy()` from 5D cannot vary ``order_type``."""
    return ExecutionRequest(
        symbol, action, price, amount, confidence=90, risk="MEDIUM",
        request_id=request_id, order_type=order_type,
    )


# ===========================================================================
# rule model and config
# ===========================================================================


def test_upper_bounds_are_optional_and_absence_means_unmodelled() -> None:
    """The shipped config carries no verified maxima, so the schema must be
    able to say "not modelled" rather than forcing a fabricated number. An
    unmodelled bound is not a permissive one: it is what the live gates
    refuse."""
    plain = rule()

    assert (plain.max_quantity, plain.max_notional, plain.market_max_quantity) == (
        None, None, None,
    )
    assert plain.has_complete_venue_bounds is False
    assert plain.upper_bound_violation(
        base_quantity=D("999999999"), quote_notional=D("999999999999"),
    ) is None

    # Completeness is all three: a rule that bounds quantity but not notional
    # still admits an order the venue would refuse.
    assert rule(max_quantity="10").has_complete_venue_bounds is False
    assert rule(
        max_quantity="10", max_notional="100",
    ).has_complete_venue_bounds is False
    assert bounded().has_complete_venue_bounds is True


def test_shipped_config_models_no_upper_bound_and_says_so() -> None:
    """No value was invented for the shipped symbols. This is the premise the
    live fail-closed gate below depends on, so it is asserted rather than
    assumed."""
    shipped = load_instrument_ruleset(DEFAULT_INSTRUMENT_RULES_PATH)

    for symbol in shipped.symbols:
        assert shipped.get(symbol).has_complete_venue_bounds is False


def test_adding_an_upper_bound_changes_rule_identity() -> None:
    """A bound changes which orders are admissible, so it must be sealed: a
    prior risk admission taken under a different maximum has to be
    invalidated, exactly as a changed step or tick already invalidates one.

    The converse - that a rule modelling no bound keeps the digest it had
    before 6B - is pinned in the 6A suite."""
    plain = rule()
    with_bounds = bounded()
    wider = bounded(max_quantity="2000")

    assert len({plain.digest, with_bounds.digest, wider.digest}) == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_quantity": "0.000001"},          # below min_quantity
        {"max_notional": "1"},                 # below min_notional
        {"market_max_quantity": "0.000001"},   # below min_quantity
        {"max_quantity": "0"},
        {"max_notional": "-5"},
        {"max_quantity": 1000.0},              # float: cannot be exact
    ],
)
def test_contradictory_or_inexact_bounds_are_refused_at_load(overrides) -> None:
    """A maximum below the matching minimum admits nothing at all. That is a
    defective config, refused when it is loaded rather than silently rejecting
    every request at runtime - and a float bound is refused for the same
    reason the existing Decimal fields refuse one."""
    with pytest.raises(InstrumentRulesConfigError):
        rule(**overrides)


def test_a_misspelled_bound_is_refused_rather_than_read_as_absent(tmp_path) -> None:
    """The hazard optional fields create: a typo would otherwise read as "this
    venue has no maximum" and silently reopen the gate."""
    entry = bounded().to_dict()
    entry["max_quanttiy"] = entry.pop("max_quantity")

    config = tmp_path / "instrument_rules.json"
    config.write_text(
        json.dumps({"schema_version": "1.0", "rules": [entry]}), encoding="utf-8",
    )

    with pytest.raises(InstrumentRulesConfigError):
        load_instrument_ruleset(config)


def test_config_round_trip_preserves_bounds_and_identity(tmp_path) -> None:
    """Bounds survive serialization exactly, and an unmodelled bound is
    omitted rather than written as null - so the shipped config's on-disk
    shape is unchanged by this package."""
    original = bounded(max_quantity="9000.00000", max_notional="9000000")

    config = tmp_path / "instrument_rules.json"
    config.write_text(
        json.dumps({"schema_version": "1.0", "rules": [original.to_dict()]}),
        encoding="utf-8",
    )

    reloaded = load_instrument_ruleset(config).get("BTCUSDT")

    assert reloaded.digest == original.digest
    assert reloaded.max_quantity == D("9000.00000")
    assert reloaded.max_notional == D("9000000")
    assert reloaded.market_max_quantity == D("1000")

    assert "max_quantity" not in rule().to_dict()
    assert "market_max_quantity" not in rule().to_dict()


# ===========================================================================
# the bound evaluation itself
# ===========================================================================


def test_an_order_exactly_at_every_bound_is_admissible() -> None:
    """Boundary equality, stated once: the venue accepts an order *at* its
    maximum, so this refuses only what is strictly above it. One step past
    each bound refuses."""
    entry = bounded(max_quantity="10", max_notional="100", market_max_quantity="10")

    assert entry.upper_bound_violation(
        base_quantity=D("10"), quote_notional=D("100"),
    ) is None

    assert entry.upper_bound_violation(
        base_quantity=D("10.00001"), quote_notional=D("100"),
    )[0] == QUANTITY_ABOVE_VENUE_MAXIMUM

    assert entry.upper_bound_violation(
        base_quantity=D("10"), quote_notional=D("100.01"),
    )[0] == NOTIONAL_ABOVE_VENUE_MAXIMUM


def test_each_bound_reports_its_own_stable_reason_and_evidence() -> None:
    """Reason codes are stable and carry only which bound was exceeded and by
    what - no account, key, or venue payload."""
    entry = bounded(max_quantity="50", max_notional="400", market_max_quantity="20")

    reason, details = entry.upper_bound_violation(
        base_quantity=D("60"), quote_notional=D("100"),
    )
    assert reason == QUANTITY_ABOVE_VENUE_MAXIMUM
    assert details == {"base_quantity": "60", "max_quantity": "50"}

    reason, details = entry.upper_bound_violation(
        base_quantity=D("30"), quote_notional=D("100"),
    )
    assert reason == QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM
    assert details["market_max_quantity"] == "20"
    assert details["order_type"] == "MARKET"

    reason, details = entry.upper_bound_violation(
        base_quantity=D("10"), quote_notional=D("500"),
    )
    assert reason == NOTIONAL_ABOVE_VENUE_MAXIMUM
    assert details == {"quote_notional": "500", "max_notional": "400"}


def test_market_lot_size_binds_market_orders_only() -> None:
    """MARKET_LOT_SIZE is a distinct venue filter, not a second copy of
    LOT_SIZE: it constrains market orders alone. A limit order at the same
    size clears it - and is still held to LOT_SIZE.maxQty."""
    entry = bounded(max_quantity="50", market_max_quantity="20")

    assert entry.upper_bound_violation(
        base_quantity=D("30"), quote_notional=D("1"), order_type="LIMIT",
    ) is None
    assert entry.upper_bound_violation(
        base_quantity=D("30"), quote_notional=D("1"), order_type="market",
    )[0] == QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM
    assert entry.upper_bound_violation(
        base_quantity=D("60"), quote_notional=D("1"), order_type="LIMIT",
    )[0] == QUANTITY_ABOVE_VENUE_MAXIMUM


def test_bound_comparison_is_exact_under_a_hostile_decimal_context() -> None:
    """The comparison must not be reachable by arithmetic precision. Under a
    context far too small to hold these values, a difference in the ninth
    significant digit still decides - which it could not if the check were a
    subtraction or a ratio."""
    entry = bounded(max_quantity="12345678.9", market_max_quantity="12345678.9")

    with localcontext() as context:
        context.prec = 6

        assert entry.upper_bound_violation(
            base_quantity=D("12345678.9"), quote_notional=D("1"),
        ) is None
        assert entry.upper_bound_violation(
            base_quantity=D("12345678.90001"), quote_notional=D("1"),
        )[0] == QUANTITY_ABOVE_VENUE_MAXIMUM


# ===========================================================================
# BUY admission
# ===========================================================================


def bounded_app(tmp_path, *, entry: InstrumentRules, **seeding):
    """A started PAPER runtime trading one symbol under a synthetic rule."""
    app = application(tmp_path, symbols=[entry.symbol], **seeding)
    app.execution.instrument_rule_freshness = frozen_freshness(
        OBSERVED_AT + timedelta(hours=1)
    )
    app.execution.instrument_rules = ruleset(entry)
    app.execution.start()
    assert app.execution.execution_halted is False
    return app


def test_buy_within_every_bound_is_admitted(tmp_path) -> None:
    """The gate discriminates on size, not on the mere presence of bounds: a
    bounded rule still admits an order that fits."""
    app = bounded_app(tmp_path, entry=bounded())

    request = buy(price="10.00", amount="100", request_id="within-bounds")
    admission = app.execution.risk_check(request)

    assert admission["approved"] is True
    assert request.approved_quote_allocation == D("100")


def test_buy_exactly_at_the_bounds_is_admitted(tmp_path) -> None:
    """Boundary equality through the real admission path: 100 quote at 10.00
    is exactly 10 base and exactly 100 notional."""
    app = bounded_app(
        tmp_path,
        entry=bounded(max_quantity="10", max_notional="100", market_max_quantity="10"),
    )

    admission = app.execution.risk_check(
        buy(price="10.00", amount="100", request_id="at-bounds")
    )

    assert admission["approved"] is True


@pytest.mark.parametrize(
    "overrides, expected_reason",
    [
        ({"max_quantity": "9.99999"}, QUANTITY_ABOVE_VENUE_MAXIMUM),
        ({"max_notional": "99.99"}, NOTIONAL_ABOVE_VENUE_MAXIMUM),
        ({"market_max_quantity": "9.99999"}, QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM),
    ],
)
def test_buy_above_a_venue_maximum_is_refused_before_reservation(
    tmp_path, overrides, expected_reason
) -> None:
    """The core of gate V1: an oversized new-risk BUY the parent commit
    admitted is now refused, in the same fail-closed place the lower bounds
    are enforced - before any capital is reserved and before an admission is
    recorded, so nothing is left behind to reconcile."""
    app = bounded_app(tmp_path, entry=bounded(**overrides))

    request = buy(price="10.00", amount="100", request_id="above-bound")
    admission = app.execution.risk_check(request)

    assert admission["approved"] is False
    assert admission["reason"] == expected_reason
    assert app.reservation_ledger.get(request.request_id) is None
    assert app.execution._has_risk_admission(request) is False
    # Never resized down to the maximum: the request is refused whole.
    assert request.approved_quote_allocation is None


def test_an_oversized_buy_is_never_capped_to_the_maximum(tmp_path) -> None:
    """The symmetry with the lower bounds, which never raise an allocation to
    reach a minimum: this never lowers one to fit a maximum. A smaller,
    independently submitted request is still evaluated fresh."""
    app = bounded_app(tmp_path, entry=bounded(max_quantity="5"))

    refused = buy(price="10.00", amount="100", request_id="too-big")
    assert app.execution.risk_check(refused)["approved"] is False
    assert position_of(app) is None

    fits = buy(price="10.00", amount="50", request_id="fits")
    assert app.execution.risk_check(fits)["approved"] is True


def test_limit_order_clears_the_market_bound_at_the_same_size(tmp_path) -> None:
    """MARKET_LOT_SIZE reaches the admission gate as a market-order
    constraint, not a universal one."""
    app = bounded_app(tmp_path, entry=bounded(market_max_quantity="9.99999"))

    as_market = app.execution.risk_check(
        order(request_id="market-order", order_type="MARKET")
    )
    assert as_market["approved"] is False
    assert as_market["reason"] == QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM

    as_limit = app.execution.risk_check(
        order(request_id="limit-order", order_type="LIMIT")
    )
    assert as_limit["approved"] is True


# ===========================================================================
# SELL
# ===========================================================================


def test_full_exit_above_the_venue_maximum_fails_closed_without_mutation(
    tmp_path,
) -> None:
    """A holding larger than one venue order is not sellable in one order.
    Refused for operator reconciliation - never silently split into several
    orders, which would be an execution plan no risk authority approved."""
    app = bounded_app(
        tmp_path,
        entry=bounded(max_quantity="50", market_max_quantity="50"),
        positions=[("BTCUSDT", "100.00000", "10")],
    )
    app.paper_trader.open_trade("BTCUSDT", 10, 1000)

    request = sell(amount=0, price="10", request_id="full-exit-too-big")
    assert app.execution.risk_check(request)["approved"] is True

    result = app.execution.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == FULL_EXIT_ABOVE_VENUE_MAXIMUM
    # The full-exit refusal is operationally distinct from a partial one, so
    # it names which bound the holding itself broke.
    assert result["error_details"]["exceeded_bound"] == QUANTITY_ABOVE_VENUE_MAXIMUM
    assert result["error_details"]["max_quantity"] == "50"
    assert position_of(app)["base_quantity"] == "100.00000"
    assert app.execution._execution_side_effect_ids == set()


def test_partial_reduction_above_the_venue_maximum_fails_closed_without_mutation(
    tmp_path,
) -> None:
    """The SELL side of the same gate, on the reduction actually submitted.
    The size is the risk-approved reduction: this path prices it, and refuses
    it, but never clips it down to the maximum."""
    app = bounded_app(
        tmp_path,
        entry=bounded(max_notional="400", max_quantity="1000"),
        positions=[("BTCUSDT", "100.00000", "10")],
    )
    app.paper_trader.open_trade("BTCUSDT", 10, 1000)

    request = sell(amount="500", price="10", request_id="partial-too-big")
    assert app.execution.risk_check(request)["approved"] is True

    result = app.execution.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == NOTIONAL_ABOVE_VENUE_MAXIMUM
    assert position_of(app)["base_quantity"] == "100.00000"
    assert app.execution._execution_side_effect_ids == set()


def test_a_sell_within_the_bounds_still_settles(tmp_path) -> None:
    """The no-regression half: a reduction that clears every bound reaches the
    durable book exactly as it did before this package."""
    app = bounded_app(
        tmp_path,
        entry=bounded(),
        positions=[("BTCUSDT", "100.00000", "10")],
    )
    app.paper_trader.open_trade("BTCUSDT", 10, 1000)

    result = settle(app, sell(amount="300", price="10", request_id="within-bounds-sell"))

    assert D(result["filled_base_quantity"]) == D("30.00000")
    assert D(position_of(app)["base_quantity"]) == D("70.00000")


# ===========================================================================
# PAPER policy: unchanged where no bound is modelled
# ===========================================================================


def test_bounded_paper_runtime_without_modelled_maxima_is_unchanged(tmp_path) -> None:
    """The explicit PAPER policy. With the shipped config - which models no
    maximum - a PAPER runtime starts, admits, and settles exactly as it did
    before 6B. Unmodelled maxima are not turned into live-style refusals
    here: nothing leaves the paper book, which is the recorded reason V1 was
    SAFE for bounded execution in the first place."""
    app = application(tmp_path)
    app.execution.start()

    assert app.execution.execution_halted is False
    assert app.instrument_ruleset.get("BTCUSDT").has_complete_venue_bounds is False

    result = settle(app, buy(price="10", amount="1000", request_id="paper-unchanged"))

    assert result["success"] is True
    assert D(position_of(app)["base_quantity"]) == D("100.00000")


# ===========================================================================
# LIVE authority: fail closed
# ===========================================================================


def live_app(tmp_path, *, entries=(), symbols=None, at=SHIPPED_OBSERVED_AT):
    """A live-authorized runtime, with freshness frozen so the 6A gate can
    never be what a 6B assertion is actually observing."""
    app = AtlasApplication(
        state_directory=seed_state(tmp_path / "state"),
        execution_mode="LIVE",
        symbols=symbols,
    )
    manager = app.execution
    manager.live_execution_enabled = True
    manager.instrument_rule_freshness = frozen_freshness(at)
    if entries:
        manager.instrument_rules = ruleset(*entries)
    return app, manager


def test_live_authorized_runtime_halts_when_maxima_are_unmodelled(tmp_path) -> None:
    """Gate V1 enforced where it matters most: a runtime that could actually
    reach a venue does not come online at all against rules that do not model
    the venue's maxima. The shipped config is used as-is - this is the state
    the repository is really in."""
    app, manager = live_app(tmp_path)

    manager.start()

    assert manager.live_authorized is True
    assert manager.execution_halted is True
    assert manager.recovery_required is True
    assert manager.halt_reason == VENUE_UPPER_BOUNDS_UNAVAILABLE


def test_the_same_runtime_starts_once_the_maxima_are_modelled(tmp_path) -> None:
    """The gate discriminates on the bounds, not on live authority alone: the
    identical live-authorized runtime comes online cleanly when every
    configured symbol models complete bounds."""
    app, manager = live_app(
        tmp_path,
        entries=(bounded(),),
        symbols=["BTCUSDT"],
        at=OBSERVED_AT + timedelta(hours=1),
    )

    manager.start()

    assert manager.execution_halted is False
    assert manager.halt_reason is None


def test_bounded_paper_runtime_is_not_held_to_the_live_bar(tmp_path) -> None:
    """The same unbounded rules, without live authority: no halt. Live
    authority is what ends the tolerance, exactly as the closure record
    said."""
    app = application(tmp_path)
    app.execution.start()

    assert app.execution.live_authorized is False
    assert app.execution.execution_halted is False


def test_live_dispatch_refuses_an_unbounded_symbol_before_the_adapter_step(
    tmp_path,
) -> None:
    """The startup gate covers the configured and held symbols; a request for
    any other symbol reaches dispatch unchecked. This is where that is caught
    - ahead of the adapter step, which is the last place it can be - and the
    refusal is the bounds gate, not the adapter's own denial."""
    app, manager = live_app(
        tmp_path,
        entries=(bounded(), rule(symbol="ETHUSDT", base_asset="ETH")),
        symbols=["BTCUSDT"],
        at=OBSERVED_AT + timedelta(hours=1),
    )
    manager.start()
    assert manager.execution_halted is False

    # ETHUSDT models no maximum and is outside the startup-checked universe,
    # so admission - which enforces only the bounds that exist - approves it.
    request = buy(
        symbol="ETHUSDT", price="10.00", amount="100", request_id="live-unbounded",
    )
    assert manager.risk_check(request)["approved"] is True

    outcome = manager.live_execute(request)

    assert outcome["success"] is False
    assert outcome["status"] == VENUE_UPPER_BOUNDS_UNAVAILABLE
    assert outcome["error_code"] == VENUE_UPPER_BOUNDS_UNAVAILABLE
    assert outcome["status"] not in manager.SUCCESS_STATUSES
    # Refused by this gate rather than falling through to the adapter denial.
    assert outcome["error_code"] != "LIVE_ADAPTER_NOT_IMPLEMENTED"


def test_the_freshness_gate_still_precedes_the_upper_bound_gate(tmp_path) -> None:
    """Interaction with 6A, pinned: when rules are both stale and unbounded,
    the older-established refusal wins, so neither gate can mask the other and
    the reason an operator sees is deterministic."""
    app, manager = live_app(
        tmp_path,
        entries=(bounded(), rule(symbol="ETHUSDT", base_asset="ETH")),
        symbols=["BTCUSDT"],
        at=OBSERVED_AT + timedelta(hours=1),
    )
    manager.start()

    request = buy(
        symbol="ETHUSDT", price="10.00", amount="100", request_id="live-stale-unbounded",
    )
    assert manager.risk_check(request)["approved"] is True

    # Only the clock moves: the ruleset - and therefore the digest sealed into
    # the admission - is untouched.
    manager.instrument_rule_freshness = frozen_freshness(datetime(2027, 1, 1, tzinfo=UTC))

    outcome = manager.live_execute(request)

    assert outcome["status"] == "VENUE_RULES_NOT_FRESH"
    assert outcome["error_code"] == REASON_STALE
