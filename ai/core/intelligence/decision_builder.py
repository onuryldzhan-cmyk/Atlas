"""
Atlas AI Decision Builder v10.0

Final decision object creator.

Responsibilities:

- Convert intelligence result into Decision
- Attach risk information
- Create metadata
- Standardize output


"""


from __future__ import annotations


from datetime import datetime



from core.decision import (
    Decision,
    DecisionAction
)

import logging as _logging

# Diagnostics go to the log, not stdout (registry v5.50: 20 coins x every cycle flooded the console).
_log = _logging.getLogger(__name__)





class DecisionBuilder:



    VERSION = "10.0"





    def __init__(self):


        _log.debug(
            "[DECISION] Decision Builder v10.0 initialized"
        )






    # =====================================================
    # BUILD DECISION
    # =====================================================



    def create(
        self,
        symbol,
        fusion,
        risk,
        reasoning=None,
        memory=None,
        agents=None,
        unavailable_agents=None
    ):



        action = self.convert_action(

            fusion.action

        )





        decision = Decision(


            action=action,


            symbol=symbol,



            confidence=round(

                fusion.confidence * 100,

                2

            ),




            reasoning=(

                "Atlas v10 Intelligence Fusion"

            ),




            risk_level=(

                risk.level

            ),





            strategy=(

                "Atlas_v10_MultiAgent"

            ),






            metadata={



                "fusion":

                    fusion.scores,



                "fusion_reason":

                    self._safe_fusion_reason(
                        fusion
                    ),



                "unavailable_agents":

                    self._safe_unavailable_agents(
                        unavailable_agents
                    ),



                "risk":

                    risk.to_dict(),



                "reasoning":

                    reasoning,



                "memory":

                    memory,



                "agents":

                    agents,



                "timestamp":

                    datetime.now()
                    .isoformat()

            }


        )




        _log.debug(

            f"[DECISION] "
            f"{symbol} | "
            f"{decision.action.value} | "
            f"Confidence: "
            f"{decision.confidence}%"

        )



        return decision




    # =====================================================
    # DIAGNOSTIC METADATA HELPERS (audit-only, non-load-bearing)
    # =====================================================
    #
    # Persist AgentFusion's INSUFFICIENT_EVIDENCE/FUSED_EVIDENCE reason
    # and the excluded-agent diagnostics into Decision.metadata so the
    # audit trail can distinguish "no directional decision" from other
    # HOLD @ 0.0 causes without inferring it from confidence alone.
    # Never load-bearing: any malformed/missing input here degrades to
    # a safe default and never raises, so action/confidence/risk_level
    # construction can never depend on this data being present.


    @staticmethod
    def _safe_fusion_reason(
        fusion
    ):

        reason = getattr(
            fusion,
            "reason",
            None
        )

        if not isinstance(
            reason,
            str
        ):

            return "FUSED_EVIDENCE"

        return reason


    @staticmethod
    def _safe_unavailable_agents(
        unavailable_agents
    ):

        if not isinstance(
            unavailable_agents,
            dict
        ):

            return {}

        valid_names = [

            name
            for name, reason in unavailable_agents.items()

            if isinstance(
                name,
                str
            )
            and isinstance(
                reason,
                str
            )

        ]

        return {

            name: unavailable_agents[name]

            for name in sorted(
                valid_names
            )

        }




    # =====================================================
    # ACTION CONVERTER
    # =====================================================



    def convert_action(
        self,
        action
    ):



        action = action.upper()





        if action == "BUY":


            return DecisionAction.BUY




        if action == "SELL":


            return DecisionAction.SELL




        return DecisionAction.HOLD