import json
import os

class Dashboard:
    """
    PROJECT ATLAS AI - Canlı Terminal Dashboard Modülü
    Yapay zekânın performans verilerini, kâr/zarar durumunu ve aktif istatistiklerini raporlar.
    """
    def __init__(self, memory_path="data/atlas_memory.json"):
        self.memory_path = memory_path

    def show(self):
        print("\n====================================================")
        print("          PROJECT ATLAS AI - CANLI PANEL")
        print("====================================================")
        
        if not os.path.exists(self.memory_path):
            print("[Bilgi] Henüz işlem geçmişi veya hafıza kaydı bulunamadı.")
            print("====================================================\n")
            return

        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                trades = json.load(f)
        except Exception as e:
            print(f"[Hata] Hafıza dosyası okunurken hata oluştu: {e}")
            return

        if not trades:
            print("[Bilgi] Hafızada henüz kayıtlı analiz veya işlem yok.")
            print("====================================================\n")
            return

        # İstatistikleri hesaplayalım
        total_records = len(trades)
        closed_trades = [t for t in trades if t.get("status") == "CLOSED"]
        passed_signals = [t for t in trades if t.get("status") == "PASSED"]
        open_trades = [t for t in trades if t.get("status") == "OPEN"]

        total_closed = len(closed_trades)
        wins = len([t for t in closed_trades if float(t.get("profit", 0)) > 0])
        losses = total_closed - wins
        win_rate = (wins / total_closed) * 100 if total_closed > 0 else 0.0
        total_profit = sum(float(t.get("profit", 0)) for t in closed_trades)

        # Strateji dağılımı
        strategies = {}
        for t in trades:
            strat = t.get("strategy", "Bilinmeyen")
            strategies[strat] = strategies.get(strat, 0) + 1

        # Tabloyu ekrana yazdırıyoruz
        print(f" Toplam Analiz Kaydı : {total_records}")
        print(f" İzlenen/Geçilen     : {len(passed_signals)} Sinyal")
        print(f" Açık Pozisyonlar    : {len(open_trades)} Adet")
        print(f" Kapatılan İşlemler  : {total_closed} Adet")
        print(f" Başarılı (Win)      : {wins} | Başarısız (Loss): {losses}")
        print(f" Başarı Oranı (WR)   : %{win_rate:.2f}")
        print(f" Toplam Net Kâr/Zarar: {total_profit:+.2f} USD")
        print("----------------------------------------------------")
        print(" Aktif Stratejilerin Kullanım Dağılımı:")
        for strat, count in strategies.items():
            print(f"  - {strat:<20}: {count} Kez Kullanıldı")
        print("----------------------------------------------------")
        
        # Son 5 işlemi listeleme
        print(" Son 5 İşlem Kaydı:")
        for t in trades[-5:]:
            decision = t.get("decision", "BEKLE")
            symbol = t.get("symbol", "Bilinmeyen")
            profit = t.get("profit", 0.0)
            strat = t.get("strategy", "Bilinmeyen")
            conf = t.get("confidence", 0)
            
            profit_str = f"{profit:+.2f} USD" if decision != "BEKLE" else "PASSED"
            print(f"  [{t.get('status')}] {symbol} -> Karar: {decision:<5} | Güven: %{conf:<3} | Kar: {profit_str:<12} | Strateji: {strat}")
            
        print("====================================================\n")