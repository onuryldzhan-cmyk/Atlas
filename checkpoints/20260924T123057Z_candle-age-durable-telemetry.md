# ATLAS CHECKPOINT — Candle-Age Metric + Durable MarketLoop Telemetry (S-3/M-2 data pipe)

- **UTC:** 2026-09-24T12:30:57Z
- **Branch:** `research/edge-validation`
- **HEAD at start:** `066239c`
- **HEAD at end:** `3d14651` (this checkpoint is committed on top)
- **Mode:** BUILD
- **Classification:** CRITICAL. The change touches `core/market_loop.py` and
  `core/application.py`, both in the runtime closure. The full gate was
  applied: IMPLEMENT → TEST → SELF-REVIEW → REGRESSION → INDEPENDENT AUDIT →
  FIX → RE-TEST → (scoped re-audit → FIX → RE-TEST) → FINAL GATE.

## Objective

Make S-3 and M-2 evidence collectable.

- **S-3** is the candle-age / market-data staleness threshold.
- **M-2** is the supervisor stall-detection threshold.

Neither could be evidenced before this package, for two reasons:

- Candle age was never computed. The existing measure is fetch liveness.
- Cycle duration existed only in memory. The file handler in `AtlasLogger`
  was dead code: `initialize()` was never called.

This package is additive observability only. It decides neither threshold.

## Completed

1. **Step 0 — governance.** Registry v4.71 was committed alone as `fb71760`,
   adding the block `candle_age_and_durable_operational_logging_authorization`.
   - **Grants:** `GRANT-CANDLE-AGE-COMPUTATION`,
     `GRANT-DURABLE-OPERATIONAL-LOGGING` and `GRANT-VERIFICATION`.
   - **Conflict check:** result `NO_CONFLICT_PROCEED`. The v4.70 and v4.45
     exclusions are scoped to those records' own grants. The v4.41 rule that
     no S-3 threshold may be written into any file is honoured: no threshold
     was written anywhere.
2. **Step 1.** Read the record back from git. All three grants and their
   byte-for-byte preservation clauses were unambiguous.
3. **Step 2 — investigation.**
   - `core/candle_processor.py:328-336` still reads `close_time` from kline
     index 6. When index 6 is absent it **falls back to `open_time`** (the same
     fallback is at `:417-422`). So `close_time <= open_time` means the value
     is not provider-supplied.
   - `AtlasLogger.initialize()` has not been called since the baseline commit
     `fa25d15`, and no record gives a reason. The reason is UNKNOWN; the
     evidence is consistent with an omission.
   - It could not simply be called as it stood:
     - its path, `logs/`, was relative to the working directory, which puts it
       inside OneDrive;
     - it added a second root console handler, which would duplicate every
       console line;
     - it wrote a root-wide file, which would be a general logging overhaul.
4. **Steps 3–4 — implementation.** Committed as `ba38ed4`.
5. **Steps 5–6 — tests and gates.** Details under *Tests* below. The first
   independent audit returned 2 MEDIUM and 4 LOW findings, all fixed. The
   scoped re-audit returned 1 new MEDIUM (N1), also fixed.
6. **Step 7.** STAGE1-PAPER-001 gained section **8.9**, additive only
   (`3d14651`). This checkpoint follows.

## Files changed (`ba38ed4`)

- **`core/market_loop.py`** — insertions only; 0 lines removed.
  - Module additions: `TELEMETRY_LOGGER_NAME = "AtlasAI.MarketLoop.Telemetry"`
    (with `propagate=False` and level INFO) and `TELEMETRY_SCHEMA_VERSION = 1`.
  - New `CANDLE_AGE_*` status constants.
  - New `last_candle_age` dict, plus the per-thread `_telemetry_cycle`
    sequence.
  - New methods: `_candle_age()` (pure), `_record_candle_age()` (never
    raises) and `_emit_cycle_telemetry()` (never raises).
  - The worker gets a sequence tag and an emit call placed after duration
    measurement.
  - `process_symbol` gets one measurement call, placed before any skip.
- **`core/logger.py`** — rewritten, including a docstring recording why the
  old `initialize()` could not be used.
  - `_TelemetryFileWriter` is a plain object, deliberately **not** a
    `logging.Handler`.
  - `_BoundedQueueListener.stop_within()` joins with a timeout.
  - `AtlasLogger.initialize()` adds an absolute-path check and an attach
    lock, and refuses a duplicate handler.
  - `close()` never raises and is bounded by 5 s.
- **`core/application.py`**
  - New `LOG_DIRECTORY_ENV = "ATLAS_LOG_DIRECTORY"` and
    `resolve_log_directory()`.
  - `_resolve_configured_directory` now accepts `default=None`. Its behaviour
    and message text for the three existing roots are unchanged, and a test
    pins that.
  - New `log_directory=` constructor argument.
  - `logger_manager.initialize()` is called last in `__init__`.
  - `stop()` closes telemetry without counting a shutdown error.
- **`conftest.py`** — TEST-ISO-001 extended to **unset**
  `ATLAS_LOG_DIRECTORY` for the pytest session.
- **`tests/test_market_loop_candle_age_telemetry.py`** — new, 59 tests.

## Architecture decisions

- **No default log location.** An unset `ATLAS_LOG_DIRECTORY` means no file
  is written.
  - The installation sits inside OneDrive (ADR-0007).
  - A disabled telemetry log costs nothing in correctness, unlike an empty
    state root.
  - So an unset variable must never mean "write next to the code".
- **Same validator as the state roots.** A set value must be absolute, must
  already exist, must be a directory, and is never created; anything else
  raises `ConfiguredDirectoryError`. An explicit relative constructor argument
  is also refused, in `AtlasLogger`.
- **Dedicated, non-propagating telemetry logger.** Root handlers, root level
  and console output are untouched.
- **A plain-file sink on a QueueListener thread.** Cycles never do disk I/O.
  Python's exit-time `logging.shutdown()` never waits on a stuck write (audit
  N1). A failed write produces one generic WARNING and never record text
  (audit F1).
- **No new first-party import edge.** `market_loop` does not import
  `core.logger`; the composition root connects them.
- **Kept off every existing surface.** Candle age is not added to `status()`
  or `health()`, so it cannot be confused with the fetch-liveness
  `market_data_stale`.

## Tests

- **Baseline** at `066239c`: 3812 passed / 1 failed (from the previous
  checkpoint). The 25 affected pre-existing files gave 1238 passed, captured
  before any change.
- **New file:** 59 passed, stable across repeated runs.
- **Affected-file comparison:** 1238 outcomes, identical test-by-test after
  every production edit (three comparisons). That includes all staleness and
  health tests.
- **Full canonical suite**, all runs preceded by the live-process check (0
  python processes, 0 listeners on :8000, `/api/health` refused):
  - REGRESSION: 3863 passed / 1 failed.
  - RE-TEST 1: 3870 passed / 1 failed.
  - **Final RE-TEST: 3871 passed / 1 failed.**
  - The one failure is the pre-existing Group B2 test
    `tests/architecture/test_forbidden_layer_imports.py`.
- **Architecture:** 106 modules, closure matches, exactly the 2 permanent B2
  edges, and graph BFS reproduces the closure.
- **Smoke test** (`test_smoke_real_application_writes_parseable_telemetry`):
  a real `AtlasApplication` built with a tmp log directory ran 3 real worker
  cycles, with only the network feed replaced. It wrote 15 records, every one
  parsed back with real values. Sample line:
  `{"candle_age_seconds": 42.0, "candle_age_status": "MEASURED", "candle_close_time": "2026-09-24T12:13:37.238000+00:00", "cycle": 1, "cycle_duration_seconds": 0.0284, "event": "market_loop_cycle", "processing_cutoff": "2026-09-24T12:14:19.238143+00:00", "schema_version": 1, "symbol": "BTCUSDT", "timestamp": "2026-09-24T12:14:19.266570+00:00"}`
- **N1 discrimination:** the same probe run against the old design (a stdlib
  `FileHandler` sink with a 6 s stuck write) took 6.4 s to exit. The new
  design exits in under 1 s with a 20 s stuck write.

## HOW TO COLLECT S-3 / M-2 DATA ON A FUTURE RUN (runbook)

1. **Create the directory first.** It is never created automatically. Use a
   path outside OneDrive, next to the live state root (ADR-0007):
   `mkdir C:\AtlasState\logs`
2. **Export the variable per-user**, the same way the state roots are set:
   `setx ATLAS_LOG_DIRECTORY C:\AtlasState\logs`
   Open a **fresh** terminal and confirm it with
   `echo %ATLAS_LOG_DIRECTORY%`. The supervisor passes its whole environment
   to the child, so the value survives restarts.
3. **Start Atlas as usual** (supervisor / `main.py`). At startup the console
   shows one line from `AtlasAI.Logger`:
   - `Durable telemetry log: C:\AtlasState\logs\market_loop_telemetry.jsonl`
     means it is active;
   - `Durable telemetry log disabled: no log directory configured` means the
     variable was not seen: stop and fix it.

   A mistyped or missing directory makes startup fail with
   `ConfiguredDirectoryError`. That is intended.
4. **File:** `<ATLAS_LOG_DIRECTORY>\market_loop_telemetry.jsonl`. It is
   appended across restarts: UTF-8, LF line endings, one JSON object per line,
   with one line per configured symbol per worker cycle.
5. **Record schema** (`schema_version` 1, `event` = `"market_loop_cycle"`):

   | Field | Content |
   | --- | --- |
   | `timestamp` | ISO UTC time the cycle finished |
   | `cycle` | Cycle count; resets to 1 on each process restart |
   | `symbol` | The symbol this record is for |
   | `cycle_duration_seconds` | Float, 4 dp. The same value for every symbol in a cycle |
   | `candle_age_seconds` | Float, ms precision, or `null` |
   | `candle_age_status` | See below |
   | `candle_close_time` | ISO time, or `null` |
   | `processing_cutoff` | ISO time, or `null` |

   `candle_age_status` takes one of these values:
   - `MEASURED` — the only status that carries an age;
   - `UNAVAILABLE_NO_CLOSED_CANDLE`, `UNAVAILABLE_CLOSE_TIME_MISSING`,
     `UNAVAILABLE_CLOSE_TIME_MALFORMED`,
     `UNAVAILABLE_CLOSE_TIME_NOT_PROVIDER_SUPPLIED`,
     `UNAVAILABLE_CLOSE_TIME_AFTER_CUTOFF`, `UNAVAILABLE_CUTOFF_MALFORMED`,
     `UNAVAILABLE_COMPUTATION_ERROR`;
   - `NOT_MEASURED_THIS_CYCLE` — the fetch returned nothing, the symbol
     failed, or the loop stopped mid-cycle.
6. **Extraction rules** for the future task:
   - **S-3:** use `candle_age_seconds` over `MEASURED` records only. Report
     the counts of every other status separately; never drop them silently,
     since `NOT_MEASURED` and `UNAVAILABLE` rates are evidence too.
   - **M-2:** use `cycle_duration_seconds` de-duplicated to **one value per
     (process run, `cycle`)**, because it repeats once per symbol. Split
     process runs where `cycle` resets.
   - Note that `cycle_duration_seconds` covers the `run_cycle()` work only.
     The wall-clock period is roughly duration + `interval` (10 s). The gap
     between consecutive `timestamp` values is the observed period.
   - `GRANT-RUN-EVIDENCE-EXTRACTION`'s honesty rules still bind (registry
     v4.45): state sample size with every statistic, propose no M-2 value
     from sparse data, and write no S-3 value into any file before the owner
     decides (v4.41).
7. **Candle interval context:** a 1m interval means a healthy
   `candle_age_seconds` is expected to cycle roughly between 0 and 60 s plus
   the fetch lag. **INFERENCE, not verified against a live run.**

## Current state

- S-3 and M-2 remain **OPEN**. Only their data-collection blocker is
  resolved.
- Authority is unchanged: `production_authority=NONE`,
  `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.
- No Atlas process was started, stopped or contacted, beyond the read-only
  precondition checks. No real state root or real log root was written.

## Known issues / accepted residuals

- **Queue loss at hard exit:** records still queued when the process ends
  without `stop()` (a hard kill) are lost. That is at most about 1 cycle,
  because the listener thread is a daemon.
- **Audit N2 (INFORMATIONAL):** after a timed-out `close()`, a second
  `close()` returns True, and `write_failures` is not surfaced on any status
  surface. The only signal is the single WARNING line.
- **Audit F5:** the attach lock has no dedicated test. The race window cannot
  be reproduced deterministically.
- **One file per process:** records carry no instance id, and a second
  application configured with a log directory cannot be constructed in the
  same process until the first is stopped. Production runs one application
  per process.
- **Resolver wording:** its error messages reuse state-root phrasing ("move
  the existing state into it"). This is cosmetic.
- **No OneDrive check:** the override is not checked against OneDrive paths,
  which matches the three existing roots. Choosing an off-OneDrive directory
  is the operator's responsibility (runbook step 1).
- **New console line:** construction now logs one new INFO line (the enabled
  or disabled telemetry notice). No existing line is changed or duplicated.

## Risks

- A run started without the variable collects nothing, silently apart from
  the "disabled" startup line. Check the startup line (runbook step 3).

## Remaining work

- An owner-scheduled, observed paper run with `ATLAS_LOG_DIRECTORY` set.
- A separate, future extraction task under its own grant.
- The S-3 and M-2 threshold decisions, which are the owner's.

## Deferred improvements (not implemented)

- Surface `write_failures`, and candle age itself, on a status surface. Each
  needs its own grant, because v4.71 deliberately kept both off
  `status()`/`health()`.
- An instance or run id field in telemetry records.

## Next exact action

Owner decision: schedule an observed paper run following the runbook above
(steps 1–3), and confirm the "Durable telemetry log: …" startup line. After
the run, authorize a read-only extraction task that applies runbook step 6 to
the file.
