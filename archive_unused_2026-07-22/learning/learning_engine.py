"""
Atlas AI Learning Engine v4
Adaptive Trading Memory System
"""

import json
import os
import datetime



class LearningEngine:


    def __init__(self):

        self.file = "atlas_learning_memory.json"


        self.data = {

            "total_trades": 0,

            "wins": 0,

            "losses": 0,

            "total_profit": 0,

            "strategies": {},

            "signals": {

                "BUY": {

                    "total": 0,

                    "wins": 0,

                    "profit": 0

                },

                "SELL": {

                    "total": 0,

                    "wins": 0,

                    "profit": 0

                }

            },

            "last_update": None

        }


        self.load()



    def load(self):

        if os.path.exists(self.file):

            try:

                with open(
                    self.file,
                    "r",
                    encoding="utf-8"
                ) as f:

                    self.data = json.load(f)


            except Exception:

                pass





    def save(self):

        self.data["last_update"] = (

            datetime.datetime.now()
            .isoformat()

        )


        with open(
            self.file,
            "w",
            encoding="utf-8"
        ) as f:


            json.dump(

                self.data,

                f,

                indent=4,

                ensure_ascii=False

            )





    def update_trade(

        self,

        signal,

        profit,

        strategy="Trend-Follow"

    ):


        self.data["total_trades"] += 1


        self.data["total_profit"] += profit



        if profit > 0:

            self.data["wins"] += 1

        else:

            self.data["losses"] += 1




        if signal not in self.data["signals"]:


            self.data["signals"][signal] = {

                "total":0,

                "wins":0,

                "profit":0

            }




        self.data["signals"][signal]["total"] += 1


        self.data["signals"][signal]["profit"] += profit



        if profit > 0:

            self.data["signals"][signal]["wins"] += 1




        if strategy not in self.data["strategies"]:


            self.data["strategies"][strategy] = {

                "trades":0,

                "wins":0,

                "profit":0

            }




        self.data["strategies"][strategy]["trades"] += 1


        self.data["strategies"][strategy]["profit"] += profit



        if profit > 0:

            self.data["strategies"][strategy]["wins"] += 1




        self.save()





    def get_learning_score(self):


        total = self.data["total_trades"]


        if total == 0:

            return {

                "score":50,

                "message":
                    "Henüz yeterli işlem verisi yok."

            }




        win_rate = (

            self.data["wins"]

            /

            total

        ) * 100



        score = int(win_rate)




        return {


            "score":
                score,


            "win_rate":
                round(win_rate,2),


            "total_trades":
                total,


            "profit":
                round(
                    self.data["total_profit"],
                    2
                ),


            "message":
                self.learning_message(score)

        }





    def learning_message(
        self,
        score
    ):


        if score >= 70:

            return (
                "Atlas mevcut stratejilerin "
                "başarılı olduğunu düşünüyor."
            )


        elif score >= 50:

            return (
                "Atlas daha fazla veri "
                "toplamaya devam ediyor."
            )


        else:

            return (
                "Atlas stratejileri "
                "yeniden değerlendirmeli."
            )





    def get_brain(self):


        return {

            "learning":
                self.data,


            "analysis":
                self.get_learning_score()

        }