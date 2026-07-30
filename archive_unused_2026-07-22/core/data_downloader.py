import os
import time
import pandas as pd
import requests
from datetime import datetime

class HistoricalDownloader:
    def __init__(self):
        # Verileri kaydedeceğimiz klasör yolunu belirliyoruz
        self.output_dir = os.path.join("data", "historical")
        os.makedirs(self.output_dir, exist_ok=True)
        self.base_url = "https://api.binance.com/api/v3/klines"

    def download_data(self, symbol: str, interval: str = "1h", limit_days: int = 30) -> str:
        """
        Belirtilen sembol ve zaman dilimi için geçmiş verileri indirir ve CSV olarak kaydeder.
        Binance tek seferde maks 1000 mum verdiği için geriye doğru döngüsel (paginated) çekim yapar.
        """
        symbol = symbol.upper()
        print(f"\n[Veri İndirici] {symbol} ({interval}) için son {limit_days} günlük tarihsel veri indiriliyor...")

        # Zaman hesaplamaları (Milisaniye cinsinden)
        now_ms = int(time.time() * 1000)
        start_time_ms = now_ms - (limit_days * 24 * 60 * 60 * 1000)
        
        all_candles = []
        current_start = start_time_ms

        while current_start < now_ms:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": current_start,
                "limit": 1000
            }
            
            try:
                response = requests.get(self.base_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                print(f"[Hata] Binance veri çekme hatası: {e}")
                break

            if not data:
                break

            all_candles.extend(data)
            
            # Son alınan mumun kapanış zamanını bir sonraki isteğin başlangıcı yapıyoruz (+1 ms ekleyerek)
            last_candle_close_time = data[-1][6]
            current_start = last_candle_close_time + 1
            
            # Binance limitlerine saygı duymak için hafif bir bekleme
            time.sleep(0.1)

            # Eğer son mumun zamanı şimdiki zamana çok yaklaştıysa döngüyü bitir
            if len(data) < 1000:
                break

        if not all_candles:
            print(f"[Hata] {symbol} için veri indirilemedi.")
            return ""

        # Veriyi Pandas DataFrame'e dönüştürüyoruz
        columns = [
            "Open_Time", "Open", "High", "Low", "Close", "Volume",
            "Close_Time", "Quote_Asset_Volume", "Number_of_Trades",
            "Taker_Buy_Base_Asset_Volume", "Taker_Buy_Quote_Asset_Volume", "Ignore"
        ]
        
        df = pd.DataFrame(all_candles, columns=columns)
        
        # Sadece bize lazım olan temel sütunları filtreleyelim ve tiplerini düzeltelim
        keep_cols = ["Open_Time", "Open", "High", "Low", "Close", "Volume"]
        df = df[keep_cols]
        
        # Sayısal değerleri float tipine çeviriyoruz
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = df[col].astype(float)
            
        # Milisaniye zaman damgasını okunabilir tarihe çevirip indeks yapalım
        df["Timestamp"] = pd.to_datetime(df["Open_Time"], unit="ms")
        df.drop(columns=["Open_Time"], inplace=True)
        df = df[["Timestamp", "Open", "High", "Low", "Close", "Volume"]]

        # CSV Dosya adını belirleyip kaydedelim
        file_name = f"{symbol}_{interval}_{limit_days}d.csv"
        file_path = os.path.join(self.output_dir, file_name)
        df.to_csv(file_path, index=False)
        
        print(f"[Başarılı] {len(df)} adet mum başarıyla indirildi ve kaydedildi:")
        print(f" -> Yol: {file_path}")
        return file_path

# Hızlı test için bağımsız çalıştırma bloğu
if __name__ == "__main__":
    downloader = HistoricalDownloader()
    # Test olarak BTCUSDT için son 15 günlük 1 saatlik mumları indirelim
    downloader.download_data("BTCUSDT", "1h", 15)