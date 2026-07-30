"""
Atlas AI - Live Data Connector
Binance API'den canli veri cekme ve Brain'e iletme

Ozellikler:
- Binance API'den 1h mum verisi cekme
- WebSocket ile anlik fiyat takibi
- Veri cache'leme
- Otomatik veri guncelleme
- Brain entegrasyonu
"""
import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Binance API ayarlari
BINANCE_API_BASE = "https://api.binance.com"
BINANCE_KLINES_URL = f"{BINANCE_API_BASE}/api/v3/klines"

class BinanceDataFetcher:
    """Binance'ten veri cekme"""

    def __init__(self):
        self.cache_dir = PROJECT_ROOT / "data"
        self.cache_dir.mkdir(exist_ok=True)
        self.last_update = None

    def fetch_klines(self, symbol: str = "BTCUSDT", interval: str = "1h", 
                     limit: int = 100) -> List[Dict]:
        """
        Binance'ten mum verisi cek

        symbol: BTCUSDT, ETHUSDT, vs.
        interval: 1m, 5m, 15m, 1h, 4h, 1d
        limit: Kac mum (max 1000)
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }

        try:
            print(f"[API] Binance'ten {symbol} {interval} verisi cekiliyor...")
            response = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            # Binance formatini standart formata cevir
            candles = []
            for item in data:
                candle = {
                    "timestamp": datetime.fromtimestamp(item[0] / 1000).isoformat(),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                    "close_time": item[6],
                    "quote_volume": float(item[7])
                }
                candles.append(candle)

            print(f"[API] {len(candles)} mum cekildi")
            print(f"[API] Tarih: {candles[0]['timestamp']} -> {candles[-1]['timestamp']}")
            print(f"[API] Fiyat: {candles[0]['close']:.2f} -> {candles[-1]['close']:.2f}")

            # Cache'e kaydet
            self._save_cache(symbol, interval, candles)

            self.last_update = datetime.now()
            return candles

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] API hatasi: {e}")
            # Cache'den oku
            return self._load_cache(symbol, interval)
        except Exception as e:
            print(f"[ERROR] Beklenmeyen hata: {e}")
            return self._load_cache(symbol, interval)

    def _save_cache(self, symbol: str, interval: str, data: List[Dict]):
        """Veriyi cache'e kaydet"""
        cache_file = self.cache_dir / f"{symbol.lower()}_{interval}.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[CACHE] {cache_file.name} kaydedildi")

    def _load_cache(self, symbol: str, interval: str) -> List[Dict]:
        """Cache'den veri yukle"""
        cache_file = self.cache_dir / f"{symbol.lower()}_{interval}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                print(f"[CACHE] {cache_file.name} cache'den yuklendi ({len(data)} mum)")
                return data
            except:
                pass
        print("[ERROR] Cache bulunamadi!")
        return []

    def get_latest_price(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """Son fiyatı al"""
        try:
            url = f"{BINANCE_API_BASE}/api/v3/ticker/price"
            response = requests.get(url, params={"symbol": symbol}, timeout=5)
            data = response.json()
            return float(data["price"])
        except:
            return None

    def get_24h_stats(self, symbol: str = "BTCUSDT") -> Optional[Dict]:
        """24 saatlik istatistikler"""
        try:
            url = f"{BINANCE_API_BASE}/api/v3/ticker/24hr"
            response = requests.get(url, params={"symbol": symbol}, timeout=5)
            data = response.json()
            return {
                "price_change": float(data["priceChange"]),
                "price_change_pct": float(data["priceChangePercent"]),
                "high": float(data["highPrice"]),
                "low": float(data["lowPrice"]),
                "volume": float(data["volume"]),
                "quote_volume": float(data["quoteVolume"])
            }
        except:
            return None


class LiveTradingLoop:
    """Canli islem dongusu"""

    def __init__(self, risk_profile: str = "MEDIUM"):
        self.fetcher = BinanceDataFetcher()
        self.risk_profile = risk_profile
        self.running = False

        # Brain'i yukle (varsa)
        try:
            from core.atlas_brain_v2 import AtlasBrainV2
            self.brain = AtlasBrainV2(risk_profile)
            self.brain_available = True
        except ImportError:
            print("[WARNING] Brain v2 bulunamadi, manuel mod")
            self.brain_available = False

    def run_once(self, symbol: str = "BTCUSDT"):
        """Tek dongu calistir"""
        print("\n" + "="*60)
        print(f"[LIVE] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)

        # 1. Veri cek
        candles = self.fetcher.fetch_klines(symbol, "1h", 100)

        if not candles:
            print("[ERROR] Veri cekilemedi!")
            return

        # 2. 24h istatistikler
        stats = self.fetcher.get_24h_stats(symbol)
        if stats:
            print(f"[24H] Degisim: {stats['price_change_pct']:.2f}%")
            print(f"[24H] High: {stats['high']:.2f} | Low: {stats['low']:.2f}")
            print(f"[24H] Hacim: {stats['volume']:.2f} BTC")

        # 3. Brain'e ver
        if self.brain_available:
            market_data = {
                "symbol": symbol,
                "prices": [c["close"] for c in candles],
                "highs": [c["high"] for c in candles],
                "lows": [c["low"] for c in candles],
                "volumes": [c["volume"] for c in candles],
                "current_price": candles[-1]["close"],
                "timestamp": candles[-1]["timestamp"]
            }

            signal = self.brain.process(market_data)
            result = self.brain.execute(signal)

            if result.get("status") == "EXECUTED":
                print(f"[LIVE] ISLEM ACILDI: {result['trade']['side']} @ {result['trade']['entry']:.2f}")
        else:
            # Manuel analiz
            self._manual_analysis(candles)

    def _manual_analysis(self, candles: List[Dict]):
        """Manuel teknik analiz (Brain yoksa)"""
        prices = [c["close"] for c in candles]
        current = prices[-1]

        # Basit RSI
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [c for c in changes[-14:] if c > 0]
        losses = [abs(c) for c in changes[-14:] if c < 0]
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        rsi = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

        print(f"[MANUEL] RSI: {rsi:.1f} | Fiyat: {current:.2f}")

        if rsi < 30:
            print("[MANUEL] SINYAL: RSI asiri satim - ALIS dusunulebilir")
        elif rsi > 70:
            print("[MANUEL] SINYAL: RSI asiri alim - SATIS dusunulebilir")
        else:
            print("[MANUEL] BEKLE - Net sinyal yok")

    def run_continuous(self, symbol: str = "BTCUSDT", interval_minutes: int = 60):
        """Surekli calistir"""
        self.running = True
        print(f"[LIVE] Surekli mod basladi (Her {interval_minutes} dk)")
        print("Durdurmak icin Ctrl+C")

        try:
            while self.running:
                self.run_once(symbol)
                print(f"\n[ZAMAN] Sonraki kontrol: {interval_minutes} dk sonra...")
                time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            print("\n[LIVE] Durduruldu.")
            self.running = False


def main():
    print("="*60)
    print("ATLAS AI - LIVE DATA CONNECTOR")
    print("="*60)
    print("\nSecenekler:")
    print("1. Tek seferlik veri cek")
    print("2. Surekli calistir (her saat)")
    print("3. Sadece fiyat kontrol et")

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["once", "continuous", "price"], default="once")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--profile", choices=["LOW", "MEDIUM", "HIGH"], default="MEDIUM")
    args = parser.parse_args()

    fetcher = BinanceDataFetcher()

    if args.mode == "price":
        price = fetcher.get_latest_price(args.symbol)
        if price:
            print(f"\n[PRICE] {args.symbol}: {price:.2f} USDT")
        else:
            print("[ERROR] Fiyat alınamadı")

    elif args.mode == "once":
        loop = LiveTradingLoop(args.profile)
        loop.run_once(args.symbol)

    elif args.mode == "continuous":
        loop = LiveTradingLoop(args.profile)
        loop.run_continuous(args.symbol)


if __name__ == "__main__":
    main()

