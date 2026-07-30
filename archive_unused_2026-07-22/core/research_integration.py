"""
Atlas Research Integration v7.0

Connects research findings
with improvement system.
"""


import logging


logger = logging.getLogger("AtlasAI")



class ResearchIntegration:


    def __init__(
        self,
        improvement_planner=None
    ):

        self.improvement_planner = improvement_planner


        self.queue = []


        logger.info(
            "Atlas Research Integration initialized."
        )



    def add_research_results(
        self,
        research_results
    ):


        for project in research_results:


            for proposal in project.get(
                "proposals",
                []
            ):


                item = {


                    "source":

                    project.get(
                        "project"
                    ),


                    "module":

                    proposal.get(
                        "module"
                    ),


                    "priority":

                    proposal.get(
                        "priority"
                    ),


                    "reason":

                    proposal.get(
                        "reason"
                    ),


                    "status":

                    "WAITING_APPROVAL"

                }


                self.queue.append(
                    item
                )



        return self.queue



    def get_queue(self):

        return self.queue