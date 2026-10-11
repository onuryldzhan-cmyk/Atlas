"""
ATLAS EXCHANGE MANAGER v3.0

Lifecycle-safe and fail-closed exchange facade.

Order path
----------
Input validation
    -> idempotency validation
    -> LIVE safety authorization
    -> financial risk authorization
    -> exchange adapter
    -> terminal result cache

Idempotency rules
-----------------
- Every live order requires a non-empty idempotency key.
- Same key + same normalized order returns the cached result.
- Same key + different order is rejected.
- Successful and exchange-rejected terminal responses are cached.
- Adapter errors are not cached, allowing controlled retry.
- Cache is bounded by TTL and maximum entry count.
- Concurrent in-flight requests are coordinated to prevent duplicate adapter submissions.
- Indeterminate outcome quarantine guarantees fail-closed protection on uncertain order submission.
- Fingerprints include normalized economic and exposure intent.
- Uncertain exchange outcomes are durably reconciled by client order id.

Task 008 hardening (registry v5.92)
-----------------------------------
- A PENDING_RECONCILIATION entry never expires and is never evicted; it is
  released only by reconciliation. At capacity, new orders are refused.
- Before a new order for a symbol, every unresolved order of that symbol is
  reconciled; one that stays ambiguous halts the pair (HALT_VENUE_PAIR).
- Venue errors are classified (exchange.base_exchange): a rate limit is retried
  with full-jitter exponential backoff under the SAME client order id; an
  unknown outcome (5xx, dropped connection) is reconciled, never resent; a
  terminal rejection is cached as PERMANENTLY_REJECTED. Any other adapter
  exception keeps its existing meaning: a definite local failure.
- Optional durable order journal (DurableAppendLog): INTENT_CREATED, DISPATCHED,
  VENUE_ACK, TERMINAL (plus UNRECONCILED, DISPATCH_FAILED, PAIR_HALTED), each
  written before the state it records; a client order id the journal has seen
  dispatched is never dispatched again unless the journal shows that attempt
  never reached the venue (DISPATCH_FAILED under the adapter contract). This
  covers every unfinished id and the most recent idempotency_max_entries
  finished ones (v5.92 known limitations).
- Optional venue precision gate: step, minimum quantity, minimum notional,
  tick and upper bounds, on venue rules no older than 24 hours.
- Real order submission stays disabled in the Binance adapters; live use also
  requires the store, the journal and the venue rules (status live_prerequisites).
"""

from __future__ import annotations

import inspect
import logging
import math
import random
import re
import threading
import time

from collections import OrderedDict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

from core.durable_append_log import DurableAppendLog
from core.instrument_rules import is_aligned_to_step
from core.venue_rule_freshness import VenueRuleFreshnessPolicy, VenueRuleFreshnessService
from exchange.base_exchange import (
    VenueError,
    VenueRateLimitedError,
    VenueRejectedError,
)

from exchange.adapters.binance_global import BinanceGlobalExchange
from exchange.adapters.binance_tr import BinanceTRExchange
from exchange.execution_exposure_guard import (
    ExecutionExposureGuard,
)
from exchange.execution_risk_guard import ExecutionRiskGuard
from exchange.execution_safety_gate import ExecutionSafetyGate
from exchange.persistent_idempotency_store import (
    PersistentIdempotencyStore,
)


logger = logging.getLogger(
    "AtlasAI.ExchangeManager"
)


_SYMBOL_PATTERN = re.compile(
    r"^[A-Z0-9]{5,30}$"
)

_ALLOWED_ORDER_SIDES = {
    "BUY",
    "SELL",
}

_TERMINAL_ORDER_STATUSES = frozenset({
    "FILLED",
    "REJECTED",
    "CANCELED",
    "CANCELLED",
    "EXPIRED",
    "PAPER_ONLY",
    "EXECUTED",
    "SUCCESS",
})


# Task 008: the brief's stale-rule TTL for orders dispatched through this manager.
EXCHANGE_MAXIMUM_RULE_AGE_SECONDS = 24 * 60 * 60

# Journal events that mean the order may have reached the venue.
_JOURNAL_DISPATCHED_EVENTS = frozenset({"DISPATCHED", "VENUE_ACK", "UNRECONCILED", "FILL"})
# Journal events after which the venue did not receive the order: DISPATCHED is written before every
# adapter call, and DISPATCH_FAILED only for a non-dispatch - a rate limit (not processed), a
# preparation failure, a proven never-dispatched release, or a generic adapter exception, which the
# adapter contract defines as a definite local failure before sending. A live adapter must therefore
# raise VenueOutcomeUnknownError for ANY failure after transmission (v5.92 known limitations).
_JOURNAL_NOT_DISPATCHED_EVENTS = frozenset({"INTENT_CREATED", "DISPATCH_FAILED"})
# Last events of a finished key: bounded in the index (review 11 F-1).
_JOURNAL_FINISHED_EVENTS = frozenset({"TERMINAL", "DISPATCH_FAILED"})

# Task 010 (registry v5.94): venue fill fields (Binance names first). A FILL journal event records
# the cumulative filled quantity of an open order; fill progress is monotonic and never exceeds the
# order quantity (the core.order_lifecycle rules). Statuses below mean the whole order filled.
_FILLED_QUANTITY_FIELDS = ("executedQty", "executed_qty", "filled_quantity")
_FILLED_QUOTE_FIELDS = ("cummulativeQuoteQty", "cumulativeQuoteQty", "cumulative_quote_qty", "filled_quote")
_FULL_FILL_STATUSES = frozenset({"FILLED", "EXECUTED", "SUCCESS"})
# Venue terminal statuses in core.order_lifecycle terms (PAPER_ONLY: the adapter refused to send it,
# so it never reached the venue - DENIED); anything else is UNKNOWN.
_LIFECYCLE_TERMINAL_STATES = {"FILLED": "FILLED", "EXECUTED": "FILLED", "SUCCESS": "FILLED",
                              "CANCELED": "CANCELLED", "CANCELLED": "CANCELLED", "EXPIRED": "EXPIRED",
                              "REJECTED": "REJECTED", "PAPER_ONLY": "DENIED"}
# Review 20 F-1: progress events a racing writer could journal after another writer's TERMINAL; once
# a key is TERMINAL they are stale and never journaled (or, replayed from an older journal, indexed).
_STALE_AFTER_TERMINAL_EVENTS = frozenset({"VENUE_ACK", "FILL", "UNRECONCILED"})


class _JournalWriteError(RuntimeError):
    """The order journal could not record an event; the guarded transition must not happen."""


class _PendingCapacityError(RuntimeError):
    """Every pending-reconciliation slot holds an unresolved order; no new order may start."""


class ExchangeManager:
    VERSION = "3.0"

    def __init__(
        self,
        exchange_name: str = "binance_global",
        *,
        exchange: Any | None = None,
        safety_gate: ExecutionSafetyGate | None = None,
        risk_guard: ExecutionRiskGuard | None = None,
        exposure_guard: ExecutionExposureGuard | None = None,
        idempotency_ttl_seconds: float = 900.0,
        idempotency_max_entries: int = 10_000,
        monotonic_provider: Callable[[], float] | None = None,
        idempotency_store_path: str | Path | None = None,
        wall_time_provider: Callable[[], float] | None = None,
        in_flight_wait_timeout_seconds: float = 30.0,
        order_journal_path: str | Path | None = None,
        venue_rules: Any = None,
        venue_rule_freshness: VenueRuleFreshnessService | None = None,
        rate_limit_max_attempts: int = 3,
        rate_limit_backoff_base_seconds: float = 0.5,
        rate_limit_backoff_cap_seconds: float = 8.0,
        sleep_provider: Callable[[float], None] | None = None,
        jitter_provider: Callable[[], float] | None = None,
    ) -> None:
        self.exchange_name = str(
            exchange_name
        ).strip().lower()

        self.exchange = (
            exchange
            if exchange is not None
            else self._create_exchange()
        )

        self.safety_gate = (
            safety_gate
            if safety_gate is not None
            else ExecutionSafetyGate.from_environment()
        )

        self.risk_guard = risk_guard
        self.exposure_guard = exposure_guard

        self.idempotency_ttl_seconds = self._normalize_positive_float(
            idempotency_ttl_seconds,
            field_name="idempotency_ttl_seconds",
        )

        self.idempotency_max_entries = self._normalize_positive_int(
            idempotency_max_entries,
            field_name="idempotency_max_entries",
        )

        self.in_flight_wait_timeout_seconds = (
            self._normalize_positive_float(
                in_flight_wait_timeout_seconds,
                field_name="in_flight_wait_timeout_seconds",
            )
        )

        self._idempotency_lock = threading.RLock()

        self._in_flight_requests: dict[
            str,
            dict[str, Any],
        ] = {}

        self._monotonic_provider = (
            monotonic_provider
            if monotonic_provider is not None
            else time.monotonic
        )

        self._wall_time_provider = (
            wall_time_provider
            if wall_time_provider is not None
            else time.time
        )

        self._idempotency_cache: OrderedDict[
            str,
            dict[str, Any],
        ] = OrderedDict()

        self._quarantined_keys: OrderedDict[
            str,
            dict[str, Any],
        ] = OrderedDict()

        self._pending_reconciliations: OrderedDict[
            str,
            dict[str, Any],
        ] = OrderedDict()

        self._idempotency_store = (
            PersistentIdempotencyStore(
                path=idempotency_store_path,
                ttl_seconds=self.idempotency_ttl_seconds,
                max_entries=self.idempotency_max_entries,
                time_provider=self._wall_time_provider,
            )
            if idempotency_store_path is not None
            else None
        )

        self._load_persistent_idempotency_entries()

        # Task 008 (registry v5.92).
        self.rate_limit_max_attempts = self._normalize_positive_int(
            rate_limit_max_attempts, field_name="rate_limit_max_attempts")
        self.rate_limit_backoff_base_seconds = self._normalize_positive_float(
            rate_limit_backoff_base_seconds, field_name="rate_limit_backoff_base_seconds")
        self.rate_limit_backoff_cap_seconds = self._normalize_positive_float(
            rate_limit_backoff_cap_seconds, field_name="rate_limit_backoff_cap_seconds")
        self._sleep = sleep_provider if sleep_provider is not None else time.sleep
        self._jitter = jitter_provider if jitter_provider is not None else random.random
        self._halted_pairs: dict[str, str] = {}
        self._venue_rules = venue_rules
        self._venue_rule_freshness = (
            venue_rule_freshness if venue_rule_freshness is not None
            else VenueRuleFreshnessService(VenueRuleFreshnessPolicy(
                maximum_age_seconds=EXCHANGE_MAXIMUM_RULE_AGE_SECONDS))
        )
        self._order_journal = (
            DurableAppendLog(order_journal_path, log_name="exchange_order_journal", version=1)
            if order_journal_path is not None else None
        )
        self._journal_index: dict[str, dict[str, Any]] = {}
        # Reviews 10 M-1 / 11 F-1: finished keys (last event TERMINAL or DISPATCH_FAILED) are indexed
        # up to idempotency_max_entries, oldest first out; every key that may be on the venue stays.
        # The journal FILE is append-only and never compacted (an immutable audit trail); its growth
        # is a recorded limitation (v5.92).
        self._journal_finished_keys: OrderedDict[str, None] = OrderedDict()
        # Review 10 H-1: one writer at a time, so concurrent orders cannot interleave sequences.
        self._journal_lock = threading.Lock()
        self._journal_available = True
        self._journal_error_type: str | None = None
        # Task 010 (registry v5.94): the fill progress of every open order, and the net filled base
        # quantity per symbol, derived only from journaled events (replayed below at startup).
        self._order_fills: dict[str, dict[str, Any]] = {}
        self._filled_base: dict[str, Decimal] = {}
        self._reservations_restored = True
        self._load_order_journal()
        self._restore_pending_from_journal()
        self._restore_reservations()

    def _restore_pending_from_journal(self) -> None:
        """Review 11 F-5: an order the journal shows may be on the venue blocks its key and pair after a restart."""
        if self._order_journal is None or not self._journal_available:
            return
        restored = 0
        try:
            with self._idempotency_lock:
                for key, entry in list(self._journal_index.items()):
                    if entry.get("event") not in _JOURNAL_DISPATCHED_EVENTS or key in self._pending_reconciliations:
                        continue
                    fingerprint = tuple(entry.get("fingerprint") or ())
                    symbol, side, quantity = str(fingerprint[0]), str(fingerprint[1]), float(fingerprint[2])
                    if len(self._pending_reconciliations) >= self.idempotency_max_entries:
                        raise _PendingCapacityError("pending reconciliation capacity exhausted on restore")
                    self._pending_reconciliations[key] = {
                        "fingerprint": fingerprint,
                        "response": self._pending_result(symbol=symbol, side=side, quantity=quantity),
                        "symbol": symbol,
                        "client_order_id": key,
                        "created_at": float(self._monotonic_provider()),
                    }
                    restored += 1
                # One durable save for the whole restore (review 12 I-2).
                if restored and not self._persist_idempotency_entries():
                    raise RuntimeError("restored pending reconciliations could not be persisted")
        except Exception as exc:
            logger.exception("A journaled unresolved order could not be restored; new orders are refused")
            self._journal_available = False
            self._journal_error_type = f"PendingRestoreFailed:{type(exc).__name__}"

    # =====================================================
    # TASK 008: ORDER JOURNAL
    # =====================================================

    def _load_order_journal(self) -> None:
        if self._order_journal is None:
            return
        try:
            for record in self._order_journal.read():
                key = record.get("client_order_id")
                if isinstance(key, str) and key:
                    self._index_journal_event(key, record.get("event"), record)
        except Exception as exc:  # a corrupt or unreadable journal fails closed
            logger.exception("Exchange order journal is unreadable; new orders are refused")
            self._journal_available = False
            self._journal_error_type = type(exc).__name__

    def _journal(self, event: str, key: str | None, **fields: Any) -> None:
        """Durably record one event BEFORE the transition it guards; raises _JournalWriteError."""
        if self._order_journal is None:
            if key is not None:
                with self._journal_lock:
                    self._track_order_event(key, event, fields)
                self._settle_reservation(key, event)
            return
        payload: dict[str, Any] = {
            "event": event,
            "client_order_id": key,
            "recorded_at": float(self._wall_time_provider()),
        }
        for name, value in fields.items():
            payload[name] = list(value) if name == "fingerprint" else deepcopy(value)
        with self._journal_lock:
            if (key is not None and event in _STALE_AFTER_TERMINAL_EVENTS
                    and self._journal_index.get(key, {}).get("event") == "TERMINAL"):
                logger.warning("Stale %s after TERMINAL not journaled: client_order_id=%s", event, key)
                return
            try:
                self._order_journal.append([payload])
            except Exception as exc:
                self._journal_available = False
                self._journal_error_type = type(exc).__name__
                raise _JournalWriteError(f"order journal write failed: {event}") from exc
            if key is not None:
                self._index_journal_event(key, event, fields)
        if key is not None:
            self._settle_reservation(key, event)

    def _index_journal_event(self, key: str, event: Any, fields: Mapping[str, Any]) -> None:
        """Index one journal event (caller holds the journal lock or is the constructor)."""
        if event in _STALE_AFTER_TERMINAL_EVENTS and self._journal_index.get(key, {}).get("event") == "TERMINAL":
            return  # review 20 F-1: a stale progress event written after TERMINAL by an older build
        entry = self._journal_index.setdefault(key, {})
        entry["event"] = event
        for name in ("fingerprint", "symbol", "response"):
            if fields.get(name) is not None:
                entry[name] = tuple(fields[name]) if name == "fingerprint" else deepcopy(fields[name])
        if event in _JOURNAL_FINISHED_EVENTS:
            self._journal_finished_keys[key] = None
            self._journal_finished_keys.move_to_end(key)
            while len(self._journal_finished_keys) > self.idempotency_max_entries:
                oldest, _ = self._journal_finished_keys.popitem(last=False)
                if self._journal_index.get(oldest, {}).get("event") in _JOURNAL_FINISHED_EVENTS:
                    self._journal_index.pop(oldest, None)
        else:
            self._journal_finished_keys.pop(key, None)  # a re-dispatched key is open again
        self._track_order_event(key, event, fields)

    # =====================================================
    # TASK 010: FILL LEDGER AND EXPOSURE RESERVATIONS
    # =====================================================

    @staticmethod
    def _fill_decimal(value: Any) -> Decimal | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return number if number.is_finite() and number >= 0 else None

    def _fill_report(self, result: Any, *, quantity: Decimal | None = None) -> tuple[Decimal | None, Decimal | None, bool]:
        """(cumulative filled quantity, cumulative quote, malformed) of a venue report.

        A FILLED-type status without a filled quantity means the whole ``quantity`` filled.
        A fill field that is present but not a finite non-negative number is malformed.
        """
        if not isinstance(result, Mapping):
            return None, None, False
        values = []
        for names in (_FILLED_QUANTITY_FIELDS, _FILLED_QUOTE_FIELDS):
            raw = next((result[name] for name in names if result.get(name) is not None), None)
            parsed = self._fill_decimal(raw)
            if raw is not None and parsed is None:
                return None, None, True
            values.append(parsed)
        filled, quote = values
        if (filled is None and quantity is not None
                and str(result.get("status", "")).strip().upper() in _FULL_FILL_STATUSES):
            filled = quantity
        return filled, quote, False

    def _fill_anomaly(self, key: str, result: Any, *, terminal: bool) -> str | None:
        """Why a venue report cannot be folded into the order's fill ledger, or None."""
        with self._journal_lock:
            entry = deepcopy(self._order_fills.get(key))
        quantity = entry.get("quantity") if entry else None
        filled, _, malformed = self._fill_report(result, quantity=quantity if terminal else None)
        if malformed:
            return "FILL_REPORT_MALFORMED"
        if entry is None or filled is None or quantity is None:
            return None
        if filled > quantity:
            return "FILL_EXCEEDS_ORDER"
        if terminal and filled < entry["filled"]:
            return "FILL_REGRESSED"
        status = str(result.get("status", "")).strip().upper() if isinstance(result, Mapping) else ""
        if terminal and status in _FULL_FILL_STATUSES and filled != quantity:
            return "FILLED_QUANTITY_MISMATCH"
        return None

    def _track_order_event(self, key: str, event: Any, fields: Mapping[str, Any]) -> None:
        """Fold one journaled event into the fill ledger (caller holds the journal lock or is the constructor)."""
        if event == "INTENT_CREATED":
            self._order_fills[key] = {
                "symbol": str(fields.get("symbol") or ""),
                "side": str(fields.get("side") or "").upper(),
                "quantity": self._fill_decimal(fields.get("quantity")),
                "filled": Decimal("0"),
                "quote": None,
                "state": "VALIDATED",
            }
            return
        entry = self._order_fills.get(key)
        if entry is None:
            return
        if event == "DISPATCHED":
            entry["state"] = "SUBMITTED"
        elif event == "VENUE_ACK":
            entry["state"] = "PARTIALLY_FILLED" if entry["filled"] > 0 else "ACKNOWLEDGED"
        elif event == "UNRECONCILED":
            entry["state"] = "UNKNOWN"
        elif event == "FILL":
            self._apply_fill(entry, self._fill_decimal(fields.get("filled_quantity")),
                             self._fill_decimal(fields.get("filled_quote")))
            entry["state"] = "PARTIALLY_FILLED"
        elif event == "TERMINAL":
            filled, quote, malformed = self._fill_report(fields.get("response"), quantity=entry["quantity"])
            if not malformed:
                self._apply_fill(entry, filled, quote)
            self._order_fills.pop(key, None)
        elif event == "DISPATCH_FAILED":
            self._order_fills.pop(key, None)

    def _apply_fill(self, entry: dict[str, Any], filled: Decimal | None, quote: Decimal | None) -> None:
        """Monotonic: a lower (stale) cumulative quantity never reduces what was recorded."""
        if filled is None or filled <= entry["filled"]:
            return
        if entry["quantity"] is not None and filled > entry["quantity"]:
            return
        delta = filled - entry["filled"]
        entry["filled"] = filled
        if quote is not None:
            entry["quote"] = quote
        sign = Decimal("1") if entry["side"] == "BUY" else Decimal("-1")
        symbol = entry["symbol"]
        self._filled_base[symbol] = self._filled_base.get(symbol, Decimal("0")) + sign * delta

    def _reserve_exposure(self, *, key: str, symbol: str, side: str, quantity: float,
                          order_notional: float, opens_new_position: bool) -> dict[str, Any] | None:
        """Hold an open BUY's notional in the exposure guard, checked against every other open BUY."""
        if side != "BUY":
            return None
        reserve = getattr(self.exposure_guard, "reserve", None)
        if not callable(reserve) or not self._reservations_restored:
            return self._rejection(reason="EXPOSURE_RESERVATION_UNAVAILABLE", symbol=symbol, side=side,
                                   quantity=quantity)
        try:
            decision = reserve(key, symbol=symbol, order_notional=order_notional,
                               opens_new_position=opens_new_position)
        except Exception:
            logger.exception("Exposure reservation failed: symbol=%s", symbol)
            decision = {"allowed": False, "reason": "EXPOSURE_RESERVATION_UNAVAILABLE"}
        if not isinstance(decision, Mapping) or decision.get("allowed") is not True:
            reason = decision.get("reason") if isinstance(decision, Mapping) else None
            return self._rejection(reason=reason or "EXPOSURE_RESERVATION_REJECTED", symbol=symbol, side=side,
                                   quantity=quantity)
        return None

    def _release_reservation(self, key: str) -> None:
        release = getattr(self.exposure_guard, "release", None)
        if callable(release):
            try:
                release(key)
            except Exception:
                logger.exception("Exposure reservation could not be released: client_order_id=%s", key)

    def _settle_reservation(self, key: str, event: Any) -> None:
        """A terminal or never-dispatched order no longer holds exposure (filled exposure arrives via
        the guard's portfolio snapshot, as before)."""
        if event in _JOURNAL_FINISHED_EVENTS:
            self._release_reservation(key)

    def _restore_reservations(self) -> None:
        """Every open BUY known after a restart holds its exposure again (no check: it may be live)."""
        with self._idempotency_lock:
            with self._journal_lock:  # review 20 F-3: replayed intents that were never dispatched
                for key in [k for k in self._order_fills if k not in self._pending_reconciliations]:
                    self._order_fills.pop(key, None)
        restore = getattr(self.exposure_guard, "restore_reservation", None)
        if self.exposure_guard is None or not callable(restore):
            return
        try:
            with self._idempotency_lock:
                for key, entry in self._pending_reconciliations.items():
                    fingerprint = tuple(entry.get("fingerprint") or ())
                    if len(fingerprint) < 5:
                        raise ValueError("an open order has no complete fingerprint")
                    if str(fingerprint[1]).upper() == "BUY":
                        restore(key, symbol=fingerprint[0], order_notional=fingerprint[3],
                                opens_new_position=fingerprint[4])
        except Exception:
            logger.exception("An open order's exposure could not be restored; new BUY orders are refused")
            self._reservations_restored = False

    def order_state(self, idempotency_key: Any) -> dict[str, Any] | None:
        """The lifecycle state (core.order_lifecycle terms) and fill progress of one client order id."""
        key = self._normalize_idempotency_key(idempotency_key)
        if key is None:
            return None
        with self._journal_lock:
            entry = deepcopy(self._order_fills.get(key))
            indexed = deepcopy(self._journal_index.get(key))
        if entry is not None:
            return {"client_order_id": key, "state": entry["state"], "symbol": entry["symbol"],
                    "side": entry["side"], "quantity": self._decimal_text(entry["quantity"]),
                    "filled_quantity": self._decimal_text(entry["filled"]),
                    "filled_quote": self._decimal_text(entry["quote"])}
        with self._idempotency_lock:
            cached = deepcopy((self._idempotency_cache.get(key) or {}).get("response"))
        response = (indexed or {}).get("response") if indexed else None
        response = response if isinstance(response, dict) else cached
        if not isinstance(response, dict):
            return None
        status = str(response.get("status", "")).strip().upper()
        state = _LIFECYCLE_TERMINAL_STATES.get(status, "UNKNOWN")
        if response.get("reason") == "PERMANENTLY_REJECTED":
            state = "REJECTED"
        return {"client_order_id": key, "state": state, "terminal": True, "response": response}

    def _record_fill_progress(self, key: str, result: Any) -> dict[str, Any]:
        """Journal a non-terminal venue report's fill progress (FILL) BEFORE returning it; the
        returned progress is what the journal holds, never more."""
        filled, quote, _ = self._fill_report(result)
        # Review 20 F-1: journaled only while the order is still pending, under the lock every
        # TERMINAL write holds, so progress can never be recorded after the order's outcome.
        with self._idempotency_lock:
            if key in self._pending_reconciliations:
                with self._journal_lock:
                    entry = self._order_fills.get(key)
                    recorded = entry["filled"] if entry is not None else None
                if recorded is not None and filled is not None and filled > recorded:
                    self._journal_quiet("FILL", key, filled_quantity=format(filled, "f"),
                                        filled_quote=None if quote is None else format(quote, "f"),
                                        order_state="PARTIALLY_FILLED")
        progress = self.order_state(key) or {}
        if "filled_quantity" not in progress:
            return {}
        return {"order_state": progress["state"], "filled_quantity": progress["filled_quantity"],
                "filled_quote": progress["filled_quote"]}

    def _journal_unreconciled_while_pending(self, key: str, reason: str, result: Any) -> None:
        """Review 20 F-1: an inconsistent report is journaled only while the order is still pending."""
        with self._idempotency_lock:
            if key in self._pending_reconciliations:
                self._journal_quiet("UNRECONCILED", key, reason=reason, response=result)

    def _forget_unsent(self, key: str) -> None:
        """Review 20 F-3: an order dropped before dispatch leaves no open entry in the fill ledger."""
        with self._journal_lock:
            self._order_fills.pop(key, None)

    @staticmethod
    def _decimal_text(value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")

    def filled_positions(self) -> dict[str, str]:
        """Net filled base quantity per symbol from journaled fills (BUY +, SELL -)."""
        with self._journal_lock:
            return {symbol: format(amount, "f") for symbol, amount in sorted(self._filled_base.items())}

    def _journal_quiet(self, event: str, key: str | None, **fields: Any) -> None:
        """Journal an event whose state is already the conservative one; a failure is logged, never swallowed."""
        try:
            self._journal(event, key, **fields)
        except _JournalWriteError:
            logger.exception("Order journal write failed: event=%s", event)

    def _journal_gate(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float, float, bool],
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any] | None:
        """A client order id the journal has seen reach the venue is never dispatched again.

        Finished ids are indexed up to idempotency_max_entries (v5.92 known limitations).

        Called under the idempotency lock.
        """
        if self._order_journal is None:
            return None
        if not self._journal_available:
            return self._rejection(reason="ORDER_JOURNAL_UNAVAILABLE", symbol=symbol, side=side, quantity=quantity)
        with self._journal_lock:
            entry = deepcopy(self._journal_index.get(key))
        if entry is None:
            return None
        recorded = tuple(entry.get("fingerprint") or ())
        if recorded and recorded != tuple(fingerprint):
            return self._rejection(reason="IDEMPOTENCY_KEY_CONFLICT", symbol=symbol, side=side, quantity=quantity)
        event = entry.get("event")
        if event == "TERMINAL" and isinstance(entry.get("response"), dict):
            return deepcopy(entry["response"])
        if event in _JOURNAL_DISPATCHED_EVENTS and key not in self._pending_reconciliations:
            # It may have reached the venue and no other record holds its outcome: reconcile it.
            try:
                return self._record_pending_reconciliation(
                    key=key, fingerprint=fingerprint, symbol=symbol, side=side, quantity=quantity)
            except Exception:
                logger.exception("Journal-recovered order could not be registered for reconciliation")
                return self._pending_result(symbol=symbol, side=side, quantity=quantity)
        return None

    # =====================================================
    # TASK 008: PAIR RECONCILIATION LOCKOUT
    # =====================================================

    def _pair_reconciliation_gate(
        self,
        *,
        key: str,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any] | None:
        """Reconcile every unresolved order of ``symbol`` before a new one; halt the pair if any stays ambiguous."""
        with self._idempotency_lock:
            # Review 10 L-3: an order still in flight is not an unresolved one.
            others = [k for k, e in self._pending_reconciliations.items()
                      if e.get("symbol") == symbol and k != key and k not in self._in_flight_requests]
        for other in others:
            self.reconcile_order(other)
        with self._idempotency_lock:
            still = [k for k, e in self._pending_reconciliations.items()
                     if e.get("symbol") == symbol and k != key and k not in self._in_flight_requests]
            if not still:
                self._halted_pairs.pop(symbol, None)
                return None
            self._halted_pairs[symbol] = "UNRECONCILED_ORDERS"
        try:
            self._journal("PAIR_HALTED", None, symbol=symbol, blocked_client_order_id=key,
                          unreconciled_orders=len(still))
        except _JournalWriteError:
            logger.exception("Pair halt could not be journaled: symbol=%s", symbol)
        logger.warning("Venue pair halted until reconciliation: symbol=%s unreconciled=%s", symbol, len(still))
        rejection = self._rejection(reason=ExecutionSafetyGate.HALT_VENUE_PAIR, symbol=symbol, side=side,
                                    quantity=quantity)
        rejection["unreconciled_orders"] = len(still)
        return rejection

    # =====================================================
    # TASK 008: VENUE PRECISION GATE
    # =====================================================

    def _venue_precision_gate(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_notional: float,
        price: Any,
    ) -> dict[str, Any] | None:
        """Pre-flight venue rules (fresh within 24 h); nothing reaches the adapter on a refusal."""
        if self._venue_rules is None:
            return None

        def refuse(reason: str, **detail: Any) -> dict[str, Any]:
            rejection = self._rejection(reason=reason, symbol=symbol, side=side, quantity=quantity)
            rejection.update(detail)
            return rejection

        try:
            ruleset = self._venue_rules() if callable(self._venue_rules) else self._venue_rules
            report = self._venue_rule_freshness.assess(ruleset)
        except Exception as exc:
            logger.exception("Venue rules could not be read or assessed: symbol=%s", symbol)
            return refuse("VENUE_RULES_UNAVAILABLE", error_type=type(exc).__name__)
        if not report.is_fresh:
            return refuse("VENUE_RULES_STALE", rule_status=report.status.value,
                          rule_age_seconds=report.age_seconds, maximum_age_seconds=report.maximum_age_seconds)
        rules = ruleset.get(symbol)
        if rules is None:
            return refuse("VENUE_RULES_UNKNOWN_SYMBOL")
        try:
            base = Decimal(str(quantity))
            notional = Decimal(str(order_notional))
        except (InvalidOperation, ValueError):
            return refuse("INVALID_QUANTITY")
        try:  # review 10 L-1: an extreme value is refused, never raised
            if base < rules.min_quantity:
                return refuse("QUANTITY_BELOW_VENUE_MINIMUM", min_quantity=str(rules.min_quantity))
            if not is_aligned_to_step(base, rules.quantity_step):
                return refuse("QUANTITY_NOT_ALIGNED_TO_STEP", quantity_step=str(rules.quantity_step))
            if notional < rules.min_notional:
                return refuse("NOTIONAL_BELOW_VENUE_MINIMUM", min_notional=str(rules.min_notional))
            violation = rules.upper_bound_violation(base_quantity=base, quote_notional=notional)
        except ArithmeticError:
            return refuse("INVALID_QUANTITY")
        if violation is not None:
            return refuse(violation[0], **violation[1])
        if price is not None:
            if isinstance(price, bool):
                return refuse("INVALID_PRICE")
            try:
                limit = Decimal(str(price))
            except (InvalidOperation, ValueError):
                return refuse("INVALID_PRICE")
            if not limit.is_finite() or limit <= 0:
                return refuse("INVALID_PRICE")
            try:
                aligned = is_aligned_to_step(limit, rules.price_tick)
            except ArithmeticError:
                return refuse("INVALID_PRICE")
            if not aligned:
                return refuse("PRICE_NOT_ALIGNED_TO_TICK", price_tick=str(rules.price_tick))
        return None

    def _backoff_delay(self, attempt: int) -> float:
        """Full jitter: uniform in [0, min(cap, base x 2^(attempt-1))]."""
        ceiling = min(self.rate_limit_backoff_cap_seconds,
                      self.rate_limit_backoff_base_seconds * (2 ** min(attempt - 1, 62)))
        return max(0.0, min(float(self._jitter()), 1.0)) * ceiling

    def _dispatch_with_backoff(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        client_order_id: str,
    ) -> Any:
        """Submit under ONE client order id; only a rate limit (request not processed) is retried."""
        attempt = 0
        while True:
            attempt += 1
            self._journal("DISPATCHED", client_order_id, attempt=attempt)
            try:
                return self._submit_order_with_client_id(
                    symbol=symbol, side=side, quantity=quantity, client_order_id=client_order_id)
            except VenueRateLimitedError:
                if attempt >= self.rate_limit_max_attempts:
                    raise
                delay = self._backoff_delay(attempt)
                logger.warning("Venue rate limit; retrying with the same client order id: symbol=%s "
                               "attempt=%s delay=%.3fs", symbol, attempt, delay)
                self._sleep(delay)

    @staticmethod
    def _normalize_positive_float(
        value: Any,
        *,
        field_name: str,
    ) -> float:
        if isinstance(value, bool):
            raise ValueError(
                f"{field_name} must be a positive finite number"
            )

        try:
            normalized = float(value)
        except (
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            raise ValueError(
                f"{field_name} must be a positive finite number"
            ) from exc

        if (
            not math.isfinite(normalized)
            or normalized <= 0
        ):
            raise ValueError(
                f"{field_name} must be a positive finite number"
            )

        return normalized

    @staticmethod
    def _normalize_positive_int(
        value: Any,
        *,
        field_name: str,
    ) -> int:
        if isinstance(value, bool):
            raise ValueError(
                f"{field_name} must be a positive integer"
            )

        try:
            normalized = int(value)
        except (
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            raise ValueError(
                f"{field_name} must be a positive integer"
            ) from exc

        if normalized <= 0:
            raise ValueError(
                f"{field_name} must be a positive integer"
            )

        return normalized

    def _create_exchange(
        self,
    ) -> Any:
        if self.exchange_name == "binance_tr":
            logger.info(
                "Using Binance TR"
            )

            return BinanceTRExchange()

        logger.info(
            "Using Binance Global"
        )

        return BinanceGlobalExchange()

    def connect(
        self,
    ) -> Any:
        return self.exchange.connect()

    def disconnect(
        self,
    ) -> Any:
        return self.exchange.disconnect()

    def get_price(
        self,
        symbol: str,
    ) -> Any:
        return self.exchange.get_price(
            symbol
        )

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
    ) -> Any:
        return self.exchange.get_klines(
            symbol,
            interval,
            limit,
        )

    @staticmethod
    def _rejection(
        *,
        reason: str,
        symbol: str,
        side: str,
        quantity: Any,
    ) -> dict[str, Any]:
        return {
            "status": "REJECTED",
            "allowed": False,
            "reason": reason,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
        }

    @staticmethod
    def _error_result(
        *,
        reason: str,
        symbol: str,
        side: str,
        quantity: float,
        error_type: str,
    ) -> dict[str, Any]:
        return {
            "status": "ERROR",
            "allowed": False,
            "reason": reason,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "error_type": error_type,
        }

    @staticmethod
    def _normalize_quantity(
        quantity: Any,
    ) -> float | None:
        if isinstance(
            quantity,
            bool,
        ):
            return None

        try:
            normalized = float(
                quantity
            )
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            return None

        if not math.isfinite(
            normalized
        ):
            return None

        if normalized <= 0:
            return None

        return normalized

    @staticmethod
    def _normalize_idempotency_key(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        normalized = str(
            value
        ).strip()

        if not normalized:
            return None

        return normalized

    @staticmethod
    def _order_fingerprint(
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_notional: float,
        opens_new_position: bool,
    ) -> tuple[str, str, float, float, bool]:
        return (
            symbol,
            side,
            quantity,
            order_notional,
            opens_new_position,
        )

    def _load_persistent_idempotency_entries(
        self,
    ) -> None:
        if self._idempotency_store is None:
            return
        entries = self._idempotency_store.load()
        if not self._idempotency_store.available:
            return
        monotonic_now = float(self._monotonic_provider())
        wall_now = float(self._wall_time_provider())
        for key, entry in entries.items():
            remaining_ttl = max(0.0, float(entry["expires_at"]) - wall_now)
            if remaining_ttl <= 0 and entry.get("state") != "PENDING_RECONCILIATION":
                continue
            age = max(0.0, self.idempotency_ttl_seconds - remaining_ttl)
            normalized_entry = {
                "fingerprint": entry["fingerprint"],
                "response": deepcopy(entry["response"]),
                "created_at": monotonic_now - age,
            }
            if entry.get("state") == "PENDING_RECONCILIATION":
                normalized_entry["created_at"] = monotonic_now  # Task 008: never expires
                normalized_entry["symbol"] = entry["symbol"]
                normalized_entry["client_order_id"] = entry.get("client_order_id", key)
                self._pending_reconciliations[key] = normalized_entry
            else:
                self._idempotency_cache[key] = normalized_entry

    def _persist_idempotency_entries(
        self,
    ) -> bool:
        if self._idempotency_store is None:
            return True
        monotonic_now = float(self._monotonic_provider())
        wall_now = float(self._wall_time_provider())
        entries: dict[str, dict[str, Any]] = {}

        def add_entry(key: str, entry: dict[str, Any], *, state: str) -> None:
            age = max(0.0, monotonic_now - float(entry["created_at"]))
            remaining_ttl = max(0.0, self.idempotency_ttl_seconds - age)
            if state == "PENDING_RECONCILIATION":
                remaining_ttl = self.idempotency_ttl_seconds  # Task 008: never expires
            elif remaining_ttl <= 0:
                return
            payload = {
                "state": state,
                "fingerprint": entry["fingerprint"],
                "response": deepcopy(entry["response"]),
                "expires_at": wall_now + remaining_ttl,
            }
            if state == "PENDING_RECONCILIATION":
                payload["symbol"] = entry["symbol"]
                payload["client_order_id"] = entry["client_order_id"]
            entries[key] = payload

        for key, entry in self._idempotency_cache.items():
            add_entry(key, entry, state="TERMINAL")
        for key, entry in self._pending_reconciliations.items():
            add_entry(key, entry, state="PENDING_RECONCILIATION")
        return self._idempotency_store.save(entries)

    def _purge_expired_idempotency_entries(
        self,
    ) -> None:
        now = float(
            self._monotonic_provider()
        )

        expired_keys = [
            key
            for key, entry in self._idempotency_cache.items()
            if (
                now - float(entry["created_at"])
                >= self.idempotency_ttl_seconds
            )
        ]

        for key in expired_keys:
            self._idempotency_cache.pop(
                key,
                None,
            )

    def _lookup_idempotency_entry(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float, float, bool],
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any] | None:
        self._purge_expired_idempotency_entries()

        entry = self._idempotency_cache.get(
            key
        )

        if entry is None:
            return None

        if entry["fingerprint"] != fingerprint:
            logger.warning(
                "Idempotency conflict rejected: "
                "symbol=%s side=%s quantity=%s",
                symbol,
                side,
                quantity,
            )

            return self._rejection(
                reason="IDEMPOTENCY_KEY_CONFLICT",
                symbol=symbol,
                side=side,
                quantity=quantity,
            )

        self._idempotency_cache.move_to_end(
            key
        )

        return deepcopy(
            entry["response"]
        )

    def _cache_idempotency_result(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float, float, bool],
        response: dict[str, Any],
    ) -> None:
        self._purge_expired_idempotency_entries()
        previous_pending = self._pending_reconciliations.pop(key, None)
        self._idempotency_cache[key] = {
            "fingerprint": fingerprint,
            "response": deepcopy(response),
            "created_at": float(self._monotonic_provider()),
        }
        self._idempotency_cache.move_to_end(key)
        while len(self._idempotency_cache) > self.idempotency_max_entries:
            self._idempotency_cache.popitem(last=False)
        if not self._persist_idempotency_entries():
            self._idempotency_cache.pop(key, None)
            if previous_pending is not None:
                self._pending_reconciliations[key] = previous_pending
            raise RuntimeError("idempotency persistence failed")

    def _purge_expired_pending_reconciliations(self) -> None:
        """Task 008 (Vector B): an unresolved order never expires; only reconciliation releases it."""
        return None

    @staticmethod
    def _pending_result(
        *,
        symbol: str,
        side: str,
        quantity: float,
        reason: str = "EXCHANGE_OUTCOME_UNKNOWN",
    ) -> dict[str, Any]:
        return {
            "status": "PENDING_RECONCILIATION",
            "allowed": False,
            "reason": reason,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
        }

    def _lookup_pending_reconciliation(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float, float, bool],
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any] | None:
        self._purge_expired_pending_reconciliations()
        entry = self._pending_reconciliations.get(key)
        if entry is None:
            return None
        if entry["fingerprint"] != fingerprint:
            return self._rejection(
                reason="IDEMPOTENCY_KEY_CONFLICT",
                symbol=symbol,
                side=side,
                quantity=quantity,
            )
        self._pending_reconciliations.move_to_end(key)
        return deepcopy(entry["response"])

    def _record_pending_reconciliation(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float, float, bool],
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        response = self._pending_result(
            symbol=symbol,
            side=side,
            quantity=quantity,
        )
        if key not in self._pending_reconciliations and (
                len(self._pending_reconciliations) >= self.idempotency_max_entries):
            # Task 008: never evict an unresolved order to make room; refuse the new one instead.
            raise _PendingCapacityError("pending reconciliation capacity exhausted")
        self._pending_reconciliations[key] = {
            "fingerprint": fingerprint,
            "response": deepcopy(response),
            "symbol": symbol,
            "client_order_id": key,
            "created_at": float(self._monotonic_provider()),
        }
        self._pending_reconciliations.move_to_end(key)
        if not self._persist_idempotency_entries():
            self._pending_reconciliations.pop(key, None)
            raise RuntimeError("pending reconciliation persistence failed")
        return response

    def _discard_pending_reconciliation(self, *, key: str) -> bool:
        previous = self._pending_reconciliations.pop(key, None)
        if previous is None:
            return True
        if self._persist_idempotency_entries():
            return True
        self._pending_reconciliations[key] = previous
        return False

    def _submit_order_with_client_id(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        client_order_id: str,
    ) -> Any:
        method = self.exchange.place_order
        supports_client_id = False
        try:
            parameters = inspect.signature(method).parameters.values()
            supports_client_id = any(
                parameter.name == "client_order_id"
                or parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (TypeError, ValueError):
            supports_client_id = False
        if supports_client_id:
            return method(
                symbol,
                side,
                quantity,
                client_order_id=client_order_id,
            )
        return method(symbol, side, quantity)

    @staticmethod
    def _is_terminal_order_result(result: dict[str, Any]) -> bool:
        return str(result.get("status", "")).strip().upper() in _TERMINAL_ORDER_STATUSES

    def _purge_expired_quarantine_entries(
        self,
    ) -> None:
        now = float(
            self._monotonic_provider()
        )

        expired_keys = [
            key
            for key, entry in self._quarantined_keys.items()
            if (
                now - float(entry["created_at"])
                >= self.idempotency_ttl_seconds
            )
        ]

        for key in expired_keys:
            self._quarantined_keys.pop(
                key,
                None,
            )

    def _quarantine_key(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float, float, bool],
        reason: str = "IDEMPOTENCY_OUTCOME_UNKNOWN",
        status_code: str = "REJECTED",
    ) -> None:
        self._purge_expired_quarantine_entries()

        self._quarantined_keys[key] = {
            "fingerprint": fingerprint,
            "reason": reason,
            "status_code": status_code,
            "created_at": float(
                self._monotonic_provider()
            ),
        }

        self._quarantined_keys.move_to_end(
            key
        )

        while (
            len(self._quarantined_keys)
            > self.idempotency_max_entries
        ):
            self._quarantined_keys.popitem(
                last=False
            )

    def _lookup_quarantined_entry(
        self,
        *,
        key: str,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any] | None:
        self._purge_expired_quarantine_entries()

        entry = self._quarantined_keys.get(
            key
        )

        if entry is None:
            return None

        self._quarantined_keys.move_to_end(
            key
        )

        reason = str(
            entry.get(
                "reason",
                "IDEMPOTENCY_OUTCOME_UNKNOWN",
            )
        )

        status_code = str(
            entry.get(
                "status_code",
                "REJECTED",
            )
        )

        if status_code == "ERROR":
            return self._error_result(
                reason=reason,
                symbol=symbol,
                side=side,
                quantity=quantity,
                error_type="IdempotencyLeaderAborted",
            )

        return self._rejection(
            reason=reason,
            symbol=symbol,
            side=side,
            quantity=quantity,
        )

    def _coordinate_in_flight_request(
        self,
        *,
        key: str,
        fingerprint: tuple[str, str, float, float, bool],
        symbol: str,
        side: str,
        quantity: float,
    ) -> tuple[
        bool,
        dict[str, Any] | None,
        dict[str, Any] | None,
    ]:
        with self._idempotency_lock:
            quarantined_result = self._lookup_quarantined_entry(
                key=key,
                symbol=symbol,
                side=side,
                quantity=quantity,
            )

            if quarantined_result is not None:
                return (
                    False,
                    quarantined_result,
                    None,
                )

            cached_result = self._lookup_idempotency_entry(
                key=key,
                fingerprint=fingerprint,
                symbol=symbol,
                side=side,
                quantity=quantity,
            )

            if cached_result is not None:
                return (
                    False,
                    cached_result,
                    None,
                )

            existing = self._in_flight_requests.get(
                key
            )

            if existing is None:
                # Review 13 M-1: the journal is re-checked here, atomically with becoming the leader,
                # so a request that passed the early check and then stalled can never re-send an
                # order the journal has meanwhile seen reach the venue.
                journal_result = self._journal_gate(
                    key=key,
                    fingerprint=fingerprint,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                )
                if journal_result is not None:
                    return (False, journal_result, None)
                pending_result = self._lookup_pending_reconciliation(
                    key=key,
                    fingerprint=fingerprint,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                )
                if pending_result is not None:
                    return (False, pending_result, None)

                entry: dict[str, Any] = {
                    "fingerprint": fingerprint,
                    "event": threading.Event(),
                    "response": None,
                }

                self._in_flight_requests[key] = entry

                return (
                    True,
                    None,
                    entry,
                )

            if existing.get(
                "fingerprint"
            ) != fingerprint:
                return (
                    False,
                    self._rejection(
                        reason="IDEMPOTENCY_KEY_CONFLICT",
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                    ),
                    None,
                )

            entry = existing
            event = entry["event"]

        completed = event.wait(
            timeout=self.in_flight_wait_timeout_seconds
        )

        if not completed:
            return (
                False,
                self._rejection(
                    reason=(
                        "IDEMPOTENCY_REQUEST_IN_FLIGHT_TIMEOUT"
                    ),
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                ),
                None,
            )

        response = entry.get(
            "response"
        )

        if not isinstance(
            response,
            dict,
        ):
            return (
                False,
                self._error_result(
                    reason="IDEMPOTENCY_IN_FLIGHT_RESULT_UNAVAILABLE",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    error_type="InFlightResultUnavailable",
                ),
                None,
            )

        return (
            False,
            deepcopy(response),
            None,
        )

    def _complete_in_flight_request(
        self,
        *,
        key: str,
        entry: dict[str, Any],
        response: dict[str, Any],
    ) -> dict[str, Any]:
        result = deepcopy(
            response
        )

        with self._idempotency_lock:
            entry["response"] = deepcopy(
                result
            )

            current = self._in_flight_requests.get(
                key
            )

            if current is entry:
                self._in_flight_requests.pop(
                    key,
                    None,
                )

            event = entry.get(
                "event"
            )

            if isinstance(
                event,
                threading.Event,
            ):
                event.set()

        return result

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: Any,
        *,
        idempotency_key: Any = None,
        order_notional: Any = None,
        opens_new_position: Any = None,
        price: Any = None,
    ) -> dict[str, Any]:
        normalized_symbol = str(
            symbol
            if symbol is not None
            else ""
        ).strip().upper()

        normalized_side = str(
            side
            if side is not None
            else ""
        ).strip().upper()

        normalized_quantity = self._normalize_quantity(
            quantity
        )

        if not _SYMBOL_PATTERN.fullmatch(
            normalized_symbol
        ):
            return self._rejection(
                reason="INVALID_SYMBOL",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=quantity,
            )

        if normalized_side not in _ALLOWED_ORDER_SIDES:
            return self._rejection(
                reason="INVALID_SIDE",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=quantity,
            )

        if normalized_quantity is None:
            return self._rejection(
                reason="INVALID_QUANTITY",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=quantity,
            )

        if (
            self._idempotency_store is not None
            and not self._idempotency_store.available
        ):
            return self._rejection(
                reason="IDEMPOTENCY_STORE_UNAVAILABLE",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        normalized_order_notional = (
            self._normalize_quantity(
                order_notional
            )
        )

        if normalized_order_notional is None:
            return self._rejection(
                reason="INVALID_ORDER_NOTIONAL",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        if not isinstance(
            opens_new_position,
            bool,
        ):
            return self._rejection(
                reason="INVALID_POSITION_INTENT",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        normalized_opens_new_position = (
            opens_new_position
        )

        normalized_idempotency_key = (
            self._normalize_idempotency_key(
                idempotency_key
            )
        )

        if normalized_idempotency_key is None:
            return self._rejection(
                reason="IDEMPOTENCY_KEY_REQUIRED",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        fingerprint = self._order_fingerprint(
            symbol=normalized_symbol,
            side=normalized_side,
            quantity=normalized_quantity,
            order_notional=normalized_order_notional,
            opens_new_position=(
                normalized_opens_new_position
            ),
        )

        if price is not None:
            # Reviews 10 M-2 / 11 F-3: the adapter contract places market orders only, so a price
            # can be neither dispatched nor fingerprinted. It is refused before any idempotency
            # lookup (a cached market result is never reported for a priced request), after the
            # venue tick check.
            precision_rejection = self._venue_precision_gate(
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
                order_notional=normalized_order_notional,
                price=price,
            )
            if precision_rejection is not None:
                return precision_rejection
            return self._rejection(
                reason="LIMIT_ORDERS_NOT_SUPPORTED",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        with self._idempotency_lock:
            quarantined_result = self._lookup_quarantined_entry(
                key=normalized_idempotency_key,
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

            if quarantined_result is not None:
                return quarantined_result

            cached_result = self._lookup_idempotency_entry(
                key=normalized_idempotency_key,
                fingerprint=fingerprint,
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

            if cached_result is None:
                cached_result = self._journal_gate(
                    key=normalized_idempotency_key,
                    fingerprint=fingerprint,
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                )

        if cached_result is not None:
            return cached_result

        precision_rejection = self._venue_precision_gate(
            symbol=normalized_symbol,
            side=normalized_side,
            quantity=normalized_quantity,
            order_notional=normalized_order_notional,
            price=price,
        )

        if precision_rejection is not None:
            return precision_rejection

        safety_decision = (
            self.safety_gate.authorize_live_order()
        )

        if safety_decision.get(
            "allowed"
        ) is not True:
            return self._rejection(
                reason=safety_decision.get(
                    "reason",
                    "LIVE_AUTHORIZATION_REJECTED",
                ),
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        if self.risk_guard is None:
            logger.error(
                "Live order rejected because risk guard is missing: "
                "symbol=%s side=%s quantity=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )

            return self._rejection(
                reason="RISK_GUARD_NOT_CONFIGURED",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        risk_decision = (
            self.risk_guard.authorize_order()
        )

        if risk_decision.get(
            "allowed"
        ) is not True:
            return self._rejection(
                reason=risk_decision.get(
                    "reason",
                    "RISK_AUTHORIZATION_REJECTED",
                ),
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        if self.exposure_guard is None:
            logger.error(
                "Live order rejected because exposure guard is missing: "
                "symbol=%s side=%s quantity=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
            )

            return self._rejection(
                reason="EXPOSURE_GUARD_NOT_CONFIGURED",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

        exposure_decision = (
            self.exposure_guard.authorize_order(
                symbol=normalized_symbol,
                order_notional=normalized_order_notional,
                opens_new_position=(
                    normalized_opens_new_position
                ),
            )
        )

        if exposure_decision.get(
            "allowed"
        ) is not True:
            rejection = self._rejection(
                reason=exposure_decision.get(
                    "reason",
                    "EXPOSURE_AUTHORIZATION_REJECTED",
                ),
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )

            logger.warning(
                "Live order rejected by exposure guard: "
                "symbol=%s side=%s quantity=%s reason=%s",
                normalized_symbol,
                normalized_side,
                normalized_quantity,
                rejection["reason"],
            )

            return rejection

        pair_rejection = self._pair_reconciliation_gate(
            key=normalized_idempotency_key,
            symbol=normalized_symbol,
            side=normalized_side,
            quantity=normalized_quantity,
        )

        if pair_rejection is not None:
            return pair_rejection

        is_leader, coordinated_result, in_flight_entry = (
            self._coordinate_in_flight_request(
                key=normalized_idempotency_key,
                fingerprint=fingerprint,
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
            )
        )

        if not is_leader:
            if coordinated_result is None:
                return self._error_result(
                    reason="IDEMPOTENCY_COORDINATION_FAILED",
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    error_type="IdempotencyCoordinationError",
                )

            return coordinated_result

        if in_flight_entry is None:
            return self._error_result(
                reason="IDEMPOTENCY_COORDINATION_FAILED",
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
                error_type="IdempotencyCoordinationError",
            )

        leader_completed = False
        pending_result = self._pending_result(
            symbol=normalized_symbol,
            side=normalized_side,
            quantity=normalized_quantity,
        )
        try:
            # Task 010: an open BUY holds its notional, checked against every other open BUY.
            reservation_rejection = self._reserve_exposure(
                key=normalized_idempotency_key,
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=normalized_quantity,
                order_notional=normalized_order_notional,
                opens_new_position=normalized_opens_new_position,
            )
            if reservation_rejection is not None:
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=reservation_rejection,
                )
                leader_completed = True
                return completed_result
            try:
                with self._idempotency_lock:
                    if (normalized_idempotency_key not in self._pending_reconciliations
                            and len(self._pending_reconciliations) >= self.idempotency_max_entries):
                        raise _PendingCapacityError("pending reconciliation capacity exhausted")
                self._journal(
                    "INTENT_CREATED",
                    normalized_idempotency_key,
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    order_notional=normalized_order_notional,
                    opens_new_position=normalized_opens_new_position,
                    fingerprint=fingerprint,
                )
                with self._idempotency_lock:
                    pending_result = self._record_pending_reconciliation(
                        key=normalized_idempotency_key,
                        fingerprint=fingerprint,
                        symbol=normalized_symbol,
                        side=normalized_side,
                        quantity=normalized_quantity,
                    )
            except Exception as exc:
                logger.exception(
                    "Order could not be prepared; nothing was dispatched: symbol=%s side=%s quantity=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                )
                if not isinstance(exc, _JournalWriteError) and self._journal_index.get(
                        normalized_idempotency_key, {}).get("event") == "INTENT_CREATED":
                    self._journal_quiet("DISPATCH_FAILED", normalized_idempotency_key,
                                        reason="PREPARATION_FAILED", error_type=type(exc).__name__)
                self._release_reservation(normalized_idempotency_key)  # nothing was dispatched
                self._forget_unsent(normalized_idempotency_key)
                error_result = self._error_result(
                    reason=(
                        "ORDER_JOURNAL_UNAVAILABLE" if isinstance(exc, _JournalWriteError)
                        else "PENDING_RECONCILIATION_CAPACITY_EXHAUSTED"
                        if isinstance(exc, _PendingCapacityError)
                        else "IDEMPOTENCY_STORE_UNAVAILABLE"
                    ),
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    error_type=type(exc).__name__,
                )
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=error_result,
                )
                leader_completed = True
                return completed_result

            try:
                result = self._dispatch_with_backoff(
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    client_order_id=normalized_idempotency_key,
                )
            except _JournalWriteError as exc:
                # DISPATCHED could not be recorded, so this attempt was never sent (earlier
                # attempts, if any, were rate limited and not processed by the venue).
                logger.exception("Order not dispatched: the order journal is unavailable")
                with self._idempotency_lock:
                    cleared = self._discard_pending_reconciliation(key=normalized_idempotency_key)
                if cleared:
                    self._release_reservation(normalized_idempotency_key)
                    self._forget_unsent(normalized_idempotency_key)
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=(
                        self._error_result(
                            reason="ORDER_JOURNAL_UNAVAILABLE",
                            symbol=normalized_symbol,
                            side=normalized_side,
                            quantity=normalized_quantity,
                            error_type=type(exc).__name__,
                        )
                        if cleared else pending_result
                    ),
                )
                leader_completed = True
                return completed_result
            except VenueRejectedError as exc:
                logger.warning(
                    "Venue rejected the order permanently: symbol=%s side=%s quantity=%s http_status=%s "
                    "venue_code=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                    exc.http_status,
                    exc.venue_code,
                )
                rejection = self._rejection(
                    reason="PERMANENTLY_REJECTED",
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                )
                rejection.update(
                    venue_reason=str(exc),
                    http_status=exc.http_status,
                    venue_code=exc.venue_code,
                )
                try:
                    self._journal("TERMINAL", normalized_idempotency_key, response=rejection)
                    with self._idempotency_lock:
                        self._cache_idempotency_result(
                            key=normalized_idempotency_key,
                            fingerprint=fingerprint,
                            response=rejection,
                        )
                except Exception:
                    logger.exception("Permanent rejection could not be durably recorded; it stays pending")
                    rejection = pending_result
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=rejection,
                )
                leader_completed = True
                return completed_result
            except VenueRateLimitedError as exc:
                logger.warning(
                    "Venue rate limit persisted after %s attempts; nothing was processed: symbol=%s",
                    self.rate_limit_max_attempts,
                    normalized_symbol,
                )
                try:
                    self._journal(
                        "DISPATCH_FAILED",
                        normalized_idempotency_key,
                        reason="VENUE_RATE_LIMITED",
                        attempts=self.rate_limit_max_attempts,
                    )
                except _JournalWriteError:
                    logger.exception("Rate-limit outcome could not be journaled; the order stays pending")
                    completed_result = self._complete_in_flight_request(
                        key=normalized_idempotency_key,
                        entry=in_flight_entry,
                        response=pending_result,
                    )
                    leader_completed = True
                    return completed_result
                with self._idempotency_lock:
                    cleared = self._discard_pending_reconciliation(key=normalized_idempotency_key)
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=(
                        self._error_result(
                            reason="VENUE_RATE_LIMITED",
                            symbol=normalized_symbol,
                            side=normalized_side,
                            quantity=normalized_quantity,
                            error_type=type(exc).__name__,
                        )
                        if cleared else pending_result
                    ),
                )
                leader_completed = True
                return completed_result
            except TimeoutError:
                self._journal_quiet(
                    "UNRECONCILED", normalized_idempotency_key, reason="EXCHANGE_TIMEOUT")
                logger.exception(
                    "Exchange timeout left order outcome indeterminate: symbol=%s side=%s quantity=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                )
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=pending_result,
                )
                leader_completed = True
                return completed_result
            except ConnectionError as exc:
                self._journal_quiet(
                    "UNRECONCILED", normalized_idempotency_key, reason="EXCHANGE_OUTCOME_UNKNOWN",
                    error_type=type(exc).__name__)
                logger.exception(
                    "Exchange connection loss left order outcome indeterminate: symbol=%s side=%s quantity=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                )
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=pending_result,
                )
                leader_completed = True
                return completed_result
            except VenueError as exc:
                # A venue response the taxonomy does not classify: its outcome is unknown.
                self._journal_quiet(
                    "UNRECONCILED", normalized_idempotency_key, reason="VENUE_ERROR_UNCLASSIFIED",
                    error_type=type(exc).__name__)
                logger.exception("Unclassified venue error left order outcome indeterminate: symbol=%s",
                                 normalized_symbol)
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=pending_result,
                )
                leader_completed = True
                return completed_result
            except Exception as exc:
                logger.exception(
                    "Unexpected exchange adapter failure: "
                    "symbol=%s side=%s quantity=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                )

                try:
                    self._journal(
                        "DISPATCH_FAILED",
                        normalized_idempotency_key,
                        reason="EXCHANGE_ADAPTER_ERROR",
                        error_type=type(exc).__name__,
                    )
                except _JournalWriteError:
                    logger.exception("Adapter failure could not be journaled; the order stays pending")
                    completed_result = self._complete_in_flight_request(
                        key=normalized_idempotency_key,
                        entry=in_flight_entry,
                        response=pending_result,
                    )
                    leader_completed = True
                    return completed_result

                with self._idempotency_lock:
                    cleared = self._discard_pending_reconciliation(
                        key=normalized_idempotency_key,
                    )
                if not cleared:
                    completed_result = self._complete_in_flight_request(
                        key=normalized_idempotency_key,
                        entry=in_flight_entry,
                        response=pending_result,
                    )
                    leader_completed = True
                    return completed_result

                error_result = self._error_result(
                    reason="EXCHANGE_ADAPTER_ERROR",
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    error_type=type(exc).__name__,
                )

                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=error_result,
                )
                leader_completed = True
                return completed_result

            if not isinstance(
                result,
                dict,
            ):
                logger.error(
                    "Invalid exchange response left outcome indeterminate: symbol=%s side=%s quantity=%s response_type=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                    type(result).__name__,
                )
                self._journal_quiet(
                    "UNRECONCILED", normalized_idempotency_key, reason="INVALID_EXCHANGE_RESPONSE")
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=pending_result,
                )
                leader_completed = True
                return completed_result

            terminal = self._is_terminal_order_result(result)
            anomaly = self._fill_anomaly(normalized_idempotency_key, result, terminal=terminal)
            if anomaly is not None:
                # Task 010: an inconsistent fill report is never folded in; the order stays
                # unreconciled (its pair halts) until the venue reports consistently.
                logger.error("Inconsistent venue fill report left order unreconciled: symbol=%s reason=%s",
                             normalized_symbol, anomaly)
                self._journal_unreconciled_while_pending(normalized_idempotency_key, anomaly, result)
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=pending_result,
                )
                leader_completed = True
                return completed_result

            if not terminal:
                nonterminal = self._pending_result(
                    symbol=normalized_symbol,
                    side=normalized_side,
                    quantity=normalized_quantity,
                    reason="EXCHANGE_ORDER_NOT_TERMINAL",
                )
                self._journal_quiet("VENUE_ACK", normalized_idempotency_key, response=result)
                nonterminal.update(self._record_fill_progress(normalized_idempotency_key, result))
                with self._idempotency_lock:
                    pending_entry = self._pending_reconciliations.get(
                        normalized_idempotency_key
                    )
                    if pending_entry is not None:
                        pending_entry["response"] = deepcopy(nonterminal)
                        if not self._persist_idempotency_entries():
                            logger.error(
                                "Venue acknowledgement could not be persisted; the order stays pending: "
                                "symbol=%s",
                                normalized_symbol,
                            )
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=nonterminal,
                )
                leader_completed = True
                return completed_result

            try:
                self._journal("TERMINAL", normalized_idempotency_key, response=result)
                with self._idempotency_lock:
                    self._cache_idempotency_result(
                        key=normalized_idempotency_key,
                        fingerprint=fingerprint,
                        response=result,
                    )

                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=result,
                )
                leader_completed = True

                logger.info(
                    "Live order delegated after validation, idempotency, "
                    "safety and risk authorization: "
                    "symbol=%s side=%s quantity=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                )

                return completed_result

            except Exception:
                logger.exception(
                    "Terminal result could not be durably finalized; reconciliation remains pending: symbol=%s side=%s quantity=%s",
                    normalized_symbol,
                    normalized_side,
                    normalized_quantity,
                )
                completed_result = self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=pending_result,
                )
                leader_completed = True
                return completed_result

        except BaseException:
            if not leader_completed:
                self._complete_in_flight_request(
                    key=normalized_idempotency_key,
                    entry=in_flight_entry,
                    response=pending_result,
                )
            raise
        finally:
            with self._idempotency_lock:
                current = self._in_flight_requests.get(
                    normalized_idempotency_key
                )
                if current is in_flight_entry:
                    self._in_flight_requests.pop(
                        normalized_idempotency_key,
                        None,
                    )
                    event = in_flight_entry.get("event")
                    if isinstance(event, threading.Event) and not event.is_set():
                        event.set()

    def _release_never_dispatched(self, key: str, expected: dict[str, Any]) -> dict[str, Any] | None:
        """Atomically release a pending order the journal proves never reached the venue (review 12 M-1).

        Everything is re-verified and done under the idempotency lock: the pending entry must still
        be the very one the caller examined, the order must not be in flight, and the journal's last
        event must still show no dispatch. A stale caller therefore can never release (or journal
        over) an order that was re-dispatched in the meantime. Returns None when nothing was released.
        """
        with self._idempotency_lock:
            if (self._pending_reconciliations.get(key) is not expected
                    or key in self._in_flight_requests
                    or self._order_journal is None
                    or not self._journal_available):
                return None
            with self._journal_lock:
                last_event = self._journal_index.get(key, {}).get("event")
            if last_event not in _JOURNAL_NOT_DISPATCHED_EVENTS:
                return None
            if last_event == "INTENT_CREATED":
                try:
                    self._journal("DISPATCH_FAILED", key, reason="NEVER_DISPATCHED")
                except _JournalWriteError:
                    logger.exception("Never-dispatched order could not be released; it stays pending")
                    return None
            if not self._discard_pending_reconciliation(key=key):
                return None
            # Review 21 L-2: released here whether or not DISPATCH_FAILED was journaled just now (an
            # order restored after a restart was re-reserved although the journal already proved it).
            self._release_reservation(key)
            self._forget_unsent(key)
            symbol = expected.get("symbol", "")
        logger.warning("Released a pending order that was never dispatched: symbol=%s", symbol)
        return self._error_result(reason="NEVER_DISPATCHED", symbol=symbol, side="", quantity=0.0,
                                  error_type="NeverDispatched")

    def reconcile_order(
        self,
        idempotency_key: Any,
    ) -> dict[str, Any]:
        key = self._normalize_idempotency_key(idempotency_key)
        if key is None:
            return self._rejection(
                reason="IDEMPOTENCY_KEY_REQUIRED",
                symbol="",
                side="",
                quantity=0.0,
            )
        with self._idempotency_lock:
            self._purge_expired_pending_reconciliations()
            pending = self._pending_reconciliations.get(key)
            if pending is None:
                cached = self._idempotency_cache.get(key)
                if cached is not None:
                    return deepcopy(cached["response"])
                return self._rejection(
                    reason="RECONCILIATION_ENTRY_NOT_FOUND",
                    symbol="",
                    side="",
                    quantity=0.0,
                )
            pending_snapshot = deepcopy(pending)
            with self._journal_lock:
                last_event = self._journal_index.get(key, {}).get("event")
            never_dispatched = (
                self._order_journal is not None
                and self._journal_available
                and key not in self._in_flight_requests
                and last_event in _JOURNAL_NOT_DISPATCHED_EVENTS
            )
        if never_dispatched:
            released = self._release_never_dispatched(key, pending)
            return released if released is not None else deepcopy(pending_snapshot["response"])
        if self.safety_gate.authorize_live_order().get("allowed") is not True:
            # Task 010: outside live authorization nothing reaches the venue, not even a status
            # query signed with whatever credentials the environment holds; the order stays pending.
            return deepcopy(pending_snapshot["response"])
        query_method = getattr(self.exchange, "get_order_by_client_id", None)
        if not callable(query_method):
            return deepcopy(pending_snapshot["response"])
        try:
            result = query_method(
                pending_snapshot["symbol"],
                pending_snapshot["client_order_id"],
            )
        except Exception:
            logger.exception("Exchange order reconciliation query failed")
            return deepcopy(pending_snapshot["response"])
        if not isinstance(result, dict):
            return deepcopy(pending_snapshot["response"])
        terminal = self._is_terminal_order_result(result)
        anomaly = self._fill_anomaly(key, result, terminal=terminal)
        if anomaly is not None:
            logger.error("Inconsistent venue fill report; the order stays unreconciled: reason=%s", anomaly)
            self._journal_unreconciled_while_pending(key, anomaly, result)
            with self._idempotency_lock:
                cached = self._idempotency_cache.get(key)
                if key not in self._pending_reconciliations and cached is not None:
                    return deepcopy(cached["response"])  # a concurrent reconciliation resolved it
            return deepcopy(pending_snapshot["response"])
        if not terminal:
            # Task 010: an open (e.g. partially filled) order stays pending, with its journaled progress.
            progress = self._record_fill_progress(key, result)
            with self._idempotency_lock:
                current = self._pending_reconciliations.get(key)
                if current is None:
                    cached = self._idempotency_cache.get(key)
                    return deepcopy(cached["response"]) if cached is not None else deepcopy(
                        pending_snapshot["response"])
                if progress:
                    current["response"] = {**current["response"], **progress}
                    if not self._persist_idempotency_entries():
                        logger.error("Fill progress could not be persisted with the pending order")
                return deepcopy(current["response"])
        with self._idempotency_lock:
            current = self._pending_reconciliations.get(key)
            if current is None:
                cached = self._idempotency_cache.get(key)
                if cached is not None:
                    return deepcopy(cached["response"])
                return deepcopy(pending_snapshot["response"])
            try:
                self._journal("TERMINAL", key, response=result, reconciled=True)
                self._cache_idempotency_result(
                    key=key,
                    fingerprint=current["fingerprint"],
                    response=result,
                )
            except Exception:
                logger.exception("Reconciled terminal outcome could not be persisted")
                return deepcopy(current["response"])
        return deepcopy(result)

    def status(
        self,
    ) -> dict[str, Any]:
        with self._idempotency_lock:
            self._purge_expired_idempotency_entries()
            self._purge_expired_pending_reconciliations()
            self._purge_expired_quarantine_entries()

            cached_entries = len(
                self._idempotency_cache
            )

            in_flight_entries = len(
                self._in_flight_requests
            )

            pending_reconciliation_entries = len(
                self._pending_reconciliations
            )
            indeterminate_entries = (
                pending_reconciliation_entries
                + len(self._quarantined_keys)
            )
            halted_pairs = dict(sorted(self._halted_pairs.items()))
        live_prerequisites = {
            "persistent_idempotency_store": self._idempotency_store is not None,
            "order_journal": self._order_journal is not None,
            "venue_rules": self._venue_rules is not None,
        }
        live_prerequisites["met"] = all(live_prerequisites.values())

        exchange_status_method = getattr(
            self.exchange,
            "status",
            None,
        )

        if callable(
            exchange_status_method
        ):
            try:
                exchange_status = (
                    exchange_status_method()
                )
            except Exception as exc:
                exchange_status = {
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
        else:
            exchange_status = {
                "status_supported": False,
            }

        return {
            "name": "ExchangeManager",
            "version": self.VERSION,
            "exchange_name": self.exchange_name,
            "validation": {
                "allowed_sides": sorted(
                    _ALLOWED_ORDER_SIDES
                ),
                "symbol_pattern": (
                    _SYMBOL_PATTERN.pattern
                ),
                "quantity_requires_positive_finite_number": True,
            },
            "idempotency": {
                "enabled": True,
                "required": True,
                "cached_entries": cached_entries,
                "in_flight_entries": in_flight_entries,
                "indeterminate_entries": indeterminate_entries,
                "pending_reconciliation_entries": (
                    pending_reconciliation_entries
                ),
                "in_flight_wait_timeout_seconds": (
                    self.in_flight_wait_timeout_seconds
                ),
                "ttl_seconds": self.idempotency_ttl_seconds,
                "max_entries": self.idempotency_max_entries,
                "persistent": (
                    self._idempotency_store is not None
                ),
                "store_available": (
                    self._idempotency_store.available
                    if self._idempotency_store is not None
                    else None
                ),
                "store_error_type": (
                    self._idempotency_store.error_type
                    if self._idempotency_store is not None
                    else None
                ),
            },
            "safety": self.safety_gate.status(),
            "risk_guard": (
                self.risk_guard.status()
                if self.risk_guard is not None
                else {
                    "configured": False,
                    "status": "FAIL_CLOSED",
                }
            ),
            "exposure_guard": (
                self.exposure_guard.status()
                if self.exposure_guard is not None
                else {
                    "configured": False,
                    "status": "FAIL_CLOSED",
                }
            ),
            "exchange": exchange_status,
            # Task 008 (registry v5.92).
            "halted_pairs": halted_pairs,
            "venue_precision_gate": {
                "configured": self._venue_rules is not None,
                "maximum_rule_age_seconds": self._venue_rule_freshness.policy.maximum_age_seconds,
            },
            "order_journal": {
                "configured": self._order_journal is not None,
                "available": self._journal_available if self._order_journal is not None else None,
                "error_type": self._journal_error_type,
            },
            "rate_limit_retry": {
                "max_attempts": self.rate_limit_max_attempts,
                "backoff_base_seconds": self.rate_limit_backoff_base_seconds,
                "backoff_cap_seconds": self.rate_limit_backoff_cap_seconds,
                "jitter": "FULL",
            },
            "live_prerequisites": live_prerequisites,
            # Task 010 (registry v5.94).
            "order_fills": self._order_fills_status(),
        }

    def _order_fills_status(self) -> dict[str, Any]:
        with self._journal_lock:
            open_orders = {key: entry["state"] for key, entry in self._order_fills.items()}
        return {
            "open_orders": len(open_orders),
            "partially_filled": sum(1 for state in open_orders.values() if state == "PARTIALLY_FILLED"),
            "filled_positions": self.filled_positions(),
            "reservations_restored": self._reservations_restored,
        }
