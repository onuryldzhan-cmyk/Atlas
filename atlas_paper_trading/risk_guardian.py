"""Atlas AI - Risk Guardian"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from enum import Enum

class RiskLevel(Enum): NORMAL = "NORMAL"; WARNING = "WARNING"; HIGH = "HIGH"; CRITICAL = "CRITICAL"; EMERGENCY = "EMERGENCY"
class KillSwitchReason(Enum): MAX_DAILY_LOSS = "MAX_DAILY_LOSS"; MAX_DRAWDOWN = "MAX_DRAWDOWN"; CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"; MANUAL = "MANUAL"

class RiskGuardian:
    def __init__(self, engine=None, tracker=None):
        self.engine = engine; self.tracker = tracker
        self.max_daily_loss_pct = 0.05; self.max_drawdown_pct = 0.10
        self.max_consecutive_losses = 5; self.max_positions = 10
        self.max_position_pct = 0.20; self.max_portfolio_heat = 0.50
        self.kill_switch_active = False
        self.kill_switch_reason = None
        self.kill_switch_triggered_at = None
        self.kill_switch_history = []
        self.circuit_breakers = {}
        self.default_cooldown = 30
        self.risk_events = []
        self.risk_callbacks = []
        self.consecutive_losses = 0; self.consecutive_wins = 0
        self.price_history = {}

    def activate_kill_switch(self, reason, message="", details=None):
        if self.kill_switch_active: return False
        self.kill_switch_active = True; self.kill_switch_reason = reason; self.kill_switch_triggered_at = datetime.now()
        event = {'timestamp': datetime.now().isoformat(), 'reason': reason.value, 'message': message, 'details': details or {}}
        self.kill_switch_history.append(event)
        for cb in self.risk_callbacks: cb({'type': 'KILL_SWITCH', 'reason': reason.value, 'message': message, 'timestamp': datetime.now().isoformat()})
        print(f"\n🔴🔴🔴 KILL SWITCH AKTIVE EDILDI 🔴🔴🔴\n   Sebep: {reason.value}\n   Mesaj: {message}\n   TUM ISLEMLER DURDURULDU!")
        if reason in [KillSwitchReason.MAX_DAILY_LOSS, KillSwitchReason.MAX_DRAWDOWN]: self._close_all_positions("Kill switch activated")
        return True

    def deactivate_kill_switch(self, manual_override=False):
        if not self.kill_switch_active: return False
        self.kill_switch_active = False; self.kill_switch_reason = None; self.kill_switch_triggered_at = None
        print(f"\n🟢 Kill Switch DEVRE DISI - Trading devam ediyor")
        return True

    def is_trading_allowed(self): return not self.kill_switch_active

    def trigger_circuit_breaker(self, symbol, reason, cooldown_minutes=None):
        if cooldown_minutes is None: cooldown_minutes = self.default_cooldown
        self.circuit_breakers[symbol.upper()] = {'symbol': symbol.upper(), 'triggered_at': datetime.now(), 'reason': reason, 'cooldown_minutes': cooldown_minutes}
        print(f"\n🟡 Circuit Breaker: {symbol} | {reason} | {cooldown_minutes} dakika durduruldu")

    def is_symbol_allowed(self, symbol):
        cb = self.circuit_breakers.get(symbol.upper())
        if cb:
            if datetime.now() >= cb['triggered_at'] + timedelta(minutes=cb['cooldown_minutes']):
                del self.circuit_breakers[symbol.upper()]; return True
            return False
        return True

    def record_trade_result(self, was_win, pnl):
        if was_win: self.consecutive_losses = 0; self.consecutive_wins += 1
        else: self.consecutive_wins = 0; self.consecutive_losses += 1

    def record_price(self, symbol, price):
        symbol = symbol.upper()
        if symbol not in self.price_history: self.price_history[symbol] = []
        self.price_history[symbol].append(price)
        if len(self.price_history[symbol]) > 20: self.price_history[symbol].pop(0)

    def check_all_risks(self):
        alerts = []
        if not self.engine: return alerts
        summary = self.engine.get_account_summary()
        equity = summary.get('equity', 10000); initial = self.engine.initial_balance
        today = datetime.now().strftime('%Y-%m-%d')
        if self.tracker and today in self.tracker.daily_pnl:
            daily = self.tracker.daily_pnl[today]
            daily_loss_pct = abs(daily.net_pnl) / initial
            if daily_loss_pct >= self.max_daily_loss_pct:
                self.activate_kill_switch(KillSwitchReason.MAX_DAILY_LOSS, f"Daily loss {daily_loss_pct*100:.2f}%")
        if self.engine.stats.get('max_drawdown', 0) >= self.max_drawdown_pct:
            self.activate_kill_switch(KillSwitchReason.MAX_DRAWDOWN, f"Max drawdown {self.engine.stats['max_drawdown']*100:.2f}%")
        if self.consecutive_losses >= self.max_consecutive_losses:
            self.activate_kill_switch(KillSwitchReason.CONSECUTIVE_LOSSES, f"{self.consecutive_losses} consecutive losses")
        return alerts

    def _close_all_positions(self, reason):
        if not self.engine: return
        positions = list(self.engine.positions.keys())
        if not positions: return
        print(f"\n⚠️ Tum pozisyonlar kapatiliyor... ({reason})")
        from paper_trading_engine import OrderSide
        for symbol in positions:
            pos = self.engine.positions.get(symbol)
            if pos:
                if pos.side.value == "LONG": self.engine.place_market_order(symbol, OrderSide.SELL, pos.quantity)
                else: self.engine.place_market_order(symbol, OrderSide.BUY, pos.quantity)
        print(f"   {len(positions)} pozisyon kapatildi.")

    def get_status(self):
        return {'kill_switch': {'active': self.kill_switch_active, 'reason': self.kill_switch_reason.value if self.kill_switch_reason else None, 'triggered_at': self.kill_switch_triggered_at.isoformat() if self.kill_switch_triggered_at else None}, 'consecutive_losses': self.consecutive_losses, 'consecutive_wins': self.consecutive_wins, 'total_risk_events': len(self.risk_events), 'limits': {'max_daily_loss_pct': self.max_daily_loss_pct, 'max_drawdown_pct': self.max_drawdown_pct, 'max_consecutive_losses': self.max_consecutive_losses, 'max_positions': self.max_positions, 'max_position_pct': self.max_position_pct, 'max_portfolio_heat': self.max_portfolio_heat}}

    def print_status(self):
        status = self.get_status()
        print("\n" + "=" * 70); print("ATLAS AI - RISK GUARDIAN STATUS"); print("=" * 70)
        ks = status['kill_switch']
        if ks['active']: print(f"\n🔴 KILL SWITCH: AKTIF\n   Sebep: {ks['reason']}\n   Zaman: {ks['triggered_at']}")
        else: print(f"\n🟢 KILL SWITCH: Pasif - Trading aktif")
        print(f"\nRISK METRIKLERI\n   Consecutive Losses: {status['consecutive_losses']}\n   Consecutive Wins: {status['consecutive_wins']}\n   Toplam Risk Olayi: {status['total_risk_events']}")
        limits = status['limits']
        print(f"\nLIMITLER\n   Max Daily Loss: {limits['max_daily_loss_pct']*100}%\n   Max Drawdown: {limits['max_drawdown_pct']*100}%\n   Max Consecutive Losses: {limits['max_consecutive_losses']}\n   Max Positions: {limits['max_positions']}\n   Max Position Size: {limits['max_position_pct']*100}%")
        print("\n" + "=" * 70)

    def on_risk_event(self, cb): self.risk_callbacks.append(cb)
