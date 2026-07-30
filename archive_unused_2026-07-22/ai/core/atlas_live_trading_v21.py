# -*- coding: utf-8 -*-
"""
ATLAS LIVE TRADING ENGINE v2.1
Gercek Binance API Entegrasyonu
RSI Filtresi + Dinamik Pozisyon + Yuvarlama Duzeltmesi
"""

import json
import time
import random
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import traceback

# =============================================================================
# KONFIGURASYON v2.1
# =============================================================================

@dataclass
class LiveConfig:
    """Canli trading konfigurasyonu v2.1"""
    # API
    BINANCE_API_URL: str = "https://api.binance.com"
    BINANCE_FAPI_URL: str = "https://fapi.binance.com"

    # Trading
    PAPER_BALANCE: float = 10000.0
    MAX_POSITIONS: int = 5
    MAX_POSITION_SIZE_PCT: float = 15.0
    MIN_CONFIDENCE: float = 0.45
    RISK_PER_TRADE_PCT: float = 2.0

    # RSI Filtreleri (YENI)
    RSI_OVERBOUGHT_BLOCK: float = 78.0   # RSI > 78 = BLOCK
    RSI_OVERBOUGHT_REDUCE: float = 70.0  # RSI > 70 = REDUCE 50%
    RSI_OVERSOLD_BOOST: float = 25.0     # RSI < 25 = BOOST 50%

    # Dinamik Pozisyon (YENI)
    POS_SIZE_LOW_CONF: float = 5.0       # Guven 0.45-0.55 = %5
    POS_SIZE_MED_CONF: float = 10.0      # Guven 0.55-0.70 = %10
    POS_SIZE_HIGH_CONF: float = 15.0     # Guven 0.70+ = %15

    # Semboller
    SYMBOLS: List[str] = field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
        "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT"
    ])

    # Timeframe
    TIMEFRAME: str = "1h"
    KLINE_LIMIT: int = 100

    # Dongu
    INTERVAL_SECONDS: int = 10

    # Mod
    MODE: str = "PAPER"

    # Risk
    STOP_LOSS_PCT: float = 3.0
    TAKE_PROFIT_PCT: float = 6.0
    TRAILING_STOP_PCT: float = 1.5  # Karin %1.5 geri cekilince kapat

    # Debug
    VERBOSE: bool = True

# =============================================================================
# BINANCE API CLIENT
# =============================================================================

class BinanceClient:
    """Gercek Binance API Client - Public endpoints"""

    def __init__(self, config: LiveConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'AtlasAI/2.1',
            'Accept': 'application/json'
        })
        self.last_prices: Dict[str, float] = {}
        self.price_history: Dict[str, List[float]] = {}
        self.kline_data: Dict[str, List[Dict]] = {}
        self.request_count = 0
        self.last_request_time = time.time()

    def _rate_limit_check(self):
        """Rate limit kontrolu - 1200 istek/dakika"""
        now = time.time()
        if now - self.last_request_time > 60:
            self.request_count = 0
            self.last_request_time = now
        self.request_count += 1
        if self.request_count > 1000:  # Guvenlik marjı
            sleep_time = 60 - (now - self.last_request_time)
            if sleep_time > 0:
                print(f"[RATE LIMIT] {sleep_time:.1f}s bekleniyor...")
                time.sleep(sleep_time)
                self.request_count = 0
                self.last_request_time = time.time()

    def _get(self, endpoint: str, params: Dict = None, futures: bool = False) -> Optional[Dict]:
        """GET istegi gonder"""
        self._rate_limit_check()
        base = self.config.BINANCE_FAPI_URL if futures else self.config.BINANCE_API_URL
        url = f"{base}{endpoint}"

        try:
            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                print(f"[API RATE LIMIT] 429 - Bekleniyor...")
                time.sleep(2)
                return self._get(endpoint, params, futures)
            else:
                print(f"[API HATA] {response.status_code}: {response.text[:200]}")
                return None
        except Exception as e:
            print(f"[API HATA] {e}")
            return None

    def get_price(self, symbol: str) -> Optional[float]:
        """Sembolun anlik fiyatini cek"""
        data = self._get("/api/v3/ticker/price", {"symbol": symbol})
        if data and 'price' in data:
            price = float(data['price'])
            self.last_prices[symbol] = price

            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(price)
            if len(self.price_history[symbol]) > 200:
                self.price_history[symbol] = self.price_history[symbol][-200:]

            return price
        return self.last_prices.get(symbol)

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Kline (mum) verisi cek"""
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        data = self._get("/api/v3/klines", params)

        if not data or not isinstance(data, list):
            return []

        klines = []
        for k in data:
            klines.append({
                'timestamp': int(k[0]),
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
                'close_time': int(k[6]),
                'quote_volume': float(k[7]),
                'trades': int(k[8])
            })

        self.kline_data[symbol] = klines
        return klines

    def get_24h_stats(self, symbol: str) -> Optional[Dict]:
        """24 saatlik istatistikler"""
        return self._get("/api/v3/ticker/24hr", {"symbol": symbol})

    def get_all_prices(self) -> Dict[str, float]:
        """Tum sembollerin fiyatlari"""
        data = self._get("/api/v3/ticker/price")
        if data and isinstance(data, list):
            return {item['symbol']: float(item['price']) for item in data}
        return {}

# =============================================================================
# TEKNIK ANALIZ MOTORU v2.1 - YUVARLAMA DUZELTMESI
# =============================================================================

class TechnicalAnalyzer:
    """Gercek teknik analiz - Yuvarlama duzeltmeli"""

    def __init__(self):
        self.indicators: Dict[str, Dict] = {}

    def calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """RSI hesapla"""
        if len(closes) < period + 1:
            return 50.0

        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        if len(gains) < period:
            return 50.0

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 2)

    def calculate_ema(self, closes: List[float], period: int) -> float:
        """EMA hesapla"""
        if len(closes) < period:
            return closes[-1] if closes else 0

        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period

        for price in closes[period:]:
            ema = (price - ema) * multiplier + ema

        return ema  # Yuvarlama yok - ham deger dondur

    def calculate_sma(self, closes: List[float], period: int) -> float:
        """SMA hesapla"""
        if len(closes) < period:
            return closes[-1] if closes else 0
        return sum(closes[-period:]) / period

    def calculate_macd(self, closes: List[float]) -> Dict:
        """MACD hesapla"""
        if len(closes) < 26:
            return {'macd': 0, 'signal': 0, 'histogram': 0}

        ema12 = self.calculate_ema(closes, 12)
        ema26 = self.calculate_ema(closes, 26)
        macd_line = ema12 - ema26

        macd_values = []
        for i in range(26, len(closes)):
            e12 = self.calculate_ema(closes[:i+1], 12)
            e26 = self.calculate_ema(closes[:i+1], 26)
            macd_values.append(e12 - e26)

        signal = self.calculate_ema(macd_values, 9) if macd_values else 0
        histogram = macd_line - signal

        return {
            'macd': round(macd_line, 6),
            'signal': round(signal, 6),
            'histogram': round(histogram, 6)
        }

    def calculate_bollinger(self, closes: List[float], period: int = 20, std_dev: float = 2.0) -> Dict:
        """Bollinger Bands hesapla"""
        if len(closes) < period:
            return {'upper': closes[-1] * 1.02, 'middle': closes[-1], 'lower': closes[-1] * 0.98, 'bandwidth': 2}

        sma = self.calculate_sma(closes, period)
        variance = sum((x - sma) ** 2 for x in closes[-period:]) / period
        std = variance ** 0.5

        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        bandwidth = (std * std_dev * 2) / sma * 100 if sma > 0 else 0

        return {
            'upper': upper,
            'middle': sma,
            'lower': lower,
            'bandwidth': round(bandwidth, 4)
        }

    def calculate_atr(self, klines: List[Dict], period: int = 14) -> float:
        """ATR (Average True Range) hesapla"""
        if len(klines) < period + 1:
            return 0

        tr_values = []
        for i in range(1, len(klines)):
            high = klines[i]['high']
            low = klines[i]['low']
            prev_close = klines[i-1]['close']

            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)

            tr_values.append(max(tr1, tr2, tr3))

        return sum(tr_values[-period:]) / period

    def calculate_volume_profile(self, klines: List[Dict]) -> Dict:
        """Hacim profili"""
        if not klines:
            return {'avg': 0, 'recent': 0, 'trend': 'neutral'}

        volumes = [k['volume'] for k in klines]
        avg_vol = sum(volumes) / len(volumes)
        recent_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else avg_vol

        trend = 'increasing' if recent_vol > avg_vol * 1.2 else 'decreasing' if recent_vol < avg_vol * 0.8 else 'neutral'

        return {
            'avg': round(avg_vol, 2),
            'recent': round(recent_vol, 2),
            'trend': trend
        }

    def analyze(self, symbol: str, klines: List[Dict]) -> Dict:
        """Tum indikatorleri hesapla - Yuvarlama duzeltmeli"""
        if not klines or len(klines) < 30:
            return self._default_analysis(symbol)

        closes = [k['close'] for k in klines]
        current_price = closes[-1]

        # RSI
        rsi = self.calculate_rsi(closes)

        # EMA - Ham degerler (yuvarlama yok)
        ema9_raw = self.calculate_ema(closes, 9)
        ema21_raw = self.calculate_ema(closes, 21)
        ema50_raw = self.calculate_ema(closes, 50) if len(closes) >= 50 else ema21_raw

        # Gorsellestirme icin yuvarlama (fiyata gore)
        if current_price >= 1000:
            ema9 = round(ema9_raw, 2)
            ema21 = round(ema21_raw, 2)
            ema50 = round(ema50_raw, 2)
        elif current_price >= 100:
            ema9 = round(ema9_raw, 4)
            ema21 = round(ema21_raw, 4)
            ema50 = round(ema50_raw, 4)
        elif current_price >= 10:
            ema9 = round(ema9_raw, 6)
            ema21 = round(ema21_raw, 6)
            ema50 = round(ema50_raw, 6)
        else:
            ema9 = round(ema9_raw, 8)
            ema21 = round(ema21_raw, 8)
            ema50 = round(ema50_raw, 8)

        # MACD
        macd = self.calculate_macd(closes)

        # Bollinger - Ham degerler
        bb_raw = self.calculate_bollinger(closes)

        # Bollinger yuvarlama
        if current_price >= 1000:
            bb = {k: round(v, 2) for k, v in bb_raw.items()}
        elif current_price >= 100:
            bb = {k: round(v, 4) for k, v in bb_raw.items()}
        elif current_price >= 10:
            bb = {k: round(v, 6) for k, v in bb_raw.items()}
        else:
            bb = {k: round(v, 8) for k, v in bb_raw.items()}

        # ATR
        atr_raw = self.calculate_atr(klines)
        atr = round(atr_raw, 4)

        # Volume
        vol_profile = self.calculate_volume_profile(klines)

        # Trend tespiti - Ham degerler kullan
        trend = self._detect_trend(closes, ema9_raw, ema21_raw, ema50_raw)

        # Destek/Direnc
        support, resistance = self._find_support_resistance(klines)

        analysis = {
            'symbol': symbol,
            'price': current_price,
            'timestamp': datetime.now().isoformat(),
            'rsi': rsi,
            'ema': {'ema9': ema9, 'ema21': ema21, 'ema50': ema50,
                    'ema9_raw': ema9_raw, 'ema21_raw': ema21_raw, 'ema50_raw': ema50_raw},
            'macd': macd,
            'bollinger': bb,
            'bollinger_raw': bb_raw,
            'atr': atr,
            'atr_raw': atr_raw,
            'atr_pct': round(atr_raw / current_price * 100, 4) if current_price > 0 else 0,
            'volume': vol_profile,
            'trend': trend,
            'support': round(support, 8),
            'resistance': round(resistance, 8),
            'price_change_24h': round((closes[-1] - closes[0]) / closes[0] * 100, 2) if closes[0] > 0 else 0
        }

        self.indicators[symbol] = analysis
        return analysis

    def _detect_trend(self, closes: List[float], ema9: float, ema21: float, ema50: float) -> str:
        """Trend tespiti - Ham degerler"""
        if len(closes) < 2:
            return 'sideways'

        price = closes[-1]

        if price > ema9 > ema21 > ema50:
            return 'strong_uptrend'
        elif price > ema9 > ema21:
            return 'uptrend'
        elif price < ema9 < ema21 < ema50:
            return 'strong_downtrend'
        elif price < ema9 < ema21:
            return 'downtrend'
        else:
            return 'sideways'

    def _find_support_resistance(self, klines: List[Dict], lookback: int = 20) -> Tuple[float, float]:
        """Basit destek/direnc"""
        if len(klines) < lookback:
            return 0, 0

        recent = klines[-lookback:]
        lows = [k['low'] for k in recent]
        highs = [k['high'] for k in recent]

        return min(lows), max(highs)

    def _default_analysis(self, symbol: str) -> Dict:
        """Varsayilan analiz"""
        return {
            'symbol': symbol,
            'price': 0,
            'timestamp': datetime.now().isoformat(),
            'rsi': 50,
            'ema': {'ema9': 0, 'ema21': 0, 'ema50': 0, 'ema9_raw': 0, 'ema21_raw': 0, 'ema50_raw': 0},
            'macd': {'macd': 0, 'signal': 0, 'histogram': 0},
            'bollinger': {'upper': 0, 'middle': 0, 'lower': 0, 'bandwidth': 0},
            'bollinger_raw': {'upper': 0, 'middle': 0, 'lower': 0, 'bandwidth': 0},
            'atr': 0,
            'atr_raw': 0,
            'atr_pct': 0,
            'volume': {'avg': 0, 'recent': 0, 'trend': 'neutral'},
            'trend': 'sideways',
            'support': 0,
            'resistance': 0,
            'price_change_24h': 0
        }

# =============================================================================
# DINAMIK AJAN SISTEMI v2.1 - RSI FILTRELI
# =============================================================================

class DynamicAgent:
    """Dinamik sinyal ureten ajan"""

    def __init__(self, name: str, agent_type: str, weight: float = 1.0):
        self.name = name
        self.agent_type = agent_type
        self.weight = weight
        self.performance = 0.0
        self.trade_count = 0
        self.win_count = 0

    def generate_signal(self, analysis: Dict) -> Tuple[str, float, str]:
        raise NotImplementedError

    def update_performance(self, result: str):
        self.trade_count += 1
        if result == 'win':
            self.win_count += 1
        self.performance = self.win_count / self.trade_count if self.trade_count > 0 else 0.0


class RSIAgent(DynamicAgent):
    """RSI tabanli teknik ajan - Filtreli"""

    def generate_signal(self, analysis: Dict) -> Tuple[str, float, str]:
        rsi = analysis.get('rsi', 50)

        if rsi < 20:
            return 'buy', 0.90, f"RSI EXTREME oversold ({rsi}) - STRONG BUY"
        elif rsi < 30:
            return 'buy', 0.75, f"RSI oversold ({rsi})"
        elif rsi < 40:
            return 'buy', 0.55, f"RSI low ({rsi})"
        elif rsi > 80:
            return 'sell', 0.90, f"RSI EXTREME overbought ({rsi}) - STRONG SELL"
        elif rsi > 70:
            return 'sell', 0.75, f"RSI overbought ({rsi})"
        elif rsi > 60:
            return 'sell', 0.55, f"RSI high ({rsi})"
        else:
            return 'hold', 0.40, f"RSI neutral ({rsi})"


class MACDAgent(DynamicAgent):
    """MACD tabanli teknik ajan"""

    def generate_signal(self, analysis: Dict) -> Tuple[str, float, str]:
        macd = analysis.get('macd', {})
        histogram = macd.get('histogram', 0)
        macd_line = macd.get('macd', 0)
        signal_line = macd.get('signal', 0)

        if histogram > 0 and macd_line > signal_line:
            if histogram > 0.5:
                return 'buy', 0.75, f"MACD strong bullish (hist: {histogram})"
            return 'buy', 0.60, f"MACD bullish (hist: {histogram})"
        elif histogram < 0 and macd_line < signal_line:
            if histogram < -0.5:
                return 'sell', 0.75, f"MACD strong bearish (hist: {histogram})"
            return 'sell', 0.60, f"MACD bearish (hist: {histogram})"
        else:
            return 'hold', 0.40, f"MACD neutral (hist: {histogram})"


class EMAAgent(DynamicAgent):
    """EMA Crossover ajan"""

    def generate_signal(self, analysis: Dict) -> Tuple[str, float, str]:
        ema = analysis.get('ema', {})
        ema9 = ema.get('ema9_raw', 0)
        ema21 = ema.get('ema21_raw', 0)
        ema50 = ema.get('ema50_raw', 0)
        price = analysis.get('price', 0)

        if ema9 > ema21 > ema50 and price > ema9:
            return 'buy', 0.80, f"Golden Cross - Strong uptrend"
        elif ema9 > ema21 and price > ema9:
            return 'buy', 0.65, f"EMA bullish"
        elif ema9 < ema21 < ema50 and price < ema9:
            return 'sell', 0.80, f"Death Cross - Strong downtrend"
        elif ema9 < ema21 and price < ema9:
            return 'sell', 0.65, f"EMA bearish"
        else:
            return 'hold', 0.40, f"EMA mixed"


class BollingerAgent(DynamicAgent):
    """Bollinger Bands ajan"""

    def generate_signal(self, analysis: Dict) -> Tuple[str, float, str]:
        bb = analysis.get('bollinger_raw', {})
        price = analysis.get('price', 0)
        upper = bb.get('upper', price * 1.02)
        lower = bb.get('lower', price * 0.98)
        bandwidth = bb.get('bandwidth', 2)

        if price <= lower:
            return 'buy', 0.75, f"Bollinger lower band touch"
        elif price < lower * 1.005:
            return 'buy', 0.60, f"Bollinger near lower band"
        elif price >= upper:
            return 'sell', 0.75, f"Bollinger upper band touch"
        elif price > upper * 0.995:
            return 'sell', 0.60, f"Bollinger near upper band"
        elif bandwidth < 1.5:
            return 'hold', 0.55, f"Bollinger squeeze - breakout expected"
        else:
            return 'hold', 0.35, f"Bollinger mid zone"


class VolumeAgent(DynamicAgent):
    """Hacim analizi ajan"""

    def generate_signal(self, analysis: Dict) -> Tuple[str, float, str]:
        vol = analysis.get('volume', {})
        trend = vol.get('trend', 'neutral')
        price_change = analysis.get('price_change_24h', 0)

        if trend == 'increasing' and price_change > 2:
            return 'buy', 0.70, f"Volume surge + uptrend (%{price_change})"
        elif trend == 'increasing' and price_change < -2:
            return 'sell', 0.70, f"Volume surge + downtrend (%{price_change})"
        elif trend == 'decreasing' and abs(price_change) < 1:
            return 'hold', 0.50, f"Low volume + sideways"
        else:
            return 'hold', 0.35, f"Volume: {trend}"


class TrendAgent(DynamicAgent):
    """Trend takip ajan"""

    def generate_signal(self, analysis: Dict) -> Tuple[str, float, str]:
        trend = analysis.get('trend', 'sideways')
        price_change = analysis.get('price_change_24h', 0)

        if trend == 'strong_uptrend':
            return 'buy', 0.85, f"Strong uptrend (+%{price_change})"
        elif trend == 'uptrend':
            return 'buy', 0.70, f"Uptrend (+%{price_change})"
        elif trend == 'strong_downtrend':
            return 'sell', 0.85, f"Strong downtrend (%{price_change})"
        elif trend == 'downtrend':
            return 'sell', 0.70, f"Downtrend (%{price_change})"
        else:
            return 'hold', 0.40, f"Sideways (%{price_change})"


class RiskAgent(DynamicAgent):
    """Risk degerlendirme ajan - RSI Filtreli"""

    def __init__(self, name: str, agent_type: str, weight: float = 1.5, config: LiveConfig = None):
        super().__init__(name, agent_type, weight)
        self.config = config or LiveConfig()

    def generate_signal(self, analysis: Dict) -> Tuple[str, float, str]:
        atr_pct = analysis.get('atr_pct', 2)
        rsi = analysis.get('rsi', 50)
        trend = analysis.get('trend', 'sideways')

        # RSI Filtreleri (YENI)
        if rsi > self.config.RSI_OVERBOUGHT_BLOCK:
            return 'avoid', 0.95, f"BLOCKED - RSI extreme overbought ({rsi})"
        elif rsi > self.config.RSI_OVERBOUGHT_REDUCE:
            return 'reduce', 0.80, f"REDUCE - RSI overbought zone ({rsi})"
        elif rsi < self.config.RSI_OVERSOLD_BOOST:
            return 'buy', 0.70, f"BOOST - RSI extreme oversold ({rsi})"

        # Volatilite riski
        if atr_pct > 5:
            return 'avoid', 0.75, f"High volatility (ATR: %{atr_pct})"
        elif atr_pct > 3:
            return 'reduce', 0.60, f"Elevated volatility (ATR: %{atr_pct})"

        # Trend riski
        if trend == 'sideways' and atr_pct > 2:
            return 'reduce', 0.50, f"Sideways + volatile"

        return 'buy', 0.50, f"Risk acceptable (ATR: %{atr_pct}, RSI: {rsi})"


# =============================================================================
# ATLAS BRAIN v2.1 - DINAMIK POZISYON + RSI FILTRE
# =============================================================================

class AtlasBrainV2:
    """Atlas Brain v2.1 - Gercek piyasa verisi + RSI Filtre + Dinamik Pozisyon"""

    def __init__(self, config: LiveConfig):
        self.config = config
        self.client = BinanceClient(config)
        self.analyzer = TechnicalAnalyzer()

        # Ajanlar
        self.agents: List[DynamicAgent] = [
            RSIAgent("RSI Master", "technical", 1.0),
            MACDAgent("MACD Expert", "technical", 1.0),
            EMAAgent("Trend Follower", "technical", 1.2),
            BollingerAgent("Bollinger Hunter", "technical", 0.9),
            VolumeAgent("Volume Analyst", "technical", 0.8),
            TrendAgent("Trend Tracker", "technical", 1.1),
            RiskAgent("Risk Guardian", "risk", 2.0, config)  # Agirlik artirildi
        ]

        # Hafiza
        self.memory: List[Dict] = []
        self.symbol_memory: Dict[str, List[Dict]] = {}

        # Performans
        self.total_trades = 0
        self.win_trades = 0
        self.loss_trades = 0

        print("[BRAIN] Atlas Brain v2.1 baslatildi")
        print(f"[BRAIN] {len(self.agents)} dinamik ajan yuklendi")
        print(f"[BRAIN] RSI Filtre: Block>{config.RSI_OVERBOUGHT_BLOCK}, Reduce>{config.RSI_OVERBOUGHT_REDUCE}")
        print(f"[BRAIN] Dinamik Pozisyon: Low={config.POS_SIZE_LOW_CONF}%, Med={config.POS_SIZE_MED_CONF}%, High={config.POS_SIZE_HIGH_CONF}%")

    def analyze_symbol(self, symbol: str) -> Optional[Dict]:
        """Sembolu analiz et"""
        klines = self.client.get_klines(symbol, self.config.TIMEFRAME, self.config.KLINE_LIMIT)

        if not klines:
            print(f"[BRAIN] {symbol} icin veri alinamadi!")
            return None

        analysis = self.analyzer.analyze(symbol, klines)

        live_price = self.client.get_price(symbol)
        if live_price:
            analysis['price'] = live_price

        return analysis

    def generate_signals(self, analysis: Dict) -> List[Dict]:
        """Tum ajanlardan sinyal al"""
        signals = []

        for agent in self.agents:
            decision, confidence, reason = agent.generate_signal(analysis)
            signals.append({
                'agent': agent.name,
                'type': agent.agent_type,
                'decision': decision,
                'confidence': confidence,
                'reason': reason,
                'weight': agent.weight,
                'performance': agent.performance
            })

        return signals

    def collective_decision(self, signals: List[Dict]) -> Tuple[str, float, str]:
        """Kolektif karar - agirlikli oylama"""
        votes = {'buy': 0, 'sell': 0, 'hold': 0, 'reduce': 0, 'avoid': 0}
        total_weight = 0

        for sig in signals:
            weight = sig['weight'] * sig['confidence']
            votes[sig['decision']] += weight
            total_weight += sig['weight']

        for key in votes:
            votes[key] = round(votes[key] / total_weight, 3) if total_weight > 0 else 0

        best_decision = max(votes, key=votes.get)
        best_score = votes[best_decision]

        reasons = [f"{s['agent']}: {s['decision']} ({s['confidence']}) - {s['reason']}" 
                   for s in signals]

        return best_decision, best_score, "\n    ".join(reasons)

    def memory_influence(self, symbol: str) -> Tuple[float, str]:
        """Gecmis performans etkisi"""
        if symbol not in self.symbol_memory or len(self.symbol_memory[symbol]) < 3:
            return 0.0, "Yetersiz gecmis veri"

        history = self.symbol_memory[symbol][-10:]
        wins = sum(1 for h in history if h.get('result') == 'win')
        total = len(history)
        win_rate = wins / total if total > 0 else 0

        if win_rate > 0.6:
            return 0.15, f"Iyi gecmis ({win_rate:.0%} win rate)"
        elif win_rate < 0.4:
            return -0.15, f"Kotu gecmis ({win_rate:.0%} win rate)"
        else:
            return 0.0, f"Notr gecmis ({win_rate:.0%} win rate)"

    def calculate_position_size(self, confidence: float, rsi: float) -> float:
        """Dinamik pozisyon boyutu - Guven + RSI bazli"""
        # Guven bazli
        if confidence >= 0.70:
            base_size = self.config.POS_SIZE_HIGH_CONF
        elif confidence >= 0.55:
            base_size = self.config.POS_SIZE_MED_CONF
        else:
            base_size = self.config.POS_SIZE_LOW_CONF

        # RSI duzeltmesi
        if rsi > self.config.RSI_OVERBOUGHT_BLOCK:
            return 0  # BLOCK
        elif rsi > self.config.RSI_OVERBOUGHT_REDUCE:
            return base_size * 0.3  # %70 azalt
        elif rsi < self.config.RSI_OVERSOLD_BOOST:
            return min(base_size * 1.5, self.config.MAX_POSITION_SIZE_PCT)  # %50 artir

        return base_size

    def final_decision(self, symbol: str, analysis: Dict, signals: List[Dict]) -> Dict:
        """Final karar - RSI Filtreli + Dinamik Pozisyon"""
        rsi = analysis.get('rsi', 50)

        # Kolektif karar
        collective, coll_conf, reasons = self.collective_decision(signals)

        # Hafiza etkisi
        memory_bonus, memory_reason = self.memory_influence(symbol)

        # Risk degerlendirmesi
        risk_signals = [s for s in signals if s['type'] == 'risk']
        risk_score = max([s['confidence'] for s in risk_signals if s['decision'] in ['avoid', 'reduce']], default=0)

        # Risk ajan karari
        risk_decision = next((s['decision'] for s in risk_signals if s['confidence'] == risk_score), 'buy')

        # Final skor
        base_score = coll_conf
        adjusted_score = base_score + memory_bonus - (risk_score * 0.3)
        adjusted_score = max(0, min(1, adjusted_score))

        # Karar mantigi - Risk oncelikli
        if risk_decision == 'avoid' and risk_score > 0.7:
            final = 'avoid'
            final_conf = adjusted_score
            position_size = 0
        elif risk_decision == 'reduce' and risk_score > 0.5:
            final = 'hold'
            final_conf = adjusted_score
            position_size = 0
        elif collective in ['buy', 'sell'] and adjusted_score >= self.config.MIN_CONFIDENCE:
            final = collective
            final_conf = adjusted_score
            position_size = self.calculate_position_size(final_conf, rsi)
        else:
            final = 'hold'
            final_conf = adjusted_score
            position_size = 0

        return {
            'symbol': symbol,
            'decision': final,
            'confidence': round(final_conf, 3),
            'position_size_pct': round(position_size, 2),
            'collective_decision': collective,
            'collective_confidence': coll_conf,
            'memory_bonus': memory_bonus,
            'risk_score': risk_score,
            'risk_decision': risk_decision,
            'rsi': rsi,
            'analysis': analysis,
            'signals': signals,
            'reasoning': reasons,
            'memory_reason': memory_reason,
            'timestamp': datetime.now().isoformat()
        }

    def update_memory(self, symbol: str, decision: Dict, result: Optional[str] = None):
        """Hafiza guncelle"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'decision': decision['decision'],
            'confidence': decision['confidence'],
            'price': decision['analysis']['price'],
            'result': result
        }

        if symbol not in self.symbol_memory:
            self.symbol_memory[symbol] = []
        self.symbol_memory[symbol].append(entry)

        if result:
            for sig in decision['signals']:
                agent = next((a for a in self.agents if a.name == sig['agent']), None)
                if agent:
                    agent.update_performance(result)

        self.memory.append(entry)

# =============================================================================
# POZISYON YONETICI v2.1 - TRAILING STOP
# =============================================================================

@dataclass
class Position:
    """Acik pozisyon - Trailing Stoplu"""
    symbol: str
    direction: str
    entry_price: float
    size_usd: float
    confidence: float
    open_time: datetime = field(default_factory=datetime.now)
    stop_loss: float = 0
    take_profit: float = 0
    trailing_stop: float = 0
    trailing_active: bool = False
    current_pnl_pct: float = 0
    current_pnl_usd: float = 0
    highest_pnl_pct: float = 0
    status: str = "OPEN"

    def update(self, current_price: float, trailing_pct: float = 1.5):
        """PnL guncelle - Trailing Stoplu"""
        if self.direction == 'LONG':
            self.current_pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
        else:
            self.current_pnl_pct = (self.entry_price - current_price) / self.entry_price * 100

        self.current_pnl_usd = self.size_usd * self.current_pnl_pct / 100

        # Highest PnL takip
        if self.current_pnl_pct > self.highest_pnl_pct:
            self.highest_pnl_pct = self.current_pnl_pct

        # Trailing Stop aktiflestirme (kar %2+ ise)
        if self.highest_pnl_pct > 2.0 and not self.trailing_active:
            self.trailing_active = True
            self.trailing_stop = self.highest_pnl_pct - trailing_pct

        # Trailing Stop guncelle
        if self.trailing_active:
            new_trailing = self.highest_pnl_pct - trailing_pct
            if new_trailing > self.trailing_stop:
                self.trailing_stop = new_trailing

            # Trailing stop tetikle
            if self.current_pnl_pct < self.trailing_stop:
                return 'trailing_stop'

        # Stop loss
        if self.current_pnl_pct <= -self.stop_loss:
            return 'stop_loss'

        # Take profit
        if self.current_pnl_pct >= self.take_profit:
            return 'take_profit'

        return None


class PositionManager:
    """Pozisyon yoneticisi v2.1"""

    def __init__(self, config: LiveConfig):
        self.config = config
        self.positions: Dict[str, Position] = {}
        self.balance = config.PAPER_BALANCE
        self.equity = config.PAPER_BALANCE
        self.trade_history: List[Dict] = []
        self.total_trades = 0
        self.win_trades = 0
        self.loss_trades = 0

    def can_open_position(self, symbol: str) -> bool:
        if len(self.positions) >= self.config.MAX_POSITIONS:
            return False
        if symbol in self.positions:
            return False
        return True

    def open_position(self, symbol: str, direction: str, price: float, 
                     confidence: float, size_pct: float) -> Optional[Position]:
        """Pozisyon ac - Dinamik boyutlu"""
        if not self.can_open_position(symbol):
            return None

        size_usd = self.equity * (size_pct / 100)
        size_usd = min(size_usd, self.balance * 0.9)

        if size_usd < 10:
            print(f"    -> Pozisyon cok kucuk: ${size_usd:.2f} (min $10)")
            return None

        sl = self.config.STOP_LOSS_PCT
        tp = self.config.TAKE_PROFIT_PCT

        pos = Position(
            symbol=symbol,
            direction=direction,
            entry_price=price,
            size_usd=size_usd,
            confidence=confidence,
            stop_loss=sl,
            take_profit=tp
        )

        self.positions[symbol] = pos
        self.balance -= size_usd
        self.total_trades += 1

        print(f"\n{'='*60}")
        print(f"POZISYON ACILDI: {symbol}")
        print(f"Yon: {direction} | Giris: ${price:,.2f}")
        print(f"Buyukluk: ${size_usd:,.2f} (%{size_pct}) | Guven: {confidence:.2f}")
        print(f"Stop Loss: %{sl} | Take Profit: %{tp} | Trailing: %{self.config.TRAILING_STOP_PCT}")
        print(f"Kalan Bakiye: ${self.balance:,.2f}")
        print(f"{'='*60}")

        return pos

    def close_position(self, symbol: str, price: float, reason: str) -> Dict:
        """Pozisyon kapat"""
        if symbol not in self.positions:
            return {}

        pos = self.positions[symbol]
        pos.update(price)

        pnl_usd = pos.current_pnl_usd
        pnl_pct = pos.current_pnl_pct

        self.balance += pos.size_usd + pnl_usd

        result = 'win' if pnl_usd > 0 else 'loss'
        if result == 'win':
            self.win_trades += 1
        else:
            self.loss_trades += 1

        trade_record = {
            'symbol': symbol,
            'direction': pos.direction,
            'entry': pos.entry_price,
            'exit': price,
            'size': pos.size_usd,
            'pnl_usd': round(pnl_usd, 2),
            'pnl_pct': round(pnl_pct, 2),
            'result': result,
            'reason': reason,
            'duration': str(datetime.now() - pos.open_time),
            'confidence': pos.confidence,
            'highest_pnl': round(pos.highest_pnl_pct, 2)
        }

        self.trade_history.append(trade_record)
        del self.positions[symbol]

        emoji = "+" if result == 'win' else "-"
        print(f"\n{'='*60}")
        print(f"POZISYON KAPANDI: {symbol} {emoji}")
        print(f"Cikis: ${price:,.2f} | PnL: ${pnl_usd:+.2f} (%{pnl_pct:+.2f})")
        print(f"En Yuksek PnL: %{pos.highest_pnl_pct:+.2f}")
        print(f"Neden: {reason}")
        print(f"Yeni Bakiye: ${self.balance:,.2f}")
        print(f"{'='*60}")

        return trade_record

    def update_positions(self, prices: Dict[str, float]):
        """Tum pozisyonlari guncelle"""
        closed = []

        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue

            current_price = prices[symbol]
            exit_reason = pos.update(current_price, self.config.TRAILING_STOP_PCT)

            if exit_reason:
                trade = self.close_position(symbol, current_price, exit_reason)
                closed.append(trade)

        # Equity guncelle
        self.equity = self.balance
        for pos in self.positions.values():
            if pos.symbol in prices:
                pos.update(prices[pos.symbol], self.config.TRAILING_STOP_PCT)
                self.equity += pos.size_usd + pos.current_pnl_usd

        return closed

    def get_portfolio_summary(self) -> Dict:
        """Portfoy ozeti"""
        total_pnl = sum(p.current_pnl_usd for p in self.positions.values())
        win_rate = (self.win_trades / self.total_trades * 100) if self.total_trades > 0 else 0

        return {
            'balance': round(self.balance, 2),
            'equity': round(self.equity, 2),
            'total_pnl': round(total_pnl, 2),
            'total_trades': self.total_trades,
            'win_trades': self.win_trades,
            'loss_trades': self.loss_trades,
            'win_rate': round(win_rate, 1),
            'open_positions': len(self.positions),
            'positions': [
                {
                    'symbol': p.symbol,
                    'direction': p.direction,
                    'entry': p.entry_price,
                    'current_pnl_pct': round(p.current_pnl_pct, 2),
                    'current_pnl_usd': round(p.current_pnl_usd, 2),
                    'size': round(p.size_usd, 2),
                    'highest_pnl': round(p.highest_pnl_pct, 2)
                }
                for p in self.positions.values()
            ]
        }

# =============================================================================
# LIVE TRADING ENGINE v2.1
# =============================================================================

class AtlasLiveTradingV2:
    """Atlas Live Trading v2.1 - RSI Filtre + Dinamik Pozisyon + Trailing Stop"""

    def __init__(self, config: Optional[LiveConfig] = None):
        self.config = config or LiveConfig()
        self.brain = AtlasBrainV2(self.config)
        self.positions = PositionManager(self.config)

        self.cycle_count = 0
        self.start_time = datetime.now()
        self.results_file = f"live_trading_v21_{self.start_time.strftime('%Y%m%d_%H%M%S')}.json"

        print(f"\n{'='*70}")
        print("ATLAS LIVE TRADING ENGINE v2.1")
        print(f"{'='*70}")
        print(f"Mod: {self.config.MODE}")
        print(f"Sermaye: ${self.config.PAPER_BALANCE:,.2f}")
        print(f"Semboller: {', '.join(self.config.SYMBOLS)}")
        print(f"Timeframe: {self.config.TIMEFRAME}")
        print(f"Min Guven: {self.config.MIN_CONFIDENCE}")
        print(f"Max Pozisyon: {self.config.MAX_POSITIONS}")
        print(f"RSI Block: >{self.config.RSI_OVERBOUGHT_BLOCK}")
        print(f"RSI Reduce: >{self.config.RSI_OVERBOUGHT_REDUCE}")
        print(f"Trailing Stop: %{self.config.TRAILING_STOP_PCT}")
        print(f"{'='*70}\n")

    def run_cycle(self) -> Dict:
        """Tek dongu calistir"""
        self.cycle_count += 1
        now = datetime.now()

        print(f"\n{'='*70}")
        print(f"DONGU #{self.cycle_count} | {now.strftime('%H:%M:%S')}")
        print(f"{'='*70}")

        results = {
            'cycle': self.cycle_count,
            'timestamp': now.isoformat(),
            'decisions': [],
            'trades': [],
            'prices': {}
        }

        # Fiyatlari cek
        prices = {}
        for symbol in self.config.SYMBOLS:
            price = self.brain.client.get_price(symbol)
            if price:
                prices[symbol] = price
                results['prices'][symbol] = price

        print(f"[FIYAT] {len(prices)} sembol canli fiyat alindi")

        # Pozisyonlari guncelle
        closed_trades = self.positions.update_positions(prices)
        results['trades'].extend(closed_trades)

        # Her sembol icin analiz
        for symbol in self.config.SYMBOLS:
            if symbol not in prices:
                continue

            print(f"\n[ANALIZ] {symbol} @ ${prices[symbol]:,.4f}")

            analysis = self.brain.analyze_symbol(symbol)
            if not analysis:
                print(f"  Uyari: Analiz yapilamadi")
                continue

            # Indikatorler
            print(f"  RSI: {analysis['rsi']} | Trend: {analysis['trend']}")
            print(f"  EMA9: {analysis['ema']['ema9']} | EMA21: {analysis['ema']['ema21']} | EMA50: {analysis['ema']['ema50']}")
            print(f"  MACD: {analysis['macd']['histogram']:.6f}")
            print(f"  BB: [{analysis['bollinger']['lower']:.4f} - {analysis['bollinger']['upper']:.4f}] (bw: {analysis['bollinger']['bandwidth']:.2f}%)")
            print(f"  ATR: %{analysis['atr_pct']:.4f} | 24h: %{analysis['price_change_24h']}")

            # Sinyaller
            signals = self.brain.generate_signals(analysis)

            print(f"  [AJANLAR]")
            for sig in signals:
                emoji = "+" if sig['decision'] == 'buy' else "-" if sig['decision'] == 'sell' else "0" if sig['decision'] == 'hold' else "!"
                print(f"    {emoji} {sig['agent']}: {sig['decision'].upper()} ({sig['confidence']}) - {sig['reason'][:55]}")

            # Karar
            decision = self.brain.final_decision(symbol, analysis, signals)

            print(f"\n  [KARAR]")
            print(f"    Kolektif: {decision['collective_decision'].upper()} ({decision['collective_confidence']})")
            print(f"    Risk: {decision['risk_decision'].upper()} ({decision['risk_score']})")
            print(f"    Hafiza: {decision['memory_bonus']:+.2f} ({decision['memory_reason']})")
            print(f"    Pozisyon Boyutu: %{decision['position_size_pct']}")
            print(f"    FINAL: {decision['decision'].upper()} (guven: {decision['confidence']})")

            results['decisions'].append(decision)

            # Pozisyon ac
            if decision['decision'] == 'buy' and decision['confidence'] >= self.config.MIN_CONFIDENCE:
                if decision['position_size_pct'] > 0:
                    if self.positions.can_open_position(symbol):
                        pos = self.positions.open_position(
                            symbol=symbol,
                            direction='LONG',
                            price=prices[symbol],
                            confidence=decision['confidence'],
                            size_pct=decision['position_size_pct']
                        )
                        if pos:
                            self.brain.update_memory(symbol, decision)
                    else:
                        print(f"    -> Pozisyon limiti dolu veya zaten acik")
                else:
                    print(f"    -> Pozisyon boyutu 0 (RSI filtresi)")
            elif decision['decision'] == 'sell' and decision['confidence'] >= self.config.MIN_CONFIDENCE:
                pass

            # Hafiza guncelle
            if decision['decision'] == 'hold':
                self.brain.update_memory(symbol, decision)

        # Portfoy
        portfolio = self.positions.get_portfolio_summary()

        print(f"\n{'='*70}")
        print("PORTFOY DURUMU")
        print(f"{'='*70}")
        print(f"Bakiye: ${portfolio['balance']:,.2f}")
        print(f"Equity: ${portfolio['equity']:,.2f}")
        print(f"Acik Pozisyon: {portfolio['open_positions']}")
        print(f"Toplam Trade: {portfolio['total_trades']} (K: {portfolio['win_trades']} / M: {portfolio['loss_trades']})")
        print(f"Win Rate: %{portfolio['win_rate']}")

        if portfolio['positions']:
            print(f"\nAcik Pozisyonlar:")
            for pos in portfolio['positions']:
                sign = "+" if pos['current_pnl_pct'] > 0 else "-" if pos['current_pnl_pct'] < 0 else "0"
                print(f"  {sign} {pos['symbol']}: {pos['direction']} | "
                      f"PnL: ${pos['current_pnl_usd']:+.2f} ({pos['current_pnl_pct']:+.2f}%) | "
                      f"En Yuksek: {pos['highest_pnl']:+.2f}%")

        print(f"{'='*70}")

        results['portfolio'] = portfolio
        self._save_results(results)

        return results

    def run(self, cycles: int = 0, interval_seconds: int = None):
        """Trading dongusunu calistir"""
        interval = interval_seconds or self.config.INTERVAL_SECONDS

        print(f"\n[TEST] {'Surekli' if cycles == 0 else cycles} donguluk paper trading...")
        print(f"[TEST] Interval: {interval}s")
        print(f"[TEST] Basliyor... (Ctrl+C ile durdur)\n")

        try:
            while True:
                self.run_cycle()

                if cycles > 0 and self.cycle_count >= cycles:
                    break

                print(f"\n[Bekle] Sonraki dongu: {interval}s...")
                time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n\n[Kullanici] Durduruldu")

        finally:
            self._final_report()

    def _save_results(self, results: Dict):
        try:
            with open(self.results_file, 'a') as f:
                f.write(json.dumps(results, default=str) + '\n')
        except:
            pass

    def _final_report(self):
        portfolio = self.positions.get_portfolio_summary()

        print(f"\n{'='*70}")
        print("FINAL RAPOR")
        print(f"{'='*70}")
        print(f"Baslangic: ${self.config.PAPER_BALANCE:,.2f}")
        print(f"Bitis: ${portfolio['equity']:,.2f}")
        print(f"Toplam PnL: ${portfolio['equity'] - self.config.PAPER_BALANCE:+.2f}")
        print(f"Toplam Trade: {portfolio['total_trades']}")
        print(f"Win Rate: %{portfolio['win_rate']}")
        print(f"Dongu Sayisi: {self.cycle_count}")
        print(f"Sure: {datetime.now() - self.start_time}")
        print(f"{'='*70}")

        prices = {}
        for symbol in self.config.SYMBOLS:
            price = self.brain.client.get_price(symbol)
            if price:
                prices[symbol] = price

        for symbol in list(self.positions.positions.keys()):
            if symbol in prices:
                self.positions.close_position(symbol, prices[symbol], 'session_end')

        print(f"\n[LIVE] Sonuclar kaydedildi: {self.results_file}")
        print(f"[LIVE] Atlas Live Trading v2.1 tamamlandi!")


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    config = LiveConfig(
        SYMBOLS=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
        INTERVAL_SECONDS=5,
        MIN_CONFIDENCE=0.45,
        MAX_POSITIONS=3,
        MAX_POSITION_SIZE_PCT=15.0,
        RSI_OVERBOUGHT_BLOCK=78.0,
        RSI_OVERBOUGHT_REDUCE=70.0,
        RSI_OVERSOLD_BOOST=25.0,
        POS_SIZE_LOW_CONF=5.0,
        POS_SIZE_MED_CONF=10.0,
        POS_SIZE_HIGH_CONF=15.0,
        TRAILING_STOP_PCT=1.5,
        VERBOSE=True
    )

    trader = AtlasLiveTradingV2(config)
    trader.run(cycles=10, interval_seconds=5)