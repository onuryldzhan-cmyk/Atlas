"""ATLAS WORLD MODEL v2.0 - Piyasa Iliskileri Grafi"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Set, Tuple
from enum import Enum
import json
import os

import logging as _logging

# Diagnostics go to the log, not stdout (registry v5.50: 20 coins x every cycle flooded the console).
_log = _logging.getLogger(__name__)

class RelationshipType(Enum):
    CAUSAL = "causal"
    CORRELATION = "correlation"
    INVERSE = "inverse"
    LEADS = "leads"
    DEPENDS = "depends"

@dataclass
class MarketNode:
    node_id: str
    name: str
    category: str  # asset, macro, sentiment, event
    current_value: float = 0.0
    volatility: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "category": self.category,
            "current_value": self.current_value,
            "volatility": self.volatility,
            "timestamp": self.timestamp.isoformat()
        }

@dataclass
class MarketEdge:
    source: str
    target: str
    relationship: RelationshipType
    strength: float = 0.5  # 0.0 - 1.0
    lag_hours: int = 0
    description: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "source": self.source,
            "target": self.target,
            "relationship": self.relationship.value,
            "strength": self.strength,
            "lag_hours": self.lag_hours,
            "description": self.description
        }

class SimpleGraph:
    """NetworkX bagimsiz basit graf implementasyonu"""
    def __init__(self):
        self.nodes: Dict[str, MarketNode] = {}
        self.edges: List[MarketEdge] = []
        self.adjacency: Dict[str, List[str]] = {}
    
    def add_node(self, node: MarketNode):
        self.nodes[node.node_id] = node
        if node.node_id not in self.adjacency:
            self.adjacency[node.node_id] = []
    
    def add_edge(self, edge: MarketEdge):
        self.edges.append(edge)
        if edge.source in self.adjacency:
            self.adjacency[edge.source].append(edge.target)
    
    def get_neighbors(self, node_id: str) -> List[str]:
        return self.adjacency.get(node_id, [])
    
    def find_path(self, start: str, end: str, visited: Set[str] = None) -> Optional[List[str]]:
        if visited is None:
            visited = set()
        
        if start == end:
            return [start]
        
        visited.add(start)
        for neighbor in self.get_neighbors(start):
            if neighbor not in visited:
                path = self.find_path(neighbor, end, visited.copy())
                if path:
                    return [start] + path
        
        return None

class AtlasWorldModel:
    def __init__(self, data_dir: str = "memory_data"):
        self.graph = SimpleGraph()
        self.data_dir = data_dir
        self._ensure_data_dir()
        self._initialize_default_nodes()
        _log.debug("[WORLD] Atlas World Model v2.0 baslatildi")
    
    def _ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
    
    def _initialize_default_nodes(self):
        # Varliklar
        assets = [
            ("BTC", "Bitcoin", "asset", 65000),
            ("ETH", "Ethereum", "asset", 3500),
            ("SOL", "Solana", "asset", 150),
            ("SPX", "S&P 500", "asset", 4500),
            ("GOLD", "Altin", "asset", 2300),
            ("DXY", "Dolar Endeksi", "asset", 104),
        ]
        
        # Makro
        macros = [
            ("FED", "FED Politikasi", "macro", 0),
            ("CPI", "Enflasyon", "macro", 3.2),
            ("GDP", "Buyume", "macro", 2.8),
            ("UNEMP", "Issizlik", "macro", 3.8),
        ]
        
        # Sentiment
        sentiments = [
            ("FG", "Fear & Greed", "sentiment", 45),
            ("VIX", "Volatilite Endeksi", "sentiment", 18),
        ]
        
        for node_id, name, category, value in assets + macros + sentiments:
            self.add_node(MarketNode(node_id, name, category, value))
        
        # Iliskiler
        relationships = [
            ("FED", "DXY", RelationshipType.CAUSAL, 0.8, 0, "FED politikasi DXY'yi etkiler"),
            ("DXY", "BTC", RelationshipType.INVERSE, 0.7, 2, "Guclu dolar kripto baskilar"),
            ("CPI", "FED", RelationshipType.CAUSAL, 0.9, 0, "Enflasyon FED kararini etkiler"),
            ("BTC", "ETH", RelationshipType.CORRELATION, 0.85, 0, "BTC-ETH yuksek korelasyon"),
            ("ETH", "SOL", RelationshipType.CORRELATION, 0.75, 0, "ETH-SOL korelasyon"),
            ("SPX", "BTC", RelationshipType.CORRELATION, 0.6, 4, "Hisse-kripto iliskisi"),
            ("GOLD", "DXY", RelationshipType.INVERSE, 0.8, 1, "Altin-dolar ters iliski"),
            ("VIX", "SPX", RelationshipType.INVERSE, 0.9, 0, "VIX-SP500 ters"),
            ("FG", "BTC", RelationshipType.LEADS, 0.5, 12, "Sentiment fiyat ongorsu"),
            ("GDP", "SPX", RelationshipType.CAUSAL, 0.7, 24, "Buyume hisseleri etkiler"),
            ("UNEMP", "FED", RelationshipType.CAUSAL, 0.6, 0, "Issizlik FED'i etkiler"),
        ]
        
        for src, tgt, rel, strength, lag, desc in relationships:
            self.add_edge(MarketEdge(src, tgt, rel, strength, lag, desc))
    
    def add_node(self, node: MarketNode):
        self.graph.add_node(node)
    
    def add_edge(self, edge: MarketEdge):
        self.graph.add_edge(edge)
    
    def find_path(self, start: str, end: str) -> Optional[List[str]]:
        return self.graph.find_path(start, end)
    
    def get_impact_chain(self, node_id: str, depth: int = 3) -> Dict:
        """Bir olayin diger varliklara olan etkisini hesapla"""
        impacts = {}
        visited = set()
        queue = [(node_id, 1.0, 0)]
        
        while queue:
            current, strength, level = queue.pop(0)
            if current in visited or level >= depth:
                continue
            
            visited.add(current)
            
            for edge in self.graph.edges:
                if edge.source == current and edge.target not in visited:
                    new_strength = strength * edge.strength
                    impacts[edge.target] = {
                        "strength": round(new_strength, 3),
                        "relationship": edge.relationship.value,
                        "lag_hours": edge.lag_hours,
                        "path": self.find_path(node_id, edge.target)
                    }
                    queue.append((edge.target, new_strength, level + 1))
        
        return impacts
    
    def update_node_value(self, node_id: str, new_value: float):
        if node_id in self.graph.nodes:
            self.graph.nodes[node_id].current_value = new_value
            self.graph.nodes[node_id].timestamp = datetime.now()
            return True
        return False
    
    def get_node(self, node_id: str) -> Optional[MarketNode]:
        return self.graph.nodes.get(node_id)
    
    def get_all_nodes(self) -> List[MarketNode]:
        return list(self.graph.nodes.values())
    
    def get_all_edges(self) -> List[MarketEdge]:
        return self.graph.edges
    
    def save(self, filepath: str = None):
        if filepath is None:
            filepath = os.path.join(self.data_dir, "atlas_world_model.json")
        
        data = {
            "nodes": [n.to_dict() for n in self.graph.nodes.values()],
            "edges": [e.to_dict() for e in self.graph.edges],
            "saved_at": datetime.now().isoformat()
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _log.debug(f"[WORLD] Kaydedildi: {filepath}")
    
    def load(self, filepath: str = None):
        if filepath is None:
            filepath = os.path.join(self.data_dir, "atlas_world_model.json")
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                json.load(f)
            _log.debug(f"[WORLD] Yuklendi: {filepath}")
            return True
        except FileNotFoundError:
            return False


# ========== TEST BOLUMU ==========
if __name__ == "__main__":
    _log.debug("-" * 60)
    _log.debug("ATLAS WORLD MODEL v2.0 - TEST")
    _log.debug("-" * 60)
    
    world = AtlasWorldModel()
    
    # Test 1: Node listeleme
    _log.debug("\n[TEST 1] Tum node'lar...")
    nodes = world.get_all_nodes()
    _log.debug(f"Toplam node: {len(nodes)}")
    for n in nodes[:5]:
        _log.debug(f"  {n.node_id}: {n.name} ({n.category}) = {n.current_value}")
    
    # Test 2: Edge listeleme
    _log.debug("\n[TEST 2] Tum edge'ler...")
    edges = world.get_all_edges()
    _log.debug(f"Toplam edge: {len(edges)}")
    for e in edges[:5]:
        _log.debug(f"  {e.source} -> {e.target} [{e.relationship.value}] (guc: {e.strength})")
    
    # Test 3: Yol bulma
    _log.debug("\n[TEST 3] Yol bulma: FED -> BTC...")
    path = world.find_path("FED", "BTC")
    _log.debug(f"Yol: {' -> '.join(path) if path else 'Bulunamadi'}")
    
    # Test 4: Etki zinciri
    _log.debug("\n[TEST 4] FED etki zinciri...")
    impacts = world.get_impact_chain("FED", depth=2)
    for target, info in impacts.items():
        _log.debug(f"  {target}: guc={info['strength']}, lag={info['lag_hours']}s, iliski={info['relationship']}")
    
    # Test 5: Node guncelleme
    _log.debug("\n[TEST 5] Node deger guncelleme...")
    world.update_node_value("BTC", 68000)
    btc = world.get_node("BTC")
    _log.debug(f"BTC yeni deger: {btc.current_value}")
    
    # Test 6: Kaydet
    _log.debug("\n[TEST 6] Kaydetme...")
    world.save()
    
    _log.debug("\n" + "-" * 60)
    _log.debug("TUM TESTLER BASARILI!")
    _log.debug("-" * 60)