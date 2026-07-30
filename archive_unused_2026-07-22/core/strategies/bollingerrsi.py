# -*- coding: utf-8 -*-
# AI Tarafından Üretilen Strateji - Sürüm: Optimized

class BollingerRSI:
    def __init__(self):
        self.name = "BollingerRSI"
        
    def generate_signals(self, df):
        # 1. Bollinger Bantları (Sapma: 2.2)
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['STD20'] = df['Close'].rolling(window=20).std()
        df['Upper_Band'] = df['MA20'] + (df['STD20'] * 2.2)
        df['Lower_Band'] = df['MA20'] - (df['STD20'] * 2.2)
        
        # 2. RSI Hesaplama
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 3. Sinyal Mantığı
        signals = []
        for idx, row in df.iterrows():
            if row['Close'] <= row['Lower_Band'] and row['RSI'] < 30:
                signals.append("AL")
            elif row['Close'] >= row['Upper_Band'] and row['RSI'] > 70:
                signals.append("SAT")
            else:
                signals.append("BEKLE")
                
        df['Signal'] = signals
        return df
