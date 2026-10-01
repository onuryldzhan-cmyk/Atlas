"""Design C: Binance funding rate as sentiment evidence only when Fear & Greed is neutral (NB-4 / NB-5 guarded)."""

import json
from decimal import Decimal

import pytest

from analysis.evidence_status import MarketDataEvidenceStatus as S
from analysis.world_analysis_engine import WorldAnalysisEngine as W
from atlas_finance.market_data.funding_rate_provider import (
    CACHE_S, STALE_S, FundingRateProvider, classify, parse)

BULL = {"trend": "BULLISH"}
NEUTRAL_FG = {"provider_status": "AVAILABLE", "value": 50, "band": "NEUTRAL", "reason": "OK"}


def ev(sentiment, analysis=BULL, tech=S.AVAILABLE):
    return W._sentiment_evidence(sentiment, analysis, tech)


def funding(band, available=True):
    return {**NEUTRAL_FG, "funding": {"available": available, "rate": "0.001", "band": band, "reason": "OK"}}


# ---------- provider ----------

def body(rows):
    return json.dumps(rows).encode()


def test_parse_and_classify():
    rates = parse(body([{"symbol": "BTCUSDT", "lastFundingRate": "0.00050000"},
                        {"symbol": "BTCUSDT_251226", "lastFundingRate": ""}, {"symbol": "X", "lastFundingRate": None}]))
    assert rates == {"BTCUSDT": Decimal("0.00050000")}
    assert classify(Decimal("0.0003")) == "CROWDED_LONG" and classify(Decimal("-0.0003")) == "CROWDED_SHORT"
    assert classify(Decimal("0.0001")) == "NEUTRAL"


@pytest.mark.parametrize("bad", [b"{}", b"not json", body([1]), body([{"symbol": "A", "lastFundingRate": "abc"}]),
                                 body([{"symbol": "A", "lastFundingRate": "NaN"}]), body([{"symbol": "A", "lastFundingRate": "0.9"}])])
def test_malformed_bodies_raise(bad):
    with pytest.raises(ValueError):
        parse(bad)


def test_provider_caches_fails_closed_and_goes_stale():
    now = [1000.0]
    calls = []

    def ok(url, timeout):
        calls.append(url)
        return body([{"symbol": "BTCUSDT", "lastFundingRate": "-0.0005"}])

    p = FundingRateProvider(transport=ok, clock=lambda: now[0])
    assert p.rate("BTCUSDT")["band"] == "CROWDED_SHORT"
    p.rate("ETHUSDT")
    assert len(calls) == 1  # cached
    assert p.rate("ETHUSDT")["available"] is False
    p._transport = lambda url, timeout: (_ for _ in ()).throw(OSError("down"))
    now[0] += CACHE_S
    assert p.rate("BTCUSDT")["available"] is True  # last good cache still fresh
    now[0] += STALE_S
    r = p.rate("BTCUSDT")
    assert r["available"] is False and r["rate"] is None


def test_provider_never_raises_without_any_data():
    p = FundingRateProvider(transport=lambda u, t: b"garbage", clock=lambda: 0.0)
    assert p.rate("BTCUSDT")["available"] is False


# ---------- engine ----------

def test_without_funding_the_neutral_band_still_abstains():
    status, score, _ = ev(NEUTRAL_FG)
    assert status is S.UNAVAILABLE_NO_PROVIDER and score is None


@pytest.mark.parametrize("f", [funding("NEUTRAL"), funding("CROWDED_LONG", available=False),
                               {**NEUTRAL_FG, "funding": None}, {**NEUTRAL_FG, "funding": "x"},
                               {**NEUTRAL_FG, "funding": {"available": "yes", "band": "CROWDED_SHORT"}}])
def test_missing_neutral_or_malformed_funding_keeps_the_abstention(f):
    # NB-4: removing or corrupting evidence can never create a vote or raise confidence.
    status, score, _ = ev(f)
    assert status is S.UNAVAILABLE_NO_PROVIDER and score is None


def test_crowded_short_with_bullish_trend_is_the_only_funding_vote():
    s, score, e = ev(funding("CROWDED_SHORT"))
    assert s is S.AVAILABLE and e["vote"] == "BUY" and e["reason"] == "FUNDING_RATE_CROWDED"
    # Audit F-1: dissenting reads (SELL/HOLD) abstain, because fuse() would turn them into MORE confidence.
    for f, a in ((funding("CROWDED_LONG"), BULL), (funding("CROWDED_SHORT"), {"trend": "NEUTRAL"}),
                 (funding("CROWDED_LONG"), {"trend": "BEARISH"})):
        s, score, e = ev(f, analysis=a)
        assert s is S.UNAVAILABLE_NO_PROVIDER and score is None




def test_fusion_never_gets_a_dissenting_funding_vote_and_roster_stays_five():
    # Audit F-3: whatever the funding read, the sentiment evidence is either a BUY or an abstention,
    # and the engine still reports exactly one sentiment evidence slot (NB-5 roster of five).
    for band in ("CROWDED_SHORT", "CROWDED_LONG", "NEUTRAL"):
        for a in (BULL, {"trend": "BEARISH"}, {"trend": "NEUTRAL"}):
            s, score, e = ev(funding(band), analysis=a)
            assert (s is S.AVAILABLE and e["vote"] == "BUY") or (s is S.UNAVAILABLE_NO_PROVIDER and score is None)


def test_fear_greed_and_funding_disagreeing_follows_fear_greed():
    greed = {"provider_status": "AVAILABLE", "value": 90, "band": "GREED", "reason": "OK",
             "funding": {"available": True, "rate": "-0.001", "band": "CROWDED_SHORT"}}
    s, score, e = ev(greed)
    assert e["vote"] == "SELL" and "funding_band" not in e


def test_fear_or_greed_band_ignores_funding():
    fg = {"provider_status": "AVAILABLE", "value": 10, "band": "FEAR", "reason": "OK",
          "funding": {"available": True, "rate": "0.001", "band": "CROWDED_LONG"}}
    s, score, e = ev(fg)
    assert e["vote"] == "BUY" and "funding_band" not in e


def test_flag_is_off_in_main_and_application_by_default(tmp_path):
    import ast
    from pathlib import Path
    from core.application import AtlasApplication
    from tests.test_block5e_fee_settlement_accounting import seed_state

    tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "AtlasApplication")
    assert "funding_sentiment" not in {k.arg for k in call.keywords}
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"))
    assert getattr(app.market_loop, "funding_provider", None) is None
    on = AtlasApplication(state_directory=seed_state(tmp_path / "s2"), funding_sentiment=True)
    assert on.market_loop.funding_provider is not None


def test_market_loop_adds_funding_without_raising():
    from types import SimpleNamespace
    from core.market_loop import MarketLoop

    loop = MarketLoop.__new__(MarketLoop)
    assert loop._with_funding(dict(NEUTRAL_FG), "BTCUSDT") == NEUTRAL_FG  # no provider -> unchanged
    loop.funding_provider = SimpleNamespace(rate=lambda s: (_ for _ in ()).throw(RuntimeError("x")))
    assert loop._with_funding(dict(NEUTRAL_FG), "BTCUSDT") == NEUTRAL_FG
    loop.funding_provider = SimpleNamespace(rate=lambda s: {"available": True, "band": "NEUTRAL"})
    assert loop._with_funding(dict(NEUTRAL_FG), "BTCUSDT")["funding"]["band"] == "NEUTRAL"
    assert loop._with_funding(None, "BTCUSDT") is None
