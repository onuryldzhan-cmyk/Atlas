"""ATLAS MEMORY CORE v2.0 - Geliştirilmiş Hafıza Sistemi"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any
from enum import Enum
import json
import os

class TradeOutcome(Enum):
    WIN = "win"
    LOSS = "loss"
    NEUTRAL = "neutral"

@dataclass
class TradeRecord:
    symbol: str
    entry_price: float
    exit_price: Optional[float] = None
    position_size: float = 0.0
    return_pct: float = 0.0
    outcome: TradeOutcome = TradeOutcome.NEUTRAL
    strategy: str = ""
    tags: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    exit_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "position_size": self.position_size,
            "return_pct": self.return_pct,
            "outcome": self.outcome.value,
            "strategy": self.strategy,
            "tags": self.tags,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "TradeRecord":
        record = cls(
            symbol=data["symbol"],
            entry_price=data["entry_price"],
            exit_price=data.get("exit_price"),
            position_size=data.get("position_size", 0.0),
            return_pct=data.get("return_pct", 0.0),
            outcome=TradeOutcome(data.get("outcome", "neutral")),
            strategy=data.get("strategy", ""),
            tags=data.get("tags", [])
        )
        if data.get("timestamp"):
            record.timestamp = datetime.fromisoformat(data["timestamp"])
        if data.get("exit_time"):
            record.exit_time = datetime.fromisoformat(data["exit_time"])
        return record

@dataclass
class MarketEpisode:
    episode_id: str
    trades: List[TradeRecord] = field(default_factory=list)
    market_context: Dict = field(default_factory=dict)
    outcome: TradeOutcome = TradeOutcome.NEUTRAL
    tags: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "episode_id": self.episode_id,
            "trades": [t.to_dict() for t in self.trades],
            "market_context": self.market_context,
            "outcome": self.outcome.value,
            "tags": self.tags,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MarketEpisode":
        episode = cls(
            episode_id=data["episode_id"],
            trades=[TradeRecord.from_dict(t) for t in data.get("trades", [])],
            market_context=data.get("market_context", {}),
            outcome=TradeOutcome(data.get("outcome", "neutral")),
            tags=data.get("tags", [])
        )
        if data.get("timestamp"):
            episode.timestamp = datetime.fromisoformat(data["timestamp"])
        return episode

class AtlasMemoryCore:
    def __init__(self, data_dir: str = "memory_data"):
        self.trades: List[TradeRecord] = []
        self.episodes: List[MarketEpisode] = []
        self.semantic_memory: Dict[str, Any] = {}
        self.data_dir = data_dir
        self._ensure_data_dir()
        print("[MEMORY] Atlas Memory Core v2.0 baslatildi")
    
    def _ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            print(f"[MEMORY] Veri dizini olusturuldu: {self.data_dir}")
    
    def record_trade(self, symbol: str, entry_price: float, position_size: float,
                     strategy: str = "", tags: List[str] = None) -> TradeRecord:
        trade = TradeRecord(
            symbol=symbol,
            entry_price=entry_price,
            position_size=position_size,
            strategy=strategy,
            tags=tags or []
        )
        self.trades.append(trade)
        print(f"[MEMORY] Trade kaydedildi: {symbol} @ {entry_price} ({strategy})")
        return trade
    
    def update_trade_outcome(self, symbol: str, exit_price: float,
                             return_pct: float, outcome: TradeOutcome) -> bool:
        for trade in reversed(self.trades):
            if trade.symbol == symbol and trade.exit_price is None:
                trade.exit_price = exit_price
                trade.return_pct = return_pct
                trade.outcome = outcome
                trade.exit_time = datetime.now()
                print(f"[MEMORY] Trade sonuclandi: {symbol} -> {outcome.value} ({return_pct:+.2f}%)")
                return True
        print(f"[MEMORY] UYARI: Acik trade bulunamadi: {symbol}")
        return False
    
    def create_episode(self, episode_id: str, tags: List[str] = None) -> MarketEpisode:
        episode = MarketEpisode(episode_id=episode_id, tags=tags or [])
        self.episodes.append(episode)
        print(f"[MEMORY] Episode olusturuldu: {episode_id}")
        return episode
    
    def add_trade_to_episode(self, episode_id: str, trade: TradeRecord) -> bool:
        for episode in self.episodes:
            if episode.episode_id == episode_id:
                episode.trades.append(trade)
                return True
        return False
    
    def get_win_rate(self, strategy: str = None) -> float:
        trades = self.trades
        if strategy:
            trades = [t for t in trades if t.strategy == strategy]
        if not trades:
            return 0.0
        wins = len([t for t in trades if t.outcome == TradeOutcome.WIN])
        return (wins / len(trades)) * 100
    
    def get_avg_return(self, strategy: str = None) -> float:
        trades = [t for t in self.trades if t.exit_price is not None]
        if strategy:
            trades = [t for t in trades if t.strategy == strategy]
        if not trades:
            return 0.0
        return sum(t.return_pct for t in trades) / len(trades)
    
    def get_stats(self) -> Dict:
        closed_trades = [t for t in self.trades if t.exit_price is not None]
        wins = len([t for t in closed_trades if t.outcome == TradeOutcome.WIN])
        losses = len([t for t in closed_trades if t.outcome == TradeOutcome.LOSS])
        
        return {
            "total_trades": len(self.trades),
            "closed_trades": len(closed_trades),
            "open_trades": len(self.trades) - len(closed_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": self.get_win_rate(),
            "avg_return": self.get_avg_return(),
            "total_return": sum(t.return_pct for t in closed_trades),
            "episodes": len(self.episodes)
        }
    
    def save(self, filepath: str = None):
        if filepath is None:
            filepath = os.path.join(self.data_dir, "atlas_memory.json")
        
        data = {
            "trades": [t.to_dict() for t in self.trades],
            "episodes": [e.to_dict() for e in self.episodes],
            "semantic_memory": self.semantic_memory,
            "saved_at": datetime.now().isoformat()
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[MEMORY] Kaydedildi: {filepath} ({len(self.trades)} trade, {len(self.episodes)} episode)")
    
    def load(self, filepath: str = None):
        if filepath is None:
            filepath = os.path.join(self.data_dir, "atlas_memory.json")
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.trades = [TradeRecord.from_dict(t) for t in data.get("trades", [])]
            self.episodes = [MarketEpisode.from_dict(e) for e in data.get("episodes", [])]
            self.semantic_memory = data.get("semantic_memory", {})
            
            print(f"[MEMORY] Yuklendi: {filepath} ({len(self.trades)} trade, {len(self.episodes)} episode)")
            return True
        except FileNotFoundError:
            print(f"[MEMORY] Dosya bulunamadi, yeni hafiza baslatiliyor: {filepath}")
            return False
        except Exception as e:
            print(f"[MEMORY] YUKLEME HATASI: {e}")
            return False
    
    def print_stats(self):
        stats = self.get_stats()
        print("-" * 50)
        print("ATLAS MEMORY CORE - ISTATISTIKLER")
        print("-" * 50)
        print(f"Toplam Trade:     {stats["total_trades"]}")
        print(f"Kapali Trade:     {stats["closed_trades"]}")
        print(f"Acik Trade:       {stats["open_trades"]}")
        print(f"Kazanilan:        {stats["wins"]}")
        print(f"Kaybedilen:       {stats["losses"]}")
        print(f"Win Rate:         {stats["win_rate"]:.1f}%")
        print(f"Ort. Getiri:      {stats["avg_return"]:+.2f}%")
        print(f"Toplam Getiri:    {stats["total_return"]:+.2f}%")
        print(f"Episode Sayisi:   {stats["episodes"]}")
        print("-" * 50)


# ========== TEST BOLUMU ==========
if __name__ == "__main__":
    print("-" * 60)
    print("ATLAS MEMORY CORE v2.0 - TEST")
    print("-" * 60)
    
    memory = AtlasMemoryCore()
    
    # Test 1: Trade kaydetme
    print("[TEST 1] Trade kaydetme...")
    memory.record_trade("BTCUSDT", 65000, 0.5, "RSI_Strategy", ["bullish", "momentum"])
    memory.record_trade("ETHUSDT", 3500, 1.0, "MACD_Strategy", ["trend"])
    memory.record_trade("SOLUSDT", 150, 2.0, "RSI_Strategy", ["breakout"])
    
    # Test 2: Trade sonuclandirma
    print("[TEST 2] Trade sonuclandirma...")
    memory.update_trade_outcome("BTCUSDT", 67000, 3.08, TradeOutcome.WIN)
    memory.update_trade_outcome("ETHUSDT", 3400, -2.86, TradeOutcome.LOSS)
    memory.update_trade_outcome("SOLUSDT", 165, 10.0, TradeOutcome.WIN)
    
    # Test 3: Episode olusturma
    print("[TEST 3] Episode olusturma...")
    ep = memory.create_episode("bull_run_2024", ["bull_market", "q1"])
    
    # Test 4: Istatistikler
    print("[TEST 4] Istatistikler...")
    memory.print_stats()
    
    # Test 5: Kaydetme
    print("[TEST 5] Kaydetme...")
    memory.save()
    
    # Test 6: Yeni instance ile yukleme
    print("[TEST 6] Yukleme testi...")
    memory2 = AtlasMemoryCore()
    memory2.load()
    memory2.print_stats()
    
    print("-" * 60)
    print("TUM TESTLER BASARILI!")
    print("-" * 60)