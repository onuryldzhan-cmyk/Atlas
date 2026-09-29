"""Liveness / readiness (registry v5.58): unknown is never ready."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from observability import readiness

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _status(**over):
    s = {"runtime": {"state": "RUNNING", "healthy": True, "emergency_mode": False},
         "market_loop": {"running": True, "last_cycle": (NOW - timedelta(seconds=5)).isoformat(),
                         "market_data_staleness": {"BTCUSDT": {"stale": False}, "ETHUSDT": {"stale": False}}},
         "execution": {"mode": "PAPER", "operational_state": {"execution_halted": False, "recovery_required": False},
                       "venue_rules": {"status": "FRESH"}}}
    s.update(over)
    return s


def test_all_good_is_ready():
    out = readiness.evaluate(_status(), NOW)
    assert out["ready"] and all(c["state"] == "OK" for c in out["checks"])


def test_each_failure_blocks_readiness():
    bad = [
        {"runtime": {"healthy": False, "state": "DEGRADED"}},
        {"runtime": {"healthy": True, "emergency_mode": True}},
        {"market_loop": {"running": True, "last_cycle": (NOW - timedelta(seconds=90)).isoformat(),
                         "market_data_staleness": {"BTCUSDT": {"stale": False}}}},
        {"market_loop": {"running": True, "last_cycle": NOW.isoformat(), "market_data_staleness": {"BTCUSDT": {"stale": True}}}},
        {"execution": {"operational_state": {"execution_halted": True, "recovery_required": False}, "venue_rules": {"status": "FRESH"}}},
        {"execution": {"operational_state": {"execution_halted": False, "recovery_required": False}, "venue_rules": {"status": "STALE"}}},
    ]
    for override in bad:
        assert readiness.evaluate(_status(**override), NOW)["ready"] is False, override


def test_missing_information_is_unknown_not_ready():
    assert readiness.evaluate({"available": False, "reason": "RUNTIME_NOT_ATTACHED"}, NOW)["ready"] is False
    out = readiness.evaluate(_status(market_loop={}), NOW)
    assert out["ready"] is False and any(c["state"] == "UNKNOWN" for c in out["checks"])


def test_routes():
    from fastapi.testclient import TestClient

    import web_app

    client = TestClient(web_app.create_app())
    assert client.get("/api/liveness").json()["alive"] is True
    r = client.get("/api/readiness")
    assert r.status_code == 503 and r.json()["ready"] is False  # no runtime attached
