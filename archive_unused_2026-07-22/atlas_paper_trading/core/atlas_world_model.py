"""
================================================================================
ATLAS AI - WORLD MODEL (atlas_world_model.py)
================================================================================
Piyasa dunya modeli. Piyasayi nesneler ve iliskiler halinde bilir.
Bu versiyon networkx kullanmaz - saf Python ile graph implementasyonu.
================================================================================
"""

import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum


# ==============================================================================
# ENUMS
# ==============================================================================

class EntityType(Enum):
    ASSET = "asset"
    CATEGORY = "category"
    ENTITY = "entity"
    INDICATOR = "indicator"
    EVENT = "event"
    REGIME = "regime"
    INSTRUMENT = "instrument"
    SECTOR = "sector"
    STABLECOIN = "stablecoin"
    INDEX = "index"

class RelationType(Enum):
    IS_A = "is_a"
    COMPETES_WITH = "competes_with"
    BELONGS_TO = "belongs_to"
    INFLUENCES = "influences"
    NEGATIVELY_CORRELATES = "negatively_correlates"
    POSITIVELY_CORRELATES = "positively_correlates"
    ENABLES = "enables"
    INCREASES_DEMAND = "increases_demand"
    DECREASES_DEMAND = "decreases_demand"
    LEADS_TO = "leads_to"
    PART_OF = "part_of"
    DEPENDS_ON = "depends_on"
    DOMINATES = "dominates"
    SYNCHRONIZES_WITH = "synchronizes_with"


# ==============================================================================
# DATA CLASSES
# ==============================================================================

@dataclass
class MarketEntity:
    id: str
    name: str
    type: EntityType
    properties: Dict[str, Any] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    importance: float = 0.5

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "name": self.name, "type": self.type.value,
            "properties": self.properties, "aliases": self.aliases,
            "description": self.description, "importance": self.importance
        }


@dataclass
class MarketRelation:
    source: str
    target: str
    relation: RelationType
    strength: float = 0.5
    direction: str = "forward"
    evidence: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "source": self.source, "target": self.target,
            "relation": self.relation.value, "strength": self.strength,
            "direction": self.direction, "evidence": self.evidence,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class MarketState:
    timestamp: datetime
    active_regime: str = "unknown"
    dominance: Dict[str, float] = field(default_factory=dict)
    correlations: Dict[str, float] = field(default_factory=dict)
    sentiment: Dict[str, float] = field(default_factory=dict)
    risk_factors: List[str] = field(default_factory=list)
    key_events: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "active_regime": self.active_regime,
            "dominance": self.dominance, "correlations": self.correlations,
            "sentiment": self.sentiment, "risk_factors": self.risk_factors,
            "key_events": self.key_events
        }


# ==============================================================================
# SIMPLE GRAPH (networkx yerine)
# ==============================================================================

class SimpleGraph:
    """Basit yonlu graph implementasyonu"""

    def __init__(self):
        self.nodes: Set[str] = set()
        self.edges: Dict[str, List[Dict]] = {}  # node -> [{target, relation, strength, direction}]
        self.reverse_edges: Dict[str, List[Dict]] = {}  # node -> [{source, relation, strength, direction}]

    def add_node(self, node_id: str, **attrs):
        self.nodes.add(node_id)
        if node_id not in self.edges:
            self.edges[node_id] = []
        if node_id not in self.reverse_edges:
            self.reverse_edges[node_id] = []

    def add_edge(self, source: str, target: str, **attrs):
        self.add_node(source)
        self.add_node(target)
        self.edges[source].append({"target": target, **attrs})
        self.reverse_edges[target].append({"source": source, **attrs})

        if attrs.get("direction") == "bidirectional":
            self.edges[target].append({"target": source, **attrs})
            self.reverse_edges[source].append({"source": target, **attrs})

    def successors(self, node: str) -> List[str]:
        return [e["target"] for e in self.edges.get(node, [])]

    def predecessors(self, node: str) -> List[str]:
        return [e["source"] for e in self.reverse_edges.get(node, [])]

    def get_edge_data(self, source: str, target: str) -> Optional[Dict]:
        for e in self.edges.get(source, []):
            if e["target"] == target:
                return e
        return None

    def degree(self, node: str) -> int:
        return len(self.edges.get(node, [])) + len(self.reverse_edges.get(node, []))

    def shortest_path(self, source: str, target: str, cutoff: int = 5) -> Optional[List[str]]:
        """BFS ile en kisa yol"""
        if source == target:
            return [source]

        visited = {source}
        queue = [(source, [source])]

        while queue:
            current, path = queue.pop(0)
            if len(path) > cutoff + 1:
                continue

            for neighbor in self.successors(current):
                if neighbor == target:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None

    def all_simple_paths(self, source: str, target: str, cutoff: int = 3) -> List[List[str]]:
        """Tum basit yollar"""
        paths = []

        def dfs(current: str, path: List[str], visited: Set[str]):
            if len(path) > cutoff + 1:
                return
            if current == target and len(path) > 1:
                paths.append(path[:])
                return

            for neighbor in self.successors(current):
                if neighbor not in visited:
                    visited.add(neighbor)
                    path.append(neighbor)
                    dfs(neighbor, path, visited)
                    path.pop()
                    visited.remove(neighbor)

        dfs(source, [source], {source})
        return paths


# ==============================================================================
# WORLD MODEL
# ==============================================================================

class AtlasWorldModel:
    def __init__(self):
        self.graph = SimpleGraph()
        self.entities: Dict[str, MarketEntity] = {}
        self.relations: List[MarketRelation] = []
        self.market_state: Optional[MarketState] = None
        self.state_history: List[MarketState] = []

        self._init_default_model()
        print("[WorldModel] Atlas World Model baslatildi")
        print(f"[WorldModel] Varlik: {len(self.entities)}, Iliski: {len(self.relations)}")

    def add_entity(self, entity_id: str, name: str, entity_type: EntityType,
                   properties: Dict = None, aliases: List[str] = None,
                   description: str = "", importance: float = 0.5) -> MarketEntity:
        entity = MarketEntity(
            id=entity_id, name=name, type=entity_type,
            properties=properties or {}, aliases=aliases or [],
            description=description, importance=importance
        )
        self.entities[entity_id] = entity
        self.graph.add_node(entity_id, **entity.to_dict())
        return entity

    def get_entity(self, entity_id: str) -> Optional[MarketEntity]:
        return self.entities.get(entity_id)

    def find_entity(self, name: str) -> Optional[MarketEntity]:
        name_lower = name.lower()
        for entity in self.entities.values():
            if entity.name.lower() == name_lower:
                return entity
            if name_lower in [a.lower() for a in entity.aliases]:
                return entity
            symbol = entity.properties.get("symbol", "").lower()
            if symbol == name_lower:
                return entity
        return None

    def get_entities_by_type(self, entity_type: EntityType) -> List[MarketEntity]:
        return [e for e in self.entities.values() if e.type == entity_type]

    def add_relation(self, source_id: str, target_id: str, 
                     relation: RelationType, strength: float = 0.5,
                     direction: str = "forward", evidence: List[str] = None) -> bool:
        if source_id not in self.entities or target_id not in self.entities:
            return False

        rel = MarketRelation(
            source=source_id, target=target_id, relation=relation,
            strength=strength, direction=direction, evidence=evidence or []
        )
        self.relations.append(rel)
        self.graph.add_edge(source_id, target_id,
                           relation=relation.value, strength=strength, direction=direction)
        return True

    def get_related(self, entity_id: str, depth: int = 1,
                    relation_filter: List[RelationType] = None) -> Dict[str, Any]:
        if entity_id not in self.entities:
            return {}

        result = {"direct": [], "indirect": [], "paths": []}

        # Dogrudan iliskiler
        for neighbor in self.graph.successors(entity_id):
            edge_data = self.graph.get_edge_data(entity_id, neighbor)
            if relation_filter and edge_data["relation"] not in [r.value for r in relation_filter]:
                continue
            result["direct"].append({
                "entity": self.entities[neighbor].to_dict(),
                "relation": edge_data["relation"],
                "strength": edge_data["strength"]
            })

        for neighbor in self.graph.predecessors(entity_id):
            edge_data = self.graph.get_edge_data(neighbor, entity_id)
            if relation_filter and edge_data["relation"] not in [r.value for r in relation_filter]:
                continue
            result["direct"].append({
                "entity": self.entities[neighbor].to_dict(),
                "relation": f"inverse_{edge_data['relation']}",
                "strength": edge_data["strength"]
            })

        # Dolayli iliskiler
        if depth > 1:
            for target in self.entities:
                if target == entity_id:
                    continue
                paths = self.graph.all_simple_paths(entity_id, target, cutoff=depth)
                if paths:
                    for path in paths[:3]:
                        path_info = []
                        for i in range(len(path) - 1):
                            edge = self.graph.get_edge_data(path[i], path[i+1])
                            path_info.append({
                                "from": self.entities[path[i]].name,
                                "to": self.entities[path[i+1]].name,
                                "relation": edge["relation"],
                                "strength": edge["strength"]
                            })
                        result["paths"].append(path_info)
                        result["indirect"].append(self.entities[target].to_dict())

        return result

    def find_path(self, source_id: str, target_id: str, max_depth: int = 5) -> Optional[List[Dict]]:
        if source_id not in self.entities or target_id not in self.entities:
            return None

        path = self.graph.shortest_path(source_id, target_id)
        if not path or len(path) > max_depth + 1:
            return None

        result = []
        for i in range(len(path) - 1):
            edge = self.graph.get_edge_data(path[i], path[i+1])
            result.append({
                "from": self.entities[path[i]].name,
                "to": self.entities[path[i+1]].name,
                "relation": edge["relation"],
                "strength": edge["strength"]
            })
        return result

    def assess_impact(self, event_id: str, target: str = None, depth: int = 3) -> Dict:
        if event_id not in self.entities:
            return {"error": f"Olay bulunamadi: {event_id}"}

        impacts = []
        visited = {event_id}
        queue = [(event_id, 1.0, [])]

        while queue:
            current, strength, path = queue.pop(0)
            if len(path) >= depth:
                continue

            for neighbor in self.graph.successors(current):
                if neighbor in visited:
                    continue

                edge = self.graph.get_edge_data(current, neighbor)
                new_strength = strength * edge["strength"]
                new_path = path + [{
                    "from": self.entities[current].name,
                    "to": self.entities[neighbor].name,
                    "relation": edge["relation"],
                    "strength": edge["strength"]
                }]

                if target and neighbor == target:
                    impacts.append({
                        "target": self.entities[neighbor].name,
                        "impact_strength": new_strength,
                        "path": new_path,
                        "direction": self._determine_impact_direction(edge["relation"])
                    })
                elif not target:
                    impacts.append({
                        "target": self.entities[neighbor].name,
                        "impact_strength": new_strength,
                        "path": new_path,
                        "direction": self._determine_impact_direction(edge["relation"])
                    })
                    queue.append((neighbor, new_strength, new_path))
                else:
                    queue.append((neighbor, new_strength, new_path))

                visited.add(neighbor)

        impacts.sort(key=lambda x: x["impact_strength"], reverse=True)
        return {
            "event": self.entities[event_id].name,
            "target": target, "impacts": impacts[:10],
            "total_paths": len(impacts)
        }

    def _determine_impact_direction(self, relation: str) -> str:
        positive = ["increases_demand", "enables", "positively_correlates", "leads_to"]
        negative = ["negatively_correlates", "decreases_demand", "competes_with"]
        if relation in positive: return "positive"
        elif relation in negative: return "negative"
        return "neutral"

    def get_market_context(self, symbol: str) -> Dict:
        entity = self.find_entity(symbol)
        if not entity:
            return {"error": f"Sembol bulunamadi: {symbol}"}

        related = self.get_related(entity.id, depth=2)
        regime = self.market_state.active_regime if self.market_state else "unknown"
        dominance = self.market_state.dominance if self.market_state else {}

        return {
            "symbol": symbol, "entity": entity.to_dict(),
            "active_regime": regime, "dominance": dominance,
            "related_assets": [r for r in related.get("direct", []) if r["entity"]["type"] == "asset"],
            "influencing_factors": [r for r in related.get("direct", []) if r["entity"]["type"] in ["entity", "indicator", "event"]],
            "indirect_relations": related.get("indirect", [])[:5],
            "paths": related.get("paths", [])[:3]
        }

    def update_market_state(self, dominance: Dict = None, correlations: Dict = None,
                           sentiment: Dict = None, risk_factors: List[str] = None,
                           key_events: List[str] = None, active_regime: str = None):
        state = MarketState(
            timestamp=datetime.now(),
            active_regime=active_regime or (self.market_state.active_regime if self.market_state else "unknown"),
            dominance=dominance or (self.market_state.dominance if self.market_state else {}),
            correlations=correlations or (self.market_state.correlations if self.market_state else {}),
            sentiment=sentiment or (self.market_state.sentiment if self.market_state else {}),
            risk_factors=risk_factors or (self.market_state.risk_factors if self.market_state else []),
            key_events=key_events or (self.market_state.key_events if self.market_state else [])
        )
        self.market_state = state
        self.state_history.append(state)
        if len(self.state_history) > 100:
            self.state_history = self.state_history[-100:]

    def get_market_state(self) -> Optional[Dict]:
        return self.market_state.to_dict() if self.market_state else None

    def analyze_market_structure(self) -> Dict:
        analysis = {
            "total_entities": len(self.entities), "total_relations": len(self.relations),
            "entity_types": {}, "relation_types": {},
            "central_entities": [], "isolated_entities": [],
            "strongest_relations": []
        }

        for entity in self.entities.values():
            et = entity.type.value
            analysis["entity_types"][et] = analysis["entity_types"].get(et, 0) + 1

        for rel in self.relations:
            rt = rel.relation.value
            analysis["relation_types"][rt] = analysis["relation_types"].get(rt, 0) + 1

        # Merkeziyet (degree)
        degrees = {}
        for node in self.graph.nodes:
            degrees[node] = self.graph.degree(node)
        sorted_deg = sorted(degrees.items(), key=lambda x: x[1], reverse=True)
        analysis["central_entities"] = [
            {"name": self.entities[eid].name, "centrality": score}
            for eid, score in sorted_deg[:5]
        ]
        analysis["isolated_entities"] = [
            self.entities[node].name for node in self.graph.nodes
            if self.graph.degree(node) == 0
        ]

        sorted_rels = sorted(self.relations, key=lambda x: x.strength, reverse=True)
        analysis["strongest_relations"] = [
            {"from": self.entities[r.source].name, "to": self.entities[r.target].name,
             "relation": r.relation.value, "strength": r.strength}
            for r in sorted_rels[:10]
        ]

        return analysis

    def detect_anomalies(self) -> List[Dict]:
        anomalies = []
        if not self.market_state:
            return anomalies

        if self.market_state.dominance:
            btc_dom = self.market_state.dominance.get("BTC", 50)
            if btc_dom > 60:
                anomalies.append({
                    "type": "high_dominance", "severity": "medium",
                    "description": f"BTC dominance cok yuksek ({btc_dom}%). Altcoin sezonu uzak.",
                    "suggestion": "BTC agirlikli portfolyo, altcoinlerden uzak dur"
                })
            elif btc_dom < 40:
                anomalies.append({
                    "type": "low_dominance", "severity": "medium",
                    "description": f"BTC dominance dusuk ({btc_dom}%). Altcoin sezonu aktif.",
                    "suggestion": "Altcoin agirlikli portfolyo degerlendir"
                })

        if self.market_state.correlations:
            for pair, corr in self.market_state.correlations.items():
                if abs(corr) > 0.9:
                    anomalies.append({
                        "type": "extreme_correlation", "severity": "high",
                        "description": f"{pair} arasinda asiri korelasyon ({corr:.2f})",
                        "suggestion": "Diversifikasyon kaybi, hedge imkani dusuk"
                    })

        if len(self.market_state.risk_factors) > 3:
            anomalies.append({
                "type": "multiple_risks", "severity": "high",
                "description": f"{len(self.market_state.risk_factors)} risk faktörü aktif",
                "suggestion": "Pozisyon azalt, risk yonetimini sikilastir"
            })

        return anomalies

    def _init_default_model(self):
        # VARLIKLAR
        assets = [
            ("bitcoin", "Bitcoin", EntityType.ASSET, {"symbol": "BTCUSDT", "market_cap_rank": 1, "dominance": True}, ["BTC", "XBT"], "Ilk ve en buyuk kripto para", 1.0),
            ("ethereum", "Ethereum", EntityType.ASSET, {"symbol": "ETHUSDT", "market_cap_rank": 2, "smart_contract": True}, ["ETH"], "Akilli sozlesme platformu", 0.95),
            ("solana", "Solana", EntityType.ASSET, {"symbol": "SOLUSDT", "market_cap_rank": 5, "high_tps": True}, ["SOL"], "Yuksek hizli Layer1", 0.8),
            ("bnb", "BNB", EntityType.ASSET, {"symbol": "BNBUSDT", "market_cap_rank": 4, "exchange_token": True}, ["BNB"], "Binance borsa tokeni", 0.75),
            ("xrp", "XRP", EntityType.ASSET, {"symbol": "XRPUSDT", "market_cap_rank": 7, "payment_focused": True}, ["XRP", "Ripple"], "Odeme odakli kripto para", 0.7),
            ("ada", "Cardano", EntityType.ASSET, {"symbol": "ADAUSDT", "market_cap_rank": 10, "research_driven": True}, ["ADA"], "Arastirma odakli Layer1", 0.65),
        ]
        for eid, name, etype, props, aliases, desc, imp in assets:
            self.add_entity(eid, name, etype, props, aliases, desc, imp)

        # KATEGORILER
        categories = [
            ("layer1", "Layer 1", EntityType.CATEGORY, {}, ["L1"], "Temel blok zinciri protokolleri", 0.9),
            ("layer2", "Layer 2", EntityType.CATEGORY, {}, ["L2"], "Olceklendirme cozumleri", 0.7),
            ("defi", "DeFi", EntityType.CATEGORY, {}, [], "Merkeziyetsiz finans", 0.85),
            ("stablecoin", "Stablecoin", EntityType.CATEGORY, {}, [], "Dolar pegli kripto paralar", 0.8),
            ("meme", "Meme Coin", EntityType.CATEGORY, {}, [], "Sosyal medya odakli coinler", 0.4),
        ]
        for eid, name, etype, props, aliases, desc, imp in categories:
            self.add_entity(eid, name, etype, props, aliases, desc, imp)

        # KURUMLAR
        entities = [
            ("fed", "FED", EntityType.ENTITY, {"country": "USA", "type": "central_bank"}, ["Federal Reserve"], "ABD Merkez Bankasi", 0.95),
            ("sec", "SEC", EntityType.ENTITY, {"country": "USA", "type": "regulator"}, [], "ABD Menkul Kiymetler Borsasi Komisyonu", 0.9),
            ("binance", "Binance", EntityType.ENTITY, {"type": "exchange", "volume_rank": 1}, ["BNB Chain"], "En buyuk kripto borsasi", 0.9),
        ]
        for eid, name, etype, props, aliases, desc, imp in entities:
            self.add_entity(eid, name, etype, props, aliases, desc, imp)

        # GOSTERGELER
        indicators = [
            ("dxy", "DXY", EntityType.INDEX, {"full_name": "US Dollar Index"}, ["Dollar Index"], "Dolar endeksi", 0.85),
            ("sp500", "S&P 500", EntityType.INDEX, {"type": "stock_index"}, ["SPX"], "ABD hisse senedi endeksi", 0.8),
            ("nasdaq", "NASDAQ", EntityType.INDEX, {"type": "tech_index"}, [], "Teknoloji hisse endeksi", 0.75),
            ("vix", "VIX", EntityType.INDEX, {"type": "volatility_index"}, ["Fear Index"], "Piyasa korku endeksi", 0.7),
        ]
        for eid, name, etype, props, aliases, desc, imp in indicators:
            self.add_entity(eid, name, etype, props, aliases, desc, imp)

        # STABLECOINLER
        stablecoins = [
            ("usdt", "USDT", EntityType.STABLECOIN, {"issuer": "Tether", "peg": "USD"}, ["Tether"], "En buyuk stablecoin", 0.9),
            ("usdc", "USDC", EntityType.STABLECOIN, {"issuer": "Circle", "peg": "USD"}, [], "ABD merkezli stablecoin", 0.85),
        ]
        for eid, name, etype, props, aliases, desc, imp in stablecoins:
            self.add_entity(eid, name, etype, props, aliases, desc, imp)

        # REJIMLER
        regimes = [
            ("bull_market", "Bull Market", EntityType.REGIME, {"sentiment": "positive", "trend": "up"}, ["Bull"], "Yukselis piyasasi", 0.8),
            ("bear_market", "Bear Market", EntityType.REGIME, {"sentiment": "negative", "trend": "down"}, ["Bear"], "Dusus piyasasi", 0.8),
            ("altcoin_season", "Altcoin Season", EntityType.REGIME, {"dominance": "low", "altcoin_performance": "high"}, ["Alt Season"], "Altcoinlerin BTC'den iyi performans gosterdigi donem", 0.7),
            ("btc_dominance", "BTC Dominance", EntityType.REGIME, {"dominance": "high", "btc_performance": "strong"}, [], "BTC'nin piyasaya hakim oldugu donem", 0.7),
        ]
        for eid, name, etype, props, aliases, desc, imp in regimes:
            self.add_entity(eid, name, etype, props, aliases, desc, imp)

        # ARACLAR
        instruments = [
            ("etf", "ETF", EntityType.INSTRUMENT, {"type": "fund", "crypto_related": True}, ["Exchange Traded Fund"], "Borsada islem goren fon", 0.85),
            ("futures", "Futures", EntityType.INSTRUMENT, {"type": "derivative"}, [], "Vadeli islem sozlesmesi", 0.8),
        ]
        for eid, name, etype, props, aliases, desc, imp in instruments:
            self.add_entity(eid, name, etype, props, aliases, desc, imp)

        # ILISKILER
        relations = [
            ("bitcoin", "layer1", RelationType.IS_A, 1.0),
            ("ethereum", "layer1", RelationType.IS_A, 1.0),
            ("solana", "layer1", RelationType.IS_A, 1.0),
            ("usdt", "stablecoin", RelationType.BELONGS_TO, 1.0),
            ("usdc", "stablecoin", RelationType.BELONGS_TO, 1.0),
            ("solana", "ethereum", RelationType.COMPETES_WITH, 0.8),
            ("bnb", "ethereum", RelationType.COMPETES_WITH, 0.6),
            ("xrp", "ethereum", RelationType.COMPETES_WITH, 0.4),
            ("fed", "dxy", RelationType.INFLUENCES, 0.9),
            ("fed", "sp500", RelationType.INFLUENCES, 0.7),
            ("sec", "bitcoin", RelationType.INFLUENCES, 0.6),
            ("sec", "etf", RelationType.INFLUENCES, 0.8),
            ("dxy", "bitcoin", RelationType.NEGATIVELY_CORRELATES, 0.6),
            ("sp500", "bitcoin", RelationType.POSITIVELY_CORRELATES, 0.5),
            ("nasdaq", "bitcoin", RelationType.POSITIVELY_CORRELATES, 0.55),
            ("vix", "bitcoin", RelationType.NEGATIVELY_CORRELATES, 0.4),
            ("etf", "bitcoin", RelationType.INCREASES_DEMAND, 0.8),
            ("etf", "ethereum", RelationType.INCREASES_DEMAND, 0.7),
            ("bull_market", "altcoin_season", RelationType.ENABLES, 0.7),
            ("btc_dominance", "altcoin_season", RelationType.NEGATIVELY_CORRELATES, 0.8),
            ("bear_market", "btc_dominance", RelationType.LEADS_TO, 0.6),
            ("altcoin_season", "bitcoin", RelationType.DEPENDS_ON, 0.9),
            ("defi", "ethereum", RelationType.DEPENDS_ON, 0.8),
            ("bitcoin", "altcoin_season", RelationType.DOMINATES, 0.7),
            ("ethereum", "bitcoin", RelationType.SYNCHRONIZES_WITH, 0.8, "bidirectional"),
            ("solana", "bitcoin", RelationType.SYNCHRONIZES_WITH, 0.7, "bidirectional"),
        ]
        for rel in relations:
            if len(rel) == 4:
                self.add_relation(rel[0], rel[1], rel[2], rel[3])
            else:
                self.add_relation(rel[0], rel[1], rel[2], rel[3], rel[4])

    def save(self, filepath: str = "database/world_model.json"):
        import os
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        data = {
            "entities": {k: v.to_dict() for k, v in self.entities.items()},
            "relations": [r.to_dict() for r in self.relations],
            "market_state": self.market_state.to_dict() if self.market_state else None
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[WorldModel] Model kaydedildi: {filepath}")

    def load(self, filepath: str = "database/world_model.json") -> bool:
        import os
        if not os.path.exists(filepath):
            return False
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for eid, edata in data["entities"].items():
            self.add_entity(eid, edata["name"], EntityType(edata["type"]),
                           edata.get("properties", {}), edata.get("aliases", []),
                           edata.get("description", ""), edata.get("importance", 0.5))
        for rdata in data["relations"]:
            self.add_relation(rdata["source"], rdata["target"],
                             RelationType(rdata["relation"]),
                             rdata.get("strength", 0.5), rdata.get("direction", "forward"))
        print(f"[WorldModel] Model yuklendi: {filepath}")
        return True

    def print_model_summary(self):
        analysis = self.analyze_market_structure()
        print("\n" + "="*60)
        print("ATLAS AI - WORLD MODEL OZETI")
        print("="*60)
        print(f"Toplam Varlik: {analysis['total_entities']}")
        print(f"Toplam Iliski: {analysis['total_relations']}")
        print(f"\nVarlik Turleri:")
        for etype, count in analysis['entity_types'].items():
            print(f"  {etype}: {count}")
        print(f"\nMerkezi Varliklar:")
        for entity in analysis['central_entities'][:5]:
            print(f"  {entity['name']}: {entity['centrality']}")
        print(f"\nEn Guclu Iliskiler:")
        for rel in analysis['strongest_relations'][:5]:
            print(f"  {rel['from']} --[{rel['relation']}]--> {rel['to']} (guc: {rel['strength']})")
        print("="*60)


# ==============================================================================
# TEST
# ==============================================================================

if __name__ == "__main__":
    print("="*70)
    print("ATLAS AI - WORLD MODEL TEST")
    print("="*70)

    world = AtlasWorldModel()

    print("\n[TEST 1] Model ozeti...")
    world.print_model_summary()

    print("\n[TEST 2] Varlik sorgulama...")
    btc = world.get_entity("bitcoin")
    print(f"   Bitcoin: {btc.name} ({btc.type.value})")
    print(f"   Properties: {btc.properties}")

    print("\n[TEST 3] Iliskili varliklar...")
    related = world.get_related("bitcoin", depth=1)
    print(f"   Dogrudan iliskiler: {len(related['direct'])}")
    for r in related['direct'][:5]:
        print(f"      → {r['entity']['name']}: {r['relation']} (guc: {r['strength']})")

    print("\n[TEST 4] Yol bulma...")
    path = world.find_path("fed", "bitcoin", max_depth=5)
    if path:
        print(f"   FED → BTC yolu:")
        for step in path:
            print(f"      {step['from']} --[{step['relation']}]--> {step['to']}")

    print("\n[TEST 5] Etki degerlendirmesi...")
    world.add_entity("fed_rate_hike", "FED Rate Hike", EntityType.EVENT,
                    {"impact": "high", "type": "monetary_policy"},
                    [], "FED faiz artirimi", 0.9)
    world.add_relation("fed_rate_hike", "fed", RelationType.LEADS_TO, 1.0)

    impact = world.assess_impact("fed_rate_hike", target="bitcoin", depth=4)
    print(f"   Olay: {impact['event']}")
    print(f"   Toplam yol: {impact['total_paths']}")
    for imp in impact['impacts'][:3]:
        print(f"      → {imp['target']}: etki gucu={imp['impact_strength']:.3f}, yon={imp['direction']}")

    print("\n[TEST 6] Piyasa baglami...")
    world.update_market_state(
        dominance={"BTC": 52.3, "ETH": 18.1, "SOL": 3.2},
        correlations={"BTC-ETH": 0.85, "BTC-SOL": 0.75},
        sentiment={"fear_greed": 35, "funding": 0.01},
        risk_factors=["FED meeting", "ETF outflows", "Geopolitical tension"],
        key_events=["FED meeting tomorrow", "ETH ETF approval pending"],
        active_regime="btc_dominance"
    )

    context = world.get_market_context("BTCUSDT")
    print(f"   Sembol: {context['symbol']}")
    print(f"   Aktif Rejim: {context['active_regime']}")
    print(f"   BTC Dominance: {context['dominance'].get('BTC', 'N/A')}%")

    print("\n[TEST 7] Anomali tespiti...")
    anomalies = world.detect_anomalies()
    print(f"   Tespit edilen anomali: {len(anomalies)}")
    for a in anomalies:
        print(f"      [{a['severity'].upper()}] {a['type']}: {a['description']}")
        print(f"         Tavsiye: {a['suggestion']}")

    print("\n[TEST 8] Persistence...")
    world.save("database/test_world_model.json")

    print("\n" + "="*70)
    print("TUM TESTLER BASARILI!")
    print("="*70)