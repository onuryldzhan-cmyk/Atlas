from intelligence.core.intelligence_core import IntelligenceCore


class AtlasBrainConnector:


    VERSION = "1.0"



    def __init__(self):

        self.intelligence = IntelligenceCore()



    def analyze_cycle(self):


        result = self.intelligence.run()


        return {

            "decision":
                result["decision"],

            "risk":
                result["risk"],

            "order":
                result["order"]

        }