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

## 6. 20 coin: gerçek Binance kurallarını çek (registry v5.41) — ÖNCE BU

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

## 11. Gerçekçilik ve strateji backtest'leri (her biri birkaç dakika; Ctrl+C yok)

```
python -m tools.backtest_replay --days 7 --step 15 --exp001
python -m tools.backtest_replay --days 7 --step 15 --exp001 --slippage-bps 5 --next-open-fill
python -m tools.backtest_replay --days 7 --step 15 --exp001 --slippage-bps 5 --next-open-fill --min-hold 60
python -m tools.backtest_replay --days 7 --step 15 --exp001 --slippage-bps 5 --next-open-fill --sell-confirm 2
```

1: bugünkü durum. 2: gerçekçi dolum (kayma + gecikme). 3 ve 4: al-sat sıklığını azaltan iki strateji fikri. Dördünü de yapıştır.

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
