"""
Atlas AI - Backtesting Engine v1.1 (BOM Fix)
"""

import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from collections import defaultdict
import statistics


@dataclass
class TradeRecord:
    entry_time: str
    exit_time: Optional[str] = None
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    status: str = "OPEN"
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    start_date: str
    end_date: str
    initial_balance: float
    final_balance: float
    total_return: float
    total_return_percent: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_percent: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    avg_trade_duration: float
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[Tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data['trades'] = [t.to_dict() for t in self.trades]
        return data


class BacktestEngine:
    def __init__(self, initial_balance=10000.0, commission_rate=0.001, slippage=0.0005, risk_per_trade=0.02):
        self.initial_balance = initial_balance
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.risk_per_trade = risk_per_trade
        self.balance = initial_balance
        self.positions: Dict[str, TradeRecord] = {}
        self.trade_history: List[TradeRecord] = []
        self.equity_curve: List[Tuple[str, float]] = []
        self.peak_balance = initial_balance
        self.max_drawdown = 0.0
        self.max_drawdown_percent = 0.0

    def reset(self):
        self.balance = self.initial_balance
        self.positions = {}
        self.trade_history = []
        self.equity_curve = []
        self.peak_balance = self.initial_balance
        self.max_drawdown = 0.0
        self.max_drawdown_percent = 0.0

    def load_historical_data(self, filepath, symbol="BTCUSDT"):
        """Tarihsel veri yukle (BOM destekli)"""
        path = Path(filepath)
        if not path.exists():
            print(f"⚠️ Veri dosyasi bulunamadi: {filepath}")
            print("   Demo veri olusturuluyor...")
            return self._generate_demo_data(symbol)

        try:
            # BOM'u handle et
            with open(filepath, 'rb') as f:
                raw = f.read()

            # BOM varsa kaldir
            if raw.startswith(b'\xef\xbb\xbf'):
                raw = raw[3:]

            data = json.loads(raw.decode('utf-8'))
            print(f"✅ {len(data)} veri noktasi yuklendi: {symbol}")
            return data

        except Exception as e:
            print(f"⚠️ Okuma hatasi: {e}")
            print("   Demo veri olusturuluyor...")
            return self._generate_demo_data(symbol)

    def _generate_demo_data(self, symbol, days=365):
        import random
        from datetime import timedelta

        data = []
        base_price = random.uniform(20000, 60000)
        current_price = base_price
        start_date = datetime.now() - timedelta(days=days)

        for i in range(days * 24):
            timestamp = start_date + timedelta(hours=i)
            change = random.uniform(-0.02, 0.02)
            current_price *= (1 + change)

            data.append({
                "timestamp": timestamp.isoformat(),
                "open": current_price * (1 + random.uniform(-0.005, 0.005)),
                "high": current_price * (1 + random.uniform(0, 0.01)),
                "low": current_price * (1 + random.uniform(-0.01, 0)),
                "close": current_price,
                "volume": random.uniform(100, 10000),
                "symbol": symbol
            })

        print(f"📊 Demo veri olusturuldu: {len(data)} saatlik mum, {days} gun")
        return data

    def run_backtest(self, strategy, data, strategy_name="Unknown", symbol="BTCUSDT"):
        self.reset()
        print(f"\n🚀 Backtest baslatiliyor: {strategy_name}")
        print(f"   Sembol: {symbol}")
        print(f"   Veri noktasi: {len(data)}")
        print(f"   Baslangic bakiye: {self.initial_balance:,.2f} USDT")
        print("-" * 50)

        for i, candle in enumerate(data):
            timestamp = candle.get("timestamp", "")
            close_price = candle.get("close", 0)

            signal = strategy(self, candle)

            if signal == "AL" and symbol not in self.positions:
                self._open_position(symbol, "LONG", close_price, timestamp)
            elif signal == "SAT" and symbol in self.positions:
                self._close_position(symbol, close_price, timestamp, "SIGNAL")

            self._check_exit_conditions(symbol, candle)

            current_equity = self._calculate_equity(close_price)
            self.equity_curve.append((timestamp, current_equity))

            if current_equity > self.peak_balance:
                self.peak_balance = current_equity
            else:
                dd = self.peak_balance - current_equity
                dd_percent = (dd / self.peak_balance) * 100
                if dd > self.max_drawdown:
                    self.max_drawdown = dd
                    self.max_drawdown_percent = dd_percent

            if len(data) > 10 and i % (len(data) // 10) == 0:
                progress = (i / len(data)) * 100
                print(f"   Ilerleme: %{progress:.0f} | Bakiye: {self.balance:,.2f}")

        if self.positions:
            last_candle = data[-1]
            for sym in list(self.positions.keys()):
                self._close_position(sym, last_candle.get("close", 0), last_candle.get("timestamp", ""), "END_OF_DATA")

        result = self._calculate_results(strategy_name, symbol, data)
        print(f"\n✅ Backtest tamamlandi!")
        print(f"   Final bakiye: {self.balance:,.2f} USDT")
        print(f"   Toplam getiri: %{result.total_return_percent:.2f}")
        return result

    def _open_position(self, symbol, side, price, timestamp):
        if side == "LONG":
            entry_price = price * (1 + self.slippage)
        else:
            entry_price = price * (1 - self.slippage)

        risk_amount = self.balance * self.risk_per_trade
        quantity = risk_amount / entry_price
        commission = quantity * entry_price * self.commission_rate
        self.balance -= commission

        trade = TradeRecord(
            entry_time=timestamp, symbol=symbol, side=side,
            entry_price=entry_price, quantity=quantity, status="OPEN", reason="SIGNAL"
        )
        self.positions[symbol] = trade

    def _close_position(self, symbol, price, timestamp, reason):
        if symbol not in self.positions:
            return
        trade = self.positions[symbol]

        if trade.side == "LONG":
            exit_price = price * (1 - self.slippage)
            pnl = (exit_price - trade.entry_price) * trade.quantity
        else:
            exit_price = price * (1 + self.slippage)
            pnl = (trade.entry_price - exit_price) * trade.quantity

        commission = trade.quantity * exit_price * self.commission_rate
        pnl -= commission

        trade.exit_time = timestamp
        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.pnl_percent = (pnl / (trade.entry_price * trade.quantity)) * 100
        trade.status = "CLOSED"
        trade.reason = reason

        self.balance += pnl
        self.trade_history.append(trade)
        del self.positions[symbol]

    def _check_exit_conditions(self, symbol, candle):
        if symbol not in self.positions:
            return
        trade = self.positions[symbol]
        high = candle.get("high", candle.get("close", 0))
        low = candle.get("low", candle.get("close", 0))

        if trade.side == "LONG":
            stop_price = trade.entry_price * 0.95
            tp_price = trade.entry_price * 1.10
            if low <= stop_price:
                self._close_position(symbol, stop_price, candle.get("timestamp", ""), "STOP_LOSS")
            elif high >= tp_price:
                self._close_position(symbol, tp_price, candle.get("timestamp", ""), "TAKE_PROFIT")

    def _calculate_equity(self, current_price):
        equity = self.balance
        for trade in self.positions.values():
            if trade.side == "LONG":
                unrealized = (current_price - trade.entry_price) * trade.quantity
            else:
                unrealized = (trade.entry_price - current_price) * trade.quantity
            equity += unrealized
        return equity

    def _calculate_results(self, strategy_name, symbol, data):
        total_trades = len(self.trade_history)
        if total_trades == 0:
            return BacktestResult(
                strategy_name=strategy_name, symbol=symbol,
                start_date=data[0].get("timestamp", ""), end_date=data[-1].get("timestamp", ""),
                initial_balance=self.initial_balance, final_balance=self.balance,
                total_return=0, total_return_percent=0, total_trades=0,
                winning_trades=0, losing_trades=0, win_rate=0,
                avg_win=0, avg_loss=0, profit_factor=0,
                max_drawdown=self.max_drawdown, max_drawdown_percent=self.max_drawdown_percent,
                sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0, avg_trade_duration=0,
                trades=[], equity_curve=self.equity_curve
            )

        winning_trades = [t for t in self.trade_history if t.pnl > 0]
        losing_trades = [t for t in self.trade_history if t.pnl <= 0]

        total_return = self.balance - self.initial_balance
        total_return_percent = (total_return / self.initial_balance) * 100
        win_rate = (len(winning_trades) / total_trades) * 100 if total_trades > 0 else 0
        avg_win = statistics.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = statistics.mean([t.pnl for t in losing_trades]) if losing_trades else 0

        total_wins = sum(t.pnl for t in winning_trades)
        total_losses = abs(sum(t.pnl for t in losing_trades))
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')

        returns = [t.pnl_percent for t in self.trade_history]
        if len(returns) > 1:
            avg_return = statistics.mean(returns)
            std_return = statistics.stdev(returns) if len(returns) > 1 else 0.001
            sharpe = (avg_return / std_return) * (252 ** 0.5) if std_return > 0 else 0
        else:
            sharpe = 0

        downside_returns = [r for r in returns if r < 0]
        if downside_returns:
            downside_std = statistics.stdev(downside_returns) if len(downside_returns) > 1 else 0.001
            sortino = (statistics.mean(returns) / downside_std) * (252 ** 0.5) if downside_std > 0 else 0
        else:
            sortino = sharpe

        calmar = (total_return_percent / self.max_drawdown_percent) if self.max_drawdown_percent > 0 else 0

        durations = []
        for trade in self.trade_history:
            if trade.exit_time and trade.entry_time:
                try:
                    entry = datetime.fromisoformat(trade.entry_time.replace('Z', '+00:00'))
                    exit_t = datetime.fromisoformat(trade.exit_time.replace('Z', '+00:00'))
                    durations.append((exit_t - entry).total_seconds() / 3600)
                except:
                    pass
        avg_duration = statistics.mean(durations) if durations else 0

        return BacktestResult(
            strategy_name=strategy_name, symbol=symbol,
            start_date=data[0].get("timestamp", ""), end_date=data[-1].get("timestamp", ""),
            initial_balance=self.initial_balance, final_balance=self.balance,
            total_return=total_return, total_return_percent=total_return_percent,
            total_trades=total_trades, winning_trades=len(winning_trades),
            losing_trades=len(losing_trades), win_rate=win_rate,
            avg_win=avg_win, avg_loss=avg_loss, profit_factor=profit_factor,
            max_drawdown=self.max_drawdown, max_drawdown_percent=self.max_drawdown_percent,
            sharpe_ratio=sharpe, sortino_ratio=sortino, calmar_ratio=calmar,
            avg_trade_duration=avg_duration, trades=self.trade_history, equity_curve=self.equity_curve
        )

    def compare_strategies(self, strategies, data, symbol="BTCUSDT"):
        results = []
        print("\n" + "="*60)
        print("STRATEJI KARŞILAŞTIRMASI")
        print("="*60)

        for name, strategy in strategies.items():
            result = self.run_backtest(strategy, data, name, symbol)
            results.append(result)

        results.sort(key=lambda x: x.total_return_percent, reverse=True)

        print("\n" + "="*60)
        print("SONUÇ TABLOSU")
        print("="*60)
        print(f"{'Strateji':<25} {'Getiri%':<10} {'Win%':<8} {'PF':<6} {'MaxDD%':<8} {'İşlem':<8}")
        print("-"*60)
        for r in results:
            print(f"{r.strategy_name:<25} {r.total_return_percent:>8.2f}% {r.win_rate:>6.1f}% {r.profit_factor:>4.2f} {r.max_drawdown_percent:>6.2f}% {r.total_trades:>6}")

        return results

    def export_results(self, result, filepath="backtest_result.json"):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"\n💾 Sonuçlar kaydedildi: {filepath}")

    def print_detailed_report(self, result):
        print("\n" + "="*60)
        print(f"📊 DETAYLI BACKTEST RAPORU: {result.strategy_name}")
        print("="*60)
        print(f"Sembol:              {result.symbol}")
        print(f"Tarih Aralığı:       {result.start_date[:10]} → {result.end_date[:10]}")
        print(f"Başlangıç Bakiye:    {result.initial_balance:,.2f} USDT")
        print(f"Final Bakiye:        {result.final_balance:,.2f} USDT")
        print(f"Toplam Getiri:       {result.total_return:,.2f} USDT (%{result.total_return_percent:.2f})")
        print("-"*60)
        print(f"Toplam İşlem:        {result.total_trades}")
        print(f"Kazanan:             {result.winning_trades}")
        print(f"Kaybeden:            {result.losing_trades}")
        print(f"Win Rate:            %{result.win_rate:.2f}")
        print(f"Ort. Kazanç:         {result.avg_win:,.2f} USDT")
        print(f"Ort. Kayıp:          {result.avg_loss:,.2f} USDT")
        print(f"Profit Factor:       {result.profit_factor:.2f}")
        print("-"*60)
        print(f"Max Drawdown:        {result.max_drawdown:,.2f} USDT (%{result.max_drawdown_percent:.2f})")
        print(f"Sharpe Ratio:        {result.sharpe_ratio:.2f}")
        print(f"Sortino Ratio:       {result.sortino_ratio:.2f}")
        print(f"Calmar Ratio:        {result.calmar_ratio:.2f}")
        print(f"Ort. İşlem Süresi:   {result.avg_trade_duration:.1f} saat")
        print("="*60)


def demo_strategy_random(engine, candle):
    return random.choice(["AL", "SAT", None])

def demo_strategy_trend_following(engine, candle):
    close = candle.get("close", 0)
    if not hasattr(engine, '_prev_close'):
        engine._prev_close = close
        return None
    change = (close - engine._prev_close) / engine._prev_close
    engine._prev_close = close
    if change > 0.005:
        return "AL"
    elif change < -0.005:
        return "SAT"
    return None

def demo_strategy_mean_reversion(engine, candle):
    close = candle.get("close", 0)
    if not hasattr(engine, '_prices'):
        engine._prices = []
    engine._prices.append(close)
    if len(engine._prices) < 20:
        return None
    sma = sum(engine._prices[-20:]) / 20
    if close < sma * 0.98:
        return "AL"
    elif close > sma * 1.02:
        return "SAT"
    return None


if __name__ == "__main__":
    print("🚀 Atlas AI Backtesting Engine v1.1 - Test Modu")
    print("="*60)

    engine = BacktestEngine(initial_balance=10000.0, commission_rate=0.001, slippage=0.0005)

    # GERCEK VERI YUKLE
    data = engine.load_historical_data("data/btcusdt_1h.json", "BTCUSDT")

    print("\n" + "="*60)
    print("TEK STRATEJI TESTI")
    print("="*60)

    result = engine.run_backtest(demo_strategy_trend_following, data, "Trend Following v1", "BTCUSDT")
    engine.print_detailed_report(result)
    engine.export_results(result, "backtest_trend_following.json")

    print("\n" + "="*60)
    print("COKLU STRATEJI KARŞILAŞTIRMASI")
    print("="*60)

    strategies = {
        "Random": demo_strategy_random,
        "Trend Following": demo_strategy_trend_following,
        "Mean Reversion": demo_strategy_mean_reversion,
    }

    results = engine.compare_strategies(strategies, data, "BTCUSDT")

    if results:
        best = results[0]
        engine.export_results(best, "backtest_best_strategy.json")
        print(f"\n🏆 En iyi strateji: {best.strategy_name} (%{best.total_return_percent:.2f} getiri)")

    print("\n✅ Test tamamlandi!")

