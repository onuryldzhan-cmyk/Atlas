import os
import json
import pandas as pd
from datetime import datetime
from core.technical_analyzer import TechnicalAnalyzer
from core.memory import LearningMemory
from core.strategy_brain import StrategyBrain
from core.risk_manager import RiskManager
from core.data_provider import DataProvider
from core.paper_trader import PaperTrader

class AtlasEngine:
    """
    PROJECT ATLAS AI - Çok Katmanlı Yapay Zekâ İşlem Motoru
    Canlı veri, teknik analiz, hafıza, strateji yarışması, risk yönetimi ve paper trading koordine eder.
    """
    def __init__(self):
        self.analyzer = TechnicalAnalyzer()
        self.memory = LearningMemory()
        self.strategy_brain = StrategyBrain()
        self.data_provider = DataProvider()
        self.paper_trader = PaperTrader()
        # Varsayılan simüle bakiye tanımı
        self.simulated_balance = 1000.0  # 1000 USD Sanal Bakiye
        self.risk_manager = RiskManager(max_risk_per_trade=0.02, default_leverage=1)
        print("[AtlasEngine] İşlem motoru, hafıza, strateji yarışması, risk yöneticisi, veri sağlayıcı ve PAPER TRADER başlatıldı.")

    def start(self, symbol: str):
        """
        Belirtilen coin için canlı veri çeker ve çok katmanlı analiz/karar döngüsünü çalıştırır.
        """
        if not symbol or symbol == "":
            print("[Hata] Geçersiz veya boş coin sembolü!")
            return

        print(f"\n--- {symbol} CANLI ANALİZ EDİLİYOR ---")
        
        # 1. Aşama: Canlı Veri Sağlayıcı (Market Intelligence)
        df = self.data_provider.get_market_data(symbol, interval="5m", limit=100)
        
        if df.empty:
            print(f"[Hata] {symbol} için canlı piyasa verileri alınamadı. İşlem iptal edildi.")
            return

        current_price = round(float(df['close'].iloc[-1]), 4)
        print(f"Canlı Fiyat: {current_price}")

        # Mevcut canlı fiyatı açık pozisyonları kontrol etmek için güncelleyelim
        self.paper_trader.update_open_positions({symbol: current_price})

        # 2. Aşama: Gelişmiş Teknik Analiz (Technical Signal)
        tech_data = self.analyzer.analyze(df)
        print(f"Teknik Analiz Özeti: Trend={tech_data['trend']}, RSI={tech_data['rsi']}, ADX={tech_data['adx']}")

        # 3. Aşama: Strategy Brain (Strateji Yarışması)
        battle_results = self.strategy_brain.evaluate_all(df, tech_data)
        best_strategy = battle_results["best_strategy"]
        brain_decision = battle_results["decision"]
        strategy_score = battle_results["score"]

        print(f"\n===== CANLI STRATEJİ YARIŞMASI SONUÇLARI =====")
        for strat_name, res in battle_results["all_strategies"].items():
            print(f" - {strat_name}: Karar={res['decision']} | Puan={res['score']}")
        print(f"Kazanan Strateji: {best_strategy} ({brain_decision}) - Puan: {strategy_score}")
        print("================================================\n")

        # 4. Aşama: Hafıza ve Başarı Analizi (Learning Memory)
        stats = self.memory.get_stats(symbol)
        if isinstance(stats, dict) and "best_strategy" in stats:
            print(f"Hafızadaki En Başarılı Strateji: {stats['best_strategy']} (Başarı Oranı: {stats.get('win_rate', 0)}%)")
        else:
            print("Henüz yeterli işlem geçmişi yok, strateji yarışmasının birincisi doğrudan kullanılacak.")

        # 5. Aşama: Çok Katmanlı Yapay Zekâ Karar Sistemi & Güven Puanı (Confidence Engine)
        decision = brain_decision
        confidence_score = strategy_score
        reasons = [f"Canlı strateji yarışmasını {best_strategy} kazandı."]

        # Risk Kontrolü: Güven skoru 50'nin altındaysa işlem açma riskini minimize et
        if confidence_score < 50:
            decision = "BEKLE"
            reasons.append("Yarışmayı kazanan stratejinin güven puanı barajın altında (%50).")

        # Nihai Karar Çıktısı
        print(f"YÜKSEK GÜVENLİ CANLI KARAR: {decision} | Nihai Güven Skoru: %{confidence_score}")
        if reasons:
            print("Gerekçeler:")
            for r in reasons:
                print(f" - {r}")

        # 6. Aşama: Sermaye ve Dinamik Risk Yönetimi (Risk Manager Entegrasyonu)
        risk_params = {
            "capital_allocated_usd": 0.0,
            "risk_amount_usd": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "sl_percent": 0.0,
            "tp_percent": 0.0,
            "leverage": 1
        }

        if decision != "BEKLE":
            risk_params = self.risk_manager.calculate_position_parameters(
                capital=self.simulated_balance,
                entry_price=current_price,
                rsi=tech_data["rsi"],
                atr=tech_data["atr"],
                trend=tech_data["trend"]
            )
            print(f"\n===== DİNAMİK RİSK VE SERMAYE YÖNETİMİ =====")
            print(f" Sınıflandırılan Kasa: {self.simulated_balance} USD")
            print(f" İşleme Ayrılan Büyüklük: {risk_params['capital_allocated_usd']} USD (Kaldıraç: {risk_params['leverage']}x)")
            print(f" Riske Edilen Miktar: {risk_params['risk_amount_usd']} USD")
            print(f" Dinamik Stop Loss: {risk_params['stop_loss']} (%{risk_params['sl_percent']})")
            print(f" Dinamik Take Profit: {risk_params['take_profit']} (%{risk_params['tp_percent']})")
            print("============================================\n")

        # İşlem durumu artık doğrudan kapatılmış sayılmayacak. 
        # Eğer bir karar verilmişse, canlıda takip edilmek üzere "OPEN" statüsünde kaydedilecek!
        trade_status = "OPEN" if decision != "BEKLE" else "PASSED"
        simulated_profit = 0.0

        # İşlem detaylarını hafızaya kaydetme
        test_trade = {
            "symbol": symbol,
            "status": trade_status,
            "entry": current_price,
            "profit": simulated_profit,
            "strategy": best_strategy,
            "rsi": tech_data["rsi"],
            "trend": tech_data["trend"],
            "decision": decision,
            "confidence": confidence_score,
            "stop_loss": risk_params["stop_loss"],
            "take_profit": risk_params["take_profit"],
            "allocated_usd": risk_params["capital_allocated_usd"],
            "leverage": risk_params["leverage"]
        }
        self.memory.save_trade(test_trade)
        print(f"[Memory] Canlı analiz döngüsü ve karar detayları {trade_status} durumunda hafızaya kaydedildi.")