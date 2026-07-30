import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, List
from enum import Enum
import json


class RiskProfile(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class CoinConfig:
    symbol: str
    allocation_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    leverage: float = 1.0


@dataclass
class RiskProfileConfig:
    name: str
    total_balance: float
    max_positions: int
    max_daily_loss_pct: float
    position_size_pct: float
    coins: List[CoinConfig]
    
    def get_coin_symbols(self):
        return [c.symbol for c in self.coins]


RISK_PROFILES = {
    RiskProfile.LOW: RiskProfileConfig(
        name="Conservative",
        total_balance=10000.0,
        max_positions=3,
        max_daily_loss_pct=0.02,
        position_size_pct=0.10,
        coins=[
            CoinConfig("BTCUSDT", 0.50, 0.03, 0.06),
            CoinConfig("ETHUSDT", 0.30, 0.04, 0.08),
            CoinConfig("BNBUSDT", 0.20, 0.05, 0.10),
        ]
    ),
    RiskProfile.MEDIUM: RiskProfileConfig(
        name="Balanced",
        total_balance=10000.0,
        max_positions=5,
        max_daily_loss_pct=0.05,
        position_size_pct=0.15,
        coins=[
            CoinConfig("BTCUSDT", 0.30, 0.04, 0.10),
            CoinConfig("ETHUSDT", 0.25, 0.05, 0.12),
            CoinConfig("BNBUSDT", 0.15, 0.06, 0.15),
            CoinConfig("SOLUSDT", 0.15, 0.08, 0.20),
            CoinConfig("ADAUSDT", 0.15, 0.10, 0.25),
        ]
    ),
    RiskProfile.HIGH: RiskProfileConfig(
        name="Aggressive",
        total_balance=10000.0,
        max_positions=6,
        max_daily_loss_pct=0.10,
        position_size_pct=0.20,
        coins=[
            CoinConfig("BTCUSDT", 0.20, 0.05, 0.15),
            CoinConfig("ETHUSDT", 0.20, 0.06, 0.18),
            CoinConfig("SOLUSDT", 0.20, 0.10, 0.30),
            CoinConfig("BNBUSDT", 0.15, 0.08, 0.25),
            CoinConfig("ADAUSDT", 0.15, 0.12, 0.35),
            CoinConfig("XRPUSDT", 0.10, 0.15, 0.40),
        ]
    ),
}


class MultiCoinScanner:
    def __init__(self, symbols=None):
        self.symbols = symbols or ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]
        self.price_data = {}
        self.signals = {}
        
    def scan_all(self, data_provider_func=None):
        results = {}
        for symbol in self.symbols:
            try:
                df = data_provider_func(symbol) if data_provider_func else self._generate_mock_data(symbol)
                self.price_data[symbol] = df
                signal = self._generate_signal(df)
                self.signals[symbol] = signal
                results[symbol] = {
                    "signal": signal,
                    "price": df["close"].iloc[-1],
                    "change_24h": self._calc_change(df, 288),
                    "rsi": self._calc_rsi(df),
                    "volume": df["volume"].iloc[-1],
                }
            except Exception as e:
                results[symbol] = {"error": str(e)}
        return results
    
    def _generate_mock_data(self, symbol, periods=5000):
        np.random.seed(hash(symbol) % 2**32)
        dates = pd.date_range(end=datetime.now(), periods=periods, freq="5min")
        base_prices = {"BTCUSDT": 65000, "ETHUSDT": 3500, "BNBUSDT": 600,
                       "SOLUSDT": 150, "ADAUSDT": 0.45, "XRPUSDT": 0.60}
        base = base_prices.get(symbol, 100)
        returns = np.random.normal(0.0001, 0.02, periods)
        prices = base * np.exp(np.cumsum(returns))
        df = pd.DataFrame({
            "timestamp": dates,
            "open": prices * (1 + np.random.normal(0, 0.001, periods)),
            "high": prices * (1 + abs(np.random.normal(0, 0.01, periods))),
            "low": prices * (1 - abs(np.random.normal(0, 0.01, periods))),
            "close": prices,
            "volume": np.random.uniform(100, 10000, periods) * base,
        })
        return df
    
    def _generate_signal(self, df):
        if len(df) < 50:
            return "HOLD"
        sma20 = df["close"].rolling(20).mean().iloc[-1]
        sma50 = df["close"].rolling(50).mean().iloc[-1]
        rsi = self._calc_rsi(df)
        if sma20 > sma50 and rsi < 70:
            return "BUY"
        elif sma20 < sma50 and rsi > 30:
            return "SELL"
        return "HOLD"
    
    def _calc_rsi(self, df, period=14):
        if len(df) < period + 1:
            return 50.0
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]
    
    def _calc_change(self, df, periods):
        if len(df) < periods:
            return 0.0
        return (df["close"].iloc[-1] - df["close"].iloc[-periods]) / df["close"].iloc[-periods]


class PortfolioAllocator:
    def __init__(self, risk_profile):
        self.config = risk_profile
        self.allocations = {}
        self._calculate_allocations()
    
    def _calculate_allocations(self):
        for coin in self.config.coins:
            self.allocations[coin.symbol] = self.config.total_balance * coin.allocation_pct
    
    def get_position_size(self, symbol):
        return self.allocations.get(symbol, 0) * self.config.position_size_pct
    
    def get_stop_loss(self, symbol, entry_price):
        for coin in self.config.coins:
            if coin.symbol == symbol:
                return entry_price * (1 - coin.stop_loss_pct)
        return entry_price * 0.95
    
    def get_take_profit(self, symbol, entry_price):
        for coin in self.config.coins:
            if coin.symbol == symbol:
                return entry_price * (1 + coin.take_profit_pct)
        return entry_price * 1.10


@dataclass
class Trade:
    symbol: str
    entry_price: float
    exit_price: float = 0.0
    quantity: float = 0.0
    side: str = "LONG"
    entry_time: datetime = None
    exit_time: datetime = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    status: str = "OPEN"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    
    def close(self, exit_price, exit_time):
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.pnl = (exit_price - self.entry_price) * self.quantity
        self.pnl_pct = (exit_price - self.entry_price) / self.entry_price
        self.status = "CLOSED"


class BacktestEngine:
    def __init__(self, risk_profile, start_date=None, end_date=None):
        self.risk_config = RISK_PROFILES[risk_profile]
        self.scanner = MultiCoinScanner(self.risk_config.get_coin_symbols())
        self.allocator = PortfolioAllocator(self.risk_config)
        self.trades = []
        self.equity_curve = []
        self.daily_returns = []
        self.current_balance = self.risk_config.total_balance
        self.start_date = start_date or (datetime.now() - timedelta(days=30))
        self.end_date = end_date or datetime.now()
        
    def run_backtest(self, data_dict=None):
        print("")
        print("[BACKTEST] " + self.risk_config.name + " Profile")
        print("   Balance: $" + str(round(self.risk_config.total_balance, 2)))
        sd = self.start_date.strftime("%Y-%m-%d")
        ed = self.end_date.strftime("%Y-%m-%d")
        print("   Date: " + sd + " to " + ed)
        syms = ", ".join(self.risk_config.get_coin_symbols())
        print("   Coins: " + syms)
        print("-" * 60)
        
        if data_dict:
            self.scanner.price_data = data_dict
        else:
            for symbol in self.risk_config.get_coin_symbols():
                self.scanner.price_data[symbol] = self.scanner._generate_mock_data(symbol)
        
        results_by_coin = {}
        for symbol in self.risk_config.get_coin_symbols():
            df = self.scanner.price_data[symbol]
            df = df[(df["timestamp"] >= self.start_date) & (df["timestamp"] <= self.end_date)]
            if len(df) < 50:
                continue
            coin_result = self._backtest_coin(symbol, df)
            results_by_coin[symbol] = coin_result
        
        total_pnl = sum(r["total_pnl"] for r in results_by_coin.values())
        total_trades = sum(r["total_trades"] for r in results_by_coin.values())
        win_trades = sum(r["win_trades"] for r in results_by_coin.values())
        
        final_balance = self.risk_config.total_balance + total_pnl
        total_return = (final_balance - self.risk_config.total_balance) / self.risk_config.total_balance
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
        
        if len(self.daily_returns) > 1:
            avg_return = np.mean(self.daily_returns)
            std_return = np.std(self.daily_returns)
            sharpe = (avg_return / std_return) * np.sqrt(365) if std_return > 0 else 0
        else:
            sharpe = 0
        
        equity = [self.risk_config.total_balance]
        for r in results_by_coin.values():
            equity.extend(r.get("equity", []))
        max_dd = self._calc_max_drawdown(equity)
        
        summary = {
            "profile": self.risk_config.name,
            "initial_balance": self.risk_config.total_balance,
            "final_balance": final_balance,
            "total_pnl": total_pnl,
            "total_return_pct": total_return * 100,
            "total_trades": total_trades,
            "win_trades": win_trades,
            "loss_trades": total_trades - win_trades,
            "win_rate": win_rate,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_dd * 100,
            "results_by_coin": results_by_coin,
        }
        return summary
    
    def _backtest_coin(self, symbol, df):
        trades = []
        equity = [self.allocator.allocations.get(symbol, 0)]
        position = None
        
        for i in range(50, len(df)):
            current = df.iloc[i]
            sma20 = df["close"].iloc[i-20:i].mean()
            sma50 = df["close"].iloc[i-50:i].mean()
            
            if position is None:
                if sma20 > sma50:
                    position_size = self.allocator.get_position_size(symbol)
                    quantity = position_size / current["close"]
                    stop_loss = self.allocator.get_stop_loss(symbol, current["close"])
                    take_profit = self.allocator.get_take_profit(symbol, current["close"])
                    position = Trade(
                        symbol=symbol,
                        entry_price=current["close"],
                        quantity=quantity,
                        entry_time=current["timestamp"],
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                    )
            else:
                if current["low"] <= position.stop_loss:
                    position.close(position.stop_loss, current["timestamp"])
                    trades.append(position)
                    position = None
                elif current["high"] >= position.take_profit:
                    position.close(position.take_profit, current["timestamp"])
                    trades.append(position)
                    position = None
                elif sma20 < sma50:
                    position.close(current["close"], current["timestamp"])
                    trades.append(position)
                    position = None
            
            if trades:
                equity.append(self.allocator.allocations.get(symbol, 0) + sum(t.pnl for t in trades))
        
        if position:
            position.close(df["close"].iloc[-1], df["timestamp"].iloc[-1])
            trades.append(position)
        
        total_pnl = sum(t.pnl for t in trades)
        win_trades = sum(1 for t in trades if t.pnl > 0)
        
        return {
            "total_trades": len(trades),
            "win_trades": win_trades,
            "loss_trades": len(trades) - win_trades,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(trades) if trades else 0,
            "equity": equity,
        }
    
    def _calc_max_drawdown(self, equity):
        if not equity:
            return 0.0
        peak = equity[0]
        max_dd = 0
        for val in equity:
            if val > peak:
                peak = val
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd


class BacktestReport:
    @staticmethod
    def print_report(summary):
        print("")
        print("=" * 60)
        print("BACKTEST REPORT - " + summary["profile"].upper())
        print("=" * 60)
        print("Start Balance:    $" + str(round(summary["initial_balance"], 2)))
        print("End Balance:      $" + str(round(summary["final_balance"], 2)))
        print("Total Return:      " + str(round(summary["total_return_pct"], 2)) + "%")
        print("Total PnL:        $" + str(round(summary["total_pnl"], 2)))
        print("Total Trades:     " + str(summary["total_trades"]))
        print("Winners:          " + str(summary["win_trades"]))
        print("Losers:           " + str(summary["loss_trades"]))
        print("Win Rate:         " + str(round(summary["win_rate"], 1)) + "%")
        print("Sharpe Ratio:     " + str(round(summary["sharpe_ratio"], 2)))
        print("Max Drawdown:     " + str(round(summary["max_drawdown_pct"], 2)) + "%")
        print("-" * 60)
        print("RESULTS BY COIN:")
        print("-" * 60)
        for symbol, result in summary["results_by_coin"].items():
            line = "  " + symbol.ljust(10) + " | Trades: " + str(result["total_trades"]).rjust(3) + " | "
            line += "PnL: $" + str(round(result["total_pnl"], 2)).rjust(8) + " | "
            line += "Win: " + str(result["win_trades"]).rjust(2) + "/" + str(result["loss_trades"]).rjust(2)
            print(line)
        print("=" * 60)
    
    @staticmethod
    def to_json(summary, filepath):
        with open(filepath, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print("")
        print("Report saved: " + filepath)


if __name__ == "__main__":
    engine = BacktestEngine(RiskProfile.MEDIUM)
    result = engine.run_backtest()
    BacktestReport.print_report(result)