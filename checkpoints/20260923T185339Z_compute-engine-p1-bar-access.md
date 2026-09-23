# ATLAS CHECKPOINT — Compute-Engine P1 (Bar/Coverage Access)

- **UTC:** 2026-09-23T18:53:39Z
- **Branch:** `research/edge-validation`
- **HEAD at start:** `772b7f4`
- **HEAD at end:** `e3f0c8e`
- **Mode:** BUILD
- **Classification:** CRITICAL (governance authorization required and
  granted this session; full critical-task final gate applied: IMPLEMENT →
  TEST → SELF-REVIEW → REGRESSION → INDEPENDENT AUDIT → FIX → RE-TEST →
  FINAL GATE).

## Objective

Implement P1 only of the compute-engine proposal: a new L3 module for
read-only archived-bar access over a requested window, plus a fail-closed
expected-count / actual-count / gap / provenance contract, per a six-step
task brief (governance authorization, governance check, real-data
investigation, implementation, adversarial tests, architecture verification,
then full gate / audit / regression / commit). No check computation
(BACKTEST/WALK_FORWARD/etc.) is in scope; `research/hypothesis_registry.py`
is never imported.

## Completed

1. **Pre-Step-0 conflict disclosure.** Before writing any governance record,
   this session independently verified the task brief's premise — that the
   owner had already accepted the compute-engine proposal with an existing
   P1–P4 breakdown — against the actual governance registry, and found the
   opposite: the proposal's recorded disposition was **DEFER**
   (`GRANT-COMPUTE-ENGINE-DEFER`, registry v4.56/v4.57, restated unchanged
   through v4.68), explicitly requiring a new owner decision to revisit, and
   the same registry's own text already noted no P1–P4 breakdown exists
   anywhere in the repository. This was disclosed to the owner as a
   CONFLICT (Expected/Actual/Evidence/Impact/Decision Required) before any
   file was written. Presented with three options via `AskUserQuestion`, the
   owner selected **"Confirm ACCEPT now"** — explicitly treating that chat
   response as the new owner decision needed to supersede the DEFER for P1
   only. This is recorded as the authorization basis in the governance
   record below.
2. **Step 0 — governance authorization.**
   `governance/current/ATLAS_MILESTONE_REGISTRY_v4.69.json`, new top-level
   block `research_edge_validation_compute_engine_p1_authorization`,
   `grant_id: GRANT-COMPUTE-ENGINE-P1-BAR-ACCESS`, committed alone as
   `4ea5732`. Additively supersedes `GRANT-COMPUTE-ENGINE-DEFER` for P1
   only; P2 (purged splits), P3 (`CheckResult` production) and P4 remain
   unauthorized. The record fixes the module path
   (`core/research_market_data_bridge.py`) and tool path
   (`tools/inspect_research_market_data_coverage.py`), and captures this
   session's own pre-change baseline as evidence: a 106-module runtime
   closure (grown from the 105 recorded at Package C,
   `checkpoints/20260920T165052Z_research-evidence-bridge-package-c.md`),
   the 2 pre-existing Group B2 forbidden edges (unrelated, already
   accepted), and real archive state read via
   `tools/fetch_historical_market_data.py --coverage-only` (360,980 bars /
   364 batches across BTCUSDT/ETHUSDT/BNBUSDT/SOLUSDT/XRPUSDT, each with
   real gaps).
3. **Step 1 — governance check.** Record read back from git commit `4ea5732`
   directly (not from memory); grant id, module path, tool path and
   exclusion count confirmed unambiguous. No STOP condition triggered.
4. **Step 2 — investigation.** Read `data_layer/market_data_archive_sqlite.py`
   and `core/research_evidence_bridge.py` (the ADR-0009 structural
   precedent) in full. Confirmed via `classify_module` that `core/*.py`
   already resolves to L3 through an existing generic `layer_rules` pattern
   — unlike `research/*` before ADR-0009 — so no
   `packaging/atlas_architecture_map.json` edit was needed for the new
   module or the new tool (the tool classifies as `None`, matching
   `tools/fetch_historical_market_data.py`).
5. **Step 3 — implementation.**
   `core/research_market_data_bridge.py`: `ResearchMarketDataBridge`,
   `load_window(symbol, timeframe, window_start, window_end)`.
   Constructor-injects `MarketDataSQLiteStorage` (required, not optional —
   mirrors `ResearchEvidenceBridge`'s conservative default). `expected_count`
   is always `((window_end_ms - window_start_ms) // interval_ms) + 1` —
   the requested window's own span divided by the timeframe — **never**
   `len(bars_returned)` (the NB-5 analogue). Every missing grid slot in the
   requested window surfaces as part of a `GapRange`; nothing is
   interpolated or silently treated as covered (the NB-4 analogue). The
   three-way `status` (`COMPLETE` / `GAPS_PRESENT_FLAGGED` /
   `GAPS_PRESENT_REFUSED`) is decided by a threshold-free rule: `REFUSED`
   exactly when the requested window extends past the archive's own
   first/last archived bar for that symbol+timeframe (that portion is
   indistinguishable from "not yet fetched," so treating it as a confirmed
   gap would overstate what is known); `FLAGGED` for confirmed interior
   gaps bracketed by real archived bars on both sides. Fails closed
   (raises) on: archive unreachable (`ArchiveUnreachableError`), symbol
   never archived — zero bars ever (`SymbolNotArchivedError`), a window
   with zero archive overlap (`WindowOutsideArchiveError`), and malformed
   provenance — empty/whitespace `source`/`endpoint`/`provider_version`/
   `checksum`, or a naive `fetched_at` (`MalformedProvenanceError`).
   Malformed symbol/timeframe/window inputs raise `MalformedWindowError`.
   The module never imports `research.hypothesis_registry`.
6. **Step 3 — tool entry point.**
   `tools/inspect_research_market_data_coverage.py`: read-only CLI mirroring
   `tools/fetch_historical_market_data.py`'s argparse/JSON style. Exit code
   0 for `COMPLETE`/`GAPS_PRESENT_FLAGGED`, 1 for `GAPS_PRESENT_REFUSED` or
   any raised error, so a caller can script on the exit code alone. Refuses
   with a clear `ArchiveNotFound` error rather than silently creating an
   archive at a missing default path (added as an audit-fix — see below).
7. **Step 4 — tests.** `tests/test_research_market_data_bridge.py`, **27
   tests, all passing.** Covers: full-contiguous window → `COMPLETE` with
   `expected_count == actual_count`; an interior gap never silently
   reported `COMPLETE`; the NB-5 proof (a constructed case where
   `len(bars_returned)` would give 7 but the correct `expected_count` is
   10, asserted to differ); a second denominator-independence test using
   two genuinely different archive fill levels (sparse: 3 of 10 slots vs.
   full: all 10) for the identical requested window, asserting
   `expected_count` matches while `actual_count` differs; a gap fully
   contained in a sub-window of a larger archive; an archive-level gap that
   starts before and ends inside a requested sub-window, proving it is
   clipped to the request rather than leaking outside it; window-edge-
   exceeding-archive → `REFUSED` vs. interior-gap → `FLAGGED`, tested in
   both directions (window starting before the archive, window ending
   after it); archive-unreachable via both a genuinely unopened real
   `MarketDataSQLiteStorage` and a fake object raising
   `sqlite3.OperationalError`; symbol-never-archived; window-entirely-
   outside-archive in both directions; malformed provenance (empty source,
   empty/whitespace endpoint); unsupported timeframe; empty symbol;
   `window_end` before `window_start`; naive datetimes on both bounds;
   misaligned (non-grid) window bounds; a multi-batch provenance summary
   with correct per-batch bar counts and per-batch metadata; a static AST
   check that the module never imports `research.hypothesis_registry`
   (mirroring `tests/test_research_evidence_bridge.py`'s boundary guard
   from the other side of the same edge) while confirming it DOES import
   `data_layer.market_data_archive_sqlite` (explicitly authorized, unlike
   the evidence-bridge precedent); and a `classify_module` check pinning L3.
8. **Real-archive verification (Step 2/4 evidence).** Against the real,
   read-only archive at `C:\AtlasState\market_archive\market_data.sqlite3`:
   a BTCUSDT 1h window around 2020-12-21 reproduced the real known gap
   (`14:00 → 17:00`, 4 bars) exactly via the CLI tool, matching the Step 2
   coverage dump byte-for-byte on the gap boundaries.
9. **Step 5 — architecture-closure verification.**
   `python tools/build_architecture_inventory.py check`, run both before
   and after implementation, reports identically: `OK: runtime closure
   matches (106 modules)`, `OK: architecture map assigns every live module
   a layer (106 modules)`, and the same 2 pre-existing Group B2 forbidden
   edges (`atlas_finance/market_data/contracts.py`), zero new violations.
   Confirmed via `grep` across `core/application.py`, `main.py`,
   `web_app.py`, `atlas_service.py`, `atlas_supervisor.py` (zero matches for
   either new filename) and via a direct call to
   `tools.build_architecture_inventory.compute_runtime_closure()` that
   neither new file is present in the computed closure.
10. **Step 6 — independent audit.** Spawned a fresh `general-purpose`
    subagent with no access to this session's design rationale, given only
    the three new files plus `data_layer/market_data_archive_sqlite.py` for
    context, instructed to hunt specifically for (a) accidental
    runtime-closure import, (b) silent gap-interpolation, (c) a denominator
    computed from `len(bars)` instead of window span, (d) fabricated data on
    a fail-closed path — plus ordinary correctness bugs (off-by-one in the
    gap-walk, the `edge_exceeded` decision logic, timezone handling,
    provenance dedup, and whether any test is tautological).
    **Result: all four mandated failure classes CONFIRMED ABSENT.** 3
    MEDIUM findings, 2 LOW, 1 INFORMATIONAL. Full independent report
    preserved in this session's transcript (agent id `acc92392c3ddfda45`).
11. **Step 6 — fix.** All 3 MEDIUM findings fixed:
    - `_ARCHIVE_FAILURE_TYPES` caught the entire `sqlite3.Error` hierarchy,
      including `ProgrammingError`/`InterfaceError`/`NotSupportedError` —
      query-usage bugs, not "archive unreachable" conditions. Fixed by
      explicitly re-raising those three subclasses before the broader
      catch in `_call_archive`.
    - `tools/inspect_research_market_data_coverage.py` silently created an
      empty archive file and schema (via `MarketDataSQLiteStorage.open()`'s
      unconditional `CREATE TABLE IF NOT EXISTS`) when pointed at a missing
      default path, contradicting its own "read-only" docstring claim.
      Fixed by checking `database.exists()` before `storage.open()` and
      refusing with a clear `ArchiveNotFound` error otherwise. Verified: no
      file is created when the database path does not exist (confirmed
      with a fresh non-existent path); a genuinely present archive still
      works.
    - `test_expected_count_formula_is_independent_of_archive_contents` was
      tautological — it called `load_window` twice against the *same*
      single archive state, so it could not have failed even for a broken
      implementation. Rewritten to construct two genuinely different
      archive fill levels (3-of-10 slots vs. all 10 slots) in two separate
      `tmp_path` stores for the identical requested window, asserting
      `expected_count` is identical while `actual_count` differs.
    - 2 LOW findings (N+1 `provenance_for_bar` queries per bar rather than
      a batched lookup; an unbounded per-slot gap-walk loop for very wide,
      fine-grained windows) and 1 INFORMATIONAL note (the CLI's import of
      `core.application` executes that module's top-level code, though it
      creates no reverse dependency) were recorded as deferred, not fixed —
      both LOW findings would require either touching the existing L2
      archive module or adding complexity beyond P1's minimal scope, which
      is out of scope for this package.
12. **Step 6 — re-test.** All 27 tests still pass after the fixes. The
    `ArchiveNotFound` CLI guard was re-verified (no file created at a
    missing path; a real archive still resolves correctly). Architecture
    closure re-confirmed unchanged (106 modules, same 2 edges).
13. **Step 6 — regression precondition check.** Before running the full
    suite, checked for live Atlas processes sharing state directories per
    the gate's own precondition. Found `atlas_supervisor.py` (×2, PIDs
    17664/23044) and `atlas_service.py` (PID 24340) genuinely running live
    on this machine. Disclosed this to the owner before proceeding, since
    the task itself calls out this precondition explicitly; owner confirmed
    to proceed, on the basis that the suite is structurally isolated
    (`tmp_path` only — established by the Package C checkpoint's own
    evidence and re-confirmed by every test added in this session).
14. **Step 6 — full regression.**
    `python -m pytest tests --basetemp=C:/atlas_pytest_tmp_full -q` →
    **3737 passed, 1 failed, 118.97s.** The 1 failure is
    `tests/architecture/test_forbidden_layer_imports.py`, the pre-existing
    Group B2 finding (`atlas_finance/market_data/contracts.py`, OPEN since
    v4.29, unrelated to this module). **Independently confirmed as
    pre-existing**, not a regression: `git stash -u` on exactly the 3 new
    files, re-ran that single test in isolation — identical failure,
    identical two violations, byte-for-byte — then `git stash pop` restored
    the 3 files.
15. **Step 6 — commit.** `core/research_market_data_bridge.py`,
    `tests/test_research_market_data_bridge.py`, and
    `tools/inspect_research_market_data_coverage.py` committed together as
    `e3f0c8e`, citing the v4.69 grant and the audit/fix history in full in
    the commit message.

## Files changed

| File | Commit | Change |
| --- | --- | --- |
| `governance/current/ATLAS_MILESTONE_REGISTRY_v4.69.json` | `4ea5732` | added |
| `core/research_market_data_bridge.py` | `e3f0c8e` | added |
| `tests/test_research_market_data_bridge.py` | `e3f0c8e` | added |
| `tools/inspect_research_market_data_coverage.py` | `e3f0c8e` | added |

Verified via `git status --short` at checkpoint time: **clean** — nothing
else was touched. No live-decision-path file, no runtime-closure file, no
historical governance registry, and no ADR was modified.

## Architecture decisions

- **Module path `core/research_market_data_bridge.py`**, chosen by following
  `research_evidence_bridge.py`'s naming convention — named after the L2
  resource it bridges (the market data archive) rather than the roadmap
  label "compute engine," which describes the capability, not the
  architectural role.
- **L3 classification confirmed via the pre-existing generic `core/*`
  `layer_rules` pattern**, with zero `packaging/atlas_architecture_map.json`
  edits — unlike ADR-0009's C1 pattern addition for `research/*`, which was
  necessary only because `research/` carried no layer assignment at all
  before that record.
- **The module is explicitly authorized to, and does, import
  `data_layer.market_data_archive_sqlite` directly (L3 → L2)** — a
  deliberate divergence from `research_evidence_bridge.py`'s `Any`-typed,
  never-imported store pattern, justified because P1 genuinely needs the
  real `ArchivedBar`/`BatchProvenance` types rather than a duck-typed
  stand-in, and because this direction of the relationship carries none of
  ADR-0009's "keep `research/` unaware" rationale (P1 does not touch
  `research/` at all).
- **The COMPLETE/FLAGGED/REFUSED gap-status policy is threshold-free.**
  `REFUSED` applies exactly when the requested window's own bounds exceed
  the archive's actual first/last archived bar for that symbol+timeframe
  (structurally unconfirmed absence); `FLAGGED` applies to gaps fully
  bracketed by real archived data on both sides (structurally confirmed
  absence). No percentage or count-based cutoff was invented.
- **`GAPS_PRESENT_REFUSED` is a returned status, not a raised exception.**
  The caller still receives every bar that is genuinely archived; only the
  confidence signal is withheld. A hard raise (`WindowOutsideArchiveError`)
  is reserved for the stricter case of *zero* overlap between the requested
  window and the archived range, where there is nothing meaningful to
  return at all.
- **`sqlite3.ProgrammingError`/`InterfaceError`/`NotSupportedError` are
  deliberately excluded from "archive unreachable" handling** (an
  audit-driven fix) so that a genuine defect in this module's own query
  usage surfaces as itself rather than being mislabeled as an infrastructure
  failure.

## Tests

- `tests/test_research_market_data_bridge.py` — **27 passed** (verified
  directly, both before and after the audit fixes, with
  `--basetemp=C:/atlas_pytest_tmp`).
- **Full regression suite: `python -m pytest tests --basetemp=C:/atlas_pytest_tmp_full -q` → 3737 passed, 1 failed, in 118.97s.**
  The 1 failure (`tests/architecture/test_forbidden_layer_imports.py`,
  Group B2) is independently confirmed pre-existing via isolation (see
  Completed #14). No test was modified, weakened, or skipped to reach this
  result.
- All test runs used an ASCII `--basetemp` under a scratch directory
  (`C:/atlas_pytest_tmp`, `C:/atlas_pytest_tmp_full`,
  `C:/atlas_pytest_tmp_verify`). No test touched a configured durable root
  or real runtime state; every fixture uses `tmp_path`.

## Current state

Branch `research/edge-validation` at `e3f0c8e`. `git status --short` is
empty — working tree clean. W1 is preserved: `research/` and the new module
both remain outside the 106-module runtime closure. P2 (purged splits), P3
(`CheckResult` production) and P4 of the compute-engine proposal remain
unauthorized and unimplemented. `research/hypothesis_registry.py` is
byte-identical to before this session.

## Known issues

- **2 LOW findings from the independent audit, deliberately deferred, not
  fixed:** N+1 `provenance_for_bar` queries (one round-trip per bar rather
  than a batched lookup) in `_provenance_summary`; an unbounded per-slot
  gap-walk loop in `_compute_gap_ranges` for very wide, fine-grained
  windows. Both are performance/scalability concerns, not correctness
  defects, and fixing either would mean touching the existing L2 archive
  module or adding complexity beyond P1's minimal scope.
- **1 INFORMATIONAL finding:** the CLI tool's import of
  `core.application.resolve_market_archive_directory` executes that
  module's full top-level code at import time. Confirmed this creates no
  reverse dependency (the runtime closure does not import the new files),
  but the audit did not read `core/application.py` in full and could not
  rule out other import-time side effects — recorded as
  `UNKNOWN — requires verification` if it ever becomes relevant.
- **The pre-existing Group B2 architecture finding** (2 forbidden edges,
  `tests/architecture/test_forbidden_layer_imports.py`, OPEN since v4.29)
  remains open exactly as it was before this session; unrelated to this
  package and tracked separately in governance.

## Risks

- None to any live, execution, or capital path: the new module is
  unreachable from the runtime closure, strictly read-only, and makes no
  network calls.
- The compute-engine proposal's P1 slice now exists as real, tested code
  for the first time. P2 and P3 are separate, larger, still-unauthorized
  packages — P3 in particular would need to import
  `research/hypothesis_registry.py`, which is explicitly forbidden here and
  remains a decision only a future, separate owner authorization can make.
- `production_authority=NONE`, `live_authority=DENIED`, paper-only; no
  change to that state from this session.

## Remaining work

- P2 (apply `research/splitting.py`'s purged splits to real timestamps), P3
  (produce `research.hypothesis_registry.CheckResult` objects for the five
  named checks) and P4 remain entirely unauthorized. Each requires its own
  separate future owner decision, exactly as this session's `AskUserQuestion`
  exchange was required for P1.
- W2 (wiring `research/` or this new module into the runtime closure)
  remains deferred and unauthorized.
- The 2 LOW performance findings above are legitimate future-package
  candidates if a P2/P3/P4 authorization ever makes wide-window usage a
  real workload, but are explicitly not authorized or scoped here.

## Next exact action

Report to the owner and stop. Do not begin P2, P3, or P4 without their own
separate, explicit owner decision. Do not import
`research/hypothesis_registry.py` from `core/research_market_data_bridge.py`
under any circumstance without that decision. Do not wire this module or
`research/` into the runtime closure (W2, still unauthorized).
