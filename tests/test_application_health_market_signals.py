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


def _application(
    tmp_path: Path,
    market_loop: Any,
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
    application.execution = StubRunningService()
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
