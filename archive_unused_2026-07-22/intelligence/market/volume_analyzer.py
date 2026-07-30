class VolumeAnalyzer:


    def __init__(self):

        self.name = "Volume Analyzer"



    def analyze(
        self,
        data
    ):


        current_volume = float(
            data["volume"].iloc[-1]
        )


        average_volume = float(
            data["volume"].mean()
        )



        volume_ratio = round(

            current_volume /
            average_volume,

            2

        )



        signal = "NORMAL"



        score = 50



        if volume_ratio >= 1.5:


            signal = "STRONG"

            score = 80



        elif volume_ratio >= 1.2:


            signal = "INCREASE"

            score = 65



        elif volume_ratio < 0.8:


            signal = "WEAK"

            score = 35



        return {


            "volume_ratio": volume_ratio,

            "signal": signal,

            "score": score


        }