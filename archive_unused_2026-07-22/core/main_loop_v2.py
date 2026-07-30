"""
Atlas AI - Main Loop v2.0
Tüm modülleri entegre eden ana döngü.

Akış:
1. Data Manager → OHLCV verisi çek
2. Strategy Base → Sinyal üret
3. Signal Pipeline → Validasyon
4. Decision Engine → Karar ver
5. Event System → Modülleri bilgilendir
6. Backtest Engine → Performans raporu
7. Memory Manager → Öğrenme kaydı

Özellikler:
- Modüler yapı — her modül bağımsız çalışır
- Hata koruması — bir modül çökerse diğerleri çalışmaya devam eder
- Event-driven — Event Bus üzerinden iletişim
- Configurable — config/settings.py'den ayarlanabilir
"""

import os
import sys
import time
import json
import logging
import traceback
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path

# Proje root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Logger ayarı
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('logs/atlas_main.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("AtlasAI.MainLoop")


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE LOADER — Güvenli modül yükleme
# ═══════════════════════════════════════════════════════════════════════════════

class ModuleLoader:
    """Modülleri güvenli şekilde yükler — hata durumunda fallback sağlar."""

    def __init__(self):
        self.modules = {}
        self.errors = {}

    def load(self, name: str, module_path: str, class_name: str = None, 
             fallback_class = None, **kwargs) -> Any:
        """
        Bir modülü yükle.

        Args:
            name: Modül adı
            module_path: Python modül yolu (örn: "core.signal_pipeline")
            class_name: Yüklenecek sınıf adı
            fallback_class: Hata durumunda kullanılacak sınıf
            **kwargs: Sınıf constructor parametreleri

        Returns:
            Yüklenen modül instance'ı veya fallback
        """
        try:
            # Dinamik import
            module = __import__(module_path, fromlist=[class_name])
            cls = getattr(module, class_name)
            instance = cls(**kwargs)

            self.modules[name] = instance
            logger.info(f"✅ [{name}] Modül yüklendi.")
            return instance

        except Exception as e:
            self.errors[name] = str(e)
            logger.error(f"❌ [{name}] Modül yükleme hatası: {e}")

            if fallback_class:
                logger.warning(f"⚠️  [{name}] Fallback kullanılıyor.")
                instance = fallback_class(**kwargs)
                self.modules[name] = instance
                return instance

            return None

    def get(self, name: str) -> Any:
        """Yüklenmiş modülü al"""
        return self.modules.get(name)

    def health_check(self) -> Dict[str, str]:
        """Tüm modüllerin sağlık durumunu kontrol et"""
        health = {}
        for name, module in self.modules.items():
            try:
                if hasattr(module, 'get_health'):
                    h = module.get_health()
                    health[name] = h.get('status', 'unknown') if isinstance(h, dict) else 'ok'
                else:
                    health[name] = 'ok'
            except Exception as e:
                health[name] = f'error: {e}'

        for name, error in self.errors.items():
            if name not in health:
                health[name] = f'failed: {error}'

        return health


# ═══════════════════════════════════════════════════════════════════════════════
# FALLBACK CLASSES — Modül yüklenemezse kullanılır
# ═══════════════════════════════════════════════════════════════════════════════

class FallbackEventBus:
    """Event Bus fallback — basit print"""
    def __init__(self, **kwargs): pass
    def publish(self, event): print(f"[EVENT] {event}")
    def subscribe(self, event_type, handler): pass
    def start(self): pass
    def stop(self): pass
    def get_health(self): return {"status": "fallback"}

class FallbackDataManager:
    """Data Manager fallback — mock veri"""
    def __init__(self, **kwargs): pass
    def get_ohlcv(self, symbol, **kwargs): 
        return type('MD', (), {
            'ohlcv': [{'timestamp': datetime.now().isoformat(), 'open': 65000, 'high': 66000, 'low': 64000, 'close': 65500, 'volume': 1000}],
            'source': 'fallback'
        })()
    def get_health(self): return {"status": "fallback"}

class FallbackDecisionEngine:
    """Decision Engine fallback — her şeyi onayla"""
    def __init__(self, **kwargs): pass
    def evaluate(self, signal): 
        return type('D', (), {'decision': type('DT', (), {'value': 'approve'})(), 'reason': 'fallback'})()
    def get_health(self): return {"status": "fallback"}


# ═══════════════════════════════════════════════════════════════════════════════
# ATLAS AI MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

class AtlasMainLoop:
    """
    Atlas AI Ana Döngüsü

    Tüm modülleri koordine eder ve piyasa döngüsünü yönetir.
    """

    def __init__(self, config_path: str = "config/settings.py"):
        self.config_path = config_path
        self.running = False
        self.iteration = 0
        self.start_time = None

        # Modül yükleyici
        self.loader = ModuleLoader()

        # Modüller
        self.event_bus = None
        self.data_manager = None
        self.signal_pipeline = None
        self.decision_engine = None
        self.strategy = None
        self.backtest_engine = None
        self.memory_manager = None

        # İstatistikler
        self.stats = {
            "cycles_completed": 0,
            "signals_generated": 0,
            "signals_approved": 0,
            "signals_rejected": 0,
            "trades_executed": 0,
            "errors": 0,
            "last_cycle_time_ms": 0
        }

        logger.info("Atlas Main Loop başlatıldı.")

    def initialize(self):
        """Tüm modülleri yükle ve başlat"""
        logger.info("🔧 Modüller yükleniyor...")
        print("\n" + "=" * 60)
        print("🔧 ATLAS AI — MODÜL YÜKLEME")
        print("=" * 60)

        # 1. Event Bus (önce yükle — diğerleri buna bağlı)
        self.event_bus = self.loader.load(
            "event_bus", "events.event_system_v2", "EventBus",
            fallback_class=FallbackEventBus,
            max_queue_size=10000, workers=2
        )
        if self.event_bus:
            self.event_bus.start()

        # 2. Data Manager
        self.data_manager = self.loader.load(
            "data_manager", "data.data_manager", "DataManager",
            fallback_class=FallbackDataManager,
            cache_ttl=5
        )

        # 3. Signal Pipeline
        self.signal_pipeline = self.loader.load(
            "signal_pipeline", "core.signal_pipeline", "SignalPipeline",
            min_confidence=0.5
        )

        # 4. Decision Engine
        self.decision_engine = self.loader.load(
            "decision_engine", "core.decision_engine", "DecisionEngine",
            fallback_class=FallbackDecisionEngine
        )

        # 5. Strategy
        try:
            from strategy.strategy_base import TrendFollowingStrategy
            self.strategy = TrendFollowingStrategy(timeframe="5m")
            self.loader.modules["strategy"] = self.strategy
            logger.info("✅ [strategy] TrendFollowingStrategy yüklendi.")
        except Exception as e:
            logger.error(f"❌ [strategy] Yükleme hatası: {e}")
            self.loader.errors["strategy"] = str(e)

        # 6. Backtest Engine
        try:
            from backtest.backtest_engine import BacktestEngine, BacktestConfig
            self.backtest_engine = BacktestEngine(BacktestConfig())
            self.loader.modules["backtest"] = self.backtest_engine
            logger.info("✅ [backtest] BacktestEngine yüklendi.")
        except Exception as e:
            logger.error(f"❌ [backtest] Yükleme hatası: {e}")
            self.loader.errors["backtest"] = str(e)

        # 7. Memory Manager
        try:
            from core.memory import MemoryManager
            self.memory_manager = MemoryManager()
            self.loader.modules["memory"] = self.memory_manager
            logger.info("✅ [memory] MemoryManager yüklendi.")
        except Exception as e:
            logger.error(f"❌ [memory] Yükleme hatası: {e}")
            self.loader.errors["memory"] = str(e)

        # Sağlık kontrolü
        print("\n🏥 SAĞLIK KONTROLÜ:")
        health = self.loader.health_check()
        for name, status in health.items():
            emoji = "✅" if status in ["ok", "healthy", "fallback"] else "❌"
            print(f"   {emoji} {name}: {status}")

        print("\n" + "=" * 60)

        # Event abonelikleri
        self._setup_event_subscriptions()

    def _setup_event_subscriptions(self):
        """Event aboneliklerini ayarla"""
        if not self.event_bus:
            return

        def on_signal_generated(event):
            logger.info(f"📡 Sinyal alındı: {event.payload.get('symbol', 'N/A')}")

        def on_trade_executed(event):
            logger.info(f"💰 İşlem gerçekleşti: {event.payload}")
            self.stats["trades_executed"] += 1

        def on_error(event):
            logger.error(f"🚨 Sistem hatası: {event.payload}")
            self.stats["errors"] += 1

        try:
            self.event_bus.subscribe("signal_generated", on_signal_generated)
            self.event_bus.subscribe("trade_executed", on_trade_executed)
            self.event_bus.subscribe("error", on_error)
            logger.info("📡 Event abonelikleri ayarlandı.")
        except Exception as e:
            logger.error(f"Event abonelik hatası: {e}")

    def run_cycle(self, symbol: str = "BTCUSDT", timeframe: str = "5m") -> Dict[str, Any]:
        """
        Tek bir piyasa döngüsü çalıştır.

        Args:
            symbol: İşlem çifti
            timeframe: Zaman aralığı

        Returns:
            Dict: Döngü sonuçları
        """
        start = time.perf_counter()
        self.iteration += 1

        logger.info(f"\n🔄 Döngü #{self.iteration} başlatılıyor... [{symbol} {timeframe}]")

        result = {
            "iteration": self.iteration,
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": datetime.now().isoformat(),
            "data_fetched": False,
            "signal_generated": False,
            "signal_valid": False,
            "decision": None,
            "error": None
        }

        try:
            # 1. Veri çek
            if self.data_manager:
                market_data = self.data_manager.get_ohlcv(symbol, timeframe, limit=100)
                result["data_fetched"] = True
                result["data_source"] = market_data.source if hasattr(market_data, 'source') else 'unknown'
                ohlcv = market_data.ohlcv if hasattr(market_data, 'ohlcv') else []
                logger.info(f"📊 Veri çekildi: {len(ohlcv)} bar ({result['data_source']})")
            else:
                logger.warning("⚠️  Data Manager yok — mock veri kullanılıyor.")
                ohlcv = []

            # 2. Strateji sinyali üret
            if self.strategy and ohlcv:
                closes = [c.close if hasattr(c, 'close') else c['close'] for c in ohlcv]
                highs = [c.high if hasattr(c, 'high') else c['high'] for c in ohlcv]
                lows = [c.low if hasattr(c, 'low') else c['low'] for c in ohlcv]

                indicators = self.strategy.analyze(closes, highs, lows)
                current_price = closes[-1] if closes else 0

                signal = self.strategy.generate_signal(indicators, current_price, symbol)
                result["signal_generated"] = True
                result["signal_action"] = signal.action if hasattr(signal, 'action') else 'HOLD'
                result["signal_confidence"] = signal.confidence if hasattr(signal, 'confidence') else 0

                self.stats["signals_generated"] += 1

                logger.info(f"📡 Sinyal: {result['signal_action']} (güven: {result['signal_confidence']})")

                # 3. Signal Pipeline validasyon
                if self.signal_pipeline and signal and hasattr(signal, 'action') and signal.action in ['BUY', 'SELL']:
                    processed = self.signal_pipeline.process(signal)
                    result["signal_valid"] = processed is not None

                    if processed:
                        logger.info("✅ Sinyal validasyonu başarılı.")

                        # 4. Decision Engine
                        if self.decision_engine:
                            try:
                                from core.signal_pipeline import Signal
                                decision_signal = Signal(
                                    symbol=symbol,
                                    action=signal.action,
                                    confidence=signal.confidence * 100 if signal.confidence else 50,
                                    strategy=self.strategy.name if hasattr(self.strategy, 'name') else 'unknown'
                                )
                                decision = self.decision_engine.evaluate(decision_signal)
                                result["decision"] = decision.decision.value if hasattr(decision, 'decision') else str(decision.decision)
                                result["decision_reason"] = decision.reason if hasattr(decision, 'reason') else ''

                                if result["decision"] in ['approve', 'modify']:
                                    self.stats["signals_approved"] += 1
                                    logger.info(f"✅ Karar: {result['decision'].upper()} — {result['decision_reason']}")
                                else:
                                    self.stats["signals_rejected"] += 1
                                    logger.info(f"❌ Karar: {result['decision'].upper()} — {result['decision_reason']}")
                            except Exception as e:
                                logger.error(f"Decision Engine hatası: {e}")
                                result["decision"] = "error"
                    else:
                        logger.warning("❌ Sinyal validasyonu başarısız.")
                        result["signal_valid"] = False
                else:
                    logger.info("⏸️  Sinyal yok veya HOLD — işlem yapılmıyor.")
            else:
                logger.warning("⚠️  Strateji veya veri yok.")

            # 5. Event yayınla
            if self.event_bus:
                try:
                    from events.event_system_v2 import AtlasEvent
                    self.event_bus.publish(AtlasEvent(
                        event_type="cycle_completed",
                        source="main_loop",
                        payload=result
                    ))
                except Exception as e:
                    logger.error(f"Event yayınlama hatası: {e}")

            # 6. Memory kaydet
            if self.memory_manager:
                try:
                    self.memory_manager.save_trade({
                        "symbol": symbol,
                        "action": result.get("signal_action", "HOLD"),
                        "confidence": result.get("signal_confidence", 0),
                        "decision": result.get("decision", "none"),
                        "price": current_price if 'current_price' in dir() else 0
                    })
                except Exception as e:
                    logger.error(f"Memory kaydetme hatası: {e}")

            self.stats["cycles_completed"] += 1

        except Exception as e:
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()
            self.stats["errors"] += 1
            logger.error(f"🚨 Döngü hatası: {e}")

            if self.event_bus:
                try:
                    from events.event_system_v2 import AtlasEvent
                    self.event_bus.publish(AtlasEvent(
                        event_type="error",
                        source="main_loop",
                        priority="CRITICAL",
                        payload={"error": str(e), "iteration": self.iteration}
                    ))
                except:
                    pass

        # Süre
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.stats["last_cycle_time_ms"] = elapsed_ms
        result["elapsed_ms"] = round(elapsed_ms, 2)

        logger.info(f"✅ Döngü #{self.iteration} tamamlandı ({elapsed_ms:.1f}ms)")

        return result

    def run(self, symbol: str = "BTCUSDT", timeframe: str = "5m", 
            cycles: int = 1, interval_seconds: float = 0):
        """
        Ana döngüyü çalıştır.

        Args:
            symbol: İşlem çifti
            timeframe: Zaman aralığı
            cycles: Kaç döngü çalıştırılacak (0 = sonsuz)
            interval_seconds: Döngüler arası bekleme süresi
        """
        self.running = True
        self.start_time = datetime.now()

        logger.info(f"\n🚀 ATLAS AI ANA DÖNGÜ BAŞLADI")
        logger.info(f"   Sembol: {symbol}")
        logger.info(f"   Timeframe: {timeframe}")
        logger.info(f"   Döngü: {'Sonsuz' if cycles == 0 else cycles}")

        print("\n" + "=" * 60)
        print("🚀 ATLAS AI ANA DÖNGÜ")
        print("=" * 60)

        cycle_count = 0

        try:
            while self.running:
                cycle_count += 1

                if cycles > 0 and cycle_count > cycles:
                    break

                result = self.run_cycle(symbol, timeframe)

                # Konsol özet
                print(f"\n📊 Döngü #{cycle_count} Sonucu:")
                print(f"   Veri: {'✅' if result['data_fetched'] else '❌'} | "
                      f"Sinyal: {result.get('signal_action', 'N/A')} | "
                      f"Karar: {result.get('decision', 'N/A')}")
                print(f"   Süre: {result.get('elapsed_ms', 0):.1f}ms")

                if interval_seconds > 0:
                    time.sleep(interval_seconds)

        except KeyboardInterrupt:
            logger.info("\n⛔ Kullanıcı tarafından durduruldu.")
        except Exception as e:
            logger.error(f"🚨 Ana döngü hatası: {e}")

        finally:
            self.shutdown()

    def shutdown(self):
        """Sistemi güvenli şekilde kapat"""
        logger.info("\n🛑 Sistem kapatılıyor...")
        self.running = False

        # Event Bus'u durdur
        if self.event_bus:
            try:
                self.event_bus.stop()
            except Exception as e:
                logger.error(f"Event Bus durdurma hatası: {e}")

        # İstatistikleri kaydet
        self._save_stats()

        # Özet
        print("\n" + "=" * 60)
        print("📊 ATLAS AI — ÇALIŞMA ÖZETİ")
        print("=" * 60)
        print(f"\n   Toplam Döngü: {self.stats['cycles_completed']}")
        print(f"   Sinyal Üretilen: {self.stats['signals_generated']}")
        print(f"   Onaylanan: {self.stats['signals_approved']}")
        print(f"   Reddedilen: {self.stats['signals_rejected']}")
        print(f"   İşlem Yapılan: {self.stats['trades_executed']}")
        print(f"   Hata: {self.stats['errors']}")
        print(f"   Son Döngü Süresi: {self.stats['last_cycle_time_ms']:.1f}ms")

        if self.start_time:
            elapsed = datetime.now() - self.start_time
            print(f"   Toplam Süre: {elapsed}")

        print("\n" + "=" * 60)
        logger.info("✅ Sistem güvenli şekilde kapatıldı.")

    def _save_stats(self):
        """İstatistikleri kaydet"""
        try:
            Path("logs").mkdir(exist_ok=True)

            stats = {
                "timestamp": datetime.now().isoformat(),
                "stats": self.stats,
                "modules": list(self.loader.modules.keys()),
                "errors": self.loader.errors
            }

            with open("logs/atlas_session_stats.json", "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2, default=str, ensure_ascii=False)

            logger.info("📊 İstatistikler kaydedildi: logs/atlas_session_stats.json")
        except Exception as e:
            logger.error(f"İstatistik kaydetme hatası: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Sistem durumunu döndür"""
        return {
            "running": self.running,
            "iteration": self.iteration,
            "stats": self.stats,
            "modules": self.loader.health_check(),
            "uptime": str(datetime.now() - self.start_time) if self.start_time else "N/A"
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_main_loop():
    """Main Loop test fonksiyonu"""
    print("🚀 Atlas AI Main Loop v2.0 - Test Mode")
    print("=" * 60)

    # Ana döngü oluştur
    atlas = AtlasMainLoop()

    # Modülleri yükle
    atlas.initialize()

    # Tek döngü çalıştır
    print("\n🔄 Tek döngü çalıştırılıyor...")
    print("-" * 60)

    result = atlas.run_cycle("BTCUSDT", "5m")

    print("\n📊 Döngü Sonucu:")
    for k, v in result.items():
        if k != "traceback":
            print(f"   {k}: {v}")

    # Durum
    print("\n📊 Sistem Durumu:")
    status = atlas.get_status()
    for k, v in status.items():
        if k != "stats":
            print(f"   {k}: {v}")

    # Kapat
    atlas.shutdown()

    print("\n" + "=" * 60)
    print("✅ Main Loop v2.0 test completed!")
    return atlas


if __name__ == "__main__":
    test_main_loop()
