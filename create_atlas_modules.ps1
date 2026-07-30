# create_atlas_modules.ps1
# Bu script, Project Atlas AI için eksik olan tüm core modüllerini tek seferde oluşturur.

Write-Host "Atlas AI modülleri oluşturuluyor..." -ForegroundColor Green

# 1. signal_fusion.py
$signal_fusion = @"
"""
core/signal_fusion.py
Sinyal Füzyonu: Teknik ve piyasa verilerini birleştirir.
"""
class SignalFusion:
    def fuse(self, tech: dict, market: dict) -> dict:
        signal = "BEKLE"
        score = 50
        rsi = tech.get("rsi", 50)
        sentiment = market.get("sentiment", "Nötr")
        
        if rsi is not None:
            if rsi < 30 and sentiment == "Pozitif":
                signal = "AL"
                score = 80
            elif rsi > 70 and sentiment == "Negatif":
                signal = "SAT"
                score = 80
        return {"signal": signal, "score": score, "tech": tech, "market": market}
"@
Set-Content -Path core\signal_fusion.py -Value $signal_fusion -Force

# 2. strategy_competition.py
$strategy_competition = @"
"""
core/strategy_competition.py
Strateji Yarışması Motoru.
"""
from core.strategy_config import StrategyConfig

class StrategyCompetition:
    def run(self, fusion: dict) -> dict:
        scores = {}
        strategies = StrategyConfig.get_all_strategies()
        for name in strategies:
            params = StrategyConfig.get_params(name)
            score = self._calculate_score(name, params, fusion)
            scores[name] = round(score, 2)
        winner = max(scores, key=scores.get)
        return {"winner": winner, "scores": scores}

    def _calculate_score(self, name, params, fusion):
        dispatch = {
            "Scalping": self._scalping,
            "Momentum": self._momentum,
            "Trend_Following": self._trend,
            "Mean_Reversion": self._mean_reversion,
            "Smart_Money_Concepts": self._smc,
            "ICT_Order_Flow": self._ict,
            "Grid_Trading": self._grid,
            "Breakout": self._breakout
        }
        handler = dispatch.get(name, lambda p, f: 50.0)
        return handler(params, fusion) * params.weight

    def _scalping(self, p, f):
        rsi = f.get("tech", {}).get("rsi", 50)
        return 85.0 if rsi < p.rsi_low or rsi > p.rsi_high else 40.0
    def _momentum(self, p, f):
        return 90.0 if f.get("tech", {}).get("adx", 25) > p.adx_threshold else 30.0
    def _trend(self, p, f):
        ema20 = f.get("tech", {}).get("ema20", 0)
        ema50 = f.get("tech", {}).get("ema50", 0)
        return 80.0 if ema20 != ema50 else 20.0
    def _mean_reversion(self, p, f):
        rsi = f.get("tech", {}).get("rsi", 50)
        return 95.0 if rsi < p.rsi_low - 10 or rsi > p.rsi_high + 10 else 10.0
    def _smc(self, p, f):
        return 88.0 if f.get("tech", {}).get("rsi", 50) < p.rsi_low else 50.0
    def _ict(self, p, f):
        return 85.0 if p.rsi_low < f.get("tech", {}).get("rsi", 50) < p.rsi_high - 5 else 40.0
    def _grid(self, p, f):
        return 90.0 if f.get("market", {}).get("volatility", 1) < p.volatility_limit else 30.0
    def _breakout(self, p, f):
        return 95.0 if f.get("tech", {}).get("adx", 25) > p.adx_threshold else 20.0
"@
Set-Content -Path core\strategy_competition.py -Value $strategy_competition -Force

# 3. confidence_engine.py
$confidence_engine = @"
"""
core/confidence_engine.py
Güven puanı hesaplar.
"""
class ConfidenceEngine:
    def calculate(self, fusion: dict, best_strategy: dict) -> float:
        score = fusion.get("score", 50)
        strategy_score = best_strategy.get("scores", {}).get(best_strategy.get("winner", ""), 0)
        return round((score + strategy_score) / 2, 2)
"@
Set-Content -Path core\confidence_engine.py -Value $confidence_engine -Force

# 4. decision_engine.py
$decision_engine = @"
"""
core/decision_engine.py
Karar motoru.
"""
class DecisionEngine:
    def decide(self, fusion: dict, confidence: float) -> dict:
        if confidence > 65 and fusion.get("signal") == "AL":
            return {"action": "BUY", "stop_loss": 0.0, "take_profit": 0.0}
        elif confidence > 65 and fusion.get("signal") == "SAT":
            return {"action": "SELL", "stop_loss": 0.0, "take_profit": 0.0}
        return {"action": "BEKLE", "stop_loss": 0.0, "take_profit": 0.0}
"@
Set-Content -Path core\decision_engine.py -Value $decision_engine -Force

# 5. capital_allocator.py
$capital_allocator = @"
"""
core/capital_allocator.py
Sermaye büyüklüğü hesaplar.
"""
class CapitalAllocator:
    def allocate(self, decision: dict, confidence: float) -> float:
        if decision.get("action") == "BEKLE":
            return 0.0
        return round((confidence / 100) * 0.1, 4)
"@
Set-Content -Path core\capital_allocator.py -Value $capital_allocator -Force

# 6. executor.py
$executor = @"
"""
core/executor.py
Emir uygulayıcı.
"""
class Executor:
    def __init__(self, trader):
        self.trader = trader
    def execute(self, symbol: str, action: str, size: float):
        if size > 0:
            self.trader.open_trade(symbol, action, size)
"@
Set-Content -Path core\executor.py -Value $executor -Force

# 7. risk_manager.py
$risk_manager = @"
"""
core/risk_manager.py
Risk yönetimi (SL/TP).
"""
class RiskManager:
    def set_stop_loss(self, symbol: str, price: float):
        pass
    def set_take_profit(self, symbol: str, price: float):
        pass
"@
Set-Content -Path core\risk_manager.py -Value $risk_manager -Force

# 8. auto_manager.py
$auto_manager = @"
"""
core/auto_manager.py
Otomatik takip.
"""
class AutoManager:
    def monitor(self):
        pass
"@
Set-Content -Path core\auto_manager.py -Value $auto_manager -Force

# 9. database.py
$database = @"
"""
core/database.py
JSON tabanlı veritabanı.
"""
import json
import os

class DatabaseManager:
    def __init__(self, file_path="data/trades.json"):
        self.file_path = file_path
        self._ensure_file()
    def _ensure_file(self):
        if not os.path.exists("data"):
            os.makedirs("data")
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                json.dump([], f)
    def save_trade(self, trade_data: dict):
        with open(self.file_path, "r") as f:
            trades = json.load(f)
        trades.append(trade_data)
        with open(self.file_path, "w") as f:
            json.dump(trades, f, indent=2)
    def get_trades(self):
        with open(self.file_path, "r") as f:
            return json.load(f)
    def save_api_keys(self, user_id, api_key, secret):
        pass
"@
Set-Content -Path core\database.py -Value $database -Force

# 10. paper_trader.py
$paper_trader = @"
"""
core/paper_trader.py
Paper Trading motoru.
"""
import datetime
from core.database import DatabaseManager

class PaperTrader:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.balance = 10000.0
    def open_trade(self, symbol: str, action: str, size: float):
        entry = self._get_price(symbol)
        trade = {"time": datetime.datetime.now().isoformat(), "symbol": symbol, "action": action, "entry": entry, "size": size}
        self.db.save_trade(trade)
        self.balance -= entry * size
        print(f"[PaperTrade] {action} {symbol} | Size: {size} | Price: {entry}")
    def _get_price(self, symbol: str):
        import requests
        try:
            return float(requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}").json()["price"])
        except:
            return 30000.0
"@
Set-Content -Path core\paper_trader.py -Value $paper_trader -Force

Write-Host "✅ Tüm modüller başarıyla oluşturuldu!" -ForegroundColor Green
Write-Host "Şimdi 'python main.py' komutunu çalıştırabilirsiniz." -ForegroundColor Cyan