"""Discriminating coverage for the new ``/api/signals`` and ``/api/trades``
endpoints added to expand the operator dashboard beyond BTCUSDT-only.

Mirrors the conventions already established in
``tests/test_web_app_runtime_response_safety.py``: real-shape fakes, leak
markers for fields the allowlist must never publish, explicit fail-closed
assertions, and a loopback-refusal check.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from web_app import create_app


# =====================================================================
# /api/signals
# =====================================================================

# Markers planted only inside metadata subtrees the allowlist must not
# publish (fusion internals, reasoning text, memory diagnostics, candle
# identity). None of them is "action" or "score", so any appearance in a
# response body is a genuine leak.
FUSION_LEAK_MARKER = "LEAK-FUSION-INTERNAL-SCORES"
REASONING_LEAK_MARKER = "LEAK-REASONING-NARRATIVE-TEXT"
MEMORY_LEAK_MARKER = "LEAK-MEMORY-DIAGNOSTIC-DETAIL"
CANDLE_LEAK_MARKER = "LEAK-CANDLE-IDENTITY-DETAIL"

SIGNAL_LEAK_MARKERS = (
    FUSION_LEAK_MARKER,
    REASONING_LEAK_MARKER,
    MEMORY_LEAK_MARKER,
    CANDLE_LEAK_MARKER,
)

# "memory" added 2026-09-30 (owner MEGA 3 §11, registry v5.82): the fixed
# BRAIN-MEM-001 caution fields only, read from metadata.memory_adjustment.
ALLOWED_SIGNAL_KEYS = frozenset(
    {"symbol", "action", "confidence", "risk_level", "agents", "memory"}
)
ALLOWED_MEMORY_KEYS = frozenset({"reason", "confidence_before", "confidence_after", "trades", "net_expectancy"})
ALLOWED_AGENT_KEYS = frozenset({"status", "action", "score", "reason"})


def _real_shape_decision(symbol: str, *, include_all_agents: bool) -> dict:
    metadata = {
        "agents": {
            "technical": {"action": "BUY", "score": 0.82},
        },
        "unavailable_agents": {
            "macro": "STATUS_MISSING",
            "sentiment": "STATUS_MISSING",
            "risk": "STATUS_MISSING",
            "momentum": "STATUS_MISSING",
        },
        "fusion": {"raw_scores": FUSION_LEAK_MARKER},
        "fusion_reason": FUSION_LEAK_MARKER,
        "reasoning": REASONING_LEAK_MARKER,
        "memory": MEMORY_LEAK_MARKER,
        "candle_identity": CANDLE_LEAK_MARKER,
        "timestamp": "2026-09-17T00:00:00Z",
    }

    if include_all_agents:
        metadata["agents"] = {
            "technical": {"action": "BUY", "score": 0.82},
            "macro": {"action": "HOLD", "score": 0.1},
            "sentiment": {"action": "SELL", "score": -0.4},
            "risk": {"action": "HOLD", "score": 0.0},
            "momentum": {"action": "BUY", "score": 0.55},
        }
        metadata["unavailable_agents"] = {}

    return {
        "action": "BUY",
        "symbol": symbol,
        "confidence": 71.5,
        "strategy": "Atlas_v10_MultiAgent",
        "risk_level": "MEDIUM",
        "price": 65000.0,
        "created_at": "2026-09-17T00:00:00Z",
        "metadata": metadata,
    }


class RealShapeMarketLoop:
    def status(self) -> dict:
        return {
            "last_signals": {
                "BTCUSDT": _real_shape_decision(
                    "BTCUSDT", include_all_agents=True
                ),
                "ETHUSDT": _real_shape_decision(
                    "ETHUSDT", include_all_agents=False
                ),
            }
        }


class _SignalsRuntime:
    def __init__(self, market_loop: object | None) -> None:
        self.market_loop = market_loop


def _signals_client(market_loop: object | None) -> TestClient:
    return TestClient(
        create_app(runtime=_SignalsRuntime(market_loop))
    )


def test_signals_endpoint_reports_all_five_agents_for_every_symbol() -> None:
    payload = _signals_client(RealShapeMarketLoop()).get("/api/signals").json()

    assert payload["status"] == "SUCCESS"

    btc = payload["signals"]["BTCUSDT"]
    assert set(btc["agents"]) == {
        "technical", "macro", "sentiment", "risk", "momentum",
    }
    assert btc["agents"]["technical"] == {
        "status": "EVALUATED", "action": "BUY", "score": 0.82,
    }

    eth = payload["signals"]["ETHUSDT"]
    assert eth["agents"]["technical"]["status"] == "EVALUATED"
    assert eth["agents"]["macro"] == {
        "status": "EXCLUDED", "reason": "STATUS_MISSING",
    }
    assert eth["agents"]["momentum"] == {
        "status": "EXCLUDED", "reason": "STATUS_MISSING",
    }


def test_signals_endpoint_does_not_leak_metadata_internals() -> None:
    response = _signals_client(RealShapeMarketLoop()).get("/api/signals")

    body = response.text

    for marker in SIGNAL_LEAK_MARKERS:
        assert marker not in body, (
            f"unsanitised MarketLoop metadata leaked into /api/signals: {marker}"
        )

    payload = response.json()

    for symbol, signal in payload["signals"].items():
        assert set(signal) <= ALLOWED_SIGNAL_KEYS, (
            f"unexpected keys for {symbol}: "
            f"{sorted(set(signal) - ALLOWED_SIGNAL_KEYS)}"
        )

        assert signal.get("memory") is None or set(signal["memory"]) <= ALLOWED_MEMORY_KEYS

        for agent_name, agent in signal["agents"].items():
            assert set(agent) <= ALLOWED_AGENT_KEYS, (
                f"unexpected keys for {symbol}.{agent_name}: "
                f"{sorted(set(agent) - ALLOWED_AGENT_KEYS)}"
            )


def test_signals_endpoint_fails_closed_without_market_loop() -> None:
    response = _signals_client(None).get("/api/signals")

    assert response.status_code == 503
    assert response.json() == {
        "status": "OFFLINE",
        "reason": "MARKET_LOOP_NOT_ATTACHED",
    }


def test_signals_endpoint_fails_closed_when_runtime_missing() -> None:
    response = TestClient(create_app()).get("/api/signals")

    assert response.status_code == 503
    assert response.json()["reason"] == "MARKET_LOOP_NOT_ATTACHED"


class RaisingMarketLoop:
    def status(self) -> dict:
        raise RuntimeError("LEAK-MARKET-LOOP-EXCEPTION-TEXT")


def test_signals_endpoint_never_leaks_a_raised_exception_message() -> None:
    response = _signals_client(RaisingMarketLoop()).get("/api/signals")

    assert response.status_code == 500
    assert "LEAK-MARKET-LOOP-EXCEPTION-TEXT" not in response.text

    payload = response.json()
    assert payload["reason"] == "SIGNALS_FAILED"
    assert payload["error_type"] == "RuntimeError"


def test_signals_endpoint_omits_symbols_with_no_cycle_yet() -> None:
    """A symbol MarketLoop hasn't processed yet must simply be absent, not
    fabricated as a null/placeholder entry - the frontend renders the
    5-symbol grid and fills gaps itself."""

    class PartialMarketLoop:
        def status(self) -> dict:
            return {
                "last_signals": {
                    "BTCUSDT": _real_shape_decision(
                        "BTCUSDT", include_all_agents=True
                    ),
                }
            }

    payload = _signals_client(PartialMarketLoop()).get("/api/signals").json()

    assert set(payload["signals"]) == {"BTCUSDT"}


# =====================================================================
# /api/trades
# =====================================================================


class FakeIndex:
    def __init__(self, records: dict) -> None:
        self.by_position_id = records


class FakeClosedArchive:
    def __init__(self, records: dict | None = None, *, raises: bool = False) -> None:
        self._records = records or {}
        self._raises = raises

    def load_index(self) -> FakeIndex:
        if self._raises:
            raise ValueError("LEAK-ARCHIVE-CORRUPTION-DETAIL")

        return FakeIndex(self._records)


class _TradesRuntime:
    def __init__(self, portfolio_foundation: object | None) -> None:
        self.portfolio_foundation = portfolio_foundation


def _closed_record(
    position_id: str,
    symbol: str,
    gross_pnl: str,
) -> dict:
    return {
        "position_id": position_id,
        "symbol": symbol,
        "base_quantity": "0",
        "cost_quote": "LEAK-COST-QUOTE-DETAIL",
        "entry_fees": "LEAK-ENTRY-FEES-DETAIL",
        "average_entry_price": "LEAK-AVG-ENTRY-PRICE-DETAIL",
        "mark_price": "LEAK-MARK-PRICE-DETAIL",
        "version": 1,
        "opened_at": "2026-09-10T00:00:00Z",
        "status": "CLOSED",
        "exit_price": "LEAK-EXIT-PRICE-DETAIL",
        "gross_pnl": gross_pnl,
        "closed_at": "2026-09-11T00:00:00Z",
    }


def _trades_client(portfolio_foundation: object | None) -> TestClient:
    return TestClient(
        create_app(runtime=_TradesRuntime(portfolio_foundation))
    )


def test_trades_endpoint_computes_win_rate_and_treats_breakeven_as_loss() -> None:
    class Foundation:
        closed_archive = FakeClosedArchive({
            "p1": _closed_record("p1", "BTCUSDT", "12.5"),
            "p2": _closed_record("p2", "ETHUSDT", "-3.25"),
            "p3": _closed_record("p3", "BTCUSDT", "0"),
        })

    payload = _trades_client(Foundation()).get("/api/trades").json()

    assert payload["available"] is True
    assert payload["total_trades"] == 3
    assert payload["wins"] == 1
    assert payload["losses"] == 2
    assert payload["win_rate"] == round(1 / 3 * 100, 2)
    assert payload["total_gross_pnl"] == "9.25"
    assert len(payload["recent_trades"]) == 3


def test_trades_endpoint_reports_empty_archive_as_available_not_an_error() -> None:
    class Foundation:
        closed_archive = FakeClosedArchive({})

    payload = _trades_client(Foundation()).get("/api/trades").json()

    assert payload == {
        "available": True,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "total_gross_pnl": "0",
        "recent_trades": [],
    }


def test_trades_endpoint_does_not_leak_internal_position_fields() -> None:
    class Foundation:
        closed_archive = FakeClosedArchive({
            "p1": _closed_record("p1", "BTCUSDT", "12.5"),
        })

    response = _trades_client(Foundation()).get("/api/trades")
    body = response.text

    for marker in (
        "LEAK-COST-QUOTE-DETAIL",
        "LEAK-ENTRY-FEES-DETAIL",
        "LEAK-AVG-ENTRY-PRICE-DETAIL",
        "LEAK-MARK-PRICE-DETAIL",
        "LEAK-EXIT-PRICE-DETAIL",
    ):
        assert marker not in body, f"internal financial detail leaked: {marker}"

    trade = response.json()["recent_trades"][0]
    assert set(trade) == {"symbol", "gross_pnl", "opened_at", "closed_at"}
    assert "position_id" not in trade
    assert "version" not in trade


def test_trades_endpoint_fails_closed_on_corrupt_archive_without_leaking_detail() -> None:
    class Foundation:
        closed_archive = FakeClosedArchive(raises=True)

    response = _trades_client(Foundation()).get("/api/trades")

    assert response.status_code == 503
    assert "LEAK-ARCHIVE-CORRUPTION-DETAIL" not in response.text

    payload = response.json()
    assert payload == {
        "available": False,
        "reason": "CLOSED_ARCHIVE_CORRUPT",
        "error_type": "ValueError",
    }


class RaisingIOArchive:
    """Simulates a bare I/O failure (permission/transient disk/encoding),
    distinct from a data-validation failure raised by load_index() itself."""

    def load_index(self):
        raise OSError("LEAK-IO-FAILURE-DETAIL")


def test_trades_endpoint_reports_io_failure_as_unreadable_not_corrupt() -> None:
    """An unreadable archive and a corrupt one need different operator
    remediation, so they must not share a reason code (see this project's
    established UNREADABLE-vs-CORRUPT convention for store read failures)."""

    class Foundation:
        closed_archive = RaisingIOArchive()

    response = _trades_client(Foundation()).get("/api/trades")

    assert response.status_code == 503
    assert "LEAK-IO-FAILURE-DETAIL" not in response.text

    payload = response.json()
    assert payload == {
        "available": False,
        "reason": "CLOSED_ARCHIVE_UNREADABLE",
        "error_type": "OSError",
    }


def test_trades_endpoint_fails_the_whole_response_closed_on_one_bad_record() -> None:
    """A record load_index() returns that fails to parse must fail the
    entire response closed (503), never be silently excluded from the
    aggregate totals while still appearing in recent_trades - that would
    produce inconsistent, partially-fabricated figures."""

    class Foundation:
        closed_archive = FakeClosedArchive({
            "p1": _closed_record("p1", "BTCUSDT", "12.5"),
            "p2": _closed_record("p2", "ETHUSDT", "not-a-number"),
        })

    response = _trades_client(Foundation()).get("/api/trades")

    assert response.status_code == 503
    payload = response.json()
    assert payload["available"] is False
    assert payload["reason"] == "CLOSED_ARCHIVE_CORRUPT"
    # The valid record's gross_pnl value must never leak partially either.
    assert "12.5" not in response.text


def test_trades_endpoint_fails_closed_without_portfolio_foundation() -> None:
    response = _trades_client(None).get("/api/trades")

    assert response.status_code == 503
    assert response.json() == {
        "available": False,
        "reason": "PORTFOLIO_FOUNDATION_NOT_ATTACHED",
    }


def test_trades_endpoint_fails_closed_when_runtime_missing() -> None:
    response = TestClient(create_app()).get("/api/trades")

    assert response.status_code == 503
    assert response.json()["reason"] == "PORTFOLIO_FOUNDATION_NOT_ATTACHED"


def test_trades_endpoint_caps_recent_trades_to_the_configured_limit() -> None:
    from web_app import TRADE_HISTORY_LIMIT

    records = {
        f"p{i}": _closed_record(f"p{i}", "BTCUSDT", "1")
        for i in range(TRADE_HISTORY_LIMIT + 10)
    }

    class Foundation:
        closed_archive = FakeClosedArchive(records)

    payload = _trades_client(Foundation()).get("/api/trades").json()

    assert payload["total_trades"] == TRADE_HISTORY_LIMIT + 10
    assert len(payload["recent_trades"]) == TRADE_HISTORY_LIMIT


# =====================================================================
# Loopback guard (both new routes)
# =====================================================================


def test_new_endpoints_refuse_non_loopback_clients() -> None:
    class Foundation:
        closed_archive = FakeClosedArchive({})

    class Runtime:
        market_loop = RealShapeMarketLoop()
        portfolio_foundation = Foundation()

    client = TestClient(
        create_app(runtime=Runtime()),
        client=("203.0.113.7", 44321),
    )

    for route in ("/api/signals", "/api/trades"):
        response = client.get(route)

        assert response.status_code == 403, route
        assert (
            response.json()["reason"] == "ATLAS_WEB_PANEL_IS_LOCALHOST_ONLY"
        ), route


def test_trades_endpoint_adds_account_net_and_fees_only_when_book_readable() -> None:
    """Registry v5.24: account-level aggregates only; per-trade fields unchanged."""

    class Readable:
        closed_archive = FakeClosedArchive({"p1": _closed_record("p1", "BTCUSDT", "12.5")})

        def snapshot(self):
            return {"realized_net_pnl": "10.3", "fees": "2.2", "cash": "LEAK-CASH"}

    class Broken:
        closed_archive = FakeClosedArchive({})

        def snapshot(self):
            raise RuntimeError("not ready")

    payload = _trades_client(Readable()).get("/api/trades").json()
    assert payload["account"] == {"realized_net_pnl": "10.3", "fees": "2.2"}
    assert "LEAK-CASH" not in str(payload)
    assert set(payload["recent_trades"][0]) == {"symbol", "gross_pnl", "opened_at", "closed_at"}
    assert "account" not in _trades_client(Broken()).get("/api/trades").json()
