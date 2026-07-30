"""
Atlas AI - Memory Manager v2.0
İşlem geçmişini kaydetme, analiz etme ve başarı oranlarını optimize etme motoru.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

logger = logging.getLogger("AtlasAI.Memory")


class MemoryManager:
    """
    Atlas AI Hafiza ve Öğrenme Motoru v2.0

    Özellikler:
    - Otomatik dosya/klasör oluşturma
    - JSON tabanlı kalıcı hafiza
    - İşlem istatistikleri ve analiz
    - Hata koruması ve loglama
    - Bellek kullanım optimizasyonu (max 1000 kayıt)
    """

    def __init__(self, filepath: str = "data/atlas_memory.json", max_records: int = 1000):
        self.filepath = Path(filepath)
        self.max_records = max_records
        self._ensure_file_exists()
        logger.info(f"Memory Manager başlatıldı: {self.filepath}")

    def _ensure_file_exists(self):
        """Hafiza dosyasinin ve klasörünün varlığını kontrol eder, yoksa oluşturur."""
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            if not self.filepath.exists():
                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=4)
                logger.info("Yeni hafiza dosyası oluşturuldu.")
        except Exception as e:
            logger.error(f"Hafiza dosyası oluşturma hatası: {e}")
            raise

    def _load_memory(self) -> List[Dict]:
        """Hafizayı güvenli şekilde yükle"""
        try:
            if not self.filepath.exists():
                return []
            with open(self.filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Hafiza dosyası bozuk: {e}. Yeniden oluşturuluyor.")
            self._ensure_file_exists()
            return []
        except Exception as e:
            logger.error(f"Hafiza yükleme hatası: {e}")
            return []

    def _save_memory(self, memory: List[Dict]):
        """Hafizayı güvenli şekilde kaydet"""
        try:
            # Bellek limiti kontrolü — eski kayıtları temizle
            if len(memory) > self.max_records:
                memory = memory[-self.max_records:]
                logger.info(f"Hafiza limiti aşıldı. Son {self.max_records} kayıt tutuldu.")

            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(memory, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Hafiza kaydetme hatası: {e}")

    def save_trade(self, trade_data: Dict[str, Any]) -> bool:
        """
        Yeni bir işlem kaydını hafızaya ekler.

        Args:
            trade_data: İşlem bilgileri (symbol, action, price, profit vb.)

        Returns:
            bool: Başarılı ise True
        """
        try:
            memory = self._load_memory()

            # İşleme zaman damgası ekle
            trade_data["timestamp"] = datetime.now().isoformat()
            trade_data["memory_id"] = len(memory) + 1

            memory.append(trade_data)
            self._save_memory(memory)

            logger.info(f"İşlem kaydedildi: {trade_data.get('symbol', 'UNKNOWN')} {trade_data.get('action', 'N/A')}")
            return True

        except Exception as e:
            logger.error(f"İşlem kaydetme hatası: {e}")
            return False

    def get_stats(self, symbol: str = None) -> Dict[str, Any]:
        """
        Hafizadaki verileri analiz ederek başarı oranlarını çıkarır.

        Args:
            symbol: Belirli bir coin filtresi (None = tümü)

        Returns:
            Dict: İstatistik raporu
        """
        try:
            trades = self._load_memory()

            if not trades:
                return {"status": "Henüz işlem kaydı yok", "total_trades": 0}

            # Sembol filtresi
            if symbol:
                trades = [t for t in trades if t.get("symbol") == symbol]
                if not trades:
                    return {"status": f"{symbol} için kayıt yok", "total_trades": 0}

            total = len(trades)
            profitable = sum(1 for t in trades if t.get("profit", 0) > 0)
            losing = sum(1 for t in trades if t.get("profit", 0) < 0)
            break_even = total - profitable - losing

            total_profit = sum(t.get("profit", 0) for t in trades)
            avg_profit = total_profit / total if total > 0 else 0

            # Strateji performansı
            strategies = {}
            for t in trades:
                strat = t.get("strategy", "unknown")
                if strat not in strategies:
                    strategies[strat] = {"count": 0, "profit": 0}
                strategies[strat]["count"] += 1
                strategies[strat]["profit"] += t.get("profit", 0)

            # En iyi ve en kötü saatler
            hours = {}
            for t in trades:
                hour = t.get("timestamp", "")
                if hour:
                    try:
                        h = datetime.fromisoformat(hour).hour
                        if h not in hours:
                            hours[h] = {"count": 0, "profit": 0}
                        hours[h]["count"] += 1
                        hours[h]["profit"] += t.get("profit", 0)
                    except:
                        pass

            best_hour = max(hours, key=lambda x: hours[x]["profit"]) if hours else None

            return {
                "status": "success",
                "symbol": symbol or "ALL",
                "total_trades": total,
                "profitable_trades": profitable,
                "losing_trades": losing,
                "break_even": break_even,
                "win_rate": round(profitable / total * 100, 2) if total > 0 else 0,
                "total_profit": round(total_profit, 4),
                "avg_profit_per_trade": round(avg_profit, 4),
                "strategies": strategies,
                "best_hour": best_hour,
                "hourly_performance": hours
            }

        except Exception as e:
            logger.error(f"İstatistik hesaplama hatası: {e}")
            return {"status": f"Hata: {str(e)}", "total_trades": 0}

    def get_recent_trades(self, n: int = 10) -> List[Dict]:
        """Son n işlemi döndür"""
        trades = self._load_memory()
        return trades[-n:] if trades else []

    def clear_memory(self) -> bool:
        """Tüm hafızayı temizle (dikkat!)"""
        try:
            self._save_memory([])
            logger.warning("Hafiza tamamen temizlendi!")
            return True
        except Exception as e:
            logger.error(f"Hafiza temizleme hatası: {e}")
            return False

    def get_memory_usage(self) -> Dict[str, Any]:
        """Hafiza kullanım bilgilerini döndür"""
        try:
            trades = self._load_memory()
            file_size = self.filepath.stat().st_size if self.filepath.exists() else 0

            return {
                "record_count": len(trades),
                "max_records": self.max_records,
                "usage_percentage": round(len(trades) / self.max_records * 100, 2),
                "file_size_kb": round(file_size / 1024, 2),
                "status": "healthy" if len(trades) < self.max_records * 0.9 else "warning"
            }
        except Exception as e:
            logger.error(f"Kullanım bilgisi hatası: {e}")
            return {"record_count": 0, "status": f"error: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_memory_manager():
    """Memory Manager test fonksiyonu"""
    print("🧠 Atlas AI Memory Manager v2.0 - Test Mode")
    print("=" * 50)

    # Test için geçici dosya kullan
    memory = MemoryManager(filepath="data/test_memory.json", max_records=100)

    print("\n💾 Test işlemleri kaydediliyor...")
    test_trades = [
        {"symbol": "BTCUSDT", "action": "BUY", "price": 65000, "profit": 150.5, "strategy": "trend_following"},
        {"symbol": "ETHUSDT", "action": "SELL", "price": 3200, "profit": -45.2, "strategy": "mean_reversion"},
        {"symbol": "SOLUSDT", "action": "BUY", "price": 145, "profit": 23.8, "strategy": "momentum"},
        {"symbol": "BTCUSDT", "action": "BUY", "price": 66000, "profit": 89.0, "strategy": "trend_following"},
    ]

    for trade in test_trades:
        success = memory.save_trade(trade)
        print(f"   {'✅' if success else '❌'} {trade['symbol']} {trade['action']} kaydedildi.")

    print("\n📊 Genel İstatistikler:")
    stats = memory.get_stats()
    for k, v in stats.items():
        if k != "hourly_performance":
            print(f"   {k}: {v}")

    print("\n📊 BTCUSDT İstatistikleri:")
    btc_stats = memory.get_stats(symbol="BTCUSDT")
    for k, v in btc_stats.items():
        if k != "hourly_performance":
            print(f"   {k}: {v}")

    print("\n💾 Hafiza Kullanımı:")
    usage = memory.get_memory_usage()
    for k, v in usage.items():
        print(f"   {k}: {v}")

    print("\n📜 Son İşlemler:")
    recent = memory.get_recent_trades(3)
    for t in recent:
        print(f"   #{t.get('memory_id')} {t['symbol']} {t['action']} @ {t['price']} → {t.get('profit', 0):.2f}")

    # Temizlik
    memory.clear_memory()
    print("\n✅ Memory Manager v2.0 test completed!")
    return memory


if __name__ == "__main__":
    test_memory_manager()
