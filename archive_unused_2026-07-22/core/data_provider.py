"""
core/data_provider.py - Veri sağlayıcı (Düzeltildi)
"""
import requests
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger("AtlasAI")

class DataProvider:
    def get_klines(self, symbol: str, interval: str = "1m", limit: int = 100) -> List[Dict[str, Any]]:
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            resp = requests.get(url, timeout=5).json()
            candles = []
            for c in resp:
                candles.append({
                    "time": c[0],
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5])
                })
            return candles
        except Exception as e:
            logger.error(f"Veri çekilemedi: {e}")
            return []

    def get_historical_klines(self, symbol: str, start_date: datetime, interval: str = "1h", end_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        HATA DÜZELTİLDİ: start_date zorunlu, interval ve end_date varsayılanlı.
        """
        if end_date is None:
            end_date = datetime.now()
        start_ms = int(start_date.timestamp() * 1000)
        end_ms = int(end_date.timestamp() * 1000)
        all_candles = []
        current_start = start_ms
        while current_start < end_ms:
            url = f"https://api.binance.com/api/v3/klines"
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": current_start,
                "endTime": end_ms,
                "limit": 1000
            }
            try:
                resp = requests.get(url, params=params, timeout=10).json()
                if not resp:
                    break
                for c in resp:
                    all_candles.append({
                        "time": c[0],
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5])
                    })
                current_start = resp[-1][0] + 1
            except Exception as e:
                logger.error(f"Historical veri hatası: {e}")
                break
        return all_candles