"""Task 010: execution engine, order routing and transaction journal (registry v5.94 grant).

Live authority stays DENIED: there is no live adapter, and every venue here is a simulated one at
the ExchangeManager adapter seam (the owner's decision: paper + simulated venue only). Covered:
the environment firewall (no order, no status query and no credentials outside live
authorization), partial fills journaled and reconciled across a disconnect and a restart, the fill
ledger's monotonic, drift-free accounting, exposure reservations that count every open BUY and are
released on any terminal outcome, the market-data latch fix with BUYs frozen on stale data while
exits route, and a concurrent journal stress run.
"""

from __future__ import annotations

import json
import socket
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from core.durable_append_log import DurableAppendLog
from exchange.adapters.binance_global import BinanceGlobalExchange
from exchange.base_exchange import VenueRejectedError
from exchange.execution_risk_guard import ExecutionRiskGuard
from exchange.execution_safety_gate import ExecutionSafetyGate
from exchange.exchange_manager import ExchangeManager
from tests.exchange.test_task008_safety_idempotency import FakeVenue, exposure_guard, journal_events, manager
from tests.test_block5c_upstream_sizing_authority import execution_enabled_loop, flat_app, holding_app  # noqa: F401
from tests.test_buy_stale_data_gate import _age_clock, _spy_execute


def buy(m: ExchangeManager, key: str, *, symbol: str = "BTCUSDT", quantity: float = 1.0,
        notional: float = 1_000.0) -> dict[str, Any]:
    return m.place_order(symbol, "BUY", quantity, idempotency_key=key, order_notional=notional,
                         opens_new_position=False)


@pytest.fixture
def no_network(monkeypatch):
    """Any socket use fails the test: the firewall must refuse before the network."""
    attempts: list[Any] = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    return attempts


# -- 3.1 environment firewall ------------------------------------------------------------------


@pytest.mark.parametrize("environment", [
    {},  # missing: defaults to PAPER
    {"ATLAS_EXECUTION_MODE": "LIVE_PRODUCTION"},  # not a mode this gate knows: PAPER
    {"ATLAS_EXECUTION_MODE": "garbage", "ATLAS_LIVE_ENABLED": "true"},
    {"ATLAS_EXECUTION_MODE": "LIVE"},  # LIVE without the explicit enablement
    {"ATLAS_EXECUTION_MODE": "LIVE", "ATLAS_LIVE_ENABLED": "true", "ATLAS_KILL_SWITCH": "true"},
])
def test_without_live_authorization_nothing_reaches_the_network(environment, no_network, monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_API_KEY", "k" * 64)
    monkeypatch.setenv("BINANCE_API_SECRET", "s" * 64)
    adapter = BinanceGlobalExchange()
    m = ExchangeManager(
        exchange_name="binance_global", exchange=adapter,
        safety_gate=ExecutionSafetyGate.from_environment(environment),
        risk_guard=ExecutionRiskGuard(starting_equity=10_000.0, max_daily_loss_percent=5.0,
                                      max_drawdown_percent=10.0),
        exposure_guard=exposure_guard(), order_journal_path=tmp_path / "journal.jsonl")
    result = buy(m, "atl-" + "a" * 32)
    assert result["status"] == "REJECTED"
    assert result["reason"] in {"EXECUTION_MODE_NOT_LIVE", "LIVE_NOT_EXPLICITLY_ENABLED", "KILL_SWITCH_ACTIVE"}
    assert no_network == [] and adapter.client is None and adapter.connected is False
    assert not hasattr(adapter, "api_key") and not hasattr(adapter, "api_secret")  # Vector B
    assert not (tmp_path / "journal.jsonl").exists() or journal_events(tmp_path / "journal.jsonl") == []


def test_reconciliation_never_queries_the_venue_outside_live_authorization(tmp_path):
    venue = FakeVenue([TimeoutError("lost")], query={"status": "FILLED", "executedQty": "1"})
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    assert buy(m, "atl-1")["status"] == "PENDING_RECONCILIATION"
    m.safety_gate = ExecutionSafetyGate(mode="PAPER")
    assert m.reconcile_order("atl-1")["status"] == "PENDING_RECONCILIATION"
    assert venue.queries == []
    m.safety_gate = ExecutionSafetyGate(mode="LIVE", live_enabled=True)
    assert m.reconcile_order("atl-1")["status"] == "FILLED" and venue.queries == ["atl-1"]


# -- 3.2 lifecycle journal, partial fills and disconnect reconciliation -------------------------


def test_a_partial_fill_survives_a_disconnect_and_reconciles_to_the_exact_quantity(tmp_path):
    path = tmp_path / "journal.jsonl"
    reports: list[Any] = [ConnectionError("socket dropped"),
                          {"status": "PARTIALLY_FILLED", "executedQty": "0.70000000", "cummulativeQuoteQty": "700"},
                          {"status": "FILLED", "executedQty": "1.00000000", "cummulativeQuoteQty": "1001"}]

    def query(client_order_id):
        report = reports.pop(0)
        if isinstance(report, BaseException):
            raise report
        return dict(report)

    venue = FakeVenue([{"status": "PARTIALLY_FILLED", "executedQty": "0.40000000", "cummulativeQuoteQty": "400"}],
                      query=query)
    m = manager(venue, order_journal_path=path)
    first = buy(m, "atl-p")
    assert first["status"] == "PENDING_RECONCILIATION"
    assert (first["order_state"], first["filled_quantity"]) == ("PARTIALLY_FILLED", "0.40000000")
    assert m.filled_positions() == {"BTCUSDT": "0.40000000"}
    assert list(m.exposure_guard.reservations()) == ["atl-p"]  # the open order still holds its notional

    # a new order on the pair is frozen while the venue status is not authoritative
    blocked = buy(m, "atl-q")
    assert blocked["reason"] == "HALT_VENUE_PAIR" and venue.dispatched == ["atl-p"]
    assert m.order_state("atl-p")["filled_quantity"] == "0.40000000"  # the disconnect changed nothing

    progressed = m.reconcile_order("atl-p")
    assert progressed["status"] == "PENDING_RECONCILIATION" and progressed["filled_quantity"] == "0.70000000"
    assert m.filled_positions() == {"BTCUSDT": "0.70000000"}

    # a restart in the middle rebuilds the exact progress, the pending order and its reservation
    restarted = manager(venue, order_journal_path=path)
    assert restarted.order_state("atl-p")["filled_quantity"] == "0.70000000"
    assert restarted.filled_positions() == {"BTCUSDT": "0.70000000"}
    assert list(restarted.exposure_guard.reservations()) == ["atl-p"]

    final = restarted.reconcile_order("atl-p")
    assert final["status"] == "FILLED" and restarted.filled_positions() == {"BTCUSDT": "1.00000000"}
    assert restarted.order_state("atl-p")["state"] == "FILLED"
    assert restarted.exposure_guard.reservations() == {}
    assert venue.dispatched == ["atl-p"]  # Vector A: reconnects and restarts never resend
    events = [event for event, key in journal_events(path) if key == "atl-p"]
    assert events == ["INTENT_CREATED", "DISPATCHED", "VENUE_ACK", "FILL", "FILL", "TERMINAL"]
    fills = [json.loads(line) for line in path.read_text().splitlines()[1:] if '"FILL"' in line]
    assert [f["filled_quantity"] for f in fills] == ["0.40000000", "0.70000000"]


@pytest.mark.parametrize("report, reason", [
    ({"status": "PARTIALLY_FILLED", "executedQty": "1.5"}, "FILL_EXCEEDS_ORDER"),
    ({"status": "FILLED", "executedQty": "0.9"}, "FILLED_QUANTITY_MISMATCH"),
    ({"status": "CANCELED", "executedQty": "0.2"}, "FILL_REGRESSED"),
    ({"status": "PARTIALLY_FILLED", "executedQty": "NaN"}, "FILL_REPORT_MALFORMED"),
    ({"status": "FILLED", "executedQty": "-1"}, "FILL_REPORT_MALFORMED"),
])
def test_an_inconsistent_fill_report_is_never_folded_in(report, reason, tmp_path):
    """Vector C: drift-free. A bad report leaves the order unreconciled and its pair frozen."""
    path = tmp_path / "j.jsonl"
    venue = FakeVenue([{"status": "PARTIALLY_FILLED", "executedQty": "0.5"}], query=report)
    m = manager(venue, order_journal_path=path)
    buy(m, "atl-x")
    assert m.reconcile_order("atl-x")["status"] == "PENDING_RECONCILIATION"
    assert m.filled_positions() == {"BTCUSDT": "0.5"} and m.order_state("atl-x")["state"] == "UNKNOWN"
    recorded = [json.loads(line) for line in path.read_text().splitlines()[1:]]
    assert recorded[-1]["event"] == "UNRECONCILED" and recorded[-1]["reason"] == reason
    assert buy(m, "atl-y")["reason"] == "HALT_VENUE_PAIR"


def test_a_stale_lower_report_never_reduces_recorded_fills(tmp_path):
    venue = FakeVenue([{"status": "PARTIALLY_FILLED", "executedQty": "0.6"}],
                      query={"status": "PARTIALLY_FILLED", "executedQty": "0.3"})
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    buy(m, "atl-s")
    assert m.reconcile_order("atl-s")["filled_quantity"] == "0.6"
    assert m.filled_positions() == {"BTCUSDT": "0.6"}


def test_a_cancelled_partial_fill_keeps_its_filled_part_and_releases_the_rest(tmp_path):
    venue = FakeVenue([{"status": "PARTIALLY_FILLED", "executedQty": "0.25"}],
                      query={"status": "CANCELED", "executedQty": "0.25"})
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    buy(m, "atl-c")
    assert m.reconcile_order("atl-c")["status"] == "CANCELED"
    assert m.order_state("atl-c")["state"] == "CANCELLED"
    assert m.filled_positions() == {"BTCUSDT": "0.25"} and m.exposure_guard.reservations() == {}


def test_sell_fills_reduce_the_net_filled_position(tmp_path):
    venue = FakeVenue([{"status": "FILLED", "executedQty": "1"}, {"status": "FILLED", "executedQty": "0.4"}])
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    buy(m, "atl-b")
    m.place_order("BTCUSDT", "SELL", 0.4, idempotency_key="atl-s", order_notional=400.0, opens_new_position=False)
    assert m.filled_positions() == {"BTCUSDT": "0.6"}


# -- 3.3 terminal rejection releases the local balance lock --------------------------------------


def test_insufficient_funds_is_terminal_and_releases_the_reservation(tmp_path):
    venue = FakeVenue([VenueRejectedError("Account has insufficient balance", http_status=400, venue_code=-2010)])
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    result = buy(m, "atl-r", notional=2_000.0)
    assert result["reason"] == "PERMANENTLY_REJECTED" and result["venue_code"] == -2010
    assert m.order_state("atl-r")["state"] == "REJECTED"
    assert m.exposure_guard.reservations() == {}
    assert buy(m, "atl-r", notional=2_000.0)["reason"] == "PERMANENTLY_REJECTED" and venue.dispatched == ["atl-r"]


@pytest.mark.parametrize("outcome", [TimeoutError("lost"), ConnectionError("dropped"),
                                     {"status": "NEW", "executedQty": "0"}])
def test_an_order_of_unknown_outcome_keeps_its_reservation(outcome, tmp_path):
    m = manager(FakeVenue([outcome]), order_journal_path=tmp_path / "j.jsonl")
    buy(m, "atl-u")
    assert list(m.exposure_guard.reservations()) == ["atl-u"]


def test_open_buys_count_against_each_other_under_concurrency(tmp_path):
    """Headroom: total exposure 7000 and a 2000 cash floor on 10000; each BUY reserves 2000."""
    venue = FakeVenue([TimeoutError("lost")] * 16)
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    barrier = threading.Barrier(8)
    results: dict[int, dict[str, Any]] = {}

    def submit(i):
        barrier.wait()
        results[i] = buy(m, f"atl-c{i}", symbol=f"C{i}USDT", notional=2_000.0)

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert len(venue.dispatched) == 3 and len(m.exposure_guard.reservations()) == 3
    refused = [r["reason"] for r in results.values() if r["status"] == "REJECTED"]
    assert len(refused) == 5 and set(refused) == {"MAX_TOTAL_EXPOSURE_EXCEEDED"}


def test_an_exposure_guard_without_reservations_refuses_buys_but_not_sells(tmp_path):
    class LegacyGuard:
        def authorize_order(self, **kw):
            return {"allowed": True, "reason": "OK"}

        def status(self):
            return {}

    venue = FakeVenue()
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    m.exposure_guard = LegacyGuard()
    assert buy(m, "atl-l")["reason"] == "EXPOSURE_RESERVATION_UNAVAILABLE"
    sold = m.place_order("BTCUSDT", "SELL", 0.1, idempotency_key="atl-m", order_notional=100.0,
                         opens_new_position=False)
    assert sold["status"] == "FILLED" and venue.dispatched == ["atl-m"]


# -- 3.3 market-data stall: the feed recovers, BUYs freeze on stale data, exits route -------------


def test_three_feed_failures_no_longer_latch_the_market_data_path():
    from exchange.market_feed import MarketFeed
    from tests.phase6.test_market_feed_compatibility import FakeProvider

    class Flaky(FakeProvider):
        failures = 3

        def get_candles(self, symbol, timeframe="5m", limit=100):
            if Flaky.failures > 0:
                Flaky.failures -= 1
                raise ConnectionError("stream stalled")
            return super().get_candles(symbol, timeframe, limit)

    feed = MarketFeed(provider=Flaky(), publish_events=False, collect_metrics=False)
    feed.start()
    for _ in range(3):
        with pytest.raises(Exception):
            feed.candles("BTCUSDT", "1m", 50)
    assert feed.service.state.value == "DEGRADED"
    assert len(feed.candles("BTCUSDT", "1m", 50)) == 50  # served while degraded, and it recovers
    assert feed.service.state.value == "RUNNING" and feed.service.consecutive_failures == 0
    feed.stop()
    with pytest.raises(Exception, match="must be running"):
        feed.candles("BTCUSDT", "1m", 50)  # a stopped feed still refuses


def test_stale_market_data_freezes_new_buys(flat_app, monkeypatch):
    buys = _spy_execute(flat_app, monkeypatch)
    loop = execution_enabled_loop(flat_app, "BUY")
    _age_clock(loop, 600)
    assert loop.process_symbol("BTCUSDT")["reason"] == "STALE_MARKET_DATA" and buys == []


def test_stale_market_data_never_blocks_an_exit(holding_app, monkeypatch):
    sells = _spy_execute(holding_app, monkeypatch)
    exit_loop = execution_enabled_loop(holding_app, "SELL")
    _age_clock(exit_loop, 3600)
    assert exit_loop.process_symbol("BTCUSDT")["status"] == "PAPER_EXECUTED" and len(sells) == 1


# -- 4 concurrent journal stress ------------------------------------------------------------------


def test_concurrent_submissions_keep_the_journal_sequential_and_complete(tmp_path):
    path = tmp_path / "journal.jsonl"
    venue = FakeVenue()
    m = manager(venue, order_journal_path=path)
    m.exposure_guard = exposure_guard()
    barrier = threading.Barrier(24)

    def submit(i):
        barrier.wait()
        side = "BUY" if i % 2 == 0 else "SELL"
        m.place_order(f"S{(i // 2) % 6}USDT", side, 0.01, idempotency_key=f"atl-j{i}", order_notional=10.0,
                      opens_new_position=False)

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    DurableAppendLog(path, log_name="exchange_order_journal", version=1).read()  # verifies the whole file
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[1:]]
    assert [r["sequence"] for r in records] == list(range(len(records)))  # strictly sequential, uncorrupted
    by_key: dict[str, list[str]] = {}
    for record in records:
        by_key.setdefault(record["client_order_id"], []).append(record["event"])
    assert len(by_key) == 24 and all(events == ["INTENT_CREATED", "DISPATCHED", "TERMINAL"]
                                     for events in by_key.values())
    assert len(venue.dispatched) == 24 and m.exposure_guard.reservations() == {}
    reloaded = manager(venue, order_journal_path=path)
    assert reloaded.filled_positions() == m.filled_positions()
    assert len(m.filled_positions()) == 6 and all(Decimal(a) == 0 for a in m.filled_positions().values())  # 2 BUYs and 2 SELLs per symbol


def test_a_fill_report_on_dispatch_is_checked_before_it_is_journaled(tmp_path):
    """The placement path refuses an inconsistent report exactly like reconciliation does."""
    path = tmp_path / "j.jsonl"
    m = manager(FakeVenue([{"status": "FILLED", "executedQty": "0.9"}]), order_journal_path=path)
    assert buy(m, "atl-f")["status"] == "PENDING_RECONCILIATION"
    assert m.filled_positions() == {} and m.order_state("atl-f")["state"] == "UNKNOWN"
    assert journal_events(path)[-1] == ("UNRECONCILED", "atl-f")


def test_fill_events_journaled_out_of_order_never_reduce_progress(tmp_path):
    """Two racing reconcilers can journal 0.7 then 0.6; replaying the journal keeps 0.7."""
    path = tmp_path / "j.jsonl"
    m = manager(FakeVenue([{"status": "PARTIALLY_FILLED", "executedQty": "0.7"}]), order_journal_path=path)
    buy(m, "atl-o")
    m._journal("FILL", "atl-o", filled_quantity="0.6", filled_quote=None, order_state="PARTIALLY_FILLED")
    assert m.order_state("atl-o")["filled_quantity"] == "0.7"
    assert manager(FakeVenue(), order_journal_path=path).filled_positions() == {"BTCUSDT": "0.7"}


# -- the exposure guard's reservations, one limit at a time ---------------------------------------


def guard_with(**limits):
    from exchange.execution_exposure_guard import ExecutionExposureGuard

    settings = dict(portfolio_equity=10_000.0, max_order_notional=2_000.0, max_symbol_exposure=3_000.0,
                    max_total_exposure=10_000.0, max_open_positions=5, minimum_cash_reserve=0.0)
    settings.update(limits)
    guard = ExecutionExposureGuard(**settings)
    assert guard.update_portfolio(cash=10_000.0, total_exposure=0.0, symbol_exposures={},
                                  open_positions=0)["accepted"] is True
    return guard


def reserve(guard, key, symbol="BTCUSDT", notional=1_500.0, opens=False):
    return guard.reserve(key, symbol=symbol, order_notional=notional, opens_new_position=opens)


def test_reservations_count_toward_the_symbol_limit():
    guard = guard_with()
    assert reserve(guard, "a")["allowed"] and reserve(guard, "b")["allowed"]
    assert reserve(guard, "c", notional=100.0)["reason"] == "MAX_SYMBOL_EXPOSURE_EXCEEDED"
    assert reserve(guard, "d", symbol="ETHUSDT")["allowed"]  # another symbol is unaffected


def test_reservations_count_toward_the_total_limit():
    guard = guard_with(max_total_exposure=3_000.0)
    assert reserve(guard, "a", symbol="AUSDT")["allowed"] and reserve(guard, "b", symbol="BUSDT")["allowed"]
    assert reserve(guard, "c", symbol="CUSDT", notional=100.0)["reason"] == "MAX_TOTAL_EXPOSURE_EXCEEDED"


def test_reservations_count_toward_the_cash_floor():
    guard = guard_with(minimum_cash_reserve=7_000.0)
    assert reserve(guard, "a", symbol="AUSDT")["allowed"] and reserve(guard, "b", symbol="BUSDT")["allowed"]
    assert reserve(guard, "c", symbol="CUSDT", notional=100.0)["reason"] == "MINIMUM_CASH_RESERVE_VIOLATION"


def test_opening_reservations_count_toward_the_position_limit():
    guard = guard_with(max_open_positions=2)
    assert reserve(guard, "a", symbol="AUSDT", opens=True)["allowed"]
    assert reserve(guard, "b", symbol="BUSDT", opens=True)["allowed"]
    assert reserve(guard, "c", symbol="CUSDT", opens=True)["reason"] == "MAX_OPEN_POSITIONS_REACHED"
    assert reserve(guard, "d", symbol="DUSDT", opens=False)["allowed"]


def test_a_release_restores_headroom_and_a_snapshot_keeps_open_reservations():
    guard = guard_with(max_total_exposure=3_000.0)
    reserve(guard, "a", symbol="AUSDT")
    reserve(guard, "b", symbol="BUSDT")
    assert reserve(guard, "a")["reason"] == "RESERVATION_HELD"  # idempotent per client order id
    guard.update_portfolio(cash=10_000.0, total_exposure=0.0, symbol_exposures={}, open_positions=0)
    assert reserve(guard, "c", symbol="CUSDT", notional=100.0)["allowed"] is False
    assert guard.release("a") is True and guard.release("a") is False
    assert reserve(guard, "c", symbol="CUSDT", notional=100.0)["allowed"] is True
    guard.restore_reservation("r", symbol="RUSDT", order_notional=1_400.0, opens_new_position=False)
    assert reserve(guard, "e", symbol="EUSDT", notional=100.0)["allowed"] is False
    with pytest.raises(ValueError):
        guard.restore_reservation("bad", symbol="", order_notional=1.0, opens_new_position=False)


def test_an_order_dropped_because_the_journal_failed_releases_its_reservation(tmp_path):
    venue = FakeVenue()
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    append = m._order_journal.append

    def failing_append(payloads):
        if payloads[0]["event"] == "DISPATCHED":
            raise OSError("disk full")
        return append(payloads)

    m._order_journal.append = failing_append
    assert buy(m, "atl-d")["reason"] == "ORDER_JOURNAL_UNAVAILABLE"
    assert venue.dispatched == [] and m.exposure_guard.reservations() == {}


# -- review 20 ----------------------------------------------------------------------------------------


def positions(m):
    return {symbol: Decimal(amount) for symbol, amount in m.filled_positions().items()}


def partially_filled(tmp_path, query):
    path = tmp_path / "j.jsonl"
    venue = FakeVenue([{"status": "PARTIALLY_FILLED", "executedQty": "0.4"}], query=query)
    m = manager(venue, order_journal_path=path)
    buy(m, "atl-k")
    return m, venue, path


def test_progress_is_never_journaled_after_the_outcome(tmp_path):
    """F-1: a racing reconciler's FILL or UNRECONCILED after TERMINAL is refused, live and on replay."""
    m, venue, path = partially_filled(tmp_path, {"status": "FILLED", "executedQty": "1"})
    assert m.reconcile_order("atl-k")["status"] == "FILLED"
    lines = len(path.read_text().splitlines())
    m._record_fill_progress("atl-k", {"status": "PARTIALLY_FILLED", "executedQty": "0.7"})
    m._journal_unreconciled_while_pending("atl-k", "FILL_REGRESSED", {"status": "CANCELED"})
    m._journal("FILL", "atl-k", filled_quantity="0.7", filled_quote=None, order_state="PARTIALLY_FILLED")
    m._journal_quiet("UNRECONCILED", "atl-k", reason="LATE")
    m._journal_quiet("VENUE_ACK", "atl-k", response={"status": "NEW"})
    assert len(path.read_text().splitlines()) == lines
    m._order_journal.append([{"event": "FILL", "client_order_id": "atl-k", "filled_quantity": "0.7",
                              "recorded_at": 0.0}])  # an older build could have written one
    restarted = manager(FakeVenue(), order_journal_path=path)
    assert restarted.order_state("atl-k")["state"] == "FILLED"
    assert restarted.exposure_guard.reservations() == {} and positions(restarted) == {"BTCUSDT": 1}
    assert buy(restarted, "atl-n")["status"] == "FILLED"  # the pair is not frozen by a phantom


def test_concurrent_reconcilers_never_leave_a_finished_order_open(tmp_path):
    """F-1: 16 reconcilers racing on one partially filled order, then a restart, many times over."""
    for trial in range(25):
        calls = {"n": 0}
        lock = threading.Lock()

        def query(client_order_id):
            with lock:
                calls["n"] += 1
                n = calls["n"]
            return ({"status": "FILLED", "executedQty": "1"} if n % 3 == 0
                    else {"status": "PARTIALLY_FILLED", "executedQty": "0.7"} if n % 3 == 1
                    else {"status": "CANCELED", "executedQty": "0.2"})

        m, venue, path = partially_filled(tmp_path / str(trial), query)
        barrier = threading.Barrier(16)

        def reconcile():
            barrier.wait()
            m.reconcile_order("atl-k")

        threads = [threading.Thread(target=reconcile) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        if m.order_state("atl-k")["state"] != "FILLED":
            continue  # every reconciler saw a non-terminal or inconsistent report this time
        restarted = manager(FakeVenue(), order_journal_path=path)
        assert restarted.order_state("atl-k")["state"] == "FILLED", trial
        assert restarted.exposure_guard.reservations() == {}, trial
        assert positions(restarted) == positions(m) == {"BTCUSDT": 1}, trial
        assert venue.dispatched == ["atl-k"]


def test_public_market_data_never_carries_credentials(monkeypatch):
    """F-2: only an order query, which ExchangeManager makes under live authorization, is signed."""
    import exchange.adapters.binance_global as adapter_module

    configured: list[Any] = []

    class FakeRest:
        def time(self):
            return type("R", (), {"data": lambda self: {}})()

        def get_order(self, **kw):
            return type("R", (), {"data": lambda self: {"status": "NEW"}})()

    monkeypatch.setattr(adapter_module, "ConfigurationRestAPI", lambda **kw: configured.append(kw) or kw)
    monkeypatch.setattr(adapter_module, "Spot", lambda config_rest_api: type("S", (), {"rest_api": FakeRest()})())
    monkeypatch.setenv("BINANCE_API_KEY", "k" * 64)
    monkeypatch.setenv("BINANCE_API_SECRET", "s" * 64)
    adapter = BinanceGlobalExchange()
    assert adapter.connect() is True
    assert configured == [{"api_key": None, "api_secret": None}]
    adapter.get_order_by_client_id("BTCUSDT", "atl-" + "a" * 32)
    assert configured[-1] == {"api_key": "k" * 64, "api_secret": "s" * 64}


def test_an_order_dropped_before_dispatch_leaves_no_open_ledger_entry(tmp_path):
    """F-3."""
    path = tmp_path / "j.jsonl"
    m = manager(FakeVenue(), order_journal_path=path)
    append = m._order_journal.append
    m._order_journal.append = lambda payloads: (_ for _ in ()).throw(OSError("full")) \
        if payloads[0]["event"] == "DISPATCHED" else append(payloads)
    buy(m, "atl-z")
    assert m.order_state("atl-z") is None and m.status()["order_fills"]["open_orders"] == 0
    restarted = manager(FakeVenue(), order_journal_path=path)
    assert restarted.order_state("atl-z") is None and restarted.status()["order_fills"]["open_orders"] == 0


def test_a_failed_reservation_restore_refuses_buys_but_not_sells(tmp_path):
    """F-4."""
    path = tmp_path / "j.jsonl"
    buy(manager(FakeVenue([TimeoutError("lost")]), order_journal_path=path), "atl-t")

    def broken(*a, **kw):
        raise RuntimeError("guard unavailable")

    original = exposure_guard
    import tests.exchange.test_task008_safety_idempotency as helpers

    def failing_guard():
        guard = original()
        guard.restore_reservation = broken
        return guard

    helpers_guard = helpers.exposure_guard
    helpers.exposure_guard = failing_guard
    try:
        venue = FakeVenue()
        m = manager(venue, order_journal_path=path)
    finally:
        helpers.exposure_guard = helpers_guard
    assert m.status()["order_fills"]["reservations_restored"] is False
    assert buy(m, "atl-b", symbol="ETHUSDT")["reason"] == "EXPOSURE_RESERVATION_UNAVAILABLE"
    sold = m.place_order("ETHUSDT", "SELL", 0.1, idempotency_key="atl-s", order_notional=100.0,
                         opens_new_position=False)
    assert sold["status"] == "FILLED"


def test_fills_and_reservations_work_without_an_order_journal():
    """F-4: journal-absent mode tracks fills and releases reservations too."""
    m = manager(FakeVenue([{"status": "PARTIALLY_FILLED", "executedQty": "0.3"}],
                          query={"status": "FILLED", "executedQty": "1"}))
    buy(m, "atl-w")
    assert positions(m) == {"BTCUSDT": Decimal("0.3")} and list(m.exposure_guard.reservations()) == ["atl-w"]
    assert m.reconcile_order("atl-w")["status"] == "FILLED"
    assert positions(m) == {"BTCUSDT": 1} and m.exposure_guard.reservations() == {}


def test_a_reservation_check_and_hold_are_atomic(monkeypatch):
    """F-4: a pause between the check and the hold cannot let two orders through."""
    import time

    guard = guard_with(max_total_exposure=3_000.0)
    check = guard._authorize

    def slow(**kw):
        decision = check(**kw)
        time.sleep(0.05)
        return decision

    monkeypatch.setattr(guard, "_authorize", slow)
    results: list[dict[str, Any]] = []
    barrier = threading.Barrier(2)

    def take(symbol):
        barrier.wait()
        results.append(reserve(guard, symbol, symbol=symbol, notional=2_000.0))

    threads = [threading.Thread(target=take, args=(s,)) for s in ("AUSDT", "BUSDT")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert sorted(r["allowed"] for r in results) == [False, True]


def test_an_order_the_adapter_never_sent_reads_as_denied(tmp_path):
    """F-5: PAPER_ONLY maps to a core.order_lifecycle state."""
    m = manager(FakeVenue([{"status": "PAPER_ONLY"}]), order_journal_path=tmp_path / "j.jsonl")
    buy(m, "atl-po")
    assert m.order_state("atl-po")["state"] == "DENIED"
    from core.order_lifecycle import STATES
    assert m.order_state("atl-po")["state"] in STATES


def test_a_success_racing_a_degrade_never_raises_and_recovers_later():
    """F-6: the degrade flag set before the state changes, then the state changed after the flag cleared."""
    from exchange.market_feed import MarketFeed
    from tests.phase6.test_market_feed_compatibility import FakeProvider

    feed = MarketFeed(provider=FakeProvider(), publish_events=False, collect_metrics=False)
    feed.start()
    service = feed.service
    service._degradation_active = True  # a failing request set the flag but has not marked DEGRADED yet
    assert len(feed.candles("BTCUSDT", "1m", 10)) == 10 and service.state.value == "RUNNING"
    service.mark_degraded("the racing failure finishes")  # flag already cleared by the success above
    assert len(feed.candles("BTCUSDT", "1m", 10)) == 10 and service.state.value == "RUNNING"


def test_an_unmapped_outcome_reads_as_unknown_never_a_raw_venue_status(tmp_path):
    """F-5: order_state only ever reports core.order_lifecycle states."""
    from core.order_lifecycle import STATES

    m = manager(FakeVenue(), order_journal_path=tmp_path / "j.jsonl")
    m._idempotency_cache["atl-e"] = {"response": {"status": "PENDING_NEW"}}
    assert m.order_state("atl-e")["state"] == "UNKNOWN" and "UNKNOWN" in STATES


# -- review 21 ----------------------------------------------------------------------------------------


def test_public_calls_after_an_order_query_stay_keyless(monkeypatch):
    """L-1: the signed client exists only for the query and is never kept."""
    import exchange.adapters.binance_global as adapter_module

    class FakeRest:
        def time(self):
            return type("R", (), {"data": lambda self: {}})()

        def get_order(self, **kw):
            return type("R", (), {"data": lambda self: {"status": "NEW"}})()

    monkeypatch.setattr(adapter_module, "ConfigurationRestAPI", lambda **kw: kw)
    monkeypatch.setattr(adapter_module, "Spot",
                        lambda config_rest_api: type("S", (), {"rest_api": FakeRest(), "cfg": config_rest_api})())
    monkeypatch.setenv("BINANCE_API_KEY", "k" * 64)
    monkeypatch.setenv("BINANCE_API_SECRET", "s" * 64)
    adapter = BinanceGlobalExchange()
    adapter.connect()
    adapter.get_order_by_client_id("BTCUSDT", "atl-" + "a" * 32)
    adapter.get_order_by_client_id("BTCUSDT", "atl-" + "b" * 32)
    assert adapter.client.cfg == {"api_key": None, "api_secret": None} and adapter._keyless_client is True


def test_an_order_proven_never_sent_releases_its_reservation_after_a_restart(tmp_path):
    """L-2: rate limited (never processed), its pending entry survives a failed discard and a restart."""
    from exchange.base_exchange import VenueRateLimitedError

    journal, store = tmp_path / "j.jsonl", tmp_path / "pending.json"
    first = manager(FakeVenue([VenueRateLimitedError("429", http_status=429)] * 3),
                    order_journal_path=journal, idempotency_store_path=store)
    first._discard_pending_reconciliation = lambda *, key: False  # the discard's persistence fails once
    buy(first, "atl-rl", notional=1_500.0)
    restarted = manager(FakeVenue(), order_journal_path=journal, idempotency_store_path=store)
    assert list(restarted.exposure_guard.reservations()) == ["atl-rl"]
    assert restarted.reconcile_order("atl-rl")["reason"] == "NEVER_DISPATCHED"
    assert restarted.exposure_guard.reservations() == {}
    assert buy(restarted, "atl-ok", notional=2_000.0)["status"] == "FILLED"


def test_degrade_and_recover_are_decided_under_one_lock():
    """L-3: a stale failure never re-degrades, a stale success never clears a newer degradation."""
    from exchange.market_feed import MarketFeed
    from tests.phase6.test_market_feed_compatibility import FakeProvider

    feed = MarketFeed(provider=FakeProvider(), publish_events=False, collect_metrics=False)
    feed.start()
    service = feed.service
    assert service._degrade_if_still_failing("stale streak") is False  # a success cleared the flag
    assert service.state.value == "RUNNING"
    service._degradation_active = True
    assert service._degrade_if_still_failing("current streak") is True and service.state.value == "DEGRADED"
    assert service._degrade_if_still_failing("again") is False  # already DEGRADED: never raises
    assert service._recover_if_degraded() is False and service.state.value == "DEGRADED"  # a newer streak owns it
    service._degradation_active = False
    assert service._recover_if_degraded() is True and service.state.value == "RUNNING"
    for _ in range(3):  # a fresh streak degrades again
        service._record_failure(request_type="candles", symbol="BTCUSDT", latency_seconds=0.0,
                                error=ConnectionError("x"), correlation_id=None)
    assert service.state.value == "DEGRADED"


def test_an_inconsistent_report_returns_an_outcome_resolved_meanwhile(tmp_path):
    """L-5 (M27): the anomaly path hands back the concurrently resolved outcome, not a stale pending."""
    holder: dict[str, Any] = {}
    calls = {"n": 0}

    def query(client_order_id):
        calls["n"] += 1
        if calls["n"] == 1:
            assert holder["m"].reconcile_order(client_order_id)["status"] == "FILLED"  # resolves meanwhile
            return {"status": "PARTIALLY_FILLED", "executedQty": "NaN"}  # then a malformed report arrives
        return {"status": "FILLED", "executedQty": "1"}

    m, venue, path = partially_filled(tmp_path, query)
    holder["m"] = m
    assert m.reconcile_order("atl-k")["status"] == "FILLED"
    assert [e for e, k in journal_events(path) if k == "atl-k"][-1] == "TERMINAL"


def test_a_replayed_overfill_is_never_applied(tmp_path):
    """L-5 (M09): the ledger's own overfill guard holds on replay of a corrupt FILL."""
    m, venue, path = partially_filled(tmp_path, None)
    m._order_journal.append([{"event": "FILL", "client_order_id": "atl-k", "filled_quantity": "1.5",
                              "recorded_at": 0.0}])
    assert positions(manager(FakeVenue(), order_journal_path=path)) == {"BTCUSDT": Decimal("0.4")}
