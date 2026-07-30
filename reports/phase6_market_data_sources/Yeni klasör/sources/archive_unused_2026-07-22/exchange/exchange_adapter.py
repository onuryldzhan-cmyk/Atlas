"""
Atlas AI v4.3 — Borsa Bağlantı Adaptörü
=======================================
Public API kullanarak Binance verisi çeker.
Şu an sadece OKUMA, yazma yok (API key yok).
"""

import ccxt
import pandas as pd
import time
from typing import List, Dict, Any, Optional
from config.settings import (
    EXCHANGE, TIMEFRAME, MIN_VOLUME_USDT, 
    MAX_COINS, USE_PUBLIC_API, BASE_URL
)


class ExchangeAdapter:
    """
    Binance borsası ile iletişim kuran adaptör.
    
    Özellikler:
    - Public API'den fiyat çekme
    - OHLCV (mum) verisi çekme
    - Tüm marketi tarama
    - Hacme göre filtreleme
    - Veri kalitesi kontrolü
    """
    
    def __init__(self):
        """Borsa bağlantısını başlat."""
        
        # CCXT ile Binance bağlantısı
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True
            }
        })
        
        # Public API kullanılıyor
        if USE_PUBLIC_API:
            print("🔗 Public API modu (sadece okuma)")
        
        # Market listesi (cache)
        self._markets_loaded = False
        self._usdt_symbols = []
        
        print(f"✅ ExchangeAdapter hazır | {EXCHANGE}")
    
    def _load_markets(self) -> None:
        """Market listesini yükle (bir kere)."""
        if self._markets_loaded:
            return
        
        try:
            self.exchange.load_markets()
            self._markets_loaded = True
            print(f"📊 {len(self.exchange.markets)} market yüklendi")
        except Exception as e:
            print(f"⚠️ Market yükleme hatası: {e}")
            self._usdt_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    
    def get_price(self, symbol: str) -> Optional[float]:
        """
        Anlık fiyat çek.
        
        Args:
            symbol: Örn: "BTCUSDT"
        
        Returns:
            Fiyat (float) veya None (hata durumunda)
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            price = float(ticker['last'])
            
            # Anomali kontrolü
            if price <= 0:
                print(f"⚠️ Anomali: {symbol} fiyatı 0 veya negatif")
                return None
            
            return price
            
        except ccxt.NetworkError as e:
            print(f"🌐 Ağ hatası {symbol}: {e}")
            return None
        except ccxt.ExchangeError as e:
            print(f"🏦 Borsa hatası {symbol}: {e}")
            return None
        except Exception as e:
            print(f"❌ Fiyat hatası {symbol}: {e}")
            return None
    
    def get_ohlcv(self, symbol: str, timeframe: str = None, limit: int = 100) -> Optional[pd.DataFrame]:
        """
        Mum (OHLCV) verisi çek.
        
        Args:
            symbol: Örn: "BTCUSDT"
            timeframe: Örn: "5m", "1h" (varsayılan: settings.TIMEFRAME)
            limit: Kaç mum (varsayılan: 100)
        
        Returns:
            DataFrame veya None
        """
        tf = timeframe or TIMEFRAME
        
        try:
            candles = self.exchange.fetch_ohlcv(symbol, tf, limit=limit)
            
            if not candles or len(candles) < 20:
                print(f"⚠️ Yetersiz mum {symbol}: {len(candles) if candles else 0}")
                return None
            
            df = pd.DataFrame(
                candles,
                columns=['time', 'open', 'high', 'low', 'close', 'volume']
            )
            
            # Veri kalitesi kontrolü
            df = self._validate_ohlcv(df, symbol)
            
            return df
            
        except Exception as e:
            print(f"❌ OHLCV hatası {symbol}: {e}")
            return None
    
    def _validate_ohlcv(self, df: pd.DataFrame, symbol: str) -> Optional[pd.DataFrame]:
        """
        Mum verisini doğrula.
        
        Kontroller:
        - Null değer
        - Negatif fiyat
        - Aşırı büyük değişim
        """
        # Null kontrolü
        if df.isnull().any().any():
            print(f"⚠️ Null değer var {symbol}")
            df = df.dropna()
        
        # Negatif kontrolü
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if (df[col] <= 0).any():
                print(f"⚠️ Negatif/0 değer var {symbol}")
                return None
        
        # Aşırı değişim kontrolü (%50'den fazla tek mumda)
        df['change'] = abs(df['close'] - df['open']) / df['open'] * 100
        if (df['change'] > 50).any():
            print(f"⚠️ Aşırı değişim var {symbol}")
            # Anomali olan satırları at
            df = df[df['change'] <= 50]
        
        return df
    
    def get_all_symbols(self, min_volume: float = None) -> List[str]:
        """
        Tüm USDT çiftlerini al, hacme göre filtrele.
        
        Args:
            min_volume: Minimum 24s hacim (varsayılan: settings.MIN_VOLUME_USDT)
        
        Returns:
            Coin listesi (sıralı)
        """
        self._load_markets()
        min_vol = min_volume or MIN_VOLUME_USDT
        
        try:
            # Ticker'ları çek (hacim bilgisi için)
            tickers = self.exchange.fetch_tickers()
            
            symbols = []
            for symbol, ticker in tickers.items():
                # Sadece USDT çiftleri
                if not symbol.endswith('USDT'):
                    continue
                
                # Aktif mi?
                if not ticker.get('quoteVolume'):
                    continue
                
                quote_volume = float(ticker['quoteVolume'])
                
                # Hacim kontrolü
                if quote_volume >= min_vol:
                    symbols.append({
                        'symbol': symbol,
                        'volume': quote_volume,
                        'price': float(ticker['last'])
                    })
            
            # Hacime göre sırala (büyükten küçüğe)
            symbols.sort(key=lambda x: x['volume'], reverse=True)
            
            # MAX_COINS ile sınırla
            symbols = symbols[:MAX_COINS]
            
            self._usdt_symbols = [s['symbol'] for s in symbols]
            
            print(f"📈 {len(self._usdt_symbols)} coin seçildi (min hacim: {min_vol:,.0f} USDT)")
            
            return self._usdt_symbols
            
        except Exception as e:
            print(f"❌ Market tarama hatası: {e}")
            return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    
    def get_top_volume_coins(self, n: int = 20) -> List[Dict[str, Any]]:
        """
        En hacimli N coini döndür (detaylı).
        
        Returns:
            [{'symbol': 'BTCUSDT', 'volume': 1000000, 'price': 65000}, ...]
        """
        self._load_markets()
        
        try:
            tickers = self.exchange.fetch_tickers()
            
            coins = []
            for symbol, ticker in tickers.items():
                if not symbol.endswith('USDT'):
                    continue
                
                volume = float(ticker.get('quoteVolume', 0))
                price = float(ticker.get('last', 0))
                
                if volume > 0 and price > 0:
                    coins.append({
                        'symbol': symbol,
                        'volume': volume,
                        'price': price,
                        'change_24h': float(ticker.get('percentage', 0))
                    })
            
            # Sırala
            coins.sort(key=lambda x: x['volume'], reverse=True)
            
            return coins[:n]
            
        except Exception as e:
            print(f"❌ Hacim listesi hatası: {e}")
            return []
    
    def get_balance(self) -> Dict[str, float]:
        """
        Public API'de bakiye yok, simülasyon döndür.
        
        Returns:
            {'USDT': 10000.0, 'free': 10000.0, 'used': 0.0}
        """
        # Public API'de bakiye bilgisi yok
        # Bu simülasyon için
        return {
            'USDT': 10000.0,
            'free': 10000.0,
            'used': 0.0,
            'note': 'Public API - Simülasyon bakiyesi'
        }
    
    def test_connection(self) -> bool:
        """
        Bağlantıyı test et.
        
        Returns:
            True (başarılı) / False (hata)
        """
        try:
            # Basit bir fiyat çekme deneyi
            ticker = self.exchange.fetch_ticker('BTCUSDT')
            price = float(ticker['last'])
            
            if price > 0:
                print(f"✅ Bağlantı OK | BTC: {price:,.2f} USDT")
                return True
            else:
                print("❌ Bağlantı başarısız: Fiyat 0")
                return False
                
        except Exception as e:
            print(f"❌ Bağlantı hatası: {e}")
            return False


# ============================================
# TEST
# ============================================
if __name__ == "__main__":
    print("🧪 ExchangeAdapter testi")
    
    adapter = ExchangeAdapter()
    
    # Bağlantı testi
    if adapter.test_connection():
        # Tek fiyat
        price = adapter.get_price("BTCUSDT")
        print(f"💰 BTC: {price}")
        
        # Mum verisi
        df = adapter.get_ohlcv("BTCUSDT", limit=5)
        if df is not None:
            print(f"📊 Son mum: {df.iloc[-1].to_dict()}")
        
        # Tüm market
        symbols = adapter.get_all_symbols()
        print(f"📈 İlk 5 coin: {symbols[:5]}")
        
        # Top hacimli
        top = adapter.get_top_volume_coins(5)
        for coin in top:
            print(f"  {coin['symbol']}: {coin['volume']:,.0f} USDT")