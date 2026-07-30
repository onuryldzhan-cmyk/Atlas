"""
ATLAS EXECUTION RISK GUARD v1.0

Central fail-closed protection for:
- daily loss limits
- maximum drawdown
- invalid equity input
- manual emergency halt
- operator-approved halt reset
"""

from __future__ import annotations

import math

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Callable


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
        }


class ExecutionRiskGuard:
    VERSION = "1.0"

    def __init__(
        self,
        *,
        starting_equity: float,
        max_daily_loss_percent: float,
        max_drawdown_percent: float,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._now_provider = (
            now_provider
            if now_provider is not None
            else lambda: datetime.now(UTC)
        )

        normalized_starting_equity = self._normalize_positive_number(
            starting_equity
        )

        normalized_daily_limit = self._normalize_non_negative_number(
            max_daily_loss_percent
        )

        normalized_drawdown_limit = self._normalize_non_negative_number(
            max_drawdown_percent
        )

        if normalized_starting_equity is None:
            raise ValueError(
                "starting_equity must be a positive finite number"
            )

        if normalized_daily_limit is None:
            raise ValueError(
                "max_daily_loss_percent must be a non-negative finite number"
            )

        if normalized_drawdown_limit is None:
            raise ValueError(
                "max_drawdown_percent must be a non-negative finite number"
            )

        now = self._normalize_datetime(
            self._now_provider()
        )

        self.starting_equity = normalized_starting_equity
        self.current_equity = normalized_starting_equity
        self.peak_equity = normalized_starting_equity
        self.daily_start_equity = normalized_starting_equity

        self.max_daily_loss_percent = normalized_daily_limit
        self.max_drawdown_percent = normalized_drawdown_limit

        self.daily_baseline_date = now.date()

        self.halted = False
        self.halt_reason: str | None = None
        self.halted_at: datetime | None = None

    @staticmethod
    def _normalize_positive_number(
        value: Any,
    ) -> float | None:
        if isinstance(
            value,
            bool,
        ):
            return None

        try:
            normalized = float(
                value
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
    def _normalize_non_negative_number(
        value: Any,
    ) -> float | None:
        if isinstance(
            value,
            bool,
        ):
            return None

        try:
            normalized = float(
                value
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

        if normalized < 0:
            return None

        return normalized

    @staticmethod
    def _normalize_datetime(
        value: datetime,
    ) -> datetime:
        if not isinstance(
            value,
            datetime,
        ):
            raise TypeError(
                "observed_at must be a datetime"
            )

        if value.tzinfo is None:
            return value.replace(
                tzinfo=UTC
            )

        return value.astimezone(
            UTC
        )

    @property
    def daily_loss_percent(
        self,
    ) -> float:
        if self.daily_start_equity <= 0:
            return 100.0

        loss = max(
            0.0,
            self.daily_start_equity - self.current_equity,
        )

        return (
            loss
            / self.daily_start_equity
            * 100.0
        )

    @property
    def drawdown_percent(
        self,
    ) -> float:
        if self.peak_equity <= 0:
            return 100.0

        drawdown = max(
            0.0,
            self.peak_equity - self.current_equity,
        )

        return (
            drawdown
            / self.peak_equity
            * 100.0
        )

    def _latch_halt(
        self,
        *,
        reason: str,
        observed_at: datetime | None = None,
    ) -> None:
        if self.halted:
            return

        timestamp = self._normalize_datetime(
            observed_at
            if observed_at is not None
            else self._now_provider()
        )

        self.halted = True
        self.halt_reason = str(
            reason
        ).strip() or "RISK_GUARD_HALTED"
        self.halted_at = timestamp

    def _evaluate_limits(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> None:
        if self.halted:
            return

        if (
            self.daily_loss_percent
            >= self.max_daily_loss_percent
        ):
            self._latch_halt(
                reason="MAX_DAILY_LOSS_EXCEEDED",
                observed_at=observed_at,
            )

            return

        if (
            self.drawdown_percent
            >= self.max_drawdown_percent
        ):
            self._latch_halt(
                reason="MAX_DRAWDOWN_EXCEEDED",
                observed_at=observed_at,
            )

    def record_equity(
        self,
        *,
        equity: Any,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = self._normalize_datetime(
            observed_at
            if observed_at is not None
            else self._now_provider()
        )

        normalized_equity = self._normalize_positive_number(
            equity
        )

        if normalized_equity is None:
            self._latch_halt(
                reason="INVALID_EQUITY",
                observed_at=timestamp,
            )

            return {
                "accepted": False,
                "status": "REJECTED",
                "reason": "INVALID_EQUITY",
            }

        if timestamp.date() > self.daily_baseline_date:
            self.roll_daily_baseline(
                observed_at=timestamp,
            )

        self.current_equity = normalized_equity

        if normalized_equity > self.peak_equity:
            self.peak_equity = normalized_equity

        self._evaluate_limits(
            observed_at=timestamp,
        )

        return {
            "accepted": True,
            "status": "RECORDED",
            "reason": "EQUITY_UPDATED",
            "equity": self.current_equity,
        }

    def authorize_order(
        self,
    ) -> dict[str, Any]:
        if self.halted:
            return RiskDecision(
                allowed=False,
                status="REJECTED",
                reason=self.halt_reason or "RISK_GUARD_HALTED",
            ).to_dict()

        self._evaluate_limits()

        if self.halted:
            return RiskDecision(
                allowed=False,
                status="REJECTED",
                reason=self.halt_reason or "RISK_GUARD_HALTED",
            ).to_dict()

        return RiskDecision(
            allowed=True,
            status="AUTHORIZED",
            reason="RISK_LIMITS_HEALTHY",
        ).to_dict()

    def halt(
        self,
        *,
        reason: str,
    ) -> dict[str, Any]:
        normalized_reason = str(
            reason
        ).strip() or "OPERATOR_HALT"

        self._latch_halt(
            reason=normalized_reason,
        )

        return {
            "halted": True,
            "status": "HALTED",
            "reason": self.halt_reason,
        }

    def reset_halt(
        self,
        *,
        operator_approved: bool,
    ) -> dict[str, Any]:
        if operator_approved is not True:
            return {
                "reset": False,
                "status": "REJECTED",
                "reason": "OPERATOR_APPROVAL_REQUIRED",
            }

        self.halted = False
        self.halt_reason = None
        self.halted_at = None

        self._evaluate_limits()

        if self.halted:
            return {
                "reset": False,
                "status": "REJECTED",
                "reason": self.halt_reason,
            }

        return {
            "reset": True,
            "status": "RESET",
            "reason": "HALT_RESET_BY_OPERATOR",
        }

    def roll_daily_baseline(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = self._normalize_datetime(
            observed_at
            if observed_at is not None
            else self._now_provider()
        )

        self.daily_start_equity = self.current_equity
        self.daily_baseline_date = timestamp.date()

        return {
            "rolled": True,
            "status": "ROLLED",
            "reason": "DAILY_BASELINE_UPDATED",
            "daily_start_equity": self.daily_start_equity,
            "daily_baseline_date": (
                self.daily_baseline_date.isoformat()
            ),
        }

    def status(
        self,
    ) -> dict[str, Any]:
        return {
            "name": "ExecutionRiskGuard",
            "version": self.VERSION,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "halted_at": (
                self.halted_at.isoformat()
                if self.halted_at is not None
                else None
            ),
            "starting_equity": self.starting_equity,
            "current_equity": self.current_equity,
            "peak_equity": self.peak_equity,
            "daily_start_equity": self.daily_start_equity,
            "daily_baseline_date": (
                self.daily_baseline_date.isoformat()
            ),
            "daily_loss_percent": self.daily_loss_percent,
            "drawdown_percent": self.drawdown_percent,
            "max_daily_loss_percent": (
                self.max_daily_loss_percent
            ),
            "max_drawdown_percent": (
                self.max_drawdown_percent
            ),
        }
