# ATLAS CHECKPOINT — G1 refresh withholds venue bounds; Block 6B reaffirmed

Branch `research/edge-validation`. Task class: CRITICAL (governance and venue rules that the live gate depends on). The full critical gate was applied.

## Objective
Fix `tools/refresh_venue_instrument_rules.py` (G1) so it can restore FRESH venue rules without ever writing Block 6B upper bounds into the shipped `config/instrument_rules.json`. Decouple the shipped-config freshness tests from a hardcoded date. Re-apply the live refresh. Close the investigation that spans 21dca17, the R1 revert 00e4f04 and this fix.

## Completed
- **Part A (4fa8db3):** the tool validates the full venue payload, maxima included, through the unchanged `publish_venue_rules`, publishing into a `tempfile` staging directory. The destination receives only the ruleset with `max_quantity`, `max_notional` and `market_max_quantity` removed. `_write_withheld_document` writes it with temp file, fsync and a canonical re-load. It refuses if a bound appears in the raw JSON or the loaded rules, then checks the digest and FRESH status before `os.replace`. Provenance: `venue_upper_bounds_modelled=false`, `venue_upper_bounds_policy=WITHHELD_FROM_SHIPPED_CONFIG`.
- **Part B:** in the two 6A shipped-config tests, the clock is now the shipped config's newest `retrieved_at` plus 12 minutes. A STALE assertion (oldest stamp + threshold + 1 s) was added.
- **Premise conflict, resolved by the owner in session:** 6B `test_live_authorized_runtime_halts_when_maxima_are_unmodelled` was pinned to 2026-08-19. The freshness gate precedes the bounds gate, so any refresh produced `VENUE_RULES_PROVENANCE_INVALID`. That, not bounds, caused the halt-reason change 00e4f04 attributed to bounds. The owner chose the narrow fix: only `SHIPPED_OBSERVED_AT` is now derived from the file.
- **Part C:** live refresh from Binance. serverTime 1790530646985, retrieved_at 2026-09-27T17:37:28Z, FRESH. Symbols unchanged: BNB, BTC, ETH, SOL and XRP USDT. The raw JSON has no bound field.
- **Part D:** full suite run, results under Tests.
- Independent audit: no BLOCKING, HIGH or MEDIUM findings. LOW-2 was fixed with a missing-only-a-maximum refusal test.
- Governance registry v4.94 records this under key `venue_rules_refresh_bounds_withheld_and_block6b_reaffirmed`.

## Files changed
`tools/refresh_venue_instrument_rules.py`, `tests/test_refresh_venue_instrument_rules.py`, `tests/test_block6a_venue_rule_freshness.py`, `tests/test_block6b_venue_upper_bounds.py` (SHIPPED_OBSERVED_AT only), `config/instrument_rules.json`, `governance/current/ATLAS_MILESTONE_REGISTRY_v4.94.json`, and this checkpoint.

## Architecture decisions
- The shipped config never carries venue maxima written by G1. The Block 6B disposition is reaffirmed unchanged, and a G1 run is not operator verification of bounds.
- `tools/venue_metadata_adapter.py` is unmodified. The strip lives only in the G1 tool.

## Tests
- 6B with the new config: 31 passed. With the 21dca17 bounded config swapped in: 3 failed, so the tests still catch bounds.
- 5D + 6C + 6A + refresh tests: 104 passed.
- Full `pytest tests` on the final production code: **2 failed, 5109 passed (5111 collected)**. The failures are B2 `test_forbidden_layer_imports` and D5 `test_committed_artifact_matches_current_source`. No OneDrive flakiness occurred in this run.
- After the audit, one test-only addition; the refresh test file gave 17 passed.
- The tests that failed on 21dca17 because bounds were present needed no edits.

## Current state
HEAD holds 4fa8db3 plus the governance/checkpoint commit. The shipped rules are FRESH as of 2026-09-27T17:37:28Z; with the 30-day policy they go stale around 2026-10-27. Authority is unchanged: production NONE, live DENIED, autonomous deployment DENIED.

## Known issues
The B2 and D5 known failures are unchanged. OneDrive `os.replace` flakiness remains possible; it was out of scope.

## Risks and deferred items
- **LOW-1:** live-fetched decimals carry 8 places (for example `0.00001000`), so `floor_to_step` output strings change shape. They are numerically equal and digests are normalized. Whether any persisted-state code compares these strings is UNKNOWN (requires verification). Deferred.
- **LOW-3 (existed before this change):** the 6B premise test checks only `has_complete_venue_bounds is False`, so a partial hand-added bound would pass it. Tightening it needs owner approval.
- **INFO:** a failed staging-dir cleanup could leave a bounded file in %TEMP%. The diff is printed after `os.replace`.

## Remaining work
None for this package.

## Next exact action
Monthly: re-run `python tools/refresh_venue_instrument_rules.py`, review the diff, commit. Owner to decide whether to address LOW-1 or LOW-3.
