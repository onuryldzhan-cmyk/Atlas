"""
Atlas AI - Pattern Memory Engine (Aşama 4)
Kazanan ve kaybeden islemleri analiz ederek ogrenen AI modulu

Ozellikler:
- Islem gecmisini analiz et (win/loss patternleri)
- Basarili sinyal kosullarini ogren
- Basarisiz sinyal kosullarini tespit et
- Piyasa durumuna gore strateji secimi oner
- Guven skoru uret (ne kadar emin olmali)
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, Counter
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class PatternMemory:
    """Islem patternlerini ogren ve hatirla"""

    def __init__(self, memory_file: str = "data/pattern_memory.json"):
        self.memory_file = PROJECT_ROOT / memory_file
        self.patterns = {
            "winning": [],      # Kazanan islem kosullari
            "losing": [],       # Kaybeden islem kosullari
            "market_context": {},  # Piyasa durumuna gore basari orani
            "signal_stats": {},    # Her sinyal tipinin istatistigi
            "time_patterns": {},   # Zamana gore basari (saat, gun)
        }
        self.confidence_threshold = 0.6
        self._load_memory()

    def _load_memory(self):
        """Onceki ogrenmeleri yukle"""
        if self.memory_file.exists():
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.patterns.update(loaded)
                print(f"[MEMORY] {len(self.patterns['winning'])} kazanani, {len(self.patterns['losing'])} kaybedeni hatirliyorum")
            except:
                pass

    def _save_memory(self):
        """Ogrenmeleri kaydet"""
        os.makedirs(self.memory_file.parent, exist_ok=True)
        with open(self.memory_file, 'w', encoding='utf-8') as f:
            json.dump(self.patterns, f, indent=2, ensure_ascii=False, default=str)

    def analyze_trade(self, trade_data: Dict) -> Dict:
        """
        Tek bir islemi analiz et ve pattern cikar

        trade_data ornegi:
        {
            "entry_price": 65000,
            "exit_price": 67000,
            "pnl": 2000,
            "pnl_pct": 3.08,
            "side": "LONG",
            "entry_time": "2026-07-01T10:00:00",
            "exit_time": "2026-07-01T14:00:00",
            "exit_reason": "TAKE_PROFIT",
            "signal_reason": "RSI asiri satim + BB alt bandi",
            "market_context": {
                "trend": "up",
                "volatility": 0.015,
                "volume_ratio": 1.5,
                "rsi": 28,
                "bb_position": -0.9
            }
        }
        """
        result = {"learned": False, "pattern_type": None}

        if trade_data.get("pnl", 0) > 0:
            # Kazanan islem - ogren
            self.patterns["winning"].append({
                "timestamp": trade_data.get("entry_time"),
                "signal": trade_data.get("signal_reason", ""),
                "context": trade_data.get("market_context", {}),
                "pnl_pct": trade_data.get("pnl_pct", 0),
                "hold_time_hours": self._calculate_hold_time(trade_data)
            })
            result["learned"] = True
            result["pattern_type"] = "WIN"
        else:
            # Kaybeden islem - ogren (ne yapmamali)
            self.patterns["losing"].append({
                "timestamp": trade_data.get("entry_time"),
                "signal": trade_data.get("signal_reason", ""),
                "context": trade_data.get("market_context", {}),
                "pnl_pct": trade_data.get("pnl_pct", 0),
                "exit_reason": trade_data.get("exit_reason", "UNKNOWN")
            })
            result["learned"] = True
            result["pattern_type"] = "LOSS"

        # Zaman patterni ogren
        self._learn_time_pattern(trade_data)

        return result

    def _calculate_hold_time(self, trade: Dict) -> float:
        """Islem tutma suresini hesapla (saat)"""
        try:
            entry = datetime.fromisoformat(trade["entry_time"].replace('Z', '+00:00'))
            exit_t = datetime.fromisoformat(trade["exit_time"].replace('Z', '+00:00'))
            return (exit_t - entry).total_seconds() / 3600
        except:
            return 0

    def _learn_time_pattern(self, trade: Dict):
        """Zamana gore basari ogren"""
        try:
            dt = datetime.fromisoformat(trade["entry_time"].replace('Z', '+00:00'))
            hour = dt.hour
            day_of_week = dt.strftime("%A")

            is_win = trade.get("pnl", 0) > 0

            # Saat bazli
            if hour not in self.patterns["time_patterns"]:
                self.patterns["time_patterns"][hour] = {"wins": 0, "losses": 0}
            if is_win:
                self.patterns["time_patterns"][hour]["wins"] += 1
            else:
                self.patterns["time_patterns"][hour]["losses"] += 1

            # Gun bazli
            if day_of_week not in self.patterns["time_patterns"]:
                self.patterns["time_patterns"][day_of_week] = {"wins": 0, "losses": 0}
            if is_win:
                self.patterns["time_patterns"][day_of_week]["wins"] += 1
            else:
                self.patterns["time_patterns"][day_of_week]["losses"] += 1

        except:
            pass

    def analyze_all_trades(self, trades: List[Dict]) -> Dict:
        """Tum islem gecmisini analiz et"""
        print(f"[ANALYSIS] {len(trades)} islem analiz ediliyor...")

        for trade in trades:
            self.analyze_trade(trade)

        # Istatistikler
        stats = self._generate_stats()

        # Kaydet
        self._save_memory()

        return stats

    def _generate_stats(self) -> Dict:
        """Pattern istatistikleri uret"""
        wins = self.patterns["winning"]
        losses = self.patterns["losing"]

        total = len(wins) + len(losses)
        if total == 0:
            return {"error": "Henuz islem yok"}

        win_rate = len(wins) / total * 100

        # Kazanan sinyalleri say
        win_signals = Counter([w["signal"] for w in wins])
        loss_signals = Counter([l["signal"] for l in losses])

        # En basarili sinyaller
        best_signals = []
        for signal, count in win_signals.most_common(5):
            loss_count = loss_signals.get(signal, 0)
            total_count = count + loss_count
            if total_count >= 3:  # En az 3 islem olmali
                success_rate = count / total_count * 100
                best_signals.append({
                    "signal": signal,
                    "wins": count,
                    "losses": loss_count,
                    "success_rate": round(success_rate, 1)
                })

        # En basarisiz sinyaller
        worst_signals = []
        for signal, count in loss_signals.most_common(5):
            win_count = win_signals.get(signal, 0)
            total_count = count + win_count
            if total_count >= 3:
                success_rate = win_count / total_count * 100
                worst_signals.append({
                    "signal": signal,
                    "wins": win_count,
                    "losses": count,
                    "success_rate": round(success_rate, 1)
                })

        # En iyi zamanlar
        best_hours = []
        for hour, data in self.patterns["time_patterns"].items():
            if isinstance(hour, int) and data["wins"] + data["losses"] >= 2:
                rate = data["wins"] / (data["wins"] + data["losses"]) * 100
                best_hours.append({"hour": hour, "success_rate": round(rate, 1), "trades": data["wins"] + data["losses"]})
        best_hours.sort(key=lambda x: x["success_rate"], reverse=True)

        return {
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate, 1),
            "best_signals": best_signals,
            "worst_signals": worst_signals,
            "best_hours": best_hours[:5],
            "avg_win_pnl": round(np.mean([w["pnl_pct"] for w in wins]), 2) if wins else 0,
            "avg_loss_pnl": round(np.mean([l["pnl_pct"] for l in losses]), 2) if losses else 0,
        }

    def should_take_signal(self, signal_data: Dict, market_context: Dict) -> Tuple[bool, float, str]:
        """
        Bu sinyal alinmali mi? Guven skoru uret

        Returns: (should_trade, confidence_score, reason)
        """
        signal_reason = signal_data.get("reason", "")

        # Onceki benzer sinyalleri bul
        similar_wins = [w for w in self.patterns["winning"] if signal_reason in w["signal"]]
        similar_losses = [l for l in self.patterns["losing"] if signal_reason in l["signal"]]

        total_similar = len(similar_wins) + len(similar_losses)

        if total_similar < 2:
            # Yeterli veri yok - orta guven
            return True, 0.5, "Yeterli gecmis veri yok"

        success_rate = len(similar_wins) / total_similar

        if success_rate >= 0.7:
            return True, success_rate, f"Bu sinyal gecmiste %{success_rate*100:.0f} basarili"
        elif success_rate <= 0.3:
            return False, 1 - success_rate, f"Bu sinyal gecmiste %{(1-success_rate)*100:.0f} basarisiz"
        else:
            return True, 0.5, f"Belirsiz basari orani: %{success_rate*100:.0f}"

    def get_report(self) -> str:
        """Detayli rapor uret"""
        stats = self._generate_stats()

        report = []
        report.append("="*60)
        report.append("ATLAS AI - PATTERN MEMORY RAPORU")
        report.append("="*60)
        report.append(f"Toplam Islem: {stats.get('total_trades', 0)}")
        report.append(f"Win Rate: {stats.get('win_rate', 0)}%")
        report.append(f"Ort. Kazanc: {stats.get('avg_win_pnl', 0)}%")
        report.append(f"Ort. Kayip: {stats.get('avg_loss_pnl', 0)}%")
        report.append("")

        if stats.get("best_signals"):
            report.append("[EN BASARILI SINYALLER]")
            for s in stats["best_signals"][:3]:
                report.append(f"  {s['signal'][:40]:40s} | Basari: {s['success_rate']}% | {s['wins']}W/{s['losses']}L")

        if stats.get("worst_signals"):
            report.append("")
            report.append("[EN BASARISIZ SINYALLER - KACIN!]")
            for s in stats["worst_signals"][:3]:
                report.append(f"  {s['signal'][:40]:40s} | Basari: {s['success_rate']}% | {s['wins']}W/{s['losses']}L")

        if stats.get("best_hours"):
            report.append("")
            report.append("[EN IYI ISLEM SAATLERI]")
            for h in stats["best_hours"][:3]:
                report.append(f"  Saat {h['hour']:02d}:00 | Basari: {h['success_rate']}% | {h['trades']} islem")

        report.append("="*60)
        return "\n".join(report)


def load_paper_trading_results() -> List[Dict]:
    """Paper trading sonuclarini yukle"""
    result_files = [
        PROJECT_ROOT / "data" / "paper_trading_results.json",
        PROJECT_ROOT / "data" / "paper_trading_v2_results.json",
    ]

    for f in result_files:
        if f.exists():
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                    trades = data.get("closed_trades", [])
                    if trades:
                        print(f"[DATA] {f.name} dosyasindan {len(trades)} islem yuklendi")
                        return trades
            except:
                pass

    print("[WARNING] Paper trading sonucu bulunamadi!")
    return []


def main():
    print("="*60)
    print("ATLAS AI - PATTERN MEMORY ENGINE (Asama 4)")
    print("="*60)

    # Pattern Memory olustur
    memory = PatternMemory()

    # Paper trading sonuclarini yukle
    trades = load_paper_trading_results()

    if trades:
        # Analiz et
        stats = memory.analyze_all_trades(trades)

        # Raporu goster
        print("\n" + memory.get_report())

        # Ornek: Yeni bir sinyal gelseydi ne derdi?
        print("\n[TEST] Ornek sinyal degerlendirmesi:")
        test_signal = {
            "reason": "RSI asiri satim",
            "direction": 1
        }
        test_context = {
            "trend": "up",
            "volatility": 0.015
        }
        should_trade, confidence, reason = memory.should_take_signal(test_signal, test_context)
        print(f"  Sinyal: {test_signal['reason']}")
        print(f"  Karar: {'AL' if should_trade else 'PAS'}")
        print(f"  Guven: {confidence:.0%}")
        print(f"  Sebep: {reason}")
    else:
        print("\n[WARNING] Analiz edilecek islem yok.")
        print("Once paper trading calistirmalisin:")
        print("  python execution/paper_trading_v2.py")

    print("\n[MEMORY] Ogrenmeler kaydedildi: data/pattern_memory.json")
    print("="*60)


if __name__ == "__main__":
    main()

