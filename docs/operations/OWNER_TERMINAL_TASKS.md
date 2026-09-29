# Owner terminal tasks (pending)

Commands the owner runs on the Windows machine. Keep this list current:
remove an item once its output has been reviewed, add new ones as they
arise. Every command below is run in **one** PowerShell window, in the
Atlas-test worktree:

```powershell
cd "C:\Users\HUAWEİ\OneDrive\Masaüstü\ATLAS_CODEX_COMPLETE_LATEST_STATE_2026-07-30\SOURCE_REPOSITORY\Atlas-test"
git fetch origin claude/exp001-on-owner-lineage
git checkout origin/claude/exp001-on-owner-lineage
```

Rules: only one Atlas at a time (a second one now exits with code 76).
Do not press Ctrl+C in the Atlas window unless you mean to stop it; copy
with Ctrl+Shift+C.

## 1. FIRST on the new build: configuration check (read-only)

```powershell
python -m tools.show_config
```

Since CFG-001 (registry v5.21) Atlas refuses to start when an unknown
`ATLAS_*` environment variable is set (owner decision). This prints the
effective settings, or every problem found. Continue only if it prints
`OK - configuration valid.` If it lists an unknown variable, paste the
output; do not start Atlas.

## 2. Before every new build: pre-flight (read-only)

```powershell
python -m tools.check_execution_authority_agreement
```

Start Atlas only if it prints `ready=True`.

## 3. EXP-001 results (read-only, safe while Atlas runs; any time, and on 2026-10-12)

```powershell
python -m tools.exp001_report
```

Shows EXP-001 trades vs policy-floor trades: win rate (with a 95% range),
gross P&L, fees, holding time, and whether the sample is big enough to
conclude anything (needs >= 30 closed trades). Paste the output.

## 4. Performance baseline + panel telemetry card (read-only, safe while Atlas runs)

```powershell
python tools/extract_candle_age_telemetry.py
python tools/extract_candle_age_telemetry.py --json > reports/observability/telemetry_summary.json
```

The first prints cycle-duration and candle-age statistics (paste the output;
it becomes the PERF-001 baseline). The second fills the panel's Telemetri card.

## 5. Backtest: today's behaviour vs staged buying/selling (read-only; several minutes each)

```powershell
python -m tools.backtest_replay --days 7 --step 15
python -m tools.backtest_replay --days 7 --step 15 --staged --sleeves
```

The first run is today's behaviour. The second adds the approved staged
entries/exits and the 50/35/15 capital split. Paste both outputs. Macro and
sentiment are excluded (stated in the report), so the result is a
conservative research estimate, not a promise.

## 0. SIRADAKİ (2026-09-29 akşam) — sırayla, Atlas-test klasöründe

Atlas'ı kapat (Ctrl+C bir kez), sonra:

```
git fetch origin claude/exp001-on-owner-lineage
git merge --no-edit origin/claude/exp001-on-owner-lineage
python -m tools.strategy_compare --days 21 --windows 3
python -m tools.performance_report --record
python -m tools.strategy_agent
python -m tools.strategy_agent --apply
git add governance/records
git commit -m "Owner run: strategy agent proposals"
git push origin HEAD:claude/exp001-on-owner-lineage
python -m tools.start_atlas
```

Bu tek komut Atlas'ı ve ajanları birlikte başlatır; bundan sonra `python atlas_supervisor.py` yerine bunu kullan. Ajanlar her saat performans analizi, strateji önerisi, öz-değerlendirme, veri sağlığı ve güvenlik taraması yapar; sonucu Ajanlar sayfasında görürsün. Kayıtları arada bir `git add governance/records`, commit ve push ile gönder.

strategy_compare bitene kadar tuşa basma ("24/24 bitti" yazar); tabloyu yapıştır. strategy_agent önerileri
"Hafıza → Öneriler ve hafıza" sayfasına düşer; onay yalnız senin imzanla olur.

Bekleyen kararların: (1) ajanlar için Anthropic API anahtarı (yalnız senin makinende, ANTHROPIC_API_KEY), (2) aylık bütçe
(öneri 20 $), (3) önce hangi ajanlar (öneri: araştırma, strateji, test, inceleme; kod ajanı kapalı başlar), (4) max_positions
(20 coin için 5 dar), (5) EXP-001 kararı (12 Ekim).

## 6a. 20 coini gerçek veriyle seç: 8 trend / 8 orta risk / 4 yüksek risk (registry v5.51) — ÖNCE BU

Atlas kapalıyken:

```
git pull
python -m tools.select_universe
python tools/refresh_venue_instrument_rules.py --symbols-file config/universe_selection.json
git add config/universe_selection.json config/instrument_rules.json
git commit -m "20-coin universe from Binance data + venue rules"
git push
```

Seçim listesini ve iki çıktıyı bana yapıştır. (6. adımdaki sabit liste yerine bunu kullan.)

## 6. 20 coin: gerçek Binance kurallarını çek (registry v5.41) — eski yol

Bulut ortamı Binance'e erişemiyor; kurallar yalnızca senin bilgisayarında, Binance'ten çekilebilir. Atlas kapalıyken:

```
git pull
python tools/refresh_venue_instrument_rules.py --preset owner-20
git diff --stat config/instrument_rules.json
git add config/instrument_rules.json
git commit -m "Venue rules for the owner's 20 coins (Binance exchangeInfo)"
git push
```

Bir coin Binance'te TRADING değilse araç `REFUSED` der ve dosyaya dokunmaz; çıktıyı bana yapıştır. Başarılıysa Atlas'ı yeniden başlat: 20 coin taranır (en fazla 5 açık pozisyon, risk sınırları aynı).

## 7. Sahip imza anahtarı (registry v5.39) — bir kez

```
python -m tools.atlas_org_cli owner-init
```

Anahtar `C:\Users\<sen>\.atlas\owner.key` içinde oluşur. Kimseyle paylaşma, depoya koyma. Onaylar bu anahtarla imzalanır.

## 8. Yeni sayfalar

Atlas çalışırken tarayıcıda: `http://127.0.0.1:8000/home` (sade başlangıç), `/trading` (sermaye, kâr/zarar, pozisyonlar), `/hq` (3D merkez).

## 9. Öz-değerlendirme (isteğe bağlı)

```
python -m tools.atlas_self_review
python -m tools.atlas_self_review --apply
```

İlki yalnızca gösterir; ikincisi görevleri açar (paneldeki "Görevler" bölümünde görünür).

## 10. Veri sağlık denetimi (salt okunur; Atlas çalışırken de güvenli)

```
python -m tools.data_health_check
```

Her satır OK / WARN / FAIL / UNKNOWN. Çıktıyı bana yapıştır; FAIL varsa birlikte bakarız.

## 11a. TEK KOMUTLA tüm stratejileri karşılaştır (önerilen; uzun sürer, Ctrl+C yok)

```
python -m tools.strategy_compare --days 21 --windows 3
```

Tabloyu bana yapıştır. (Aşağıdaki 11. bölümdeki tek tek komutlara artık gerek yok.)

## 11. Gerçekçilik ve strateji backtest'leri (her biri birkaç dakika; Ctrl+C yok)

```
python -m tools.backtest_replay --days 7 --step 15 --exp001
python -m tools.backtest_replay --days 7 --step 15 --exp001 --slippage-bps 5 --next-open-fill
python -m tools.backtest_replay --days 7 --step 15 --exp001 --slippage-bps 5 --next-open-fill --min-hold 60
python -m tools.backtest_replay --days 7 --step 15 --exp001 --slippage-bps 5 --next-open-fill --sell-confirm 2
```

1: bugünkü durum. 2: gerçekçi dolum (kayma + gecikme). 3 ve 4: al-sat sıklığını azaltan iki strateji fikri. Dördünü de yapıştır.

Strateji araştırmasından üç fikir daha (docs/research/TRADING_STRATEGY_COMPARISON_2026-09-29.md):

```
python -m tools.backtest_replay --days 7 --step 15 --exp001 --slippage-bps 5 --next-open-fill --trend-ema 20
python -m tools.backtest_replay --days 7 --step 15 --exp001 --slippage-bps 5 --next-open-fill --atr-stop 2
python -m tools.backtest_replay --days 7 --step 15 --exp001 --slippage-bps 5 --next-open-fill --atr-stop 2 --risk-per-trade 0.01
```

5: 1 saatlik trend filtresi. 6: oynaklığa göre stop. 7: işlem başına en fazla %1 risk.

## 12. Atlas'ın kendi işlemlerinden öğrendikleri

```
python -m tools.performance_report
```

## Done (kept for reference)

- Audit-fork quarantine applied 2026-09-28 (registry v5.06).
- 2026-09-28 evening run of 8b54758 (registry v5.19): pre-flight ready=True;
  position report OK (5 EXP-001 positions); Windows single-instance lock
  proven (exit 76); SELL fix proven live (BNB/SOL/XRP closed, 3W/0L).
- Volatility ceiling measured (30 days); owner chose p30 (registry v5.20).
