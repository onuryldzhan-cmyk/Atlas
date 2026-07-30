class DecisionEngine:

    def __init__(self):
        pass

    def decide(self, signal, brain_data, analysis, multi):
        score = 50
        reasons = []

        score, reasons = self._evaluate_signal(signal, score, reasons)
        score, reasons = self._evaluate_trend(signal, analysis, score, reasons)
        score, reasons = self._evaluate_rsi(signal, analysis, score, reasons)
        score, reasons = self._evaluate_multi_timeframe(multi, score, reasons)
        score, reasons = self._evaluate_learning(signal, brain_data, score, reasons)

        return self._build_result(score, reasons)

    def _evaluate_signal(self, signal, score, reasons):
        if signal in ["AL", "SAT"]:
            score += 20
            reasons.append("Strateji gecerli sinyal uretti")
        return score, reasons

    def _evaluate_trend(self, signal, analysis, score, reasons):
        trend = analysis.get("trend")

        if signal == "AL":
            if trend == "YUKSELIS":
                score += 10
                reasons.append("Yukselis trendi AL destekliyor")
            else:
                score -= 10
                reasons.append("Trend AL sinyalini desteklemiyor")

        elif signal == "SAT":
            if trend == "DUSUS":
                score += 10
                reasons.append("Dusus trendi SAT destekliyor")
            else:
                score -= 10
                reasons.append("Trend SAT sinyalini desteklemiyor")

        return score, reasons

    def _evaluate_rsi(self, signal, analysis, score, reasons):
        rsi = analysis.get("rsi", 50)

        if signal == "AL" and rsi < 60:
            score += 5
            reasons.append("RSI AL icin uygun bolgede")

        if signal == "SAT" and rsi > 40:
            score += 5
            reasons.append("RSI SAT icin uygun bolgede")

        return score, reasons

    def _evaluate_multi_timeframe(self, multi, score, reasons):
        multi_score = multi.get("score", 0)

        if multi_score >= 25:
            score += 20
            reasons.append("Multi Timeframe cok guclu")
        elif multi_score >= 10:
            score += 10
            reasons.append("Multi Timeframe guclu")
        elif multi_score > 0:
            score += 5
            reasons.append("Multi Timeframe destekliyor")
        elif multi_score <= -25:
            score -= 20
            reasons.append("Multi Timeframe cok zayif")
        elif multi_score < 0:
            score -= 10
            reasons.append("Multi Timeframe zayif")

        return score, reasons

    def _evaluate_learning(self, signal, brain_data, score, reasons):
        if brain_data:
            learning = brain_data.get("learning", {})
            best = learning.get("best_signal")

            if best == signal:
                score += 10
                reasons.append("Ogrenme sistemi bu sinyali destekliyor")

        return score, reasons

    def _build_result(self, score, reasons):
        confidence = max(0, min(score, 100))

        mode = "NORMAL"
        if confidence >= 90:
            mode = "AGGRESSIVE"
        elif confidence >= 75:
            mode = "SCALP"

        decision = "ONAY" if confidence >= 75 else "RED"

        return {
            "decision": decision,
            "score": score,
            "confidence": confidence,
            "mode": mode,
            "reason": reasons
        }

