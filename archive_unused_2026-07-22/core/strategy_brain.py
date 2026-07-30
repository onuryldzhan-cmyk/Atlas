import pandas as pd

class StrategyBrain:
    """
    PROJECT ATLAS AI - Strategy Brain & Strateji Yarışması
    Birden fazla trading stratejisini aynı anda analiz eder, 
    puanlar ve en yüksek performansı gösteren stratejiyi belirler.
    """
    def __init__(self):
        pass

    def evaluate_all(self, df: pd.DataFrame, tech_data: dict) -> dict:
        """
        Tüm stratejileri analiz eder ve her biri için yön (AL/SAT/BEKLE) ve 
        strateji bazlı güven puanı üretir.
        """
        closes = df['close'].astype(float).tolist()
        
        strategies = {
            "Scalping": self._scalping_strategy(closes, tech_data),
            "Momentum": self._momentum_strategy(tech_data),
            "Trend_Following": self._trend_following_strategy(tech_data),
            "Mean_Reversion": self._mean_reversion_strategy(tech_data)
        }
        
        # En yüksek güven puanına sahip aktif stratejiyi seçelim
        best_strategy_name = "None"
        best_score = -1
        best_decision = "BEKLE"

        for name, result in strategies.items():
            if result["score"] > best_score and result["decision"] != "BEKLE":
                best_score = result["score"]
                best_strategy_name = name
                best_decision = result["decision"]

        # Eğer hiçbir strateji tetiklenmediyse varsayılan bekle değerlerini ata
        if best_strategy_name == "None":
            best_strategy_name = "Scalping"
            best_decision = "BEKLE"
            best_score = 0

        return {
            "best_strategy": best_strategy_name,
            "decision": best_decision,
            "score": best_score,
            "all_strategies": strategies
        }

    def _scalping_strategy(self, closes: list, tech_data: dict) -> dict:
        """Kısa vadeli RSI ve volatiliteye dayalı scalping stratejisi."""
        rsi = tech_data.get("rsi", 50)
        decision = "BEKLE"
        score = 0

        if rsi < 35:
            decision = "AL"
            score = 75 - rsi  # RSI ne kadar düşükse o kadar güçlü alım sinyali
        elif rsi > 65:
            decision = "SAT"
            score = rsi - 25

        return {"decision": decision, "score": max(0, round(score, 2))}

    def _momentum_strategy(self, tech_data: dict) -> dict:
        """MACD ve ADX göstergelerine dayalı momentum takip stratejisi."""
        macd = tech_data.get("macd", 0)
        macd_sig = tech_data.get("macd_signal", 0)
        adx = tech_data.get("adx", 20)
        
        decision = "BEKLE"
        score = 0

        # ADX > 25 ise güçlü trend, momentum takip edilebilir
        if adx > 25:
            if macd > macd_sig:
                decision = "AL"
                score = min(adx + 20, 100)
            elif macd < macd_sig:
                decision = "SAT"
                score = min(adx + 20, 100)

        return {"decision": decision, "score": round(score, 2)}

    def _trend_following_strategy(self, tech_data: dict) -> dict:
        """EMA20 ve EMA50 kesişimlerine odaklanan orta-uzun vadeli trend takip stratejisi."""
        trend = tech_data.get("trend", "NEUTRAL")
        decision = "BEKLE"
        score = 0

        if trend == "BULLISH":
            decision = "AL"
            score = 65
        elif trend == "BEARISH":
            decision = "SAT"
            score = 65

        return {"decision": decision, "score": score}

    def _mean_reversion_strategy(self, tech_data: dict) -> dict:
        """Bollinger bantlarından taşmaları ve ortalamaya geri dönüşleri hedefleyen strateji."""
        bollinger_w = tech_data.get("bollinger_w", 0)
        rsi = tech_data.get("rsi", 50)
        decision = "BEKLE"
        score = 0

        # Sıkışma sonrası patlamaları veya aşırı genişlemeleri yakalar
        if bollinger_w > 12.0:  # Aşırı geniş bantlar, ortalamaya geri dönme ihtimali yüksek
            if rsi > 70:
                decision = "SAT"
                score = 80
            elif rsi < 30:
                decision = "AL"
                score = 80

        return {"decision": decision, "score": score}