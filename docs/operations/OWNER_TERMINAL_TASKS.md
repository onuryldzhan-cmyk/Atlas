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

## Done (kept for reference)

- Audit-fork quarantine applied 2026-09-28 (registry v5.06).
- 2026-09-28 evening run of 8b54758 (registry v5.19): pre-flight ready=True;
  position report OK (5 EXP-001 positions); Windows single-instance lock
  proven (exit 76); SELL fix proven live (BNB/SOL/XRP closed, 3W/0L).
- Volatility ceiling measured (30 days); owner chose p30 (registry v5.20).
