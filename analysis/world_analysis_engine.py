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


    def __init__(self):

        self.name = "World Analysis Engine"


    def build_market_data(
        self,
        symbol,
        price,
        analysis,
        score,
        sentiment_input=None,
    ):

        # ---------------------------------------------------
        # PHASE 2 / STEP 2C - EVIDENCE CONTRACT (CUTOVER COMPLETE)
        # ---------------------------------------------------
        #
        # macro_score / sentiment_score / risk_score are no longer
        # emitted. No production-grade macro, sentiment, or market-risk
        # provider exists in this repository (see Phase 2 Market-Data
        # Evidence Semantics Review), so there is no genuine numeric
        # value to report for these fields. Step 2A/2B established that
        # fabricating one (0.5, None, or any other sentinel) makes
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

        evidence_status = {

            "technical":
                technical_status.value,

            "macro":
                MarketDataEvidenceStatus
                .UNAVAILABLE_NO_PROVIDER.value,

            "sentiment":
                sentiment_status.value,

            "market_risk":
                MarketDataEvidenceStatus
                .UNAVAILABLE_NO_PROVIDER.value,

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

        return market_data


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