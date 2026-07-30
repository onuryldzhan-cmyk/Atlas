from signals.base_signal import BaseSignal



class RiskSignal(BaseSignal):


    def __init__(self):

        super().__init__(
            "Risk Signal"
        )



    def generate(
        self,
        risk
    ):


        score = 50

        reasons = []



        level = risk.get(
            "level",
            "MEDIUM"
        )



        # Risk seviyesi değerlendirme

        if level == "LOW":

            score += 30

            reasons.append(
                "Düşük risk ortamı"
            )



        elif level == "MEDIUM":

            score += 0

            reasons.append(
                "Orta risk seviyesi"
            )



        elif level == "HIGH":

            score -= 30

            reasons.append(
                "Yüksek risk seviyesi"
            )



        score = max(
            0,
            min(
                score,
                100
            )
        )



        if score >= 70:

            signal = "SAFE"



        elif score >= 40:

            signal = "NORMAL"



        else:

            signal = "DANGER"



        return self.result(

            signal,

            score,

            ", ".join(
                reasons
            )

        )