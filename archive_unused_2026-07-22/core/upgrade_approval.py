"""
Atlas Upgrade Approval v6.7

User controlled upgrade permission system
"""

import logging


logger = logging.getLogger("AtlasAI")



class UpgradeApproval:


    def __init__(
        self,
        brain
    ):

        self.brain = brain


        logger.info(
            "Atlas Upgrade Approval initialized."
        )



    # =====================================
    # SHOW REQUEST
    # =====================================

    def request(
        self
    ):


        report = (
            self.brain
            .upgrade_advisor
            .analyze()
        )


        upgrades = report.get(
            "upgrades",
            []
        )


        if not upgrades:

            return {
                "status":"NO_UPGRADE"
            }



        approved = []



        for upgrade in upgrades:


            print("\n==============================")

            print(
                "ATLAS UPGRADE REQUEST"
            )

            print("==============================")

            print(
                f"Module: {upgrade['module']}"
            )

            print(
                f"Problem: {upgrade['problem']}"
            )

            print(
                f"Priority: {upgrade['priority']}"
            )

            print(
                f"Expected Gain: {upgrade['expected']}"
            )


            answer = input(
                "Apply upgrade? (Y/N): "
            ).upper()



            if answer == "Y":

                approved.append(
                    upgrade
                )


        return {

            "status":"APPROVED",

            "upgrades":approved

        }