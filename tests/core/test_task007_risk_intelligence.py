"""Task 007: risk intelligence and position limit rules (registry v5.91 grant).

RiskEngine is the independent veto: these tests show its Task 007 guards refusing
even maximum-confidence BUYs, failing closed on missing or corrupt inputs, and never
touching exits. Every guard is off by default, so existing decisions are unchanged.
The downsize-only sizing ceiling is shared by PositionSizingService (which shrinks to
it) and RiskEngine (which vetoes above it).
"""

from __future__ import annotations

import hashlib
import itertools
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

import core.position_sizing as ps
import core.risk_engine as re_engine
from core.position_sizing import PositionSizingService, SizingInputs, SizingStatus
from core.risk_engine import (
    PositionExposure,
    RiskDecisionStatus,
    RiskEngine,
    RiskPolicy,
    RiskRequest,
    RiskState,
    SizingSignal,
    drawdown_fraction,
    quote_currency,
    sizing_ceiling,
)

D = Decimal
CAPITAL = D("10000")
LEGACY_KEYS = {"status", "approved", "reason_code", "approved_allocation", "gross_exposure", "available_capital",
               "reserved_capital", "daily_realized_pnl", "drawdown_amount", "drawdown_pct", "drawdown_level",
               "policy_version", "experiment_id"}


def policy(**kw) -> RiskPolicy:
    return RiskPolicy(total_capital=CAPITAL, **kw)


def position(symbol: str, quote: str) -> PositionExposure:
    return PositionExposure(symbol, D(quote) / 100, D("100"), D(quote))


def state(*positions: PositionExposure, peak: str = "10000", current: str = "10000", pnl: str = "0") -> RiskState:
    return RiskState(positions=positions, committed_quote=sum((p.quote_exposure for p in positions), D("0")),
                     realized_daily_pnl=D(pnl), peak_equity=D(peak), current_equity=D(current), state_ready=True,
                     accounting_day_utc=datetime.now(UTC).date().isoformat(), policy_version="phase3-risk-v1")


def buy(symbol: str = "BTCUSDT", amount: str = "1000", **kw) -> RiskRequest:
    """A maximum-confidence LOW-risk BUY: anything refusing it is a genuine veto."""
    return RiskRequest(symbol=symbol, action="BUY", confidence=D("1"), requested_quote_allocation=D(amount),
                       execution_price=D("100"), risk_bucket="LOW", **kw)


def exit_(symbol: str, amount: str, **kw) -> RiskRequest:
    return RiskRequest(symbol=symbol, action="SELL", confidence=D("0"), requested_quote_allocation=D(amount),
                       execution_price=D("100"), risk_bucket="CRITICAL", reduce_only=True, **kw)


def decide(pol: RiskPolicy, request: RiskRequest, st: RiskState | None = None):
    return RiskEngine(pol).evaluate(request, st or state())


# -- defaults are byte-identical ---------------------------------------------------------


def test_every_guard_is_off_by_default_and_the_policy_version_is_unchanged():
    pol = policy()
    assert pol.version == "phase3-risk-v1"
    assert (pol.correlation_ceiling, pol.cluster_exposure_pct, pol.quote_exposure_pct, pol.max_market_data_age_seconds,
            pol.kelly_fraction, pol.volatility_target, pol.drawdown_sizing) == (None,) * 6 + (False,)
    assert sizing_ceiling(pol, None, drawdown_pct=None).amount is None
    for request, st in ((buy(), state()), (buy(amount="9000"), state()), (buy("ETHUSDT"), state(position("BTCUSDT", "2000"))),
                        (exit_("BTCUSDT", "2000"), state(position("BTCUSDT", "2000")))):
        decision = decide(pol, request, st).to_dict()
        assert set(decision) == LEGACY_KEYS  # no Task 007 detail on any existing decision


# -- leverage: spot only, hard cap 1x ---------------------------------------------------------


def test_any_leverage_is_vetoed_even_at_full_confidence():
    decision = decide(policy(), buy(leverage=D("2")))
    assert (decision.status, decision.reason_code) == (RiskDecisionStatus.REJECT, "LEVERAGE_NOT_PERMITTED")
    assert decision.approved_allocation == 0 and decision.to_dict()["detail"] == {"leverage": "2", "max_leverage": "1"}
    assert decide(policy(), buy(leverage=1.0)).reason_code == "INVALID_FINANCIAL_INPUT"  # floats never pass
    assert decide(policy(), buy(leverage=D("0"))).reason_code == "INVALID_FINANCIAL_INPUT"
    assert decide(policy(), buy(leverage=D("1"))).approved


def test_exits_never_see_the_new_guards():
    """Fail-closed for new entries only: risk reduction stays possible with every guard on and every input missing."""
    strict = policy(correlation_ceiling=D("0"), cluster_exposure_pct=D("0.01"), quote_exposure_pct=D("0.01"),
                    max_market_data_age_seconds=D("1"), kelly_fraction=D("0.25"), volatility_target=D("0.01"),
                    drawdown_sizing=True)
    held = state(position("BTCUSDT", "2000"), peak="10000", current="8000")  # 20%: past the drawdown halt
    decision = decide(strict, exit_("BTCUSDT", "2000", leverage=D("3")), held)
    assert decision.approved and decision.reason_code == "RISK_REDUCTION_APPROVED"
    assert decide(strict, buy("ETHUSDT"), held).reason_code == "MARKET_DATA_AGE_UNKNOWN"  # breakers come first
    assert decide(strict, buy("ETHUSDT", market_data_age_seconds=D("0")), held).reason_code == "DRAWDOWN_HALT_NEW_RISK"


# -- fail closed on missing balance state or corrupt market data ----------------------------------


def test_unverified_balance_state_blocks_new_entries():
    decision = RiskEngine(policy()).evaluate(buy(), RiskState())
    assert (decision.status, decision.reason_code) == (RiskDecisionStatus.BLOCK_RECOVERY_REQUIRED, "RISK_STATE_NOT_READY")


@pytest.mark.parametrize("price", [D("NaN"), D("-1"), D("0"), 100.0, "garbage"])
def test_corrupt_prices_are_refused(price):
    request = RiskRequest(symbol="BTCUSDT", action="BUY", confidence=D("1"), requested_quote_allocation=D("1000"),
                          execution_price=price, risk_bucket="LOW")
    assert decide(policy(), request).reason_code == "INVALID_FINANCIAL_INPUT"


def test_stale_or_unknown_market_data_halts_new_entries():
    pol = policy(max_market_data_age_seconds=D("180"))
    assert decide(pol, buy()).reason_code == "MARKET_DATA_AGE_UNKNOWN"
    stale = decide(pol, buy(market_data_age_seconds=D("181")))
    assert stale.reason_code == "STALE_MARKET_DATA"
    assert stale.to_dict()["detail"] == {"market_data_age_seconds": "181", "max_market_data_age_seconds": "180"}
    assert decide(pol, buy(market_data_age_seconds=D("NaN"))).reason_code == "INVALID_FINANCIAL_INPUT"
    assert decide(pol, buy(market_data_age_seconds=180.0)).reason_code == "INVALID_FINANCIAL_INPUT"
    assert decide(pol, buy(market_data_age_seconds=D("180"))).approved


# -- correlation budget ---------------------------------------------------------------------


def test_correlated_entries_are_vetoed_and_unknown_correlation_fails_closed():
    pol = policy(correlation_ceiling=D("0.7"))
    held = state(position("ETHUSDT", "1000"), position("SOLUSDT", "1000"))
    assert decide(pol, buy()).approved  # nothing open: nothing to correlate with
    unknown = decide(pol, buy(return_correlations={"ETHUSDT": D("0.2")}), held)
    assert unknown.reason_code == "CORRELATION_UNKNOWN" and unknown.to_dict()["detail"] == {"symbol": "SOLUSDT"}
    breached = decide(pol, buy(return_correlations={"ethusdt": D("0.2"), "SOLUSDT": D("0.85")}), held)
    assert breached.reason_code == "CORRELATION_LIMIT_BREACHED"
    assert breached.to_dict()["detail"] == {"symbol": "SOLUSDT", "correlation": "0.85", "correlation_ceiling": "0.7"}
    assert decide(pol, buy(return_correlations={"ETHUSDT": D("0.7"), "SOLUSDT": D("-0.9")}), held).approved
    for bad in (0.5, D("1.01"), D("NaN"), "x", True):
        assert decide(pol, buy(return_correlations={"ETHUSDT": bad, "SOLUSDT": D("0")}), held).reason_code \
            == "INVALID_FINANCIAL_INPUT", bad


# -- cluster and quote-currency exposure -------------------------------------------------------


def test_cluster_exposure_limit_and_unknown_clusters():
    pol = policy(cluster_exposure_pct=D("0.30"),
                 symbol_clusters={"btcusdt": "l1", "ETHUSDT": "L1", "SOLUSDT": "L1", "DOGEUSDT": "MEME"})
    held = state(position("ETHUSDT", "2500"))
    over = decide(pol, buy("SOLUSDT"), held)
    assert over.reason_code == "CLUSTER_EXPOSURE_LIMIT"
    assert over.to_dict()["detail"] == {"cluster": "L1", "open_exposure": "2500", "requested_allocation": "1000",
                                        "limit": "3000.00"}
    assert decide(pol, buy("SOLUSDT", amount="500"), held).approved  # exactly at the limit
    assert decide(pol, buy("DOGEUSDT"), held).approved
    assert decide(pol, buy("XRPUSDT"), held).reason_code == "CLUSTER_UNKNOWN"
    # NB-4: a position whose cluster is unknown counts against every cluster, so losing the label never loosens.
    assert decide(pol, buy("DOGEUSDT"), state(position("XRPUSDT", "2500"))).reason_code == "CLUSTER_EXPOSURE_LIMIT"


def test_quote_currency_exposure_limit():
    assert [quote_currency(s, ("USDT", "USD", "BTC", "FDUSD")) for s in ("BTCUSDT", "BTCFDUSD", "ETHBTC", "USDT", "FOO")] \
        == ["USDT", "FDUSD", "BTC", None, None]
    pol = policy(quote_exposure_pct=D("0.30"))
    held = state(position("ETHUSDT", "2500"))
    assert decide(pol, buy("BTCUSDT"), held).reason_code == "QUOTE_CURRENCY_EXPOSURE_LIMIT"
    assert decide(pol, buy("ETHBTC"), held).approved
    assert decide(pol, buy("FOOBAR"), held).reason_code == "QUOTE_CURRENCY_UNKNOWN"
    assert decide(pol, buy("ETHBTC"), state(position("FOOBAR", "2500"))).reason_code == "QUOTE_CURRENCY_EXPOSURE_LIMIT"


# -- downsize-only sizing: EV (fractional Kelly), volatility, drawdown -------------------------------


def signal(p="0.55", win="0.02", loss="0.02", vol=None) -> SizingSignal:
    return SizingSignal(win_probability=D(p), win_return=D(win), loss_return=D(loss),
                        realized_volatility=None if vol is None else D(vol))


def test_ev_sizing_vetoes_without_a_positive_evidenced_edge():
    pol = policy(kelly_fraction=D("0.25"))
    assert decide(pol, buy()).reason_code == "SIZING_EV_UNKNOWN"  # NB-4: no evidence -> no entry
    assert decide(pol, buy(sizing_signal=SizingSignal(win_probability=D("0.6")))).reason_code == "SIZING_EV_UNKNOWN"
    assert decide(pol, buy(sizing_signal=signal(p="0.5"))).reason_code == "SIZING_EV_NOT_POSITIVE"
    assert decide(pol, buy(sizing_signal=signal(p="1.2"))).reason_code == "SIZING_EV_UNKNOWN"
    # f* = 0.501 / 0.02 - 0.499 / 0.02 = 0.1 -> ceiling 10000 x 0.25 x 0.1 = 250
    thin = decide(pol, buy(sizing_signal=signal(p="0.501")))
    assert thin.reason_code == "REQUEST_EXCEEDS_SIZING_CEILING" and D(thin.to_dict()["detail"]["sizing_ceiling"]) == 250
    assert decide(pol, buy(amount="250", sizing_signal=signal(p="0.501"))).approved
    # A strong edge never lifts the ceiling above the policy's own position cap (40% = 4000).
    strong = sizing_ceiling(pol, signal(p="0.9"), drawdown_pct=D("0"))
    assert strong.amount == D("4000.00") and decide(pol, buy(amount="4001", sizing_signal=signal(p="0.9"))).reason_code \
        == "REQUEST_EXCEEDS_SIZING_CEILING"


def test_volatility_targeting_and_drawdown_taper():
    pol = policy(volatility_target=D("0.01"))
    assert sizing_ceiling(pol, signal(vol="0.04"), drawdown_pct=None).amount == 2500
    assert decide(pol, buy(amount="2600", sizing_signal=signal(vol="0.04"))).reason_code == "REQUEST_EXCEEDS_SIZING_CEILING"
    assert decide(pol, buy(amount="2500", sizing_signal=signal(vol="0.04"))).approved
    assert decide(pol, buy(sizing_signal=signal(vol="0"))).reason_code == "SIZING_VOLATILITY_UNKNOWN"
    assert decide(pol, buy()).reason_code == "SIZING_VOLATILITY_UNKNOWN"
    taper = policy(drawdown_sizing=True)  # restrict at 10%: 4% drawdown keeps 60% of the 4000 cap
    assert sizing_ceiling(taper, None, drawdown_pct=D("0.04")).amount == 2400
    assert sizing_ceiling(taper, None, drawdown_pct=D("0.10")).amount == 0
    assert sizing_ceiling(taper, None, drawdown_pct=None).reason == "SIZING_DRAWDOWN_UNKNOWN"
    assert decide(taper, buy(amount="2500"), state(peak="10000", current="9600")).reason_code \
        == "REQUEST_EXCEEDS_SIZING_CEILING"
    assert decide(taper, buy(amount="2400"), state(peak="10000", current="9600")).approved


@pytest.mark.parametrize("p", ["0.52", "0.6", "0.75", "0.95"])
@pytest.mark.parametrize("vol", ["0.005", "0.02", "0.1"])
@pytest.mark.parametrize("dd", ["0", "0.03", "0.08"])
def test_the_ceiling_only_ever_shrinks_a_size(p, vol, dd):
    pol = policy(kelly_fraction=D("0.5"), volatility_target=D("0.01"), drawdown_sizing=True)
    ceiling = sizing_ceiling(pol, signal(p=p, vol=vol), drawdown_pct=D(dd))
    assert ceiling.reason is None and D("0") <= ceiling.amount <= CAPITAL * pol.max_position_pct
    weaker = sizing_ceiling(pol, signal(p=str(D(p) - D("0.01")), vol=vol), drawdown_pct=D(dd))
    assert weaker.amount <= ceiling.amount  # less evidence of edge never sizes up
    deeper = sizing_ceiling(pol, signal(p=p, vol=vol), drawdown_pct=D(dd) + D("0.01"))
    assert deeper.amount <= ceiling.amount


def test_the_sizer_shrinks_to_the_ceiling_and_the_engine_approves_what_it_proposes():
    pol = policy(kelly_fraction=D("0.25"), volatility_target=D("0.01"))
    sizer = PositionSizingService(pol)

    def inputs(sig, **kw):
        return SizingInputs(request_id="r1", symbol="BTCUSDT", risk_bucket="LOW", durable_free_quote_capital=CAPITAL,
                            symbol_exposure=D("0"), committed_quote=D("0"), sizing_signal=sig, **kw)

    free = PositionSizingService(policy()).propose(inputs(None))
    shrunk = sizer.propose(inputs(signal(vol="0.05")))  # vol ceiling 2000 < the 4000 the bucket would propose
    assert free.proposed_quote_allocation == 4000 and shrunk.proposed_quote_allocation == 2000
    assert shrunk.provenance["sizing_ceiling"] == "2000" and shrunk.provenance["inputs_digest"] \
        != sizer.propose(inputs(signal(vol="0.04"))).provenance["inputs_digest"]
    approved = decide(pol, buy(amount=str(shrunk.proposed_quote_allocation), sizing_signal=signal(vol="0.05")))
    assert approved.approved and approved.approved_allocation == shrunk.proposed_quote_allocation
    refused = sizer.propose(inputs(None))
    assert (refused.status, refused.reason_code, refused.proposed_quote_allocation) == \
        (SizingStatus.REFUSED, "SIZING_EV_UNKNOWN", 0)
    taper = PositionSizingService(policy(drawdown_sizing=True))
    assert taper.propose(inputs(None)).reason_code == "SIZING_DRAWDOWN_UNKNOWN"
    assert taper.propose(inputs(None, drawdown_pct=D("0.05"))).proposed_quote_allocation == 2000


def test_sizer_output_is_unchanged_with_every_guard_off():
    sizer = PositionSizingService(policy())
    base = SizingInputs(request_id="r1", symbol="BTCUSDT", risk_bucket="MEDIUM", durable_free_quote_capital=D("8000"),
                        symbol_exposure=D("0"), committed_quote=D("2000"))
    with_signal = SizingInputs(request_id="r1", symbol="BTCUSDT", risk_bucket="MEDIUM",
                               durable_free_quote_capital=D("8000"), symbol_exposure=D("0"),
                               committed_quote=D("2000"), sizing_signal=signal(p="0.4"), drawdown_pct=D("0.5"))
    a, b = sizer.propose(base), sizer.propose(with_signal)
    assert a == b and "sizing_ceiling" not in a.provenance  # inputs are ignored while every guard is off


# -- drawdown halts and the veto record ----------------------------------------------------------


def test_drawdown_and_daily_loss_halts_override_full_confidence():
    assert decide(policy(), buy(), state(peak="10000", current="8500")).reason_code == "DRAWDOWN_HALT_NEW_RISK"
    assert decide(policy(), buy(), state(peak="10000", current="8900")).reason_code == "DRAWDOWN_RESTRICT_NEW_RISK"
    assert decide(policy(), buy(), state(pnl="-500")).reason_code == "DAILY_LOSS_LIMIT_BREACHED"


def test_policy_inputs_are_validated():
    for bad in (dict(correlation_ceiling=D("1.5")), dict(cluster_exposure_pct=D("0")), dict(kelly_fraction=0.25),
                dict(volatility_target=D("0")), dict(max_market_data_age_seconds=D("-1")),
                dict(symbol_clusters={"BTCUSDT": ""}), dict(symbol_clusters={"BTCUSDT": 3}), dict(quote_currencies=()),
                dict(drawdown_sizing="yes")):
        with pytest.raises(ValueError):
            policy(**bad)


def test_every_veto_carries_its_structured_reason_and_zero_allocation():
    pol = policy(correlation_ceiling=D("0.5"), max_market_data_age_seconds=D("60"))
    vetoes = [decide(pol, buy(leverage=D("5"), market_data_age_seconds=D("1"))),
              decide(pol, buy(market_data_age_seconds=D("61"))),
              decide(pol, buy(market_data_age_seconds=D("1"), return_correlations={"ETHUSDT": D("0.9")}),
                     state(position("ETHUSDT", "1000")))]
    assert [v.reason_code for v in vetoes] == ["LEVERAGE_NOT_PERMITTED", "STALE_MARKET_DATA", "CORRELATION_LIMIT_BREACHED"]
    for v in vetoes:
        record = v.to_dict()
        assert record["approved"] is False and record["approved_allocation"] == "0" and record["detail"]
        assert all(isinstance(value, str) for value in record["detail"].values())


# -- review 7 regressions ------------------------------------------------------------------------

# Digest of the golden grid below as computed by the code BEFORE Task 007 (HEAD ab6eb0a). With every
# Task 007 guard off, the decisions and proposals must stay byte-identical (review 7 F9).
PRE_TASK007_GOLDEN_DIGEST = "1558c121cc8d1a3de90037ec40a9e4560951dd762e049dd9a9cadec7d45dd756"


def golden_digest(re_, ps_) -> str:
    today = datetime.now(UTC).date().isoformat()
    out = []
    for flags in ({}, {"sleeves_enabled": True, "count_unrealized_in_daily_loss": True}):
        pol = re_.RiskPolicy(total_capital=Decimal("10000"), **flags)
        for syms, cur, pnl, unreal in itertools.product(
                [(), ("BTCUSDT",), ("ETHUSDT", "SOLUSDT"), ("A1USDT", "A2USDT", "A3USDT", "A4USDT", "A5USDT")],
                ["10000", "9400", "8900", "8000"], ["0", "-600"], [Decimal("0"), Decimal("-300"), None]):
            positions = tuple(re_.PositionExposure(x, Decimal("10"), Decimal("100"), Decimal("1000"), "LOW") for x in syms)
            st = re_.RiskState(positions=positions, committed_quote=Decimal(1000 * len(syms)), realized_daily_pnl=Decimal(pnl),
                               peak_equity=Decimal("10000"), current_equity=Decimal(cur), state_ready=True,
                               accounting_day_utc=today, policy_version="phase3-risk-v1", unrealized_pnl=unreal)
            for sym, act, conf, amt, bucket, red in itertools.product(
                    ("BTCUSDT", "ETHUSDT"), ("BUY", "SELL"), (Decimal("0.65"), Decimal("0.95")), ("1000", "4500"),
                    ("LOW", "MEDIUM", "HIGH", "CRITICAL", "EXTREME"), (False, True)):
                req = re_.RiskRequest(symbol=sym, action=act, confidence=conf, requested_quote_allocation=Decimal(amt),
                                      execution_price=Decimal("100"), risk_bucket=bucket, reduce_only=red)
                out.append(re_.RiskEngine(pol).evaluate(req, st).to_dict())
        sizer = ps_.PositionSizingService(pol)
        for b, free, sx, cq in itertools.product(("LOW", "MEDIUM", "HIGH", "CRITICAL", "X"), ("0", "100", "8000"),
                                                  ("0", "1000"), ("0", "3000", "8000")):
            p = sizer.propose(ps_.SizingInputs("r", "BTCUSDT", b, Decimal(free), Decimal(sx), Decimal(cq)))
            out.append([p.status.value, p.reason_code, str(p.proposed_quote_allocation), dict(p.provenance)])
    return hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()


def test_decisions_and_proposals_match_the_pre_task007_code_with_every_guard_off():
    assert golden_digest(re_engine, ps) == PRE_TASK007_GOLDEN_DIGEST


def test_conflicting_or_ambiguous_evidence_fails_closed():
    pol = policy(correlation_ceiling=D("0.5"))
    held = state(position("ETHUSDT", "1000"))
    dup = decide(pol, buy(return_correlations={"ETHUSDT": D("0.9"), "ethusdt": D("0.1")}), held)  # F1
    assert dup.reason_code == "INVALID_FINANCIAL_INPUT" and dup.detail["field"] == "return_correlations"
    with pytest.raises(ValueError, match="more than once"):  # F6
        policy(cluster_exposure_pct=D("0.3"), symbol_clusters={"ethusdt": "L1", "ETHUSDT": "MEME"})


def test_a_decision_and_its_detail_are_immutable_and_hashable():
    decision = decide(policy(), buy(leverage=D("2")))
    with pytest.raises(TypeError):
        decision.detail["leverage"] = "1"  # F3
    assert hash(decision) == hash(decide(policy(), buy(leverage=D("2")))) and hash(decide(policy(), buy()))


@pytest.mark.parametrize("sig", [signal(loss="1E-1000005"), signal(win="1E-1000005")])
def test_overflowing_evidence_is_refused_as_unknown_not_raised(sig):
    pol = policy(kelly_fraction=D("0.25"))
    decision = decide(pol, buy(sizing_signal=sig))  # F4: never an exception out of evaluate()
    assert decision.reason_code == "SIZING_EV_UNKNOWN" and all(len(v) < 80 for v in decision.detail.values())
    proposal = PositionSizingService(pol).propose(SizingInputs(
        request_id="r", symbol="BTCUSDT", risk_bucket="LOW", durable_free_quote_capital=CAPITAL,
        symbol_exposure=D("0"), committed_quote=D("0"), sizing_signal=sig))
    assert (proposal.status, proposal.reason_code) == (SizingStatus.REFUSED, "SIZING_EV_UNKNOWN")
    assert decide(policy(volatility_target=D("0.01")), buy(sizing_signal=signal(vol="1E-1000005"))).reason_code \
        == "SIZING_VOLATILITY_UNKNOWN"


def test_extreme_finite_evidence_never_sizes_above_the_cap_and_its_detail_stays_bounded():
    pol = policy(kelly_fraction=D("0.25"))
    ceiling = sizing_ceiling(pol, signal(loss="1E-5000"), drawdown_pct=None)
    assert ceiling.amount == D("4000.00") and all(len(v) < 80 for v in ceiling.detail.values())
    assert decide(pol, buy(amount="4001", sizing_signal=signal(loss="1E-5000"))).reason_code \
        == "REQUEST_EXCEEDS_SIZING_CEILING"


def test_a_zero_restrict_level_tapers_to_zero_like_the_engine():
    pol = policy(drawdown_sizing=True, drawdown_warning_pct=D("0"), drawdown_restrict_pct=D("0"))  # F5
    assert sizing_ceiling(pol, None, drawdown_pct=D("0")).amount == 0
    assert decide(pol, buy()).reason_code == "DRAWDOWN_RESTRICT_NEW_RISK"


def test_every_task007_refusal_names_its_input():
    pol = policy(max_market_data_age_seconds=D("60"))  # F7
    assert decide(pol, buy()).to_dict()["detail"] == {"max_market_data_age_seconds": "60"}
    assert decide(pol, buy(market_data_age_seconds="x")).to_dict()["detail"] == {
        "field": "market_data_age_seconds", "max_market_data_age_seconds": "60"}
    assert decide(policy(), buy(leverage="x")).to_dict()["detail"] == {"field": "leverage"}
    assert "detail" not in decide(policy(), RiskRequest(symbol="BTCUSDT", action="BUY", confidence=D("1"),
                                                        requested_quote_allocation=D("1000"), execution_price=1.0,
                                                        risk_bucket="LOW")).to_dict()  # legacy refusals unchanged


def test_decisions_still_pickle_copy_and_print_as_before():
    """Review 8: the read-only detail must not change how an existing decision serializes or prints."""
    import copy
    import pickle

    for decision in (decide(policy(), buy()), decide(policy(), buy(leverage=D("2")))):
        assert pickle.loads(pickle.dumps(decision)) == decision and copy.deepcopy(decision) == decision
        assert "detail" not in repr(decision) and hash(decision) == hash(copy.deepcopy(decision))
    assert pickle.loads(pickle.dumps(decide(policy(), buy(leverage=D("2"))))).detail["leverage"] == "2"


def test_policy_maps_cannot_be_changed_or_mistyped_after_validation():
    pol = policy(cluster_exposure_pct=D("0.3"), symbol_clusters={"BTCUSDT": "L1"})
    with pytest.raises(TypeError):
        pol.symbol_clusters["SOLUSDT"] = "L1"  # review 8: no edit can bypass the validation
    with pytest.raises(ValueError, match="sequence"):
        policy(quote_currencies="USDT")


def test_an_extreme_drawdown_input_is_refused_not_raised():
    taper = policy(drawdown_sizing=True)
    assert sizing_ceiling(taper, None, drawdown_pct=D("9E+999999")).reason == "SIZING_DRAWDOWN_UNKNOWN"
    proposal = PositionSizingService(taper).propose(SizingInputs(
        request_id="r", symbol="BTCUSDT", risk_bucket="LOW", durable_free_quote_capital=CAPITAL,
        symbol_exposure=D("0"), committed_quote=D("0"), drawdown_pct=D("9E+999999")))
    assert proposal.reason_code == "SIZING_DRAWDOWN_UNKNOWN"


def test_frozen_maps_reject_attribute_rewrites():
    pol = policy(cluster_exposure_pct=D("0.3"), symbol_clusters={"BTCUSDT": "L1"})
    decision = decide(policy(), buy(leverage=D("2")))
    for frozen in (pol.symbol_clusters, decision.detail):  # review 9 L1
        with pytest.raises(AttributeError):
            frozen._items = ()
        with pytest.raises(AttributeError):
            del frozen._items
    assert dict(pol.symbol_clusters) == {"BTCUSDT": "L1"} and decision.detail["leverage"] == "2"


def test_the_sizer_and_the_engine_apply_the_same_non_terminating_drawdown():
    """Review 9 L2: with the shared drawdown_fraction, a tapered proposal is exactly what the engine approves."""
    pol = policy(drawdown_sizing=True)
    held = state(peak="9000", current="8700")  # 1/30 drawdown: a non-terminating fraction
    proposal = PositionSizingService(pol).propose(SizingInputs(
        request_id="r", symbol="BTCUSDT", risk_bucket="LOW", durable_free_quote_capital=CAPITAL,
        symbol_exposure=D("0"), committed_quote=D("0"), drawdown_pct=drawdown_fraction(D("9000"), D("8700"))))
    assert proposal.status is SizingStatus.PROPOSED and proposal.proposed_quote_allocation < 4000
    decision = decide(pol, buy(amount=format(proposal.proposed_quote_allocation, "f")), held)
    assert decision.approved and decision.approved_allocation == proposal.proposed_quote_allocation
