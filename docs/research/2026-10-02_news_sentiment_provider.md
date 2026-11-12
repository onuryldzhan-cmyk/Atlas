# Haber ve duygu (sentiment) sağlayıcısı — değerlendirme

Kaynak: sahibin paylaştığı video (fidetolabs, "Realtime news processing"); GitHub: AI4Finance-Foundation/FinGPT (~20 bin yıldız), ProsusAI/finBERT (~2,2 bin yıldız). Yıldız sayıları arama sonucundan; kullanılmadan önce yeniden doğrulanmalı.

## DÜZELTME (2026-10-02, aynı gün)
Aşağıdaki ilk madde YANLIŞTIR ve olduğu gibi bırakılmıştır (kararın neden değiştiği kayıtlı kalsın diye).
`agent_fusion.py` içindeki "no provider" yorumu eskimiş: registry v4.66 Crypto Fear & Greed sağlayıcısını
(`atlas_finance/market_data/fear_greed_provider.py`) ve v4.79 makro (Treasury) ile piyasa riski (volatilite)
sağlayıcılarını canlıya bağladı (`analysis/world_analysis_engine.py`). Duygu oyu yalnız korku (<25) ve açgözlülük
(>=75) bandında verilir; nötrde çekimser kalır. Hata kaynağı: eski bir kod yorumu doğrulanmadan kabul edildi.
Yeni ilk adım: canlı duygu oyunun geçmişte işe yarayıp yaramadığını yalnız gözlemle ölçmek
(`tools/sentiment_lessons.py`: deneyim kararları x günlük Fear & Greed bandı, bağımsız örnek + FDR süzgeci).
Eskimiş yorum `agent_fusion.py` içinde ayrıca düzeltilmeli (yalnız yorum; davranış değişmez).

## Repo ile ilgili gerçekler (2026-10-02 incelemesi — ilk madde yukarıdaki düzeltmeyle geçersiz)
- `ai/core/intelligence/agent_fusion.py`: "macro/sentiment/market_risk currently have no provider"; bu yüzden en az 3 katılımcı ajan şartı (`MIN_PARTICIPATING_AGENTS = 3`) bugün hiç sağlanamıyor. Bu bilinçli bir fail-closed durumdur, hata değildir.
- `core/market_intelligence.py::_sentiment` sabit `{"news": "neutral", "score": 50}` döndürüyor. Bu sınıfı canlı runtime kurmuyor (yalnız `dashboard/` ve kök test scriptleri); yine de sahte veri, ileride kaldırılmalı veya N/A yapılmalı.
- `ai/core/atlas_world_model.py` sabit "Fear & Greed 45 / VIX 18" düğümleri içeriyor. Kararlara etkisi: UNKNOWN — doğrulama gerekir.

## Değerlendirme
- **What:** Haber başlıklarından coin bazlı duygu skoru üreten salt-okunur bir kanıt sağlayıcı (toplama → tekrar ayıklama → coin eşleme → skor), kaynak ve zaman damgasıyla.
- **Why:** Füzyondaki eksik üçüncü bağımsız kanıt kaynağı; bugün kararlar yalnız teknik + momentumdan geliyor.
- **Where:** Mevcut faz: karar zekâsı (decision intelligence) — yeni faz değil.
- **Dependencies:** Haber kaynağı (lisans/kota), skor modeli (FinBERT yerel, ya da mevcut AI geçidi yalnız danışman olarak), geçmiş veri (geri test için).
- **Risk:** Yüksek. Karar zincirine yeni girdi = NB-4/NB-5 riski; haber manipülasyonu; gecikme; geçmiş haber verisi olmadan geri test edilemez.
- **Cost:** Orta-yüksek; bağımsız denetim ve paper + shadow doğrulaması gerekir.
- **Alternative:** Önce yalnız gözlem: skoru kaydedip kararlara BAĞLAMADAN 30+ gün sonuçla ilişkisini ölçmek (deneyim ajanı ve walk-forward + FDR süzgeci ile).
- **Decision:** DEFER — sahip onayı gerekir. Önerilen ilk adım yalnız gözlem alternatifi.
