"""
Atlas Upgrade Advisor v7.0

Converts research findings
into upgrade proposals.
"""


import logging


logger = logging.getLogger("AtlasAI")



class UpgradeAdvisor:


    def __init__(
    self,
    brain=None
):

        self.brain = brain


        logger.info(
            "Atlas Upgrade Advisor initialized."
        )



    # =====================================
    # CREATE UPGRADE PROPOSALS
    # =====================================

    def generate(
        self,
        analysis
    ):


        proposals = []


        for item in analysis.get(
            "suggestions",
            []
        ):


            proposal = {


                "module":

                item.get(
                    "module"
                ),


                "priority":

                item.get(
                    "priority",
                    "LOW"
                ),


                "reason":

                item.get(
                    "reason"
                ),


                "status":

                "WAITING_APPROVAL"


            }


            proposals.append(
                proposal
            )



        return {


            "project":

            analysis.get(
                "project"
            ),


            "proposals":

            proposals


        }