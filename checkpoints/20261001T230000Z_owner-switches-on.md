# ATLAS CHECKPOINT — 2026-10-01: owner switches ON, R-2/R-3 closed, event API

## Completed (pushed)
- **S1 re-audit R-2:**
  - a corrupt sidecar now shows in `/api/readiness` as `position_risk_buckets` FAIL;
  - owner repair tool: `python -m tools.position_risk_buckets_repair <file>` (drops only an unfinished last line, keeps `.bak`).
- **R-3:**
  - restart test through the real wiring;
  - full flag-off decision comparison.
- **Event contract:**
  - `events_from_records` adapter;
  - read-only, loopback-guarded `GET /api/events`.
- **Owner switch-on ("Aç onayı da veriyorum"):** `main.py` now passes `count_unrealized_in_daily_loss=True`, `sleeves_enabled=True` and `paper_slippage_bps="5"`.
  - `AtlasApplication` defaults stay OFF, so existing tests and tools keep their baselines. This is the same opt-in pattern as `paper_fee_rate`.
  - Tests: `tests/test_owner_switches_2026_10_01.py` covers the literals in `main.py`, the wiring into the engines, the defaults staying off, and a PAPER round trip with everything ON.

## Tests
Last full suite: 6238 passed, 1 failed, 12 skipped. The failure is `test_execution_audit_trail_completeness.py::test_c2_failure_after_booking_marks_both_events_and_rerun_is_unaffected`. That file passed 62/62 three times in a row on its own. The cause is UNKNOWN: possibly order- or time-dependent. Not root-caused.

An earlier unidentified intermittent failure was also seen once this session.

## Known issues
- The intermittent test above needs investigation.
- Positions opened before the sidecar existed read UNKNOWN and are charged to every sleeve. This is expected and conservative.

## Next exact action
1. Investigate the intermittent c2 test (run the full suite with `-p no:randomly`; check date / accounting-day dependence).
2. Owner: update the machine and restart Atlas (commands are given when the owner writes "geldim").
