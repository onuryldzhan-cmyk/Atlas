"""
Atlas Version Memory v6.6

Self Improvement History System

Tracks:
- Upgrade history
- Version changes
- Performance comparison
- Success / Failure memory
"""


import json
import os
import logging
from datetime import datetime


logger = logging.getLogger("AtlasAI")



class VersionMemory:


    def __init__(self):

        self.file = "atlas_version_history.json"


        self.history = []


        self.load()


        logger.info(
            "Atlas Version Memory initialized."
        )



    # =====================================
    # LOAD HISTORY
    # =====================================

    def load(
        self
    ):


        if os.path.exists(
            self.file
        ):


            try:

                with open(
                    self.file,
                    "r",
                    encoding="utf-8"
                ) as f:


                    self.history = json.load(
                        f
                    )


            except Exception as e:


                logger.error(
                    f"Version memory load error: {e}"
                )


                self.history = []



    # =====================================
    # SAVE HISTORY
    # =====================================

    def save(
        self
    ):


        with open(
            self.file,
            "w",
            encoding="utf-8"
        ) as f:


            json.dump(
                self.history,
                f,
                indent=4,
                ensure_ascii=False
            )



    # =====================================
    # ADD UPGRADE RECORD
    # =====================================

    def add_upgrade(
        self,
        version_before,
        version_after,
        module,
        change,
        reason,
        before_result=None
    ):


        record = {


            "date":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),


            "version_before":
            version_before,


            "version_after":
            version_after,


            "module":
            module,


            "change":
            change,


            "reason":
            reason,


            "before":
            before_result,


            "after":
            None,


            "status":
            "TESTING"


        }



        self.history.append(
            record
        )


        self.save()



        logger.info(
            f"[VERSION] Upgrade saved {version_after}"
        )



        return record



    # =====================================
    # COMPLETE UPGRADE RESULT
    # =====================================

    def complete_upgrade(
        self,
        index,
        after_result,
        success
    ):


        if index >= len(
            self.history
        ):

            return False



        item = self.history[index]


        item["after"] = after_result



        if success:

            item["status"] = "SUCCESS"


        else:

            item["status"] = "FAILED"



        self.save()


        return True



    # =====================================
    # LAST VERSION
    # =====================================

    def last_upgrade(
        self
    ):


        if not self.history:

            return None



        return self.history[-1]



    # =====================================
    # STATISTICS
    # =====================================

    def statistics(
        self
    ):


        total = len(
            self.history
        )


        success = len(

            [
                x for x in self.history

                if x.get("status")
                ==
                "SUCCESS"
            ]

        )


        return {


            "total_upgrades":
            total,


            "successful":
            success,


            "failed":
            total - success


        }