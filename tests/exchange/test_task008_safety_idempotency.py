"""Task 008: exchange adapter safety, idempotency and order journal (registry v5.92 grant).

Real order submission stays disabled in the Binance adapters; every test drives
ExchangeManager through fake adapters. Covered: exactly one dispatch under a
100-thread burst, reconciliation before the next order of a pair (and the pair
halt when it stays ambiguous), unresolved orders that never expire, the venue
error taxonomy (rate limit retried under the same id with full jitter, unknown
outcome reconciled, terminal rejection cached), the durable order journal, the
24-hour venue precision gate and the deterministic client order id.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from core.instrument_rules import InstrumentRules, InstrumentRuleset
from core.venue_rule_freshness import VenueRuleFreshnessPolicy, VenueRuleFreshnessService
import exchange.exchange_manager as exchange_manager_module
from exchange.adapters.binance_global import BinanceGlobalExchange
from exchange.base_exchange import (
    CLIENT_ORDER_ID_PATTERN,
    VenueError,
    VenueOutcomeUnknownError,
    VenueRateLimitedError,
    VenueRejectedError,
    classify_venue_failure,
    derive_client_order_id,
)
from exchange.execution_exposure_guard import ExecutionExposureGuard
from exchange.execution_risk_guard import ExecutionRiskGuard
from exchange.execution_safety_gate import ExecutionSafetyGate
from exchange.exchange_manager import ExchangeManager
from exchange.persistent_idempotency_store import PersistentIdempotencyStore

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


class FakeVenue:
    """Counts every dispatch; scripted outcomes per call."""

    def __init__(self, outcomes: list[Any] | None = None, *, query: Any = None, delay: threading.Event | None = None):
        self.outcomes = list(outcomes or [])
        self.query = query
        self.delay = delay
        self.dispatched: list[str | None] = []
        self.queries: list[str] = []
        self.lock = threading.Lock()

    def place_order(self, symbol: str, side: str, quantity: float, *, client_order_id: str | None = None):
        with self.lock:
            self.dispatched.append(client_order_id)
            outcome = self.outcomes.pop(0) if self.outcomes else None
        if self.delay is not None:
            self.delay.wait(5)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, dict):
            return dict(outcome)
        return {"status": "FILLED", "order_id": f"fill-{client_order_id}", "client_order_id": client_order_id,
                "symbol": symbol, "side": side, "quantity": quantity}

    def get_order_by_client_id(self, symbol: str, client_order_id: str):
        self.queries.append(client_order_id)
        if isinstance(self.query, BaseException):
            raise self.query
        if callable(self.query):
            return self.query(client_order_id)
        return dict(self.query) if isinstance(self.query, dict) else {"status": "UNKNOWN"}


def exposure_guard() -> ExecutionExposureGuard:
    guard = ExecutionExposureGuard(portfolio_equity=10_000.0, max_order_notional=2_000.0,
                                   max_symbol_exposure=3_000.0, max_total_exposure=7_000.0,
                                   max_open_positions=5, minimum_cash_reserve=2_000.0)
    assert guard.update_portfolio(cash=10_000.0, total_exposure=0.0, symbol_exposures={},
                                  open_positions=0)["accepted"] is True
    return guard


def manager(venue: FakeVenue, **kw) -> ExchangeManager:
    kw.setdefault("sleep_provider", lambda seconds: None)
    return ExchangeManager(
        exchange_name="test", exchange=venue,
        safety_gate=ExecutionSafetyGate(mode="LIVE", live_enabled=True),
        risk_guard=ExecutionRiskGuard(starting_equity=10_000.0, max_daily_loss_percent=5.0,
                                      max_drawdown_percent=10.0),
        exposure_guard=exposure_guard(), **kw)


def order(m: ExchangeManager, key: str, *, symbol: str = "BTCUSDT", quantity: float = 0.01,
          notional: float = 500.0, price: Any = None) -> dict[str, Any]:
    return m.place_order(symbol, "BUY", quantity, idempotency_key=key, order_notional=notional,
                         opens_new_position=False, price=price)


def journal_events(path: Path) -> list[tuple[str, str | None]]:
    lines = path.read_text(encoding="utf-8").splitlines()[1:]
    return [(json.loads(line)["event"], json.loads(line)["client_order_id"]) for line in lines]


# -- 3.1 deterministic idempotency -------------------------------------------------------------


def test_one_hundred_simultaneous_identical_submissions_dispatch_exactly_once(tmp_path):
    gate = threading.Event()
    venue = FakeVenue(delay=gate)
    m = manager(venue, idempotency_store_path=tmp_path / "store.json", order_journal_path=tmp_path / "j.jsonl")
    start = threading.Barrier(100)
    results: list[dict[str, Any]] = []

    def submit():
        start.wait()
        results.append(order(m, "atl-burst"))

    threads = [threading.Thread(target=submit) for _ in range(100)]
    for t in threads:
        t.start()
    threading.Timer(0.3, gate.set).start()
    for t in threads:
        t.join(10)
    assert venue.dispatched == ["atl-burst"]  # exactly one network dispatch
    assert len(results) == 100 and all(r["status"] == "FILLED" for r in results)
    assert order(m, "atl-burst")["status"] == "FILLED" and venue.dispatched == ["atl-burst"]  # cached


def test_the_client_order_id_is_deterministic_bounded_and_venue_valid():
    fields = dict(strategy_id="s1", symbol="btcusdt", side="buy", order_type="market",
                  quantity=Decimal("0.00100"), price=None, timestamp_ms=1_700_000_000_000)
    cid = derive_client_order_id(**fields)
    assert cid == derive_client_order_id(**fields) and len(cid) == 36 and CLIENT_ORDER_ID_PATTERN.fullmatch(cid)
    assert cid == derive_client_order_id(**{**fields, "timestamp_ms": 1_700_000_000_000 + 59_999 - 40_000})
    for change in (dict(strategy_id="s2"), dict(symbol="ETHUSDT"), dict(side="SELL"), dict(order_type="LIMIT"),
                   dict(quantity="0.001"), dict(price=Decimal("100.10")), dict(timestamp_ms=1_700_000_060_000)):
        assert derive_client_order_id(**{**fields, **change}) != cid, change  # precision strings matter
    for bad in (dict(quantity=0.001), dict(quantity="0"), dict(timestamp_ms=-1), dict(symbol="a|b"),
                dict(price=float("nan"))):
        with pytest.raises(ValueError):
            derive_client_order_id(**{**fields, **bad})


def test_the_binance_adapter_refuses_an_order_without_a_valid_client_order_id():
    adapter = BinanceGlobalExchange()
    for cid in (None, "", "x" * 37, "bad id", "naïve"):
        assert adapter.place_order("BTCUSDT", "BUY", 0.001, client_order_id=cid)["reason"] == "INVALID_CLIENT_ORDER_ID"
    assert adapter.place_order("BTCUSDT", "BUY", 0.001, client_order_id="atl-" + "a" * 32)["status"] == "PAPER_ONLY"


# -- 3.2 fail-closed reconciliation ---------------------------------------------------------------


def test_a_timeout_is_reconciled_before_the_next_order_of_the_pair():
    venue = FakeVenue([TimeoutError("response lost")],
                      query={"status": "FILLED", "order_id": "late-fill"})
    m = manager(venue)
    assert order(m, "atl-first")["status"] == "PENDING_RECONCILIATION"
    second = order(m, "atl-second")
    assert venue.queries == ["atl-first"]  # the venue was asked BEFORE the new order went out
    assert second["status"] == "FILLED" and venue.dispatched == ["atl-first", "atl-second"]
    assert order(m, "atl-first")["order_id"] == "late-fill"  # the reconciled outcome is cached


def test_an_order_that_stays_ambiguous_halts_its_pair_only():
    venue = FakeVenue([ConnectionError("dropped")], query=ConnectionError("still down"))
    m = manager(venue)
    assert order(m, "atl-a")["status"] == "PENDING_RECONCILIATION"
    halted = order(m, "atl-b")
    assert (halted["status"], halted["reason"]) == ("REJECTED", ExecutionSafetyGate.HALT_VENUE_PAIR)
    assert halted["unreconciled_orders"] == 1 and venue.dispatched == ["atl-a"]  # nothing new was sent
    assert m.status()["halted_pairs"] == {"BTCUSDT": "UNRECONCILED_ORDERS"}
    assert order(m, "atl-c", symbol="ETHUSDT")["status"] == "FILLED"  # other pairs keep trading
    venue.query = {"status": "CANCELED"}
    assert order(m, "atl-d")["status"] == "FILLED" and m.status()["halted_pairs"] == {}


def test_an_unresolved_order_never_expires_and_is_never_evicted(tmp_path):
    clock = {"mono": 0.0, "wall": 1_000_000.0}
    venue = FakeVenue([TimeoutError("lost")])
    kw = dict(idempotency_store_path=tmp_path / "store.json", idempotency_ttl_seconds=60, idempotency_max_entries=2,
              monotonic_provider=lambda: clock["mono"], wall_time_provider=lambda: clock["wall"])
    m = manager(venue, **kw)
    assert order(m, "atl-x")["status"] == "PENDING_RECONCILIATION"
    clock["mono"] += 10_000
    clock["wall"] += 10_000  # far past the TTL
    assert order(m, "atl-x")["status"] == "PENDING_RECONCILIATION" and venue.dispatched == ["atl-x"]
    restarted = manager(FakeVenue(), **kw)  # a restart long after expiry still remembers it
    assert order(restarted, "atl-x")["status"] == "PENDING_RECONCILIATION"
    assert restarted.status()["idempotency"]["pending_reconciliation_entries"] == 1


def test_pending_capacity_refuses_new_orders_instead_of_evicting():
    venue = FakeVenue([TimeoutError("a"), TimeoutError("b")], query=ConnectionError("down"))
    m = manager(venue, idempotency_max_entries=2)
    assert order(m, "atl-1", symbol="BTCUSDT")["status"] == "PENDING_RECONCILIATION"
    assert order(m, "atl-2", symbol="ETHUSDT")["status"] == "PENDING_RECONCILIATION"
    full = order(m, "atl-3", symbol="BNBUSDT")
    assert full["reason"] == "PENDING_RECONCILIATION_CAPACITY_EXHAUSTED" and venue.dispatched == ["atl-1", "atl-2"]
    assert m.status()["idempotency"]["pending_reconciliation_entries"] == 2


def test_the_store_keeps_pending_entries_and_fails_closed_on_a_malformed_one(tmp_path):
    path = tmp_path / "store.json"
    store = PersistentIdempotencyStore(path=path, ttl_seconds=10, max_entries=1, time_provider=lambda: 100.0)
    fp = ["BTCUSDT", "BUY", 0.01, 500.0, False]
    pending = {"state": "PENDING_RECONCILIATION", "fingerprint": fp, "response": {"status": "PENDING_RECONCILIATION"},
               "expires_at": 50.0, "symbol": "BTCUSDT", "client_order_id": "atl-p"}
    assert store.save({"t1": {"state": "TERMINAL", "fingerprint": fp, "response": {"status": "FILLED"},
                              "expires_at": 500.0}, "atl-p": pending, "atl-q": {**pending, "client_order_id": "atl-q"}})
    loaded = store.load()
    assert set(loaded) == {"atl-p", "atl-q"}  # both pending kept past max_entries and past expires_at
    raw = json.loads(path.read_text())
    raw["entries"]["atl-p"].pop("symbol")
    path.write_text(json.dumps(raw))
    assert store.load() == {} and store.available is False  # an unresolved order is never silently dropped


def test_the_store_is_fsynced_before_it_replaces_the_old_file(tmp_path, monkeypatch):
    import exchange.persistent_idempotency_store as module

    synced: list[int] = []
    real_fsync = module.os.fsync
    monkeypatch.setattr(module.os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd))[1])
    store = PersistentIdempotencyStore(path=tmp_path / "s.json", ttl_seconds=10, max_entries=5)
    assert store.save({}) and len(synced) >= 1


# -- 3.4 fault classification --------------------------------------------------------------------


def test_a_rate_limit_is_retried_with_the_same_id_and_full_jitter():
    sleeps: list[float] = []
    venue = FakeVenue([VenueRateLimitedError("429", http_status=429), VenueRateLimitedError("429", http_status=429)])
    m = manager(venue, sleep_provider=sleeps.append, jitter_provider=lambda: 0.5,
                rate_limit_backoff_base_seconds=1.0, rate_limit_backoff_cap_seconds=1.5)
    assert order(m, "atl-rl")["status"] == "FILLED"
    assert venue.dispatched == ["atl-rl"] * 3  # never a new id
    assert sleeps == [0.5, 0.75]  # jitter x min(cap, base x 2^(n-1))


def test_an_exhausted_rate_limit_is_a_definite_failure_and_may_be_retried_later():
    venue = FakeVenue([VenueRateLimitedError("429", http_status=429)] * 3)
    m = manager(venue)
    failed = order(m, "atl-rl")
    assert (failed["status"], failed["reason"]) == ("ERROR", "VENUE_RATE_LIMITED") and len(venue.dispatched) == 3
    assert m.status()["idempotency"]["pending_reconciliation_entries"] == 0
    assert order(m, "atl-rl")["status"] == "FILLED"  # same id, later


def test_a_server_error_is_reconciled_never_resent():
    venue = FakeVenue([VenueOutcomeUnknownError("503", http_status=503)])
    m = manager(venue)
    assert order(m, "atl-5xx")["status"] == "PENDING_RECONCILIATION"
    assert order(m, "atl-5xx")["status"] == "PENDING_RECONCILIATION" and venue.dispatched == ["atl-5xx"]
    unclassified = FakeVenue([VenueError("odd venue reply")])
    assert order(manager(unclassified), "atl-odd")["status"] == "PENDING_RECONCILIATION"


@pytest.mark.parametrize("status, code", [(400, -1013), (401, None), (403, None), (400, -2010)])
def test_a_terminal_rejection_is_permanent_and_cached(status, code):
    error = classify_venue_failure(status, code)("rejected", http_status=status, venue_code=code)
    assert isinstance(error, VenueRejectedError)
    venue = FakeVenue([error])
    m = manager(venue)
    rejected = order(m, "atl-rej")
    assert (rejected["status"], rejected["reason"]) == ("REJECTED", "PERMANENTLY_REJECTED")
    assert (rejected["http_status"], rejected["venue_code"]) == (status, code)
    assert order(m, "atl-rej") == rejected and venue.dispatched == ["atl-rej"]  # never retried


def test_the_failure_classification():
    assert classify_venue_failure(429) is VenueRateLimitedError and classify_venue_failure(418) is VenueRateLimitedError
    for status in (500, 502, 503, 504, None):
        assert classify_venue_failure(status) is VenueOutcomeUnknownError
    assert classify_venue_failure(None, -2010) is VenueRejectedError
    assert issubclass(VenueOutcomeUnknownError, ConnectionError)  # the existing unknown-outcome path


# -- 3.2 the order journal ------------------------------------------------------------------------


def test_the_journal_records_every_milestone_before_its_state(tmp_path):
    path = tmp_path / "journal.jsonl"
    venue = FakeVenue([{"status": "NEW", "order_id": "ack"}])
    m = manager(venue, order_journal_path=path, idempotency_store_path=tmp_path / "s.json")
    assert order(m, "atl-ack")["status"] == "PENDING_RECONCILIATION"
    assert order(m, "atl-fill", symbol="ETHUSDT")["status"] == "FILLED"  # the acked BTC order halts BTCUSDT
    assert journal_events(path) == [("INTENT_CREATED", "atl-ack"), ("DISPATCHED", "atl-ack"), ("VENUE_ACK", "atl-ack"),
                                    ("INTENT_CREATED", "atl-fill"), ("DISPATCHED", "atl-fill"), ("TERMINAL", "atl-fill")]


def test_a_journaled_id_is_never_dispatched_again_even_without_a_store(tmp_path):
    path = tmp_path / "journal.jsonl"
    venue = FakeVenue([TimeoutError("lost")])
    assert order(manager(venue, order_journal_path=path), "atl-j")["status"] == "PENDING_RECONCILIATION"
    restarted_venue = FakeVenue()
    restarted = manager(restarted_venue, order_journal_path=path)  # no idempotency store: only the journal knows
    assert order(restarted, "atl-j")["status"] == "PENDING_RECONCILIATION" and restarted_venue.dispatched == []
    filled_path = tmp_path / "filled.jsonl"
    assert order(manager(FakeVenue(), order_journal_path=filled_path), "atl-f")["status"] == "FILLED"
    again_venue = FakeVenue()
    again = order(manager(again_venue, order_journal_path=filled_path), "atl-f")
    assert again["status"] == "FILLED" and again_venue.dispatched == []  # the journal's terminal result


def test_no_order_is_dispatched_when_the_journal_cannot_record_it(tmp_path, monkeypatch):
    path = tmp_path / "journal.jsonl"
    venue = FakeVenue()
    m = manager(venue, order_journal_path=path)
    monkeypatch.setattr(m._order_journal, "append", lambda payloads: (_ for _ in ()).throw(OSError("disk full")))
    failed = order(m, "atl-nojournal")
    assert (failed["status"], failed["reason"]) == ("ERROR", "ORDER_JOURNAL_UNAVAILABLE") and venue.dispatched == []
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text("not json\n")
    refused = order(manager(FakeVenue(), order_journal_path=corrupt), "atl-c")
    assert refused["reason"] == "ORDER_JOURNAL_UNAVAILABLE"


# -- 3.3 venue precision and freshness ------------------------------------------------------------


def rules(retrieved_at: datetime = NOW - timedelta(hours=1)) -> InstrumentRuleset:
    rule = InstrumentRules(venue="BINANCE", symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
                           quantity_step=Decimal("0.00001"), min_quantity=Decimal("0.00001"),
                           min_notional=Decimal("5"), price_tick=Decimal("0.01"), source="test",
                           source_version="1", retrieved_at=retrieved_at.isoformat())
    return InstrumentRuleset(rules={"BTCUSDT": rule})


def gated(venue: FakeVenue, ruleset: Any) -> ExchangeManager:
    return manager(venue, venue_rules=ruleset,
                   venue_rule_freshness=VenueRuleFreshnessService(
                       VenueRuleFreshnessPolicy(maximum_age_seconds=24 * 3600), clock=lambda: NOW))


@pytest.mark.parametrize("quantity, notional, price, reason", [
    (0.000001, 500.0, None, "QUANTITY_BELOW_VENUE_MINIMUM"),       # sub-step dust
    (0.000015, 500.0, None, "QUANTITY_NOT_ALIGNED_TO_STEP"),       # never rounded up
    (0.01, 4.99, None, "NOTIONAL_BELOW_VENUE_MINIMUM"),
    (0.01, 500.0, "100.005", "PRICE_NOT_ALIGNED_TO_TICK"),
    (0.01, 500.0, "-1", "INVALID_PRICE"),
])
def test_precision_violations_never_reach_the_venue(quantity, notional, price, reason):
    venue = FakeVenue()
    refused = order(gated(venue, rules()), "atl-p", quantity=quantity, notional=notional, price=price)
    assert refused["reason"] == reason and venue.dispatched == []


def test_stale_unknown_or_missing_venue_rules_block_every_order():
    venue = FakeVenue()
    stale = order(gated(venue, rules(NOW - timedelta(hours=25))), "atl-s")
    assert stale["reason"] == "VENUE_RULES_STALE" and stale["maximum_age_seconds"] == 86400
    assert order(gated(venue, rules()), "atl-u", symbol="ETHUSDT")["reason"] == "VENUE_RULES_UNKNOWN_SYMBOL"
    assert order(gated(venue, lambda: None), "atl-n")["reason"] == "VENUE_RULES_STALE"
    assert order(gated(venue, lambda: (_ for _ in ()).throw(OSError("fetch failed"))), "atl-f")["reason"] \
        == "VENUE_RULES_UNAVAILABLE"
    assert venue.dispatched == []
    priced = order(gated(venue, rules()), "atl-px", quantity=0.01, notional=500.0, price="100.01")
    assert priced["reason"] == "LIMIT_ORDERS_NOT_SUPPORTED" and venue.dispatched == []  # review 10 M-2
    fresh = order(gated(venue, rules()), "atl-ok", quantity=0.01, notional=500.0)
    assert fresh["status"] == "FILLED" and venue.dispatched == ["atl-ok"]


def test_status_reports_the_live_prerequisites(tmp_path):
    bare = manager(FakeVenue()).status()
    assert bare["live_prerequisites"] == {"persistent_idempotency_store": False, "order_journal": False,
                                          "venue_rules": False, "met": False}
    full = manager(FakeVenue(), idempotency_store_path=tmp_path / "s.json", order_journal_path=tmp_path / "j.jsonl",
                   venue_rules=rules()).status()
    assert full["live_prerequisites"]["met"] is True and full["venue_precision_gate"]["maximum_rule_age_seconds"] == 86400


# -- review 10 regressions -------------------------------------------------------------------------


def test_concurrent_orders_keep_the_journal_readable(tmp_path):
    """H-1: many threads journaling distinct orders must leave one valid, gap-free sequence."""
    path = tmp_path / "journal.jsonl"
    m = manager(FakeVenue(), order_journal_path=path)
    start = threading.Barrier(8)

    def worker(n):
        start.wait()
        for i in range(25):
            order(m, f"atl-{n}-{i}", symbol=f"T{n}{i:03d}USDT")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    restarted = manager(FakeVenue(), order_journal_path=path)  # a corrupt journal would fail closed here
    assert restarted.status()["order_journal"]["available"] is True
    events = journal_events(path)
    assert sum(1 for e, _ in events if e == "TERMINAL") == 200 and len(events) == 600


def test_the_journal_index_keeps_unfinished_keys_and_bounds_finished_ones(tmp_path):
    """M-1: memory stays bounded; an unresolved key is never dropped from the index."""
    path = tmp_path / "journal.jsonl"
    venue = FakeVenue([TimeoutError("lost")])
    m = manager(venue, order_journal_path=path, idempotency_max_entries=10)
    assert order(m, "atl-open", symbol="ETHUSDT")["status"] == "PENDING_RECONCILIATION"
    for i in range(50):
        order(m, f"atl-done-{i}")
    assert len(m._journal_index) == 11 and "atl-open" in m._journal_index
    restarted = manager(FakeVenue(), order_journal_path=path, idempotency_max_entries=10)
    assert len(restarted._journal_index) == 11 and restarted._journal_index["atl-open"]["event"] == "UNRECONCILED"


@pytest.mark.parametrize("status, code, message", [(400, -2010, "Duplicate order sent."), (400, -1006, None),
                                                    (408, -1007, None), (None, -1006, None)])
def test_unknown_outcome_codes_are_never_terminal(status, code, message):
    """M-3: a venue that already holds the id, or does not know the result, is reconciled."""
    assert classify_venue_failure(status, code, message) is VenueOutcomeUnknownError
    venue = FakeVenue([classify_venue_failure(status, code, message)("x", http_status=status, venue_code=code)])
    assert order(manager(venue), "atl-u")["status"] == "PENDING_RECONCILIATION"
    assert classify_venue_failure(400, -2010, "Account has insufficient balance for requested action.") \
        is VenueRejectedError


def test_extreme_precision_inputs_are_refused_not_raised():
    """L-1."""
    venue = FakeVenue()
    assert order(gated(venue, rules()), "atl-big", quantity=1e24, notional=500.0)["reason"] == "INVALID_QUANTITY"
    assert order(gated(venue, rules()), "atl-bigp", price="1e30")["reason"] == "INVALID_PRICE"
    assert venue.dispatched == []


def test_an_unknown_store_state_fails_closed(tmp_path):
    """L-2."""
    path = tmp_path / "store.json"
    path.write_text(json.dumps({"version": "1.2", "entries": {"atl-x": {
        "state": "PENDING_RECONCILATION", "fingerprint": ["BTCUSDT", "BUY", 0.01, 500.0, False],
        "response": {}, "expires_at": 1e12, "symbol": "BTCUSDT", "client_order_id": "atl-x"}}}))
    store = PersistentIdempotencyStore(path=path, ttl_seconds=10, max_entries=5)
    assert store.load() == {} and store.available is False


def test_an_in_flight_order_does_not_halt_its_pair():
    """L-3: a concurrent order on the same pair is not refused while another is merely in flight."""
    gate = threading.Event()
    venue = FakeVenue(delay=gate)
    m = manager(venue)
    first: list[dict[str, Any]] = []
    t = threading.Thread(target=lambda: first.append(order(m, "atl-slow")))
    t.start()
    while not venue.dispatched:
        threading.Event().wait(0.01)
    second = threading.Thread(target=lambda: first.append(order(m, "atl-fast")))
    second.start()
    threading.Timer(0.2, gate.set).start()
    t.join(5)
    second.join(5)
    assert sorted(r["status"] for r in first) == ["FILLED", "FILLED"] and venue.queries == []


def test_a_journaled_but_never_dispatched_order_is_released(tmp_path):
    """L-3: a crash between the pending record and DISPATCHED leaves an order the venue never saw."""
    kw = dict(order_journal_path=tmp_path / "j.jsonl", idempotency_store_path=tmp_path / "s.json")
    crashed = manager(FakeVenue(), **kw)
    fp = ("BTCUSDT", "BUY", 0.01, 500.0, False)
    crashed._journal("INTENT_CREATED", "atl-crash", symbol="BTCUSDT", fingerprint=fp)
    with crashed._idempotency_lock:
        crashed._record_pending_reconciliation(key="atl-crash", fingerprint=fp, symbol="BTCUSDT", side="BUY",
                                               quantity=0.01)
    venue = FakeVenue(query=ConnectionError("unknown to the venue"))
    restarted = manager(venue, **kw)
    assert order(restarted, "atl-next")["status"] == "FILLED"  # released without a venue query
    assert venue.queries == [] and order(restarted, "atl-crash")["status"] == "FILLED"


# -- review 11 regressions -------------------------------------------------------------------------


def test_failure_paths_do_not_grow_the_journal_index_without_bound(tmp_path):
    """F-1: definite failures and capacity refusals are bounded like finished orders."""
    path = tmp_path / "journal.jsonl"
    failing = FakeVenue([RuntimeError("local failure")] * 60)
    m = manager(failing, order_journal_path=path, idempotency_max_entries=20)
    for i in range(60):  # three times the bound
        assert order(m, f"atl-f{i}")["status"] == "ERROR"
    assert len(m._journal_index) <= 20
    assert len(manager(FakeVenue(), order_journal_path=path, idempotency_max_entries=20)._journal_index) <= 20
    stuck = FakeVenue([TimeoutError("a"), TimeoutError("b")], query=ConnectionError("down"))
    full = manager(stuck, order_journal_path=tmp_path / "cap.jsonl", idempotency_max_entries=2)
    order(full, "atl-1", symbol="BTCUSDT")
    order(full, "atl-2", symbol="ETHUSDT")
    for i in range(50):
        assert order(full, f"atl-r{i}", symbol="BNBUSDT")["reason"] == "PENDING_RECONCILIATION_CAPACITY_EXHAUSTED"
    assert set(full._journal_index) == {"atl-1", "atl-2"}  # a refused order leaves no open journal entry


@pytest.mark.parametrize("outcome, event", [(TimeoutError("lost"), "UNRECONCILED"),
                                            ({"status": "NEW", "order_id": "ack"}, "VENUE_ACK")])
def test_an_order_that_may_be_on_the_venue_is_never_released(tmp_path, outcome, event):
    """F-2: only a provably never-dispatched order is released; anything later is queried and stays pending."""
    kw = dict(order_journal_path=tmp_path / "j.jsonl", idempotency_store_path=tmp_path / "s.json")
    venue = FakeVenue([outcome], query=ConnectionError("venue unreachable"))
    m = manager(venue, **kw)
    assert order(m, "atl-k")["status"] == "PENDING_RECONCILIATION"
    assert m._journal_index["atl-k"]["event"] == event
    assert m.reconcile_order("atl-k")["status"] == "PENDING_RECONCILIATION" and venue.queries == ["atl-k"]
    restarted_venue = FakeVenue(query=ConnectionError("still unreachable"))
    restarted = manager(restarted_venue, **kw)
    assert restarted.reconcile_order("atl-k")["status"] == "PENDING_RECONCILIATION"
    assert order(restarted, "atl-k")["status"] == "PENDING_RECONCILIATION"
    assert venue.dispatched == ["atl-k"] and restarted_venue.dispatched == []  # never sent twice


def test_an_order_in_flight_between_its_intent_and_dispatch_is_never_released(tmp_path):
    """F-2: the leader is paused after INTENT_CREATED and the pending record, before DISPATCHED."""
    venue = FakeVenue()
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    paused, resume = threading.Event(), threading.Event()
    real_journal = m._journal

    def journal(event, key, **fields):
        if event == "DISPATCHED" and key == "atl-p":
            paused.set()
            resume.wait(5)
        return real_journal(event, key, **fields)

    m._journal = journal
    results: list[dict[str, Any]] = []
    leader = threading.Thread(target=lambda: results.append(order(m, "atl-p")))
    leader.start()
    assert paused.wait(5)
    assert m.reconcile_order("atl-p")["status"] == "PENDING_RECONCILIATION"  # not NEVER_DISPATCHED
    assert m._journal_index["atl-p"]["event"] == "INTENT_CREATED"
    resume.set()
    leader.join(5)
    assert results[0]["status"] == "FILLED" and venue.dispatched == ["atl-p"]


def test_a_stuck_release_is_retried_and_releasing_never_dispatches(tmp_path):
    """F-4: a release whose store save failed is completed later; the release itself sends nothing."""
    kw = dict(order_journal_path=tmp_path / "j.jsonl", idempotency_store_path=tmp_path / "s.json")
    crashed = manager(FakeVenue(), **kw)
    fp = ("BTCUSDT", "BUY", 0.01, 500.0, False)
    crashed._journal("INTENT_CREATED", "atl-c", symbol="BTCUSDT", fingerprint=fp)
    with crashed._idempotency_lock:
        crashed._record_pending_reconciliation(key="atl-c", fingerprint=fp, symbol="BTCUSDT", side="BUY",
                                               quantity=0.01)
    crashed._journal("DISPATCH_FAILED", "atl-c", reason="NEVER_DISPATCHED")  # released, store not yet saved
    venue = FakeVenue(query=ConnectionError("unknown"))
    restarted = manager(venue, **kw)
    assert restarted.reconcile_order("atl-c")["reason"] == "NEVER_DISPATCHED"
    assert venue.queries == [] and venue.dispatched == []
    assert order(restarted, "atl-c")["status"] == "FILLED" and venue.dispatched == ["atl-c"]


def test_a_priced_request_never_reports_a_cached_market_result():
    """F-3."""
    venue = FakeVenue()
    m = manager(venue)
    assert order(m, "atl-k")["status"] == "FILLED"
    assert order(m, "atl-k", price="100.01")["reason"] == "LIMIT_ORDERS_NOT_SUPPORTED"
    assert venue.dispatched == ["atl-k"]


def test_a_journal_without_a_store_still_halts_the_pair_after_a_restart(tmp_path):
    """F-5."""
    path = tmp_path / "j.jsonl"
    assert order(manager(FakeVenue([TimeoutError("lost")]), order_journal_path=path), "atl-t")["status"] \
        == "PENDING_RECONCILIATION"
    venue = FakeVenue(query=ConnectionError("down"))
    restarted = manager(venue, order_journal_path=path)
    assert order(restarted, "atl-new")["reason"] == ExecutionSafetyGate.HALT_VENUE_PAIR
    assert venue.queries == ["atl-t"] and venue.dispatched == []


def test_a_request_timeout_is_an_unknown_outcome():
    """Review 11 I-2."""
    assert classify_venue_failure(408) is VenueOutcomeUnknownError


# -- review 12 regressions -------------------------------------------------------------------------


def _crashed_intent(m: ExchangeManager, key: str) -> dict[str, Any]:
    """A pending order whose journal shows only INTENT_CREATED (a crash before DISPATCHED)."""
    fp = ("BTCUSDT", "BUY", 0.01, 500.0, False)
    m._journal("INTENT_CREATED", key, symbol="BTCUSDT", fingerprint=fp)
    with m._idempotency_lock:
        m._record_pending_reconciliation(key=key, fingerprint=fp, symbol="BTCUSDT", side="BUY", quantity=0.01)
        return m._pending_reconciliations[key]


def test_a_stale_release_never_touches_a_re_dispatched_order(tmp_path):
    """M-1: a second reconcile that decided 'never dispatched' before a re-dispatch must not release it."""
    venue = FakeVenue([TimeoutError("lost")], query=ConnectionError("down"))
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl", idempotency_store_path=tmp_path / "s.json")
    stale = _crashed_intent(m, "atl-x")
    assert m._release_never_dispatched("atl-x", stale)["reason"] == "NEVER_DISPATCHED"  # the first release
    assert order(m, "atl-x")["status"] == "PENDING_RECONCILIATION"  # re-dispatched, outcome unknown
    assert m._release_never_dispatched("atl-x", stale) is None  # the stale second release does nothing
    assert "atl-x" in m._pending_reconciliations and m._journal_index["atl-x"]["event"] == "UNRECONCILED"
    restarted_venue = FakeVenue(query=ConnectionError("down"))
    restarted = manager(restarted_venue, order_journal_path=tmp_path / "j.jsonl",
                        idempotency_store_path=tmp_path / "s.json")
    assert order(restarted, "atl-x")["status"] == "PENDING_RECONCILIATION"
    assert venue.dispatched == ["atl-x"] and restarted_venue.dispatched == []  # sent exactly once


def test_concurrent_reconciles_release_a_never_dispatched_order_once(tmp_path):
    venue = FakeVenue(query=ConnectionError("down"))
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    _crashed_intent(m, "atl-y")
    start = threading.Barrier(16)
    results: list[dict[str, Any]] = []

    def reconcile():
        start.wait()
        results.append(m.reconcile_order("atl-y"))

    threads = [threading.Thread(target=reconcile) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert sum(1 for r in results if r.get("reason") == "NEVER_DISPATCHED") == 1
    assert [e for e, k in journal_events(tmp_path / "j.jsonl") if k == "atl-y"] == ["INTENT_CREATED", "DISPATCH_FAILED"]


def test_a_preparation_failure_closes_its_journaled_intent(tmp_path, monkeypatch):
    """L-1 (PREPARATION_FAILED)."""
    venue = FakeVenue()
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl", idempotency_store_path=tmp_path / "s.json")
    monkeypatch.setattr(m._idempotency_store, "save", lambda entries: False)
    failed = order(m, "atl-prep")
    assert failed["reason"] == "IDEMPOTENCY_STORE_UNAVAILABLE" and venue.dispatched == []
    assert [e for e, k in journal_events(tmp_path / "j.jsonl") if k == "atl-prep"] == ["INTENT_CREATED", "DISPATCH_FAILED"]
    assert m._journal_index["atl-prep"]["event"] == "DISPATCH_FAILED"


def test_a_failed_restore_refuses_every_order(tmp_path):
    """L-1 (restore failure disables the journal)."""
    path = tmp_path / "j.jsonl"
    m = manager(FakeVenue([TimeoutError("a"), TimeoutError("b"), TimeoutError("c")]), order_journal_path=path)
    for i, symbol in enumerate(("BTCUSDT", "ETHUSDT", "BNBUSDT")):
        assert order(m, f"atl-{i}", symbol=symbol)["status"] == "PENDING_RECONCILIATION"
    venue = FakeVenue()
    restarted = manager(venue, order_journal_path=path, idempotency_max_entries=2)  # cannot hold all three
    assert restarted.status()["order_journal"]["available"] is False
    assert order(restarted, "atl-new", symbol="SOLUSDT")["reason"] == "ORDER_JOURNAL_UNAVAILABLE"
    assert venue.dispatched == []


def test_the_journal_gate_registers_a_dispatched_key_it_alone_knows(tmp_path):
    """L-1 (journal gate DISPATCHED branch, isolated from the startup restore)."""
    venue = FakeVenue(query=ConnectionError("down"))
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    fp = ("BTCUSDT", "BUY", 0.01, 500.0, False)
    m._journal("INTENT_CREATED", "atl-g", symbol="BTCUSDT", fingerprint=fp)
    m._journal("DISPATCHED", "atl-g", attempt=1)
    assert "atl-g" not in m._pending_reconciliations
    assert order(m, "atl-g")["status"] == "PENDING_RECONCILIATION" and venue.dispatched == []
    assert "atl-g" in m._pending_reconciliations


def test_a_re_opened_key_is_never_evicted_from_the_index(tmp_path):
    """L-1 (re-open and eviction guard): a key re-dispatched after a definite failure stays indexed."""
    path = tmp_path / "j.jsonl"
    venue = FakeVenue([RuntimeError("local"), TimeoutError("lost")])
    m = manager(venue, order_journal_path=path, idempotency_max_entries=5)
    assert order(m, "atl-r")["status"] == "ERROR"  # DISPATCH_FAILED: finished
    assert order(m, "atl-r")["status"] == "PENDING_RECONCILIATION"  # re-dispatched: open again
    for i in range(20):
        order(m, f"atl-d{i}", symbol="ETHUSDT")
    assert m._journal_index["atl-r"]["event"] == "UNRECONCILED"
    restarted = manager(FakeVenue(), order_journal_path=path, idempotency_max_entries=5)
    assert restarted._journal_index["atl-r"]["event"] == "UNRECONCILED" and "atl-r" in restarted._pending_reconciliations


# -- review 13 regressions -------------------------------------------------------------------------


def test_a_stalled_request_cannot_resend_an_order_the_journal_saw_finish(tmp_path):
    """M-1: request A passes the early checks and stalls; K fills meanwhile and its cache entry expires;
    A must not become the leader and send K again."""
    clock = {"mono": 0.0}
    venue = FakeVenue()
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl", idempotency_ttl_seconds=60,
                monotonic_provider=lambda: clock["mono"])
    stalled, resume = threading.Event(), threading.Event()
    real_gate = m._pair_reconciliation_gate

    def slow_gate(**kw):
        if threading.current_thread().name == "A":
            stalled.set()
            resume.wait(5)
        return real_gate(**kw)

    m._pair_reconciliation_gate = slow_gate
    results: list[dict[str, Any]] = []
    a = threading.Thread(target=lambda: results.append(order(m, "atl-k")), name="A")
    a.start()
    assert stalled.wait(5)
    assert order(m, "atl-k")["status"] == "FILLED"  # request B fills K
    clock["mono"] += 3600  # K's cache entry expires
    resume.set()
    a.join(5)
    assert results[0]["status"] == "FILLED" and venue.dispatched == ["atl-k"]  # the journal's result, once


class AdapterCrash(BaseException):
    """A process crash inside the adapter call, after the venue already received the order."""


def test_dispatched_is_journaled_before_the_adapter_is_called(tmp_path):
    """M-2: the never-dispatched release depends on DISPATCHED being durable before the adapter call."""
    kw = dict(order_journal_path=tmp_path / "j.jsonl", idempotency_store_path=tmp_path / "s.json")
    seen: list[Any] = []

    class CrashingVenue(FakeVenue):
        def place_order(self, symbol, side, quantity, *, client_order_id=None):
            seen.append(m._journal_index[client_order_id]["event"])  # what is durable at call time
            self.dispatched.append(client_order_id)  # the venue has it ...
            raise AdapterCrash("process died")       # ... and then the process dies

    crashing = CrashingVenue()
    m = manager(crashing, **kw)
    with pytest.raises(AdapterCrash):
        order(m, "atl-c")
    assert seen == ["DISPATCHED"]
    venue = FakeVenue(query=ConnectionError("venue unreachable"))
    restarted = manager(venue, **kw)
    assert restarted.reconcile_order("atl-c")["status"] == "PENDING_RECONCILIATION"  # never NEVER_DISPATCHED
    assert order(restarted, "atl-c")["status"] == "PENDING_RECONCILIATION"
    assert crashing.dispatched + venue.dispatched == ["atl-c"]  # the venue received it exactly once


def test_a_restore_that_cannot_be_persisted_refuses_every_order(tmp_path, monkeypatch):
    """L-1 (S1/S3)."""
    path = tmp_path / "j.jsonl"
    assert order(manager(FakeVenue([TimeoutError("lost")]), order_journal_path=path), "atl-t")["status"] \
        == "PENDING_RECONCILIATION"
    monkeypatch.setattr(PersistentIdempotencyStore, "save", lambda self, entries: False)
    venue = FakeVenue()
    restarted = manager(venue, order_journal_path=path, idempotency_store_path=tmp_path / "s.json")
    assert restarted.status()["order_journal"]["available"] is False
    assert order(restarted, "atl-n", symbol="ETHUSDT")["reason"] == "ORDER_JOURNAL_UNAVAILABLE" and venue.dispatched == []


def test_a_reconciled_outcome_is_journaled_as_terminal(tmp_path):
    """L-1 (T1)."""
    path = tmp_path / "j.jsonl"
    m = manager(FakeVenue([TimeoutError("lost")], query={"status": "FILLED", "order_id": "late"}),
                order_journal_path=path)
    order(m, "atl-r")
    assert m.reconcile_order("atl-r")["status"] == "FILLED"
    assert journal_events(path)[-1] == ("TERMINAL", "atl-r")


def _failing_journal(m: ExchangeManager, failing_event: str):
    real = m._journal

    def journal(event, key, **fields):
        if event == failing_event:
            raise exchange_manager_module._JournalWriteError(f"cannot record {event}")
        return real(event, key, **fields)

    return journal


def test_an_unjournaled_rate_limit_outcome_stays_pending(tmp_path):
    """L-1 (G): a rate-limit failure that cannot be journaled is not released."""
    venue = FakeVenue([VenueRateLimitedError("429", http_status=429)] * 3)
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    m._journal = _failing_journal(m, "DISPATCH_FAILED")
    assert order(m, "atl-rl")["status"] == "PENDING_RECONCILIATION" and "atl-rl" in m._pending_reconciliations


def test_a_dispatched_write_failure_sends_nothing_and_clears_the_pending_entry(tmp_path):
    """L-1 (T3)."""
    venue = FakeVenue()
    m = manager(venue, order_journal_path=tmp_path / "j.jsonl")
    m._journal = _failing_journal(m, "DISPATCHED")
    failed = order(m, "atl-d")
    assert (failed["status"], failed["reason"]) == ("ERROR", "ORDER_JOURNAL_UNAVAILABLE")
    assert venue.dispatched == [] and "atl-d" not in m._pending_reconciliations


# -- review 14 --------------------------------------------------------------------------------------


def test_a_journaled_outcome_is_returned_before_any_authorization_gate(tmp_path):
    """I-1: the early journal check answers a finished id even while the live gate refuses new orders."""
    path = tmp_path / "j.jsonl"
    assert order(manager(FakeVenue(), order_journal_path=path), "atl-e")["status"] == "FILLED"
    venue = FakeVenue()
    refusing = ExchangeManager(
        exchange_name="test", exchange=venue, safety_gate=ExecutionSafetyGate(mode="PAPER", live_enabled=False),
        risk_guard=ExecutionRiskGuard(starting_equity=10_000.0, max_daily_loss_percent=5.0,
                                      max_drawdown_percent=10.0),
        exposure_guard=exposure_guard(), order_journal_path=path)
    assert order(refusing, "atl-e")["status"] == "FILLED" and venue.dispatched == []
    assert order(refusing, "atl-new")["status"] == "REJECTED"  # a new order is still refused by the gate
