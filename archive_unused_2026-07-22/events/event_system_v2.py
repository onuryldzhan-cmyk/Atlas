"""
Atlas AI - Event System v2.0
Aşama 2.4: Async pub/sub event bus — modüller birbirini bloklamadan iletişim kurar.

Özellikler:
- Thread-safe event bus
- Async event handlers
- Event filtreleme ve routing
- Event history ve replay
- Priority queue
- Dead letter queue (başarısız eventler)
"""

import json
import time
import queue
import threading
import logging
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Callable, Any, Set
from enum import Enum
from pathlib import Path

logger = logging.getLogger("AtlasAI.EventSystem")


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class EventPriority(Enum):
    """Event öncelikleri"""
    CRITICAL = 0    # Kritik — hemen işlenmeli
    HIGH = 1        # Yüksek — öncelikli
    NORMAL = 2      # Normal — sırayla
    LOW = 3         # Düşük — boşta işlenir
    BACKGROUND = 4  # Arka plan — en son


class EventType(Enum):
    """Standart event türleri"""
    # Piyasa Eventleri
    PRICE_UPDATE = "price_update"
    MARKET_REGIME_CHANGE = "market_regime_change"
    VOLATILITY_ALERT = "volatility_alert"

    # Sinyal Eventleri
    SIGNAL_GENERATED = "signal_generated"
    SIGNAL_VALIDATED = "signal_validated"
    SIGNAL_REJECTED = "signal_rejected"
    SIGNAL_EXECUTED = "signal_executed"

    # İşlem Eventleri
    TRADE_OPENED = "trade_opened"
    TRADE_CLOSED = "trade_closed"
    POSITION_UPDATE = "position_update"

    # Risk Eventleri
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    TAKE_PROFIT_TRIGGERED = "take_profit_triggered"
    RISK_ALERT = "risk_alert"

    # Sistem Eventleri
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    ERROR = "error"
    HEARTBEAT = "heartbeat"

    # AI Eventleri
    MODEL_PREDICTION = "model_prediction"
    LEARNING_UPDATE = "learning_update"
    STRATEGY_EVALUATION = "strategy_evaluation"


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AtlasEvent:
    """
    Atlas AI Standart Event

    Tüm modüller arası iletişim birimidir.
    """
    event_id: str = field(default_factory=lambda: f"evt_{int(time.time()*1000)%100000}")
    event_type: str = "generic"
    priority: str = "NORMAL"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    source: str = "unknown"
    target: Optional[str] = None  # None = broadcast
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    processed: bool = False
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "priority": self.priority,
            "timestamp": self.timestamp,
            "source": self.source,
            "target": self.target,
            "payload": self.payload,
            "metadata": self.metadata,
            "processed": self.processed,
            "error_count": self.error_count
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT BUS
# ═══════════════════════════════════════════════════════════════════════════════

class EventBus:
    """
    Atlas AI Event Bus v2.0

    Thread-safe pub/sub event sistemi.

    Kullanım:
        bus = EventBus()

        # Abone ol
        bus.subscribe("signal_generated", my_handler)

        # Event yayınla
        event = AtlasEvent(event_type="signal_generated", source="strategy", payload={...})
        bus.publish(event)

        # Başlat
        bus.start()

        # Durdur
        bus.stop()
    """

    def __init__(self, max_queue_size: int = 10000, workers: int = 4):
        self.max_queue_size = max_queue_size
        self.workers = workers

        # Event kuyruğu — priority queue
        self.event_queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=max_queue_size)

        # Aboneler — {event_type: [handler1, handler2, ...]}
        self.subscribers: Dict[str, List[Callable]] = {}
        self.subscriber_lock = threading.RLock()

        # Event geçmişi
        self.event_history: List[AtlasEvent] = []
        self.history_limit = 1000

        # Dead letter queue
        self.dead_letters: List[AtlasEvent] = []
        self.max_dead_letters = 100

        # Worker thread'ler
        self.worker_threads: List[threading.Thread] = []
        self.running = False
        self.shutdown_event = threading.Event()

        # İstatistikler
        self.stats = {
            "published": 0,
            "processed": 0,
            "dropped": 0,
            "errors": 0,
            "dead_letters": 0
        }

        logger.info(f"Event Bus başlatıldı ({workers} worker, {max_queue_size} max queue).")

    def subscribe(self, event_type: str, handler: Callable, priority_filter: List[str] = None):
        """
        Bir event türüne abone ol.

        Args:
            event_type: Event türü (EventType değeri veya "*" tümü)
            handler: Callback fonksiyonu — fn(event: AtlasEvent)
            priority_filter: Sadece belirli öncelikler (opsiyonel)
        """
        with self.subscriber_lock:
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []

            self.subscribers[event_type].append({
                "handler": handler,
                "priority_filter": priority_filter or ["CRITICAL", "HIGH", "NORMAL", "LOW"]
            })

            logger.info(f"[{event_type}] Abone eklendi: {handler.__name__}")

    def unsubscribe(self, event_type: str, handler: Callable):
        """Aboneliği kaldır"""
        with self.subscriber_lock:
            if event_type in self.subscribers:
                self.subscribers[event_type] = [
                    s for s in self.subscribers[event_type]
                    if s["handler"] != handler
                ]

    def publish(self, event: AtlasEvent) -> bool:
        """
        Event yayınla.

        Args:
            event: Yayınlanacak event

        Returns:
            bool: Başarılı ise True
        """
        try:
            # Priority değerini al
            priority_val = EventPriority[event.priority].value if hasattr(EventPriority, event.priority) else 2

            # Queue'ya ekle — (priority, timestamp, event)
            self.event_queue.put_nowait((priority_val, time.time(), event))
            self.stats["published"] += 1

            logger.debug(f"[{event.event_id}] Event yayınlandı: {event.event_type}")
            return True

        except queue.Full:
            self.stats["dropped"] += 1
            logger.warning(f"Event kuyruğu dolu! Event düşürüldü: {event.event_type}")
            return False
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Event yayınlama hatası: {e}")
            return False

    def publish_sync(self, event_type: str, payload: Dict, source: str = "system",
                     priority: str = "NORMAL", target: str = None) -> bool:
        """
        Hızlı event yayınlama — AtlasEvent otomatik oluşturulur.
        """
        event = AtlasEvent(
            event_type=event_type,
            priority=priority,
            source=source,
            target=target,
            payload=payload
        )
        return self.publish(event)

    def _process_event(self, event: AtlasEvent):
        """Tek bir event'i işle"""
        event.processed = True

        # Hedefe özel mi?
        target_handlers = []
        broadcast_handlers = []

        with self.subscriber_lock:
            # Hedefe özel handler'lar
            if event.target and event.target in self.subscribers:
                target_handlers = self.subscribers[event.target]

            # Broadcast handler'lar
            if event.event_type in self.subscribers:
                broadcast_handlers = self.subscribers[event.event_type]

            # "*" ile tüm event'lere abone olanlar
            if "*" in self.subscribers:
                broadcast_handlers.extend(self.subscribers["*"])

        all_handlers = target_handlers + broadcast_handlers

        if not all_handlers:
            logger.debug(f"[{event.event_id}] Abone yok: {event.event_type}")
            return

        # Handler'ları çalıştır
        for sub in all_handlers:
            handler = sub["handler"]
            priority_filter = sub.get("priority_filter", [])

            # Öncelik filtresi kontrolü
            if priority_filter and event.priority not in priority_filter:
                continue

            try:
                handler(event)
                logger.debug(f"[{event.event_id}] Handler çalıştı: {handler.__name__}")
            except Exception as e:
                event.error_count += 1
                self.stats["errors"] += 1
                logger.error(f"[{event.event_id}] Handler hatası ({handler.__name__}): {e}")

                # 3 hata = dead letter
                if event.error_count >= 3:
                    self._dead_letter(event)
                    break

        self.stats["processed"] += 1

        # Geçmişe ekle
        self.event_history.append(event)
        if len(self.event_history) > self.history_limit:
            self.event_history.pop(0)

    def _dead_letter(self, event: AtlasEvent):
        """Başarısız event'i dead letter queue'ya ekle"""
        self.dead_letters.append(event)
        self.stats["dead_letters"] += 1

        if len(self.dead_letters) > self.max_dead_letters:
            self.dead_letters.pop(0)

        logger.warning(f"[{event.event_id}] Dead letter queue'ya eklendi.")

    def _worker_loop(self, worker_id: int):
        """Worker thread ana döngüsü"""
        logger.info(f"Worker {worker_id} başlatıldı.")

        while self.running and not self.shutdown_event.is_set():
            try:
                # Event bekle (timeout ile — düzenli kontrol için)
                priority, ts, event = self.event_queue.get(timeout=1.0)
                self._process_event(event)
                self.event_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker {worker_id} hatası: {e}")

        logger.info(f"Worker {worker_id} durduruldu.")

    def start(self):
        """Event Bus'u başlat"""
        if self.running:
            logger.warning("Event Bus zaten çalışıyor.")
            return

        self.running = True
        self.shutdown_event.clear()

        # Worker thread'leri başlat
        for i in range(self.workers):
            t = threading.Thread(target=self._worker_loop, args=(i,), daemon=True)
            t.start()
            self.worker_threads.append(t)

        logger.info(f"Event Bus aktif ({self.workers} worker).")

    def stop(self, timeout: float = 5.0):
        """Event Bus'u durdur"""
        if not self.running:
            return

        logger.info("Event Bus durduruluyor...")
        self.running = False
        self.shutdown_event.set()

        # Kalan event'leri işle
        remaining = []
        while not self.event_queue.empty():
            try:
                remaining.append(self.event_queue.get_nowait())
            except queue.Empty:
                break

        logger.info(f"Kalan event sayısı: {len(remaining)}")

        # Worker'ları bekle
        for t in self.worker_threads:
            t.join(timeout=timeout / len(self.worker_threads))

        self.worker_threads.clear()
        logger.info("Event Bus durduruldu.")

    def get_stats(self) -> Dict[str, Any]:
        """Event Bus istatistiklerini döndür"""
        return {
            "running": self.running,
            "workers": self.workers,
            "queue_size": self.event_queue.qsize(),
            "published": self.stats["published"],
            "processed": self.stats["processed"],
            "dropped": self.stats["dropped"],
            "errors": self.stats["errors"],
            "dead_letters": self.stats["dead_letters"],
            "subscribers": {k: len(v) for k, v in self.subscribers.items()},
            "history_size": len(self.event_history)
        }

    def get_recent_events(self, n: int = 10) -> List[Dict]:
        """Son n event'i döndür"""
        return [e.to_dict() for e in self.event_history[-n:]]

    def replay_events(self, event_type: str = None, count: int = 100):
        """Geçmiş event'leri yeniden işle"""
        events = self.event_history[-count:] if count else self.event_history

        if event_type:
            events = [e for e in events if e.event_type == event_type]

        logger.info(f"{len(events)} event yeniden işleniyor...")

        for event in events:
            event.processed = False
            event.error_count = 0
            self.publish(event)

        logger.info("Replay tamamlandı.")


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT BRIDGE — Modüller arası köprü
# ═══════════════════════════════════════════════════════════════════════════════

class EventBridge:
    """
    Event Bridge — farklı modülleri event bus üzerinden bağlar.

    Örnek: Signal Pipeline → Event Bus → Execution Engine
    """

    def __init__(self, event_bus: EventBus):
        self.bus = event_bus
        self.bridges: Dict[str, Callable] = {}
        logger.info("Event Bridge başlatıldı.")

    def bridge(self, source_event: str, target_event: str, 
               transform: Callable = None):
        """
        İki event türü arasında köprü kur.

        Args:
            source_event: Kaynak event türü
            target_event: Hedef event türü
            transform: Dönüşüm fonksiyonu (opsiyonel)
        """
        def handler(event: AtlasEvent):
            new_payload = event.payload

            if transform:
                new_payload = transform(event.payload)

            self.bus.publish_sync(
                event_type=target_event,
                payload=new_payload,
                source="event_bridge",
                priority=event.priority
            )

        self.bus.subscribe(source_event, handler)
        self.bridges[f"{source_event}→{target_event}"] = handler

        logger.info(f"Köprü kuruldu: {source_event} → {target_event}")

    def remove_bridge(self, source_event: str, target_event: str):
        """Köprüyü kaldır"""
        key = f"{source_event}→{target_event}"
        if key in self.bridges:
            self.bus.unsubscribe(source_event, self.bridges[key])
            del self.bridges[key]
            logger.info(f"Köprü kaldırıldı: {source_event} → {target_event}")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_event_system():
    """Event System test fonksiyonu"""
    print("📡 Atlas AI Event System v2.0 - Test Mode")
    print("=" * 60)

    # Event Bus oluştur
    bus = EventBus(max_queue_size=1000, workers=2)

    # Test handler'ları
    received_signals = []
    received_trades = []
    received_all = []

    def signal_handler(event: AtlasEvent):
        received_signals.append(event)
        print(f"   📡 [SIGNAL] {event.event_type} | Kaynak: {event.source} | Payload: {event.payload.get('symbol', 'N/A')}")

    def trade_handler(event: AtlasEvent):
        received_trades.append(event)
        print(f"   💰 [TRADE] {event.event_type} | Kaynak: {event.source} | Payload: {event.payload}")

    def catch_all_handler(event: AtlasEvent):
        received_all.append(event)
        print(f"   🌐 [ALL] {event.event_type} | Öncelik: {event.priority}")

    # Abone ol
    print("\n📋 Abonelikler ayarlanıyor...")
    bus.subscribe("signal_generated", signal_handler)
    bus.subscribe("signal_validated", signal_handler)
    bus.subscribe("trade_opened", trade_handler)
    bus.subscribe("trade_closed", trade_handler)
    bus.subscribe("*", catch_all_handler)  # Tüm event'ler

    # Event Bus'u başlat
    print("\n🚀 Event Bus başlatılıyor...")
    bus.start()
    time.sleep(0.5)  # Worker'ların başlaması için

    # Event yayınla
    print("\n📤 Event'ler yayınlanıyor...")
    print("-" * 60)

    events = [
        AtlasEvent(event_type="signal_generated", source="strategy", priority="HIGH",
                  payload={"symbol": "BTCUSDT", "action": "BUY", "confidence": 0.85}),
        AtlasEvent(event_type="signal_validated", source="pipeline", priority="NORMAL",
                  payload={"symbol": "BTCUSDT", "valid": True}),
        AtlasEvent(event_type="trade_opened", source="execution", priority="CRITICAL",
                  payload={"symbol": "BTCUSDT", "side": "BUY", "size": 0.01}),
        AtlasEvent(event_type="price_update", source="data_manager", priority="LOW",
                  payload={"symbol": "ETHUSDT", "price": 3200.0}),
        AtlasEvent(event_type="heartbeat", source="system", priority="BACKGROUND",
                  payload={"status": "healthy"}),
    ]

    for event in events:
        bus.publish(event)
        time.sleep(0.1)  # İşlem sırası için

    # İşlenmesini bekle
    time.sleep(1.0)

    print("\n" + "-" * 60)
    print("\n📊 İstatistikler:")
    stats = bus.get_stats()
    for k, v in stats.items():
        if k not in ["subscribers"]:
            print(f"   {k}: {v}")

    print(f"\n📡 Alınan Sinyal Event'leri: {len(received_signals)}")
    print(f"💰 Alınan Trade Event'leri: {len(received_trades)}")
    print(f"🌐 Toplam Event (catch-all): {len(received_all)}")

    # Event Bridge testi
    print("\n" + "=" * 60)
    print("🔗 Event Bridge Testi")
    print("=" * 60)

    bridge = EventBridge(bus)
    bridge_outputs = []

    def bridge_target_handler(event: AtlasEvent):
        bridge_outputs.append(event)
        print(f"   🎯 [BRIDGE TARGET] {event.event_type} | Payload: {event.payload}")

    bus.subscribe("trade_executed", bridge_target_handler)

    # Köprü kur: signal_executed → trade_executed
    bridge.bridge("signal_executed", "trade_executed", 
                  transform=lambda p: {**p, "bridged": True, "timestamp": datetime.now().isoformat()})

    # Test event
    bus.publish_sync("signal_executed", {"symbol": "SOLUSDT", "action": "SELL"}, source="strategy")
    time.sleep(0.5)

    print(f"\n📊 Bridge çıktısı: {len(bridge_outputs)} event")

    # Durum raporu
    print("\n" + "=" * 60)
    print("📊 Son Event Geçmişi:")
    recent = bus.get_recent_events(5)
    for e in recent:
        print(f"   [{e['event_id']}] {e['event_type']} ({e['priority']})")

    # Durdur
    print("\n🛑 Event Bus durduruluyor...")
    bus.stop()

    print("\n" + "=" * 60)
    print("✅ Event System v2.0 test completed!")
    return bus


if __name__ == "__main__":
    test_event_system()
