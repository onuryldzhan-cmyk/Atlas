"""
ATLAS EXECUTION SAFETY GATE v1.0

Central fail-closed authorization gate for live order execution.

Security principles
-------------------
- Default execution mode is PAPER.
- LIVE requires both:
    1. mode == LIVE
    2. live_enabled == True
- Kill switch always blocks live execution.
- Invalid modes fall back to PAPER.
- Live credentials may be required explicitly.
- Authorization returns structured decisions.
- This module never places orders itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping


_TRUE_VALUES = {
    "1",
    "true",
    "yes",
    "on",
    "enabled",
}

_VALID_MODES = {
    "PAPER",
    "LIVE",
}


def _as_bool(
    value: Any,
    *,
    default: bool = False,
) -> bool:
    """
    Convert common environment/config values to bool safely.
    """

    if isinstance(value, bool):
        return value

    if value is None:
        return default

    normalized = str(value).strip().lower()

    if not normalized:
        return default

    return normalized in _TRUE_VALUES


def _normalize_mode(
    value: Any,
) -> str:
    """
    Normalize execution mode and fail closed to PAPER.
    """

    normalized = str(
        value or "PAPER"
    ).strip().upper()

    if normalized not in _VALID_MODES:
        return "PAPER"

    return normalized


@dataclass(frozen=True)
class ExecutionAuthorization:
    """
    Structured execution authorization decision.
    """

    allowed: bool
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
        }


class ExecutionSafetyGate:
    """
    Central authorization gate for live order execution.

    This gate does not submit orders. Callers must authorize immediately
    before invoking an exchange adapter's live order method.
    """

    VERSION = "1.0"

    MODE_PAPER = "PAPER"
    MODE_LIVE = "LIVE"

    def __init__(
        self,
        *,
        mode: str = MODE_PAPER,
        live_enabled: bool = False,
        kill_switch: bool = False,
        require_credentials: bool = False,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.mode = _normalize_mode(
            mode
        )

        self.live_enabled = _as_bool(
            live_enabled,
            default=False,
        )

        self.kill_switch = _as_bool(
            kill_switch,
            default=False,
        )

        self.require_credentials = _as_bool(
            require_credentials,
            default=False,
        )

        self._environment = (
            environment
            if environment is not None
            else os.environ
        )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "ExecutionSafetyGate":
        """
        Build the gate from environment variables.

        Missing or invalid values fail closed.
        """

        env = (
            environment
            if environment is not None
            else os.environ
        )

        return cls(
            mode=env.get(
                "ATLAS_EXECUTION_MODE",
                cls.MODE_PAPER,
            ),
            live_enabled=_as_bool(
                env.get(
                    "ATLAS_LIVE_ENABLED",
                    False,
                )
            ),
            kill_switch=_as_bool(
                env.get(
                    "ATLAS_KILL_SWITCH",
                    False,
                )
            ),
            require_credentials=_as_bool(
                env.get(
                    "ATLAS_REQUIRE_LIVE_CREDENTIALS",
                    False,
                )
            ),
            environment=env,
        )

    @property
    def live_allowed(self) -> bool:
        """
        Return whether the non-credential live gates currently pass.
        """

        return bool(
            self.mode == self.MODE_LIVE
            and self.live_enabled
            and not self.kill_switch
        )

    def _credentials_available(self) -> bool:
        """
        Check whether both live credential values are present.
        """

        api_key = str(
            self._environment.get(
                "BINANCE_API_KEY",
                "",
            )
        ).strip()

        api_secret = str(
            self._environment.get(
                "BINANCE_API_SECRET",
                "",
            )
        ).strip()

        return bool(
            api_key
            and api_secret
        )

    def authorize_live_order(
        self,
    ) -> dict[str, Any]:
        """
        Authorize or reject a live order request.

        Rejection order is intentional:
        1. kill switch
        2. execution mode
        3. explicit live enablement
        4. credentials, when required
        """

        if self.kill_switch:
            return ExecutionAuthorization(
                allowed=False,
                status="REJECTED",
                reason="KILL_SWITCH_ACTIVE",
            ).to_dict()

        if self.mode != self.MODE_LIVE:
            return ExecutionAuthorization(
                allowed=False,
                status="REJECTED",
                reason="EXECUTION_MODE_NOT_LIVE",
            ).to_dict()

        if not self.live_enabled:
            return ExecutionAuthorization(
                allowed=False,
                status="REJECTED",
                reason="LIVE_NOT_EXPLICITLY_ENABLED",
            ).to_dict()

        if (
            self.require_credentials
            and not self._credentials_available()
        ):
            return ExecutionAuthorization(
                allowed=False,
                status="REJECTED",
                reason="LIVE_CREDENTIALS_MISSING",
            ).to_dict()

        return ExecutionAuthorization(
            allowed=True,
            status="AUTHORIZED",
            reason="LIVE_DOUBLE_GATE_PASSED",
        ).to_dict()

    def status(self) -> dict[str, Any]:
        """
        Return non-secret gate state for diagnostics.
        """

        return {
            "version": self.VERSION,
            "mode": self.mode,
            "live_enabled": self.live_enabled,
            "kill_switch": self.kill_switch,
            "require_credentials": self.require_credentials,
            "credentials_available": (
                self._credentials_available()
                if self.require_credentials
                else None
            ),
            "live_allowed": self.live_allowed,
        }
