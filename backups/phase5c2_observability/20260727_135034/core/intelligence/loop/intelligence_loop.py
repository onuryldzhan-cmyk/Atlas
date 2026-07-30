from __future__ import annotations

import time
from datetime import datetime, UTC

from core.intelligence.atlas_brain_connector import AtlasBrainConnector
from intelligence.trading.paper_bridge import PaperBridge



class IntelligenceLoop:


    VERSION = "1.1"



    def __init__(self):

        self.brain = AtlasBrainConnector()

        self.paper = PaperBridge()

        self.running = False

        self.history = []



    def run_cycle(self):


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

        self.running = False