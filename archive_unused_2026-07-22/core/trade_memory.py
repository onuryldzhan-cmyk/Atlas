"""
Atlas AI Trade Memory v6.2
Decision + Outcome Memory System
"""

import json
import os
import logging


logger = logging.getLogger("AtlasAI")



class TradeMemory:


    def __init__(self):

        self.file = "trade_memory.json"

        self.memory = []

        self.load()



    # =====================================
    # LOAD
    # =====================================

    def load(self):

        if os.path.exists(
            self.file
        ):

            try:

                with open(
                    self.file,
                    "r"
                ) as f:

                    self.memory = json.load(f)


            except Exception:

                self.memory = []



    # =====================================
    # SAVE
    # =====================================

    def save(self):

        with open(
            self.file,
            "w"
        ) as f:

            json.dump(
                self.memory,
                f,
                indent=4
            )



    # =====================================
    # ANALYSIS RECORD
    # =====================================

    def record_analysis(
        self,
        symbol,
        decision,
        confidence,
        strategy
    ):


        data = {

            "type": "analysis",

            "symbol": symbol,

            "decision": decision,

            "confidence": confidence,

            "strategy": strategy

        }


        self.memory.append(
            data
        )


        self.save()



        logger.info(
            f"[MEMORY] Analysis stored: {symbol}"
        )



    # =====================================
    # EVENT DECISION RECORD
    # =====================================

    def record_decision(
        self,
        symbol,
        decision
    ):


        data = {

            "type": "decision",

            "symbol": symbol,

            "decision": decision

        }


        self.memory.append(
            data
        )


        self.save()


        logger.info(
            f"[MEMORY] Decision stored: {symbol}"
        )



    # =====================================
    # OUTCOME
    # =====================================

    def record_outcome(
        self,
        symbol,
        result
    ):


        data = {

            "type": "outcome",

            "symbol": symbol,

            "result": result

        }


        self.memory.append(
            data
        )


        self.save()


        logger.info(
            f"[MEMORY] Outcome stored: {symbol}"
        )



    # =====================================
    # LAST MEMORY
    # =====================================

    def get_recent(
        self,
        limit=10
    ):

        return self.memory[-limit:]