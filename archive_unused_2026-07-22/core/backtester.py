# -*- coding: utf-8 -*-
import os
import sys
import pandas as pd
import importlib.util

class BacktestEngine:
    def __init__(self, initial_balance=1000.0, commission_rate=0.001, slippage_rate=0.0005):
        """
        commission_rate: %0.1 standart borsa komisyonu (0.001)
        slippage_rate: %0.05 ortalama fiyat kayması (0.0005)
        """
        self.initial_balance = initial_balance
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.reset_pools()

    def reset_pools(self):
        self.balance_low = self.initial_balance * 0.60
        self.balance_mid = self.initial_balance * 0.30
        self.balance_high = self.initial_balance * 0.10
        self.trades = []

    def load_strategy_dynamically(self, strategy_name: str):
        file_name = f"{strategy_name.lower()}.py"
        file_path = os.path.join("core", "strategies", file_name)
        if not os.path.exists(file_path):
            return None
        try:
            spec = importlib.util.spec_from_file_location(strategy_name, file_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[strategy_name] = module
            spec.loader.exec_module(module)
            strategy_class = getattr(module, strategy_name)
            return strategy_class()
        except Exception as e:
            print(f"[Hata] Dinamik strateji yüklenirken hata oluştu: {e}")
            return None

    def run_backtest(self, csv_path: str, strategy_name: str):
        if not os.path.exists(csv_path):
            print(f"[Hata] Test edilecek veri dosyası bulunamadı: {csv_path}")
            return 0.0

        self.reset_pools()
        df = pd.read_csv(csv_path)
        
        print(f"\n====================================================")
        print(f"   ATLAS AI - GERÇEKÇİ SİMÜLASYON TESTİ (Borsa Koşulları)")
        print(f"====================================================")
        print(f"Veri Seti            : {os.path.basename(csv_path)}")
        print(f"Hedeflenen Strateji   : {strategy_name}")
        print(f"Slippage Oranı       : %{self.slippage_rate * 100:.3f}")
        print(f"Komisyon Oranı       : %{self.commission_rate * 100:.2f}")

        strategy_instance = self.load_strategy_dynamically(strategy_name)
        
        if strategy_instance:
            print(f"[Başarılı] AI Stratejisi '{strategy_name}' dinamik yüklendi.")
            df = strategy_instance.generate_signals(df)
        else:
            print(f"[Bilgi] Dahili MA-Cross yedek stratejisi kullanılıyor.")
            df['MA_Fast'] = df['Close'].rolling(window=10).mean()
            df['MA_Slow'] = df['Close'].rolling(window=30).mean()
            signals = []
            for idx, row in df.iterrows():
                if pd.isna(row['MA_Fast']) or pd.isna(row['MA_Slow']):
                    signals.append("BEKLE")
                elif row['MA_Fast'] > row['MA_Slow']:
                    signals.append("AL")
                elif row['MA_Fast'] < row['MA_Slow']:
                    signals.append("SAT")
                else:
                    signals.append("BEKLE")
            df['Signal'] = signals

        in_position = False
        entry_price = 0
        position_type = ""
        allocated_pool = ""
        trade_amount = 0

        for idx, row in df.iterrows():
            signal = row.get('Signal', 'BEKLE')

            # 1. POZİSYON AÇILIŞI (Komisyon ve Slippage Dahil Ediliyor)
            if not in_position:
                if signal in ["AL", "SAT"]:
                    in_position = True
                    raw_price = row['Close']
                    
                    # Gerçekçi Giriş Fiyatı (Slippage ekleniyor)
                    if signal == "AL":
                        # Alırken slippage yüzünden biraz daha pahalıdan alırız
                        entry_price = raw_price * (1 + self.slippage_rate)
                        position_type = "LONG"
                    else:
                        # Satarken (Short) slippage yüzünden biraz daha ucuzdan satarız
                        entry_price = raw_price * (1 - self.slippage_rate)
                        position_type = "SHORT"
                    
                    # Giriş Komisyonu Kesintisi
                    entry_commission = trade_amount * self.commission_rate
                    
                    if strategy_name == "BollingerRSI":
                        allocated_pool = "MID"
                        trade_amount = (self.balance_mid * 0.5) - entry_commission
                    else:
                        allocated_pool = "LOW"
                        trade_amount = (self.balance_low * 0.5) - entry_commission
            
            # 2. POZİSYON KAPANIŞI (Komisyon ve Slippage Dahil Ediliyor)
            elif in_position:
                raw_exit_price = row['Close']
                
                # Gerçekçi Çıkış Fiyatı (Slippage ekleniyor)
                if position_type == "LONG":
                    exit_price = raw_exit_price * (1 - self.slippage_rate)
                else:
                    exit_price = raw_exit_price * (1 + self.slippage_rate)
                
                price_change = (exit_price - entry_price) / entry_price
                pnl_percent = price_change if position_type == "LONG" else -price_change
                
                # Çıkış komisyonu kesintisi
                exit_commission = trade_amount * self.commission_rate
                
                # Hedefler: %2 kâr alma veya %1 stop-loss
                is_tp = pnl_percent >= 0.02
                is_sl = pnl_percent <= -0.01
                
                reverse_signal = (position_type == "LONG" and signal == "SAT") or (position_type == "SHORT" and signal == "AL")

                if is_tp or is_sl or reverse_signal:
                    pnl_usd = (trade_amount * pnl_percent) - exit_commission
                    
                    if allocated_pool == "LOW":
                        self.balance_low += pnl_usd
                    elif allocated_pool == "MID":
                        self.balance_mid += pnl_usd
                    else:
                        self.balance_high += pnl_usd
                        
                    self.trades.append({
                        "Result": "WIN" if pnl_usd > 0 else "LOSS",
                        "PnL_USD": pnl_usd
                    })
                    in_position = False

        return self.report_results()

    def report_results(self):
        total_trades = len(self.trades)
        if total_trades == 0:
            print("[Uyarı] Simülasyon süresince hiç işlem gerçekleşmedi.")
            return 0.0

        wins = sum(1 for t in self.trades if t['Result'] == "WIN")
        win_rate = (wins / total_trades) * 100
        total_pnl = sum(t['PnL_USD'] for t in self.trades)
        final_balance = self.balance_low + self.balance_mid + self.balance_high

        print("----------------------------------------------------")
        print(f"Toplam İşlem Adedi   : {total_trades}")
        print(f"Kazanma Oranı (WR)   : %{win_rate:.2f}")
        print(f"Toplam Net Kar/Zarar : {total_pnl:+.2f} USD (Komisyonlar Düştü)")
        print(f"Güncel Toplam Kasa   : {final_balance:.2f} USD")
        print(f" - Düşük Risk (LOW)  : {self.balance_low:.2f} USD")
        print(f" - Orta Risk (MID)   : {self.balance_mid:.2f} USD")
        print(f" - Yüksek Risk (HIGH): {self.balance_high:.2f} USD")
        print("====================================================\n")
        return win_rate

if __name__ == "__main__":
    # Slippage: %0.05, Komisyon: %0.1 gerçek borsa parametreleriyle başlatıyoruz
    backtester = BacktestEngine(initial_balance=1000.0, commission_rate=0.001, slippage_rate=0.0005)
    
    classic_wr = backtester.run_backtest("data/historical/BTCUSDT_1h_15d.csv", "Trend_Following")
    ai_wr = backtester.run_backtest("data/historical/BTCUSDT_1h_15d.csv", "BollingerRSI")
    
    print("=== YAPAY ZEKA STRATEJİ DEĞERLENDİRMESİ ===")
    if ai_wr > classic_wr:
        print(f"🔥 HARİKA! AI'ın yeni yazdığı strateji (%{ai_wr:.2f} WR) borsa koşullarında eskiyi geçti!")
    else:
        print(f"⚠️ AI'ın yazdığı ilk strateji (%{ai_wr:.2f} WR) yetersiz kaldı.")
        print("🔄 Kendi Kendini İyileştirme Döngüsü (Self-Healing) Başlatılıyor...")
        
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        from core.ai_generator import AICodeGenerator
        
        generator = AICodeGenerator()
        generator.discover_and_generate("BollingerRSI", optimize=True)
        
        print("\n--- OPTİMİZE EDİLMİŞ SÜRÜM YENİDEN TEST EDİLİYOR ---")
        optimized_wr = backtester.run_backtest("data/historical/BTCUSDT_1h_15d.csv", "BollingerRSI")
        
        if optimized_wr > ai_wr:
            print(f"📈 BAŞARILI: Optimizasyon işe yaradı! Kazanma oranı %{ai_wr:.2f}'den %{optimized_wr:.2f}'ye yükseldi.")
        else:
            print(f"❌ Optimizasyon da borsa koşullarında yetersiz kaldı. Strateji tamamen reddedildi.")
    print("===========================================")