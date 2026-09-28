# Atlas recovery runbook (Phase 2–3 item 6)

What to do when Atlas refuses to start or stops trading because of its own
durable state. Every row below was verified on 2026-09-28. The evidence is
named in each row. A row saying **"no repair tool"** means exactly that:
stop and ask. Do not hand-edit state files.

## Before anything

1. **Stop Atlas.** Only one Atlas may run per state root. A second one exits with code 76.
2. **Back up the whole state root before touching anything:**
   ```powershell
   Copy-Item C:\AtlasState "C:\AtlasState_backup_$(Get-Date -Format yyyyMMdd_HHmmss)" -Recurse
   ```
3. **Never delete or edit a line in any `*.jsonl` or `*.json` state file by hand.**

## Symptoms → outcome → action

| Symptom (log / exit code) | Cause | What Atlas does | Action | Evidence |
|---|---|---|---|---|
| `Audit event chain verification failed: Previous hash mismatch at line N`, exit **75** | Audit log forked, e.g. two Atlas processes wrote to it | Refuses to start. The supervisor does not restart it. | 1. `python -m tools.diagnose_audit_chain_fork <audit.jsonl>` (read-only). 2. If exactly one break chains from an earlier line: `python -m tools.quarantine_audit_fork <audit.jsonl> --lines A-B` (dry run), check it, then add `--apply`. 3. Record the repair in a successor registry. | registry v5.05, v5.06; `tests/test_quarantine_audit_fork.py` |
| `Audit ... Event hash mismatch`, or more than one break | Tampering, or corruption the fork tool does not cover | Refuses to start (exit 75) | **No repair tool.** Stop, keep the backup, report. | fork tool refuses anything but a single clean fork |
| `Another Atlas instance holds ...atlas.instance.lock`, exit **76** | A second Atlas on the same state root | The second process exits at once. The first keeps running. | Close the extra window. `Get-Process python` shows what is running. | registry v5.05, v5.08; `tests/test_single_instance_and_integrity_exit.py` |
| `Instance lock unavailable: ...`, exit **1** | State root missing or not writable | Refuses to start | Check `ATLAS_STATE_DIRECTORY`. The folder must exist and be writable. | `test_unusable_state_root_is_a_normal_failure_not_run_unlocked` |
| `Execution idempotency state load failed` / `DurableAppendLogCorruptError: execution_idempotency` | Malformed line in `execution_idempotency.jsonl` | Starts, but execution is **halted** (BUY → `RECOVERY_REQUIRED`) | **No repair tool.** Stop, keep the backup, report. | registry v5.09; `tests/test_corrupt_execution_state_fails_closed.py` |
| `Execution transaction journal load failed` | Malformed line in `execution_transaction_journal.jsonl` | Starts, execution **halted** | **No repair tool.** Stop and report. | same |
| `portfolio_state_ready=False` | `execution_financial_state.json` unreadable | Starts, execution **halted** | **No repair tool.** Stop and report. | same |
| `reservation_state_ready=False` | `capital_reservations.json` unreadable | Starts. BUY refused with `CAPITAL_RESERVATION_STATE_NOT_READY`. | **No repair tool.** Stop and report. | same |
| BUY rejected `RISK_STATE_RESTORATION_FAILED` | `risk_accounting_state.json` truncated, empty or missing | Starts, every BUY refused | **No repair tool.** Stop and report. | registry v5.11; `tests/test_corrupt_risk_state_fails_closed.py` |
| Supervisor log `Atlas child unresponsive` | Main loop hung | The child is stopped and restarted within the budget. After repeated hangs the supervisor gives up (exit 1). | Paste the log. Do not restart in a loop by hand. | `tests/test_process_supervisor.py` |

## Known gaps (UNKNOWN / not yet decided)

- **No repair tools exist for the idempotency log, the journal, the financial state, the reservation store or the risk state.** Recovery for these needs an owner-approved procedure first.
- **Exits while halted.** Whether a *held* position can still be exited while a corrupt store has halted execution has not been decided. See the Phase 2–3 proposal, item 1.
- **Panel coupling.** A panel (web) failure stops Atlas by design. See the Phase 2–3 proposal, item 5.
