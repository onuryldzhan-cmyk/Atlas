"""
============================================================
ATLAS EXECUTION RISK GATE v1.0
============================================================

Execution safety layer

Responsibilities
----------------
- Validate trade confidence
- Validate risk level
- Prevent unsafe execution
- Provide rejection reasons

============================================================
"""

from __future__ import annotations

import logging


logger = logging.getLogger(
    "AtlasAI.ExecutionRiskGate"
)



class ExecutionRiskGate:


    VERSION = "1.0"



    def __init__(
        self,
        minimum_confidence: float = 60,
        max_positions: int = 5,
    ):


        self.minimum_confidence = (
            minimum_confidence
        )


        self.max_positions = (
            max_positions
        )


        self.rejected = 0


        logger.info(
            "Execution Risk Gate initialized"
        )



    def check(
        self,
        request,
    ):


        if request.confidence < self.minimum_confidence:

            self.rejected += 1

            return False



        if request.risk not in (
            "LOW",
            "MEDIUM",
            "HIGH"
        ):

            self.rejected += 1

            return False



        return True
    # =====================================================
    # DETAILED VALIDATION
    # =====================================================


    def validate(
        self,
        request,
    ) -> dict:


        result = {


            "allowed":

                True,


            "reason":

                "APPROVED",


            "checks":

                {},

        }



        # ---------------------------------
        # Confidence Check
        # ---------------------------------


        confidence_ok = (

            request.confidence

            >=

            self.minimum_confidence

        )


        result["checks"][

            "confidence"

        ] = confidence_ok



        if not confidence_ok:


            result["allowed"] = False


            result["reason"] = (

                "LOW_CONFIDENCE"

            )



        # ---------------------------------
        # Risk Level Check
        # ---------------------------------


        valid_risk = request.risk in (

            "LOW",

            "MEDIUM",

            "HIGH"

        )


        result["checks"][

            "risk_level"

        ] = valid_risk



        if not valid_risk:


            result["allowed"] = False


            result["reason"] = (

                "INVALID_RISK"

            )



        return result



    # =====================================================
    # SAFE CHECK WRAPPER
    # =====================================================


    def check_request(
        self,
        request,
    ) -> tuple[bool,str]:


        result = self.validate(
            request
        )


        if not result["allowed"]:


            self.rejected += 1


            return (

                False,

                result["reason"]

            )



        return (

            True,

            "APPROVED"

        )



    # =====================================================
    # STATISTICS
    # =====================================================


    def statistics(self):


        return {


            "version":

                self.VERSION,


            "minimum_confidence":

                self.minimum_confidence,


            "max_positions":

                self.max_positions,


            "rejected":

                self.rejected,


        }
    # =====================================================
    # HEALTH
    # =====================================================


    def health(self):


        return {


            "healthy":

                True,


            "component":

                "ExecutionRiskGate",


            "version":

                self.VERSION,


            "rejected":

                self.rejected,


        }



    # =====================================================
    # DIAGNOSTICS
    # =====================================================


    def diagnostics(self):


        return {


            "component":

                "ExecutionRiskGate",


            "version":

                self.VERSION,


            "configuration":{


                "minimum_confidence":

                    self.minimum_confidence,


                "max_positions":

                    self.max_positions,

            },


            "statistics":{


                "rejected":

                    self.rejected,

            },


        }



    # =====================================================
    # RESET
    # =====================================================


    def reset(self):


        self.rejected = 0


        logger.warning(

            "Execution Risk Gate reset"

        )



    # =====================================================
    # REPRESENTATION
    # =====================================================


    def __repr__(self):


        return (

            f"<ExecutionRiskGate "

            f"version={self.VERSION} "

            f"rejected={self.rejected}>"

        )



    def __str__(self):


        return (

            f"ExecutionRiskGate "

            f"v{self.VERSION}"

        )