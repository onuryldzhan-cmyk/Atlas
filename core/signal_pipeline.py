"""
Atlas AI - Signal Pipeline v2.0
Aşama 2.1: Tüm sinyallerin standart formatı, validasyonu ve işlenme akışı.

Bu modül, Atlas AI'nin tüm modülleri arasındaki iletişim dilini tanımlar.
Her sinyal aynı yapıyı kullanır, her modül aynı formatta üretir/tüketir.
"""

import json
import time
import uuid
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from pathlib import Path

logger = logging.getLogger("AtlasAI.SignalPipeline")


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class SignalAction(Enum):
    """İşlem aksiyonları"""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"
    MODIFY = "MODIFY"


class SignalStatus(Enum):
    """Sinyal durumları"""
    PENDING = "pending"           # Bekliyor
    VALIDATED = "validated"       # Doğrulandı
    APPROVED = "approved"         # Onaylandı
    REJECTED = "rejected"         # Reddedildi
    EXECUTED = "executed"         # İşleme kondu
    EXPIRED = "expired"           # Süresi doldu
    FAILED = "failed"             # Başarısız


class SignalSource(Enum):
    """Sinyal kaynakları"""
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
    BREAKOUT = "breakout"
    SCALPING = "scalping"
    AI_MODEL = "ai_model"
    MANUAL = "manual"
    RISK_MANAGER = "risk_manager"


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SignalMetadata:
    """Sinyal meta verileri"""
    timeframe: str = "5m"
    exchange: str = "binance"
    market_type: str = "spot"  # spot | futures
    strategy_version: str = "1.0"
    backtested: bool = False
    backtest_win_rate: float = 0.0
    custom: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalRisk:
    """Sinyal risk parametreleri"""
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward_ratio: float = 0.0
    position_size_pct: float = 0.01  # Portföyün %1'i
    max_slippage_pct: float = 0.5
    trailing_stop: bool = False
    trailing_stop_distance: float = 0.0


@dataclass
class SignalContext:
    """Sinyal bağlamı — piyasa durumu"""
    trend: str = "neutral"  # bullish | bearish | neutral | sideways
    trend_strength: float = 0.0
    volatility: float = 0.0
    volume_profile: str = "normal"
    market_regime: str = "unknown"
    indicators: Dict[str, float] = field(default_factory=dict)


@dataclass
class TradingSignal:
    """
    Atlas AI Standart Trading Sinyali

    Tüm modüller bu yapıyı kullanır. Eksik alan = invalid sinyal.
    """
    # Kimlik
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Temel bilgiler
    symbol: str = ""                    # Örn: BTCUSDT
    action: str = "HOLD"                # BUY | SELL | HOLD | CLOSE | MODIFY
    confidence: float = 0.0             # 0.0 - 1.0

    # Kaynak
    source: str = "unknown"             # Hangi strateji/AI üretti
    source_version: str = "1.0"

    # Fiyat bilgileri
    entry_price: float = 0.0
    current_price: float = 0.0

    # Risk
    risk: SignalRisk = field(default_factory=SignalRisk)

    # Bağlam
    context: SignalContext = field(default_factory=SignalContext)

    # Meta
    metadata: SignalMetadata = field(default_factory=SignalMetadata)

    # Durum
    status: str = "pending"
    status_history: List[Dict] = field(default_factory=list)

    # Hata ve notlar
    errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Sinyal oluşturulduktan sonra çalışır"""
        if not self.status_history:
            self._add_status_history("created")

    def _add_status_history(self, new_status: str, reason: str = ""):
        """Durum geçmişine ekle"""
        self.status_history.append({
            "status": new_status,
            "timestamp": datetime.now().isoformat(),
            "reason": reason
        })

    def to_dict(self) -> Dict[str, Any]:
        """Sinyali JSON-serialize edilebilir dict'e çevir"""
        return {
            "signal_id": self.signal_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "action": self.action,
            "confidence": self.confidence,
            "source": self.source,
            "source_version": self.source_version,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "risk": asdict(self.risk),
            "context": asdict(self.context),
            "metadata": asdict(self.metadata),
            "status": self.status,
            "status_history": self.status_history,
            "errors": self.errors,
            "notes": self.notes
        }

    def to_json(self, indent: int = 2) -> str:
        """Sinyali JSON string'e çevir"""
        return json.dumps(self.to_dict(), indent=indent, default=str, ensure_ascii=False)

    def update_status(self, new_status: str, reason: str = ""):
        """Sinyal durumunu güncelle"""
        old_status = self.status
        self.status = new_status
        self._add_status_history(new_status, reason)
        logger.info(f"[{self.signal_id}] {old_status} → {new_status} | {reason}")

    def add_note(self, note: str):
        """Sinyale not ekle"""
        self.notes.append(f"[{datetime.now().strftime('%H:%M:%S')}] {note}")

    def add_error(self, error: str):
        """Sinyale hata ekle"""
        self.errors.append(f"[{datetime.now().strftime('%H:%M:%S')}] {error}")
        logger.error(f"[{self.signal_id}] Hata: {error}")


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════════

class SignalValidator:
    """
    Sinyal validatörü — her sinyalin geçerli olup olmadığını kontrol eder.
    """

    # Zorunlu alanlar
    REQUIRED_FIELDS = ["symbol", "action", "confidence", "source"]

    # Geçerli aksiyonlar
    VALID_ACTIONS = ["BUY", "SELL", "HOLD", "CLOSE", "MODIFY"]

    # Minimum güven skoru
    MIN_CONFIDENCE = 0.0
    MAX_CONFIDENCE = 1.0

    # Sinyal ömrü (dakika)
    SIGNAL_TTL_MINUTES = 30

    def __init__(self, min_confidence: float = 0.5, signal_ttl: int = 30):
        self.min_confidence = min_confidence
        self.signal_ttl = signal_ttl
        self.validation_stats = {
            "total_validated": 0,
            "valid": 0,
            "invalid": 0,
            "expired": 0
        }

    def validate(self, signal: TradingSignal) -> Tuple[bool, List[str]]:
        """
        Bir sinyali doğrula.

        Returns:
            Tuple[bool, List[str]]: (geçerli_mi, hata_mesajları)
        """
        self.validation_stats["total_validated"] += 1
        errors = []

        # 1. Zorunlu alanlar
        for field in self.REQUIRED_FIELDS:
            value = getattr(signal, field, None)
            if not value and value != 0.0:
                errors.append(f"Eksik alan: {field}")

        # 2. Aksiyon geçerliliği
        if signal.action not in self.VALID_ACTIONS:
            errors.append(f"Geçersiz aksiyon: {signal.action}")

        # 3. Güven skoru aralığı
        if not (self.MIN_CONFIDENCE <= signal.confidence <= self.MAX_CONFIDENCE):
            errors.append(f"Güven skoru aralık dışı: {signal.confidence}")

        # 4. Minimum güven skoru
        if signal.confidence < self.min_confidence:
            errors.append(f"Güven skoru çok düşük: {signal.confidence} < {self.min_confidence}")

        # 5. Zaman aşımı
        try:
            signal_time = datetime.fromisoformat(signal.timestamp)
            if datetime.now() - signal_time > timedelta(minutes=self.signal_ttl):
                errors.append(f"Sinyal süresi doldu: {signal.timestamp}")
                self.validation_stats["expired"] += 1
        except:
            errors.append(f"Geçersiz zaman damgası: {signal.timestamp}")

        # 6. Sembol formatı
        if signal.symbol and not signal.symbol.endswith("USDT"):
            errors.append(f"Sembol formatı uyarısı: {signal.symbol} (USDT çifti önerilir)")

        # 7. Risk parametreleri
        if signal.risk.stop_loss <= 0 and signal.action in ["BUY", "SELL"]:
            errors.append("Stop loss belirtilmemiş")

        if signal.risk.take_profit <= 0 and signal.action in ["BUY", "SELL"]:
            errors.append("Take profit belirtilmemiş")

        # Sonuç
        is_valid = len(errors) == 0

        if is_valid:
            self.validation_stats["valid"] += 1
            signal.update_status("validated", "Tüm kontrollerden geçti")
        else:
            self.validation_stats["invalid"] += 1
            for error in errors:
                signal.add_error(error)
            signal.update_status("rejected", f"{len(errors)} validasyon hatası")

        return is_valid, errors

    def get_stats(self) -> Dict[str, Any]:
        """Validasyon istatistiklerini döndür"""
        total = self.validation_stats["total_validated"]
        return {
            "total_validated": total,
            "valid": self.validation_stats["valid"],
            "invalid": self.validation_stats["invalid"],
            "expired": self.validation_stats["expired"],
            "valid_rate": round(self.validation_stats["valid"] / total * 100, 2) if total > 0 else 0
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

class SignalPipeline:
    """
    Atlas AI Signal Pipeline

    Sinyallerin işlenme akışı:
    1. Al (Receive)
    2. Doğrula (Validate)
    3. Filtrele (Filter)
    4. Zenginleştir (Enrich)
    5. Yönlendir (Route)
    """

    def __init__(self, min_confidence: float = 0.5):
        self.validator = SignalValidator(min_confidence=min_confidence)
        self.signals: List[TradingSignal] = []
        self.processed_signals: List[TradingSignal] = []
        self.rejected_signals: List[TradingSignal] = []

        # Pipeline aşamaları
        self.stages: Dict[str, List[Callable]] = {
            "receive": [],
            "validate": [],
            "filter": [],
            "enrich": [],
            "route": []
        }

        # İstatistikler
        self.stats = {
            "received": 0,
            "validated": 0,
            "filtered": 0,
            "enriched": 0,
            "routed": 0,
            "rejected": 0
        }

        logger.info("Signal Pipeline başlatıldı.")

    def add_stage_handler(self, stage: str, handler: Callable):
        """Pipeline aşamasına handler ekle"""
        if stage in self.stages:
            self.stages[stage].append(handler)
            logger.info(f"[{stage}] Handler eklendi: {handler.__name__}")

    def receive(self, signal: TradingSignal) -> TradingSignal:
        """Sinyal al — Stage 1"""
        self.stats["received"] += 1
        self.signals.append(signal)
        signal.add_note("Pipeline'a alındı")

        # Receive handler'ları çalıştır
        for handler in self.stages["receive"]:
            handler(signal)

        logger.info(f"[{signal.signal_id}] Sinyal alındı: {signal.symbol} {signal.action}")
        return signal

    def validate(self, signal: TradingSignal) -> bool:
        """Sinyal doğrula — Stage 2"""
        is_valid, errors = self.validator.validate(signal)

        if is_valid:
            self.stats["validated"] += 1
            signal.add_note("Validasyon başarılı")

            # Validate handler'ları çalıştır
            for handler in self.stages["validate"]:
                handler(signal)

            return True
        else:
            self.stats["rejected"] += 1
            self.rejected_signals.append(signal)
            logger.warning(f"[{signal.signal_id}] Validasyon başarısız: {errors}")
            return False

    def filter_signal(self, signal: TradingSignal) -> bool:
        """Sinyal filtrele — Stage 3"""
        # Varsayılan filtreler

        # 1. Güven skoru filtresi
        if signal.confidence < 0.5:
            signal.add_note("Düşük güven — filtrelendi")
            return False

        # 2. Aynı sembol + aksiyon çiftini kontrol et (son 5 dakika)
        recent = [
            s for s in self.processed_signals
            if s.symbol == signal.symbol
            and s.action == signal.action
            and datetime.now() - datetime.fromisoformat(s.timestamp) < timedelta(minutes=5)
        ]
        if recent:
            signal.add_note("Yakın zamanda aynı sinyal var — filtrelendi")
            return False

        self.stats["filtered"] += 1
        signal.add_note("Filtreleme başarılı")

        # Filter handler'ları çalıştır
        for handler in self.stages["filter"]:
            if not handler(signal):
                return False

        return True

    def enrich(self, signal: TradingSignal) -> TradingSignal:
        """Sinyal zenginleştir — Stage 4"""
        # Varsayılan zenginleştirmeler

        # 1. Risk/ödül hesapla
        if signal.risk.stop_loss > 0 and signal.risk.take_profit > 0:
            risk = abs(signal.entry_price - signal.risk.stop_loss)
            reward = abs(signal.risk.take_profit - signal.entry_price)
            signal.risk.risk_reward_ratio = round(reward / risk, 2) if risk > 0 else 0

        # 2. Piyasa rejimi belirle
        if signal.context.volatility > 0.05:
            signal.context.market_regime = "volatile"
        elif signal.context.trend_strength > 0.7:
            signal.context.market_regime = "trending"
        else:
            signal.context.market_regime = "ranging"

        self.stats["enriched"] += 1
        signal.add_note("Zenginleştirme tamamlandı")

        # Enrich handler'ları çalıştır
        for handler in self.stages["enrich"]:
            handler(signal)

        return signal

    def route(self, signal: TradingSignal) -> str:
        """Sinyali hedefe yönlendir — Stage 5"""
        self.stats["routed"] += 1
        self.processed_signals.append(signal)

        # Hedef belirle
        if signal.action == "HOLD":
            destination = "monitor"
        elif signal.confidence > 0.8:
            destination = "execution_high_priority"
        else:
            destination = "execution_normal"

        signal.update_status("approved", f"Yönlendirildi: {destination}")
        signal.add_note(f"Hedef: {destination}")

        # Route handler'ları çalıştır
        for handler in self.stages["route"]:
            handler(signal, destination)

        logger.info(f"[{signal.signal_id}] Yönlendirildi: {destination}")
        return destination

    def process(self, signal: TradingSignal) -> Optional[TradingSignal]:
        """
        Tam pipeline işlemi — tüm aşamalar.

        Returns:
            TradingSignal: Başarılı ise işlenmiş sinyal, değilse None
        """
        # Stage 1: Al
        self.receive(signal)

        # Stage 2: Doğrula
        if not self.validate(signal):
            return None

        # Stage 3: Filtrele
        if not self.filter_signal(signal):
            return None

        # Stage 4: Zenginleştir
        self.enrich(signal)

        # Stage 5: Yönlendir
        self.route(signal)

        return signal

    def process_batch(self, signals: List[TradingSignal]) -> List[TradingSignal]:
        """Birden fazla sinyali işle"""
        results = []
        for signal in signals:
            result = self.process(signal)
            if result:
                results.append(result)
        return results

    def get_stats(self) -> Dict[str, Any]:
        """Pipeline istatistiklerini döndür"""
        return {
            "pipeline_stats": self.stats,
            "validation_stats": self.validator.get_stats(),
            "pending_signals": len(self.signals) - len(self.processed_signals) - len(self.rejected_signals),
            "processed_signals": len(self.processed_signals),
            "rejected_signals": len(self.rejected_signals),
            "success_rate": round(
                len(self.processed_signals) / max(self.stats["received"], 1) * 100, 2
            )
        }

    def get_signal_by_id(self, signal_id: str) -> Optional[TradingSignal]:
        """ID ile sinyal bul"""
        for s in self.signals:
            if s.signal_id == signal_id:
                return s
        return None

    def export_to_json(self, filepath: str = "logs/signals.json"):
        """Tüm sinyalleri JSON olarak dışa aktar"""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        data = {
            "export_time": datetime.now().isoformat(),
            "signals": [s.to_dict() for s in self.processed_signals],
            "rejected": [s.to_dict() for s in self.rejected_signals],
            "stats": self.get_stats()
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Sinyaller dışa aktarıldı: {filepath}")


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY — Kolay sinyal oluşturma
# ═══════════════════════════════════════════════════════════════════════════════

class SignalFactory:
    """Kolay sinyal oluşturma fabrikası"""

    @staticmethod
    def buy(symbol: str, confidence: float, entry: float, stop: float, target: float,
            source: str = "manual", timeframe: str = "5m") -> TradingSignal:
        """BUY sinyali oluştur"""
        return TradingSignal(
            symbol=symbol,
            action="BUY",
            confidence=confidence,
            source=source,
            entry_price=entry,
            current_price=entry,
            risk=SignalRisk(
                stop_loss=stop,
                take_profit=target,
                position_size_pct=0.01
            ),
            metadata=SignalMetadata(timeframe=timeframe)
        )

    @staticmethod
    def sell(symbol: str, confidence: float, entry: float, stop: float, target: float,
             source: str = "manual", timeframe: str = "5m") -> TradingSignal:
        """SELL sinyali oluştur"""
        return TradingSignal(
            symbol=symbol,
            action="SELL",
            confidence=confidence,
            source=source,
            entry_price=entry,
            current_price=entry,
            risk=SignalRisk(
                stop_loss=stop,
                take_profit=target,
                position_size_pct=0.01
            ),
            metadata=SignalMetadata(timeframe=timeframe)
        )

    @staticmethod
    def hold(symbol: str, reason: str = "", source: str = "manual") -> TradingSignal:
        """HOLD sinyali oluştur"""
        return TradingSignal(
            symbol=symbol,
            action="HOLD",
            confidence=1.0,
            source=source,
            notes=[reason] if reason else []
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_signal_pipeline():
    """Signal Pipeline test fonksiyonu"""
    print("📡 Atlas AI Signal Pipeline v2.0 - Test Mode")
    print("=" * 60)

    pipeline = SignalPipeline(min_confidence=0.5)

    # Test sinyalleri oluştur
    print("\n🔨 Test sinyalleri oluşturuluyor...")

    signals = [
        # Geçerli BUY sinyali
        SignalFactory.buy(
            symbol="BTCUSDT",
            confidence=0.85,
            entry=65000.0,
            stop=64000.0,
            target=67000.0,
            source="trend_following"
        ),

        # Geçerli SELL sinyali
        SignalFactory.sell(
            symbol="ETHUSDT",
            confidence=0.72,
            entry=3200.0,
            stop=3300.0,
            target=3000.0,
            source="mean_reversion"
        ),

        # Düşük güven — red edilmeli
        TradingSignal(
            symbol="SOLUSDT",
            action="BUY",
            confidence=0.3,
            source="momentum",
            entry_price=145.0,
            risk=SignalRisk(stop_loss=140.0, take_profit=155.0)
        ),

        # Eksik alan — red edilmeli
        TradingSignal(
            symbol="ADAUSDT",
            action="BUY",
            confidence=0.8,
            source="breakout"
            # entry_price ve risk eksik
        ),

        # HOLD sinyali
        SignalFactory.hold("XRPUSDT", "Piyasa kararsız", "risk_manager")
    ]

    print(f"   {len(signals)} sinyal oluşturuldu.")

    # Pipeline işlemi
    print("\n🔄 Pipeline işlemi başlatılıyor...")
    print("-" * 60)

    results = pipeline.process_batch(signals)

    print("\n" + "=" * 60)
    print("📊 Pipeline İstatistikleri:")
    stats = pipeline.get_stats()
    for key, value in stats.items():
        if key != "validation_stats":
            print(f"   {key}: {value}")

    print("\n📊 Validasyon İstatistikleri:")
    for key, value in stats["validation_stats"].items():
        print(f"   {key}: {value}")

    print("\n✅ İşlenen Sinyaller:")
    for s in pipeline.processed_signals:
        print(f"   🟢 [{s.signal_id}] {s.symbol} {s.action} | Güven: {s.confidence} | Hedef: {s.risk.take_profit}")

    print("\n❌ Reddedilen Sinyaller:")
    for s in pipeline.rejected_signals:
        print(f"   🔴 [{s.signal_id}] {s.symbol} {s.action} | Hatalar: {len(s.errors)}")
        for err in s.errors[:2]:
            print(f"      → {err}")

    # JSON export testi
    print("\n💾 JSON Export testi...")
    pipeline.export_to_json("logs/test_signals.json")
    print("   ✅ Sinyaller logs/test_signals.json olarak kaydedildi.")

    print("\n" + "=" * 60)
    print("✅ Signal Pipeline v2.0 test completed!")
    return pipeline


if __name__ == "__main__":
    test_signal_pipeline()
