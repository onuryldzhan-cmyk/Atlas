"""Task 013 (registry v5.97): read-only reliability signals, delta tests only.

Pinned here: the market feed's DEGRADED -> recovered counters and its status(), MarketLoop's per-reason
contract rejection record, their /api/status allowlist entries (codes, counts and timestamps only; never
free text, paths or decisions), the two conditional readiness checks and their windows. Readiness,
allowlist, feed and contract behaviour that existed before is covered by its own suites.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import web_app
from observability import readiness
from tests.core.test_task012_brain_decision_contract import StampedBrain, _stamp, loop_and_app  # noqa: F401
from tests.test_readiness import NOW, _status

# -- the market feed --------------------------------------------------------------------------------


def _flaky_feed(failures: int):
    from exchange.market_feed import MarketFeed
    from tests.phase6.test_market_feed_compatibility import FakeProvider

    class Flaky(FakeProvider):
        remaining = failures

        def get_candles(self, symbol, timeframe="5m", limit=100):
            if Flaky.remaining > 0:
                Flaky.remaining -= 1
                raise ConnectionError("stream stalled at /secret/path")
            return super().get_candles(symbol, timeframe, limit)

    return MarketFeed(provider=Flaky(), publish_events=False, collect_metrics=False)


def test_the_feed_counts_each_degradation_and_recovery_with_its_time():
    feed = _flaky_feed(3)
    feed.start()
    try:
        before = feed.status()
        assert (before["available"], before["status_supported"]) == (True, True)
        assert (before["state"], before["degradations"], before["recoveries"]) == ("RUNNING", 0, 0)
        assert before["last_degraded_at"] is None and before["last_recovered_at"] is None
        for _ in range(3):
            with pytest.raises(Exception):
                feed.candles("BTCUSDT", "1m", 50)
        degraded = feed.status()
        assert (degraded["state"], degraded["healthy"], degraded["degradations"], degraded["recoveries"]) == \
            ("DEGRADED", False, 1, 0)
        assert datetime.fromisoformat(degraded["last_degraded_at"]).tzinfo is not None
        feed.candles("BTCUSDT", "1m", 50)
        recovered = feed.status()
        assert (recovered["state"], recovered["healthy"], recovered["degradations"], recovered["recoveries"]) == \
            ("RUNNING", True, 1, 1)
        assert recovered["last_recovered_at"] >= recovered["last_degraded_at"]
        assert recovered["consecutive_failures"] == 0
    finally:
        feed.stop()


def test_the_feed_status_never_carries_the_provider_error_text():
    feed = _flaky_feed(3)
    feed.start()
    try:
        for _ in range(3):
            with pytest.raises(Exception):
                feed.candles("BTCUSDT", "1m", 50)
        status = feed.status()
        assert set(status) == {"available", "status_supported", "healthy", "state", "consecutive_failures",
                               "degradations", "recoveries", "last_degraded_at", "last_recovered_at"}
        assert "stalled" not in json.dumps(status) and "/secret" not in json.dumps(status)
    finally:
        feed.stop()


def test_a_refused_transition_is_not_counted():
    feed = _flaky_feed(0)
    feed.start()
    try:
        service = feed.service
        assert service._recover_if_degraded() is False  # RUNNING: nothing to recover
        assert service._degrade_if_still_failing("no streak") is False  # no failure streak owns it
        assert (feed.status()["degradations"], feed.status()["recoveries"]) == (0, 0)
    finally:
        feed.stop()


# -- MarketLoop's contract rejection record ----------------------------------------------------------


def test_the_contract_record_appears_only_after_a_rejection_and_counts_by_reason(loop_and_app):
    loop, _app = loop_and_app
    assert "decision_contract" not in loop.status()  # the default status is unchanged
    loop.brain = StampedBrain("BUY", _stamp(loop, 600))
    loop.process_symbol("BTCUSDT")
    loop.process_symbol("BTCUSDT")  # the candle was not marked, so the same stale decision is refused again
    loop.brain = StampedBrain("BUY", "yesterday")
    loop.process_symbol("BTCUSDT")
    record = loop.status()["decision_contract"]
    assert record["rejections_by_reason"] == {"DECISION_STALE": 2, "CREATED_AT_INVALID": 1}
    assert record["last_rejection"]["reason"] == "CREATED_AT_INVALID"
    assert set(record) == {"rejections_by_reason", "last_rejection"} and set(record["last_rejection"]) == {"reason", "at"}
    assert datetime.fromisoformat(record["last_rejection"]["at"]).tzinfo is not None
    assert loop.metrics["decision_contract_rejected"] == 3


class _CountingLock:
    """Wraps MarketLoop.lock and counts how deeply its with-blocks are nested (public behaviour only).

    The depth is shared by all threads, so this is sound only because the fixture never starts the loop thread.
    """

    def __init__(self, inner) -> None:
        self.inner, self.depth = inner, 0

    def __enter__(self):
        self.inner.acquire()
        self.depth += 1
        return self

    def __exit__(self, *exc) -> bool:
        self.depth -= 1
        self.inner.release()
        return False


class _LockCheckedDict(dict):
    def __init__(self, lock: _CountingLock) -> None:
        super().__init__()
        self.lock = lock

    def _held(self) -> None:
        assert self.lock.depth > 0, "contract record touched without MarketLoop.lock"

    def get(self, *args):
        self._held()
        return super().get(*args)

    def __setitem__(self, key, value) -> None:
        self._held()
        super().__setitem__(key, value)

    def __len__(self) -> int:
        self._held()
        return super().__len__()

    def __iter__(self):
        self._held()
        return super().__iter__()


def test_the_contract_record_is_written_and_read_only_under_the_loop_lock(loop_and_app):
    """Single-threaded and deterministic (review 35 M-1): the per-reason map's get, item assignment, length and
    iteration must happen under the lock. Not checked here: the latest-rejection record and the copy status() makes."""
    loop, _app = loop_and_app
    loop.lock = _CountingLock(loop.lock)
    loop._contract_rejections = _LockCheckedDict(loop.lock)
    assert "decision_contract" not in loop.status()  # read while empty
    loop.brain = StampedBrain("BUY", _stamp(loop, 600))
    loop.process_symbol("BTCUSDT")  # written
    assert loop.status()["decision_contract"]["rejections_by_reason"] == {"DECISION_STALE": 1}


def test_a_published_contract_record_is_a_snapshot_not_the_live_record(loop_and_app):
    loop, _app = loop_and_app
    loop.brain = StampedBrain("BUY", _stamp(loop, 600))
    loop.process_symbol("BTCUSDT")
    snapshot = loop.status()["decision_contract"]
    loop.process_symbol("BTCUSDT")  # a later rejection must not change what was already published
    assert snapshot["rejections_by_reason"] == {"DECISION_STALE": 1}
    assert loop.status()["decision_contract"]["rejections_by_reason"] == {"DECISION_STALE": 2}


# -- the /api/status allowlist -----------------------------------------------------------------------


class _Runtime:
    def __init__(self, status: dict[str, Any]) -> None:
        self._status = status

    def status(self) -> dict[str, Any]:
        return self._status


def _published(status: dict[str, Any]) -> dict[str, Any]:
    return web_app._safe_runtime_status(_Runtime(status))


def test_the_status_route_publishes_contract_codes_and_counts_only():
    hostile = {
        "market_loop": {"name": "MarketLoop", "decision_contract": {
            "rejections_by_reason": {"DECISION_STALE": 2, "/etc/passwd": 1, "bad code; rm -rf /": 3,
                                     "lowercase_free_text": 5, "SYMBOL_MISMATCH": "many"},
            "last_rejection": {"reason": "decision-stale-text", "at": "2026-10-17T10:00:00+00:00",
                               "detail": "free text", "decision": {"action": "BUY"}},
            "decision": {"action": "BUY", "price": 1.0},
        }},
    }
    published = _published(hostile)["market_loop"]["decision_contract"]
    assert published == {
        "rejections_by_reason": {"DECISION_STALE": 2, "SYMBOL_MISMATCH": None},
        "last_rejection": {"reason": None, "at": "2026-10-17T10:00:00+00:00"},
    }


def test_the_status_route_publishes_the_feed_state_counts_and_times_only():
    hostile = {"market_feed": {
        "available": True, "status_supported": True, "healthy": False, "state": "DEGRADED",
        "consecutive_failures": 3, "degradations": 1, "recoveries": 0,
        "last_degraded_at": "2026-10-17T10:00:00+00:00", "last_recovered_at": "C-Users-owner",
        "last_error": "Market-data provider reached 3 consecutive request failures at /secret",
        "provider": "BinancePublicProvider",
    }}
    assert _published(hostile)["market_feed"] == {
        "available": True, "status_supported": True, "healthy": False, "state": "DEGRADED",
        "consecutive_failures": 3, "degradations": 1, "recoveries": 0,
        "last_degraded_at": "2026-10-17T10:00:00+00:00", "last_recovered_at": None,
    }
    assert _published({"market_feed": {"state": "degraded-free-text"}})["market_feed"] == {"state": None}


def test_the_real_application_status_reaches_the_route_with_the_new_feed_fields_only(tmp_path):
    from tests.test_block5c_upstream_sizing_authority import application

    app = application(tmp_path)
    published = _published(app.status())
    assert set(published["market_feed"]) == {"available", "status_supported", "healthy", "state",
                                             "consecutive_failures", "degradations", "recoveries",
                                             "last_degraded_at", "last_recovered_at"}
    assert "decision_contract" not in published["market_loop"]


# -- readiness ---------------------------------------------------------------------------------------


def _with_contract(seconds_ago: float | None, counts=None) -> dict[str, Any]:
    status = _status()
    status["market_loop"]["decision_contract"] = {
        "rejections_by_reason": counts if counts is not None else {"DECISION_STALE": 4, "CREATED_AT_INVALID": 1},
        "last_rejection": {"reason": "DECISION_STALE",
                           "at": None if seconds_ago is None else (NOW - timedelta(seconds=seconds_ago)).isoformat()},
    }
    return status


def _check(result: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((c for c in result["checks"] if c["check"] == name), None)


@pytest.mark.parametrize("seconds_ago, state", [
    (0, "FAIL"), (readiness.RECENT_CONTRACT_REJECTION_S, "FAIL"),
    (readiness.RECENT_CONTRACT_REJECTION_S + 0.001, None), (None, "UNKNOWN"),
])
def test_a_recent_contract_rejection_blocks_readiness_and_an_old_one_does_not(seconds_ago, state):
    result = readiness.evaluate(_with_contract(seconds_ago), NOW)
    check = _check(result, "decision_contract")
    if state is None:
        assert check is None and result["ready"] is True
    else:
        assert check["state"] == state and result["ready"] is False
        assert "CREATED_AT_INVALID x1, DECISION_STALE x4" in check["detail"] and "latest DECISION_STALE" in check["detail"]


def test_the_contract_window_is_five_minutes():
    assert readiness.RECENT_CONTRACT_REJECTION_S == 300.0


@pytest.mark.parametrize("feed, expected", [
    ({"state": "DEGRADED"}, "FAIL"), ({"state": "RUNNING"}, None), ({"state": "STOPPED"}, "FAIL"),
    ({"state": "FAILED"}, "FAIL"), ({"state": "CREATED"}, "FAIL"), ({"state": "STARTING"}, "FAIL"),
    ({"state": "STOPPING"}, "FAIL"), ({"state": None}, "UNKNOWN"), ({"available": True, "healthy": False}, "UNKNOWN"),
    ({"available": True, "status_supported": False}, None),
])
def test_a_feed_that_is_not_running_blocks_readiness(feed, expected):
    status = _status(market_feed={**feed, "degradations": 2, "recoveries": 1,
                                  "last_degraded_at": "2026-09-29T11:59:00+00:00"})
    result = readiness.evaluate(status, NOW)
    check = _check(result, "market_feed")
    if expected is None:
        assert check is None and result["ready"] is True
    else:
        assert check["state"] == expected and result["ready"] is False
    if feed.get("state") == "DEGRADED":
        assert "2 degradation(s), 1 recovery(ies)" in check["detail"] and "2026-09-29T11:59:00+00:00" in check["detail"]
    elif expected == "FAIL":
        assert check["detail"] == f"market-data provider {feed['state']}: not serving"


def test_a_healthy_status_yields_exactly_the_checks_it_did_before_task_013():
    names = [c["check"] for c in readiness.evaluate(_status(market_feed={"state": "RUNNING"}), NOW)["checks"]]
    assert names == ["runtime", "market_loop", "market_data", "execution", "venue_rules"]


# -- the /system page ---------------------------------------------------------------------------------


def test_the_system_page_shows_both_rows_escaped_with_the_readiness_window():
    import re
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "templates" / "system.html").read_text(encoding="utf-8")
    window = re.search(r"const CONTRACT_RECENT_S = (\d+);", page)
    assert window and float(window.group(1)) == readiness.RECENT_CONTRACT_REJECTION_S
    assert "row('Veri sağlayıcı'" in page and "row('Karar sözleşmesi'" in page
    feed_rows = page[page.index("const fd = st.market_feed"):page.index("const dc = ml.decision_contract")]
    contract_rows = page[page.index("const dc = ml.decision_contract"):page.index("const ex = st.execution")]
    # The rows are always rendered and map states as readiness does (review 33 L-3; the page is static
    # text to these tests, so the expressions themselves are pinned).
    assert "        rows.push(!fd.state ? row('Veri sağlayıcı', 'UNKNOWN', 'durum yok')" in feed_rows
    assert "fd.state === 'RUNNING' ? 'OK' : (fd.state === 'DEGRADED' ? 'DEGRADED' : 'DOWN')" in feed_rows
    assert "            rows.push(row('Karar sözleşmesi', 'UNKNOWN', 'durum yok'));" in contract_rows
    assert "            rows.push(row('Karar sözleşmesi', 'OK', 'reddedilen karar yok'));" in contract_rows
    assert "lastAge === null || lastAge <= CONTRACT_RECENT_S ? 'DEGRADED' : 'OK'" in contract_rows
    assert "        if (!ml.name) {\n" in contract_rows and "        } else if (!dc) {\n" in contract_rows
    assert "const last = dc.last_rejection || {}, lastAge = ageSeconds(last.at);" in contract_rows
    # The whole Task 013 block is pinned verbatim (review 35 L-1): the page has no JavaScript runtime in these
    # tests, so any change to which row is rendered, its state, counts or age text must change this text.
    start = page.index("        // Task 013 (registry v5.97): market-data provider")
    assert page[start:page.index("        const ex = st.execution")] == SYSTEM_PAGE_TASK013_BLOCK
    # Every value read from /api/status is escaped before it reaches innerHTML.
    for block, fields in ((feed_rows, ("fd.state", "fd.degradations", "fd.recoveries", "fd.last_degraded_at",
                                       "fd.last_recovered_at")),
                          (contract_rows, ("last.reason", "k)", "v)"))):
        for field in fields:
            assert f"esc({field}" in block, field


SYSTEM_PAGE_TASK013_BLOCK = "        // Task 013 (registry v5.97): market-data provider DEGRADED -> recovered transitions.\n        const fd = st.market_feed || {};\n        rows.push(!fd.state ? row('Veri sağlayıcı', 'UNKNOWN', 'durum yok')\n            : row('Veri sağlayıcı', fd.state === 'RUNNING' ? 'OK' : (fd.state === 'DEGRADED' ? 'DEGRADED' : 'DOWN'),\n                `${esc(fd.state)} · bozulma ${esc(fd.degradations ?? '?')} · toparlanma ${esc(fd.recoveries ?? '?')}`\n                + (fd.last_degraded_at ? ` · son bozulma ${esc(fd.last_degraded_at)}` : '')\n                + (fd.last_recovered_at ? ` · son toparlanma ${esc(fd.last_recovered_at)}` : '')));\n        // Task 013: Brain decision contract rejections (reason codes and counts only).\n        const dc = ml.decision_contract;\n        if (!ml.name) {\n            rows.push(row('Karar sözleşmesi', 'UNKNOWN', 'durum yok'));\n        } else if (!dc) {\n            rows.push(row('Karar sözleşmesi', 'OK', 'reddedilen karar yok'));\n        } else {\n            const last = dc.last_rejection || {}, lastAge = ageSeconds(last.at);\n            const counts = Object.entries(dc.rejections_by_reason || {}).map(([k, v]) => `${esc(k)} ×${esc(v)}`).join(', ');\n            rows.push(row('Karar sözleşmesi', lastAge === null || lastAge <= CONTRACT_RECENT_S ? 'DEGRADED' : 'OK',\n                `reddedilen: ${counts || '?'} · son ${esc(last.reason || '?')} ${lastAge === null ? '?' : lastAge.toFixed(0) + ' sn önce'} · reddedilen karar hiç yönlendirilmez`));\n        }\n"
