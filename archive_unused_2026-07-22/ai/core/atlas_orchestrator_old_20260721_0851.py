"""
ATLAS ORCHESTRATOR - Yonetici Beyin (CIO Entegrasyonlu)
Faz 1 modullerini + CIO'yu birlestirip canli karar ureten ana kontrolcu
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import random

# Faz 1 modulleri
try:
    from atlas_memory_core import AtlasMemoryCore, TradeOutcome, MarketEpisode
    from atlas_reasoning_engine import AtlasReasoningEngine, DecisionReport
    from atlas_world_model import AtlasWorldModel
    from atlas_multi_agent import AtlasMultiAgentSystem, Agent
    FAZ1_AVAILABLE = True
except ImportError:
    FAZ1_AVAILABLE = False
    print("[ORCHESTRATOR] UYARI: Faz 1 modulleri bulunamadi! Temel modda calisiliyor.")

# CIO entegrasyonu
try:
    from atlas_cio import AtlasCIO, MarketRegime, RiskProfile
    CIO_AVAILABLE = True
except ImportError:
    CIO_AVAILABLE = False
    print("[ORCHESTRATOR] UYARI: CIO modulu bulunamadi! CIO'suz calisiliyor.")


class TradeAction(Enum):
    HOLD = "hold"
    BUY = "buy"
    SELL = "sell"
    REDUCE = "reduce"
    CLOSE = "close"


@dataclass
class MarketData:
    """Canli piyasa verisi"""
    symbol: str
    price: float
    volume_24h: float
    change_24h: float
    rsi: float
    macd: float
    ema_20: float
    ema_50: float
    bb_upper: float
    bb_lower: float
    atr: float
    timestamp: datetime

    def to_dict(self):
        return {
            'symbol': self.symbol, 'price': self.price, 'volume_24h': self.volume_24h,
            'change_24h': self.change_24h, 'rsi': self.rsi, 'macd': self.macd,
            'ema_20': self.ema_20, 'ema_50': self.ema_50, 'bb_upper': self.bb_upper,
            'bb_lower': self.bb_lower, 'atr': self.atr, 'timestamp': self.timestamp.isoformat()
        }

    def to_cio_dict(self):
        """CIO icin sadelestirilmis veri"""
        return {
            'symbol': self.symbol,
            'price': self.price,
            'change_24h': self.change_24h
        }


@dataclass
class TradeDecision:
    """Trade karari"""
    symbol: str
    action: TradeAction
    confidence: float
    position_size: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    reasoning: str
    agents_votes: Dict[str, str]
    risk_level: str
    timestamp: datetime
    cio_approved: bool = True

    def to_dict(self):
        return {
            'symbol': self.symbol, 'action': self.action.value, 'confidence': self.confidence,
            'position_size': self.position_size, 'stop_loss': self.stop_loss,
            'take_profit': self.take_profit, 'reasoning': self.reasoning,
            'agents_votes': self.agents_votes, 'risk_level': self.risk_level,
            'cio_approved': self.cio_approved, 'timestamp': self.timestamp.isoformat()
        }


class AtlasOrchestrator:
    """
    ATLAS Yonetici Beyin - CIO Entegrasyonlu
    Faz 1 modullerini + CIO'yu orkestre eder
    """

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.logger = self._setup_logger()

        # Faz 1 modulleri
        self.memory = None
        self.reasoning = None
        self.world_model = None
        self.multi_agent = None

        # CIO
        self.cio = None
        self.cio_report = None

        # Durum
        self.is_running = False
        self.cycle_count = 0
        self.decisions_history: List[TradeDecision] = []
        self.active_positions: Dict[str, Dict] = {}
        self.portfolio_value = 10000.0
        self.cash = 10000.0

        # Thresholds (CIO yoksa varsayilan)
        self.min_confidence = self.config.get('min_confidence', 0.2)
        self.max_position_size = self.config.get('max_position_size', 0.2)
        self.max_positions = self.config.get('max_positions', 3)

        self._init_modules()
        self.logger.info("[ORCHESTRATOR] Atlas Orchestrator baslatildi!")

    def _setup_logger(self):
        logger = logging.getLogger('AtlasOrchestrator')
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _init_modules(self):
        """Tum modulleri baslat"""
        # Faz 1
        if FAZ1_AVAILABLE:
            try:
                self.memory = AtlasMemoryCore()
                self.reasoning = AtlasReasoningEngine()
                self.world_model = AtlasWorldModel()
                self.multi_agent = AtlasMultiAgentSystem()
                self._register_agents()
                self.logger.info("[ORCHESTRATOR] Faz 1 modulleri basariliyla yuklendi!")
            except Exception as e:
                self.logger.error(f"[ORCHESTRATOR] Faz 1 modul yukleme hatasi: {e}")
        else:
            self.logger.warning("[ORCHESTRATOR] Faz 1 modulleri mevcut degil!")

        # CIO
        if CIO_AVAILABLE:
            try:
                self.cio = AtlasCIO()
                self.logger.info("[ORCHESTRATOR] CIO modulu basariliyla yuklendi!")
            except Exception as e:
                self.logger.error(f"[ORCHESTRATOR] CIO yukleme hatasi: {e}")
        else:
            self.logger.warning("[ORCHESTRATOR] CIO modulu mevcut degil!")

    def _register_agents(self):
        """Multi-agent sistemine ajanlari kaydet"""
        if not self.multi_agent:
            return

        agents = [
            Agent("TechnicalAnalyst", "technical", 1.0),
            Agent("MacroAnalyst", "macro", 1.0),
            Agent("RiskManager", "risk", 1.0),
            Agent("SentimentAnalyzer", "sentiment", 0.8),
            Agent("QuantStrategist", "quant", 0.9),
        ]

        for agent in agents:
            self.multi_agent.register_agent(agent)

        self.logger.info(f"[ORCHESTRATOR] {len(agents)} ajan kaydedildi")

    def _update_cio_settings(self):
        """CIO raporuna gore ayarlari guncelle"""
        if not self.cio_report:
            return

        # CIO'nun onerdigi limitleri uygula
        self.max_positions = self.cio_report.max_positions
        self.max_position_size = self.cio_report.position_size_range[1]

        # Risk profiline gore min_confidence ayarla
        if self.cio_report.risk_profile == RiskProfile.CONSERVATIVE:
            self.min_confidence = 0.3
        elif self.cio_report.risk_profile == RiskProfile.AGGRESSIVE:
            self.min_confidence = 0.15
        else:
            self.min_confidence = 0.2

        self.logger.info(f"[ORCHESTRATOR] CIO ayarlari uygulandi: "
                        f"max_pos={self.max_positions}, "
                        f"max_size={self.max_position_size:.2f}, "
                        f"min_conf={self.min_confidence}")

    def update_market_data(self, market_data_list: List[MarketData]):
        """
        Canli piyasa verisini al ve isle
        """
        self.logger.info(f"[ORCHESTRATOR] {len(market_data_list)} coin icin veri alindi")

        # === CIO ANALIZI ===
        if self.cio:
            cio_data = [d.to_cio_dict() for d in market_data_list]
            self.cio_report = self.cio.generate_report(
                cio_data, self.active_positions, self.portfolio_value, self.cash
            )
            self._update_cio_settings()

        decisions = []
        for data in market_data_list:
            decision = self._process_symbol(data)
            if decision:
                decisions.append(decision)

        decisions = self._filter_decisions(decisions)
        self.decisions_history.extend(decisions)

        return decisions

    def _process_symbol(self, data: MarketData) -> Optional[TradeDecision]:
        """Tek sembol icin karar uret"""

        # 1. CIO kontrolu - Bu sembol trade edilebilir mi?
        if self.cio and self.cio_report:
            cio_approved = self.cio.should_trade(data.symbol, self.cio_report, self.active_positions)
            if not cio_approved:
                return TradeDecision(
                    symbol=data.symbol,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    position_size=0.0,
                    stop_loss=None,
                    take_profit=None,
                    reasoning="CIO tarafindan red edildi (sektor limiti veya pozisyon sayisi)",
                    agents_votes={},
                    risk_level="low",
                    timestamp=datetime.now(),
                    cio_approved=False
                )

        # 2. Multi-Agent analiz
        agent_votes = self._get_agent_votes(data)

        # 3. Teknik skor
        technical_score = self._calculate_technical_score(data)

        # 4. World Model
        world_impact = self._get_world_impact(data.symbol)

        # 5. Memory
        memory_insight = self._get_memory_insight(data.symbol)

        # 6. Nihai karar
        decision = self._make_decision(data, agent_votes, technical_score, world_impact, memory_insight)

        return decision

    def _get_agent_votes(self, data: MarketData) -> Dict[str, str]:
        """Ajan oylari"""
        if not self.multi_agent:
            return {"Fallback": "neutral"}

        tasks = {
            "TechnicalAnalyst": f"Analyze {data.symbol}: RSI={data.rsi:.1f}, MACD={data.macd:.4f}, Price={data.price:.2f}",
            "MacroAnalyst": f"Macro view for {data.symbol}: 24h change={data.change_24h:.2f}%",
            "RiskManager": f"Risk assessment: ATR={data.atr:.2f}, Volume={data.volume_24h:.0f}",
            "SentimentAnalyzer": f"Sentiment: 24h change={data.change_24h:.2f}%",
            "QuantStrategist": f"Quant analysis: EMA20={data.ema_20:.2f}, EMA50={data.ema_50:.2f}",
        }

        results = self.multi_agent.assign_tasks(tasks)

        votes = {}
        for agent_id, result in results.items():
            if "buy" in result.lower() or "bullish" in result.lower():
                votes[agent_id] = "buy"
            elif "sell" in result.lower() or "bearish" in result.lower():
                votes[agent_id] = "sell"
            elif "reduce" in result.lower():
                votes[agent_id] = "reduce"
            else:
                votes[agent_id] = "hold"

        return votes

    def _calculate_technical_score(self, data: MarketData) -> float:
        """Teknik skor hesapla (-1 ile 1 arasi)"""
        score = 0.0

        if data.rsi < 35:
            score += 0.3
        elif data.rsi > 65:
            score -= 0.3

        if data.macd > 0:
            score += 0.2
        else:
            score -= 0.2

        if data.ema_20 > data.ema_50:
            score += 0.2
        else:
            score -= 0.2

        if data.price < data.bb_lower:
            score += 0.15
        elif data.price > data.bb_upper:
            score -= 0.15

        if data.volume_24h > 500000:
            score += 0.15

        return max(-1, min(1, score))

    def _get_world_impact(self, symbol: str) -> float:
        """World model etki degerlendirmesi"""
        if not self.world_model:
            return 0.0

        try:
            if symbol != "BTCUSDT":
                path = self.world_model.find_path(symbol.replace("USDT", ""), "Bitcoin")
                if path:
                    impact = self.world_model.assess_impact("FED", symbol.replace("USDT", ""))
                    return impact
            return 0.0
        except:
            return 0.0

    def _get_memory_insight(self, symbol: str) -> Dict:
        """Memory'den gecmis deneyim"""
        if not self.memory:
            return {"win_rate": 0.5, "avg_return": 0, "suggestion": "neutral"}

        try:
            symbol_trades = [e for e in self.memory.episodes if symbol in str(e.tags)]

            if not symbol_trades:
                return {"win_rate": 0.5, "avg_return": 0, "suggestion": "neutral"}

            wins = sum(1 for t in symbol_trades if t.outcome == TradeOutcome.WIN)
            win_rate = wins / len(symbol_trades)
            avg_return = sum(t.return_pct for t in symbol_trades) / len(symbol_trades)

            suggestion = "buy" if win_rate > 0.6 else "sell" if win_rate < 0.4 else "neutral"

            return {
                "win_rate": win_rate,
                "avg_return": avg_return,
                "suggestion": suggestion,
                "sample_size": len(symbol_trades)
            }
        except:
            return {"win_rate": 0.5, "avg_return": 0, "suggestion": "neutral"}

    def _make_decision(self, data: MarketData, agent_votes: Dict, technical_score: float,
                      world_impact: float, memory_insight: Dict) -> Optional[TradeDecision]:
        """Nihai karar"""

        has_position = data.symbol in self.active_positions

        buy_votes = sum(1 for v in agent_votes.values() if v == "buy")
        sell_votes = sum(1 for v in agent_votes.values() if v == "sell")
        total_votes = len(agent_votes)

        agent_score = (buy_votes - sell_votes) / total_votes if total_votes > 0 else 0

        memory_factor = 0
        if memory_insight["win_rate"] > 0.6:
            memory_factor = 0.2
        elif memory_insight["win_rate"] < 0.4:
            memory_factor = -0.2

        total_score = (technical_score * 0.4) + (agent_score * 0.3) + (world_impact * 0.1) + (memory_factor * 0.2)

        confidence = abs(total_score)

        action = TradeAction.HOLD
        position_size = 0.0
        reasoning_parts = []

        # CIO pozisyon size ayari
        if self.cio and self.cio_report:
            position_size = self.cio.get_position_size(self.cio_report, confidence)

        if confidence < self.min_confidence:
            action = TradeAction.HOLD
            reasoning_parts.append(f"Guven dusuk ({confidence:.2f} < {self.min_confidence})")
        elif total_score > 0.2:
            if has_position:
                action = TradeAction.HOLD
                reasoning_parts.append("Zaten pozisyon var, tut")
            elif len(self.active_positions) >= self.max_positions:
                action = TradeAction.HOLD
                reasoning_parts.append(f"Max pozisyon sayisi ({self.max_positions}) dolu")
            else:
                action = TradeAction.BUY
                if not (self.cio and self.cio_report):
                    position_size = min(confidence * self.max_position_size, self.max_position_size)
                reasoning_parts.append(f"Guclu AL sinyali (skor: {total_score:.2f})")
        elif total_score < -0.2:
            if has_position:
                action = TradeAction.CLOSE
                reasoning_parts.append(f"Guclu SAT sinyali (skor: {total_score:.2f})")
            else:
                action = TradeAction.HOLD
                reasoning_parts.append("SAT sinyali ama pozisyon yok")
        elif total_score > 0.05:
            if not has_position and len(self.active_positions) < self.max_positions:
                action = TradeAction.BUY
                if not (self.cio and self.cio_report):
                    position_size = min(confidence * self.max_position_size * 0.5, self.max_position_size * 0.5)
                reasoning_parts.append(f"Zayif AL sinyali (skor: {total_score:.2f})")
            else:
                action = TradeAction.HOLD
        elif total_score < -0.05:
            if has_position:
                action = TradeAction.REDUCE
                position_size = 0.5
                reasoning_parts.append(f"Risk azaltma (skor: {total_score:.2f})")
            else:
                action = TradeAction.HOLD

        if confidence > 0.8 and abs(total_score) > 0.5:
            risk_level = "high"
        elif confidence > 0.5:
            risk_level = "medium"
        else:
            risk_level = "low"

        stop_loss = None
        take_profit = None
        if action in [TradeAction.BUY, TradeAction.REDUCE]:
            stop_loss = data.price * 0.95
            take_profit = data.price * 1.1

        reasoning = " | ".join(reasoning_parts)
        if not reasoning:
            reasoning = "Notr sinyal, islem yok"

        # CIO bilgisi ekle
        if self.cio_report:
            reasoning += f" | [CIO: {self.cio_report.regime.value}, {self.cio_report.risk_profile.value}]"

        return TradeDecision(
            symbol=data.symbol,
            action=action,
            confidence=confidence,
            position_size=position_size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reasoning=reasoning,
            agents_votes=agent_votes,
            risk_level=risk_level,
            timestamp=datetime.now(),
            cio_approved=True
        )

    def _filter_decisions(self, decisions: List[TradeDecision]) -> List[TradeDecision]:
        """Kararlari filtrele ve en iyileri sec"""
        actionable = [d for d in decisions if d.action != TradeAction.HOLD]
        actionable.sort(key=lambda x: x.confidence, reverse=True)

        buy_decisions = [d for d in actionable if d.action == TradeAction.BUY]
        other_decisions = [d for d in actionable if d.action != TradeAction.BUY]

        available_slots = self.max_positions - len(self.active_positions)
        selected_buys = buy_decisions[:available_slots]

        return selected_buys + other_decisions

    def execute_decision(self, decision: TradeDecision, current_price: float) -> Dict:
        """Karari uygula (paper trading)"""

        result = {
            'symbol': decision.symbol, 'action': decision.action.value, 'executed': False,
            'price': current_price, 'pnl': 0.0, 'message': ''
        }

        if decision.action == TradeAction.BUY:
            investment = self.portfolio_value * decision.position_size
            if investment > self.cash:
                investment = self.cash * 0.9

            quantity = investment / current_price

            self.active_positions[decision.symbol] = {
                'entry_price': current_price, 'quantity': quantity, 'investment': investment,
                'stop_loss': decision.stop_loss, 'take_profit': decision.take_profit,
                'timestamp': datetime.now(), 'last_price': current_price
            }

            self.cash -= investment
            result['executed'] = True
            result['message'] = f"Pozisyon acildi: {quantity:.4f} @ {current_price:.2f}"

            if self.memory:
                self.memory.record_trade(
                    symbol=decision.symbol, entry_price=current_price,
                    position_size=investment, strategy="AtlasOrchestrator", tags=["live", decision.risk_level]
                )

        elif decision.action in [TradeAction.SELL, TradeAction.CLOSE]:
            if decision.symbol in self.active_positions:
                pos = self.active_positions[decision.symbol]
                pnl = (current_price - pos['entry_price']) * pos['quantity']
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100

                self.cash += pos['investment'] + pnl
                del self.active_positions[decision.symbol]

                result['executed'] = True
                result['pnl'] = pnl
                result['message'] = f"Pozisyon kapandi: PnL=${pnl:.2f} ({pnl_pct:.2f}%)"

                if self.memory:
                    outcome = TradeOutcome.WIN if pnl > 0 else TradeOutcome.LOSS
                    self.memory.update_trade_outcome(
                        symbol=decision.symbol, exit_price=current_price,
                        return_pct=pnl_pct, outcome=outcome
                    )

        elif decision.action == TradeAction.REDUCE:
            if decision.symbol in self.active_positions:
                pos = self.active_positions[decision.symbol]
                half_qty = pos['quantity'] / 2
                pnl = (current_price - pos['entry_price']) * half_qty

                pos['quantity'] -= half_qty
                pos['investment'] = pos['quantity'] * current_price
                pos['last_price'] = current_price

                self.cash += (half_qty * current_price)

                result['executed'] = True
                result['pnl'] = pnl
                result['message'] = f"Pozisyon yariya indirildi: PnL=${pnl:.2f}"

        self._update_portfolio_value()

        return result

    def _update_portfolio_value(self):
        """Portfoy degerini guncelle"""
        positions_value = sum(
            pos['quantity'] * pos.get('last_price', pos['entry_price'])
            for pos in self.active_positions.values()
        )
        self.portfolio_value = self.cash + positions_value

    def check_positions(self, market_data: Dict[str, float]):
        """Aktif pozisyonlari kontrol et"""
        closed_positions = []

        for symbol, pos in list(self.active_positions.items()):
            if symbol not in market_data:
                continue

            current_price = market_data[symbol]
            pos['last_price'] = current_price

            if pos['stop_loss'] and current_price <= pos['stop_loss']:
                decision = TradeDecision(
                    symbol=symbol, action=TradeAction.CLOSE, confidence=1.0, position_size=0,
                    stop_loss=None, take_profit=None, reasoning="Stop loss tetiklendi",
                    agents_votes={}, risk_level="high", timestamp=datetime.now()
                )
                result = self.execute_decision(decision, current_price)
                closed_positions.append(result)

            elif pos['take_profit'] and current_price >= pos['take_profit']:
                decision = TradeDecision(
                    symbol=symbol, action=TradeAction.CLOSE, confidence=1.0, position_size=0,
                    stop_loss=None, take_profit=None, reasoning="Take profit tetiklendi",
                    agents_votes={}, risk_level="low", timestamp=datetime.now()
                )
                result = self.execute_decision(decision, current_price)
                closed_positions.append(result)

        return closed_positions

    def get_status(self) -> Dict:
        """Sistem durumu"""
        status = {
            'is_running': self.is_running, 'cycle_count': self.cycle_count,
            'portfolio_value': self.portfolio_value, 'cash': self.cash,
            'active_positions': len(self.active_positions),
            'positions': {s: {
                'entry': p['entry_price'], 'qty': p['quantity'],
                'investment': p['investment'], 'sl': p['stop_loss'], 'tp': p['take_profit'],
                'last_price': p.get('last_price', p['entry_price'])
            } for s, p in self.active_positions.items()},
            'total_decisions': len(self.decisions_history),
            'faz1_modules_loaded': FAZ1_AVAILABLE,
            'cio_loaded': CIO_AVAILABLE
        }

        if self.cio_report:
            status['cio'] = {
                'regime': self.cio_report.regime.value,
                'risk_profile': self.cio_report.risk_profile.value,
                'cash_target': self.cio_report.cash_target,
                'max_positions': self.cio_report.max_positions
            }

        return status

    def save_state(self, filepath: str = "atlas_orchestrator_state.json"):
        """Durumu kaydet"""
        state = {
            'portfolio_value': self.portfolio_value, 'cash': self.cash,
            'active_positions': {
                s: {
                    'entry_price': p['entry_price'], 'quantity': p['quantity'],
                    'investment': p['investment'], 'stop_loss': p['stop_loss'],
                    'take_profit': p['take_profit'], 'timestamp': p['timestamp'].isoformat(),
                    'last_price': p.get('last_price', p['entry_price'])
                }
                for s, p in self.active_positions.items()
            },
            'decisions_history': [d.to_dict() for d in self.decisions_history[-100:]],
            'cycle_count': self.cycle_count
        }

        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)

        self.logger.info(f"[ORCHESTRATOR] Durum kaydedildi: {filepath}")

    def load_state(self, filepath: str = "atlas_orchestrator_state.json"):
        """Durumu yukle"""
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)

            self.portfolio_value = state.get('portfolio_value', 10000)
            self.cash = state.get('cash', 10000)
            self.cycle_count = state.get('cycle_count', 0)

            for symbol, pos in state.get('active_positions', {}).items():
                self.active_positions[symbol] = {
                    'entry_price': pos['entry_price'], 'quantity': pos['quantity'],
                    'investment': pos['investment'], 'stop_loss': pos.get('stop_loss'),
                    'take_profit': pos.get('take_profit'),
                    'timestamp': datetime.fromisoformat(pos['timestamp']),
                    'last_price': pos.get('last_price', pos['entry_price'])
                }

            self.logger.info(f"[ORCHESTRATOR] Durum yuklendi: {filepath}")
        except FileNotFoundError:
            self.logger.info("[ORCHESTRATOR] Kayitli durum bulunamadi, yeni baslatiliyor")

    def run_cycle(self, market_data_list: List[MarketData]) -> Dict:
        """Tek dongu calistir"""
        self.cycle_count += 1
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"[ORCHESTRATOR] DONGU #{self.cycle_count} BASLIYOR")
        self.logger.info(f"{'='*60}")

        decisions = self.update_market_data(market_data_list)

        executed = []
        for decision in decisions:
            current_price = next((d.price for d in market_data_list if d.symbol == decision.symbol), 0)
            if current_price > 0:
                result = self.execute_decision(decision, current_price)
                executed.append(result)
                self.logger.info(f"[TRADE] {decision.symbol}: {result['message']}")

        price_map = {d.symbol: d.price for d in market_data_list}
        closed = self.check_positions(price_map)
        for c in closed:
            self.logger.info(f"[AUTO] {c['symbol']}: {c['message']}")

        self.save_state()

        status = self.get_status()
        self.logger.info(f"\n[DURUM] Portfoy: ${status['portfolio_value']:.2f} | Nakit: ${status['cash']:.2f} | Pozisyon: {status['active_positions']}")

        return {
            'cycle': self.cycle_count, 'decisions': [d.to_dict() for d in decisions],
            'executed': executed, 'auto_closed': closed, 'status': status
        }


def create_demo_market_data() -> List[MarketData]:
    """Demo piyasa verisi olustur"""
    symbols = [
        ("BTCUSDT", 65000, 0.05), ("ETHUSDT", 3500, 0.08),
        ("SOLUSDT", 150, 0.12), ("BNBUSDT", 580, -0.03),
        ("ADAUSDT", 0.45, 0.02),
    ]

    data = []
    for symbol, base_price, change in symbols:
        rsi = random.uniform(20, 80)
        macd = random.uniform(-0.5, 0.5)
        ema_20 = base_price * (1 + random.uniform(-0.02, 0.02))
        ema_50 = base_price * (1 + random.uniform(-0.05, 0.05))
        bb_upper = base_price * 1.05
        bb_lower = base_price * 0.95
        atr = base_price * 0.02

        data.append(MarketData(
            symbol=symbol, price=base_price * (1 + change), volume_24h=random.uniform(1e6, 1e9),
            change_24h=change * 100, rsi=rsi, macd=macd, ema_20=ema_20, ema_50=ema_50,
            bb_upper=bb_upper, bb_lower=bb_lower, atr=atr, timestamp=datetime.now()
        ))

    return data


def test_orchestrator():
    """Orchestrator testi"""
    print("\n" + "="*70)
    print("ATLAS ORCHESTRATOR + CIO - TEST")
    print("="*70)

    orch = AtlasOrchestrator(config={
        'min_confidence': 0.2, 'max_position_size': 0.2, 'max_positions': 3
    })

    for i in range(3):
        print(f"\n{'='*70}")
        print(f"DONGU {i+1}/3")
        print(f"{'='*70}")

        market_data = create_demo_market_data()
        result = orch.run_cycle(market_data)

        print(f"\nKararlar: {len(result['decisions'])}")
        for d in result['decisions']:
            cio_info = " [CIO-ONAYLI]" if d.get('cio_approved') else " [CIO-RED]"
            print(f"  {d['symbol']}: {d['action'].upper()} (guven: {d['confidence']:.2f}){cio_info}")
            print(f"    -> {d['reasoning']}")

        print(f"\nUygulanan: {len(result['executed'])}")
        for e in result['executed']:
            if e['executed']:
                print(f"  [OK] {e['symbol']}: {e['message']}")

        print(f"\nDurum: ${result['status']['portfolio_value']:.2f} | "
              f"Nakit: ${result['status']['cash']:.2f} | "
              f"Pozisyon: {result['status']['active_positions']}")

        # CIO durumu
        if 'cio' in result['status']:
            cio = result['status']['cio']
            print(f"\n[CIO] Rejim: {cio['regime'].upper()} | Risk: {cio['risk_profile']} | "
                  f"Cash Hedef: %{cio['cash_target']*100:.0f} | Max Pos: {cio['max_positions']}")

    print(f"\n{'='*70}")
    print("FINAL OZET")
    print(f"{'='*70}")
    status = orch.get_status()
    print(f"Toplam Dongu: {status['cycle_count']}")
    print(f"Portfoy Degeri: ${status['portfolio_value']:.2f}")
    print(f"Nakit: ${status['cash']:.2f}")
    print(f"Aktif Pozisyonlar: {status['active_positions']}")
    for sym, pos in status['positions'].items():
        print(f"  {sym}: {pos['qty']:.4f} @ ${pos['entry']:.2f}")
    print(f"Toplam Karar: {status['total_decisions']}")
    print(f"Faz 1 Modulleri: {'YUKLU' if status['faz1_modules_loaded'] else 'YOK'}")
    print(f"CIO: {'YUKLU' if status['cio_loaded'] else 'YOK'}")

    if orch.memory:
        print(f"\nMemory Kayitlari: {len(orch.memory.trades)} trade, {len(orch.memory.episodes)} episode")

    print("\n[OK] ORCHESTRATOR + CIO TEST TAMAMLANDI!")
    return orch


if __name__ == "__main__":
    test_orchestrator()