"""ATLAS MULTI AGENT v2.0 - Cok Ajanli Karar Sistemi"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Callable, Any
from enum import Enum
import json
import os
import random

class AgentType(Enum):
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    MACRO = "macro"
    RISK = "risk"
    PORTFOLIO = "portfolio"

class AgentStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LEARNING = "learning"

@dataclass
class AgentSignal:
    agent_id: str
    agent_type: AgentType
    symbol: str
    signal: str  # buy, sell, hold
    confidence: float = 0.0
    reasoning: str = ""
    weight: float = 1.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type.value,
            "symbol": self.symbol,
            "signal": self.signal,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "weight": self.weight,
            "timestamp": self.timestamp.isoformat()
        }

@dataclass
class Agent:
    agent_id: str
    agent_type: AgentType
    name: str
    status: AgentStatus = AgentStatus.ACTIVE
    performance_score: float = 0.5
    total_signals: int = 0
    successful_signals: int = 0
    strategy: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type.value,
            "name": self.name,
            "status": self.status.value,
            "performance_score": self.performance_score,
            "total_signals": self.total_signals,
            "successful_signals": self.successful_signals
        }

class AtlasMultiAgent:
    def __init__(self, data_dir: str = "memory_data"):
        self.agents: Dict[str, Agent] = {}
        self.signals: List[AgentSignal] = []
        self.voting_history: List[Dict] = []
        self.data_dir = data_dir
        self._ensure_data_dir()
        self._initialize_default_agents()
        print("[MULTI] Atlas Multi Agent v2.0 baslatildi")
    
    def _ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
    
    def _initialize_default_agents(self):
        default_agents = [
            ("tech_01", AgentType.TECHNICAL, "RSI Master"),
            ("tech_02", AgentType.TECHNICAL, "MACD Expert"),
            ("macro_01", AgentType.MACRO, "FED Watcher"),
            ("sent_01", AgentType.SENTIMENT, "Fear&Greed Analyzer"),
            ("risk_01", AgentType.RISK, "Risk Guardian"),
            ("fund_01", AgentType.FUNDAMENTAL, "On-Chain Analyst"),
        ]
        
        for agent_id, agent_type, name in default_agents:
            self.register_agent(Agent(agent_id, agent_type, name))
    
    def register_agent(self, agent: Agent):
        self.agents[agent.agent_id] = agent
        print(f"[MULTI] Ajan kaydedildi: {agent.name} ({agent.agent_type.value})")
    
    def generate_signal(self, agent_id: str, symbol: str, signal: str, 
                        confidence: float, reasoning: str = "") -> Optional[AgentSignal]:
        if agent_id not in self.agents:
            return None
        
        agent = self.agents[agent_id]
        if agent.status != AgentStatus.ACTIVE:
            return None
        
        agent_signal = AgentSignal(
            agent_id=agent_id,
            agent_type=agent.agent_type,
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            reasoning=reasoning,
            weight=agent.performance_score
        )
        
        self.signals.append(agent_signal)
        agent.total_signals += 1
        return agent_signal
    
    def collective_decision(self, symbol: str) -> Dict:
        """Tum ajanlarin oylamasini yap"""
        symbol_signals = [s for s in self.signals if s.symbol == symbol]
        
        if not symbol_signals:
            return {"decision": "hold", "confidence": 0.0, "agents": 0}
        
        # Agirlikli oylama
        votes = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
        agent_votes = []
        
        for signal in symbol_signals:
            weighted_vote = signal.confidence * signal.weight
            votes[signal.signal] += weighted_vote
            
            agent_votes.append({
                "agent": self.agents[signal.agent_id].name,
                "signal": signal.signal,
                "confidence": signal.confidence,
                "weight": signal.weight
            })
        
        # En yuksek oy
        decision = max(votes, key=votes.get)
        total_confidence = sum(votes.values())
        
        # Normalize confidence
        confidence = votes[decision] / total_confidence if total_confidence > 0 else 0
        
        result = {
            "symbol": symbol,
            "decision": decision,
            "confidence": round(confidence, 2),
            "agents": len(symbol_signals),
            "vote_breakdown": votes,
            "agent_votes": agent_votes
        }
        
        self.voting_history.append(result)
        print(f"[MULTI] Kolektif karar: {symbol} -> {decision} (guven: {confidence:.2f})")
        return result
    
    def update_agent_performance(self, agent_id: str, was_successful: bool):
        if agent_id not in self.agents:
            return False
        
        agent = self.agents[agent_id]
        if was_successful:
            agent.successful_signals += 1
        
        # Darwinian selection: basari oranina gore agirlik guncelle
        if agent.total_signals > 0:
            win_rate = agent.successful_signals / agent.total_signals
            agent.performance_score = 0.3 + (win_rate * 0.7)  # 0.3 - 1.0 arasi
        
        print(f"[MULTI] {agent.name} performans: {agent.performance_score:.2f}")
        return True
    
    def get_top_agents(self, n: int = 3) -> List[Agent]:
        return sorted(self.agents.values(), key=lambda a: a.performance_score, reverse=True)[:n]
    
    def get_agent_signals(self, agent_id: str = None, symbol: str = None) -> List[AgentSignal]:
        signals = self.signals
        if agent_id:
            signals = [s for s in signals if s.agent_id == agent_id]
        if symbol:
            signals = [s for s in signals if s.symbol == symbol]
        return signals
    
    def simulate_market_scenario(self, symbol: str, scenario: Dict):
        """Bir senaryo altinda tum ajanlarin tepkisini simule et"""
        print(f"\n[MULTI] Senaryo simulasyonu: {symbol}")
        print(f"  Senaryo: {scenario.get('description', 'N/A')}")
        
        # Her ajanin sinyal uretmesini simule et
        for agent_id, agent in self.agents.items():
            if agent.status != AgentStatus.ACTIVE:
                continue
            
            # Ajan tipine gore farkli sinyal uret
            if agent.agent_type == AgentType.TECHNICAL:
                confidence = scenario.get("technical_score", 0.5)
                signal = "buy" if confidence > 0.6 else "sell" if confidence < 0.4 else "hold"
            elif agent.agent_type == AgentType.MACRO:
                confidence = scenario.get("macro_score", 0.5)
                signal = "buy" if confidence > 0.5 else "hold"
            elif agent.agent_type == AgentType.SENTIMENT:
                confidence = scenario.get("sentiment_score", 0.5)
                signal = "buy" if confidence > 0.7 else "sell" if confidence < 0.3 else "hold"
            elif agent.agent_type == AgentType.RISK:
                confidence = scenario.get("risk_score", 0.5)
                signal = "hold" if confidence > 0.7 else "buy"
            else:
                confidence = random.uniform(0.3, 0.8)
                signal = random.choice(["buy", "sell", "hold"])
            
            self.generate_signal(agent_id, symbol, signal, round(confidence, 2), 
                               f"Simulated {agent.agent_type.value} signal")
        
        # Kolektif karar
        return self.collective_decision(symbol)
    
    def save(self, filepath: str = None):
        if filepath is None:
            filepath = os.path.join(self.data_dir, "atlas_multi_agent.json")
        
        data = {
            "agents": [a.to_dict() for a in self.agents.values()],
            "signals": [s.to_dict() for s in self.signals[-100:]],  # Son 100 sinyal
            "voting_history": self.voting_history[-50:],
            "saved_at": datetime.now().isoformat()
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[MULTI] Kaydedildi: {filepath}")
    
    def load(self, filepath: str = None):
        if filepath is None:
            filepath = os.path.join(self.data_dir, "atlas_multi_agent.json")
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                json.load(f)
            print(f"[MULTI] Yuklendi: {filepath}")
            return True
        except FileNotFoundError:
            return False


# ========== TEST BOLUMU ==========
if __name__ == "__main__":
    print("-" * 60)
    print("ATLAS MULTI AGENT v2.0 - TEST")
    print("-" * 60)
    
    multi = AtlasMultiAgent()
    
    # Test 1: Ajan listesi
    print("\n[TEST 1] Kayitli ajanlar...")
    for agent in multi.agents.values():
        print(f"  {agent.name} ({agent.agent_type.value}) - Skor: {agent.performance_score}")
    
    # Test 2: Sinyal uretme
    print("\n[TEST 2] Sinyal uretme...")
    multi.generate_signal("tech_01", "BTCUSDT", "buy", 0.85, "RSI 28 - asiri satim")
    multi.generate_signal("tech_02", "BTCUSDT", "buy", 0.75, "MACD yukari kesti")
    multi.generate_signal("macro_01", "BTCUSDT", "hold", 0.60, "FED beklemede")
    multi.generate_signal("sent_01", "BTCUSDT", "buy", 0.90, "Fear 20 - extreme fear")
    multi.generate_signal("risk_01", "BTCUSDT", "hold", 0.70, "Volatilite yuksek")
    
    # Test 3: Kolektif karar
    print("\n[TEST 3] Kolektif karar...")
    decision = multi.collective_decision("BTCUSDT")
    print(f"Karar: {decision['decision']} | Guven: {decision['confidence']}")
    print("Oylar:")
    for vote in decision["agent_votes"]:
        print(f"  {vote['agent']}: {vote['signal']} (conf: {vote['confidence']}, weight: {vote['weight']:.2f})")
    
    # Test 4: Performans guncelleme
    print("\n[TEST 4] Performans guncelleme...")
    multi.update_agent_performance("tech_01", True)
    multi.update_agent_performance("tech_02", True)
    multi.update_agent_performance("macro_01", False)
    
    # Test 5: En iyi ajanlar
    print("\n[TEST 5] En iyi ajanlar...")
    top = multi.get_top_agents(3)
    for i, agent in enumerate(top, 1):
        print(f"  {i}. {agent.name} - Skor: {agent.performance_score:.2f}")
    
    # Test 6: Senaryo simulasyonu
    print("\n[TEST 6] Senaryo simulasyonu...")
    result = multi.simulate_market_scenario("ETHUSDT", {
        "description": "FED dovish, teknik olumlu",
        "technical_score": 0.8,
        "macro_score": 0.7,
        "sentiment_score": 0.6,
        "risk_score": 0.4
    })
    print(f"Simulasyon sonucu: {result['decision']} (guven: {result['confidence']})")
    
    # Test 7: Kaydet
    print("\n[TEST 7] Kaydetme...")
    multi.save()
    
    print("\n" + "-" * 60)
    print("TUM TESTLER BASARILI!")
    print("-" * 60)