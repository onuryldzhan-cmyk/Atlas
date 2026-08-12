"""
Atlas AI Agent Fusion Engine v10.0

Multi intelligence voting system.

Responsibilities:

- Collect independent intelligence signals
- Normalize agent scores
- Weighted voting
- Generate fusion result

Agents:

Technical
Momentum
Risk
Macro
Sentiment


Atlas Brain only orchestrates.

"""


from __future__ import annotations


from dataclasses import dataclass
from typing import Dict

from analysis.evidence_status import MarketDataEvidenceStatus





# =====================================================
# RESULT MODEL
# =====================================================


@dataclass
class FusionResult:


    action: str


    confidence: float


    scores: Dict


    # Additive, backward-compatible: existing callers that construct
    # FusionResult with only action/confidence/scores are unaffected.
    # "FUSED_EVIDENCE" is the normal-path reason; "INSUFFICIENT_EVIDENCE"
    # marks the minimum-evidence-floor fail-safe result (see AgentFusion
    # .MIN_PARTICIPATING_AGENTS / .MIN_WEIGHT_COVERAGE), which is
    # distinct from a genuine HOLD vote reached via normal fusion.
    reason: str = "FUSED_EVIDENCE"



    def to_dict(self):

        return {


            "action":
                self.action,


            "confidence":
                round(
                    self.confidence,
                    3
                ),


            "scores":
                self.scores,


            "reason":
                self.reason

        }





# =====================================================
# AGENT FUSION ENGINE
# =====================================================



class AgentFusion:



    VERSION = "10.0"



    WEIGHTS = {


        "technical":
            0.40,


        "momentum":
            0.20,


        "risk":
            0.20,


        "macro":
            0.10,


        "sentiment":
            0.10

    }


    # =================================================
    # MINIMUM-EVIDENCE FLOOR (Step 2B, load-bearing since Step 2C)
    # =================================================
    #
    # Introduced in Step 2B while evaluate() still defaulted unavailable
    # agents to 0.5 (floor was inert then - all five agents were always
    # present). Since Step 2C, evaluate() excludes unavailable agents
    # from `signals` entirely, so this floor is now load-bearing: it is
    # what prevents a single remaining configured agent from reaching
    # 100% bucket-share confidence and clearing execution's
    # MIN_CONFIDENCE gate on its own.
    #
    # Raised from 2 to 3 (Step 2C threshold-boundary policy decision):
    # technical and momentum are not independent evidence - both derive
    # from the same RSI/EMA-trend observation, so a technical+momentum
    # pair is one real observation counted twice, not two independent
    # sources. That pair's combined configured weight (0.40+0.20=0.60)
    # is a hard ceiling that, under full directional agreement, always
    # produces bucket_share=1.0 and therefore final confidence exactly
    # equal to 0.60 - which coincidentally equals execution's
    # MIN_CONFIDENCE=60.0, making a non-independent, two-source
    # duplication confidence-eligible for execution. Requiring >=3
    # participating configured agents closes this categorically (no
    # 2-source combination can ever satisfy it) without touching
    # WEIGHTS, confidence scaling, or the execution gate. Accepted
    # consequence: since macro/sentiment/market_risk currently have no
    # provider, technical+momentum is the only combination ever
    # reachable today, so this floor is never cleared until a genuine
    # third evidence source exists - this is an intentional, accepted
    # fail-closed state, not a bug.

    MIN_PARTICIPATING_AGENTS = 3


    MIN_WEIGHT_COVERAGE = 0.50


    # =================================================
    # EVIDENCE CONTRACT (Step 2C)
    # =================================================
    #
    # Maps each configured agent name to the evidence_status key the
    # producer (WorldAnalysisEngine) uses for it. "risk" is kept as the
    # agent/WEIGHTS name (unchanged, preserves existing callers/tests);
    # "market_risk" is only the evidence_status label - chosen upstream
    # specifically so it is not confused with RiskEngine's independent
    # execution-risk authority, which reads neither this field nor this
    # agent's score.

    AGENT_EVIDENCE_STATUS_KEYS = {

        "technical":
            "technical",

        "macro":
            "macro",

        "sentiment":
            "sentiment",

        "risk":
            "market_risk",

    }


    # Raw score field each agent reads from market_data, consulted only
    # when that agent's evidence_status is AVAILABLE.

    AGENT_SCORE_KEYS = {

        "technical":
            "technical_score",

        "macro":
            "macro_score",

        "sentiment":
            "sentiment_score",

        "risk":
            "risk_score",

    }



    def __init__(
        self,
        config=None
    ):


        self.config = config or {}


        # Deterministic, machine-readable diagnostics from the most
        # recent evaluate() call: {agent_name: status_or_reason}.
        # Reset at the start of every evaluate() call.
        self.last_unavailable_agents = {}



        print(
            "[AGENTS] Agent Fusion Engine v10.0 initialized"
        )





    # =================================================
    # ANALYZE AGENTS
    # =================================================



    def evaluate(
        self,
        symbol,
        market_data
    ):


        # Reset up front (NB-1/INFO-3): if anything below this point
        # were ever to raise before the normal end-of-method assignment
        # is reached, the previous cycle's diagnostics must not remain
        # visible on this instance. An empty dict is a safe, honest
        # "no diagnostics available for this cycle" state - never
        # stale data from a prior, unrelated symbol/cycle.
        self.last_unavailable_agents = {}


        # -------------------------------------------------
        # EVIDENCE-STATUS CONSUMPTION (Step 2C)
        # -------------------------------------------------
        #
        # Only technical/macro/sentiment/risk are gated by
        # evidence_status - they each have a producer-declared status.
        # Momentum has no evidence_status entry (it is derived
        # internally from market_data["rsi"]/["trend"], not a producer
        # field), so it remains unconditional, exactly as before.
        #
        # A missing/non-dict evidence_status (e.g. a caller that does
        # not use WorldAnalysisEngine) is treated the same as every
        # field being unavailable - never as implicit availability.

        evidence_status = market_data.get(
            "evidence_status"
        )

        if not isinstance(
            evidence_status,
            dict,
        ):

            evidence_status = {}


        signals = {}

        unavailable = {}


        for agent_name, status_key in self.AGENT_EVIDENCE_STATUS_KEYS.items():


            status_value = evidence_status.get(
                status_key
            )


            if status_value != MarketDataEvidenceStatus.AVAILABLE.value:

                reason = (
                    status_value
                    if status_value is not None
                    else "STATUS_MISSING"
                )

                unavailable[agent_name] = reason

                print(
                    f"[AGENT] {agent_name}: "
                    f"EXCLUDED status={reason}"
                )

                continue


            score_key = self.AGENT_SCORE_KEYS[agent_name]

            score = market_data.get(
                score_key
            )

            if score is None:

                # Defensive: status claims AVAILABLE but the producer
                # did not actually supply a value. Excluded rather than
                # defaulted - never trust a missing value into 0.5.
                unavailable[agent_name] = (
                    "SCORE_MISSING_DESPITE_AVAILABLE_STATUS"
                )

                print(
                    f"[AGENT] {agent_name}: "
                    f"EXCLUDED status=SCORE_MISSING_DESPITE_AVAILABLE_STATUS"
                )

                continue


            action = self.score_to_action(
                score
            )

            signals[agent_name] = {

                "action":
                    action,

                "score":
                    round(
                        score,
                        3
                    )

            }

            print(

                f"[AGENT] {agent_name}: "
                f"{action} "
                f"{score:.2f}"

            )


        # -------------------------------------------------
        # MOMENTUM EVIDENCE VALIDATION (Step NB-1 + Step NB-3)
        # -------------------------------------------------
        #
        # NB-1: calculate_momentum() does raw numeric comparisons on
        # RSI (`rsi < 35`, `rsi > 70`) with no type guard of its own.
        # When "rsi" is PRESENT but not coercible to a number - a
        # malformed string, an arbitrary object, or an explicit None -
        # those comparisons raise, even though technical evidence for
        # the identical field would already be REJECTED_MALFORMED
        # (WorldAnalysisEngine._technical_evidence_status). This
        # mirrors that same producer-side parse check (a bare float()
        # conversion) on the identical field, so momentum detects the
        # same failure mode the producer already detects for this
        # input - it is not a new/independent heuristic.
        #
        # NB-3: a MISSING "rsi" or "trend" key must also exclude
        # momentum, not silently default to RSI=50 / trend=SIDEWAYS.
        # Both of those old defaults were numerically inert in
        # calculate_momentum()'s own formula (50 is neither <35 nor
        # >70; SIDEWAYS produces the same "no adjustment" as any
        # non-BULLISH/non-BEARISH value) - so they never injected a
        # false directional signal, but they let momentum cast a
        # HOLD@0.5 vote, counted toward the evidence floor's
        # participant/coverage totals, backed by zero real evidence.
        # This is the same fabricated-evidence class Step 2C already
        # eliminated for macro/sentiment/risk; momentum was the one
        # agent still exempt.
        #
        # In all cases, momentum is excluded the same way every other
        # unavailable agent is excluded (absent from `signals`,
        # recorded in `unavailable`) - never by raising, never by
        # fabricating a HOLD@0.5 score, never by coercing a missing
        # value to a neutral default.
        #
        # rsi=None is deliberately treated the same as a malformed
        # value, not specially: WorldAnalysisEngine's own RSI parse
        # check documents that it cannot currently distinguish
        # "insufficient candle history" from "truly malformed input" -
        # both surface as None upstream - so this does not invent a
        # distinction the producer itself does not make.
        #
        # A trend value that IS present but is neither "BULLISH" nor
        # "BEARISH" (e.g. "SIDEWAYS", or any other producer-supplied
        # string) is untouched by this check - that is genuine,
        # already-existing evidence, and its "no adjustment"
        # interpretation is unchanged, pre-existing algorithm behavior,
        # not a fabricated default.

        momentum_unavailable_reason = None

        if "rsi" not in market_data:

            momentum_unavailable_reason = "RSI_MISSING"

        elif not self._is_usable_rsi(
            market_data["rsi"]
        ):

            momentum_unavailable_reason = (
                "RSI_UNAVAILABLE_OR_MALFORMED"
            )

        elif "trend" not in market_data:

            momentum_unavailable_reason = "TREND_MISSING"


        if momentum_unavailable_reason is not None:

            unavailable["momentum"] = (
                momentum_unavailable_reason
            )

            print(
                f"[AGENT] momentum: "
                f"EXCLUDED status={momentum_unavailable_reason}"
            )

        else:

            momentum_score = self.calculate_momentum(
                market_data
            )

            momentum_action = self.score_to_action(
                momentum_score
            )

            signals["momentum"] = {

                "action":
                    momentum_action,

                "score":
                    round(
                        momentum_score,
                        3
                    )

            }

            print(

                f"[AGENT] momentum: "
                f"{momentum_action} "
                f"{momentum_score:.2f}"

            )


        self.last_unavailable_agents = unavailable

        return signals






    # =================================================
    # FUSION
    # =================================================



    def fuse(
        self,
        signals
    ):


        # -------------------------------------------------
        # MINIMUM-EVIDENCE FLOOR (Step 2B)
        # -------------------------------------------------
        #
        # Only configured signal names count toward participation and
        # coverage - an unconfigured/unknown name carries weight 0 and
        # must never inflate coverage. This is a fail-safe gate, not a
        # renormalization: bucket arithmetic below is unchanged.

        configured_participants = [

            name
            for name in signals
            if name in self.WEIGHTS

        ]

        participating_count = len(
            configured_participants
        )

        available_weight = sum(

            self.WEIGHTS[name]
            for name in configured_participants

        )

        total_configured_weight = sum(
            self.WEIGHTS.values()
        )

        weight_coverage = (

            available_weight / total_configured_weight

            if total_configured_weight > 0

            else 0

        )

        if (

            participating_count < self.MIN_PARTICIPATING_AGENTS

            or weight_coverage < self.MIN_WEIGHT_COVERAGE

        ):

            return FusionResult(

                action="HOLD",

                confidence=0.0,

                scores={},

                reason="INSUFFICIENT_EVIDENCE",

            )



        buy = 0

        sell = 0

        hold = 0




        for name, data in signals.items():


            weight = self.WEIGHTS.get(
                name,
                0
            )


            score = data["score"]


            action = data["action"]




            if action == "BUY":


                buy += score * weight



            elif action == "SELL":


                sell += (1-score) * weight



            else:


                hold += 0.5 * weight






        total = (

            buy +

            sell +

            hold

        )



        if total == 0:


            return FusionResult(

                action="HOLD",

                confidence=0.0,

                scores={}

            )





        scores = {


            "BUY":

                round(
                    buy/total,
                    3
                ),



            "SELL":

                round(
                    sell/total,
                    3
                ),



            "HOLD":

                round(
                    hold/total,
                    3
                )

        }



        action=max(

            scores,

            key=scores.get

        )



        bucket_confidence = scores[action]



        # -------------------------------------------------
        # AVAILABILITY-SCALED CONFIDENCE (Step 2C)
        # -------------------------------------------------
        #
        # `scores` (and bucket_confidence) reflect agreement only among
        # the agents actually present in `signals` - they say nothing
        # about how much of the configured evidence base that
        # represents. Reporting bucket_confidence directly would let
        # two fully agreeing agents read as 100% conviction even though
        # most configured evidence is missing. weight_coverage was
        # already computed above (for the evidence floor) and is reused
        # unchanged here, per the authorized design, to fold the
        # missing-evidence fraction into the externally reported
        # confidence:
        #
        #     final_confidence = bucket_confidence * weight_coverage
        #
        # `scores` itself is left unscaled - it stays the honest
        # internal bucket distribution among available evidence only.

        confidence = round(

            bucket_confidence * weight_coverage,

            4,

        )



        return FusionResult(

            action=action,

            confidence=confidence,

            scores=scores

        )






    # =================================================
    # HELPERS
    # =================================================



    def score_to_action(
        self,
        score
    ):



        if score >= 0.60:


            return "BUY"



        elif score <= 0.40:


            return "SELL"



        return "HOLD"






    @staticmethod
    def _is_usable_rsi(
        value
    ):
        """
        True when `value` (an RSI already known to be PRESENT in
        market_data) is coercible to a number. Callers are responsible
        for the "key missing" case separately - this only judges a
        value that is actually there.
        """

        try:

            float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):

            return False

        return True




    def calculate_momentum(
        self,
        market_data
    ):



        rsi = market_data.get(
            "rsi",
            50
        )

        # Defensive coercion, not a new default: evaluate() already
        # gates this call on _is_usable_rsi() for the "rsi" key when
        # present, so `rsi` reaching here should already be coercible
        # (including a numeric string, e.g. "55" - the same convention
        # WorldAnalysisEngine._technical_evidence_status() applies to
        # this identical field). This coerces that already-validated
        # value to the number it represents (not a fabricated one) so
        # the comparisons below don't raise on a numeric-string type,
        # and stays None-safe for any future direct caller that
        # bypasses that gate - in which case the RSI-based adjustment
        # below is simply skipped, not defaulted to neutral.
        try:

            rsi = float(
                rsi
            )

        except (
            TypeError,
            ValueError,
        ):

            rsi = None


        trend = market_data.get(
            "trend",
            "SIDEWAYS"
        )



        score=0.5




        if trend=="BULLISH":


            score +=0.20




        elif trend=="BEARISH":


            score -=0.20





        if rsi is not None and rsi <35:


            score +=0.10




        elif rsi is not None and rsi>70:


            score -=0.10





        return max(

            0,

            min(

                score,

                1

            )

        )