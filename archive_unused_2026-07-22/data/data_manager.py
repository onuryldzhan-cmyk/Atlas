"""
Atlas AI - Data Manager v2.0
Aşama 2.2: Gerçek Binance API verisi + yerel cache + rate limit yönetimi.

Özellikler:
- Binance Spot/Futures API entegrasyonu
- SQLite tabanlı yerel cache
- Rate limit koruması (otomatik bekleme)
- Çoklu timeframe desteği
- Bağlantı hatası durumunda otomatik retry
- API key olmadan mock/test modu
"""

import os
import json
import time
import sqlite3
import logging
import hashlib
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from enum import Enum

logger = logging.getLogger("AtlasAI.DataManager")


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class OHLCV:
    """Standart OHLCV (Open-High-Low-Close-Volume) veri yapısı"""
    timestamp: int          # Unix timestamp (ms)
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_list(cls, data: List[float]) -> "OHLCV":
        """Binance API formatından oluştur [timestamp, open, high, low, close, volume]"""
        return cls(
            timestamp=int(data[0]),
            open=float(data[1]),
            high=float(data[2]),
            low=float(data[3]),
            close=float(data[4]),
            volume=float(data[5])
        )


@dataclass
class MarketData:
    """Bir sembol için tam piyasa verisi"""
    symbol: str
    timeframe: str
    source: str             # "binance" | "cache" | "mock"
    last_updated: str
    ohlcv: List[OHLCV]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "source": self.source,
            "last_updated": self.last_updated,
            "candle_count": len(self.ohlcv),
            "price_range": {
                "min": min(c.low for c in self.ohlcv) if self.ohlcv else 0,
                "max": max(c.high for c in self.ohlcv) if self.ohlcv else 0,
            },
            "latest_close": self.ohlcv[-1].close if self.ohlcv else 0,
            "metadata": self.metadata
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CACHE MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class CacheManager:
    """
    SQLite tabanlı veri cache yöneticisi.

    Özellikler:
    - Otomatik tablo oluşturma
    - Cache TTL (Time To Live) kontrolü
    - Eski verilerin otomatik temizlenmesi
    """

    def __init__(self, db_path: str = "data/cache/market_data.db", ttl_minutes: int = 5):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(minutes=ttl_minutes)
        self._init_db()
        logger.info(f"Cache Manager başlatıldı: {self.db_path}")

    def _init_db(self):
        """Veritabanı tablolarını oluştur"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ohlcv_cache (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    last_fetch TEXT,
                    source TEXT,
                    candle_count INTEGER,
                    PRIMARY KEY (symbol, timeframe)
                )
            """)
            conn.commit()

    def _make_key(self, symbol: str, timeframe: str) -> str:
        """Cache anahtarı oluştur"""
        return f"{symbol}_{timeframe}"

    def is_fresh(self, symbol: str, timeframe: str) -> bool:
        """Cache'in taze olup olmadığını kontrol et"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT last_fetch FROM cache_metadata WHERE symbol=? AND timeframe=?",
                (symbol, timeframe)
            )
            row = cursor.fetchone()

            if not row or not row[0]:
                return False

            last_fetch = datetime.fromisoformat(row[0])
            return datetime.now() - last_fetch < self.ttl

    def get(self, symbol: str, timeframe: str, limit: int = 100) -> Optional[List[OHLCV]]:
        """Cache'den veri al"""
        if not self.is_fresh(symbol, timeframe):
            return None

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT timestamp, open, high, low, close, volume 
                   FROM ohlcv_cache 
                   WHERE symbol=? AND timeframe=?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (symbol, timeframe, limit)
            )
            rows = cursor.fetchall()

            if not rows:
                return None

            # Ters sıralama (eskiden yeniye)
            rows.reverse()

            return [OHLCV(timestamp=r[0], open=r[1], high=r[2], 
                         low=r[3], close=r[4], volume=r[5]) for r in rows]

    def save(self, symbol: str, timeframe: str, data: List[OHLCV], source: str = "binance"):
        """Veriyi cache'e kaydet"""
        with sqlite3.connect(self.db_path) as conn:
            # OHLCV verilerini kaydet
            for candle in data:
                conn.execute("""
                    INSERT OR REPLACE INTO ohlcv_cache 
                    (symbol, timeframe, timestamp, open, high, low, close, volume, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (symbol, timeframe, candle.timestamp, candle.open, candle.high,
                      candle.low, candle.close, candle.volume, datetime.now().isoformat()))

            # Metadata güncelle
            conn.execute("""
                INSERT OR REPLACE INTO cache_metadata 
                (symbol, timeframe, last_fetch, source, candle_count)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, timeframe, datetime.now().isoformat(), source, len(data)))

            conn.commit()

        logger.info(f"[{symbol}] {len(data)} candle cache'e kaydedildi ({timeframe}).")

    def clear_old(self, max_age_days: int = 7):
        """Eski verileri temizle"""
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM ohlcv_cache WHERE fetched_at < ?",
                (cutoff,)
            )
            deleted = cursor.rowcount
            conn.commit()

        if deleted > 0:
            logger.info(f"{deleted} eski cache kaydı silindi.")

        return deleted

    def get_stats(self) -> Dict[str, Any]:
        """Cache istatistiklerini döndür"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), COUNT(DISTINCT timeframe) FROM ohlcv_cache")
            total, symbols, timeframes = cursor.fetchone()

            cursor = conn.execute("SELECT SUM(candle_count) FROM cache_metadata")
            total_cached = cursor.fetchone()[0] or 0

            # DB boyutu
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

            return {
                "total_candles": total,
                "unique_symbols": symbols,
                "unique_timeframes": timeframes,
                "total_cached_records": total_cached,
                "db_size_kb": round(db_size / 1024, 2),
                "db_path": str(self.db_path)
            }


# ═══════════════════════════════════════════════════════════════════════════════
# BINANCE API CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

class BinanceClient:
    """
    Binance API istemcisi.

    Özellikler:
    - Rate limit koruması
    - Otomatik retry (bağlantı hatası durumunda)
    - Mock modu (API key olmadan test)
    """

    BASE_URL = "https://api.binance.com"
    FUTURES_URL = "https://fapi.binance.com"

    # Rate limit ayarları
    RATE_LIMIT_REQUESTS = 1200  # Dakikada maksimum istek
    RATE_LIMIT_WINDOW = 60      # Saniye

    def __init__(self, api_key: str = None, api_secret: str = None, use_futures: bool = False):
        self.api_key = api_key or os.getenv("BINANCE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BINANCE_API_SECRET", "")
        self.use_futures = use_futures
        self.base_url = self.FUTURES_URL if use_futures else self.BASE_URL

        # Rate limit takibi
        self.request_count = 0
        self.window_start = time.time()

        # Retry ayarları
        self.max_retries = 3
        self.retry_delay = 1  # saniye

        self.mock_mode = not (self.api_key and self.api_secret)

        if self.mock_mode:
            logger.warning("API key bulunamadı — MOCK modu aktif.")
        else:
            logger.info("Binance Client başlatıldı.")

    def _wait_for_rate_limit(self):
        """Rate limit kontrolü — gerekirse bekle"""
        now = time.time()
        elapsed = now - self.window_start

        if elapsed > self.RATE_LIMIT_WINDOW:
            # Yeni pencere
            self.request_count = 0
            self.window_start = now
        elif self.request_count >= self.RATE_LIMIT_REQUESTS:
            # Limit aşıldı — bekle
            sleep_time = self.RATE_LIMIT_WINDOW - elapsed + 1
            logger.warning(f"Rate limit yaklaşıyor. {sleep_time:.1f}s bekleniyor...")
            time.sleep(sleep_time)
            self.request_count = 0
            self.window_start = time.time()

    def _make_request(self, endpoint: str, params: Dict = None) -> Any:
        """HTTP isteği yap — retry ve rate limit ile"""
        import urllib.request
        import urllib.error

        self._wait_for_rate_limit()

        url = f"{self.base_url}{endpoint}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"

        headers = {}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key

        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    self.request_count += 1
                    return json.loads(response.read().decode())

            except urllib.error.HTTPError as e:
                if e.code == 429:
                    logger.warning(f"Rate limit aşıldı. Bekleniyor... (deneme {attempt + 1})")
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise
            except Exception as e:
                logger.error(f"İstek hatası (deneme {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise

        return None

    def get_klines(self, symbol: str, interval: str = "5m", limit: int = 100) -> List[OHLCV]:
        """
        Kline (OHLCV) verisi çek.

        Args:
            symbol: İşlem çifti (örn: BTCUSDT)
            interval: Zaman aralığı (1m, 5m, 15m, 1h, 4h, 1d)
            limit: Candle sayısı (max 1000)

        Returns:
            List[OHLCV]: OHLCV verileri
        """
        if self.mock_mode:
            return self._generate_mock_data(symbol, interval, limit)

        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": min(limit, 1000)
        }

        data = self._make_request("/api/v3/klines", params)

        if data:
            return [OHLCV.from_list(candle) for candle in data]

        return []

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Anlık fiyat bilgisi al"""
        if self.mock_mode:
            return self._generate_mock_ticker(symbol)

        params = {"symbol": symbol.upper()}
        return self._make_request("/api/v3/ticker/24hr", params) or {}

    def _generate_mock_data(self, symbol: str, interval: str, limit: int) -> List[OHLCV]:
        """Mock OHLCV verisi üret (test için)"""
        import random

        # Sembol bazlı başlangıç fiyatı
        base_prices = {
            "BTCUSDT": 65000.0, "ETHUSDT": 3200.0, "SOLUSDT": 145.0,
            "ADAUSDT": 0.45, "XRPUSDT": 0.60, "DOTUSDT": 7.0,
            "LINKUSDT": 14.0, "MATICUSDT": 0.55, "AVAXUSDT": 28.0
        }

        base = base_prices.get(symbol.upper(), 100.0)

        # Interval bazlı zaman adımı (ms)
        interval_ms = {
            "1m": 60_000, "5m": 300_000, "15m": 900_000,
            "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000
        }
        step = interval_ms.get(interval, 300_000)

        now = int(time.time() * 1000)
        data = []
        price = base

        for i in range(limit):
            ts = now - (limit - i) * step

            # Rastgele fiyat hareketi (%0.5 volatilite)
            change = random.uniform(-0.005, 0.005)
            open_p = price
            close_p = price * (1 + change)
            high_p = max(open_p, close_p) * (1 + random.uniform(0, 0.002))
            low_p = min(open_p, close_p) * (1 - random.uniform(0, 0.002))
            vol = random.uniform(base * 0.1, base * 0.5)

            data.append(OHLCV(
                timestamp=ts,
                open=round(open_p, 2),
                high=round(high_p, 2),
                low=round(low_p, 2),
                close=round(close_p, 2),
                volume=round(vol, 2)
            ))

            price = close_p

        logger.info(f"[{symbol}] Mock veri üretildi: {limit} candle ({interval}).")
        return data

    def _generate_mock_ticker(self, symbol: str) -> Dict[str, Any]:
        """Mock ticker verisi üret"""
        import random
        base = {"BTCUSDT": 65000, "ETHUSDT": 3200, "SOLUSDT": 145}.get(symbol.upper(), 100)

        return {
            "symbol": symbol.upper(),
            "lastPrice": str(base * (1 + random.uniform(-0.02, 0.02))),
            "priceChangePercent": str(random.uniform(-5, 5)),
            "volume": str(random.uniform(1000, 10000)),
            "quoteVolume": str(random.uniform(1000000, 10000000)),
            "mock": True
        }


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class DataManager:
    """
    Atlas AI Data Manager v2.0

    Merkezi veri yönetimi:
    - Cache öncelikli okuma
    - API'den eksik verileri çekme
    - Otomatik cache güncelleme
    """

    VALID_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

    def __init__(self, api_key: str = None, api_secret: str = None, 
                 cache_ttl: int = 5, use_futures: bool = False):
        self.client = BinanceClient(api_key, api_secret, use_futures)
        self.cache = CacheManager(ttl_minutes=cache_ttl)
        self.stats = {
            "api_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
            "last_update": None
        }
        logger.info("Data Manager v2.0 başlatıldı.")

    def get_ohlcv(self, symbol: str, timeframe: str = "5m", limit: int = 100,
                  use_cache: bool = True) -> MarketData:
        """
        OHLCV verisi al — cache öncelikli.

        Args:
            symbol: İşlem çifti
            timeframe: Zaman aralığı
            limit: Candle sayısı
            use_cache: Cache kullanılsın mı?

        Returns:
            MarketData: Piyasa verisi
        """
        if timeframe not in self.VALID_TIMEFRAMES:
            raise ValueError(f"Geçersiz timeframe: {timeframe}. Geçerli: {self.VALID_TIMEFRAMES}")

        symbol = symbol.upper()

        # 1. Cache kontrolü
        if use_cache:
            cached = self.cache.get(symbol, timeframe, limit)
            if cached:
                self.stats["cache_hits"] += 1
                logger.info(f"[{symbol}] Cache'den alındı ({len(cached)} candle).")

                return MarketData(
                    symbol=symbol,
                    timeframe=timeframe,
                    source="cache",
                    last_updated=datetime.now().isoformat(),
                    ohlcv=cached,
                    metadata={"cached": True, "ttl_minutes": 5}
                )
            else:
                self.stats["cache_misses"] += 1

        # 2. API'den çek
        try:
            self.stats["api_requests"] += 1
            data = self.client.get_klines(symbol, timeframe, limit)

            if data:
                # Cache'e kaydet
                self.cache.save(symbol, timeframe, data, 
                               "mock" if self.client.mock_mode else "binance")

                self.stats["last_update"] = datetime.now().isoformat()

                return MarketData(
                    symbol=symbol,
                    timeframe=timeframe,
                    source="mock" if self.client.mock_mode else "binance",
                    last_updated=datetime.now().isoformat(),
                    ohlcv=data,
                    metadata={
                        "mock": self.client.mock_mode,
                        "api_requests": self.stats["api_requests"]
                    }
                )

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"[{symbol}] Veri çekme hatası: {e}")
            raise

        return MarketData(
            symbol=symbol,
            timeframe=timeframe,
            source="error",
            last_updated=datetime.now().isoformat(),
            ohlcv=[],
            metadata={"error": "No data available"}
        )

    def get_multiple(self, symbols: List[str], timeframe: str = "5m", 
                     limit: int = 100) -> Dict[str, MarketData]:
        """Birden fazla sembol için veri al"""
        results = {}
        for symbol in symbols:
            try:
                results[symbol] = self.get_ohlcv(symbol, timeframe, limit)
            except Exception as e:
                logger.error(f"[{symbol}] Veri alınamadı: {e}")
                results[symbol] = None
        return results

    def get_latest_price(self, symbol: str) -> float:
        """Son fiyatı al"""
        ticker = self.client.get_ticker(symbol)
        return float(ticker.get("lastPrice", 0))

    def get_stats(self) -> Dict[str, Any]:
        """Data Manager istatistiklerini döndür"""
        total_requests = self.stats["cache_hits"] + self.stats["cache_misses"]
        cache_rate = (self.stats["cache_hits"] / total_requests * 100) if total_requests > 0 else 0

        return {
            "api_requests": self.stats["api_requests"],
            "cache_hits": self.stats["cache_hits"],
            "cache_misses": self.stats["cache_misses"],
            "cache_hit_rate": round(cache_rate, 2),
            "errors": self.stats["errors"],
            "mock_mode": self.client.mock_mode,
            "last_update": self.stats["last_update"],
            "cache_stats": self.cache.get_stats()
        }

    def clear_cache(self):
        """Tüm cache'i temizle"""
        deleted = self.cache.clear_old(max_age_days=0)
        logger.info(f"Cache temizlendi: {deleted} kayıt silindi.")
        return deleted


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_data_manager():
    """Data Manager test fonksiyonu"""
    print("📊 Atlas AI Data Manager v2.0 - Test Mode")
    print("=" * 60)

    # Mock mod ile test (API key gerekmez)
    dm = DataManager(cache_ttl=5)

    print(f"\n🔧 Mod: {'MOCK' if dm.client.mock_mode else 'LIVE'}")
    print(f"   Cache TTL: 5 dakika")

    # Tek sembol testi
    print("\n📈 BTCUSDT 5m verisi çekiliyor...")
    data = dm.get_ohlcv("BTCUSDT", timeframe="5m", limit=10)

    print(f"   Kaynak: {data.source}")
    print(f"   Candle sayısı: {data.ohlcv_count if hasattr(data, 'ohlcv_count') else len(data.ohlcv)}")
    print(f"   Son fiyat: ${data.ohlcv[-1].close if data.ohlcv else 'N/A'}")
    print(f"   Zaman aralığı: {data.to_dict()['price_range']}")

    # Cache testi — aynı veri tekrar çekilsin
    print("\n💾 Cache testi — aynı veri tekrar çekiliyor...")
    data2 = dm.get_ohlcv("BTCUSDT", timeframe="5m", limit=10)
    print(f"   Kaynak: {data2.source} (cache'den gelmeli)")

    # Çoklu sembol testi
    print("\n📈 Çoklu sembol testi...")
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    multi_data = dm.get_multiple(symbols, timeframe="1h", limit=5)

    for sym, md in multi_data.items():
        if md:
            print(f"   {sym}: {len(md.ohlcv)} candle, son: ${md.ohlcv[-1].close if md.ohlcv else 'N/A'}")

    # Son fiyat testi
    print("\n💰 Son fiyat testi...")
    price = dm.get_latest_price("BTCUSDT")
    print(f"   BTCUSDT: ${price:,.2f}")

    # İstatistikler
    print("\n📊 Data Manager İstatistikleri:")
    stats = dm.get_stats()
    for k, v in stats.items():
        if k != "cache_stats":
            print(f"   {k}: {v}")

    print("\n📊 Cache İstatistikleri:")
    for k, v in stats["cache_stats"].items():
        print(f"   {k}: {v}")

    # Temizlik
    print("\n🗑️  Cache temizleniyor...")
    dm.clear_cache()

    print("\n" + "=" * 60)
    print("✅ Data Manager v2.0 test completed!")
    return dm


if __name__ == "__main__":
    test_data_manager()
