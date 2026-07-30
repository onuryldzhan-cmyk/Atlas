"""
Atlas AI - Enhanced Data Fetcher
Birden fazla sembol ve zaman araligi icin veri ceker.
"""

import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path


def fetch_klines(symbol, interval, limit=1000, start_time=None, end_time=None):
    """Binance'den kline verisi cek"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    if start_time:
        url += f"&startTime={start_time}"
    if end_time:
        url += f"&endTime={end_time}"

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'AtlasAI/1.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"   Hata: {e}")
        return []


def fetch_large_dataset(symbol, interval, days=365):
    """Buyuk veri seti cek"""
    print(f"\n{'='*60}")
    print(f"VERI CEKME: {symbol} | {interval} | {days} gun")
    print(f"{'='*60}")

    interval_ms = {"1m": 60000, "5m": 300000, "15m": 900000, 
                   "1h": 3600000, "4h": 14400000, "1d": 86400000}.get(interval, 3600000)

    end_time = int(datetime.now().timestamp() * 1000)
    all_klines = []

    total_needed = (days * 86400000) // interval_ms
    requests_count = min((total_needed // 1000) + 1, 20)  # Max 20 istek

    print(f"Tahmini mum: {total_needed} | Istek: {requests_count}")
    print("-"*60)

    for i in range(requests_count):
        start = end_time - (1000 * interval_ms)

        print(f"[{i+1}/{requests_count}] Istek gonderiliyor...", end=" ")
        klines = fetch_klines(symbol, interval, 1000, start, end_time)

        if not klines:
            print("BASARISIZ")
            continue

        print(f"OK ({len(klines)} mum)")
        all_klines.extend(klines)

        end_time = klines[0][0] - interval_ms

        if len(klines) < 1000:
            print("Tum veriler cekildi.")
            break

        time.sleep(0.5)

    all_klines.sort(key=lambda x: x[0])

    print(f"\n{'='*60}")
    print(f"TOPLAM: {len(all_klines)} mum")
    if all_klines:
        first = datetime.fromtimestamp(all_klines[0][0]/1000)
        last = datetime.fromtimestamp(all_klines[-1][0]/1000)
        print(f"Tarih: {first.strftime('%Y-%m-%d')} -> {last.strftime('%Y-%m-%d')}")
    print("="*60)

    return all_klines


def save_klines(klines, symbol, interval):
    """Kline verilerini kaydet"""
    candles = []
    for k in klines:
        candles.append({
            "timestamp": datetime.fromtimestamp(k[0]/1000).isoformat(),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": datetime.fromtimestamp(k[6]/1000).isoformat(),
            "quote_volume": float(k[7]),
            "trades": int(k[8]),
            "symbol": symbol
        })

    Path("data").mkdir(exist_ok=True)
    filename = f"data/{symbol.lower()}_{interval}.json"

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(candles, f, indent=2, ensure_ascii=False)

    file_size = Path(filename).stat().st_size / 1024
    print(f"\n💾 Kaydedildi: {filename}")
    print(f"   Boyut: {file_size:.1f} KB")

    if candles:
        closes = [c["close"] for c in candles]
        print(f"\n📊 OZET:")
        print(f"   Ilk fiyat: {closes[0]:,.2f}")
        print(f"   Son fiyat: {closes[-1]:,.2f}")
        print(f"   Degisim: %{((closes[-1]-closes[0])/closes[0])*100:.2f}")
        print(f"   En yuksek: {max(c['high'] for c in candles):,.2f}")
        print(f"   En dusuk: {min(c['low'] for c in candles):,.2f}")

    return filename


def fetch_multiple_symbols(symbols, interval="1h", days=365):
    """Birden fazla sembol icin veri cek"""
    print("\n" + "="*60)
    print("COKLU SEMBOL VERI CEKME")
    print("="*60)

    for symbol in symbols:
        klines = fetch_large_dataset(symbol, interval, days)
        if klines:
            save_klines(klines, symbol, interval)
        print("\n" + "-"*60)

    print("\n✅ Tum semboller tamamlandi!")


def main():
    print("="*60)
    print("ATLAS AI - ENHANCED DATA FETCHER")
    print("="*60)

    print("\n1. BTCUSDT - 1h (365 gun)")
    print("2. ETHUSDT - 1h (365 gun)")
    print("3. SOLUSDT - 1h (365 gun)")
    print("4. Hepsi (BTC, ETH, SOL)")
    print("5. Ozel")

    choice = input("\nSecim (1-5): ").strip()

    if choice == "1":
        klines = fetch_large_dataset("BTCUSDT", "1h", 365)
        if klines: save_klines(klines, "BTCUSDT", "1h")

    elif choice == "2":
        klines = fetch_large_dataset("ETHUSDT", "1h", 365)
        if klines: save_klines(klines, "ETHUSDT", "1h")

    elif choice == "3":
        klines = fetch_large_dataset("SOLUSDT", "1h", 365)
        if klines: save_klines(klines, "SOLUSDT", "1h")

    elif choice == "4":
        fetch_multiple_symbols(["BTCUSDT", "ETHUSDT", "SOLUSDT"], "1h", 365)

    elif choice == "5":
        symbol = input("Sembol: ").strip().upper()
        interval = input("Aralik (1m/5m/15m/1h/4h/1d): ").strip()
        days = int(input("Gun: ").strip())
        klines = fetch_large_dataset(symbol, interval, days)
        if klines: save_klines(klines, symbol, interval)

    else:
        print("Gecersiz secim!")
        return

    print("\n✅ Islem tamamlandi!")


if __name__ == "__main__":
    main()

