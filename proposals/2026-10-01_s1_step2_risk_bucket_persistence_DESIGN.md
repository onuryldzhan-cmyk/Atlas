# S1 step 2: keep each open position's risk bucket. Design, not implemented (2026-10-01)

**Status:** DESIGN ONLY. Classified CRITICAL because it changes the durable financial state. Nothing is coded until the owner and an independent audit approve this design (CLAUDE.md rule 7, Financial / migration safety).

## Why
S1 sleeves (`core/risk_engine.py`, `sleeves_enabled`, default OFF) need each open position's risk bucket. Today `ExecutionManager` builds `PositionExposure(symbol, base, mark, base*mark)` without `risk_bucket`. With sleeves ON, every open position would count as "unknown bucket". Because of that, the switch must stay OFF until this is done.

## Facts (verified in code, 2026-10-01)
- Open positions live in `execution_financial_state.json`, which is at `schema_version 2` (`core/execution_portfolio_foundation.py:35`).
- `load()` refuses any other version: schema 1 raises a migration error, anything else means recovery required.
- Closed-position records have a fixed required-field list (`_CLOSED_POSITION_REQUIRED_FIELDS`, line 340).
- The risk bucket of the opening BUY is known at admission (`RiskRequest.risk_bucket=request.risk`, `core/execution_manager.py:3301`), but it is not written anywhere durable.

## Options
| | Option | Risk |
|---|---|---|
| A | Add an optional `risk_bucket` field to open positions in the financial state, as schema v3 with an explicit offline migration (v2 → v3, old positions set to `UNKNOWN`) | Touches the financial truth file; needs the full migration checklist |
| B | Separate append-only sidecar `position_risk_buckets.jsonl` keyed by `position_id`, written after a confirmed open; the financial state is untouched | Two files can disagree: a crash between them leaves a position without a bucket, which reads as `UNKNOWN` (fail-closed) |
| C | Do not persist; recompute from the audit log | The audit window is limited and this is look-back inference: rejected |

**Recommendation: B.** The financial truth file and its schema stay unchanged. A missing or contradictory entry is always treated as `UNKNOWN`, and with sleeves ON the most conservative bucket limit applies to `UNKNOWN`. That way, missing evidence can never loosen a limit (the same principle as NB-4).

## Migration checklist (for option B)
- **Idempotency:** the record key is `position_id`. A repeat of an identical record is a no-op; a different bucket for the same id makes that position UNKNOWN (see audit changes below).
- **Resume / retry:** written only after the open has been committed. On restart, open positions with no record get `UNKNOWN`. Nothing is backfilled by guessing.
- **Sequence / ordering:** append-only; one record per position.
- **Duplicates:** identical lines are tolerated; contradictory ones mean halt.
- **Partial state:** a truncated last line is a corrupt file, which halts the sidecar read and makes every bucket `UNKNOWN`. Trading itself is not blocked, because sleeves are OFF by default.
- **Conflicts:** reported, never auto-resolved.
- **Rollback:** delete the sidecar. That is safe: everything returns to `UNKNOWN`.
- **Backup:** add the file to `tools/state_backup.py` (it already copies the whole state directory).

## Tests required before an audit
- A bucket is written after an open and read back.
- Restart: an old position with no record is `UNKNOWN`.
- A conflicting record halts.
- A truncated file means everything is `UNKNOWN`.
- With sleeves ON, `UNKNOWN` gets the strictest limit.
- With sleeves OFF, behaviour is byte-identical.

## Decision required
Owner: approve A or B (recommended B), or reject. Then an independent audit, then the switch-on.

## Changes after the independent audit (2026-10-01, `docs/audits/INDEPENDENT_AUDIT_S1_STEP2_2026-10-01.md`)
- **F-1 (HIGH), fixed.** UNKNOWN now counts against **every** sleeve, not only the smallest one. The old rule let a lost bucket free up its real sleeve (NB-4).
- **F-2, checked.** The runtime refuses a second BUY on an open position (`DUPLICATE_OPEN_POSITION`, verified by a test), so a position never gets a second bucket. If records ever disagree, the position reads UNKNOWN, which is now the strictest outcome.
- **F-3, partly fixed.** A corrupt file is logged once at ERROR level. Repair stays with the owner; deleting the file is safe.
- **F-4, design text corrected.** The record is written **before** the durable commit, not after. This is harmless: position ids are deterministic per `request_id`, and an id whose open never commits is never looked up.
- **F-5, mostly fixed** (re-audit R-3: still missing a restart test and a full flag-off decision comparison; the wiring test only checks a line of source text). The weak `hasattr` test was replaced. Tests were added for: an add-on under a different bucket, a failing sidecar not changing the trade, the wiring, and NB-4 evidence removal.
- **F-6 / F-7 deferred:** file growth and reading cost; a lock between read and append, and Windows behaviour (UNKNOWN).
