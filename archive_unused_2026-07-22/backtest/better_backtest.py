"""
Atlas AI - Better Backtest
Daha fazla islem yapan, daha esnek stratejiler.
"""

import os
import json
import statistics
from pathlib import Path
from datetime import datetime

# Proje klasorunu bul
def find_project_dir():
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / "data").exists() or (parent / "core").exists():
            return parent
    return current

PROJECT_DIR = find_project_dir()
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

print(f"Proje klasoru: {PROJECT_DIR}")
print(f"Veri klasoru: {DATA_DIR}")

# Mevcut dosyalari listele
print(f"\nMevcut veri dosyalari:")
for f in DATA_DIR.glob("*.json"):
    print(f"   {f.name}")


# ============ TEKNIK GOSTERGELER ============
def sma(prices, period):
    if len(prices) < period: return []
    return [sum(prices[i:i+period])/period for i in range(len(prices)-period+1)]

def ema(prices, period):
    if len(prices) < period: return []
    mult = 2/(period+1)
    vals = [sum(prices[:period])/period]
    for p in prices[period:]:
        vals.append((p-vals[-1])*mult+vals[-1])
    return vals

def rsi(prices, period=14):
    if len(prices) < period+1: return []
    deltas = [prices[i]-prices[i-1] for i in range(1,len(prices))]
    gains = [d if d>0 else 0 for d in deltas]
    losses = [-d if d<0 else 0 for d in deltas]
    avg_g = sum(gains[:period])/period
    avg_l = sum(losses[:period])/period
    vals = []
    for i in range(period, len(gains)):
        avg_g = (avg_g*(period-1)+gains[i])/period
        avg_l = (avg_l*(period-1)+losses[i])/period
        vals.append(100 if avg_l==0 else 100-(100/(1+avg_g/avg_l)))
    return vals

def bollinger(prices, period=20, std_dev=2.0):
    if len(prices) < period: return {"upper":[], "middle":[], "lower":[]}
    u, m, l = [], [], []
    for i in range(period-1, len(prices)):
        w = prices[i-period+1:i+1]
        s = sum(w)/period
        v = sum((p-s)**2 for p in w)/period
        d = v**0.5
        m.append(s)
        u.append(s+std_dev*d)
        l.append(s-std_dev*d)
    return {"upper":u, "middle":m, "lower":l}

def macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow: return {"macd":[], "signal":[], "histogram":[]}
    ef = ema(prices, fast)
    es = ema(prices, slow)
    si = slow-fast
    ml = [ef[i+si]-es[i] for i in range(len(es))]
    sl = ema(ml, signal)
    hs = len(ml)-len(sl)
    h = [ml[i+hs]-sl[i] for i in range(len(sl))]
    return {"macd":ml[len(ml)-len(sl):], "signal":sl, "histogram":h}


# ============ STRATEJI SINIFLARI ============
class StrategyBase:
    def __init__(self):
        self._prices = []

class AdvancedStrategy(StrategyBase):
    """Daha esnek kosullar - daha fazla islem"""
    def __call__(self, candle):
        close = candle.get("close", 0)
        self._prices.append(close)
        if len(self._prices) < 40: return None

        prices = self._prices
        rsi_vals = rsi(prices, 14)
        bb = bollinger(prices, 20, 2.0)
        macd_data = macd(prices, 12, 26, 9)

        if not rsi_vals or not bb["upper"] or not macd_data["macd"]:
            return None

        r = rsi_vals[-1]
        u = bb["upper"][-1]
        l = bb["lower"][-1]
        mc = macd_data["macd"][-1]
        ms = macd_data["signal"][-1]

        # Daha esnek kosullar
        if r < 40 and close < l * 1.005 and mc > ms: return "AL"
        if r > 60 and close > u * 0.995 and mc < ms: return "SAT"
        return None

class SMACrossStrategy(StrategyBase):
    def __call__(self, candle):
        close = candle.get("close", 0)
        self._prices.append(close)
        if len(self._prices) < 55: return None
        prices = self._prices
        s20 = [sum(prices[i:i+20])/20 for i in range(len(prices)-20+1)]
        s50 = [sum(prices[i:i+50])/50 for i in range(len(prices)-50+1)]
        if not s20 or not s50: return None
        if s20[-1] > s50[-1] and s20[-2] <= s50[-2]: return "AL"
        if s20[-1] < s50[-1] and s20[-2] >= s50[-2]: return "SAT"
        return None

class MeanReversionStrategy(StrategyBase):
    def __call__(self, candle):
        close = candle.get("close", 0)
        self._prices.append(close)
        if len(self._prices) < 20: return None
        prices = self._prices
        s = sum(prices[-20:])/20
        if close < s*0.985: return "AL"
        if close > s*1.015: return "SAT"
        return None

class RSIStrategy(StrategyBase):
    """Sadece RSI bazli strateji"""
    def __call__(self, candle):
        close = candle.get("close", 0)
        self._prices.append(close)
        if len(self._prices) < 15: return None
        prices = self._prices
        rsi_vals = rsi(prices, 14)
        if not rsi_vals: return None
        r = rsi_vals[-1]
        if r < 30: return "AL"
        if r > 70: return "SAT"
        return None

class BollingerStrategy(StrategyBase):
    """Sadece Bollinger bazli strateji"""
    def __call__(self, candle):
        close = candle.get("close", 0)
        self._prices.append(close)
        if len(self._prices) < 25: return None
        prices = self._prices
        bb = bollinger(prices, 20, 2.0)
        if not bb["upper"]: return None
        if close < bb["lower"][-1]: return "AL"
        if close > bb["upper"][-1]: return "SAT"
        return None


# ============ BACKTEST ============
def backtest(strategy, data, name="Strategy", symbol="BTCUSDT"):
    balance = 10000.0
    position = None
    entry_price = 0
    trades = []
    equity = [(data[0]["timestamp"], balance)]
    peak = balance
    max_dd = 0.0

    print(f"\n{name} backtest basliyor...")

    for candle in data:
        close = candle.get("close", 0)
        ts = candle.get("timestamp", "")

        signal = strategy(candle)

        if signal == "AL" and position is None:
            position = "LONG"
            entry_price = close
        elif signal == "SAT" and position == "LONG":
            qty = (balance * 0.02) / entry_price
            pnl = (close - entry_price) * qty
            balance += pnl
            trades.append({"pnl": pnl, "win": pnl > 0})
            position = None

        eq = balance
        if position:
            qty = (balance * 0.02) / entry_price
            eq += (close - entry_price) * qty

        equity.append((ts, eq))

        if eq > peak:
            peak = eq
        else:
            dd = peak - eq
            if dd > max_dd:
                max_dd = dd

    if position:
        qty = (balance * 0.02) / entry_price
        pnl = (data[-1]["close"] - entry_price) * qty
        balance += pnl
        trades.append({"pnl": pnl, "win": pnl > 0})

    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]

    ret = ((balance - 10000) / 10000) * 100
    wr = (len(wins) / len(trades) * 100) if trades else 0
    pf = abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses)) if losses and sum(t["pnl"] for t in losses) != 0 else float('inf')
    dd_pct = (max_dd / peak) * 100 if peak > 0 else 0

    print(f"Tamamlandi! Getiri:%{ret:.2f}, Win:%{wr:.1f}, PF:{pf:.2f}, DD:%{dd_pct:.2f}, Islem:{len(trades)}")

    return {
        "name": name, "symbol": symbol, "return": ret, "win_rate": wr,
        "profit_factor": pf, "max_drawdown": dd_pct, "trades": len(trades),
        "balance": balance, "equity": equity
    }


# ============ ANA PROGRAM ============
print("="*70)
print("ATLAS AI - GELISTIRILMIS BACKTEST")
print("Daha fazla islem, daha esnek stratejiler")
print("="*70)

# Dosya isimlerini bul
symbol_files = {}
for f in DATA_DIR.glob("*.json"):
    name = f.name.lower()
    if "btc" in name:
        symbol_files["BTCUSDT"] = f
    elif "eth" in name:
        symbol_files["ETHUSDT"] = f
    elif "sol" in name:
        symbol_files["SOLUSDT"] = f

if not symbol_files:
    print("\n❌ Hic veri dosyasi bulunamadi!")
    print(f"   {DATA_DIR} klasorunu kontrol et.")
    exit()

strategies = {
    "Advanced (RSI+BB+MACD)": AdvancedStrategy(),
    "SMA Crossover": SMACrossStrategy(),
    "Mean Reversion": MeanReversionStrategy(),
    "RSI Only": RSIStrategy(),
    "Bollinger Only": BollingerStrategy()
}

all_results = []

for symbol, filepath in symbol_files.items():
    with open(filepath, 'rb') as f:
        raw = f.read()
        if raw.startswith(b'\xef\xbb\xbf'):
            raw = raw[3:]
        data = json.loads(raw.decode('utf-8'))

    print(f"\n{'='*70}")
    print(f"SEMBOL: {symbol} | {len(data)} mum")
    print(f"Tarih: {data[0]['timestamp'][:10]} -> {data[-1]['timestamp'][:10]}")
    print(f"Fiyat: {data[0]['close']:,.2f} -> {data[-1]['close']:,.2f}")
    print(f"Degisim: %{((data[-1]['close']-data[0]['close'])/data[0]['close'])*100:.2f}")
    print("="*70)

    for sname, strat in strategies.items():
        result = backtest(strat, data, sname, symbol)
        all_results.append(result)

# Sonuclari karsilastir
print("\n" + "="*70)
print("GENEL SONUC TABLOSU")
print("="*70)
print(f"{'Sembol':<10} {'Strateji':<25} {'Getiri%':<10} {'Win%':<8} {'PF':<6} {'DD%':<8} {'Islem':<8}")
print("-"*70)

for r in sorted(all_results, key=lambda x: x["return"], reverse=True):
    print(f"{r['symbol']:<10} {r['name']:<25} {r['return']:>8.2f}% {r['win_rate']:>6.1f}% {r['profit_factor']:>4.2f} {r['max_drawdown']:>6.2f}% {r['trades']:>6}")

# En iyi strateji
if all_results:
    best = max(all_results, key=lambda x: x["return"])
    print(f"\n🏆 EN IYI: {best['name']} @ {best['symbol']}")
    print(f"   Getiri: %{best['return']:.2f}")
    print(f"   Win Rate: %{best['win_rate']:.1f}")
    print(f"   Profit Factor: {best['profit_factor']:.2f}")
    print(f"   Islem Sayisi: {best['trades']}")

print("\n✅ Tamamlandi!")

