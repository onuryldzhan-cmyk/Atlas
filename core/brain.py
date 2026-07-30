"""
Atlas Executive Brain v9.0

Central intelligence decision layer.

Responsibilities
-----------------

- Receive market observations
- Run intelligence analysis
- Produce trading decisions
- Maintain brain state
- Provide status information


Architecture

MarketLoop
    |
    v
AtlasBrain
    |
    +-- Intelligence Brain
    |
    +-- Decision Adapter
    |
    v
Decision
    |
    v
ExecutionManager


"""



from datetime import datetime, timezone
import logging



from core.decision_adapter import DecisionAdapter



logger = logging.getLogger(
    "AtlasAI.Brain"
)





class BrainState:


    def __init__(self):

        self.last_input = None

        self.last_analysis = None

        self.last_decision = None


        self.total_cycles = 0

        self.total_errors = 0


        self.started_at = datetime.now(
            timezone.utc
        )






class AtlasBrain:



    VERSION = "9.0"




    def __init__(
        self,
        event_bus=None
    ):


        self.event_bus = event_bus


        self.state = BrainState()



        self.intelligence = None


        self.running = True



        self.load_intelligence()



        logger.info(
            "Atlas Executive Brain v9.0 initialized"
        )






    # ==================================================
    # LOAD INTELLIGENCE
    # ==================================================


    def load_intelligence(self):


        try:


            from ai.core.atlas_brain import AtlasBrain as IntelligenceBrain



            self.intelligence = IntelligenceBrain()



            logger.info(
                "Intelligence Brain connected"
            )



        except Exception as e:


            logger.exception(
                e
            )


            self.intelligence = None






    # ==================================================
    # OBSERVE
    # ==================================================


    def observe(
        self,
        data
    ):


        self.state.last_input = data


        self.state.total_cycles += 1



        return data






    # ==================================================
    # ANALYZE
    # ==================================================


    def analyze(
        self,
        observation
    ):


        if not self.intelligence:


            return {

                "status":
                "OFFLINE"

            }




        try:


            symbol = observation.get(
                "symbol",
                "UNKNOWN"
            )



            result = self.intelligence.analyze_and_decide(

                symbol,

                observation

            )



            analysis = {


                "status":
                "SUCCESS",


                "symbol":
                symbol,


                "result":
                result

            }




            self.state.last_analysis = analysis



            return analysis




        except Exception as e:


            self.state.total_errors += 1


            logger.exception(
                e
            )



            return {


                "status":
                "ERROR",


                "error":
                str(e)

            }







    # ==================================================
    # DECISION
    # ==================================================


    def decide(
        self,
        analysis
    ):


        try:


            if analysis.get(
                "status"
            ) != "SUCCESS":


                return None




            decision = DecisionAdapter.convert(

                analysis["result"]

            )



            self.state.last_decision = decision



            return decision




        except Exception as e:


            self.state.total_errors += 1


            logger.exception(
                e
            )


            return None







    # ==================================================
    # MAIN ENTRY
    # ==================================================


    def process(
        self,
        data
    ):


        try:


            observation = self.observe(
                data
            )



            analysis = self.analyze(

                observation

            )



            decision = self.decide(

                analysis

            )




            return {


                "symbol":

                data.get(
                    "symbol"
                ),



                "decision":

                decision.to_dict()

                if decision and hasattr(
                    decision,
                    "to_dict"
                )

                else decision,



                "analysis":

                analysis,



                "time":

                datetime.now(
                    timezone.utc
                ).isoformat()


            }




        except Exception as e:


            self.state.total_errors += 1


            logger.exception(
                e
            )



            return {


                "status":
                "ERROR",


                "error":
                str(e)

            }







    # ==================================================
    # MARKET LOOP COMPATIBILITY
    # ==================================================


    def analyze_and_decide(
        self,
        symbol,
        market_data
    ):


        payload = {


            "symbol":
            symbol,


            **market_data

        }



        result = self.process(
            payload
        )



        return result.get(
            "decision"
        )






    # ==================================================
    # STATUS
    # ==================================================


    def status(self):


        return {


            "version":
            self.VERSION,


            "running":
            self.running,


            "cycles":
            self.state.total_cycles,


            "errors":
            self.state.total_errors,


            "intelligence":

            self.intelligence is not None


        }






    # ==================================================
    # SHUTDOWN
    # ==================================================


    def shutdown(self):


        self.running = False


        logger.info(
            "Atlas Brain stopped"
        )