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

## 0. FIRST: pre-flight before starting the new build (read-only)

```powershell
python -m tools.check_execution_authority_agreement
```

Registry v5.13 tightened the startup agreement check between the idempotency log and the transaction journal. Start Atlas only if this prints `ready=True`. Otherwise paste the output and do not start Atlas.

## 1. Volatility ceiling measurement (read-only, safe while Atlas runs)

```powershell
python -m tools.measure_volatility_ceiling
```

Takes a few minutes (downloads 30 days of 1-minute prices). Paste the
output; the LOW ceiling for the risk_level proposal is chosen from it.

## 2. Position report (read-only, safe while Atlas runs)

```powershell
python -m tools.paper_position_report
```

Confirms all five open positions were admitted under EXP-001 (BNB's line
was mis-attributed before commit f23d0bd) and shows unrealized P&L.

## 3. Run Atlas and watch (the long-running one)

```powershell
python atlas_supervisor.py
```

Then open http://127.0.0.1:8000 . Check:
- the gates legend shows `EXP-001 AKTİF … kullanılan N/50`;
- BTC/SOL/ETH/XRP/BNB cards say `≥ 60 gerekli (EXP-001 deneyi, PAPER; politika ≥ 80)`;
- when a SELL arrives: held symbols close, unheld ones log `treated as HOLD` /
  `NO_POSITION_TO_SELL`, never `INVALID_FINANCIAL_INPUT`.

Stop with one Ctrl+C in that window and paste the last ~40 lines.

## Done (kept for reference)

- Audit-fork quarantine applied 2026-09-28 (registry v5.06).
