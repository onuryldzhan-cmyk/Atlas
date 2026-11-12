"""A3 / A4: AtlasApplication.health() must tell the truth about MarketLoop.

Before this coverage existed, AtlasApplication.health() returned only
{healthy, running, runtime_state, error_count}: it never read MarketLoop's
staleness verdict at all (A3), and it derived its market-data signal purely
from status()["running"], so a market loop whose daemon worker thread had
died still reported healthy=true (A4).

The two signals are deliberately treated differently:

* market_data_stale is REPORTED ONLY. MarketLoop.health() documents that
  staleness never affects healthy and never gates trading or decisions;
  that contract must not be quietly inverted one layer up.
* thread_alive GATES healthy. A dead worker thread under a loop that still
  believes it is running is an unhealthy application, not stale data.

Every application here is constructed against an isolated tmp_path state
directory so no test can touch the repository's real runtime state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.application import AtlasApplication


# Distinguishes "the caller said nothing about operational_state" (build the
# normal one) from "the caller said there is none" (omit the key entirely).
_UNSET = object()


class StubMarketLoop:
    """Minimal stand-in exposing MarketLoop's real health/status fields."""

    def __init__(
        self,
        *,
        running: bool = True,
        thread_alive: bool = True,
        market_data_stale: bool = False,
        expose_thread_alive: bool = True,
    ) -> None:
        self._running = running
        self._thread_alive = thread_alive
        self._market_data_stale = market_data_stale
        self._expose_thread_alive = expose_thread_alive

    def status(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": "MarketLoop",
            "running": self._running,
        }

        if self._expose_thread_alive:
            payload["thread_alive"] = self._thread_alive

        return payload

    def health(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "healthy": True,
            "running": self._running,
            "market_data_stale": self._market_data_stale,
        }

        if self._expose_thread_alive:
            payload["thread_alive"] = self._thread_alive

        return payload


class ExplodingMarketLoop:
    def status(self) -> dict[str, Any]:
        return {"running": True, "thread_alive": True}

    def health(self) -> dict[str, Any]:
        raise RuntimeError("market health unavailable")


class StubRunningService:
    """A started service, so only the market loop varies between cases."""

    def status(self) -> dict[str, Any]:
        return {"running": True, "healthy": True}


class StubExecutionService:
    """A started ExecutionManager stand-in exposing its real halt fields.

    ExecutionManager.status() reports ``running`` alongside a nested
    ``operational_state`` carrying execution_halted / recovery_required /
    halt_reason. The important shape to reproduce is that ``running`` stays
    True while halted - that is exactly the combination that used to report
    healthy.
    """

    def __init__(
        self,
        *,
        running: bool = True,
        execution_halted: bool = False,
        recovery_required: bool = False,
        halt_reason: Any = None,
        operational_state: Any = _UNSET,
    ) -> None:
        self._running = running
        self._execution_halted = execution_halted
        self._recovery_required = recovery_required
        self._halt_reason = halt_reason
        self._operational_state = operational_state

    def status(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": "ExecutionManager",
            "running": self._running,
        }

        if self._operational_state is _UNSET:
            payload["operational_state"] = {
                "execution_halted": self._execution_halted,
                "recovery_required": self._recovery_required,
                "halt_reason": self._halt_reason,
            }
        elif self._operational_state is not None:
            payload["operational_state"] = self._operational_state

        return payload


def _application(
    tmp_path: Path,
    market_loop: Any,
    execution: Any = None,
) -> AtlasApplication:
    """Build an application whose only unhealthy candidate is the market loop.

    A freshly constructed AtlasApplication is legitimately unhealthy: its
    ExecutionManager has not been started, so execution_status["running"] is
    False. Left that way, every assertion below would read False regardless
    of the market loop and prove nothing. The execution service is therefore
    replaced with a started stub, making the market loop the single
    independent variable.
    """

    application = AtlasApplication(
        state_directory=tmp_path / "state",
    )
    application.execution = (
        execution if execution is not None else StubRunningService()
    )
    application.market_loop = market_loop

    return application


# =====================================================================
# A3 - staleness is reported, never a health gate
# =====================================================================


def test_health_reports_market_data_staleness(tmp_path: Path) -> None:
    application = _application(
        tmp_path,
        StubMarketLoop(market_data_stale=True),
    )

    report = application.health()

    assert report["market_data_stale"] is True


def test_stale_market_data_does_not_flip_healthy(tmp_path: Path) -> None:
    """Mirrors MarketLoop's own contract: staleness is reported only."""

    fresh = _application(
        tmp_path,
        StubMarketLoop(market_data_stale=False),
    ).health()

    stale = _application(
        tmp_path,
        StubMarketLoop(market_data_stale=True),
    ).health()

    assert fresh["healthy"] is True
    assert stale["healthy"] is True
    assert stale["market_data_stale"] is True


def test_health_fails_closed_when_market_health_raises(
    tmp_path: Path,
) -> None:
    """A raising health() must not take the whole health report down."""

    report = _application(
        tmp_path,
        ExplodingMarketLoop(),
    ).health()

    assert report["market_data_stale"] is None
    assert report["market_data_stale_reason"] == "MARKET_HEALTH_UNREADABLE"


def test_unreadable_market_health_is_distinct_from_absent(
    tmp_path: Path,
) -> None:
    """An unreadable source needs its own reason code, not a shared None.

    Both cases report market_data_stale=None, so without a reason code an
    operator cannot tell a market loop that is simply not attached from one
    whose health() is throwing - and the remediation for the two differs.
    """

    unreadable = _application(
        tmp_path,
        ExplodingMarketLoop(),
    ).health()

    absent = _application(tmp_path, None).health()

    assert unreadable["market_data_stale"] == absent["market_data_stale"]
    assert unreadable["market_data_stale_reason"] == "MARKET_HEALTH_UNREADABLE"
    assert absent["market_data_stale_reason"] is None


# =====================================================================
# A4 - a dead worker thread is never healthy
# =====================================================================


def test_dead_market_thread_is_not_healthy(tmp_path: Path) -> None:
    report = _application(
        tmp_path,
        StubMarketLoop(running=True, thread_alive=False),
    ).health()

    assert report["market_loop_thread_alive"] is False
    assert report["healthy"] is False


def test_live_market_thread_stays_healthy(tmp_path: Path) -> None:
    report = _application(
        tmp_path,
        StubMarketLoop(running=True, thread_alive=True),
    ).health()

    assert report["market_loop_thread_alive"] is True
    assert report["healthy"] is True


def test_absent_thread_liveness_is_unknown_not_dead(
    tmp_path: Path,
) -> None:
    """A service that cannot report liveness is not evidence of a dead thread."""

    report = _application(
        tmp_path,
        StubMarketLoop(expose_thread_alive=False),
    ).health()

    assert report["market_loop_thread_alive"] is None
    assert report["healthy"] is True


def test_health_without_a_market_loop_is_unchanged(
    tmp_path: Path,
) -> None:
    report = _application(tmp_path, None).health()

    assert report["healthy"] is True
    assert report["market_data_stale"] is None
    assert report["market_data_stale_reason"] is None
    assert report["market_loop_thread_alive"] is None


# =====================================================================
# A halted runtime is never healthy
# =====================================================================
#
# ExecutionManager.start() returns True when it finds corrupt or unresolved
# durable state: it sets execution_halted / recovery_required and keeps
# running True, and every later admission fails closed with
# RECOVERY_REQUIRED. health() read only execution_status["running"], so a
# runtime that will never trade again reported healthy=true - and under
# process supervision that is indistinguishable from a working Atlas,
# because the process is alive and answering.
#
# Only an explicit True flips healthy. Absent or unreadable recovery state is
# unknown, exactly as an absent thread_alive is above.


def test_recovery_required_execution_is_not_healthy(tmp_path: Path) -> None:
    application = _application(
        tmp_path,
        StubMarketLoop(),
        StubExecutionService(running=True, recovery_required=True),
    )

    report = application.health()

    assert report["execution_recovery_required"] is True
    assert report["healthy"] is False

    # The condition that used to mask it, asserted directly: the execution
    # service still reports running while halted, so "running" alone can
    # never be the health signal for it.
    assert application.execution.status()["running"] is True


def test_halted_execution_is_not_healthy(tmp_path: Path) -> None:
    """execution_halted gates healthy on its own, not only via recovery."""

    report = _application(
        tmp_path,
        StubMarketLoop(),
        StubExecutionService(
            running=True,
            execution_halted=True,
            recovery_required=False,
        ),
    ).health()

    assert report["execution_halted"] is True
    assert report["execution_recovery_required"] is False
    assert report["healthy"] is False


def test_operational_execution_stays_healthy(tmp_path: Path) -> None:
    """The control case: a running, unhalted execution service is healthy."""

    report = _application(
        tmp_path,
        StubMarketLoop(),
        StubExecutionService(running=True),
    ).health()

    assert report["execution_halted"] is False
    assert report["execution_recovery_required"] is False
    assert report["healthy"] is True


def test_absent_operational_state_does_not_flip_healthy(
    tmp_path: Path,
) -> None:
    """Unknown is not evidence of a halt.

    This is also the startup window: health() can be called before an
    execution service has published any recovery state at all, and that must
    not read as a halt.
    """

    report = _application(
        tmp_path,
        StubMarketLoop(),
        StubExecutionService(running=True, operational_state=None),
    ).health()

    assert report["execution_halted"] is None
    assert report["execution_recovery_required"] is None
    assert report["healthy"] is True


def test_unrecognized_operational_state_does_not_flip_healthy(
    tmp_path: Path,
) -> None:
    """A non-dictionary operational_state is unreadable, not a halt.

    Flipping healthy here would let any shape change in a dependency take
    the runtime down; reporting it as a halt would be a claim the data does
    not support.
    """

    report = _application(
        tmp_path,
        StubMarketLoop(),
        StubExecutionService(
            running=True,
            operational_state="RECOVERY_REQUIRED",
        ),
    ).health()

    assert report["execution_halted"] is None
    assert report["execution_recovery_required"] is None
    assert report["healthy"] is True


def test_health_never_publishes_the_halt_reason(tmp_path: Path) -> None:
    """The halt reason must not reach the health payload.

    health() is returned verbatim to /api/health by
    web_app._safe_runtime_health, and ExecutionManager.halt_reason can carry
    a portfolio-foundation diagnostic embedding a raw execution_id,
    idempotency_key, position_id, or archive line number. The booleans say an
    operator is needed; the logs and status() say why.
    """

    report = _application(
        tmp_path,
        StubMarketLoop(),
        StubExecutionService(
            running=True,
            execution_halted=True,
            recovery_required=True,
            halt_reason=(
                "FINANCIAL_APPLIED_AUTHORITY_CORRUPT: "
                "execution_id=EXEC-SECRET-0001 line=42"
            ),
        ),
    ).health()

    assert report["healthy"] is False
    assert "EXEC-SECRET-0001" not in repr(report)
    assert "halt_reason" not in report


# =====================================================================
# Classified execution_halt_reason
# =====================================================================


def test_health_publishes_an_allowlisted_halt_reason_verbatim(
    tmp_path: Path,
) -> None:
    """A known-safe constant code is published as-is."""

    report = _application(
        tmp_path,
        StubMarketLoop(),
        StubExecutionService(
            running=True,
            execution_halted=True,
            recovery_required=True,
            halt_reason="INSTRUMENT_RULES_UNAVAILABLE",
        ),
    ).health()

    assert report["execution_halt_reason"] == "INSTRUMENT_RULES_UNAVAILABLE"


def test_health_classifies_an_unrecognized_halt_reason_as_unclassified(
    tmp_path: Path,
) -> None:
    """Free-form diagnostic text collapses to the generic safe code.

    This is the same scenario test_health_never_publishes_the_halt_reason
    exercises, asserted from the other direction: the classified field must
    carry a safe, generic value rather than silently being absent.
    """

    from core.application import UNCLASSIFIED_EXECUTION_HALT_REASON

    report = _application(
        tmp_path,
        StubMarketLoop(),
        StubExecutionService(
            running=True,
            execution_halted=True,
            recovery_required=True,
            halt_reason=(
                "FINANCIAL_APPLIED_AUTHORITY_CORRUPT: "
                "execution_id=EXEC-SECRET-0001 line=42"
            ),
        ),
    ).health()

    assert report["execution_halt_reason"] == UNCLASSIFIED_EXECUTION_HALT_REASON
    assert "EXEC-SECRET-0001" not in repr(report)


def test_health_reports_no_halt_reason_when_not_halted(
    tmp_path: Path,
) -> None:
    report = _application(
        tmp_path,
        StubMarketLoop(),
        StubExecutionService(running=True),
    ).health()

    assert report["execution_halted"] is False
    assert report["execution_recovery_required"] is False
    assert report["execution_halt_reason"] is None


def test_health_classifies_a_non_string_halt_reason_as_unclassified(
    tmp_path: Path,
) -> None:
    """A malformed halt_reason (wrong type) must not be echoed or crash."""

    from core.application import UNCLASSIFIED_EXECUTION_HALT_REASON

    report = _application(
        tmp_path,
        StubMarketLoop(),
        StubExecutionService(
            running=True,
            execution_halted=True,
            recovery_required=True,
            halt_reason={"unexpected": "shape"},
        ),
    ).health()

    assert report["execution_halt_reason"] == UNCLASSIFIED_EXECUTION_HALT_REASON
