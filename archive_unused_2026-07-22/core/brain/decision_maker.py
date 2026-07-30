"""
Atlas AI - Decision Maker Module
Karar alma motoru - atlas_brain.py'den ayrildi
"""
import json
from datetime import datetime
from pathlib import Path

class DecisionMaker:
    """AI kararlarini olusturan modul"""

    def __init__(self, config_path="config/settings.py"):
        self.config_path = config_path
        self.decision_history = []
        self.confidence_threshold = 0.6

    def evaluate_signal(self, signal_data: dict) -> dict:
        """Sinyal degerlendir"""
        score = 0
        reasons = []

        # Teknik gosterge skorlari
        if signal_data.get("rsi", 50) < 30:
            score += 2
            reasons.append("RSI asiri satim")
        elif signal_data.get("rsi", 50) > 70:
            score -= 2
            reasons.append("RSI asiri alim")

        if signal_data.get("macd_bullish", False):
            score += 1
            reasons.append("MACD yukari kesisim")

        if signal_data.get("bb_position", 0) < -0.8:
            score += 2
            reasons.append("BB alt bandinda")

        # Trend kontrolu
        if signal_data.get("trend", "neutral") == "up":
            score += 1
        elif signal_data.get("trend", "neutral") == "down":
            score -= 1

        confidence = min(1.0, max(0.0, 0.5 + score * 0.1))

        decision = {
            "action": "BUY" if score >= 2 else "SELL" if score <= -2 else "HOLD",
            "confidence": confidence,
            "score": score,
            "reasons": reasons,
            "timestamp": datetime.now().isoformat()
        }

        self.decision_history.append(decision)
        return decision

    def get_decision_stats(self) -> dict:
        """Karar istatistikleri"""
        if not self.decision_history:
            return {}

        buys = sum(1 for d in self.decision_history if d["action"] == "BUY")
        sells = sum(1 for d in self.decision_history if d["action"] == "SELL")
        holds = sum(1 for d in self.decision_history if d["action"] == "HOLD")

        return {
            "total_decisions": len(self.decision_history),
            "buys": buys,
            "sells": sells,
            "holds": holds,
            "avg_confidence": sum(d["confidence"] for d in self.decision_history) / len(self.decision_history)
        }

