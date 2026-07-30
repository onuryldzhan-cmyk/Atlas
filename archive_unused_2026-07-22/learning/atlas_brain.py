from learning.model_memory import ModelMemory
from learning.learning_engine import LearningEngine



class AtlasBrain:


    def __init__(self):

        self.memory = ModelMemory()

        self.learning = LearningEngine()



    def think(self):


        trades = self.memory.get_memory()

        learning_data = self.learning.status()


        total = len(trades)



        if total == 0:

            return {

                "message": "Henüz yeterli veri yok.",

                "confidence": 50,

                "trades": 0,

                "learning": learning_data

            }



        al_success = 0

        sat_success = 0



        al_total = learning_data["AL"]["total"]

        sat_total = learning_data["SAT"]["total"]



        if al_total > 0:

            al_success = (

                learning_data["AL"]["wins"]

                /

                al_total

            ) * 100



        if sat_total > 0:

            sat_success = (

                learning_data["SAT"]["wins"]

                /

                sat_total

            ) * 100




        if sat_success > al_success:


            message = "Öğrenmeye göre SAT daha güçlü."

            confidence = int(
                50 + (sat_success - al_success) / 2
            )



        elif al_success > sat_success:


            message = "Öğrenmeye göre AL daha güçlü."

            confidence = int(
                50 + (al_success - sat_success) / 2
            )



        else:


            message = "Piyasa dengeli."

            confidence = 50




        confidence = max(
            0,
            min(
                confidence,
                95
            )
        )



        return {


            "message": message,


            "confidence": confidence,


            "trades": total,


            "AL_success": round(
                al_success,
                2
            ),


            "SAT_success": round(
                sat_success,
                2
            ),


            "learning": learning_data

        }