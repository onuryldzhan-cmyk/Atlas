"""Atlas AI - Position Tracker"""
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, List
from collections import deque

@dataclass
class DailyPnL:
    date: str; realized_pnl: float; unrealized_pnl: float
    commission: float; num_trades: int; num_wins: int; num_losses: int
    @property
    def net_pnl(self): return self.realized_pnl + self.unrealized_pnl - self.commission
    @property
    def win_rate(self): return (self.num_wins / max(self.num_wins + self.num_losses, 1)) * 100

class PositionTracker:
    def __init__(self, engine=None):
        self.engine = engine
        self.daily_pnl: Dict[str, DailyPnL] = {}
        self.pnl_history: deque = deque(maxlen=10000)
        self.risk_history: deque = deque(maxlen=1000)
        self.alerts: List[dict] = []
        self.alert_callbacks = []
        self.max_daily_loss_pct = 0.05
        self.max_position_pct = 0.20
        self.max_portfolio_heat = 0.50

    def get_open_positions(self):
        if not self.engine: return []
        positions = []
        for pos in self.engine.get_all_positions():
            current_price = self.engine.current_prices.get(pos.symbol, pos.entry_price)
            if pos.side.value == "LONG":
                pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100
                pnl_amount = (current_price - pos.entry_price) * pos.quantity
            else:
                pnl_pct = ((pos.entry_price - current_price) / pos.entry_price) * 100
                pnl_amount = (pos.entry_price - current_price) * pos.quantity
            positions.append({'id': pos.id, 'symbol': pos.symbol, 'side': pos.side.value, 'entry_price': pos.entry_price, 'current_price': current_price, 'quantity': pos.quantity, 'notional': pos.quantity * current_price, 'pnl_amount': pnl_amount, 'pnl_pct': pnl_pct, 'margin': pos.margin, 'opened_at': pos.opened_at.isoformat(), 'duration_minutes': (datetime.now() - pos.opened_at).total_seconds() / 60})
        return positions

    def get_position_summary(self):
        positions = self.get_open_positions()
        if not positions: return {'count': 0, 'total_notional': 0.0, 'total_unrealized_pnl': 0.0, 'long_count': 0, 'short_count': 0, 'avg_pnl_pct': 0.0, 'best_position': None, 'worst_position': None}
        total_notional = sum(p['notional'] for p in positions)
        total_pnl = sum(p['pnl_amount'] for p in positions)
        long_count = sum(1 for p in positions if p['side'] == 'LONG')
        short_count = sum(1 for p in positions if p['side'] == 'SHORT')
        avg_pnl = sum(p['pnl_pct'] for p in positions) / len(positions)
        best = max(positions, key=lambda x: x['pnl_pct'])
        worst = min(positions, key=lambda x: x['pnl_pct'])
        return {'count': len(positions), 'total_notional': total_notional, 'total_unrealized_pnl': total_pnl, 'long_count': long_count, 'short_count': short_count, 'avg_pnl_pct': avg_pnl, 'best_position': {'symbol': best['symbol'], 'pnl_pct': best['pnl_pct']}, 'worst_position': {'symbol': worst['symbol'], 'pnl_pct': worst['pnl_pct']}}

    def record_trade_pnl(self, trade_data):
        today = datetime.now().strftime('%Y-%m-%d')
        if today not in self.daily_pnl:
            self.daily_pnl[today] = DailyPnL(date=today, realized_pnl=0.0, unrealized_pnl=0.0, commission=0.0, num_trades=0, num_wins=0, num_losses=0)
        daily = self.daily_pnl[today]; daily.num_trades += 1
        if trade_data.get('realized_pnl', 0) > 0: daily.num_wins += 1
        elif trade_data.get('realized_pnl', 0) < 0: daily.num_losses += 1
        daily.realized_pnl += trade_data.get('realized_pnl', 0)
        daily.commission += trade_data.get('commission', 0)
        self.pnl_history.append({'timestamp': datetime.now().isoformat(), 'symbol': trade_data.get('symbol'), 'realized_pnl': trade_data.get('realized_pnl', 0), 'commission': trade_data.get('commission', 0)})

    def get_daily_pnl(self, days=7):
        result = []; today = datetime.now()
        for i in range(days):
            date_str = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            if date_str in self.daily_pnl:
                daily = self.daily_pnl[date_str]
                result.append({'date': date_str, 'realized_pnl': daily.realized_pnl, 'unrealized_pnl': daily.unrealized_pnl, 'commission': daily.commission, 'net_pnl': daily.net_pnl, 'trades': daily.num_trades, 'wins': daily.num_wins, 'losses': daily.num_losses, 'win_rate': daily.win_rate})
            else:
                result.append({'date': date_str, 'realized_pnl': 0.0, 'unrealized_pnl': 0.0, 'commission': 0.0, 'net_pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0})
        return result

    def calculate_risk_metrics(self):
        if not self.engine: return {}
        positions = self.get_open_positions()
        summary = self.engine.get_account_summary()
        equity = summary.get('equity', 10000)
        if not positions: return {'total_exposure': 0.0, 'portfolio_heat': 0.0, 'concentration_risk': 0.0, 'max_position_pct': 0.0, 'risk_level': 'LOW', 'recommendation': 'No open positions'}
        total_notional = sum(p['notional'] for p in positions)
        total_exposure = total_notional / equity if equity > 0 else 0
        max_pos = max(positions, key=lambda x: x['notional'])
        max_position_pct = max_pos['notional'] / equity if equity > 0 else 0
        portfolio_heat = total_exposure
        concentration_risk = max_position_pct
        if portfolio_heat > self.max_portfolio_heat: risk_level = 'CRITICAL'
        elif portfolio_heat > self.max_portfolio_heat * 0.7: risk_level = 'HIGH'
        elif portfolio_heat > self.max_portfolio_heat * 0.4: risk_level = 'MEDIUM'
        else: risk_level = 'LOW'
        recommendations = []
        if portfolio_heat > self.max_portfolio_heat: recommendations.append("Reduce total exposure immediately")
        if max_position_pct > self.max_position_pct: recommendations.append(f"Reduce {max_pos['symbol']} position size")
        if not recommendations: recommendations.append("Risk levels acceptable")
        metrics = {'total_exposure': total_exposure, 'portfolio_heat': portfolio_heat, 'concentration_risk': concentration_risk, 'max_position_pct': max_position_pct, 'max_position_symbol': max_pos['symbol'], 'num_positions': len(positions), 'risk_level': risk_level, 'recommendation': ' | '.join(recommendations), 'unrealized_pnl': sum(p['pnl_amount'] for p in positions), 'unrealized_pnl_pct': (sum(p['pnl_amount'] for p in positions) / equity) * 100}
        self.risk_history.append({'timestamp': datetime.now().isoformat(), **metrics})
        return metrics

    def check_alerts(self):
        alerts = []
        if not self.engine: return alerts
        summary = self.engine.get_account_summary()
        equity = summary.get('equity', 10000)
        positions = self.get_open_positions()
        today = datetime.now().strftime('%Y-%m-%d')
        daily_pnl = self.daily_pnl.get(today)
        if daily_pnl:
            daily_loss_pct = abs(daily_pnl.net_pnl) / self.engine.initial_balance
            if daily_loss_pct >= self.max_daily_loss_pct:
                alerts.append({'level': 'CRITICAL', 'type': 'MAX_DAILY_LOSS', 'message': f"Daily loss {daily_loss_pct*100:.2f}% exceeds limit", 'action': 'STOP_TRADING'})
        for pos in positions:
            pos_pct = pos['notional'] / equity if equity > 0 else 0
            if pos_pct > self.max_position_pct:
                alerts.append({'level': 'WARNING', 'type': 'POSITION_SIZE_LIMIT', 'message': f"{pos['symbol']} position too large: {pos_pct*100:.1f}%", 'action': 'REDUCE_POSITION'})
        for alert in alerts:
            alert['timestamp'] = datetime.now().isoformat(); self.alerts.append(alert)
            for cb in self.alert_callbacks: cb(alert)
        return alerts

    def get_recent_alerts(self, limit=20): return self.alerts[-limit:]
    def on_alert(self, cb): self.alert_callbacks.append(cb)

    def print_report(self):
        report = self.generate_report()
        print("\n" + "=" * 70); print("ATLAS AI - POSITION TRACKER REPORT"); print("=" * 70)
        print(f"Zaman: {report['timestamp']}")
        acc = report['account']
        print(f"\nHESAP OZETI\n   Equity: ${acc.get('equity', 0):,.2f}\n   Available: ${acc.get('available_balance', 0):,.2f}\n   Return: {acc.get('return_pct', 0):+.2f}%\n   Total PnL: ${acc.get('total_pnl', 0):,.2f}")
        pos_summary = report['positions']['summary']
        print(f"\nPOZISYONLAR ({pos_summary['count']} acik)")
        if pos_summary['count'] > 0:
            print(f"   Total Notional: ${pos_summary['total_notional']:,.2f}\n   Unrealized PnL: ${pos_summary['total_unrealized_pnl']:,.2f}\n   Long: {pos_summary['long_count']} | Short: {pos_summary['short_count']}")
            for pos in report['positions']['open']:
                emoji = "🟢" if pos['pnl_pct'] >= 0 else "🔴"
                print(f"   {emoji} {pos['symbol']} {pos['side']} | Entry: ${pos['entry_price']:,.2f} | Current: ${pos['current_price']:,.2f} | PnL: {pos['pnl_pct']:+.2f}% (${pos['pnl_amount']:,.2f})")
        risk = report['risk']
        print(f"\nRISK METRIKLERI\n   Risk Level: {risk.get('risk_level', 'N/A')}\n   Portfolio Heat: {risk.get('portfolio_heat', 0)*100:.1f}%\n   Max Position: {risk.get('max_position_pct', 0)*100:.1f}% ({risk.get('max_position_symbol', '')})\n   Recommendation: {risk.get('recommendation', 'N/A')}")
        if report['alerts']:
            print(f"\nAKTIF ALERTLER")
            for alert in report['alerts'][-5:]:
                emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(alert['level'], "⚪")
                print(f"   {emoji} [{alert['level']}] {alert['message']}")
        print("\n" + "=" * 70)

    def generate_report(self):
        return {'timestamp': datetime.now().isoformat(), 'account': self.engine.get_account_summary() if self.engine else {}, 'positions': {'open': self.get_open_positions(), 'summary': self.get_position_summary()}, 'risk': self.calculate_risk_metrics(), 'alerts': self.get_recent_alerts(10), 'daily_pnl': self.get_daily_pnl(7)}
