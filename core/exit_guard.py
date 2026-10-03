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
- open, add to, or resize risk (it only ever emits a full-exit SELL)
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
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

logger = logging.getLogger("AtlasAI.ExitGuard")

OBSERVE = "OBSERVE"
ENFORCE = "ENFORCE"

SAFETY_EXIT = "SAFETY_EXIT"
PROTECTIVE_EXIT = "PROTECTIVE_EXIT"
_PRIORITY_ORDER = {SAFETY_EXIT: 0, PROTECTIVE_EXIT: 1}

RULE_MAX_LOSS_PCT = "MAX_LOSS_PCT"

EXIT_TRIGGERED = "EXIT_TRIGGERED"
EXIT_PENDING_PRICE = "EXIT_PENDING_PRICE"
EXIT_NOT_TRIGGERED = "EXIT_NOT_TRIGGERED"
EXIT_POSITION_INVALID = "EXIT_POSITION_INVALID"

OBSERVED = "OBSERVED"
SUBMITTED = "SUBMITTED"
EXECUTION_UNAVAILABLE = "EXIT_EXECUTION_UNAVAILABLE"

DEFAULT_MAX_PRICE_AGE_SECONDS = 120.0


@dataclass(frozen=True)
class ExitRule:
    """One owner-configured protective rule.

    MAX_LOSS_PCT: exit when (mark - average_entry) / average_entry is at or
    below ``-threshold`` (threshold 0.05 = a 5% loss).
    """

    rule_id: str
    kind: str
    threshold: Decimal
    priority: str = PROTECTIVE_EXIT

    def __post_init__(self) -> None:
        if not str(self.rule_id).strip():
            raise ValueError("rule_id is required")
        if self.kind != RULE_MAX_LOSS_PCT:
            raise ValueError(f"unsupported exit rule kind: {self.kind}")
        if not isinstance(self.threshold, Decimal) or not (
            Decimal("0") < self.threshold < Decimal("1")
        ):
            raise ValueError("threshold must be a Decimal in (0, 1)")
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
            positions = self.portfolio_foundation.snapshot()["positions"]
        except Exception as exc:
            logger.warning("ExitGuard cannot read the durable book: %s", type(exc).__name__)
            return []

        now = self.clock()
        intents: list[ExitIntent] = []

        for symbol, position in sorted(dict(positions).items()):
            intents.append(self._evaluate_position(str(symbol), position, marks, now))

        intents.sort(
            key=lambda intent: (
                _PRIORITY_ORDER.get(intent.priority or "", len(_PRIORITY_ORDER)),
                intent.symbol,
            )
        )
        return intents

    def _evaluate_position(
        self,
        symbol: str,
        position: Mapping[str, Any],
        marks: Mapping[str, Mark],
        now: float,
    ) -> ExitIntent:
        base = _decimal(position.get("base_quantity"))
        entry = _decimal(position.get("average_entry_price"))
        position_id = str(position.get("position_id") or "")

        if base is None or base <= 0 or entry is None or entry <= 0 or not position_id:
            return ExitIntent(symbol, EXIT_POSITION_INVALID, position_id or None)

        if not self.rules:
            return ExitIntent(symbol, EXIT_NOT_TRIGGERED, position_id, base_quantity=base)

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

        if not fresh:
            # Never sell blind on a stale or missing price.
            return ExitIntent(
                symbol, EXIT_PENDING_PRICE, position_id, base_quantity=base,
                detail={"max_price_age_seconds": self.max_price_age_seconds},
            )

        change = (price - entry) / entry

        durable_mark = _decimal(position.get("mark_price"))

        for rule in self.rules:
            if change <= -rule.threshold:
                if durable_mark is None or durable_mark <= 0:
                    return ExitIntent(symbol, EXIT_POSITION_INVALID, position_id)
                return ExitIntent(
                    symbol, EXIT_TRIGGERED, position_id,
                    rule_id=rule.rule_id, priority=rule.priority,
                    base_quantity=base, price=price,
                    request_id=self._request_id(position, rule),
                    exposure_quote=base * durable_mark,
                    detail={"change": format(change, "f"),
                            "threshold": format(rule.threshold, "f")},
                )

        return ExitIntent(symbol, EXIT_NOT_TRIGGERED, position_id, base_quantity=base, price=price)

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
            decision = ExecutionRequest(
                intent.symbol,
                "SELL",
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
                     "threshold": format(r.threshold, "f"), "priority": r.priority}
                    for r in self.rules
                ],
                "max_price_age_seconds": self.max_price_age_seconds,
                "statistics": dict(self.stats),
                "last_run": [dict(item) for item in self.last_run],
            }
