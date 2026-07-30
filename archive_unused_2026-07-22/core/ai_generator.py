import os

class AICodeGenerator:
    def __init__(self):
        self.strategy_dir = os.path.join("core", "strategies")
        os.makedirs(self.strategy_dir, exist_ok=True)

    def discover_and_generate(self, strategy_name: str, optimize: bool = False) -> str:
        """
        Strateji kodunu üretir. Eğer optimize=True ise, 
        parametreleri daha güvenli/dar hale getirerek kazanma oranını artırmayı hedefler.
        """
        print(f"\n[AI Kaşif] İnternet üzerinden yeni strateji konseptleri aranıyor...")
        
        # Optimizasyon durumuna göre parametreleri dinamik belirliyoruz
        if optimize:
            print(f"[AI Optimizasyon] ⚠️ Önceki sürüm elendi. Parametreler daha güvenli hale getiriliyor...")
            rsi_lower = 30  # Aşırı satım sınırını düşürdük (Daha kesin AL sinyali)
            rsi_upper = 70  # Aşırı alım sınırını yükselttik (Daha kesin SAT sinyali)
            std_dev = 2.2   # Bollinger bandını genişlettik (Sadece uç fiyat hareketlerinde işleme girsin)
            version_note = "İyileştirilmiş Sürüm (Daha dar filtreler)"
        else:
            print(f"[AI Kaşif] Konsept bulundu: '{strategy_name}'")
            rsi_lower = 35
            rsi_upper = 65
            std_dev = 2.0
            version_note = "İlk Sürüm"

        print(f"[AI Üretici] {strategy_name} ({version_note}) için Python kodu yazılıyor...")

        code_content = f"""# -*- coding: utf-8 -*-
# AI Tarafından Üretilen Strateji - Sürüm: {"Optimized" if optimize else "Standard"}

class {strategy_name}:
    def __init__(self):
        self.name = "{strategy_name}"
        
    def generate_signals(self, df):
        # 1. Bollinger Bantları (Sapma: {std_dev})
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['STD20'] = df['Close'].rolling(window=20).std()
        df['Upper_Band'] = df['MA20'] + (df['STD20'] * {std_dev})
        df['Lower_Band'] = df['MA20'] - (df['STD20'] * {std_dev})
        
        # 2. RSI Hesaplama
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 3. Sinyal Mantığı
        signals = []
        for idx, row in df.iterrows():
            if row['Close'] <= row['Lower_Band'] and row['RSI'] < {rsi_lower}:
                signals.append("AL")
            elif row['Close'] >= row['Upper_Band'] and row['RSI'] > {rsi_upper}:
                signals.append("SAT")
            else:
                signals.append("BEKLE")
                
        df['Signal'] = signals
        return df
"""
        file_name = f"{strategy_name.lower()}.py"
        file_path = os.path.join(self.strategy_dir, file_name)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_content)
            
        print(f"[Başarılı] Strateji dosyası güncellendi: {file_path}")
        return file_path

if __name__ == "__main__":
    generator = AICodeGenerator()
    generator.discover_and_generate("BollingerRSI", optimize=False)