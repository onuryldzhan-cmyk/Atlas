class TradeQualityFilter:


    def __init__(self):
        pass



    def evaluate(
        self,
        analysis,
        multi,
        decision
    ):


        score = 50

        reasons = []



        # AI güven puanı

        confidence = decision.get(
            "confidence",
            0
        )


        if confidence >= 80:

            score += 15

            reasons.append(
                "AI güven seviyesi yüksek"
            )


        elif confidence < 70:

            score -= 15

            reasons.append(
                "AI güven seviyesi düşük"
            )



        # Multi timeframe kontrolü

        trend = multi.get(
            "trend"
        )


        multi_score = multi.get(
            "score",
            0
        )



        if trend == "YUKSELIS":

            score += 15

            reasons.append(
                "Multi timeframe yükselişi destekliyor"
            )


        elif trend == "DUSUS":

            score -= 15

            reasons.append(
                "Multi timeframe düşüş gösteriyor"
            )


        else:

            score -= 5

            reasons.append(
                "Multi timeframe kararsız"
            )



        # Teknik analiz

        technical = analysis.get(
            "technical_score",
            50
        )


        if technical >= 70:

            score += 10

            reasons.append(
                "Teknik analiz güçlü"
            )


        elif technical < 50:

            score -= 10

            reasons.append(
                "Teknik analiz zayıf"
            )



        # Son karar


        if score >= 70:

            status = "QUALITY_OK"

        else:

            status = "QUALITY_LOW"



        return {

            "status": status,

            "quality_score": score,

            "reasons": reasons

        }