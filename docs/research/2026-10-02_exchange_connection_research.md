# Borsa bağlantısı (Binance / Binance TR) — araştırma notu

Durum: ARAŞTIRMA. Canlı yetki DENIED, production NONE. Hiçbir kod değişikliği önermez; Small Live
hazırlığına (Paper → Shadow → Small Live) girdi olarak tutulur.

## 1. Botlar borsada yasak mı? Gizlenmek gerekir mi?

- **Hayır, gizlenmek gerekmez ve yapılmamalı.** Binance API anahtarları otomatik işlem için verilir;
  borsa API ile gelen her isteğin bir program olduğunu zaten bilir ve buna göre kural koyar.
- Atlas borsanın otomasyonu fark etmesini engellemeye **çalışmayacak**: web arayüzünü taklit eden otomasyon,
  istek sınırlarını aşmak için birden çok hesap/IP, sınırları dolanma gibi yollar kullanım şartlarına aykırıdır,
  hesabın dondurulmasına yol açar ve Atlas'ın "güvenlik kârdan önce gelir" kuralına ters düşer.
- Piyasa manipülasyonu sayılan davranışlar (kendi kendine alım-satım / wash trading, gerçekleşmesi
  amaçlanmayan emirler / spoofing) hem borsa kurallarına hem sermaye piyasası mevzuatına aykırıdır; Atlas'ın
  stratejileri bunları içermez ve içermemelidir.

## 2. Profesyonel bir botun "iyi müşteri" kalması için uyduğu kurallar (Binance Spot API)

| Kural | Ne demek | Atlas'ta durum |
|---|---|---|
| İstek ağırlığı (REQUEST_WEIGHT) | Dakikalık ağırlık sınırı; aşınca 429, sürerse 418 (IP yasağı) | 2026-10-02: 418/429 sonrası Retry-After kadar tüm istekler durduruluyor (e566c69). Eksik: `X-MBX-USED-WEIGHT` başlığını izleyip sınıra yaklaşınca yavaşlamak |
| Dolmamış emir sayısı (unfilled order count) | Kısa aralıkta çok sayıda dolmamış emir → 429 / -1015 "Too many new orders" | Paper'da emir yok. Small Live öncesi: emir hızı sınırlayıcı + `GET /api/v3/rateLimit/order` takibi |
| MAX_NUM_ORDERS | Sembol başına en fazla 200 açık emir | Atlas sembol başına tek pozisyon; risk yok |
| exchangeInfo filtreleri | PRICE_FILTER, LOT_SIZE, MIN_NOTIONAL vb. | Var: `config/instrument_rules.json` + venue minimum kontrolleri |
| İstemci emir kimliği | `newClientOrderId` ile aynı emrin iki kez gönderilmesi önlenir | Atlas'ın `request_id` idempotency'si var; canlıda `newClientOrderId` olarak eşlenmeli |
| Zaman senkronu | `timestamp` + `recvWindow`; saat kayarsa istek reddedilir | Small Live öncesi eklenmeli |
| Emir durumu uzlaştırma | Kullanıcı veri akışı (user data stream) ile dolum/iptal takibi | Small Live öncesi eklenmeli (journal + recovery zaten var) |
| Testnet | testnet.binance.vision: gerçek API, sahte bakiye | Small Live'dan önce zorunlu entegrasyon adımı olarak önerilir (yeni faz değil, S3 hazırlığı) |

## 3. API anahtarı güvenliği (Small Live zamanı)

- Yalnız "Okuma + Spot işlem" izni; **para çekme izni asla açılmaz**.
- IP kısıtlaması (yalnız Atlas'ın çalıştığı IP).
- Anahtar koda, sohbete, loga yazılmaz; yalnız ortam değişkeni/OS kasası. `exchange/execution_safety_gate.py`
  zaten `BINANCE_API_KEY/SECRET` varlığını kontrol eder (değeri saklamaz) ve kill switch canlı emri her zaman durdurur.
- Küçük sermaye ile başlanır; S3 ölçütleri ve sahip onayı olmadan anahtar bağlanmaz.

## 4. Binance TR (binance.tr)

- Binance TR ayrı bir platformdur; API anahtarı web arayüzünden "API Yönetimi" ile oluşturulur (mobilde yok),
  HMAC anahtarı verilir; yalnız Trade izni önerilir.
- **UNKNOWN — doğrulama gerekir:** Binance TR API'sinin uç noktaları, istek sınırları, sembolleri (TRY pariteleri)
  ve emir kuralları binance.com ile birebir aynı değildir; resmi dokümantasyon (binance.tr) okunmadan bağlantı
  kodu yazılmaz. Atlas'ın bugünkü veri sağlayıcısı binance.com public API'sidir.
- Hangi borsanın seçileceği sahibin kararıdır (komisyon, TRY likiditesi, vergi ve lisans durumu).

## 5. Türkiye mevzuatı (bilgi amaçlı, hukuki danışmanlık değildir)

- 7518 sayılı Kanun (Resmî Gazete 2 Temmuz 2024): kripto varlık hizmet sağlayıcılarının SPK izni alması zorunlu.
  Kullanılacak platformun izin durumunun güncel olarak doğrulanması gerekir (UNKNOWN).
- Vergi: kazançların beyanı gerekebilir; yabancı platformlarda OECD-CARF otomatik bilgi paylaşımı 2026'dan
  itibaren devreye giriyor. Bir mali müşavire danışılmalı.

## 6. Sonraki adımlar (Small Live hazırlığına eklenecek, sahip onayıyla)

1. `X-MBX-USED-WEIGHT` takibi ile istek ağırlığı bütçesi (hummingbot AsyncThrottler fikri).
2. `request_id` → `newClientOrderId` eşlemesi ve user data stream ile emir uzlaştırması.
3. Binance Spot Testnet üzerinde uçtan uca entegrasyon testi (gerçek para yok).
4. Borsa seçimi (binance.com / binance.tr) ve resmi API dokümanının okunması.

## Kaynaklar

- Binance Spot API: Trading endpoints, Rate limits, Order Count Decrement FAQ, FIX API (developers.binance.com)
- Binance TR API anahtarı oluşturma (binance.com/tr destek, Binance Akademi TR)
- 7518 sayılı Kanun özetleri (Andersen TR, DergiPark makalesi)
