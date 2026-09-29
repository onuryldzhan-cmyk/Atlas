"""
Atlas AI Confidence Engine v10.1

Professional confidence calculation layer.

Responsibilities:

- Measure intelligence agreement
- Penalize signal conflicts
- Combine agents + reasoning
- Calculate market conviction
- Separate confidence from action

Pipeline:

Agents
   |
   v
Agreement Analysis
   |
   v
Reasoning Influence
   |
   v
Risk Adjustment
   |
   v
Final Confidence


"""


from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Mapping

import logging as _logging

# Diagnostics go to the log, not stdout (registry v5.50: 20 coins x every cycle flooded the console).
_log = _logging.getLogger(__name__)



# =====================================================
# CONFIDENCE RESULT MODEL
# =====================================================


@dataclass
class ConfidenceResult:

    value: float

    agreement: float

    reasoning_effect: float

    risk_penalty: float

    explanation: str



    def percentage(self):

        return round(
            self.value * 100,
            2
        )





# =====================================================
# CONFIDENCE ENGINE
# =====================================================


class ConfidenceEngine:


    """
    Atlas Intelligence Confidence Engine v10.1

    Calculates confidence independently
    from decision making.

    """


    VERSION = "10.1"



    def __init__(self):


        _log.debug(
            "[CONFIDENCE] Confidence Engine v10.1 initialized"
        )




    # =================================================
    # MAIN CALCULATOR
    # =================================================


    def calculate(

        self,
        agents: Dict,
        reasoning: Dict,
        risk: Dict | None = None,
        expected_agent_count: int | None = None

    ) -> ConfidenceResult:



        agreement = self.calculate_agent_agreement(

            agents,

            expected_agent_count=expected_agent_count

        )



        reasoning_effect = self.calculate_reasoning_effect(

            reasoning

        )



        risk_penalty = self.calculate_risk_penalty(

            risk

        )



        confidence = (

            agreement * 0.50

            +

            reasoning_effect * 0.35

            -

            risk_penalty * 0.15

        )



        confidence = max(

            0,

            min(

                confidence,

                1

            )

        )




        explanation = (

            f"Agreement={agreement:.2f} "

            f"Reasoning={reasoning_effect:.2f} "

            f"RiskPenalty={risk_penalty:.2f}"

        )




        return ConfidenceResult(

            value=confidence,

            agreement=agreement,

            reasoning_effect=reasoning_effect,

            risk_penalty=risk_penalty,

            explanation=explanation

        )





    # =================================================
    # AGENT AGREEMENT
    # =================================================


    def calculate_agent_agreement(

        self,

        agents: Dict,

        expected_agent_count: int | None = None

    ):


        if not agents:


            return 0



        actions = []



        for data in agents.values():


            actions.append(

                data.get(

                    "action",

                    "HOLD"

                )

            )



        if not actions:


            return 0




        counts = {}



        for action in actions:


            counts[action] = (

                counts.get(

                    action,

                    0

                )

                + 1

            )



        strongest = max(

            counts.values()

        )



        # NB-4/NB-5: the denominator must reflect the expected/configured
        # agent roster, not merely the agents that survived to this call.
        # Missing evidence must never shrink the denominator below the
        # roster size - doing so lets evidence loss inflate agreement
        # (e.g. 2/2 surviving BUY votes reading as 1.0 when 3 other
        # configured agents are simply absent). `expected_agent_count`
        # is optional and additive: callers that omit it (or pass a
        # value no larger than the surviving count) keep the prior,
        # unscaled `strongest / len(actions)` behavior exactly - this
        # also guarantees the denominator can never be smaller than
        # `len(actions)` (which is already known >0 here), so no
        # division-by-zero is possible regardless of what is passed in.

        denominator = len(actions)

        if (

            expected_agent_count is not None

            and expected_agent_count > denominator

        ):

            denominator = expected_agent_count



        return strongest / denominator





    # =================================================
    # REASONING EFFECT
    # =================================================


    def calculate_reasoning_effect(

        self,

        reasoning: Dict

    ):



        confidence = reasoning.get(

            "confidence",

            0

        )



        confidence = float(

            confidence

        )



        if confidence > 1:


            confidence = confidence / 100



        return max(

            0,

            min(

                confidence,

                1

            )

        )






    # =================================================
    # RISK PENALTY
    # =================================================


    # -------------------------------------------------
    # RISK PENALTY TAXONOMY (M-3)
    # -------------------------------------------------
    #
    # LOW/MEDIUM/HIGH keep their existing values exactly. CRITICAL and
    # UNKNOWN are added, and they are the two states the previous
    # `penalties.get(level, 0.20)` silently resolved to the MEDIUM
    # penalty - i.e. a maximum-risk or uninterpretable classification
    # was scored as *less* dangerous than a HIGH one and produced a
    # higher confidence than the evidence justified. That is M-3.
    #
    # Both are pinned at the maximum penalty rather than at some value
    # merely above HIGH, because both are non-executable states in the
    # canonical execution authority (core.risk_engine rejects them with
    # CRITICAL_RISK_NOT_EXECUTABLE / UNSUPPORTED_RISK_LEVEL and zero
    # allocation). Nothing this advisory layer computes should read as
    # partial confidence in a state execution refuses outright, and a
    # penalty of 1.0 spends the whole risk term of the confidence
    # formula, which is the strongest statement available here.

    RISK_PENALTIES = {

        "LOW":
            0.05,

        "MEDIUM":
            0.20,

        "HIGH":
            0.40,

        "CRITICAL":
            1.00,

        "UNKNOWN":
            1.00,

    }


    # Applied when a risk classification is PRESENT but not understood
    # ("EXTREME", "SEVERE", a number, any future label). It fails closed
    # at the maximum rather than at MEDIUM: an unrecognized label is not
    # evidence of moderate risk, and treating it as such let unknown
    # input buy back confidence.

    UNSUPPORTED_RISK_PENALTY = 1.00


    # Applied when risk is genuinely ABSENT (no mapping, or no/empty
    # level inside it). This is the one legacy default deliberately
    # retained, matching the frozen Block-1 convention that a
    # missing/None/empty risk value keeps its MEDIUM default and is
    # never confused with malformed PRESENT input. It is no longer 0:
    # scoring "no risk information at all" as *zero* risk penalty made
    # absence the single most favourable input this method accepted,
    # which is the same missing-evidence-is-good-evidence failure M-2
    # removed from fusion.

    ABSENT_RISK_PENALTY = 0.20


    def calculate_risk_penalty(

        self,

        risk

    ):



        level = self._risk_level_token(

            risk

        )



        if level is None:


            return self.ABSENT_RISK_PENALTY



        return self.RISK_PENALTIES.get(

            level,

            self.UNSUPPORTED_RISK_PENALTY

        )




    @staticmethod
    def _risk_level_token(

        risk

    ):

        """
        Resolve a risk input to a canonical level token.

        Returns None for genuine absence (no risk mapping, no "level"
        entry, or an empty/None level) and an upper-cased token
        otherwise. A present but non-textual value is returned as text
        rather than as absence, so it fails closed as unsupported
        instead of inheriting the absence default.

        Case/whitespace normalization mirrors
        core.risk_engine.analytical_risk_level() on purpose: Atlas must
        not grow a second, differently-strict risk vocabulary in the
        advisory layer.
        """

        if not risk:

            return None


        if isinstance(
            risk,
            Mapping,
        ):

            value = risk.get(
                "level"
            )

        else:

            value = getattr(
                risk,
                "level",
                None,
            )


        if value is None:

            return None


        if isinstance(
            value,
            Enum,
        ):

            value = (
                value.value
                if isinstance(
                    value.value,
                    str,
                )
                else value.name
            )


        token = str(
            value
        ).strip().upper()


        return token or None





    # =================================================
    # DEBUG
    # =================================================


    def explain(

        self,

        result: ConfidenceResult

    ):



        return {


            "confidence":

                result.percentage(),


            "agreement":

                round(

                    result.agreement,

                    2

                ),


            "reasoning":

                round(

                    result.reasoning_effect,

                    2

                ),


            "risk_penalty":

                round(

                    result.risk_penalty,

                    2

                ),


            "explanation":

                result.explanation

        }