"""
Atlas AI - Signal Processor Module
Sinyal isleme ve filtreleme - atlas_brain.py'den ayrildi
"""
import numpy as np
from typing import List, Dict
from dataclasses import dataclass

@dataclass
class Signal:
    source: str
    direction: int  # 1: BUY, -1: SELL, 0: HOLD
    strength: float  # 0.0 - 1.0
    timestamp: str
    metadata: Dict

class SignalProcessor:
    """Coklu sinyal kaynaklarini birlestir"""

    def __init__(self):
        self.signals = []
        self.weights = {
            "technical": 0.3,
            "sentiment": 0.2,
            "fundamental": 0.2,
            "ml_model": 0.3
        }

    def add_signal(self, signal: Signal):
        """Yeni sinyal ekle"""
        self.signals.append(signal)
        # Son 100 sinyali tut
        self.signals = self.signals[-100:]

    def process_signals(self) -> Dict:
        """Tum sinyalleri isle ve birlestir"""
        if not self.signals:
            return {"direction": 0, "strength": 0, "confidence": 0}

        # Agirlikli ortalama
        weighted_sum = 0
        total_weight = 0

        for signal in self.signals[-10:]:  # Son 10 sinyal
            weight = self.weights.get(signal.source, 0.1)
            weighted_sum += signal.direction * signal.strength * weight
            total_weight += weight

        if total_weight == 0:
            return {"direction": 0, "strength": 0, "confidence": 0}

        final_score = weighted_sum / total_weight

        return {
            "direction": 1 if final_score > 0.2 else -1 if final_score < -0.2 else 0,
            "strength": abs(final_score),
            "confidence": min(1.0, abs(final_score) * 2),
            "sources": list(set(s.source for s in self.signals[-10:]))
        }

    def get_signal_diversity(self) -> float:
        """Sinyal cesitliligi"""
        if not self.signals:
            return 0
        sources = set(s.source for s in self.signals)
        return len(sources) / len(self.weights)

