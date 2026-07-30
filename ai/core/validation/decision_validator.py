"""
Atlas AI Decision Validator v1.0

Validates intelligence decisions
before execution.

Brain decides.
Validator approves.
Executor acts.

"""


class DecisionValidator:


    VERSION = "1.0"



    def __init__(self):

        print(
            "[VALIDATOR] Decision Validator v1.0 initialized"
        )



    def validate(
        self,
        decision
    ):


        reasons = []



        # confidence check

        if decision.confidence < 60:

            reasons.append(
                "Low confidence"
            )



        # hold decisions

        if decision.is_hold():

            return {

                "approved": False,

                "reason":

                    "Decision is HOLD",

                "decision":

                    decision.to_dict()

            }




        # final result


        approved = (

            len(reasons)==0

        )



        return {


            "approved":

                approved,


            "reasons":

                reasons,


            "decision":

                decision.to_dict()

        }