"""Atlas AI - Performance Report"""
from datetime import datetime, timedelta
from typing import Dict, List
from collections import deque
import math

class PerformanceReport:
    def __init__(self, engine=None, benchmark_symbol="BTCUSDT"):
        self.engine = engine; self.benchmark_symbol = benchmark_symbol
        self.equity_history: deque = deque(maxlen=100000)
        self.daily_equity: Dict[str, float] = {}
        self.trade_history: List[dict] = []
        self.benchmark_prices: Dict[str, float] = {}
        self.risk_free_rate = 0.02

    def record_equity(self, equity, timestamp=None):
        if timestamp is None: timestamp = datetime.now()
        self.equity_history.append({'timestamp': timestamp.isoformat(), 'equity': equity})
        self.daily_equity[timestamp.strftime('%Y-%m-%d')] = equity

    def get_equity_curve(self, days=30):
        if not self.daily_equity: return []
        result = []; today = datetime.now()
        for i in range(days, -1, -1):
            date = today - timedelta(days=i); date_str = date.strftime('%Y-%m-%d')
            if date_str in self.daily_equity: result.append({'date': date_str, 'equity': self.daily_equity[date_str]})
        return result

    def _calculate_drawdown(self, start_date, end_date):
        if not self.daily_equity: return 0.0, 0.0
        start_dt = datetime.strptime(start_date, '%Y-%m-%d'); end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        relevant = [v for k, v in sorted(self.daily_equity.items()) if start_dt <= datetime.strptime(k, '%Y-%m-%d') <= end_dt]
        if not relevant: return 0.0, 0.0
        peak = relevant[0]; max_dd = 0.0
        for eq in relevant:
            if eq > peak: peak = eq
            dd = peak - eq
            if dd > max_dd: max_dd = dd
        return max_dd, (max_dd / peak) * 100 if peak > 0 else 0

    def _get_daily_returns(self, start_date, end_date):
        returns = []
        filtered = {k: v for k, v in self.daily_equity.items() if datetime.strptime(start_date, '%Y-%m-%d') <= datetime.strptime(k, '%Y-%m-%d') <= datetime.strptime(end_date, '%Y-%m-%d')}
        sorted_eq = sorted(filtered.items())
        for i in range(1, len(sorted_eq)):
            returns.append((sorted_eq[i][1] - sorted_eq[i-1][1]) / max(sorted_eq[i-1][1], 1))
        return returns

    def _calculate_sharpe(self, daily_returns):
        if len(daily_returns) < 2: return 0.0
        avg = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg) ** 2 for r in daily_returns) / len(daily_returns)
        std = math.sqrt(variance)
        if std == 0: return 0.0
        daily_rf = self.risk_free_rate / 365
        return ((avg - daily_rf) / std) * math.sqrt(365)

    def _calculate_sortino(self, daily_returns):
        if len(daily_returns) < 2: return 0.0
        avg = sum(daily_returns) / len(daily_returns)
        neg = [r for r in daily_returns if r < 0]
        if not neg: return 0.0
        downside = math.sqrt(sum(r ** 2 for r in neg) / len(neg))
        if downside == 0: return 0.0
        daily_rf = self.risk_free_rate / 365
        return ((avg - daily_rf) / downside) * math.sqrt(365)

    def set_benchmark_price(self, price, timestamp=None):
        if timestamp is None: timestamp = datetime.now()
        self.benchmark_prices[timestamp.strftime('%Y-%m-%d')] = price

    def get_benchmark_return(self, days=30):
        if len(self.benchmark_prices) < 2: return 0.0
        sorted_p = sorted(self.benchmark_prices.items())
        return ((sorted_p[-1][1] - sorted_p[0][1]) / sorted_p[0][1]) * 100

    def compare_to_benchmark(self):
        if not self.engine: return {}
        strategy_return = self.engine.get_account_summary().get('return_pct', 0)
        benchmark_return = self.get_benchmark_return()
        return {'strategy_return_pct': strategy_return, 'benchmark_return_pct': benchmark_return, 'alpha': strategy_return - benchmark_return, 'outperformed': strategy_return > benchmark_return}

    def generate_full_report(self):
        today = datetime.now().strftime('%Y-%m-%d')
        this_week = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
        this_month = datetime.now().strftime('%Y-%m')
        return {'generated_at': datetime.now().isoformat(), 'account_summary': self.engine.get_account_summary() if self.engine else {}, 'equity_curve': self.get_equity_curve(30), 'benchmark_comparison': self.compare_to_benchmark()}

    def print_full_report(self):
        report = self.generate_full_report()
        print("\n" + "=" * 75); print("ATLAS AI - PERFORMANCE REPORT"); print("=" * 75)
        print(f"Rapor Tarihi: {report['generated_at']}")
        acc = report['account_summary']
        print(f"\nHESAP OZETI\n   Equity: ${acc.get('equity', 0):,.2f}\n   Return: {acc.get('return_pct', 0):+.2f}%\n   Total PnL: ${acc.get('total_pnl', 0):,.2f}\n   Win Rate: {acc.get('win_rate', 0):.1f}%\n   Open Positions: {acc.get('open_positions', 0)}")
        bench = report['benchmark_comparison']
        if bench:
            print(f"\nBENCHMARK ({self.benchmark_symbol})\n   Strateji: {bench['strategy_return_pct']:+.2f}%\n   Benchmark: {bench['benchmark_return_pct']:+.2f}%\n   Alpha: {bench['alpha']:+.2f}%\n   {'✅ Strateji kazandi!' if bench['outperformed'] else '❌ Benchmark kazandi'}")
        print("\n" + "=" * 75)
