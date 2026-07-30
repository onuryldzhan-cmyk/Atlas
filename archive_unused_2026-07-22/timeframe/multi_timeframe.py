class MultiTimeframeAnalyzer:


    def __init__(self):

        pass



    def analyze(
        self,
        data
    ):


        result = {

            "4h": "NEUTRAL",
            "1h": "NEUTRAL",
            "15m": "NEUTRAL",
            "5m": "NEUTRAL",

            "score": 0,

            "trend": "BELIRSIZ"

        }



        try:


            # 4 saatlik ana trend

            if data.get("4h"):

                close = data["4h"]["close"]
                ema = data["4h"]["ema"]


                if close > ema:

                    result["4h"] = "YUKSELIS"

                    result["score"] += 20


                else:

                    result["4h"] = "DUSUS"

                    result["score"] -= 20





            # 1 saatlik trend

            if data.get("1h"):

                close = data["1h"]["close"]
                ema = data["1h"]["ema"]


                if close > ema:

                    result["1h"] = "YUKSELIS"

                    result["score"] += 15


                else:

                    result["1h"] = "DUSUS"

                    result["score"] -= 15





            # 15 dakika giriş hazırlığı

            if data.get("15m"):

                close = data["15m"]["close"]
                ema = data["15m"]["ema"]


                if close > ema:

                    result["15m"] = "YUKSELIS"

                    result["score"] += 10


                else:

                    result["15m"] = "DUSUS"

                    result["score"] -= 10






            # 5 dakika scalping

            if data.get("5m"):

                close = data["5m"]["close"]
                ema = data["5m"]["ema"]


                if close > ema:

                    result["5m"] = "YUKSELIS"

                    result["score"] += 5


                else:

                    result["5m"] = "DUSUS"

                    result["score"] -= 5






            # Genel karar


            if result["score"] >= 25:

                result["trend"] = "GUCLU_YUKSELIS"



            elif result["score"] <= -25:

                result["trend"] = "GUCLU_DUSUS"



            else:

                result["trend"] = "KARARSIZ"




            return result




        except Exception as e:


            return {

                "error": str(e)

            }