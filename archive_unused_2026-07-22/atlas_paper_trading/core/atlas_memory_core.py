"""
================================================================================
ATLAS AI - MEMORY CORE (atlas_memory_core.py)
================================================================================
Birlestirilmis hafiza sistemi. Tum hafiza turlerini tek cati altinda toplar:
- Short Memory (Anlik calisma hafizasi)
- Long Memory (Uzun vadeli ogrenme)
- Semantic Memory (Anlamli bilgi - piyasa kavramlari, iliskiler)
- Episode Memory (Olay bazli - her trade bir episode)
- Trade Memory (Islem kayitlari)
- Knowledge Memory (Elde edilen bilgiler, kesifler)

Tasarim prensibi: Tum hafiza turleri tek bir API uzerinden erisilebilir.
Diger moduller (Reasoning, Multi-Agent, Learning) sadece bu modulu import eder.
================================================================================
"""

import json
import pickle
import hashlib
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field, asdict
from collections import defaultdict, deque
from enum import Enum
import threading
import os


# ==============================================================================
# ENUMS & CONSTANTS
# ==============================================================================

class MemoryType(Enum):
    SHORT = "short"           # Anlik calisma hafizasi (son 100 olay)
    LONG = "long"             # Uzun vadeli ogrenme
    SEMANTIC = "semantic"     # Anlamli bilgi (kavramlar, iliskiler)
    EPISODE = "episode"       # Olay bazli (her trade bir episode)
    TRADE = "trade"           # Islem kayitlari
    KNOWLEDGE = "knowledge"   # Elde edilen bilgiler

class ConfidenceLevel(Enum):
    VERY_LOW = 0.1
    LOW = 0.3
    MEDIUM = 0.5
    HIGH = 0.7
    VERY_HIGH = 0.9


# ==============================================================================
# DATA CLASSES
# ==============================================================================

@dataclass
class MemoryEntry:
    """Tekil hafiza kaydi"""
    id: str
    memory_type: MemoryType
    content: Dict[str, Any]
    timestamp: datetime
    confidence: float = 0.5
    source: str = "unknown"
    tags: List[str] = field(default_factory=list)
    related_ids: List[str] = field(default_factory=list)
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    importance_score: float = 0.5  # 0-1, otomatik hesaplanir

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence,
            "source": self.source,
            "tags": self.tags,
            "related_ids": self.related_ids,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "importance_score": self.importance_score
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'MemoryEntry':
        return cls(
            id=data["id"],
            memory_type=MemoryType(data["memory_type"]),
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            confidence=data["confidence"],
            source=data["source"],
            tags=data.get("tags", []),
            related_ids=data.get("related_ids", []),
            access_count=data.get("access_count", 0),
            last_accessed=datetime.fromisoformat(data["last_accessed"]) if data.get("last_accessed") else None,
            importance_score=data.get("importance_score", 0.5)
        )


@dataclass
class TradeEpisode:
    """Bir trade episode'u - acilis, yonetim, kapanis tamami"""
    episode_id: str
    symbol: str
    direction: str  # LONG / SHORT
    entry_price: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    size: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    strategy: str = "unknown"
    signals: List[Dict] = field(default_factory=list)
    market_conditions: Dict = field(default_factory=dict)
    reasoning: str = ""  # Neden bu karar verildi?
    expected_scenario: str = ""  # Beklenen senaryo
    actual_scenario: str = ""  # Gerceklesen senaryo
    emotions: Dict = field(default_factory=dict)  # Confidence, fear, greed
    lessons: List[str] = field(default_factory=list)
    status: str = "open"  # open / closed / cancelled

    def to_dict(self) -> Dict:
        return {
            "episode_id": self.episode_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "exit_price": self.exit_price,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "size": self.size,
            "pnl": self.pnl,
            "pnl_percent": self.pnl_percent,
            "strategy": self.strategy,
            "signals": self.signals,
            "market_conditions": self.market_conditions,
            "reasoning": self.reasoning,
            "expected_scenario": self.expected_scenario,
            "actual_scenario": self.actual_scenario,
            "emotions": self.emotions,
            "lessons": self.lessons,
            "status": self.status
        }


@dataclass
class SemanticConcept:
    """Semantik hafiza - piyasa kavramlari ve iliskileri"""
    concept_id: str
    name: str
    category: str  # asset, indicator, event, regime, etc.
    properties: Dict[str, Any] = field(default_factory=dict)
    relationships: List[Dict] = field(default_factory=list)  # {target, relation, strength}
    definition: str = ""
    examples: List[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> Dict:
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "category": self.category,
            "properties": self.properties,
            "relationships": self.relationships,
            "definition": self.definition,
            "examples": self.examples,
            "confidence": self.confidence
        }


# ==============================================================================
# ATLAS MEMORY CORE
# ==============================================================================

class AtlasMemoryCore:
    """
    Atlas AI'nin birlestirilmis hafiza sistemi.

    Kullanim:
        memory = AtlasMemoryCore()

        # Trade kaydet
        memory.store_trade_episode(episode)

        # Semantik bilgi ekle
        memory.add_concept("bitcoin", "asset", {"type": "cryptocurrency", "layer": "Layer1"})
        memory.add_relationship("bitcoin", "ethereum", "competes_with", 0.8)

        # Hafiza sorgula
        recent_trades = memory.query_trades(symbol="BTCUSDT", limit=10)
        lessons = memory.query_lessons(strategy="RSI", min_pnl=-0.05)

        # Pattern bul
        patterns = memory.find_patterns("bullish_divergence", min_occurrences=3)
    """

    def __init__(self, storage_path: str = "database/memory_core"):
        self.storage_path = storage_path
        self.lock = threading.RLock()

        # Hafiza depolari
        self._short_memory: deque = deque(maxlen=1000)  # Son 1000 anlik kayit
        self._long_memory: Dict[str, MemoryEntry] = {}
        self._semantic_memory: Dict[str, SemanticConcept] = {}
        self._episodes: Dict[str, TradeEpisode] = {}
        self._knowledge_base: Dict[str, Dict] = {}

        # Indeksler
        self._tag_index: Dict[str, List[str]] = defaultdict(list)
        self._symbol_index: Dict[str, List[str]] = defaultdict(list)
        self._strategy_index: Dict[str, List[str]] = defaultdict(list)
        self._time_index: List[Tuple[datetime, str]] = []  # (timestamp, entry_id)

        # Istatistikler
        self.stats = {
            "total_entries": 0,
            "total_episodes": 0,
            "total_concepts": 0,
            "total_lessons": 0,
            "successful_trades": 0,
            "failed_trades": 0,
            "last_updated": datetime.now()
        }

        # Varsayilan piyasa kavramlarini yukle
        self._init_default_concepts()

        print("[MemoryCore] Atlas Memory Core baslatildi")
        print(f"[MemoryCore] Depolama: {storage_path}")

    # ==========================================================================
    # CORE OPERATIONS
    # ==========================================================================

    def store(self, content: Dict, memory_type: MemoryType, 
              source: str = "system", confidence: float = 0.5,
              tags: List[str] = None, related_ids: List[str] = None) -> str:
        """Genel hafiza kaydetme"""
        with self.lock:
            entry_id = self._generate_id(content, memory_type)
            entry = MemoryEntry(
                id=entry_id,
                memory_type=memory_type,
                content=content,
                timestamp=datetime.now(),
                confidence=confidence,
                source=source,
                tags=tags or [],
                related_ids=related_ids or []
            )

            # Importance score hesapla
            entry.importance_score = self._calculate_importance(entry)

            # Depola
            if memory_type == MemoryType.SHORT:
                self._short_memory.append(entry)
            else:
                self._long_memory[entry_id] = entry

            # Indeksle
            self._index_entry(entry)
            self.stats["total_entries"] += 1
            self.stats["last_updated"] = datetime.now()

            return entry_id

    def retrieve(self, entry_id: str) -> Optional[MemoryEntry]:
        """Hafiza kaydi getir"""
        with self.lock:
            # Long memory'de ara
            if entry_id in self._long_memory:
                entry = self._long_memory[entry_id]
                entry.access_count += 1
                entry.last_accessed = datetime.now()
                return entry

            # Short memory'de ara
            for entry in self._short_memory:
                if entry.id == entry_id:
                    entry.access_count += 1
                    entry.last_accessed = datetime.now()
                    return entry

            return None

    def query(self, memory_type: MemoryType = None, 
              tags: List[str] = None, source: str = None,
              min_confidence: float = 0.0, limit: int = 100,
              start_time: datetime = None, end_time: datetime = None) -> List[MemoryEntry]:
        """Hafiza sorgula"""
        with self.lock:
            results = []

            # Long memory'den ara
            for entry in self._long_memory.values():
                if memory_type and entry.memory_type != memory_type:
                    continue
                if tags and not any(t in entry.tags for t in tags):
                    continue
                if source and entry.source != source:
                    continue
                if entry.confidence < min_confidence:
                    continue
                if start_time and entry.timestamp < start_time:
                    continue
                if end_time and entry.timestamp > end_time:
                    continue
                results.append(entry)

            # Short memory'den ara
            for entry in self._short_memory:
                if memory_type and entry.memory_type != memory_type:
                    continue
                if tags and not any(t in entry.tags for t in tags):
                    continue
                if source and entry.source != source:
                    continue
                if entry.confidence < min_confidence:
                    continue
                if start_time and entry.timestamp < start_time:
                    continue
                if end_time and entry.timestamp > end_time:
                    continue
                results.append(entry)

            # Onem skoruna gore sirala
            results.sort(key=lambda x: x.importance_score, reverse=True)
            return results[:limit]

    # ==========================================================================
    # TRADE EPISODE OPERATIONS
    # ==========================================================================

    def store_trade_episode(self, episode: TradeEpisode) -> str:
        """Trade episode'u kaydet"""
        with self.lock:
            self._episodes[episode.episode_id] = episode
            self.stats["total_episodes"] += 1

            if episode.status == "closed":
                if episode.pnl > 0:
                    self.stats["successful_trades"] += 1
                else:
                    self.stats["failed_trades"] += 1

            # Sembol ve strateji indekslerine ekle
            self._symbol_index[episode.symbol].append(episode.episode_id)
            self._strategy_index[episode.strategy].append(episode.episode_id)

            # Long memory'ye de kaydet
            self.store(
                content=episode.to_dict(),
                memory_type=MemoryType.TRADE,
                source="trading",
                tags=["trade", episode.symbol, episode.strategy, episode.status],
                related_ids=[]
            )

            return episode.episode_id

    def get_episode(self, episode_id: str) -> Optional[TradeEpisode]:
        """Episode getir"""
        return self._episodes.get(episode_id)

    def query_trades(self, symbol: str = None, strategy: str = None,
                     status: str = None, min_pnl: float = None,
                     max_pnl: float = None, limit: int = 50) -> List[TradeEpisode]:
        """Trade sorgula"""
        with self.lock:
            results = []

            # Sembol indeksinden basla
            if symbol and symbol in self._symbol_index:
                episode_ids = self._symbol_index[symbol]
            elif strategy and strategy in self._strategy_index:
                episode_ids = self._strategy_index[strategy]
            else:
                episode_ids = list(self._episodes.keys())

            for eid in episode_ids:
                ep = self._episodes[eid]
                if symbol and ep.symbol != symbol:
                    continue
                if strategy and ep.strategy != strategy:
                    continue
                if status and ep.status != status:
                    continue
                if min_pnl is not None and ep.pnl_percent < min_pnl:
                    continue
                if max_pnl is not None and ep.pnl_percent > max_pnl:
                    continue
                results.append(ep)

            # Zamana gore sirala (en yeni once)
            results.sort(key=lambda x: x.entry_time, reverse=True)
            return results[:limit]

    def query_lessons(self, strategy: str = None, min_pnl: float = None,
                      tag: str = None, limit: int = 20) -> List[Dict]:
        """Ogrenilen dersleri sorgula"""
        lessons = []
        trades = self.query_trades(strategy=strategy, min_pnl=min_pnl, limit=limit * 2)

        for trade in trades:
            for lesson in trade.lessons:
                lessons.append({
                    "lesson": lesson,
                    "symbol": trade.symbol,
                    "strategy": trade.strategy,
                    "pnl": trade.pnl_percent,
                    "timestamp": trade.exit_time or trade.entry_time,
                    "episode_id": trade.episode_id
                })

        return lessons[:limit]

    def get_trade_stats(self, symbol: str = None, strategy: str = None) -> Dict:
        """Trade istatistikleri"""
        trades = self.query_trades(symbol=symbol, strategy=strategy, status="closed")

        if not trades:
            return {"count": 0, "win_rate": 0, "avg_pnl": 0, "total_pnl": 0}

        wins = sum(1 for t in trades if t.pnl > 0)
        total_pnl = sum(t.pnl_percent for t in trades)

        return {
            "count": len(trades),
            "win_rate": wins / len(trades),
            "avg_pnl": total_pnl / len(trades),
            "total_pnl": total_pnl,
            "best_trade": max(trades, key=lambda x: x.pnl_percent).pnl_percent,
            "worst_trade": min(trades, key=lambda x: x.pnl_percent).pnl_percent,
            "avg_holding_time": self._avg_holding_time(trades)
        }

    # ==========================================================================
    # SEMANTIC MEMORY OPERATIONS
    # ==========================================================================

    def add_concept(self, name: str, category: str, 
                    properties: Dict = None, definition: str = "",
                    confidence: float = 0.5) -> str:
        """Yeni kavram ekle"""
        with self.lock:
            concept_id = f"concept_{name.lower().replace(' ', '_')}"
            concept = SemanticConcept(
                concept_id=concept_id,
                name=name,
                category=category,
                properties=properties or {},
                definition=definition,
                confidence=confidence
            )
            self._semantic_memory[concept_id] = concept
            self.stats["total_concepts"] += 1
            return concept_id

    def add_relationship(self, from_concept: str, to_concept: str,
                         relation: str, strength: float = 0.5) -> bool:
        """Kavumlar arasi iliski ekle"""
        with self.lock:
            from_id = f"concept_{from_concept.lower().replace(' ', '_')}"
            to_id = f"concept_{to_concept.lower().replace(' ', '_')}"

            if from_id not in self._semantic_memory:
                return False

            self._semantic_memory[from_id].relationships.append({
                "target": to_concept,
                "target_id": to_id,
                "relation": relation,
                "strength": strength
            })
            return True

    def get_concept(self, name: str) -> Optional[SemanticConcept]:
        """Kavram getir"""
        concept_id = f"concept_{name.lower().replace(' ', '_')}"
        return self._semantic_memory.get(concept_id)

    def query_concepts(self, category: str = None, 
                       min_confidence: float = 0.0) -> List[SemanticConcept]:
        """Kavram sorgula"""
        results = []
        for concept in self._semantic_memory.values():
            if category and concept.category != category:
                continue
            if concept.confidence < min_confidence:
                continue
            results.append(concept)
        return results

    def get_related_concepts(self, name: str, relation_type: str = None) -> List[Dict]:
        """Iliskili kavramlari getir"""
        concept = self.get_concept(name)
        if not concept:
            return []

        if relation_type:
            return [r for r in concept.relationships if r["relation"] == relation_type]
        return concept.relationships

    # ==========================================================================
    # PATTERN & LEARNING OPERATIONS
    # ==========================================================================

    def find_patterns(self, pattern_name: str = None, 
                      min_occurrences: int = 3,
                      min_confidence: float = 0.6) -> List[Dict]:
        """Tekrarlayan pattern'leri bul"""
        patterns = defaultdict(lambda: {"count": 0, "examples": [], "avg_pnl": []})

        trades = self.query_trades(status="closed", limit=1000)

        for trade in trades:
            # Sinyal pattern'lerini analiz et
            for signal in trade.signals:
                pattern_key = signal.get("pattern", signal.get("name", "unknown"))
                if pattern_name and pattern_key != pattern_name:
                    continue

                patterns[pattern_key]["count"] += 1
                patterns[pattern_key]["examples"].append(trade.episode_id)
                patterns[pattern_key]["avg_pnl"].append(trade.pnl_percent)

        # Filtrele ve sonuclari hazirla
        results = []
        for pattern, data in patterns.items():
            if data["count"] >= min_occurrences:
                avg_pnl = np.mean(data["avg_pnl"]) if data["avg_pnl"] else 0
                win_rate = sum(1 for p in data["avg_pnl"] if p > 0) / len(data["avg_pnl"]) if data["avg_pnl"] else 0

                if win_rate >= min_confidence:
                    results.append({
                        "pattern": pattern,
                        "occurrences": data["count"],
                        "win_rate": win_rate,
                        "avg_pnl": avg_pnl,
                        "examples": data["examples"][:5]
                    })

        return sorted(results, key=lambda x: x["avg_pnl"], reverse=True)

    def get_market_regime_memory(self, regime: str = None, 
                                  limit: int = 50) -> List[Dict]:
        """Piyasa rejimi hafizasi"""
        entries = self.query(
            memory_type=MemoryType.KNOWLEDGE,
            tags=["regime"] + ([regime] if regime else []),
            limit=limit
        )
        return [e.to_dict() for e in entries]

    def store_knowledge(self, topic: str, content: Dict,
                        confidence: float = 0.5, source: str = "system") -> str:
        """Bilgi kaydet"""
        return self.store(
            content={"topic": topic, **content},
            memory_type=MemoryType.KNOWLEDGE,
            source=source,
            confidence=confidence,
            tags=["knowledge", topic]
        )

    # ==========================================================================
    # SHORT-TERM WORKING MEMORY
    # ==========================================================================

    def working_memory_add(self, content: Dict, source: str = "system") -> str:
        """Anlik calisma hafizasina ekle"""
        return self.store(
            content=content,
            memory_type=MemoryType.SHORT,
            source=source,
            tags=["working"]
        )

    def working_memory_get_recent(self, n: int = 10) -> List[MemoryEntry]:
        """Son n anlik kaydi getir"""
        return list(self._short_memory)[-n:]

    def working_memory_clear(self):
        """Anlik hafizayi temizle"""
        self._short_memory.clear()

    # ==========================================================================
    # PERSISTENCE
    # ==========================================================================

    def save(self, filepath: str = None):
        """Hafizayi diske kaydet"""
        filepath = filepath or f"{self.storage_path}/memory_core.pkl"
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with self.lock:
            data = {
                "long_memory": {k: v.to_dict() for k, v in self._long_memory.items()},
                "semantic_memory": {k: v.to_dict() for k, v in self._semantic_memory.items()},
                "episodes": {k: v.to_dict() for k, v in self._episodes.items()},
                "stats": self.stats,
                "tag_index": dict(self._tag_index),
                "symbol_index": dict(self._symbol_index),
                "strategy_index": dict(self._strategy_index)
            }

            with open(filepath, 'wb') as f:
                pickle.dump(data, f)

        print(f"[MemoryCore] Hafiza kaydedildi: {filepath}")

    def load(self, filepath: str = None):
        """Hafizayi diskten yukle"""
        filepath = filepath or f"{self.storage_path}/memory_core.pkl"

        if not os.path.exists(filepath):
            print(f"[MemoryCore] Kayit bulunamadi: {filepath}")
            return False

        with self.lock:
            with open(filepath, 'rb') as f:
                data = pickle.load(f)

            self._long_memory = {
                k: MemoryEntry.from_dict(v) for k, v in data["long_memory"].items()
            }
            self._episodes = {
                k: TradeEpisode(**v) for k, v in data["episodes"].items()
            }
            self.stats = data["stats"]
            self._tag_index = defaultdict(list, data["tag_index"])
            self._symbol_index = defaultdict(list, data["symbol_index"])
            self._strategy_index = defaultdict(list, data["strategy_index"])

        print(f"[MemoryCore] Hafiza yuklendi: {filepath}")
        print(f"[MemoryCore] {self.stats['total_entries']} kayit, {self.stats['total_episodes']} episode")
        return True

    # ==========================================================================
    # INTERNAL METHODS
    # ==========================================================================

    def _generate_id(self, content: Dict, memory_type: MemoryType) -> str:
        """Benzersiz ID uret"""
        content_str = json.dumps(content, sort_keys=True, default=str)
        hash_input = f"{memory_type.value}_{content_str}_{datetime.now().isoformat()}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:16]

    def _calculate_importance(self, entry: MemoryEntry) -> float:
        """Kaydin onem skorunu hesapla"""
        score = entry.confidence

        # Trade kayitlari daha onemli
        if entry.memory_type == MemoryType.TRADE:
            score += 0.2

        # Knowledge kayitlari onemli
        if entry.memory_type == MemoryType.KNOWLEDGE:
            score += 0.15

        # Daha cok erisilen kayitlar onemli
        if entry.access_count > 5:
            score += 0.1

        # Yeni kayitlar biraz daha onemli (recency bias)
        age_hours = (datetime.now() - entry.timestamp).total_seconds() / 3600
        if age_hours < 24:
            score += 0.1

        return min(score, 1.0)

    def _index_entry(self, entry: MemoryEntry):
        """Kaydi indeksle"""
        # Tag indeksi
        for tag in entry.tags:
            self._tag_index[tag].append(entry.id)

        # Zaman indeksi
        self._time_index.append((entry.timestamp, entry.id))
        self._time_index.sort()

    def _init_default_concepts(self):
        """Varsayilan piyasa kavramlarini yukle"""
        defaults = [
            ("bitcoin", "asset", {"type": "cryptocurrency", "layer": "Layer1", "dominance": True}, "Ilk ve en buyuk kripto para"),
            ("ethereum", "asset", {"type": "cryptocurrency", "layer": "Layer1", "smart_contract": True}, "Akilli sozlesme platformu"),
            ("solana", "asset", {"type": "cryptocurrency", "layer": "Layer1", "high_tps": True}, "Yuksek hizli Layer1"),
            ("fed", "entity", {"type": "central_bank", "country": "USA"}, "ABD Merkez Bankasi"),
            ("dxy", "indicator", {"type": "index", "full_name": "US Dollar Index"}, "Dolar endeksi"),
            ("etf", "instrument", {"type": "fund", "crypto_related": True}, "Borsada islem goren fon"),
            ("bull_market", "regime", {"sentiment": "positive", "trend": "up"}, "Yukselis piyasasi"),
            ("bear_market", "regime", {"sentiment": "negative", "trend": "down"}, "Dusus piyasasi"),
            ("altcoin_season", "regime", {"dominance": "low", "altcoin_performance": "high"}, "Altcoinlerin BTC'den iyi performans gosterdigi donem"),
        ]

        for name, category, props, definition in defaults:
            self.add_concept(name, category, props, definition, confidence=0.9)

        # Iliskiler
        relationships = [
            ("bitcoin", "ethereum", "dominates", 0.7),
            ("ethereum", "solana", "competes_with", 0.8),
            ("fed", "dxy", "influences", 0.9),
            ("dxy", "bitcoin", "negatively_correlates", 0.6),
            ("etf", "bitcoin", "increases_demand", 0.8),
            ("bull_market", "altcoin_season", "enables", 0.7),
        ]

        for from_c, to_c, rel, strength in relationships:
            self.add_relationship(from_c, to_c, rel, strength)

    def _avg_holding_time(self, trades: List[TradeEpisode]) -> float:
        """Ortalama tutma suresi (saat)"""
        durations = []
        for t in trades:
            if t.exit_time and t.entry_time:
                duration = (t.exit_time - t.entry_time).total_seconds() / 3600
                durations.append(duration)
        return np.mean(durations) if durations else 0

    # ==========================================================================
    # REPORTING
    # ==========================================================================

    def get_summary(self) -> Dict:
        """Hafiza ozeti"""
        return {
            "total_entries": self.stats["total_entries"],
            "total_episodes": self.stats["total_episodes"],
            "total_concepts": self.stats["total_concepts"],
            "successful_trades": self.stats["successful_trades"],
            "failed_trades": self.stats["failed_trades"],
            "win_rate": self.stats["successful_trades"] / max(self.stats["total_episodes"], 1),
            "short_memory_size": len(self._short_memory),
            "long_memory_size": len(self._long_memory),
            "semantic_concepts": len(self._semantic_memory),
            "indexed_symbols": list(self._symbol_index.keys()),
            "indexed_strategies": list(self._strategy_index.keys()),
            "last_updated": self.stats["last_updated"].isoformat()
        }

    def print_summary(self):
        """Hafiza ozetini yazdir"""
        summary = self.get_summary()
        print("\n" + "="*60)
        print("ATLAS AI - MEMORY CORE OZETI")
        print("="*60)
        print(f"Toplam Kayit:        {summary['total_entries']}")
        print(f"Toplam Episode:      {summary['total_episodes']}")
        print(f"Basarili Trade:      {summary['successful_trades']}")
        print(f"Basarisiz Trade:     {summary['failed_trades']}")
        print(f"Win Rate:            {summary['win_rate']:.1%}")
        print(f"Anlik Hafiza:        {summary['short_memory_size']} kayit")
        print(f"Uzun Hafiza:         {summary['long_memory_size']} kayit")
        print(f"Semantik Kavram:     {summary['semantic_concepts']} adet")
        print(f"Indekslenmis Sembol: {', '.join(summary['indexed_symbols'][:5])}")
        print(f"Indekslenmis Strateji: {', '.join(summary['indexed_strategies'][:5])}")
        print("="*60)


# ==============================================================================
# TEST
# ==============================================================================

if __name__ == "__main__":
    print("="*70)
    print("ATLAS AI - MEMORY CORE TEST")
    print("="*70)

    # Memory Core olustur
    memory = AtlasMemoryCore()

    # 1. Varsayilan kavramlari kontrol et
    print("\n[TEST 1] Varsayilan kavramlar...")
    btc = memory.get_concept("bitcoin")
    print(f"   Bitcoin: {btc.name} ({btc.category})")
    print(f"   Properties: {btc.properties}")

    related = memory.get_related_concepts("bitcoin")
    print(f"   Iliskiler: {len(related)} adet")
    for r in related:
        print(f"      → {r['target']}: {r['relation']} (guc: {r['strength']})")

    # 2. Trade episode kaydet
    print("\n[TEST 2] Trade episode kaydetme...")
    episode = TradeEpisode(
        episode_id="ep_001",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=64700.0,
        entry_time=datetime.now(),
        size=0.1,
        strategy="RSI_Oversold",
        signals=[
            {"name": "RSI", "value": 28, "threshold": 30, "signal": "oversold"},
            {"name": "MACD", "value": -0.5, "signal": "bullish_cross"}
        ],
        market_conditions={
            "dominance": 52.3,
            "funding_rate": 0.01,
            "volatility": "medium"
        },
        reasoning="RSI 28 (oversold) + MACD bullish cross. BTC dominance yuksek, altcoinler zayif. BTC guvenli liman.",
        expected_scenario="RSI 50'ye donus, %3-5 yukselis",
        emotions={"confidence": 0.75, "fear": 0.2, "greed": 0.3}
    )

    memory.store_trade_episode(episode)
    print(f"   Episode kaydedildi: {episode.episode_id}")

    # 3. Episode'u kapat ve ders ekle
    print("\n[TEST 3] Episode kapatma ve ders ekleme...")
    episode.exit_price = 66500.0
    episode.exit_time = datetime.now()
    episode.pnl = (episode.exit_price - episode.entry_price) * episode.size
    episode.pnl_percent = (episode.exit_price - episode.entry_price) / episode.entry_price * 100
    episode.status = "closed"
    episode.actual_scenario = "RSI 55'e dondu, %2.8 yukselis. Beklenenden dusuk ama karli."
    episode.lessons = [
        "RSI 28'den donus guclu sinyal",
        "BTC dominance > 50 iken BTC LONG daha guvenli",
        "MACD cross oncesi giris daha iyi olabilirdi"
    ]

    print(f"   PnL: ${episode.pnl:.2f} ({episode.pnl_percent:.2f}%)")
    print(f"   Dersler: {len(episode.lessons)} adet")
    for lesson in episode.lessons:
        print(f"      → {lesson}")

    # 4. Bilgi kaydet
    print("\n[TEST 4] Bilgi kaydetme...")
    memory.store_knowledge(
        topic="btc_dominance_strategy",
        content={
            "finding": "BTC dominance > 50 iken BTC LONG, altcoin SHORT daha basarili",
            "evidence": 15,
            "win_rate": 0.73,
            "avg_return": 0.042
        },
        confidence=0.73,
        source="trade_analysis"
    )
    print("   Bilgi kaydedildi: btc_dominance_strategy")

    # 5. Pattern bul
    print("\n[TEST 5] Pattern analizi...")
    # Birkaç daha episode ekle
    for i in range(5):
        ep = TradeEpisode(
            episode_id=f"ep_{i+2:03d}",
            symbol="ETHUSDT",
            direction="LONG",
            entry_price=3500.0,
            entry_time=datetime.now(),
            exit_price=3600.0 if i % 2 == 0 else 3400.0,
            exit_time=datetime.now(),
            size=0.5,
            pnl=(100.0 if i % 2 == 0 else -100.0),
            pnl_percent=(2.86 if i % 2 == 0 else -2.86),
            strategy="EMA_Cross",
            signals=[{"name": "EMA_Cross", "value": "bullish", "pattern": "golden_cross"}],
            status="closed",
            lessons=["Golden cross guclu trend sinyali"] if i % 2 == 0 else ["False breakout, trend zayif"]
        )
        memory.store_trade_episode(ep)

    patterns = memory.find_patterns(min_occurrences=2)
    print(f"   Bulunan pattern'ler: {len(patterns)}")
    for p in patterns:
        print(f"      → {p['pattern']}: {p['occurrences']} kez, Win Rate: {p['win_rate']:.1%}, Avg PnL: {p['avg_pnl']:.2f}%")

    # 6. Ders sorgula
    print("\n[TEST 6] Ders sorgulama...")
    lessons = memory.query_lessons(limit=5)
    print(f"   Toplam ders: {len(lessons)}")
    for lesson in lessons[:3]:
        print(f"      → [{lesson['symbol']}] {lesson['lesson']}")

    # 7. Istatistikler
    print("\n[TEST 7] Istatistikler...")
    stats = memory.get_trade_stats()
    print(f"   Toplam Trade: {stats['count']}")
    print(f"   Win Rate: {stats['win_rate']:.1%}")
    print(f"   Ortalama PnL: {stats['avg_pnl']:.2f}%")

    # 8. Ozet
    print("\n[TEST 8] Genel ozet...")
    memory.print_summary()

    # 9. Kaydet ve yukle
    print("\n[TEST 9] Persistence test...")
    memory.save("database/test_memory_core.pkl")

    memory2 = AtlasMemoryCore()
    memory2.load("database/test_memory_core.pkl")
    memory2.print_summary()

    print("\n" + "="*70)
    print("TUM TESTLER BASARILI!")
    print("="*70)