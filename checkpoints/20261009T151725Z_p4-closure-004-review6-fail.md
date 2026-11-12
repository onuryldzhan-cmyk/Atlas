# ATLAS CHECKPOINT — P4-CLOSURE-004 remediation, independent review round 6: FAIL (2026-10-09)

**Status: INCOMPLETE — STOPPED for owner decision.** Phase 4 is **not** closed; P4-7 is **NOT MET**. Rounds 1–5 are committed as UNVERIFIED WIP (`8b847f4`, `5a97dd3`, `75660d7`) on `claude/exp001-on-owner-lineage`. Round 6 is in the working tree, uncommitted. This file grants no authority. Predecessor: `20261009T100523Z_p4-closure-004-review5-fail.md`.

**Objective:** close R5-1 and R5-3, and document R5-2, R5-4 and the INFO items, as authorized by the owner for round 6. Then pass a fresh-context review.

## Round-6 changes (uncommitted)
- `tools/strategy_compare.py`
  - R5-1: a refused registered run (`StudyRegistrationError`) writes a REFUSED result (non-evidence) to `--output`.
  - R5-3: `_candle_open` requires before the run is recorded:
    - 12 columns;
    - close time = open time + 59 999 ms;
    - finite, positive OHLC;
    - non-negative volume.
  - The docstring records gap windows and the residuals R5-2, R5-5, R5-6 and historical BETTER records.
- `tools/agent_cycle.py` (R5-1)
  - A REFUSED result becomes one REFUSED memory record plus a `strategy_compare.refused` marker; later launches run exploratory, with the reason in the summary.
  - At launch, the sealed universe is checked against the universe selection; drift is handled as a refusal.
  - Every fallback states its reason in the launch summary.
- `.claude/hooks/atlas_proposal_write_guard.py`: the R5-4 gaps are documented as residual.
- `tests/test_research_preregistration_enforcement.py`
  - New tests: R5-1 (tool refusal recorded once, then exploratory; universe drift; a new hypothesis after a refusal; a REFUSED result is never evidence) and R5-3 (six malformed-row cases).
  - The "no output file" assertions became `_no_evidence()`; the change is documented in the helper.

## Tests
- Focused suites + `tests/architecture`: **3609 passed**.
- Full suite: **10192 passed, 0 failed, 12 skipped**, exit 0.
- Reviewer 6 targeted runs: 3384 + 86 passed.

## Review round 6 verdict: FAIL. No BLOCKING/HIGH open.
- **REMEDIATED:**
  - F-1 (4000-roster property probe: 0 NB-4/NB-5 violations), F-2 (end-to-end registered daily study verified), F-3, F-5, F-6;
  - N-1, N-3;
  - NF-1..NF-7;
  - NEW-1..NEW-4;
  - R4-1, R4-2.
- **PARTIAL, documented:** F-4, N-2.
- **NOT VERIFIABLE:** N-4.
- **Documented residuals:** R5-2, R5-4, R5-5, R5-6, R5-7.
- **PARTIAL:** R5-1 (crash case, see R6-1); R5-3 (see R6-2).
- **Reviewer's answers on the round-6 mechanisms:**
  - They cannot promote evidence: REFUSED never verifies, and a forged REFUSED file can only demote.
  - They do not wedge the agent by themselves.
  - They can block a legitimate study permanently through the universe check (R6-3).

### Open findings
- **R6-1 MEDIUM (operational): a registered daily run that crashes still stalls silently.**
  - Triggers, which escape `main()` before `start_study_run`:
    - a persistent download `OSError`, e.g. a delisted symbol in the sealed universe;
    - a malformed exchange row (e.g. `int(r[6])` TypeError).
  - Effect: no output; the hypothesis stays REGISTERED; stderr is discarded; it relaunches registered every timeout, and the summary reads "still running".
  - Fix: catch download/parse errors before the run is recorded and write a non-evidence FAILED result. The agent records and reports it, without the permanent refused marker, because such errors may be transient. Or document it as a residual.
- **R6-2 LOW:** `_candle_open` accepts:
  - float or string open times;
  - high < low;
  - non-numeric columns 7–9.
  The replay did not crash on these rows. Fix: validate columns 7–10 and require low ≤ open/close ≤ high, or correct the docstring's "checked in full".
- **R6-3 LOW:** the launch-time universe check compares sorted lists (the tool uses sets) and runs before the window-ended check. A duplicate symbol, or drift while waiting for the window to end, refuses the hypothesis for good. Recovery (deleting `strategy_compare.refused`) is undocumented. Fix: compare as sets, check only after the window has ended, and document the recovery.
- **R6-4 INFO:**
  - A repeated REFUSED file's summary says "written to memory", but no new record is written.
  - A forged REFUSED file can add a misleading demotion record (file-write residual).
  - Host names that resolve to loopback (e.g. `*.nip.io`) pass the hook's "public host" check.

## Trend for the owner
Six rounds have closed every HIGH. Since round 4, each FAIL has rested on one MEDIUM in the *liveness* of the daily research path (stall/visibility), not on evidence promotion. The reviewer states that fixing or documenting R6-1 leaves only LOW/INFO.

## v5.88 inputs (prepared, not a record; no signature invented)
- Unchanged from the predecessor checkpoints.
- R5-7: owner approval is UNKNOWN for two new on-disk formats: the binding file `strategy_research_registration.json` and the result/memory `study` block. The `strategy_compare.refused` marker is new in round 6, also UNKNOWN.
- P4-7 is NOT MET.

## Next exact action (owner decides)
1. Round 7: fix R6-1 (non-evidence FAILED result, recorded, transient), plus R6-3 and R6-2 (small). Or document R6-1 (and the LOWs) as residual. Then a 7th review.
2. Whether to commit the round-6 tree as UNVERIFIED WIP.
3. Only on PASS: commit/push, then the v5.88 closure proposal. Phase 4 stays OPEN; tasks 005–015 stay BLOCKED.

## Owner decisions after this checkpoint (2026-10-09, in session)
- Round 7 authorized:
  - **R6-1:** catch download/parse errors before the run is recorded and write a non-evidence FAILED result that the agent records and reports. Use no permanent marker, so the run is retried.
  - **R6-3:** run the universe check as a set comparison, only after the window ends, and document the recovery path.
  - **R6-2:** validate the full candle, including columns 7–10 and low ≤ open/close ≤ high.
  - Then a 7th fresh-context review.
- Commit the round-6 tree as UNVERIFIED WIP.
