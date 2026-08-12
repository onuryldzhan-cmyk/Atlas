"""
Atlas AI
World Analysis Engine v1.0

Market environment intelligence layer.
"""

from datetime import datetime, timezone

from analysis.evidence_status import MarketDataEvidenceStatus


class WorldAnalysisEngine:


    VERSION = "1.0"


    def __init__(self):

        self.name = "World Analysis Engine"


    def build_market_data(
        self,
        symbol,
        price,
        analysis,
        score
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
        technical_status = self._technical_evidence_status(
            analysis
        )

        evidence_status = {

            "technical":
                technical_status.value,

            "macro":
                MarketDataEvidenceStatus
                .UNAVAILABLE_NO_PROVIDER.value,

            "sentiment":
                MarketDataEvidenceStatus
                .UNAVAILABLE_NO_PROVIDER.value,

            "market_risk":
                MarketDataEvidenceStatus
                .UNAVAILABLE_NO_PROVIDER.value,

        }

        return {


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