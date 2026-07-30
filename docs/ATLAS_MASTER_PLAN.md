# Atlas AI Master Plan

## North Star

Atlas, bir al-sat botu değil; yatırım, güvenlik/kontrol ve kurumsal yönetim
sistemlerini birlikte yürüten, insan onayını kritik eylemlerin merkezinde tutan
denetlenebilir bir AI Investment Company platformudur.

## Değişmez ilkeler

1. Sermayenin korunması getiriden önce gelir.
2. AI analiz ve öneri üretir; tek başına kritik canlı eylem yetkisi alamaz.
3. Paper, shadow ve digital-twin kanıtı olmadan canlıya geçilmez.
4. Emir, pozisyon, nakit ve audit için tek doğruluk kaynağı bulunur.
5. Her karar veri soy ağacı, model/strateji sürümü ve gerekçesiyle izlenir.
6. Güvenli varsayılan, fail-closed ve geri dönüş zorunludur.
7. Kendi kendini geliştirme araştırma ve taslakla sınırlıdır; yayın insan onayı ister.

## Yetenek alanları

- Yatırım zekâsı: teknik, makro, haber, sentiment, on-chain, order book,
  funding, open interest, opsiyon ve kurumsal akış analizi.
- Strateji sistemi: rejim algılama, strateji portföyü/yarışması, benchmark,
  decay/drift tespiti, emeklilik ve sermaye tahsisi.
- Risk: trade/position/portfolio/model/likidite/korelasyon/counterparty/tail risk,
  stres, drawdown recovery, risk bütçesi ve kill switch.
- Execution: maliyet zekâsı, akıllı yönlendirme, emir durum makinesi,
  idempotency, reconciliation ve replay.
- Veri: kalite skoru, çoklu kaynak doğrulama, feature store, lineage, zaman
  senkronizasyonu, point-in-time veri ve saklama politikası.
- AI organizasyonu: CEO/Director/departman/uzman ajanlar, model konseyi, red team,
  ajan güven modeli, bütçe ve yetki sınırları.
- Kurumsal yönetim: onaylar, bağımsız denetim, model validasyonu, ADR,
  değişiklik yönetimi, canary/rollback ve teknik borç.
- Operasyon: SLO, hata bütçesi, logs/metrics/traces, akıllı alarm, runbook,
  incident/postmortem, backup restore testi ve felaket kurtarma.
- Finans/hukuk: ledger, muhasebe mutabakatı, vergi kayıtları, gizlilik,
  regülasyon hazırlığı ve gelecekte ayrı fon/müşteri hesapları.

## Teslim durumu

| Seviye | Durum | Kapsam |
|---|---|---|
| L0 – Emniyet tabanı | Mevcut/kısmi | PAPER varsayılanı, live kapalı, execution idempotency, audit, runtime durumları |
| L1 – Tek çekirdek | Kısmi | Composition root, canonical execution contract, position controller, event altyapısı |
| L2 – Doğrulanabilir paper | Sonraki kapı | Deterministik ledger, reconciliation, gerçekçi maliyet modeli, tam test piramidi |
| L3 – Intelligence platform | Planlı | Veri kalite merkezi, rejim, strateji portföyü, açıklanabilirlik ve kalibrasyon |
| L4 – Digital twin | Planlı | Shadow, stres/kaos, drift, model risk ve promotion gate |
| L5 – Kurumsal operasyon | Planlı | RBAC/onay, immutable audit, SLO, incident, DR, secrets ve supply-chain |
| L6 – Kontrollü canlı | Kilitli | Hukuk/risk onayı, testnet/soak, küçük sermaye ve kademeli ölçekleme |

## Uygulama sırası

### Faz 1 – Foundation gate

- Tek repository çalışma hattı; backup/quarantine kodunu runtime'dan ayır.
- Typed configuration, secret provider ve startup validation ekle.
- Double-entry portfolio ledger ve exchange reconciliation kur.
- Contract/unit/integration testlerini CI kapısı yap.
- Deterministik zaman, event identity/ordering ve replay kurallarını tamamla.

Kabul: yeniden başlatma sonrası aynı emir ikinci kez oluşmaz; ledger ile paper
broker bakiyesi eşleşir; kritik dependency hatasında yeni emir fail-closed olur.

### Faz 2 – Research ve risk gate

- Point-in-time veri kataloğu, quality score, lineage ve feature registry.
- Walk-forward/purged CV, fee-spread-slippage-funding içeren ortak simülasyon.
- Rejim, strategy registry/competition, benchmark ve decay/drift izleme.
- Risk committee, exposure/correlation/liquidity/tail-risk ve drawdown recovery.

Kabul: backtest-paper parity raporu, out-of-sample kanıt ve risk ihlalsiz minimum
örneklem olmadan strateji promotion edilemez.

### Faz 3 – Governance ve digital twin gate

- Agent identity/RBAC, tool/data/spend limitleri ve prompt-injection izolasyonu.
- Model registry, calibration, uncertainty, challenger/red-team ve approval queue.
- Shadow/digital twin, stres ve kontrollü chaos senaryoları.
- Değişiklik talebi → test → review → approval → canary → rollback hattı.

Kabul: hiçbir ajan onaysız risk limiti, kod yayını veya canlı execution
değişikliği yapamaz; tüm karar zinciri yeniden oynatılabilir.

### Faz 4 – Institutional operations gate

- SLO/error budget, telemetry, alarm deduplication ve operasyon paneli.
- Incident runbook, postmortem, backup/restore tatbikatı ve DR.
- Muhasebe/vergi export, veri saklama/gizlilik ve regülasyon kararları.
- Testnet soak sonrası bağımsız risk, güvenlik ve hukuk onayı.

Kabul: restore ve failover tatbikatı; kill switch testi; sıfır reconciliation farkı;
onaylı sermaye ölçeklendirme politikası. Bunlar olmadan L6 kapalı kalır.

## Kaynak belgeler

Kullanıcının dört hedef metni `docs/vision/` altında değiştirilmeden tutulur.
Bu master plan onların uygulama sırasını ve güvenlik kapılarını tanımlar;
kaynak metinlerin yerine geçmez.
