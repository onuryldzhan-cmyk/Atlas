"""
============================================================
ATLAS EXIT GUARD v1 (Phase-2 B1/B2)
============================================================

A Brain-independent, risk-reducing exit path.

What it does
------------
For every open LONG position in the durable book it checks owner-configured
protective rules against a *fresh* mark price and, when a rule triggers,
produces an exit intent. In ENFORCE mode the intent is submitted as a
reduce-only SELL through ``ExecutionManager.execute`` - the one execution
authority - so idempotency, the transaction journal, audit, recovery and
RiskEngine's reduction checks all apply exactly as for any other SELL.

What it never does
------------------
- open, add to, or resize risk (it only ever emits a full exit: a SELL for a LONG, a BUY for a margin-book
  SHORT - Task 026)
- generate alpha: there are no built-in rules; every rule is owner-supplied
- sell on a stale or missing price: that is EXIT_PENDING_PRICE
- bypass ExecutionManager, RiskEngine, idempotency or audit

Defaults are deliberately inert: mode OBSERVE and no rules. Enabling
ENFORCE or adding a rule changes trading behaviour and is an owner decision.

Priority
--------
SAFETY_EXIT > PROTECTIVE_EXIT > Brain SELL > new-risk decisions. Within one
``run_once`` intents are submitted in that order; a caller that runs the
guard before the Brain's decisions gets the global ordering.

Idempotency
-----------
The request id is derived from the position identity (position_id +
opened_at) and the rule id, so a repeated trigger - the next cycle, a
retry, or a restart - is the same request and ExecutionManager's duplicate
and terminal-result handling make it execute at most once.
============================================================
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

logger = logging.getLogger("AtlasAI.ExitGuard")

OBSERVE = "OBSERVE"
ENFORCE = "ENFORCE"

SAFETY_EXIT = "SAFETY_EXIT"
PROTECTIVE_EXIT = "PROTECTIVE_EXIT"
_PRIORITY_ORDER = {SAFETY_EXIT: 0, PROTECTIVE_EXIT: 1}

RULE_MAX_LOSS_PCT = "MAX_LOSS_PCT"
# Task 023 (registry v5.106, policy manifest v3): close every open position inside a market's pre-close window
# (forex: the last ``minutes`` before the Friday 17:00 New York close). Owner 2026-10-26: 30 minutes, FOREX only.
RULE_WEEKEND_CLOSE = "WEEKEND_CLOSE"
# Task 025 (registry v5.108, policy manifest v4): a margin book's stop-out. When the margin level (equity / used
# margin, equity re-marked with every fresh price) is at or below ``threshold``, every open position is closed,
# largest loss first. Owner 2026-10-26: 100 % (threshold 1), FOREX only. An unreadable margin level exits.
RULE_STOP_OUT = "STOP_OUT"

EXIT_TRIGGERED = "EXIT_TRIGGERED"
EXIT_PENDING_PRICE = "EXIT_PENDING_PRICE"
EXIT_NOT_TRIGGERED = "EXIT_NOT_TRIGGERED"
EXIT_POSITION_INVALID = "EXIT_POSITION_INVALID"

OBSERVED = "OBSERVED"
SUBMITTED = "SUBMITTED"
EXECUTION_UNAVAILABLE = "EXIT_EXECUTION_UNAVAILABLE"

DEFAULT_MAX_PRICE_AGE_SECONDS = 120.0
UNREADABLE_LEVEL = "UNREADABLE"


@dataclass(frozen=True)
class ExitRule:
    """One owner-configured protective rule.

    MAX_LOSS_PCT: exit when (mark - average_entry) / average_entry is at or
    below ``-threshold`` (threshold 0.05 = a 5% loss).

    WEEKEND_CLOSE: exit when ``in_window(now, minutes)`` is True, ``now`` being the guard's clock as an aware UTC
    datetime and ``minutes`` this rule's own value, so the window is always the pinned one (forex:
    atlas_finance.forex.sessions.is_forex_pre_close). ``threshold`` is unused (None). A
    window check that raises or answers anything but False counts as inside the window: the rule only ever
    reduces risk, so an unsure answer exits.

    STOP_OUT: exit every position when the book's margin level is at or below ``threshold`` (1 = 100 %); see
    RULE_STOP_OUT. It must be a SAFETY_EXIT.
    """

    rule_id: str
    kind: str
    threshold: Decimal | None
    priority: str = PROTECTIVE_EXIT
    minutes: int | None = None
    in_window: Callable[[datetime, int], Any] | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not str(self.rule_id).strip():
            raise ValueError("rule_id is required")
        if self.kind == RULE_MAX_LOSS_PCT:
            if not isinstance(self.threshold, Decimal) or not (
                Decimal("0") < self.threshold < Decimal("1")
            ):
                raise ValueError("threshold must be a Decimal in (0, 1)")
            if self.minutes is not None or self.in_window is not None:
                raise ValueError("MAX_LOSS_PCT takes no minutes or window")
        elif self.kind == RULE_STOP_OUT:
            if not isinstance(self.threshold, Decimal) or not (Decimal("0") < self.threshold <= Decimal("5")):
                raise ValueError("STOP_OUT threshold must be a Decimal margin level in (0, 5]")
            if self.minutes is not None or self.in_window is not None:
                raise ValueError("STOP_OUT takes no minutes or window")
            if self.priority != SAFETY_EXIT:
                raise ValueError("STOP_OUT must be a SAFETY_EXIT")
        elif self.kind == RULE_WEEKEND_CLOSE:
            if self.threshold is not None:
                raise ValueError("WEEKEND_CLOSE takes no threshold")
            if isinstance(self.minutes, bool) or not isinstance(self.minutes, int) or not 1 <= self.minutes <= 120:
                raise ValueError("WEEKEND_CLOSE minutes must be an integer from 1 to 120")
            if not callable(self.in_window):
                raise ValueError("WEEKEND_CLOSE needs an in_window(now, minutes) check")
        else:
            raise ValueError(f"unsupported exit rule kind: {self.kind}")
        if self.priority not in _PRIORITY_ORDER:
            raise ValueError(f"unsupported exit priority: {self.priority}")


@dataclass(frozen=True)
class Mark:
    price: Decimal
    as_of: float  # epoch seconds


@dataclass
class ExitIntent:
    symbol: str
    state: str
    position_id: str | None = None
    rule_id: str | None = None
    priority: str | None = None
    base_quantity: Decimal | None = None
    price: Decimal | None = None
    request_id: str | None = None
    # Full-exit quote amount on the durable book's own basis
    # (base_quantity x durable mark_price): ExecutionManager sizes a
    # reduction against that basis, so only this exact amount closes the
    # whole position without stranding dust.
    exposure_quote: Decimal | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "state": self.state,
            "position_id": self.position_id,
            "rule_id": self.rule_id,
            "priority": self.priority,
            "base_quantity": (
                None if self.base_quantity is None else format(self.base_quantity, "f")
            ),
            "price": None if self.price is None else format(self.price, "f"),
            "request_id": self.request_id,
            "detail": dict(self.detail),
        }


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


class ExitGuard:
    NAME = "ExitGuard"
    VERSION = "1.0"

    def __init__(
        self,
        execution_manager: Any,
        portfolio_foundation: Any,
        *,
        rules: tuple[ExitRule, ...] = (),
        mode: str = OBSERVE,
        max_price_age_seconds: float = DEFAULT_MAX_PRICE_AGE_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if mode not in {OBSERVE, ENFORCE}:
            raise ValueError(f"unsupported ExitGuard mode: {mode}")

        ids = [rule.rule_id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate exit rule_id")

        self.execution_manager = execution_manager
        self.portfolio_foundation = portfolio_foundation
        self.rules = tuple(
            sorted(rules, key=lambda rule: _PRIORITY_ORDER[rule.priority])
        )
        self.mode = mode
        self.max_price_age_seconds = float(max_price_age_seconds)
        self.clock = clock

        self._lock = threading.RLock()
        self.last_run: list[dict[str, Any]] = []
        self.stats = {"runs": 0, "triggered": 0, "pending_price": 0,
                      "submitted": 0, "unavailable": 0}

    # =========================================================
    # EVALUATE (pure read)
    # =========================================================

    def evaluate(self, marks: Mapping[str, Mark]) -> list[ExitIntent]:
        try:
            snapshot = self.portfolio_foundation.snapshot()
            positions = snapshot["positions"]
        except Exception as exc:
            logger.warning("ExitGuard cannot read the durable book: %s", type(exc).__name__)
            return []

        now = self.clock()
        intents: list[ExitIntent] = []
        stop_out: Any = None
        if any(rule.kind == RULE_STOP_OUT for rule in self.rules):
            try:
                stop_out = self._stop_out_level(snapshot, marks, now)
            except Exception:
                logger.exception("ExitGuard cannot read the margin level; treated as a stop-out")
                stop_out = UNREADABLE_LEVEL

        for symbol, position in sorted(dict(positions).items()):
            intents.append(self._evaluate_position(str(symbol), position, marks, now, stop_out))

        def loss_first(intent: ExitIntent) -> Decimal:
            # Task 025: a stop-out closes the largest loss first.
            if intent.detail.get("rule_kind") != RULE_STOP_OUT:
                return Decimal("0")
            return -Decimal(str(intent.detail.get("loss_quote", "0")))

        intents.sort(
            key=lambda intent: (
                _PRIORITY_ORDER.get(intent.priority or "", len(_PRIORITY_ORDER)),
                loss_first(intent),
                intent.symbol,
            )
        )
        return intents

    def _fresh_price(self, symbol: str, marks: Mapping[str, Mark], now: float) -> Decimal | None:
        mark = marks.get(symbol) if isinstance(marks, Mapping) else None
        price = _decimal(getattr(mark, "price", None))
        as_of = getattr(mark, "as_of", None)
        fresh = (
            price is not None
            and price > 0
            and isinstance(as_of, (int, float))
            and not isinstance(as_of, bool)
            and 0 <= now - float(as_of) <= self.max_price_age_seconds
        )
        return price if fresh else None

    def _stop_out_level(self, snapshot: Mapping[str, Any], marks: Mapping[str, Mark],
                        now: float) -> Decimal | None:
        """The margin level, equity re-marked with every fresh price; None when the book holds no margin.

        A position without a fresh price keeps its durable mark. Raises when a figure is unreadable, which the
        caller treats as a stop-out (an unsure answer exits)."""
        used = _decimal(snapshot.get("used_margin"))
        equity = _decimal(snapshot.get("equity"))
        if used is None or equity is None or used < 0:
            raise ValueError("margin figures unreadable")
        if used == 0:
            return None
        for symbol, position in dict(snapshot["positions"]).items():
            price = self._fresh_price(str(symbol), marks, now)
            if price is None:
                continue
            base = _decimal(position.get("base_quantity"))
            durable = _decimal(position.get("mark_price"))
            if base is None or durable is None:
                raise ValueError("position figures unreadable")
            sign = -1 if position.get("side") == "SHORT" else 1     # Task 026: a short gains as the price falls
            equity += sign * base * (price - durable)
        return equity / used

    def _evaluate_position(
        self,
        symbol: str,
        position: Mapping[str, Any],
        marks: Mapping[str, Mark],
        now: float,
        stop_out: Any = None,
    ) -> ExitIntent:
        base = _decimal(position.get("base_quantity"))
        entry = _decimal(position.get("average_entry_price"))
        position_id = str(position.get("position_id") or "")

        if base is None or base <= 0 or entry is None or entry <= 0 or not position_id:
            return ExitIntent(symbol, EXIT_POSITION_INVALID, position_id or None)

        if not self.rules:
            return ExitIntent(symbol, EXIT_NOT_TRIGGERED, position_id, base_quantity=base)

        price = self._fresh_price(symbol, marks, now)

        if price is None:
            # Never sell blind on a stale or missing price.
            return ExitIntent(
                symbol, EXIT_PENDING_PRICE, position_id, base_quantity=base,
                detail={"max_price_age_seconds": self.max_price_age_seconds},
            )

        short = position.get("side") == "SHORT"
        # Task 026: the change is in the position's own favour, so a short's loss is a rising price
        change = (entry - price) / entry if short else (price - entry) / entry

        durable_mark = _decimal(position.get("mark_price"))

        for rule in self.rules:
            if rule.kind == RULE_STOP_OUT:
                triggered, detail = self._stop_out_triggered(rule, stop_out)
                detail.update(change=format(change, "f"), rule_kind=RULE_STOP_OUT,
                              loss_quote=format(max(-change * entry * base, Decimal("0")), "f"))
            elif rule.kind == RULE_WEEKEND_CLOSE:
                triggered = self._in_window(rule, now)
                detail = {"change": format(change, "f"), "window_minutes": rule.minutes}
            else:
                triggered = change <= -rule.threshold
                detail = {"change": format(change, "f"), "threshold": format(rule.threshold, "f")}
            if triggered:
                if durable_mark is None or durable_mark <= 0:
                    return ExitIntent(symbol, EXIT_POSITION_INVALID, position_id)
                return ExitIntent(
                    symbol, EXIT_TRIGGERED, position_id,
                    rule_id=rule.rule_id, priority=rule.priority,
                    base_quantity=base, price=price,
                    request_id=self._request_id(position, rule),
                    exposure_quote=base * durable_mark,
                    detail={**detail, **({"position_side": "SHORT"} if short else {})},
                )

        return ExitIntent(symbol, EXIT_NOT_TRIGGERED, position_id, base_quantity=base, price=price)

    @staticmethod
    def _stop_out_triggered(rule: ExitRule, stop_out: Any) -> tuple[bool, dict[str, Any]]:
        detail: dict[str, Any] = {"threshold": format(rule.threshold, "f")}
        if isinstance(stop_out, Decimal):
            detail["margin_level"] = format(stop_out, "f")
            return stop_out <= rule.threshold, detail
        if stop_out is None:   # no margin is used: nothing to stop out
            return False, detail
        detail["margin_level"] = UNREADABLE_LEVEL
        return True, detail

    @staticmethod
    def _in_window(rule: ExitRule, now: float) -> bool:
        try:
            return rule.in_window(datetime.fromtimestamp(float(now), UTC), rule.minutes) is not False
        except Exception:
            logger.exception("ExitGuard window check %s failed; treated as inside the window", rule.rule_id)
            return True

    @staticmethod
    def _request_id(position: Mapping[str, Any], rule: ExitRule) -> str:
        identity = "|".join(
            (
                str(position.get("position_id") or ""),
                str(position.get("opened_at") or ""),
                rule.rule_id,
            )
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return f"exitguard:{rule.priority.lower()}:{digest}"

    # =========================================================
    # RUN
    # =========================================================

    def run_once(self, marks: Mapping[str, Mark]) -> list[dict[str, Any]]:
        intents = self.evaluate(marks)
        outcomes: list[dict[str, Any]] = []

        with self._lock:
            self.stats["runs"] += 1

        for intent in intents:
            record = intent.to_dict()

            if intent.state == EXIT_PENDING_PRICE:
                with self._lock:
                    self.stats["pending_price"] += 1
                logger.warning("ExitGuard %s: %s", intent.symbol, EXIT_PENDING_PRICE)

            if intent.state != EXIT_TRIGGERED:
                outcomes.append(record)
                continue

            with self._lock:
                self.stats["triggered"] += 1

            if self.mode == OBSERVE:
                record["outcome"] = OBSERVED
                logger.warning(
                    "ExitGuard would exit %s (rule=%s priority=%s) - OBSERVE only",
                    intent.symbol, intent.rule_id, intent.priority,
                )
                outcomes.append(record)
                continue

            record.update(self._submit(intent))
            outcomes.append(record)

        with self._lock:
            self.last_run = [dict(item) for item in outcomes]

        return outcomes

    def _submit(self, intent: ExitIntent) -> dict[str, Any]:
        from core.execution_models import ExecutionRequest

        price = intent.price
        exposure = intent.exposure_quote
        assert price is not None and exposure is not None

        try:
            # Task 026: a short is closed by buying it back; ExecutionManager re-derives the side from the book
            decision = ExecutionRequest(
                intent.symbol,
                "BUY" if intent.detail.get("position_side") == "SHORT" else "SELL",
                float(price),
                format(exposure, "f"),
                # Confidence is irrelevant to a reduction (Phase-2 B1) and is
                # not a probability (E1); 0 asserts no conviction at all.
                confidence=0,
                risk="HIGH",
                request_id=intent.request_id,
                reduce_only=True,
            ).to_dict()
            decision["exit_priority"] = intent.priority
            decision["exit_rule_id"] = intent.rule_id

            result = self.execution_manager.execute(decision, None)

        except Exception as exc:
            with self._lock:
                self.stats["unavailable"] += 1
            logger.exception("ExitGuard submission failed for %s", intent.symbol)
            return {"outcome": EXECUTION_UNAVAILABLE, "error_type": type(exc).__name__}

        with self._lock:
            self.stats["submitted"] += 1

        status = result.get("status") if isinstance(result, Mapping) else None
        return {"outcome": SUBMITTED, "execution_status": status,
                "execution_result": dict(result) if isinstance(result, Mapping) else None}

    # =========================================================
    # STATUS
    # =========================================================

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.NAME,
                "version": self.VERSION,
                "mode": self.mode,
                "rules": [
                    {"rule_id": r.rule_id, "kind": r.kind,
                     "threshold": None if r.threshold is None else format(r.threshold, "f"),
                     "minutes": r.minutes, "priority": r.priority}
                    for r in self.rules
                ],
                "max_price_age_seconds": self.max_price_age_seconds,
                "statistics": dict(self.stats),
                "last_run": [dict(item) for item in self.last_run],
            }
