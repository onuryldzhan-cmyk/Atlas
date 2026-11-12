# Shadow aşaması — tasarım önerisi (owner onayı bekliyor)

Merdiven (CLAUDE.md): Paper → **Shadow** → Small Live → Controlled Autonomous → Advanced Autonomous.
Tanım: canlı piyasa verisi, yalnız sanal emir, gerçek sermaye yok; kararlar gerçek piyasayla paralel alınır ve
performans emir gönderilmeden ölçülür. `config/environments.json`: SHADOW = "NOT IMPLEMENTED".

## Repo gerçekleri (2026-10-02)
- Paper zaten canlı Binance verisi + sanal emir kullanıyor (`EXECUTION_MODE=PAPER`).
- Paper dolumu son fiyattan, kayma varsayılanı 0 (`core/execution_manager.py::PAPER_SLIPPAGE_BPS = 0`),
  ücret `PAPER_FEE_RATE_PER_SIDE`. Yani spread ve emir defteri derinliği hiç ödenmiyor: Paper iyimser.

## Shadow'u Paper'dan ayıran şey
Gerçek bir emrin ödeyeceği maliyet: dolum, canlı emir defterine karşı (alışta ask tarafı, satışta bid tarafı,
emir büyüklüğü kadar seviye yürüyerek) hesaplanır. Kaynak fikirler:
- NautilusTrader (sandbox): canlı veri + simüle eşleştirme motoru, emir mekâna gitmez; fill/fee/latency modelleri.
- hummingbot (~19 bin yıldız): canlı Binance verisine karşı paper trade.
- freqtrade (~38 bin yıldız): dry-run; belgeleri dry-run'ın gerçek sonuçtan iyimser olabileceğini açıkça söyler.

## Aşamalar
- **S1 — Gözlem (bu oturumda, çalışma zamanı değişikliği yok):** `shadow_costs` ajanı her döngüde evrendeki
  coinlerin emir defterini (Binance public depth) okur; tipik işlem büyüklüğü için alış/satış maliyetini (spread +
  derinlik, bps) kaydeder. `tools/shadow_report.py` kapanan Paper işlemlerini bu maliyetle yeniden fiyatlar:
  "Paper net" ile "Shadow tahmini net" yan yana. Karar, emir, eşik değişmez.
- **S2 — Ayrı Shadow çalışma modu (ONAY GEREKİR, CRITICAL):** `EXECUTION_MODE=SHADOW`, ayrı durum dizini,
  `may_submit_orders=false` sabit; dolum = canlı defterden VWAP (S1 modeli), mekân kuralları (min notional, lot)
  uygulanır; Paper ile aynı karar akışı (Decision → Risk → Capital → Execution Manager), yalnız fill modeli farklı.
  Bağımsız denetim + başarısızlık testleri (defter alınamazsa emir REDDEDİLİR, son fiyata düşülmez).
- **S3 — Kapı ölçütleri (ONAY GEREKİR):** Shadow'dan Small Live'a geçiş için en az N gün/işlem, ücret+maliyet
  sonrası pozitif beklenti (güven aralığıyla), kalibrasyon farkı sınırı, sıfır kritik olay. Sayılar sahibin kararı.

## Riskler
Defter anlık görüntüsü emir anındaki gerçeği tam yansıtmaz (gecikme, iptal edilen emirler); S1 yalnız tahmindir
ve öyle etiketlenir. Ağ hatası: değer uydurulmaz, o döngü "veri yok" kalır.

## Karar
S1: ACCEPT (gözlem, geri alınabilir). S2, S3: DEFER — sahip onayı ve bağımsız denetim gerekir.
