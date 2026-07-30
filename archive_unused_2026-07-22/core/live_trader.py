# -*- coding: utf-8 -*-
import os
import sys
import time
import pandas as pd
from binance.client import Client
from dotenv import load_dotenv

# API anahtarlarını yükle
load_dotenv()

class LiveTrader:
    def __init__(self, symbol="BTCUSDT", interval="1h"):
        self.symbol = symbol.upper()
        self.interval = interval
        self.api_key = os.getenv("BINANCE_TR_API_KEY")
        self.api_secret = os.getenv("BINANCE_TR_API_SECRET")
        self.client = None
        self.strategy = None
        
        # Binance TR API bağlantısını başlat (Binance TR için tld='me' kullanılır)
        self.connect_to_binance()

    def connect_to_binance(self):
        """Binance TR API bağlantısını güvenli bir şekilde kurar."""
        print(f"\n[Sistem] Binance TR API bağlantısı kuruluyor...")
        try:
            # Eğer anahtarlar girilmediyse veya varsayılan değerdeyse 'gözlemci' modunda başla
            if not self.api_key or "your_api" in self.api_key:
                print("[Bilgi] API Anahtarları bulunamadı. Gözlemci (Sadece Okuma) modunda başlatılıyor.")
                self.client = Client("", "") # Boş anahtarlarla sadece veri çekilebilir
            else:
                self.client = Client(self.api_key, self.api_secret, tld="me")
                # Bağlantıyı test et
                status = self.client.get_system_status()
                if status.get("status") == 0:
                    print("[Başarılı] Binance TR API bağlantısı aktif ve sağlıklı!")
                else:
                    print("[Uyarı] Binance TR sistem bakımı olabilir veya bağlantı zayıf.")
        except Exception as e:
            print(f"[Hata] API bağlantısı kurulamadı. Hata: {e}")
            print("[Bilgi] Gözlemci moduna geçiş yapıldı (Sadece veri analizi aktif).")
            self.client = Client("", "")

    def fetch_live_data(self, limit=100) -> pd.DataFrame:
        """Binance TR'den canlı k-line (mum) verilerini çeker."""
        print(f"[Veri] {self.symbol} için son {limit} adet {self.interval} mumu çekiliyor...")
        try:
            # Binance TR k-line verilerini çekiyoruz
            klines = self.client.get_klines(
                symbol=self.symbol,
                interval=self.interval,
                limit=limit
            )
            
            # Gelen veriyi DataFrame formatına dönüştürüyoruz
            df = pd.DataFrame(klines, columns=[
                'Open_Time', 'Open', 'High', 'Low', 'Close', 'Volume',
                'Close_Time', 'Quote_Asset_Volume', 'Number_of_Trades',
                'Taker_Buy_Base_Asset_Volume', 'Taker_Buy_Quote_Asset_Volume', 'Ignore'
            ])
            
            # Veri tiplerini sayısala çevir
            numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col])
                
            # Zaman damgasını okunabilir yap
            df['Open_Time'] = pd.to_datetime(df['Open_Time'], unit='ms')
            return df
            
        except Exception as e:
            print(f"[Hata] Canlı veri çekilirken hata oluştu: {e}")
            return pd.DataFrame()

    def set_active_strategy(self, strategy_instance):
        """Canlı analiz için kullanılacak stratejiyi sisteme tanımlar."""
        self.strategy = strategy_instance
        print(f"[Strateji] Canlı strateji aktif edildi: {strategy_instance.name}")

    def monitor_market(self, check_interval_seconds=10):
        """Belirli aralıklarla piyasayı tarayıp canlı sinyal üreten ana döngü."""
        if not self.strategy:
            print("[Hata] Aktif bir strateji atanmadan canlı takip başlatılamaz!")
            return

        print(f"\n⚡ ATLAS AI CANLI TAKİP MODU BAŞLATILDI ⚡")
        print(f"Takip Edilen: {self.symbol} | Tarama Sıklığı: {check_interval_seconds} Saniye")
        print("Döngüyü durdurmak için 'Ctrl + C' tuşlarına basın.\n")

        try:
            while True:
                # 1. Canlı Veriyi Çek
                df = self.fetch_live_data(limit=100)
                
                if not df.empty:
                    # 2. Stratejiye veriyi besle ve sinyal üret
                    df = self.strategy.generate_signals(df)
                    
                    # Son mumu ve üretilen sinyali al
                    latest_row = df.iloc[-1]
                    latest_time = latest_row['Open_Time']
                    latest_close = latest_row['Close']
                    latest_signal = latest_row.get('Signal', 'BEKLE')
                    
                    print(f"[{latest_time}] Fiyat: {latest_close:.2f} USD | Sinyal: {latest_signal}")
                    
                    # 3. Canlı Emir Tetikleme Mekanizması İskeleti
                    if latest_signal == "AL":
                        self.execute_mock_order("BUY", latest_close)
                    elif latest_signal == "SAT":
                        self.execute_mock_order("SELL", latest_close)
                else:
                    print("[Uyarı] Canlı veri boş döndü, bir sonraki döngü bekleniyor...")

                # Belirtilen saniye kadar bekle
                time.sleep(check_interval_seconds)
                
        except KeyboardInterrupt:
            print("\n[Sistem] Canlı takip modundan çıkılıyor. Atlas AI beklemede.")

    def execute_mock_order(self, side, price):
        """
        [Canlı Testnet/Simülasyon Emri] 
        Gerçek hesapta para kaybetmeden önce canlı sinyali simüle eder.
        Gelecekte burası doğrudan Binance TR API emir gönderme koduna bağlanacak.
        """
        print(f"🚀 [CANLI EMİR TETİKLENDİ] Yön: {side} | Fiyat: {price:.2f} USD")
        print(f"👉 [Bilgi] Gerçek API aktif olduğunda bu emir Binance TR borsasına iletilecektir.")

if __name__ == "__main__":
    # Canlı takip modülünü BTCUSDT için başlatıyoruz
    trader = LiveTrader(symbol="BTCUSDT", interval="1h")
    
    # AI'ın kazanan BollingerRSI stratejisini dinamik olarak yüklüyoruz
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from core.backtester import BacktestEngine
    
    engine = BacktestEngine()
    ai_strategy = engine.load_strategy_dynamically("BollingerRSI")
    
    if ai_strategy:
        trader.set_active_strategy(ai_strategy)
        # 5 saniyede bir canlı piyasayı sorgulayacak şekilde başlatıyoruz (Test amaçlı hızlı tarama)
        trader.monitor_market(check_interval_seconds=5)