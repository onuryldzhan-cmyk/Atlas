# ATLAS CHECKPOINT — REM-001 Gates 2–5 Assessment + Compute-Engine P2 (Timestamp-Bound Splits)

- **UTC:** 2026-09-23T19:32:15Z
- **Branch:** `research/edge-validation`
- **HEAD at start:** `3099bb6`
- **HEAD at end:** `dfcf21e` (this checkpoint is committed on top)
- **Mode:** AUDIT (Parts A–D), BUILD (Part E)
- **Classification:** CRITICAL. Parts A–D touch governance; Part E is new
  research code. The full critical gate was applied to Part E: IMPLEMENT →
  TEST → SELF-REVIEW → REGRESSION → INDEPENDENT AUDIT → FIX → RE-TEST →
  FINAL GATE.

## Objective

A five-part owner task, in this order:

- **Parts A–D:** for REM-001 Gates 2 (Reproducible Build), 3 (Deterministic
  Core Tests) and 4 (Offline & Replay Runtime), write a definition of done
  first, check real evidence against it, and certify only if the evidence
  genuinely passes. For Gate 5 (Core Refactoring), record its honest status.
- **Part E:** implement Compute-Engine P2. It binds
  `research/splitting.py`'s `make_purged_split()` output onto real
  timestamps through P1's bridge. It must fail closed whenever a real gap
  straddles a purge, embargo or split boundary.

## Completed

1. **Step 0 — governance.** Latest registry (v4.69) and HEAD verified. I
   searched the log, `governance/`, `governance/findings/` and
   `checkpoints/`: no concurrent Gate 2–5 or P2 work existed.
   - **P2 authorization check.** v4.69 lists P2 under `explicit_exclusions`
     and defers it to "its own future, separate owner decision". The owner's
     instruction this session is that decision. Its scope matches v4.69's own
     one-line definition of P2. Result: `NO_CONFLICT_PROCEED`.
   - **Registry.** `governance/current/ATLAS_MILESTONE_REGISTRY_v4.70.json`
     was committed alone as `3ed05c3`. It adds the block
     `rem001_gates_2_to_5_and_compute_engine_p2_authorization` with five
     grants: `GRANT-GATE2/3/4-CERTIFICATION`, `GRANT-GATE5-STATUS` and
     `GRANT-COMPUTE-ENGINE-P2`.
   - The record also states that no gate outcome advances REM-001's
     `current_gate`, which stays at Gate 1, open.
   - It discloses that importing `research.splitting` executes
     `research/__init__.py`, which in turn loads `hypothesis_registry`.
2. **Step 1.** I read the record back from git (`git show HEAD:…`). All five
   grants are present and unambiguous.
3. **Parts A–D.**
   - Recorded in `governance/findings/REM001-GATES-2-5_CERTIFICATION_ASSESSMENT.md`,
     committed as `f107415`.
   - REM-001's specification Parts are absent from the repository
     (GOV-DRIFT-005). The definitions of done are therefore newly authored,
     and are labelled that way in the document.
   - Outcomes: Gate 2 **PARTIAL**, Gate 3 **PARTIAL**, Gate 4 **PARTIAL**,
     Gate 5 **ongoing by design, currently in an owner-accepted state**. No
     gate is certified. Details are under *Architecture decisions* below.
4. **New Gate 3 evidence, gathered this session.** Both plugins live in the
   session scratchpad, never in the repository.
   - **Reverse-order full run** at `3ed05c3`: **1 failed, 3737 passed in
     192.71s**. This is identical to P1's forward run on the same code.
   - **Network-blocked full run** with the P2 package staged. Every
     non-loopback socket connection and DNS lookup was refused. Result:
     **0 attempts**, and **1 failed, 3812 passed in 133.85s**. This is
     identical to the canonical run.
5. **Part E — implementation.**
   - `core/research_timestamp_split_binding.py` (L3) provides
     `ResearchTimestampSplitBinder` (P1 bridge injected through the
     constructor) and `bind_split_to_timestamps(split, access)`.
   - Index *i* binds to `bars[i]`, the real archived bars, never to grid
     slots.
   - Refusals (always raised, never a returned split):
     - `GapStraddlesBoundaryError`, reporting every violation, for a gap
       inside a buffer, between a segment and its buffer, or directly
       between segments.
     - `CoverageRefusedError` when P1's coverage status is REFUSED.
     - `SplitShapeError` when `n_observations` is not the real bar count, or
       the split is not exactly `make_purged_split(n, split.spec)`.
     - `BarSequenceIntegrityError` when the bars disagree with P1's
       `gap_ranges` or `expected_count`, or are unsorted, duplicated,
       misaligned or outside the window.
   - Gaps strictly inside one segment's body, or at a window edge, are
     returned and flagged rather than refused.
6. **Part E — tests.** `tests/test_research_timestamp_split_binding.py` has
   **75 tests, all passing**. Coverage by the task's required cases:
   - **(a)** A clean window gives exactly the index math.
   - **(b)** A fixture reproduces the real BTCUSDT window 2020-12-17 00:00 →
     2020-12-26 23:00, gap for gap: the known 12-21 14:00→17:00 gap
     (4 bars) plus a real 12-25 02:00 gap (1 bar). It binds with both gaps
     flagged. The same real gap is refused once the window is shifted to
     12-15 22:00 → 12-25 21:00.
   - **(c)** A gap at each of the 10 boundary positions is refused, at gap
     sizes 1 and 7. In every case `DataSplit`'s own invariant and P1's
     FLAGGED status both say the split is safe. A separate test reproduces
     the concrete leak of the naive grid-slot binding: a label
     `label_horizon_bars` observations ahead lands inside CALIBRATION.
   - **(d)** Purge and embargo widths are exact in wall-clock time across
     the 1m, 15m, 1h, 4h and 1d timeframes.
   - Also covered: every fail-closed path, exact no-fabrication checks, and
     live runtime-closure and L3 pins.
7. **Real-archive evidence.** Read-only, from a scratch script, never from a
   test. No Python processes were running at the time.
   - The real window above binds as `BOUND_WITH_FLAGGED_GAPS`.
   - Shifting the window start one hour at a time over 200 real windows,
     **12 were refused**. The first refusal was the 12-21 gap between TRAIN
     and EMBARGO (index 135 → 136).
8. **Step E4 — architecture.**
   - `tools/build_architecture_inventory.py check`, run with the files
     staged so `git ls-files` sees them: **106 modules**, and exactly the 2
     Group B2 edges. This is unchanged from P1's baseline.
   - `compute_runtime_closure()` includes neither P1's nor P2's module.
   - No entry point references either module.
9. **Step E5 — gate.**
   - Six mutants were all caught by the tests:
     - all gaps treated as interior;
     - the gap cross-check skipped;
     - the split taken over the grid-slot count;
     - a fabricated segment start;
     - the spec-equality check removed;
     - a lax `<` instead of `<=` in the ordering check.
   - **Independent audit** (a fresh subagent given no design context):
     - The three mandated classes were all **CONFIRMED ABSENT**: silent
       boundary-gap acceptance (brute-forced over 5 specs × 99 positions),
       closure leak, and fabricated timestamps.
     - **1 MEDIUM, fixed:** a hand-built `DataSplit` with purge and embargo
       of 0/0, against a spec that required 2/3, was accepted. It is now
       refused by requiring equality with `make_purged_split(n, split.spec)`.
     - **3 LOW, fixed:** non-integer buffer sizes raised a bare
       `TypeError` (closed by the MEDIUM fix); the docstring overclaimed
       which timestamps are real bars (narrowed); several refusal paths
       were untested (tests added, including a true-duplicate case).
     - **2 INFORMATIONAL:** the closure test read a committed artifact (a
       live-computed test was added), and a note to re-stage the test file
       (done).
   - **Re-test:** 75/75 pass.
   - **Precondition check:** `tasklist` showed 0 Python processes, so no
     live Atlas was running.
   - **Full canonical suite:** `python -m pytest tests --basetemp=C:/atlas_pytest_tmp_full -q`
     gave **1 failed, 3812 passed, 2 warnings in 135.48s**.
     - The 3812 is 3737 plus the 75 new tests, so there are zero
       regressions.
     - The 1 failure is the pre-existing Group B2 test. It failed
       identically at `3ed05c3`, before the P2 files existed.
     - The 2 warnings are `PytestCacheWarning`: `.pytest_cache` is not
       writable on this host (permission denied). This is environmental,
       not a test issue.
   - Committed as `dfcf21e`.

## Files changed

| File | Commit | Change |
| --- | --- | --- |
| `governance/current/ATLAS_MILESTONE_REGISTRY_v4.70.json` | `3ed05c3` | added |
| `governance/findings/REM001-GATES-2-5_CERTIFICATION_ASSESSMENT.md` | `f107415` | added |
| `core/research_timestamp_split_binding.py` | `dfcf21e` | added |
| `tests/test_research_timestamp_split_binding.py` | `dfcf21e` | added |
| this checkpoint | next commit | added |

Nothing else was touched. No live-decision-path file, runtime-closure file,
P1 file, `research/` file, ADR, historical registry or existing findings text
was modified.

## Architecture decisions

- **P2 is a new L3 sibling module, not an extension of P1.** P1 is committed
  and audited, and its tests pin P1's import profile. P2 needs
  `research.splitting` (L3 → L4), an import ADR-0009 explicitly sanctions.
- **Indices bind to real bars, never grid slots.**
  - `n_observations` equals the actual bar count.
  - This guarantees no interpolated timestamp.
  - It also makes the naive grid-slot split, which is the leaking one,
    structurally unbindable (`SplitShapeError`).
- **The fail-closed policy is convention-independent.** A finding worth
  stating plainly: under the real-bar binding alone, a gap inside a buffer
  only *over*-removes in wall-clock time. The under-removal the owner
  described happens when a buffer sized in one unit (bars vs. hours) meets
  a label or feature computed in the other. The grid-slot leak test shows
  this. P3's convention does not exist yet, so P2 refuses wherever the two
  units can disagree at a boundary. That is correct for either convention.
- **Gate outcomes are assessments, not certifications.** They do not advance
  REM-001 `current_gate`. Whether later gates may pass while Gate 1 is open
  remains an owner decision.

## Tests

- `tests/test_research_timestamp_split_binding.py`: 75 passed (also passed
  within the full runs).
- Full canonical run: **3812 passed / 1 failed** (the B2 test).
- Reverse-order full run at `3ed05c3`: **3737 passed / 1 failed** (B2).
- Network-blocked full run: **3812 passed / 1 failed**, 0 network attempts.
- Every run used an ASCII `--basetemp` and `tmp_path`-only fixtures. No test
  was modified to make it pass.
  - After the audit fix, two existing refusal tests changed their expected
    *message* from shape wording to "sealed spec". Both still assert a
    `SplitShapeError` refusal; the refusal is now caught by the stricter
    check first.

## Current state

- `dfcf21e` plus this checkpoint. Working tree clean.
- P1 and P2 both exist and both are outside the 106-module runtime closure.
- P3 and P4 are unauthorized.
- Authority is unchanged: `production_authority=NONE`,
  `live_authority=DENIED`.

## Known issues

- **Gate 2 gaps:** the toolchain is not pinned (floating Python 3.14.x,
  unpinned pip, `windows-latest`). There has been no off-machine run
  (CI-EVIDENCE-001; no git remote). No environment-identity check exists.
- **Gate 3 gaps:**
  - Time and randomness independence is unaudited (UNKNOWN).
  - Only one non-default order (reverse) has been tested.
  - CI and `validate_atlas.ps1` report FAIL on every run by construction,
    because the accepted B2 failure sets a nonzero pytest exit code.
- **Gate 4 gap:** no offline runtime mode and no market-data replay exist.
- **CONFLICT (documentation lag, informational):**
  `governance/findings/TEST-ISO-001_…md` still says
  `OPEN_PROPOSED_REMEDIATION_NOT_IMPLEMENTED`, although `4534da8`
  implemented the fix. Not edited, because that is outside the v4.70 grants.
- **P1's LOW N+1 provenance-query finding is now observable in practice.**
  Evaluating 200 real 240-bar windows took over 2 minutes. It remains
  deferred.
- **Pre-existing:** the Group B2 test stays permanently red by owner
  decision (v4.63).

## Risks

- None to any live, execution or capital path. P2 is research-only,
  read-only, has no network access, and is outside the closure.
- `research/__init__.py` eagerly loads `hypothesis_registry` whenever P2 is
  imported. This is disclosed. P2 references none of it, and a static test
  pins that.

## Remaining work

- **P3** (`CheckResult` production) and **P4** each need their own separate
  owner decision.
- Candidate follow-ups, recorded but not authorized:
  - Gate 2: pin the toolchain, obtain one hosted CI run, add a lock-equality
    check.
  - Gate 3: audit time and randomness use; add a seeded random-order run,
    which requires a dependency decision.
  - Append an additive status section to the TEST-ISO-001 document.
  - P1: batched provenance lookup.

## Next exact action

Report to the owner and stop. Do not begin P3 or P4, do not wire P1 or P2
into the runtime (W2), and do not treat any Gate 2–4 PARTIAL as
certification without a new owner decision.
