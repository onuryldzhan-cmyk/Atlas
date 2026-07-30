from __future__ import annotations

import logging

import time
from datetime import datetime, UTC

from core.intelligence.atlas_brain_connector import AtlasBrainConnector
from intelligence.trading.paper_bridge import PaperBridge


logger = logging.getLogger("AtlasAI.IntelligenceLoop")



class IntelligenceLoop:


    VERSION = "1.1"



    def __init__(self):


        logger.debug("IntelligenceLoop initialization started.")
        self.brain = AtlasBrainConnector()

        self.paper = PaperBridge()

        self.running = False

        self.history = []



    def run_cycle(self):



        logger.debug("Intelligence cycle started.")
        result = self.brain.analyze_cycle()



        decision = result["decision"]["decision"]



        if decision == "BUY":


            order = result["order"]


            trade = self.paper.open_trade(

                symbol=order["symbol"],

                size=order["size"],

                strategy=order["strategy"]

            )


            result["paper_trade"] = trade



        record = {


            "time":

                datetime.now(UTC).isoformat(),


            "result":

                result

        }



        self.history.append(record)


        return record



    def start(

        self,

        cycles=5,

        delay=5

    ):



        logger.info("IntelligenceLoop start requested.")
        self.running = True


        results = []



        for _ in range(cycles):


            if not self.running:

                break



            results.append(

                self.run_cycle()

            )


            time.sleep(delay)



        return results



    def stop(self):


        logger.info("IntelligenceLoop stop requested.")
        self.running = False