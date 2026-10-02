"""T-0015 (owner 2026-10-03): golden characterization of MarketLoop.process_symbol.

Generated on the pre-refactor code (one 513-line body). For every scenario the split
must reproduce: each returned result (None is a real result here: "skip this symbol"),
published events, metrics, the per-symbol memory (processed candle, signal, execution),
the error trail (phase/type/message; tracebacks excluded: they carry line numbers) and
the durable positions. Volatile values are normalized by norm(); nothing else is.

Regenerate ONLY for an intended, approved behaviour change:
    python -c "import json, tempfile, pathlib; from tests.test_process_symbol_golden import collect, GOLDEN; \
GOLDEN.write_text(json.dumps(collect(pathlib.Path(tempfile.mkdtemp())), indent=1, sort_keys=True))"
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from core.candle_processor import CandleContractError
from tests.test_block5c_upstream_sizing_authority import application, execution_enabled_loop
from tests.test_execute_decision_golden import _fail, norm

GOLDEN = Path(__file__).with_name("golden") / "process_symbol_golden.json"


def _contract_error(*a, **k):
    raise CandleContractError("unordered bars")


# ----------------------------------------------------------------------------- scenarios
# Each: (action, holding, setup(loop, app)) -> number of process_symbol calls (default 1)
def s_buy_routed(loop, app):
    pass


def s_hold(loop, app):
    pass


s_hold.action = "HOLD"


def s_sell_flat(loop, app):
    pass


s_sell_flat.action = "SELL"


def s_sell_held(loop, app):
    pass


s_sell_held.action, s_sell_held.holding = "SELL", True


def s_stale_buy(loop, app):
    from datetime import timedelta

    fresh = loop._processing_cutoff()
    loop._processing_cutoff = lambda: fresh + timedelta(seconds=599)


def s_duplicate_candle(loop, app):
    return 2


def s_no_candles(loop, app):
    loop._load_candles = lambda symbol: []


def s_normalize_empty(loop, app):
    loop.processor.normalize = lambda candles, processing_cutoff=None: []


def s_no_closed(loop, app):
    loop.processor.closed_candles = lambda candles: []


def s_insufficient_closed(loop, app):
    real = loop.processor.closed_candles
    loop.processor.closed_candles = lambda candles: real(candles)[-10:]


def s_identity_none(loop, app):
    loop.processor.latest_closed_identity = lambda candles: None


def s_invalid_analysis(loop, app):
    loop.technical.analyze = lambda candles: "not a dict"


def s_invalid_price(loop, app):
    loop.processor.latest_closed_price = lambda candles: 0


def s_normalization_failed(loop, app):
    loop.normalize_decision = lambda **kw: None


def s_invalid_action(loop, app):
    real = loop.normalize_decision

    def normalize(**kw):
        d = real(**kw)
        if d is not None:
            d["action"] = "TELEPORT"
        return d
    loop.normalize_decision = normalize


def s_execution_unavailable(loop, app):
    loop.execution = None


def s_contract_error(loop, app):
    loop._load_candles = _contract_error


def s_world_raises(loop, app):
    loop.world.build_market_data = _fail("world boom")


def s_brain_raises(loop, app):
    loop.brain.analyze_and_decide = _fail("brain boom")


def s_route_raises(loop, app):
    loop.route_execution = _fail("route boom")


def s_lowercase_symbol(loop, app):
    loop._golden_symbol = " btcusdt "


SCENARIOS: dict[str, Callable[[Any, Any], Any]] = {
    name.removeprefix("s_"): fn for name, fn in sorted(globals().items()) if name.startswith("s_") and callable(fn)
}


def collect(root: Path) -> dict[str, Any]:
    out = {}
    for name, scenario in SCENARIOS.items():
        holding = getattr(scenario, "holding", False)
        app = application(root / name, **({"positions": [("BTCUSDT", "10", "10")]} if holding else {}))
        if holding:
            app.paper_trader.open_trade("BTCUSDT", 10, 100)
        app.execution.start()
        loop = execution_enabled_loop(app, getattr(scenario, "action", "BUY"))
        published = []
        real_publish = loop.publish

        def publish(event, payload, _real=real_publish, _pub=published):
            _pub.append([event, norm(payload)])
            return _real(event, payload)
        loop.publish = publish
        calls = scenario(loop, app) or 1
        symbol = getattr(loop, "_golden_symbol", "BTCUSDT")
        results = [loop.process_symbol(symbol) for _ in range(calls)]
        with loop.lock:
            memory = {"processed": dict(loop.last_processed_candles), "signals": sorted(loop.last_signals),
                      "executions": dict(loop.last_executions), "agent_evidence": sorted(loop.last_agent_evidence),
                      "fetch_success": sorted(loop.last_symbol_fetch_success_at)}
        out[name] = norm({
            "results": results,
            "published": published,
            "metrics": dict(loop.metrics),
            "memory": memory,
            "errors": [[e.get("phase"), e.get("type"), e.get("error")] for e in getattr(loop, "errors", [])],
            "positions": app.portfolio_foundation.snapshot().get("positions"),
        })
        app.stop()
    return out


def test_process_symbol_matches_golden(tmp_path):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = collect(tmp_path)
    assert sorted(actual) == sorted(expected), "scenario set changed"
    for name in sorted(expected):
        assert actual[name] == expected[name], f"scenario {name!r} diverged from the golden record"


def test_golden_covers_every_process_symbol_return():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    results = [r for snap in expected.values() for r in snap["results"]]
    reasons = {r.get("reason") for r in results if isinstance(r, dict)}
    assert None in results  # "skip" results
    assert {"NO_CLOSED_CANDLES", "INSUFFICIENT_CLOSED_CANDLES", "CANDLE_IDENTITY_UNAVAILABLE",
            "DUPLICATE_CLOSED_CANDLE", "NON_EXECUTION_ACTION", "INVALID_NORMALIZED_ACTION",
            "EXECUTION_MANAGER_UNAVAILABLE", "NO_POSITION_TO_SELL", "STALE_MARKET_DATA"} <= reasons, reasons
    assert any(isinstance(r, dict) and r.get("status") == "PAPER_EXECUTED" for r in results)
