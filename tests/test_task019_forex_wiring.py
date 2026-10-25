"""Task 019 (registry v5.103): forex wiring - ATLAS_MARKET, the MT5 feed, MT5 instrument rules, USD quotes and the
market-session guard. CRYPTO stays the default and must behave exactly as before."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from atlas_finance.forex.sessions import is_forex_market_open
from atlas_finance.market_data.exceptions import InvalidCandleError
from atlas_finance.market_data.models import MarketCandle
from atlas_finance.market_data.mt5_provider import Mt5MarketDataProvider
from core.application import DEFAULT_INSTRUMENT_RULES_PATH, FOREX_INSTRUMENT_RULES_PATH, AtlasApplication
from core.atlas_config import AtlasConfigError, load_config
from core.candle_processor import CandleProcessor
from core.instrument_rules import load_instrument_ruleset
from core.market_loop import MarketLoop
from core.risk_engine import quote_currency
from exchange.market_feed import MarketFeed
from tests.intelligence.test_task009_regime_tracking import T0, Brain, Execution, Feed
from tests.test_block5c_upstream_sizing_authority import seed_state
from tests.test_task018_forex_foundation import NOW, FakeMt5
from tools.refresh_mt5_instrument_rules import build_ruleset, refresh_mt5_instrument_rules

# ---------------------------------------------------------------- ATLAS_MARKET


def config(env, monkeypatch):
    for name in [n for n in __import__("os").environ if n.upper().startswith("ATLAS_")]:
        monkeypatch.delenv(name, raising=False)
    return load_config(env, execution_mode="PAPER", paper_confidence_experiment=False)


def test_the_market_defaults_to_crypto_and_accepts_forex(monkeypatch):
    assert config({}, monkeypatch).market == "CRYPTO"
    assert config({"ATLAS_MARKET": " forex "}, monkeypatch).market == "FOREX"
    assert config({"ATLAS_MARKET": "forex"}, monkeypatch).describe()["market"] == "FOREX"


def test_an_unknown_market_is_refused(monkeypatch):
    with pytest.raises(AtlasConfigError, match="ATLAS_MARKET 'STOCKS' is refused"):
        config({"ATLAS_MARKET": "STOCKS"}, monkeypatch)


def test_the_binance_book_fill_is_refused_on_forex_even_with_a_valid_shadow_state(monkeypatch, tmp_path):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    env = {"ATLAS_FILL_MODEL": "BOOK", "ATLAS_STATE_DIRECTORY": str(shadow)}
    for name in [n for n in __import__("os").environ if n.upper().startswith("ATLAS_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(shadow))
    assert load_config(env, execution_mode="PAPER", paper_confidence_experiment=False).fill_model == "BOOK"
    with pytest.raises(AtlasConfigError) as refused:
        load_config({**env, "ATLAS_MARKET": "FOREX"}, execution_mode="PAPER", paper_confidence_experiment=False)
    assert refused.value.errors == ["ATLAS_MARKET=FOREX refuses ATLAS_FILL_MODEL=BOOK: the BOOK fill reads the "
                                    "Binance order book"]


# ---------------------------------------------------------------- the application in each market


def test_crypto_stays_exactly_as_before(tmp_path):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"))
    try:
        assert app.market == "CRYPTO" and app.exchange_name == "binance_global"
        assert app.instrument_rules_path == DEFAULT_INSTRUMENT_RULES_PATH
        assert app.sentiment_provider is not None and app.market_loop.market_session_open is None
        assert "USD" not in app.risk_policy.quote_currencies and "USDT" in app.risk_policy.quote_currencies
    finally:
        app.stop()


def test_forex_reads_mt5_its_own_rules_usd_quotes_and_the_session(tmp_path):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), market="forex")
    try:
        assert app.market == "FOREX" and app.exchange_name == "mt5"
        assert isinstance(app.market_feed.provider, Mt5MarketDataProvider)
        assert app.market_feed.provider.connected is False                # nothing connects at construction
        assert app.instrument_rules_path == FOREX_INSTRUMENT_RULES_PATH
        assert app.risk_policy.quote_currencies == ("USD",)
        assert app.sentiment_provider is None                             # crypto Fear & Greed is not forex evidence
        assert app.market_loop.market_session_open is is_forex_market_open
        assert app.symbols and all(s.endswith("USD") and len(s) == 6 for s in app.symbols)
        assert app.execution.live_execution_enabled is False
    finally:
        app.stop()


@pytest.mark.parametrize("kwargs, message", [
    ({"market": "stocks"}, "not one of"),
    ({"market": "FOREX", "paper_fill_model": "BOOK"}, "refuses"),
    ({"market": "FOREX", "funding_sentiment": True}, "refuses"),
])
def test_unknown_markets_and_binance_inputs_on_forex_are_refused(tmp_path, kwargs, message):
    with pytest.raises(ValueError, match=message):
        AtlasApplication(state_directory=seed_state(tmp_path / "state"), **kwargs)


def test_eurusd_has_a_quote_currency_only_on_the_forex_list():
    assert quote_currency("EURUSD", ("USD",)) == "USD"
    assert quote_currency("EURUSD", ("USDT", "USDC", "FDUSD", "TUSD", "TRY", "EUR", "BTC", "ETH", "BNB")) is None


# ---------------------------------------------------------------- MarketFeed on MT5


def tick_candle(**meta):
    t = datetime(2026, 10, 28, 7, tzinfo=UTC)
    return MarketCandle("EURUSD", "1m", t, t + timedelta(seconds=59.999), 1.08, 1.081, 1.079, 1.0805, 123.0, "mt5",
                        True, {"volume_kind": "TICK", **meta})


def test_the_feed_accepts_mt5_and_carries_absent_exchange_volume_as_none():
    feed = MarketFeed(exchange_name="mt5", provider=Mt5MarketDataProvider(mt5_module=FakeMt5(), clock=lambda: NOW))
    assert feed.exchange_name == "mt5"
    row = MarketFeed._to_legacy_candle_row(tick_candle())
    assert row[5] == "123.0" and row[7:11] == [None, None, None, None]   # never a fabricated zero
    normalized = CandleProcessor().normalize([row], processing_cutoff=row[6] + 1)
    assert normalized[0]["volume"] == 123.0 and "quote_volume" not in normalized[0]


def test_a_crypto_candle_still_needs_its_exchange_volume():
    t = datetime(2026, 10, 28, 7, tzinfo=UTC)
    bare = MarketCandle("BTCUSDT", "1m", t, t + timedelta(seconds=59.999), 1, 1, 1, 1, 1.0, "binance", True, {})
    with pytest.raises(InvalidCandleError):
        MarketFeed._to_legacy_candle_row(bare)


def test_an_unknown_exchange_is_still_refused():
    with pytest.raises(ValueError, match="mt5"):
        MarketFeed(exchange_name="oanda")


# ---------------------------------------------------------------- the session guard in MarketLoop


def loop_with(guard):
    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["EURUSD"])
    loop._sell_symbol_known_flat = lambda symbol: False
    loop.market_session_open = guard
    return loop


def gate(loop, action):
    cutoff = datetime.fromtimestamp(T0 / 1000, UTC)
    return loop._symbol_execution_gate("EURUSD", {"action": action, "symbol": "EURUSD", "metadata": {}},
                                       [{"open_time": T0 - 60_000, "close_time": T0 - 1}], cutoff)


@pytest.mark.parametrize("action", ["BUY", "SELL"])
@pytest.mark.parametrize("guard", [lambda now: False, lambda now: 1 / 0, lambda now: "yes", lambda now: None])
def test_nothing_is_routed_while_the_market_is_closed_or_the_guard_is_unsure(action, guard):
    loop = loop_with(guard)
    result = gate(loop, action)
    assert result["status"] == "SKIPPED" and result["reason"] == "MARKET_CLOSED" and result["action"] == action
    assert loop.metrics["market_closed_skipped"] == 1 and loop.execution.calls == 0


@pytest.mark.parametrize("action", ["BUY", "SELL"])
def test_an_open_market_or_no_guard_leaves_the_gate_unchanged(action):
    for guard in (None, lambda now: True):
        result = gate(loop_with(guard), action)
        assert not (isinstance(result, dict) and result.get("reason") == "MARKET_CLOSED")
    assert "market_closed_skipped" not in loop_with(None).metrics                # crypto metrics unchanged


def test_hold_is_never_counted_as_a_closed_market_skip():
    loop = loop_with(lambda now: False)
    assert gate(loop, "HOLD")["reason"] == "NON_EXECUTION_ACTION" and "market_closed_skipped" not in loop.metrics


def test_the_guard_reads_the_cycle_cutoff():
    seen = []
    loop = loop_with(lambda now: seen.append(now) or True)
    gate(loop, "BUY")
    assert seen == [datetime.fromtimestamp(T0 / 1000, UTC)]


# ---------------------------------------------------------------- MT5 instrument rules


def test_mt5_rules_are_written_validated_and_carry_no_venue_maxima(tmp_path):
    provider = Mt5MarketDataProvider(mt5_module=FakeMt5(), clock=lambda: NOW)
    target = tmp_path / "instrument_rules_mt5.json"
    written = refresh_mt5_instrument_rules(destination=target, provider=provider, now=datetime.now(UTC))
    loaded = load_instrument_ruleset(target)
    assert set(loaded.symbols) == set(written.symbols) == {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"}
    eur = loaded.rules["EURUSD"]
    assert (eur.venue, eur.quote_asset, eur.quantity_step, eur.min_quantity, eur.price_tick) == (
        "MT5", "USD", Decimal("1000"), Decimal("1000"), Decimal("0.00001"))
    assert eur.max_quantity is None and eur.max_notional is None and eur.market_max_quantity is None
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert raw["provenance"]["venue_upper_bounds_modelled"] is False and provider.connected is False


def test_a_failed_terminal_never_touches_the_rules_file(tmp_path):
    target = tmp_path / "instrument_rules_mt5.json"
    target.write_text("previous", encoding="utf-8")
    with pytest.raises(Exception):
        refresh_mt5_instrument_rules(destination=target,
                                     provider=Mt5MarketDataProvider(mt5_module=FakeMt5(trade_mode=2),
                                                                    clock=lambda: NOW))
    assert target.read_text(encoding="utf-8") == "previous"


def test_a_misaligned_volume_minimum_is_refused():
    from atlas_finance.forex import ForexInstrument
    from core.instrument_rules import InstrumentRulesConfigError

    info = SimpleNamespace(name="EURUSD", currency_base="EUR", currency_profit="USD", digits=5, point=0.00001,
                           trade_contract_size=100000.0, volume_min=0.015, volume_step=0.01, volume_max=100.0)
    with pytest.raises(InstrumentRulesConfigError):
        build_ruleset({"EURUSD": ForexInstrument.from_symbol_info(info)}, retrieved_at=datetime.now(UTC))


def test_the_forex_rules_have_their_own_file_and_the_crypto_rules_stay_binance():
    assert FOREX_INSTRUMENT_RULES_PATH != DEFAULT_INSTRUMENT_RULES_PATH
    assert {rule.venue for rule in load_instrument_ruleset(DEFAULT_INSTRUMENT_RULES_PATH).rules.values()} == {"BINANCE"}
