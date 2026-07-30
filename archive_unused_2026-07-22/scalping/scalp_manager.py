class ScalpManager:


    def __init__(self):

        self.mode = "SCALP"



    def calculate_targets(self, entry, signal):


        if signal == "AL":


            stop_loss = entry * 0.996

            tp1 = entry * 1.003

            tp2 = entry * 1.007



        elif signal == "SAT":


            stop_loss = entry * 1.004

            tp1 = entry * 0.997

            tp2 = entry * 0.993


        else:


            return None



        return {


            "mode": self.mode,

            "entry": round(entry,6),

            "stop_loss": round(stop_loss,6),

            "take_profit_1": round(tp1,6),

            "take_profit_2": round(tp2,6)

        }



    def should_trade(self, confidence):


        if confidence >= 65:

            return True


        return False