"""
Atlas AI - Backtest Engine v3.0
Aşama 3.1: Profesyonel strateji test motoru.

Özellikler:
- Transaction cost (komisyon + slippage)
- Realistic execution (market/limit emir)
- Position sizing (fixed fractional, Kelly)
- Risk metrics (Sharpe, Sortino, Calmar, VaR, Max Drawdown)
- Portfolio tracking (her işlem detaylı)
- Equity curve (zaman serisi kar/zarar)
- Walk-forward ready yapı
"""

import json
import math
import random
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict

@dataclass
class BacktestConfig:
    """Backtest konfigürasyonu"""
    initial_capital: float = 10000.0
    commission_pct: float = 0.001
    commission_per_order: float = 0.0
    slippage_pct: float = 0.0005
    max_slippage_pct: float = 0.01
    risk_per_trade: float = 0.01
    max_position_size_pct: float = 0.3
    max_positions: int = 10
    use_market_orders: bool = True
    fill_at_worst_price: bool = True
    max_holding_bars: int = 100

    def to_dict(self):
        return asdict(self)

from typing import Dict, List, Optional, Tuple, Any, Callable
from enum import Enum
from pathlib import Path

logger = logging.getLogger("AtlasAI.Backtest")


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class TradeSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ExitReason(Enum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    TIME_EXIT = "time_exit"
    SIGNAL_REVERSE = "signal_reverse"
    MANUAL = "manual"


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    """Tek bir işlemin detaylı kaydı"""
    trade_id: int
    symbol: str
    side: str  # LONG | SHORT
    entry_time: str
    exit_time: Optional[str] = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    position_size: float = 0.0  # Coin miktarı
    position_value: float = 0.0  # USDT değeri
    leverage: float = 1.0

    # Maliyetler
    commission: float = 0.0
    slippage: float = 0.0
    total_cost: float = 0.0

    # Sonuçlar
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    pnl_pct: float = 0.0

    # Risk
    stop_loss: float = 0.0
    take_profit: float = 0.0
    max_favorable_excursion: float = 0.0  # İşlem içi max kar
    max_adverse_excursion: float = 0.0   # İşlem içi max zarar

    # Çıkış
    exit_reason: str = ""
    holding_bars: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EquityPoint:
    """Equity curve noktası"""
    timestamp: str
    equity: float
    cash: float
    positions_value: float
    unrealized_pnl: float
    drawdown: float
    drawdown_pct: float
    high_water_mark: float


@dataclass
class BacktestConfig:
    """Backtest konfigürasyonu"""
    initial_capital: float = 10000.0
    commission_pct: float = 0.001  # %0.1 (Binance spot)
    commission_per_order: float = 0.0
    slippage_pct: float = 0.0005  # %0.05
    max_slippage_pct: float = 0.01

    # Risk
    risk_per_trade: float = 0.01  # Portföyün %1'i
    max_position_size_pct: float = 0.3  # Portföyün %30'u
    max_positions: int = 10

    # Execution
    use_market_orders: bool = True
    fill_at_worst_price: bool = True  # Slippage simülasyonu

    # Time
    max_holding_bars: int = 100  # Otomatik kapatma

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BacktestResult:
    """Backtest sonuç raporu"""
    strategy_name: str
    symbol: str
    timeframe: str
    config: BacktestConfig

    # Temel metrikler
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    break_even_trades: int = 0
    win_rate: float = 0.0

    # Getiri
    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    avg_return_per_trade: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0

    # Risk
    max_drawdown_pct: float = 0.0
    max_drawdown_duration: int = 0  # Bar sayısı
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0

    # VaR
    var_95: float = 0.0  # 95% Value at Risk
    var_99: float = 0.0  # 99% Value at Risk

    # Seri
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # Son durum
    final_equity: float = 0.0
    peak_equity: float = 0.0

    # Detaylar
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[EquityPoint] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "config": self.config.to_dict(),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "break_even_trades": self.break_even_trades,
            "win_rate": round(self.win_rate, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "annualized_return_pct": round(self.annualized_return_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "profit_factor": round(self.profit_factor, 2),
            "expectancy": round(self.expectancy, 4),
            "var_95": round(self.var_95, 2),
            "var_99": round(self.var_99, 2),
            "final_equity": round(self.final_equity, 2),
            "peak_equity": round(self.peak_equity, 2)
        }


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class BacktestEngine:
    """
    Atlas AI Backtest Engine v3.0

    Profesyonel strateji test motoru.

    Kullanım:
        engine = BacktestEngine(config)
        engine.load_data(ohlcv_data)
        engine.set_strategy(strategy)
        result = engine.run()
    """

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()

        # Veri
        self.ohlcv: List[Dict] = []  # [{timestamp, open, high, low, close, volume}, ...]
        self.current_bar: int = 0

        # Strateji
        self.strategy = None
        self.strategy_params: Dict = {}

        # Portföy
        self.cash: float = self.config.initial_capital
        self.equity: float = self.config.initial_capital
        self.positions: Dict[str, Dict] = {}  # {symbol: position}
        self.high_water_mark: float = self.config.initial_capital

        # Kayıtlar
        self.trades: List[TradeRecord] = []
        self.equity_curve: List[EquityPoint] = []

        # İstatistikler
        self.consecutive_wins: int = 0
        self.consecutive_losses: int = 0
        self.max_consecutive_wins: int = 0
        self.max_consecutive_losses: int = 0

        logger.info("Backtest Engine v3.0 başlatıldı.")

    def load_data(self, ohlcv_data: List[Dict]):
        """
        OHLCV verisini yükle.

        Args:
            ohlcv_data: [{timestamp, open, high, low, close, volume}, ...]
        """
        self.ohlcv = ohlcv_data
        logger.info(f"Veri yüklendi: {len(ohlcv_data)} bar.")

    def set_strategy(self, strategy, params: Dict = None):
        """
        Stratejiyi ayarla.

        Args:
            strategy: BaseStrategy türevi
            params: Strateji parametreleri
        """
        self.strategy = strategy
        self.strategy_params = params or {}
        logger.info(f"Strateji ayarlandı: {strategy.name if hasattr(strategy, 'name') else 'unknown'}")

    def _get_bar(self, index: int) -> Optional[Dict]:
        """Belirli bir bar'ı al"""
        if 0 <= index < len(self.ohlcv):
            return self.ohlcv[index]
        return None

    def _calculate_position_size(self, price: float, stop_loss: float) -> float:
        """
        Pozisyon büyüklüğü hesapla (fixed fractional).

        Risk = |entry - stop| / entry * position_size
        position_size = (equity * risk_per_trade) / (|entry - stop| / entry)
        """
        risk_amount = self.equity * self.config.risk_per_trade

        if stop_loss <= 0 or price <= 0:
            # Stop yoksa — basit yüzde
            max_value = self.equity * self.config.max_position_size_pct
            return max_value / price

        price_risk = abs(price - stop_loss) / price
        if price_risk == 0:
            price_risk = 0.01  # Minimum %1 risk

        position_value = risk_amount / price_risk

        # Maksimum limit
        max_value = self.equity * self.config.max_position_size_pct
        position_value = min(position_value, max_value)

        return position_value / price

    def _calculate_slippage(self, price: float, side: str) -> float:
        """Slippage hesapla"""
        slippage = price * self.config.slippage_pct * (1 + random.uniform(0, 1))
        slippage = min(slippage, price * self.config.max_slippage_pct)

        if side == "LONG":
            return price + slippage  # Alışta yukarı kayma
        else:
            return price - slippage  # Satışta aşağı kayma

    def _open_position(self, symbol: str, side: str, price: float, 
                       stop_loss: float, take_profit: float, bar_index: int) -> Optional[TradeRecord]:
        """Pozisyon aç"""
        # Maksimum pozisyon kontrolü
        if len(self.positions) >= self.config.max_positions:
            logger.warning("Maksimum pozisyon sayısına ulaşıldı.")
            return None

        # Pozisyon büyüklüğü
        position_size = self._calculate_position_size(price, stop_loss)
        position_value = position_size * price

        # Komisyon
        commission = position_value * self.config.commission_pct + self.config.commission_per_order

        # Slippage
        fill_price = self._calculate_slippage(price, side)
        slippage_cost = abs(fill_price - price) * position_size

        total_cost = commission + slippage_cost

        # Yeterli bakiye?
        if position_value + total_cost > self.cash:
            logger.warning("Yetersiz bakiye.")
            return None

        # Pozisyonu aç
        self.cash -= position_value + total_cost

        bar = self._get_bar(bar_index)

        trade = TradeRecord(
            trade_id=len(self.trades) + 1,
            symbol=symbol,
            side=side,
            entry_time=bar["timestamp"] if bar else datetime.now().isoformat(),
            entry_price=fill_price,
            position_size=position_size,
            position_value=position_value,
            commission=commission,
            slippage=slippage_cost,
            total_cost=total_cost,
            stop_loss=stop_loss,
            take_profit=take_profit
        )

        self.positions[symbol] = {
            "trade": trade,
            "side": side,
            "entry_price": fill_price,
            "size": position_size,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "entry_bar": bar_index,
            "max_price": fill_price,
            "min_price": fill_price
        }

        logger.info(f"[{trade.trade_id}] Pozisyon açıldı: {side} {symbol} @ {fill_price:.2f}")
        return trade

    def _close_position(self, symbol: str, price: float, reason: ExitReason, 
                        bar_index: int) -> Optional[TradeRecord]:
        """Pozisyon kapat"""
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        trade = pos["trade"]

        # Slippage
        fill_price = self._calculate_slippage(price, "SHORT" if pos["side"] == "LONG" else "LONG")
        slippage_cost = abs(fill_price - price) * pos["size"]

        # Komisyon
        position_value = pos["size"] * fill_price
        commission = position_value * self.config.commission_pct + self.config.commission_per_order

        # PnL hesapla
        if pos["side"] == "LONG":
            gross_pnl = (fill_price - pos["entry_price"]) * pos["size"]
        else:
            gross_pnl = (pos["entry_price"] - fill_price) * pos["size"]

        total_cost = commission + slippage_cost + trade.total_cost  # Giriş + çıkış maliyeti
        net_pnl = gross_pnl - total_cost
        pnl_pct = (net_pnl / (pos["entry_price"] * pos["size"])) * 100 if pos["entry_price"] > 0 else 0

        # Trade kaydını güncelle
        bar = self._get_bar(bar_index)
        trade.exit_time = bar["timestamp"] if bar else datetime.now().isoformat()
        trade.exit_price = fill_price
        trade.commission += commission
        trade.slippage += slippage_cost
        trade.total_cost += total_cost
        trade.gross_pnl = gross_pnl
        trade.net_pnl = net_pnl
        trade.pnl_pct = pnl_pct
        trade.exit_reason = reason.value
        trade.holding_bars = bar_index - pos["entry_bar"]

        # Bakiyeyi güncelle
        self.cash += position_value - commission - slippage_cost

        # Seri takibi
        if net_pnl > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            self.max_consecutive_wins = max(self.max_consecutive_wins, self.consecutive_wins)
        elif net_pnl < 0:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            self.max_consecutive_losses = max(self.max_consecutive_losses, self.consecutive_losses)

        self.trades.append(trade)
        del self.positions[symbol]

        logger.info(f"[{trade.trade_id}] Pozisyon kapandı: {reason.value} | PnL: ${net_pnl:.2f}")
        return trade

    def _update_positions(self, bar: Dict, bar_index: int):
        """Açık pozisyonları güncelle — stop/take-profit kontrolü"""
        for symbol, pos in list(self.positions.items()):
            trade = pos["trade"]

            # Max excursion güncelle
            pos["max_price"] = max(pos["max_price"], bar["high"])
            pos["min_price"] = min(pos["min_price"], bar["low"])

            trade.max_favorable_excursion = max(trade.max_favorable_excursion,
                (pos["max_price"] - pos["entry_price"]) * pos["size"] if pos["side"] == "LONG" else
                (pos["entry_price"] - pos["min_price"]) * pos["size"])

            trade.max_adverse_excursion = max(trade.max_adverse_excursion,
                (pos["entry_price"] - pos["min_price"]) * pos["size"] if pos["side"] == "LONG" else
                (pos["max_price"] - pos["entry_price"]) * pos["size"])

            # Stop loss kontrolü
            if pos["side"] == "LONG" and bar["low"] <= pos["stop_loss"]:
                self._close_position(symbol, pos["stop_loss"], ExitReason.STOP_LOSS, bar_index)
                continue
            elif pos["side"] == "SHORT" and bar["high"] >= pos["stop_loss"]:
                self._close_position(symbol, pos["stop_loss"], ExitReason.STOP_LOSS, bar_index)
                continue

            # Take profit kontrolü
            if pos["side"] == "LONG" and bar["high"] >= pos["take_profit"]:
                self._close_position(symbol, pos["take_profit"], ExitReason.TAKE_PROFIT, bar_index)
                continue
            elif pos["side"] == "SHORT" and bar["low"] <= pos["take_profit"]:
                self._close_position(symbol, pos["take_profit"], ExitReason.TAKE_PROFIT, bar_index)
                continue

            # Zaman aşımı
            if bar_index - pos["entry_bar"] >= self.config.max_holding_bars:
                self._close_position(symbol, bar["close"], ExitReason.TIME_EXIT, bar_index)
                continue

    def _update_equity(self, bar: Dict, bar_index: int):
        """Equity curve'ü güncelle"""
        # Açık pozisyonların değeri
        positions_value = 0.0
        unrealized_pnl = 0.0

        for symbol, pos in self.positions.items():
            current_value = pos["size"] * bar["close"]
            positions_value += current_value

            if pos["side"] == "LONG":
                unrealized_pnl += (bar["close"] - pos["entry_price"]) * pos["size"]
            else:
                unrealized_pnl += (pos["entry_price"] - bar["close"]) * pos["size"]

        self.equity = self.cash + positions_value

        # High water mark
        if self.equity > self.high_water_mark:
            self.high_water_mark = self.equity

        # Drawdown
        drawdown = self.high_water_mark - self.equity
        drawdown_pct = (drawdown / self.high_water_mark) * 100 if self.high_water_mark > 0 else 0

        self.equity_curve.append(EquityPoint(
            timestamp=bar["timestamp"],
            equity=self.equity,
            cash=self.cash,
            positions_value=positions_value,
            unrealized_pnl=unrealized_pnl,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
            high_water_mark=self.high_water_mark
        ))

    def run(self) -> BacktestResult:
        """
        Backtest'i çalıştır.

        Returns:
            BacktestResult: Detaylı sonuç raporu
        """
        if not self.ohlcv:
            raise ValueError("Veri yüklenmemiş!")

        if not self.strategy:
            raise ValueError("Strateji ayarlanmamış!")

        logger.info(f"Backtest başlatılıyor: {len(self.ohlcv)} bar...")

        # Ana döngü
        for i in range(50, len(self.ohlcv)):  # İlk 50 bar indikatör için
            bar = self.ohlcv[i]
            self.current_bar = i

            # Pozisyonları güncelle (stop/take-profit)
            self._update_positions(bar, i)

            # Strateji sinyali üret
            closes = [b["close"] for b in self.ohlcv[:i+1]]
            highs = [b["high"] for b in self.ohlcv[:i+1]]
            lows = [b["low"] for b in self.ohlcv[:i+1]]

            indicators = self.strategy.analyze(closes, highs, lows)
            signal = self.strategy.generate_signal(indicators, bar["close"], "BTCUSDT")

            # Sinyali işle
            if signal and signal.action in ["BUY", "SELL"]:
                side = "LONG" if signal.action == "BUY" else "SHORT"

                # Ters pozisyon varsa kapat
                if "BTCUSDT" in self.positions:
                    current_pos = self.positions["BTCUSDT"]
                    if (side == "LONG" and current_pos["side"] == "SHORT") or                        (side == "SHORT" and current_pos["side"] == "LONG"):
                        self._close_position("BTCUSDT", bar["close"], ExitReason.SIGNAL_REVERSE, i)

                # Yeni pozisyon aç (eğer yoksa)
                if "BTCUSDT" not in self.positions:
                    self._open_position(
                        symbol="BTCUSDT",
                        side=side,
                        price=bar["close"],
                        stop_loss=signal.risk.stop_loss if hasattr(signal, 'risk') and signal.risk else bar["close"] * 0.98,
                        take_profit=signal.risk.take_profit if hasattr(signal, 'risk') and signal.risk else bar["close"] * 1.03,
                        bar_index=i
                    )

            # Equity güncelle
            self._update_equity(bar, i)

        # Kalan pozisyonları kapat
        final_bar = self.ohlcv[-1]
        for symbol in list(self.positions.keys()):
            self._close_position(symbol, final_bar["close"], ExitReason.MANUAL, len(self.ohlcv) - 1)

        # Sonuçları hesapla
        return self._calculate_results()

    def _calculate_results(self) -> BacktestResult:
        """Sonuç metriklerini hesapla"""
        result = BacktestResult(
            strategy_name=self.strategy.name if hasattr(self.strategy, 'name') else "unknown",
            symbol="BTCUSDT",
            timeframe="5m",
            config=self.config
        )

        # Trade istatistikleri
        result.trades = self.trades
        result.total_trades = len(self.trades)

        if result.total_trades == 0:
            return result

        wins = [t for t in self.trades if t.net_pnl > 0]
        losses = [t for t in self.trades if t.net_pnl < 0]
        break_evens = [t for t in self.trades if t.net_pnl == 0]

        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.break_even_trades = len(break_evens)
        result.win_rate = (result.winning_trades / result.total_trades) * 100

        # Getiri
        result.final_equity = self.equity
        result.peak_equity = self.high_water_mark
        result.total_return_pct = ((self.equity - self.config.initial_capital) / self.config.initial_capital) * 100

        # Yıllık getiri (basit)
        bars = len(self.ohlcv)
        if bars > 0:
            years = bars / (365 * 24 * 12)  # 5m bar = 12 bar/saat
            if years > 0:
                result.annualized_return_pct = ((self.equity / self.config.initial_capital) ** (1/years) - 1) * 100

        result.avg_return_per_trade = sum(t.net_pnl for t in self.trades) / result.total_trades
        result.avg_win = sum(t.net_pnl for t in wins) / len(wins) if wins else 0
        result.avg_loss = sum(t.net_pnl for t in losses) / len(losses) if losses else 0

        # Drawdown
        result.equity_curve = self.equity_curve
        if self.equity_curve:
            result.max_drawdown_pct = max(p.drawdown_pct for p in self.equity_curve)

            # Drawdown süresi
            in_dd = False
            dd_start = 0
            for i, p in enumerate(self.equity_curve):
                if p.drawdown_pct > 0 and not in_dd:
                    in_dd = True
                    dd_start = i
                elif p.drawdown_pct == 0 and in_dd:
                    in_dd = False
                    result.max_drawdown_duration = max(result.max_drawdown_duration, i - dd_start)

        # Sharpe Ratio
        returns = []
        for i in range(1, len(self.equity_curve)):
            if self.equity_curve[i-1].equity > 0:
                r = (self.equity_curve[i].equity - self.equity_curve[i-1].equity) / self.equity_curve[i-1].equity
                returns.append(r)

        if len(returns) > 1:
            avg_return = sum(returns) / len(returns)
            variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
            std_dev = math.sqrt(variance) if variance > 0 else 0.001

            # Annualized Sharpe (risk-free = 0)
            result.sharpe_ratio = (avg_return / std_dev) * math.sqrt(252 * 24 * 12) if std_dev > 0 else 0

            # Sortino (downside deviation only)
            downside = [r for r in returns if r < 0]
            downside_std = math.sqrt(sum(r**2 for r in downside) / len(downside)) if downside else 0.001
            result.sortino_ratio = (avg_return / downside_std) * math.sqrt(252 * 24 * 12) if downside_std > 0 else 0

        # Calmar
        if result.max_drawdown_pct > 0:
            result.calmar_ratio = result.annualized_return_pct / result.max_drawdown_pct

        # Profit Factor
        gross_profit = sum(t.net_pnl for t in wins)
        gross_loss = abs(sum(t.net_pnl for t in losses))
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

        # Expectancy
        win_prob = result.winning_trades / result.total_trades
        loss_prob = result.losing_trades / result.total_trades
        avg_win_size = result.avg_win if result.avg_win > 0 else 0.001
        avg_loss_size = abs(result.avg_loss) if result.avg_loss < 0 else 0.001
        result.expectancy = (win_prob * avg_win_size) - (loss_prob * avg_loss_size)

        # VaR
        all_returns = [t.pnl_pct for t in self.trades]
        all_returns.sort()
        if all_returns:
            result.var_95 = all_returns[int(len(all_returns) * 0.05)] if len(all_returns) >= 20 else all_returns[0]
            result.var_99 = all_returns[int(len(all_returns) * 0.01)] if len(all_returns) >= 100 else all_returns[0]

        # Seriler
        result.max_consecutive_wins = self.max_consecutive_wins
        result.max_consecutive_losses = self.max_consecutive_losses

        return result

    def export_results(self, filepath: str = "logs/backtest_result.json"):
        """Sonuçları JSON olarak dışa aktar"""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        result = self._calculate_results()

        data = {
            "export_time": datetime.now().isoformat(),
            "summary": result.to_dict(),
            "trades": [t.to_dict() for t in result.trades],
            "equity_curve": [asdict(p) for p in result.equity_curve]
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)

        logger.info(f"Sonuçlar dışa aktarıldı: {filepath}")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_backtest_engine():
    """Backtest Engine test fonksiyonu"""
    print("📊 Atlas AI Backtest Engine v3.0 - Test Mode")
    print("=" * 60)

    import random
    random.seed(42)

    # Test verisi — trend + noise
    print("\n📈 Test verisi oluşturuluyor...")
    base_price = 65000.0
    ohlcv = []

    for i in range(500):
        # Trend: İlk 250 yukarı, son 250 aşağı
        trend = 0.0008 if i < 250 else -0.0008
        noise = random.uniform(-0.003, 0.003)

        close = base_price * (1 + trend + noise)
        high = close * (1 + random.uniform(0, 0.002))
        low = close * (1 - random.uniform(0, 0.002))
        open_p = close * (1 + random.uniform(-0.001, 0.001))
        volume = random.uniform(100, 1000)

        ohlcv.append({
            "timestamp": (datetime.now() + timedelta(minutes=5*i)).isoformat(),
            "open": round(open_p, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(volume, 2)
        })

        base_price = close

    print(f"   {len(ohlcv)} bar oluşturuldu.")
    print(f"   Başlangıç: ${ohlcv[0]['close']:,.2f}")
    print(f"   Bitiş: ${ohlcv[-1]['close']:,.2f}")

    # Strateji oluştur (Strategy Base'den)
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    try:
        from strategy.strategy_base import TrendFollowingStrategy
        strategy = TrendFollowingStrategy(timeframe="5m")
    except ImportError:
        print("   ⚠️  Strategy Base bulunamadı — basit strateji kullanılıyor.")

        class SimpleStrategy:
            name = "SimpleTrend"
            def analyze(self, closes, highs=None, lows=None):
                return type('obj', (object,), {
                    'ema_20': sum(closes[-20:]) / 20 if len(closes) >= 20 else closes[-1],
                    'ema_50': sum(closes[-50:]) / 50 if len(closes) >= 50 else closes[-1],
                    'rsi': 50.0,
                    'atr': (max(highs[-20:]) - min(lows[-20:])) / 20 if highs and lows else closes[-1] * 0.02
                })()

            def generate_signal(self, indicators, current_price, symbol="BTCUSDT"):
                from dataclasses import dataclass
                @dataclass
                class FakeSignal:
                    action: str
                    confidence: float
                    risk: Any = None

                if indicators.ema_20 > indicators.ema_50 * 1.002:
                    return FakeSignal("BUY", 0.8, type('R', (), {'stop_loss': current_price * 0.98, 'take_profit': current_price * 1.03})())
                elif indicators.ema_20 < indicators.ema_50 * 0.998:
                    return FakeSignal("SELL", 0.8, type('R', (), {'stop_loss': current_price * 1.02, 'take_profit': current_price * 0.97})())
                return FakeSignal("HOLD", 0.0)

        strategy = SimpleStrategy()

    # Backtest konfigürasyonu
    config = BacktestConfig(
        initial_capital=10000.0,
        commission_pct=0.001,
        slippage_pct=0.0005,
        risk_per_trade=0.02,
        max_position_size_pct=0.5,
        max_positions=3,
        max_holding_bars=50
    )

    # Engine oluştur ve çalıştır
    print("\n🚀 Backtest başlatılıyor...")
    print("-" * 60)

    engine = BacktestEngine(config)
    engine.load_data(ohlcv)
    engine.set_strategy(strategy)

    result = engine.run()

    # Sonuçları yazdır
    print("\n" + "=" * 60)
    print("📊 BACKTEST SONUÇLARI")
    print("=" * 60)

    summary = result.to_dict()

    print(f"\n📈 Temel Metrikler:")
    print(f"   Strateji: {summary['strategy_name']}")
    print(f"   Toplam İşlem: {summary['total_trades']}")
    print(f"   Kazanan: {summary['winning_trades']} | Kaybeden: {summary['losing_trades']}")
    print(f"   Win Rate: %{summary['win_rate']}")

    print(f"\n💰 Getiri:")
    print(f"   Toplam Getiri: %{summary['total_return_pct']}")
    print(f"   Yıllık Getiri: %{summary['annualized_return_pct']}")
    print(f"   Ortalama/İşlem: ${summary['avg_return_per_trade']:.2f}")
    print(f"   Ortalama Kazanç: ${summary['avg_win']:.2f}")
    print(f"   Ortalama Kayıp: ${summary['avg_loss']:.2f}")

    print(f"\n⚠️  Risk:")
    print(f"   Max Drawdown: %{summary['max_drawdown_pct']}")
    print(f"   Sharpe Ratio: {summary['sharpe_ratio']}")
    print(f"   Sortino Ratio: {summary['sortino_ratio']}")
    print(f"   Calmar Ratio: {summary['calmar_ratio']}")
    print(f"   Profit Factor: {summary['profit_factor']}")
    print(f"   Expectancy: ${summary['expectancy']:.4f}")
    print(f"   VaR 95%: %{summary['var_95']}")
    print(f"   VaR 99%: %{summary['var_99']}")

    print(f"\n📊 Seriler:")
    print(f"   Max Ardışık Kazanç: {summary['max_consecutive_wins']}")
    print(f"   Max Ardışık Kayıp: {summary['max_consecutive_losses']}")

    print(f"\n💵 Son Durum:")
    print(f"   Başlangıç: $10,000.00")
    print(f"   Bitiş: ${summary['final_equity']:,.2f}")
    print(f"   Zirve: ${summary['peak_equity']:,.2f}")

    # Son 5 işlem
    print(f"\n📜 Son 5 İşlem:")
    for t in result.trades[-5:]:
        emoji = "🟢" if t.net_pnl > 0 else "🔴"
        print(f"   {emoji} #{t.trade_id} {t.side} | Giriş: ${t.entry_price:,.2f} → Çıkış: ${t.exit_price:,.2f} | PnL: ${t.net_pnl:+.2f} ({t.pnl_pct:+.2f}%)")

    # Export
    print("\n💾 Sonuçlar dışa aktarılıyor...")
    engine.export_results("logs/backtest_result.json")

    print("\n" + "=" * 60)
    print("✅ Backtest Engine v3.0 test completed!")
    return result


if __name__ == "__main__":
    test_backtest_engine()
