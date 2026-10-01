"""
Atlas AI
World Analysis Engine v1.0

Market environment intelligence layer.
"""

from datetime import datetime, timezone

from analysis.evidence_status import MarketDataEvidenceStatus


class WorldAnalysisEngine:


    VERSION = "1.0"


    # ---------------------------------------------------------
    # SENTIMENT (registry v4.66, GRANT-SENTIMENT-P3-IMPLEMENTATION)
    # ---------------------------------------------------------
    #
    # This module receives only plain values from MarketLoop (L3). It
    # must never import the Fear & Greed provider or anything that
    # touches the network: that would be the forbidden L4 -> L2 edge.
    #
    # The band labels are the provider's own output vocabulary, repeated
    # here as literals so no import is needed.
    SENTIMENT_BAND_FEAR = "FEAR"
    SENTIMENT_BAND_GREED = "GREED"
    SENTIMENT_BAND_NEUTRAL = "NEUTRAL"

    SENTIMENT_BANDS = frozenset({
        SENTIMENT_BAND_FEAR,
        SENTIMENT_BAND_GREED,
        SENTIMENT_BAND_NEUTRAL,
    })

    # AgentFusion.evaluate() turns a score into an action with
    # score_to_action (>= 0.60 BUY, <= 0.40 SELL, otherwise HOLD). The
    # sentiment vote is encoded with the same inputs registry v4.65's
    # measured AgentFusion fixture used, so the two are comparable.
    SENTIMENT_VOTE_SCORES = {
        "BUY": 0.75,
        "SELL": 0.25,
        "HOLD": 0.50,
    }


    # ---------------------------------------------------------
    # MACRO (registry v4.79, GRANT-BACKLOG001-MACRO-RISK-IMPLEMENTATION)
    # ---------------------------------------------------------
    #
    # Same boundary as sentiment: plain values only, no import of the
    # Treasury yield provider. The move labels are the provider's own
    # output vocabulary, repeated here as literals.
    MACRO_MOVE_RISING = "RISING"
    MACRO_MOVE_FALLING = "FALLING"
    MACRO_MOVE_FLAT = "FLAT"

    MACRO_MOVES = frozenset({
        MACRO_MOVE_RISING,
        MACRO_MOVE_FALLING,
        MACRO_MOVE_FLAT,
    })

    # Same score encoding as the sentiment vote, so the externally
    # sourced votes are comparable inside AgentFusion.
    MACRO_VOTE_SCORES = {
        "BUY": 0.75,
        "SELL": 0.25,
        "HOLD": 0.50,
    }

    # Sanity bound on plain basis-point inputs (30 percentage points).
    MACRO_MAX_ABS_BP = 3000

    # The provider's move threshold, repeated as a literal (no L2 import).
    MACRO_MOVE_THRESHOLD_BP = 25

    # ---------------------------------------------------------
    # MARKET RISK (registry v4.79)
    # ---------------------------------------------------------
    #
    # Fusion-input vote only. Nothing here reads or feeds RiskEngine or
    # any execution/capital path; "market_risk" is the evidence label
    # precisely so it is never confused with that authority.
    MARKET_RISK_REGIME_HIGH = "HIGH"
    MARKET_RISK_REGIME_LOW = "LOW"
    MARKET_RISK_REGIME_NEUTRAL = "NEUTRAL"

    MARKET_RISK_REGIMES = frozenset({
        MARKET_RISK_REGIME_HIGH,
        MARKET_RISK_REGIME_LOW,
        MARKET_RISK_REGIME_NEUTRAL,
    })

    MARKET_RISK_VOTE_SCORES = {
        "SELL": 0.25,
        "HOLD": 0.50,
    }


    def __init__(self):

        self.name = "World Analysis Engine"


    def build_market_data(
        self,
        symbol,
        price,
        analysis,
        score,
        sentiment_input=None,
        macro_input=None,
        market_risk_input=None,
    ):

        # ---------------------------------------------------
        # PHASE 2 / STEP 2C - EVIDENCE CONTRACT (CUTOVER COMPLETE)
        # ---------------------------------------------------
        #
        # macro_score / sentiment_score / risk_score are no longer
        # emitted as placeholders. No production-grade macro or
        # market-risk provider exists in this repository (see Phase 2
        # Market-Data Evidence Semantics Review), so there is no genuine
        # numeric value to report for those two fields. Sentiment is the
        # exception (registry v4.66): a real provider now exists, but in
        # the neutral band (Fear&Greed 25-74) it reports no directional
        # signal by design, not because no data source exists for it -
        # see the sentiment note below. Step 2A/2B established that
        # fabricating a score (0.5, None, or any other sentinel) makes
        # missing evidence indistinguishable from genuinely observed
        # neutral evidence downstream - so none is fabricated here.
        #
        # evidence_status remains the sole, authoritative statement of
        # what this producer does and does not know. AgentFusion now
        # reads evidence_status directly (Step 2C) and excludes any
        # agent whose status is not AVAILABLE, instead of defaulting
        # it to 0.5.
        #
        # Registry v4.66: sentiment is the one exception. When MarketLoop
        # supplies a Fear & Greed reading, sentiment becomes AVAILABLE only
        # in the fear or greed band; see _sentiment_evidence(). Without a
        # reading it stays UNAVAILABLE_NO_PROVIDER exactly as before.
        #
        # Registry v4.79 supersedes the "no macro or market-risk provider"
        # statement above: a Treasury yield provider (macro) and a
        # realized-volatility regime provider (market_risk) now exist and
        # follow the same contract - AVAILABLE with a score only for a
        # well-formed reading, UNAVAILABLE_PROVIDER_ERROR on provider
        # failure, UNAVAILABLE_NO_PROVIDER when MarketLoop supplies no
        # input. See _macro_evidence() and _market_risk_evidence().
        technical_status = self._technical_evidence_status(
            analysis
        )

        (
            sentiment_status,
            sentiment_score,
            sentiment_evidence,
        ) = self._sentiment_evidence(
            sentiment_input,
            analysis,
            technical_status,
        )

        (
            macro_status,
            macro_score,
            macro_evidence,
        ) = self._macro_evidence(
            macro_input,
        )

        (
            market_risk_status,
            risk_score,
            market_risk_evidence,
        ) = self._market_risk_evidence(
            market_risk_input,
        )

        evidence_status = {

            "technical":
                technical_status.value,

            "macro":
                macro_status.value,

            "sentiment":
                sentiment_status.value,

            "market_risk":
                market_risk_status.value,

        }

        market_data = {


            "symbol": symbol,

            "price": price,


            "technical_score": score,


            "rsi":
                analysis.get(
                    "rsi"
                ),


            "ema20":
                analysis.get(
                    "ema20"
                ),


            "ema50":
                analysis.get(
                    "ema50"
                ),


            "adx":
                analysis.get(
                    "adx"
                ),


            "trend":
                analysis.get(
                    "trend"
                ),


            "evidence_status":
                evidence_status,


            "timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat()

        }

        # Emitted only when AVAILABLE - never a placeholder (Step 2C).
        if sentiment_score is not None:

            market_data["sentiment_score"] = sentiment_score

        # Audit context only; AgentFusion does not read it. Deliberately
        # not named "fear_greed": ReasoningAdapter reads that key.
        if sentiment_evidence is not None:

            market_data["sentiment_evidence"] = sentiment_evidence

        # Registry v4.79: same emission rule for macro and market_risk.
        # The audit keys are deliberately not ReasoningAdapter inputs
        # ("fed_policy", "inflation", "fear_greed").
        if macro_score is not None:

            market_data["macro_score"] = macro_score

        if macro_evidence is not None:

            market_data["macro_evidence"] = macro_evidence

        if risk_score is not None:

            market_data["risk_score"] = risk_score

        if market_risk_evidence is not None:

            market_data["market_risk_evidence"] = market_risk_evidence

        return market_data


    # =========================================================
    # MACRO (registry v4.79)
    # =========================================================

    @classmethod
    def macro_vote(
        cls,
        move,
        curve_inverted
    ):
        """
        The owner-approved rule (registry v4.79), on the US 10-year
        Treasury yield's move over the last 20 trading days:

            RISING  (>= +25bp)                       -> SELL (risk-off)
            FALLING (<= -25bp), curve not inverted   -> BUY  (risk-on)
            FALLING (<= -25bp), curve inverted       -> HOLD
            FLAT    (between)                        -> HOLD

        "Inverted" means 10Y minus 2Y is below zero: falling yields while
        the curve signals recession are not read as a bullish easing.
        ``curve_inverted`` must be an exact bool; any other move raises.
        """

        if type(curve_inverted) is not bool:

            raise ValueError(
                f"curve_inverted must be a bool, got {curve_inverted!r}"
            )

        if move == cls.MACRO_MOVE_RISING:

            return "SELL"

        if move == cls.MACRO_MOVE_FALLING:

            return "HOLD" if curve_inverted else "BUY"

        if move == cls.MACRO_MOVE_FLAT:

            return "HOLD"

        raise ValueError(
            f"no macro vote exists for move {move!r}"
        )


    @classmethod
    def _expected_macro_move(
        cls,
        change_bp
    ):
        """
        The move label a well-formed input must carry for ``change_bp``.
        Repeats the provider's +/-25bp threshold as a literal (no L2
        import), so a label that contradicts its own number is rejected
        rather than trusted - the same agreement check market_risk makes.
        """

        if change_bp >= cls.MACRO_MOVE_THRESHOLD_BP:

            return cls.MACRO_MOVE_RISING

        if change_bp <= -cls.MACRO_MOVE_THRESHOLD_BP:

            return cls.MACRO_MOVE_FALLING

        return cls.MACRO_MOVE_FLAT


    @staticmethod
    def _is_iso_date(
        value
    ):

        if not isinstance(value, str) or len(value) != 10:

            return False

        try:

            datetime.strptime(
                value,
                "%Y-%m-%d",
            )

        except ValueError:

            return False

        return True


    @classmethod
    def _macro_evidence(
        cls,
        macro_input
    ):
        """
        Return ``(status, score_or_None, evidence_or_None)``.

        ``macro_input`` is the plain dict MarketLoop builds:
        ``provider_status``, ``ten_year_change_bp`` (int),
        ``curve_spread_bp`` (int), ``move`` and ``observed_date``.

        Fail-closed: a score is returned only for a well-formed AVAILABLE
        reading. A provider failure is UNAVAILABLE_PROVIDER_ERROR; a
        malformed input is REJECTED_MALFORMED. Neither ever scores.
        """

        if macro_input is None:

            return (
                MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER,
                None,
                None,
            )

        if not isinstance(macro_input, dict):

            return (
                MarketDataEvidenceStatus.REJECTED_MALFORMED,
                None,
                {"reason": "MALFORMED_MACRO_INPUT"},
            )

        provider_status = macro_input.get(
            "provider_status"
        )

        if provider_status == (
            MarketDataEvidenceStatus.UNAVAILABLE_PROVIDER_ERROR.value
        ):

            reason = macro_input.get(
                "reason"
            )

            return (
                MarketDataEvidenceStatus.UNAVAILABLE_PROVIDER_ERROR,
                None,
                {
                    "ten_year_change_bp": None,
                    "curve_spread_bp": None,
                    "move": None,
                    "vote": None,
                    "reason": (
                        reason
                        if isinstance(reason, str)
                        else "UNSPECIFIED"
                    ),
                },
            )

        change_bp = macro_input.get(
            "ten_year_change_bp"
        )

        spread_bp = macro_input.get(
            "curve_spread_bp"
        )

        move = macro_input.get(
            "move"
        )

        observed_date = macro_input.get(
            "observed_date"
        )

        if (
            provider_status != MarketDataEvidenceStatus.AVAILABLE.value
            or type(change_bp) is not int
            or type(spread_bp) is not int
            or abs(change_bp) > cls.MACRO_MAX_ABS_BP
            or abs(spread_bp) > cls.MACRO_MAX_ABS_BP
            or not isinstance(move, str)
            or move not in cls.MACRO_MOVES
            or not cls._is_iso_date(observed_date)
            or move != cls._expected_macro_move(change_bp)
        ):

            return (
                MarketDataEvidenceStatus.REJECTED_MALFORMED,
                None,
                {"reason": "MALFORMED_MACRO_INPUT"},
            )

        curve_inverted = spread_bp < 0

        vote = cls.macro_vote(
            move,
            curve_inverted,
        )

        return (
            MarketDataEvidenceStatus.AVAILABLE,
            cls.MACRO_VOTE_SCORES[vote],
            {
                "source": "US_TREASURY_PAR_YIELD_CURVE",
                "observed_date": observed_date,
                "ten_year_change_bp": change_bp,
                "curve_spread_bp": spread_bp,
                "curve_inverted": curve_inverted,
                "move": move,
                "vote": vote,
                "reason": "OK",
            },
        )


    # =========================================================
    # MARKET RISK (registry v4.79)
    # =========================================================

    @classmethod
    def market_risk_vote(
        cls,
        regime
    ):
        """
        The owner-decided three-zone rule (registry v4.79), on trailing
        realized volatility against its own ~p20 / ~p80:

            HIGH    (above p80)     -> SELL (caution / risk-off)
            NEUTRAL (p20 .. p80)    -> HOLD
            LOW     (below p20)     -> HOLD (permissive: adds no caution,
                                             but volatility is not
                                             directional, so it never
                                             votes BUY)

        Any other regime raises.
        """

        if regime == cls.MARKET_RISK_REGIME_HIGH:

            return "SELL"

        if regime in (
            cls.MARKET_RISK_REGIME_NEUTRAL,
            cls.MARKET_RISK_REGIME_LOW,
        ):

            return "HOLD"

        raise ValueError(
            f"no market risk vote exists for regime {regime!r}"
        )


    @staticmethod
    def _finite_non_negative(
        value
    ):

        # No import: this module's import set is pinned to datetime and
        # the L1 evidence vocabulary. NaN fails the self-comparison, and
        # +inf fails the subtraction check (inf - inf is NaN).
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and value == value
            and value - value == 0
            and value >= 0
        )


    @classmethod
    def _market_risk_evidence(
        cls,
        market_risk_input
    ):
        """
        Return ``(status, score_or_None, evidence_or_None)``.

        ``market_risk_input`` is the plain dict MarketLoop builds:
        ``provider_status``, ``regime``, ``realized_volatility``, ``p20``,
        ``p80`` and ``reference_windows``.

        Fail-closed exactly like _macro_evidence(). The regime label must
        also agree with the numbers it came from, so a contradictory
        input is rejected rather than trusted.
        """

        if market_risk_input is None:

            return (
                MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER,
                None,
                None,
            )

        if not isinstance(market_risk_input, dict):

            return (
                MarketDataEvidenceStatus.REJECTED_MALFORMED,
                None,
                {"reason": "MALFORMED_MARKET_RISK_INPUT"},
            )

        provider_status = market_risk_input.get(
            "provider_status"
        )

        if provider_status == (
            MarketDataEvidenceStatus.UNAVAILABLE_PROVIDER_ERROR.value
        ):

            reason = market_risk_input.get(
                "reason"
            )

            return (
                MarketDataEvidenceStatus.UNAVAILABLE_PROVIDER_ERROR,
                None,
                {
                    "regime": None,
                    "vote": None,
                    "reason": (
                        reason
                        if isinstance(reason, str)
                        else "UNSPECIFIED"
                    ),
                },
            )

        regime = market_risk_input.get(
            "regime"
        )

        current = market_risk_input.get(
            "realized_volatility"
        )

        p20 = market_risk_input.get(
            "p20"
        )

        p80 = market_risk_input.get(
            "p80"
        )

        reference_windows = market_risk_input.get(
            "reference_windows"
        )

        well_formed = (
            provider_status == MarketDataEvidenceStatus.AVAILABLE.value
            and isinstance(regime, str)
            and regime in cls.MARKET_RISK_REGIMES
            and cls._finite_non_negative(current)
            and cls._finite_non_negative(p20)
            and cls._finite_non_negative(p80)
            and p20 <= p80
            and type(reference_windows) is int
            and reference_windows > 0
        )

        if well_formed:

            if current > p80:

                expected = cls.MARKET_RISK_REGIME_HIGH

            elif current < p20:

                expected = cls.MARKET_RISK_REGIME_LOW

            else:

                expected = cls.MARKET_RISK_REGIME_NEUTRAL

            well_formed = expected == regime

        if not well_formed:

            return (
                MarketDataEvidenceStatus.REJECTED_MALFORMED,
                None,
                {"reason": "MALFORMED_MARKET_RISK_INPUT"},
            )

        vote = cls.market_risk_vote(
            regime,
        )

        return (
            MarketDataEvidenceStatus.AVAILABLE,
            cls.MARKET_RISK_VOTE_SCORES[vote],
            {
                "source": "REALIZED_VOLATILITY_1M_CANDLES",
                "regime": regime,
                "realized_volatility": current,
                "p20": p20,
                "p80": p80,
                "reference_windows": reference_windows,
                "vote": vote,
                "reason": "OK",
            },
        )


    # =========================================================
    # SENTIMENT (registry v4.66)
    # =========================================================

    @classmethod
    def sentiment_vote(
        cls,
        band,
        trend
    ):
        """
        The owner-confirmed rule (registry v4.66):

            FEAR  + BULLISH               -> BUY
            FEAR  + BEARISH or ambiguous  -> SELL
            GREED + BULLISH               -> SELL (overextension read)
            GREED + BEARISH or ambiguous  -> HOLD

        ``trend`` is "BULLISH", "BEARISH", or None for ambiguous. Any
        other band - including NEUTRAL, which must never vote - raises.
        """

        if band == cls.SENTIMENT_BAND_FEAR:

            return "BUY" if trend == "BULLISH" else "SELL"

        if band == cls.SENTIMENT_BAND_GREED:

            return "SELL" if trend == "BULLISH" else "HOLD"

        raise ValueError(
            f"no sentiment vote exists for band {band!r}"
        )


    @staticmethod
    def _sentiment_trend(
        analysis,
        technical_status
    ):
        """
        Reuse the technical agent's already-computed trend (EMA20 vs
        EMA50 from TechnicalAnalyzer) - never recompute it.

        Only an exact "BULLISH"/"BEARISH" backed by AVAILABLE technical
        evidence counts. Anything else - NEUTRAL, missing, malformed, or
        technical evidence that was itself rejected - is ambiguous (None),
        which routes both bands to their conservative branch.
        """

        if technical_status is not MarketDataEvidenceStatus.AVAILABLE:

            return None

        trend = analysis.get(
            "trend"
        )

        if isinstance(trend, str) and trend in ("BULLISH", "BEARISH"):

            return trend

        return None


    @classmethod
    def _sentiment_evidence(
        cls,
        sentiment_input,
        analysis,
        technical_status
    ):
        """
        Return ``(status, score_or_None, evidence_or_None)``.

        ``sentiment_input`` is the plain dict MarketLoop builds:
        ``provider_status`` ("AVAILABLE" or "UNAVAILABLE_PROVIDER_ERROR"),
        ``value`` (int 0-100 or None), ``band`` ("FEAR"/"GREED"/"NEUTRAL"
        or None) and ``reason``.

        Fail-closed: a score is returned only for a well-formed AVAILABLE
        reading in the fear or greed band. The neutral band reports
        UNAVAILABLE_NO_PROVIDER (the owner's exact status code) so it can
        never become a participating vote.
        """

        if sentiment_input is None:

            return (
                MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER,
                None,
                None,
            )

        if not isinstance(sentiment_input, dict):

            return (
                MarketDataEvidenceStatus.REJECTED_MALFORMED,
                None,
                {"reason": "MALFORMED_SENTIMENT_INPUT"},
            )

        provider_status = sentiment_input.get(
            "provider_status"
        )

        if provider_status == (
            MarketDataEvidenceStatus.UNAVAILABLE_PROVIDER_ERROR.value
        ):

            reason = sentiment_input.get(
                "reason"
            )

            return (
                MarketDataEvidenceStatus.UNAVAILABLE_PROVIDER_ERROR,
                None,
                {
                    "fear_greed_index": None,
                    "band": None,
                    "vote": None,
                    "reason": (
                        reason
                        if isinstance(reason, str)
                        else "UNSPECIFIED"
                    ),
                },
            )

        value = sentiment_input.get(
            "value"
        )

        band = sentiment_input.get(
            "band"
        )

        if (
            provider_status != MarketDataEvidenceStatus.AVAILABLE.value
            or type(value) is not int
            or not 0 <= value <= 100
            or not isinstance(band, str)
            or band not in cls.SENTIMENT_BANDS
        ):

            return (
                MarketDataEvidenceStatus.REJECTED_MALFORMED,
                None,
                {"reason": "MALFORMED_SENTIMENT_INPUT"},
            )

        if band == cls.SENTIMENT_BAND_NEUTRAL:

            # Design C (owner choice 2026-10-01): with Fear & Greed neutral, a
            # crowded perpetual funding rate for this coin may give the one
            # sentiment vote, through the SAME owner-confirmed rule: crowded
            # short reads like FEAR, crowded long like GREED. Anything else
            # (absent, unavailable, malformed, neutral) keeps the abstention,
            # so missing evidence can never raise confidence (NB-4) and the
            # roster stays five agents (NB-5).
            funding = sentiment_input.get("funding")
            mapped = None
            if (isinstance(funding, dict) and funding.get("available") is True
                    and funding.get("band") in ("CROWDED_SHORT", "CROWDED_LONG")):
                mapped = cls.SENTIMENT_BAND_FEAR if funding["band"] == "CROWDED_SHORT" else cls.SENTIMENT_BAND_GREED
            # Audit 2026-10-01 F-1 (HIGH): AgentFusion's NB-5 denominator makes a
            # dissenting HOLD/SELL vote RAISE the winner's confidence versus an
            # abstention. Until fuse() is fixed (separate governed change), funding
            # may only add agreeing BUY evidence; any other funding read abstains.
            vote = cls.sentiment_vote(mapped, cls._sentiment_trend(analysis, technical_status)) if mapped else None
            if vote == "BUY":
                trend = cls._sentiment_trend(analysis, technical_status)
                return (
                    MarketDataEvidenceStatus.AVAILABLE,
                    cls.SENTIMENT_VOTE_SCORES[vote],
                    {
                        "fear_greed_index": value,
                        "band": band,
                        "funding_rate": funding.get("rate"),
                        "funding_band": funding.get("band"),
                        "trend_basis": trend or "AMBIGUOUS",
                        "vote": vote,
                        "reason": "FUNDING_RATE_CROWDED",
                    },
                )

            return (
                MarketDataEvidenceStatus.UNAVAILABLE_NO_PROVIDER,
                None,
                {
                    "fear_greed_index": value,
                    "band": band,
                    "vote": None,
                    "reason": "NEUTRAL_BAND_NO_DIRECTIONAL_SIGNAL",
                },
            )

        trend = cls._sentiment_trend(
            analysis,
            technical_status,
        )

        vote = cls.sentiment_vote(
            band,
            trend,
        )

        return (
            MarketDataEvidenceStatus.AVAILABLE,
            cls.SENTIMENT_VOTE_SCORES[vote],
            {
                "fear_greed_index": value,
                "band": band,
                "trend_basis": trend or "AMBIGUOUS",
                "vote": vote,
                "reason": "OK",
            },
        )


    # =========================================================
    # EVIDENCE STATUS HELPERS
    # =========================================================

    @staticmethod
    def _technical_evidence_status(
        analysis
    ):
        """
        Determine technical evidence status from the same RSI input
        MarketLoop.calculate_score() consumes, without touching or
        depending on calculate_score() itself.

        This mirrors calculate_score()'s own parse check (a bare
        ``float(rsi)`` conversion) applied to the identical input
        field, so it detects the same failure mode calculate_score()
        already guards against - it does not introduce a new or
        independent malformed-input heuristic.

        Known Step 2A limitation: TechnicalAnalyzer.rsi() also returns
        None when too few candles are available (insufficient history),
        which is indistinguishable here from truly malformed RSI input.
        Disambiguating "insufficient history" from "malformed value"
        would require instrumenting calculate_score() or
        TechnicalAnalyzer directly, which is out of scope for Step 2A.
        REJECTED_MALFORMED is therefore a conservative, transitional
        status covering both cases.
        """

        rsi = analysis.get(
            "rsi"
        )

        try:

            float(
                rsi
            )

        except (
            TypeError,
            ValueError,
        ):

            return (
                MarketDataEvidenceStatus
                .REJECTED_MALFORMED
            )

        return (
            MarketDataEvidenceStatus
            .AVAILABLE
        )



    def build_market_state(
        self,
        market_data
    ):


        return {


            "symbol":
                market_data["symbol"],


            "price":
                market_data["price"],


            "rsi":
                market_data["rsi"],


            "trend":
                market_data["trend"],


            "score":
                market_data["technical_score"],


            "timestamp":
                market_data["timestamp"]

        }