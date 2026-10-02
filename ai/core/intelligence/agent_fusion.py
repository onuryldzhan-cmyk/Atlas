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

import logging as _logging

# Diagnostics go to the log, not stdout (registry v5.50: 20 coins x every cycle flooded the console).
_log = _logging.getLogger(__name__)





# =====================================================
# RESULT MODEL
# =====================================================


@dataclass
class AgentFusionResult:


    action: str


    confidence: float


    scores: Dict


    # Additive, backward-compatible: existing callers that construct
    # AgentFusionResult with only action/confidence/scores are unaffected.
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
    # MASS QUANTIZATION (M-2)
    # =================================================
    #
    # Every bucket mass is a sum of (configured weight x vote factor)
    # products. Weights carry two decimal places and scores are rounded
    # to three, so no semantically meaningful digit exists beyond about
    # five decimal places. Quantizing the confidence ratio's numerator
    # and denominator at twelve places therefore cannot change a real
    # value; it only removes binary floating-point accumulation noise.
    #
    # This is load-bearing for the M-2 monotonicity guarantee, not
    # cosmetic. The same mathematical quantity is reached by different
    # summation paths depending on which participants are present (a
    # removed participant's weight moves out of `total` and into
    # `missing_weight`), so two mathematically identical results can
    # differ in the last bit. Without quantization, an exact tie can
    # straddle the 4-decimal rounding boundary and report a +0.0001
    # "increase" on evidence removal. Grid verification found exactly
    # that: 8 such artifacts unquantized, 0 at this precision.

    MASS_PRECISION = 12


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



        _log.debug(
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

                _log.debug(
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

                _log.debug(
                    f"[AGENT] {agent_name}: "
                    f"EXCLUDED status=SCORE_MISSING_DESPITE_AVAILABLE_STATUS"
                )

                continue


            if not self._is_usable_score(
                score
            ):

                # Package 4 red team: the value is present but outside the
                # contractual [0, 1] score range (or NaN, or not a number
                # at all). fuse() excludes such a participant defensively
                # too; catching it here as well is what turns a silent
                # exclusion into a named, auditable diagnostic on the
                # canonical producer path.
                unavailable[agent_name] = (
                    "SCORE_OUT_OF_CONTRACT_RANGE"
                )

                _log.debug(
                    f"[AGENT] {agent_name}: "
                    f"EXCLUDED status=SCORE_OUT_OF_CONTRACT_RANGE"
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

            _log.debug(

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

            _log.debug(
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

            _log.debug(

                f"[AGENT] momentum: "
                f"{momentum_action} "
                f"{momentum_score:.2f}"

            )


        self.last_unavailable_agents = unavailable

        return signals






    # =================================================
    # FUSION
    # =================================================



    # Audit 2026-10-01 F-1 fix, OFF by default (set per instance by the composition root).
    full_weight_denominator = False

    def fuse(
        self,
        signals
    ):
        """Fuse agent votes into one action and an availability-adjusted confidence.

        T-0001 (2026-10-02): split into the helpers below with no behaviour
        change (pinned by tests/test_agent_fusion_refactor_golden.py).
        """

        signals = self._usable_signals(
            signals
        )

        available_weight, total_configured_weight, sufficient = (
            self._evidence_coverage(
                signals
            )
        )

        if not sufficient:

            return AgentFusionResult(

                action="HOLD",

                confidence=0.0,

                scores={},

                reason="INSUFFICIENT_EVIDENCE",

            )

        buy, sell, hold = self._bucket_masses(
            signals
        )

        total = (

            buy +

            sell +

            hold

        )

        if total == 0:

            return AgentFusionResult(

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

        action, winning_mass = self._select_winner(
            buy,
            sell,
            hold,
        )

        confidence = self._availability_confidence(
            winning_mass,
            total,
            available_weight,
            total_configured_weight,
        )

        return AgentFusionResult(

            action=action,

            confidence=confidence,

            scores=scores

        )


    def _usable_signals(
        self,
        signals
    ):

        # -------------------------------------------------
        # SCORE RANGE GUARD (Package 4 red team)
        # -------------------------------------------------
        #
        # Every score is contractually a fraction in [0, 1], and the live
        # producer (MarketLoop.calculate_score) does clamp to that range.
        # fuse() never checked, though, and it is a public method: a score
        # outside the range makes a bucket mass exceed the participant's
        # weight, or go negative, and the resulting confidence escapes
        # [0, 1] entirely (an out-of-range input was measured producing
        # confidence 1.3333 - a nonsensical 133% conviction).
        #
        # Such a participant is excluded, not clamped, for the same reason
        # NB-1/NB-3 exclude a malformed RSI rather than defaulting it: a
        # value Atlas cannot interpret is absent evidence, and absent
        # evidence must cost the participant its weight rather than be
        # rewritten into a plausible one. Exclusion is exactly the removal
        # case the availability charge below already handles, so it is
        # fail-closed by construction and cannot raise confidence.
        #
        # With every surviving factor in [0, 1] and every weight
        # non-negative, winning_mass <= total <= total + missing_weight,
        # so the reported confidence is now bounded to [0, 1] by the
        # arithmetic itself rather than by a downstream clamp.

        return {

            name: data

            for name, data in signals.items()

            if self._is_usable_score(
                data.get(
                    "score"
                )
                if isinstance(
                    data,
                    dict,
                )
                else None
            )

        }


    def _evidence_coverage(
        self,
        signals
    ):
        """(available_weight, total_configured_weight, passes the floor)."""

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

        sufficient = not (

            participating_count < self.MIN_PARTICIPATING_AGENTS

            or weight_coverage < self.MIN_WEIGHT_COVERAGE

        )

        return available_weight, total_configured_weight, sufficient


    def _bucket_masses(
        self,
        signals
    ):
        """Weighted BUY / SELL / HOLD mass of the usable signals."""

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

        return buy, sell, hold


    def _select_winner(
        self,
        buy,
        sell,
        hold,
    ):
        """(winning action, its quantized mass)."""

        # -------------------------------------------------
        # WINNER-SELECTION AUTHORITY (M-2)
        # -------------------------------------------------
        #
        # The winning bucket is chosen from bucket MASS quantized at
        # MASS_PRECISION - the identical quantity the confidence
        # numerator below divides - and never from `scores`, which is a
        # 3-decimal distribution kept for display and backward
        # compatibility. Decision authority must not depend on
        # presentation rounding.
        #
        # Selecting on `scores` was a real monotonicity defect, not a
        # cosmetic one. Two buckets whose true masses differ only in the
        # 4th decimal collapse onto one 3-decimal share, and max() then
        # returns the first key in insertion order (BUY, SELL, HOLD) -
        # so BUY could be declared the winner while SELL held strictly
        # more mass, while the confidence numerator still used the
        # winner's own, smaller, unrounded mass. Removing a participant
        # broke the collision, the larger true mass became the
        # numerator, and reported confidence ROSE on evidence removal -
        # exactly what M-2 exists to forbid. Independent grid search
        # found 69 such inversions across 6.7M removals, up to +0.0007,
        # including one where the removed participant voted with factor
        # 1.0 so the denominator was provably unchanged.
        #
        # With selection and numerator reading the same quantized value,
        # the numerator is max_b q(mass_b). No removal can increase any
        # bucket's mass and q is monotone, so the numerator is
        # non-increasing while the denominator is non-decreasing: the
        # quotient can only fall. A surviving tie is now a genuine
        # equality of quantized mass, so either branch of the
        # deterministic insertion-order tie-break yields the identical
        # numerator and cannot invert anything.

        quantized_mass = {

            "BUY":
                round(
                    buy,
                    self.MASS_PRECISION,
                ),

            "SELL":
                round(
                    sell,
                    self.MASS_PRECISION,
                ),

            "HOLD":
                round(
                    hold,
                    self.MASS_PRECISION,
                ),

        }

        action=max(

            quantized_mass,

            key=quantized_mass.get

        )

        # The same quantized mass that selected `action` above is
        # returned as the confidence numerator. Reading it from `quantized_mass` rather than
        # re-quantizing a second copy is what makes "the winner" and
        # "the numerator" one value by construction instead of two
        # values that happen to agree.

        return action, quantized_mass[action]


    def _availability_confidence(
        self,
        winning_mass,
        total,
        available_weight,
        total_configured_weight,
    ):

        # -------------------------------------------------
        # AVAILABILITY-ADJUSTED CONFIDENCE (M-2, supersedes Step 2C)
        # -------------------------------------------------
        #
        # Step 2C reported `bucket_share * weight_coverage`, where
        # bucket_share = winning_mass / total (total being the mass of
        # the *surviving* participants only). That is two independent
        # normalizations against two different populations, and the
        # first one is not availability-aware: `total` shrinks when a
        # participant disappears, so bucket_share rises. The coverage
        # factor does not always cancel that rise, because `total` is
        # not the participating weight - each participant contributes
        # only a fraction of its weight (score for BUY, 1-score for
        # SELL, 0.5 for HOLD). Whenever the surviving evidence is
        # weakly held (total / available_weight < 1 - f_removed),
        # removing a participant increased the reported confidence.
        # That is M-2: reproduced at this HEAD by grid search at up to
        # +0.133 (0.667 -> 0.800) for a single removal, and it is the
        # reason MIN_PARTICIPATING_AGENTS=3 had to stay an interlock
        # against a third evidence provider.
        #
        # The correction is a single normalization against the *whole*
        # configured roster. An absent participant is not dropped from
        # the denominator and is not fabricated into a bucket; it is
        # charged its full configured weight against whatever wins:
        #
        #     missing_weight = total_configured_weight - available_weight
        #     confidence     = winning_mass / (total + missing_weight)
        #
        # Two properties follow, and both are what M-2 required:
        #
        # 1. Monotonicity. Removing participant j removes c_j = f_j*w_j
        #    from `total` and adds w_j to missing_weight, so the
        #    denominator moves by w_j*(1 - f_j) >= 0 - it can never
        #    shrink. The numerator either loses c_j (j voted with the
        #    winner) or is unchanged, and if the winner changes the new
        #    winner's mass was already <= the old winner's. So the
        #    quotient is non-increasing under any removal, for every
        #    input. Removing evidence can no longer buy confidence.
        #
        # 2. Absence is the worst case, not the neutral case. Charging
        #    the full weight w_j means a missing participant is treated
        #    as maximally non-supporting: no real vote it could have
        #    cast is worse than its absence. Missing evidence therefore
        #    cannot improve the result, which is the invariant Step 2C
        #    was reaching for.
        #
        # Full-roster behaviour is preserved exactly: missing_weight is
        # 0, so confidence is the winning bucket share, which is what
        # `bucket_share * 1.0` already produced. Under unanimous
        # maximal conviction the value still degrades to the coverage
        # ratio (3/5 -> 0.80, 2/5 -> 0.60), so Step 2C's intended
        # availability ladder is unchanged; only the cases Step 2C got
        # wrong move, and they only ever move down.
        #
        # `scores` is deliberately left as-is: it stays the honest
        # bucket distribution among available evidence only, rounded
        # to 3 decimals for display and backward compatibility. It
        # carries no decision authority - `action` is selected from
        # `quantized_mass` above, which is the same MASS_PRECISION
        # authority the `winning_mass` numerator below reads. Keeping
        # presentation rounding out of the selection path is what
        # closes the M-2 display-rounding monotonicity defect.

        missing_weight = max(

            round(
                total_configured_weight - available_weight,
                self.MASS_PRECISION,
            ),

            0.0,

        )

        # proposals/2026-10-01_fusion_dissent_confidence_DESIGN.md (audit F-1):
        # with FULL_WEIGHT_DENOMINATOR every expected agent is charged its full
        # configured weight, so a dissenting or neutral vote counts exactly like
        # an abstention for the winner (never more), and agreeing evidence can
        # only add. NB-4 and NB-5 still hold: the denominator is the full roster.
        # Default False keeps today's decisions byte-identical until the owner
        # switches it on (after audit).
        denominator = (
            total_configured_weight
            if self.full_weight_denominator
            else total + missing_weight
        )

        return round(

            winning_mass
            / round(
                denominator,
                self.MASS_PRECISION,
            ),

            4,

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
    def _is_usable_score(
        value
    ):
        """
        True when `value` is a real number inside the contractual score
        range [0, 1]. Booleans are refused despite being ints: a boolean
        score is a caller mistake, not a 0/1 measurement. NaN is refused
        by the self-comparison, which no arithmetic check would catch.
        """

        if isinstance(
            value,
            bool,
        ) or not isinstance(
            value,
            (
                int,
                float,
            ),
        ):

            return False

        if value != value:

            return False

        return 0.0 <= value <= 1.0




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