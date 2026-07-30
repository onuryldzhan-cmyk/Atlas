"""
ATLAS LIVE CONNECTOR - Binance API Entegrasyonu
Gerçek piyasa verisini çekip Orchestrator'a ileten köprü modülü
"""

import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import random

# Orchestrator'dan MarketData ve TradeAction'ı import et
try:
    from atlas_orchestrator import AtlasOrchestrator, MarketData, TradeAction
    ORCHESTRATOR_AVAILABLE = True
except ImportError:
    ORCHESTRATOR_AVAILABLE = False
    print("[CONNECTOR] UYARI: Orchestrator bulunamadi! Demo modda calisiliyor.")

# Binance API için
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("[CONNECTOR] UYARI: requests kutuphanesi yok! Demo veri kullanilacak.")


class BinanceAPI:
    """Binance API wrapper"""

    BASE_URL = "https://api.binance.com"

    def __init__(self):
        self.logger = logging.getLogger('BinanceAPI')
        self.session = requests.Session() if REQUESTS_AVAILABLE else None
        self.last_prices: Dict[str, float] = {}

    def get_ticker_24h(self, symbol: str) -> Optional[Dict]:
        """24 saatlik istatistikleri al"""
        if not REQUESTS_AVAILABLE:
            return None

        try:
            url = f"{self.BASE_URL}/api/v3/ticker/24hr"
            params = {"symbol": symbol}
            response = self.session.get(url, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                return {
                    'symbol': data['symbol'],
                    'price': float(data['lastPrice']),
                    'change_24h': float(data['priceChangePercent']),
                    'volume': float(data['volume']),
                    'high': float(data['highPrice']),
                    'low': float(data['lowPrice']),
                    'quote_volume': float(data['quoteVolume'])
                }
            else:
                self.logger.warning(f"[BINANCE] Hata {response.status_code} for {symbol}")
                return None
        except Exception as e:
            self.logger.error(f"[BINANCE] API hatasi {symbol}: {e}")
            return None

    def get_klines(self, symbol: str, interval: str = "5m", limit: int = 100) -> Optional[List]:
        """Kline (OHLCV) verisi al"""
        if not REQUESTS_AVAILABLE:
            return None

        try:
            url = f"{self.BASE_URL}/api/v3/klines"
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            response = self.session.get(url, params=params, timeout=10)

            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            self.logger.error(f"[BINANCE] Kline hatasi {symbol}: {e}")
            return None

    def get_all_tickers(self) -> List[Dict]:
        """Tüm tickers'ı al"""
        if not REQUESTS_AVAILABLE:
            return []

        try:
            url = f"{self.BASE_URL}/api/v3/ticker/24hr"
            response = self.session.get(url, timeout=15)

            if response.status_code == 200:
                data = response.json()
                # Sadece USDT çiftlerini filtrele
                usdt_pairs = [d for d in data if d['symbol'].endswith('USDT')]
                # Hacme göre sırala, top 20'yi al
                usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
                return usdt_pairs[:20]
            return []
        except Exception as e:
            self.logger.error(f"[BINANCE] Tüm tickers hatasi: {e}")
            return []


class TechnicalIndicators:
    """Teknik gösterge hesaplayıcı"""

    @staticmethod
    def calculate_rsi(closes: List[float], period: int = 14) -> float:
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

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def calculate_macd(closes: List[float]) -> float:
        """MACD histogram değeri hesapla"""
        if len(closes) < 26:
            return 0.0

        ema_12 = TechnicalIndicators._ema(closes, 12)
        ema_26 = TechnicalIndicators._ema(closes, 26)

        if ema_12 and ema_26:
            macd_line = ema_12 - ema_26
            # Signal line (EMA 9 of MACD) - basitleştirilmiş
            return macd_line
        return 0.0

    @staticmethod
    def calculate_ema(closes: List[float], period: int) -> float:
        """EMA hesapla"""
        if len(closes) < period:
            return closes[-1] if closes else 0.0
        return TechnicalIndicators._ema(closes, period)

    @staticmethod
    def _ema(closes: List[float], period: int) -> float:
        """EMA hesaplama yardımcısı"""
        if len(closes) < period:
            return sum(closes) / len(closes) if closes else 0.0

        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period

        for price in closes[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    @staticmethod
    def calculate_bollinger(closes: List[float], period: int = 20) -> Tuple[float, float]:
        """Bollinger Bands hesapla"""
        if len(closes) < period:
            last = closes[-1] if closes else 0.0
            return last * 1.02, last * 0.98

        sma = sum(closes[-period:]) / period
        variance = sum((x - sma) ** 2 for x in closes[-period:]) / period
        std_dev = variance ** 0.5

        upper = sma + (std_dev * 2)
        lower = sma - (std_dev * 2)

        return upper, lower

    @staticmethod
    def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """ATR hesapla"""
        if len(closes) < period + 1:
            return (max(highs) - min(lows)) / 2 if highs and lows else 0.0

        tr_values = []
        for i in range(1, len(closes)):
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i-1])
            tr3 = abs(lows[i] - closes[i-1])
            tr_values.append(max(tr1, tr2, tr3))

        return sum(tr_values[-period:]) / period


class AtlasLiveConnector:
    """
    ATLAS Live Connector
    Binance API'den veri çekip Orchestrator'a iletir
    """

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.logger = self._setup_logger()

        self.binance = BinanceAPI()
        self.indicators = TechnicalIndicators()
        self.orchestrator = None

        # Ayarlar
        self.symbols = self.config.get('symbols', [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
            "XRPUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT",
            "MATICUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT",
            "XLMUSDT", "ALGOUSDT", "VETUSDT", "FILUSDT", "TRXUSDT"
        ])
        self.interval = self.config.get('interval', '5m')
        self.demo_mode = self.config.get('demo_mode', not REQUESTS_AVAILABLE)

        # Orchestrator'ı başlat
        if ORCHESTRATOR_AVAILABLE:
            orch_config = {
                'min_confidence': self.config.get('min_confidence', 0.2),
                'max_position_size': self.config.get('max_position_size', 0.15),
                'max_positions': self.config.get('max_positions', 5)
            }
            self.orchestrator = AtlasOrchestrator(config=orch_config)
            self.logger.info("[CONNECTOR] Orchestrator baslatildi!")

        self.logger.info(f"[CONNECTOR] Atlas Live Connector baslatildi! (Demo: {self.demo_mode})")

    def _setup_logger(self):
        logger = logging.getLogger('AtlasLiveConnector')
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def fetch_market_data(self, symbol: str) -> Optional[MarketData]:
        """Tek sembol için piyasa verisi çek"""

        if self.demo_mode:
            return self._generate_demo_data(symbol)

        # Binance API'den veri çek
        ticker = self.binance.get_ticker_24h(symbol)
        klines = self.binance.get_klines(symbol, self.interval, 100)

        if not ticker or not klines:
            return None

        # Kline verisini parse et
        closes = [float(k[4]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        volumes = [float(k[5]) for k in klines]

        # Teknik göstergeleri hesapla
        rsi = self.indicators.calculate_rsi(closes)
        macd = self.indicators.calculate_macd(closes)
        ema_20 = self.indicators.calculate_ema(closes, 20)
        ema_50 = self.indicators.calculate_ema(closes, 50)
        bb_upper, bb_lower = self.indicators.calculate_bollinger(closes)
        atr = self.indicators.calculate_atr(highs, lows, closes)

        return MarketData(
            symbol=symbol,
            price=ticker['price'],
            volume_24h=ticker['volume'],
            change_24h=ticker['change_24h'],
            rsi=rsi,
            macd=macd,
            ema_20=ema_20,
            ema_50=ema_50,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            atr=atr,
            timestamp=datetime.now()
        )

    def _generate_demo_data(self, symbol: str) -> MarketData:
        """Demo verisi üret"""
        # Sembol bazlı sabit fiyatlar (gerçekçi)
        base_prices = {
            "BTCUSDT": 65000, "ETHUSDT": 3500, "BNBUSDT": 580,
            "SOLUSDT": 150, "ADAUSDT": 0.45, "XRPUSDT": 0.60,
            "DOTUSDT": 7.5, "DOGEUSDT": 0.12, "AVAXUSDT": 28,
            "LINKUSDT": 14, "MATICUSDT": 0.70, "LTCUSDT": 75,
            "UNIUSDT": 9, "ATOMUSDT": 6.5, "ETCUSDT": 25,
            "XLMUSDT": 0.10, "ALGOUSDT": 0.15, "VETUSDT": 0.03,
            "FILUSDT": 4.5, "TRXUSDT": 0.12
        }

        base = base_prices.get(symbol, 100)
        change = random.uniform(-0.05, 0.05)
        price = base * (1 + change)

        # Rastgele ama tutarlı göstergeler
        rsi = random.uniform(25, 75)
        macd = random.uniform(-0.5, 0.5) * (base / 1000)
        ema_20 = price * (1 + random.uniform(-0.02, 0.02))
        ema_50 = price * (1 + random.uniform(-0.05, 0.05))
        bb_upper = price * 1.05
        bb_lower = price * 0.95
        atr = price * 0.02

        return MarketData(
            symbol=symbol,
            price=price,
            volume_24h=random.uniform(1e6, 1e9),
            change_24h=change * 100,
            rsi=rsi,
            macd=macd,
            ema_20=ema_20,
            ema_50=ema_50,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            atr=atr,
            timestamp=datetime.now()
        )

    def run_single_cycle(self) -> Dict:
        """Tek döngü çalıştır"""
        self.logger.info(f"\n{'='*70}")
        self.logger.info(f"[CONNECTOR] DONGU BASLIYOR - {datetime.now().strftime('%H:%M:%S')}")
        self.logger.info(f"{'='*70}")

        # Tüm semboller için veri çek
        market_data_list = []
        for symbol in self.symbols:
            data = self.fetch_market_data(symbol)
            if data:
                market_data_list.append(data)
            time.sleep(0.1)  # API rate limit koruması

        self.logger.info(f"[CONNECTOR] {len(market_data_list)} sembol icin veri cekildi")

        # Orchestrator'a ilet
        if self.orchestrator and market_data_list:
            result = self.orchestrator.run_cycle(market_data_list)
            return result

        return {"error": "Orchestrator veya veri yok"}

    def run_continuous(self, interval_seconds: int = 300):
        """Sürekli çalıştır (her X saniyede bir)"""
        self.logger.info(f"[CONNECTOR] Surekli mod basladi! Aralik: {interval_seconds}s")

        try:
            while True:
                self.run_single_cycle()

                # Sonraki döngüye kadar bekle
                self.logger.info(f"[CONNECTOR] Sonraki dongu: {interval_seconds} saniye...")
                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            self.logger.info("[CONNECTOR] Kullanici tarafindan durduruldu")

        finally:
            if self.orchestrator:
                self.orchestrator.save_state()
            self.logger.info("[CONNECTOR] Durum kaydedildi, cikiliyor...")

    def get_portfolio_summary(self) -> Dict:
        """Portföy özetini al"""
        if self.orchestrator:
            return self.orchestrator.get_status()
        return {}

    def print_market_overview(self, market_data_list: List[MarketData]):
        """Piyasa özetini yazdır"""
        print(f"\n{'='*70}")
        print("PIYASA OZETI")
        print(f"{'='*70}")
        print(f"{'Sembol':<12} {'Fiyat':>12} {'Degisim%':>10} {'RSI':>8} {'Sinyal':<10}")
        print("-" * 70)

        for data in market_data_list[:10]:  # İlk 10
            signal = ""
            if data.rsi < 30:
                signal = "🟢 AL"
            elif data.rsi > 70:
                signal = "🔴 SAT"
            else:
                signal = "⚪ NÖTR"

            print(f"{data.symbol:<12} ${data.price:>10.2f} {data.change_24h:>+9.2f}% {data.rsi:>7.1f} {signal:<10}")


def test_connector():
    """Connector testi"""
    print("\n" + "="*70)
    print("ATLAS LIVE CONNECTOR - TEST")
    print("="*70)

    # Demo modda başlat
    connector = AtlasLiveConnector(config={
        'demo_mode': True,
        'min_confidence': 0.2,
        'max_position_size': 0.15,
        'max_positions': 3,
        'symbols': ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT"]
    })

    # Tek döngü çalıştır
    result = connector.run_single_cycle()

    # Piyasa özetini yazdır
    if 'decisions' in result:
        print(f"\n{'='*70}")
        print("KARARLAR")
        print(f"{'='*70}")
        for d in result['decisions']:
            print(f"  {d['symbol']}: {d['action'].upper()} (guven: {d['confidence']:.2f})")

    if 'executed' in result:
        print(f"\n{'='*70}")
        print("UYGULANAN ISLEMLER")
        print(f"{'='*70}")
        for e in result['executed']:
            if e['executed']:
                print(f"  [OK] {e['symbol']}: {e['message']}")

    # Portföy durumu
    print(f"\n{'='*70}")
    print("PORTFOY DURUMU")
    print(f"{'='*70}")
    status = connector.get_portfolio_summary()
    print(f"Portfoy Degeri: ${status.get('portfolio_value', 0):.2f}")
    print(f"Nakit: ${status.get('cash', 0):.2f}")
    print(f"Aktif Pozisyonlar: {status.get('active_positions', 0)}")

    if status.get('positions'):
        print(f"\nPozisyonlar:")
        for sym, pos in status['positions'].items():
            print(f"  {sym}: {pos['qty']:.4f} @ ${pos['entry']:.2f}")

    print(f"\n{'='*70}")
    print("✅ CONNECTOR TEST TAMAMLANDI!")
    print(f"{'='*70}")

    return connector


if __name__ == "__main__":
    test_connector()