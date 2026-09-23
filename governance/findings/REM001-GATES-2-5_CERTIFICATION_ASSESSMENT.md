# REM001-GATES-2-5 — Definitions of done and evidenced status for REM-001 Gates 2, 3, 4 and 5

## Status

**ASSESSMENT RECORDED. No gate is CERTIFIED. No REM-001 state changes.**

Authorized by `governance/current/ATLAS_MILESTONE_REGISTRY_v4.70.json`
(`rem001_gates_2_to_5_and_compute_engine_p2_authorization`, commit `3ed05c3`),
grants `GRANT-GATE2-CERTIFICATION`, `GRANT-GATE3-CERTIFICATION`,
`GRANT-GATE4-CERTIFICATION` and `GRANT-GATE5-STATUS`.

| Gate | Name | Outcome |
| --- | --- | --- |
| 2 | `REPRODUCIBLE_BUILD` | **PARTIAL** — 3 of 6 criteria met |
| 3 | `DETERMINISTIC_CORE_TESTS` | **PARTIAL** — 6 of 7 criteria met (two with stated limits), 1 UNKNOWN |
| 4 | `OFFLINE_AND_REPLAY_RUNTIME` | **PARTIAL** — replay mechanics met (5 of 8); no offline runtime mode exists |
| 5 | `CORE_REFACTORING` | **ONGOING BY DESIGN — CURRENTLY IN AN OWNER-ACCEPTED STATE.** Not COMPLETE; not a completion gate |

| Field | Value |
| --- | --- |
| Operating mode | AUDIT MODE (investigate, then certify only if evidenced) |
| Recorded on | 2026-09-23 |
| Branch | `research/edge-validation` |
| Evidence HEAD | `3ed05c3` (code-identical to `e3f0c8e`, the P1 commit; `3ed05c3` adds only the v4.70 registry JSON). The 3812-test runs in §2.4 were taken at `3ed05c3` with the P2 package staged — exactly the code committed next as P2. |
| Production effect | NONE |
| Live effect | NONE |

## 0. Read this first — what these outcomes do and do not mean

1. **The definitions of done below are newly authored, not recovered.**
   REM-001's thirteen specification Parts are absent from the repository
   (`governance/ATLAS_REM001_SPECIFICATION_ARTIFACT_INTEGRITY_v1.0.md` §3.1,
   finding GOV-DRIFT-005). The only surviving trace of Gates 2–5 is their
   names in `milestones.REM-001.gates`. Each definition below was written in
   this session under the v4.70 grants, *before* the evidence was checked
   against it, from the gate's name and this project's own conventions. If
   the original Part text is ever recovered and defines a gate differently,
   that is a CONFLICT to record, and the original governs.
2. **No outcome here advances REM-001.** `current_gate` remains
   `GATE_1_CANONICAL_COMPONENT_MAPPING` (`OPEN_NOT_CERTIFIED`, closure
   authority `OWNER_ACCEPTANCE_REQUIRED`). The gates list is ordered; whether a
   later gate may be formally passed while Gate 1 is open is an owner
   decision this record does not take. The question is moot for now because
   no gate below reaches CERTIFIED.
3. **PARTIAL is a real result, not a placeholder.** Each PARTIAL names
   exactly which criteria are met, with citations, and which are not.

---

## 1. Gate 2 — REPRODUCIBLE_BUILD

### 1.1 Definition of done (written before the evidence check)

Identical source plus identical lock files yield an identical, verifiable
environment on a clean machine, reproducibly. Concretely, all six:

| # | Criterion |
| --- | --- |
| G2-1 | Every third-party Python dependency installed by the canonical paths is pinned to an exact version with a SHA-256 hash, and installation enforces the hashes. |
| G2-2 | Every CI action is pinned to an immutable commit SHA. |
| G2-3 | The toolchain is pinned: exact interpreter version, exact pip version, and a fixed runner/OS image — so identical inputs imply an identical environment. |
| G2-4 | A clean environment built from the locks reproduces the canonical test verdict. |
| G2-5 | That reproduction is evidenced on at least one environment independent of the developer machine (hosted CI or a second machine). |
| G2-6 | The resulting environment's identity is verifiable: it is compared against the lock (or reduced to a recorded digest), so "identical build" is checked rather than asserted. |

### 1.2 Evidence against each criterion

| # | Result | Evidence |
| --- | --- | --- |
| G2-1 | **MET** | `requirements/locks/windows-py314-dev.txt`: 47 pinned entries, 47 with `--hash=sha256:` (counted this session). `requirements/locks/windows-py314-runtime.txt`: 41 / 41. Both CI (`.github/workflows/atlas_ci_cd.yml` lines 67–71) and `scripts/validate_atlas.ps1` install with `--require-hashes -r requirements/locks/windows-py314-dev.txt`, then run `pip check`. SUPPLY-CHAIN-001 `CLOSED` (hash enforcement commit `0c6f4a9`). The numpy gap found by TEST-QUALITY-002 is closed: the numpy entry was added at `b60e9b3`, its hash independently re-checked against PyPI's published digest (registry `governance_findings.TEST-QUALITY-002.closure`). |
| G2-2 | **MET** | `actions/checkout@11d5960a…` (line 33), `actions/setup-python@a26af69b…` (line 40), `actions/upload-artifact@043fb46d…` (line 156), all full commit SHAs. SUPPLY-CHAIN-001 `github_actions_sha_pinned: true`, action-pinning commit `4208116`. |
| G2-3 | **NOT MET** | CI `python-version: "3.14"` (line 42) floats to the newest 3.14.x; the CI step "Upgrade pip" (line 64) installs whatever pip is newest, unpinned and unhashed; `runs-on: windows-latest` (line 19) floats. `scripts/validate_atlas.ps1` builds its venv from whichever `python` is first on PATH (3.14.6 on this host today) and does not pin pip. The lock header itself scopes the lock to "CPython 3.14", not to a patch release. |
| G2-4 | **MET (same machine only)** | TEST-QUALITY-002 closure (registry v4.55, commit `b60e9b3`): `scripts/validate_atlas.ps1` run to completion — fresh `.venv_atlas_validation`, `--require-hashes` PASS, `pip check` PASS, all test files collected, **3225 passed / 1 failed**, identical to the ambient-environment count on the same code, the single failure being the accepted Group B2 test. |
| G2-5 | **NOT MET** | CI-EVIDENCE-001 status `CONFIRMED`, `hosted_ci_execution: NOT_EVIDENCED`, `closure_requires_hosted_run_evidence: true`. `git remote -v` returns nothing at `3ed05c3` (checked this session): the workflow has never run anywhere. No second-machine reproduction is recorded. |
| G2-6 | **NOT MET** | Nothing compares the built environment to the lock or records a digest. CI's `pip freeze` (line 172) prints for diagnostics only; `validate_atlas.ps1` prints no environment identity. Atlas builds no distributable artifact (no wheel/sdist step exists), so "build artifact" reduces entirely to "environment", which is itself unverified. |

### 1.3 Outcome — **PARTIAL**

The *dependency-immutability* half of reproducibility is genuinely
established (G2-1, G2-2) and has been exercised on a clean venv (G2-4). The
*toolchain*, *independent-machine* and *verifiable-identity* half (G2-3, G2-5,
G2-6) is not. "Identical source + identical locks → identical build on a clean
machine" is therefore not proven: two runs a month apart could differ in
interpreter patch release and pip version, and no run has ever happened off
this machine.

What would close it (recorded, not authorized): pin the interpreter patch
version and pip in both paths; obtain one hosted CI run (needs a remote — the
CI-EVIDENCE-001 dependency); add a step asserting `pip freeze` equals the lock
set.

---

## 2. Gate 3 — DETERMINISTIC_CORE_TESTS

### 2.1 Definition of done (written before the evidence check)

The full suite is deterministic: the same code yields the same pass/fail
outcome across repeated runs, with no flaky, order-dependent or
environment-dependent test in the core path. Concretely, all seven:

| # | Criterion |
| --- | --- |
| G3-1 | Repeated full runs on the same code produce the same outcome: same pass count, same failing-test identities. |
| G3-2 | The outcome is independent of execution order — at minimum a reversed-order full run matches the forward run. |
| G3-3 | Tests are isolated from real runtime state: no test can open the operator's durable state roots. |
| G3-4 | Test outcomes do not depend on external network access. |
| G3-5 | Test outcomes do not depend on wall-clock time or unseeded randomness in ways that can flip pass/fail. |
| G3-6 | No flaky or order-dependent test is recorded anywhere in project history (or every such record is resolved). |
| G3-7 | The canonical outcome is well defined: every failure in it is a recorded, accepted, deterministic failure. |

### 2.2 Evidence against each criterion

| # | Result | Evidence |
| --- | --- | --- |
| G3-1 | **MET** | Forward run at `e3f0c8e`: **3737 passed / 1 failed** (checkpoint `20260923T185339Z`, Completed #14). Reverse-order run this session at `3ed05c3` (code-identical): **3737 passed / 1 failed**, same failing test, same two edges (see G3-2). Earlier independent pair: TEST-QUALITY-002's isolated-venv run and the ambient run at the same code both gave 3225 / 1 with the same identity. |
| G3-2 | **MET (one permutation)** | New this session. `python -m pytest tests -p atlas_reverse_order --basetemp=C:/atlas_pytest_tmp_rev -q -p no:cacheprovider`, with a 12-line plugin kept outside the repository (scratchpad) that reverses the collected item list; its terminal line confirmed it was active (`first=tests/test_web_app_signals_and_trades.py::test_new_endpoints_refuse_non_loopback_clients`). Result **1 failed, 3737 passed in 192.71s**, the failure being `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports` reporting exactly B2.1 and B2.2. Random permutations were not tested: no randomization plugin is in the hash lock and adding one is a dependency change outside this grant. |
| G3-3 | **MET** | TEST-ISO-001 remediation implemented at `4534da8` (registry `GRANT-TEST-ISO-001-REMEDIATION`, `implemented: true`): `conftest.py` `_isolate_state_root_environment` forces `ATLAS_STATE_DIRECTORY`, `ATLAS_MARKET_ARCHIVE_DIRECTORY` and `ATLAS_EVIDENCE_DIRECTORY` to a fresh session temp root before collection, deliberately not exception-swallowing; `tests/test_pytest_state_root_isolation.py` proves it with a nested pytest subprocess. Test fixtures use `tmp_path`; runs use an ASCII `--basetemp`. |
| G3-4 | **MET (Python-socket level)** | New this session, see §2.4: a full run with every non-loopback connection and DNS lookup refused made **zero** attempts and gave the identical outcome. |
| G3-5 | **UNKNOWN** | Not audited. No suite-wide audit of `datetime.now()`/`time.time()`/unseeded `random` use exists. The only evidence is indirect: runs on different days (TEST-QUALITY-002, P1, this session) produced outcomes consistent with the tests added in between. That is weak evidence and is not counted as MET. |
| G3-6 | **MET (as far as records show)** | A case-insensitive search of `checkpoints/`, `governance/findings/`, `governance/*.md` and registry v4.69 for flaky / order-dependent / nondeterministic / intermittent returns no record of such a test (the only hits are unrelated: an xdist-worker note in `conftest.py`, and "non-deterministic sequence" describing journal data in STAGE1-PAPER-001). |
| G3-7 | **MET, with a recorded assurance gap** | The single canonical failure is the Group B2 architecture test, permanently accepted by owner decision (registry v4.63, `GRANT-B2-PERMANENT-CLOSURE`; `ARCH-EDGE-001` section added at `de2de76`), and it is deterministic (identical in every run above). **Gap:** both CI and `validate_atlas.ps1` gate on pytest's exit code, so each reports FAIL on every run by construction and cannot distinguish "the accepted failure" from "a new failure" without a human reading the failure identity. Recorded, not remediated. |

### 2.3 Documentation lag found in passing — CONFLICT (informational)

- **Expected:** `governance/findings/TEST-ISO-001_PYTEST_SHARED_STATE_ROOT_ENVIRONMENT_HAZARD.md`
  reflects the finding's current state.
- **Actual:** its status table still reads
  `OPEN_PROPOSED_REMEDIATION_NOT_IMPLEMENTED`.
- **Evidence:** registry `ladder_correction_testiso_remediation_and_d1_status_grants_authorization.grant_b_test_iso_001_remediation`
  records `implemented: true`, `implementing_commit: 4534da8`; `conftest.py`
  contains the isolation hook.
- **Impact:** a reader of the findings file alone would believe tests are
  not isolated from the operator's state roots. No runtime impact.
- **Decision required:** whether to append an additive status section to
  that document. Not done here — editing another finding's text is outside
  every v4.70 grant.

### 2.4 Network independence (G3-4), further repeats, and outcome

**Network-blocked run (new evidence).** After the P2 package was staged, the
full suite was run with a second out-of-repository plugin (scratchpad) that
replaces `socket.socket.connect`, `socket.socket.connect_ex` and
`socket.getaddrinfo` for the whole session, refusing any non-loopback target
and recording the test that tried:

`python -m pytest tests -p atlas_no_network --basetemp=C:/atlas_pytest_tmp_nonet -q -p no:cacheprovider`
→ `ATLAS_NO_NETWORK_ACTIVE attempts=0 tests_attempting=0`, **1 failed, 3812
passed in 133.85s**, the failure being the Group B2 test.

No test in the suite attempted a non-loopback connection or DNS lookup, and
the outcome is identical to the unblocked canonical run on the same code
(`python -m pytest tests --basetemp=C:/atlas_pytest_tmp_full -q` → **1
failed, 3812 passed in 135.48s**, same failure). Limit: the guard sits at the
Python `socket` module; a C extension opening sockets without it would not
be seen. No such extension is known to be exercised by the suite, but that is
not proven.

**Repeat count now on record.** Two pairs of identical outcomes on identical
code: 3737 / 1 (forward at `e3f0c8e`, reversed at `3ed05c3`) and 3812 / 1
(canonical and network-blocked with the P2 package staged). The 75-test
difference is exactly the P2 test file.

**Outcome — PARTIAL.** Six criteria are met with evidence (G3-2 for one
permutation only, G3-7 with the recorded exit-code assurance gap). G3-5 —
independence from wall-clock time and unseeded randomness — has never been
audited and stays UNKNOWN. The suite behaves deterministically in every run
on record, but a claim that no test *can* flip on time or chance is not yet
evidenced, so CERTIFIED is not claimed.

What would close it (recorded, not authorized): an audit of time/random use
in `tests/` and the code under test, and one or more seeded random-order
runs (requires adding a hash-locked plugin — a dependency decision).

---

## 3. Gate 4 — OFFLINE_AND_REPLAY_RUNTIME

### 3.1 Definitions (as this project means them) and definition of done

- **Replay** — re-applying confirmed, authoritative execution evidence to
  rebuild relational/financial state, idempotently, without contacting an
  exchange. This is the meaning `data_layer/projection_replay.py` ("Idempotent
  relational projection from confirmed authoritative evidence. This module
  deliberately has no exchange dependency.") and the recovery path give it.
- **Offline runtime mode** — the Atlas runtime (composition root, market
  loop, decision path, execution manager in paper mode) runnable end-to-end
  with no network access, driven by locally archived or recorded market data,
  producing a reproducible result.

These are different claims. Strong tests of the first are not evidence of
the second.

| # | Criterion |
| --- | --- |
| G4-1 | Replay is idempotent. |
| G4-2 | Replay never contacts an exchange. |
| G4-3 | Replay is atomic: a failed write or commit leaves no partial projection. |
| G4-4 | Replay rejects stale, duplicate and regressive state (compare-and-set). |
| G4-5 | Replay and recovery are wired into the real runtime, with fail-closed readiness. |
| G4-6 | A runnable offline runtime mode exists (entry point or configuration). |
| G4-7 | A recorded market-data window can be replayed through the runtime decision path deterministically. |
| G4-8 | G4-6 and G4-7 are tested end-to-end. |

### 3.2 Evidence against each criterion

| # | Result | Evidence |
| --- | --- | --- |
| G4-1 | **MET** | `tests/test_phase2_recovery_projection_safety.py::test_replay_once_and_twice_is_idempotent_and_preserves_units` |
| G4-2 | **MET** | `…::test_replay_never_calls_exchange`; `data_layer/projection_replay.py` imports no exchange module (its imports are `data_layer.contracts` and `data_layer.models` only). |
| G4-3 | **MET** | `…::test_replay_second_write_failure_rolls_back`, `…::test_replay_commit_failure_remains_unprojected` |
| G4-4 | **MET** | `…::test_order_cas_valid_stale_duplicate_and_terminal_regression`, `…::test_position_stale_cas_rejected`, `…::test_full_close_and_short_or_partial_close_rejected`; readiness gates in `…::test_confirmed_missing_requires_replay_and_present_is_ready`, `…::test_reconciliation_blocks_readiness_and_never_allows_blind_retry`, `…::test_corruption_or_invalid_schema_fails_closed`. All 11 tests in the file are inside the 3737 passing tests above. |
| G4-5 | **MET** | `data_layer/projection_replay.py` and `data_layer/recovery.py` are in the committed runtime closure (`packaging/atlas_runtime_closure.json`). `core/execution_manager.py` imports `data_layer.runtime_safety` (line 106) and blocks with `RECOVERY_REQUIRED` / `BLOCK_RECOVERY_REQUIRED` (e.g. lines 987, 2722). Integration coverage: `tests/test_phase2_runtime_safety_integration.py`, `tests/test_block5j_execution_authority_recovery.py`, `tests/test_deprecated_execution_state_recovery.py`. |
| G4-6 | **NOT MET** | No offline mode exists. `main.py` constructs the runtime with `execution_mode="PAPER"` (line 407), which runs against live market data. A search for offline/replay mode flags across first-party `.py` files finds only `core/brain.py`'s "offline" (meaning *service stopped, fail closed*, not *no network*) and a retired module under `archive_unused_2026-07-22/`. |
| G4-7 | **NOT MET** | The archived-bar path (`core/research_market_data_bridge.py`, P1, and `core/research_timestamp_split_binding.py`, P2) is research-only and deliberately outside the runtime closure (W2 unauthorized). Nothing feeds archived bars through `MarketLoop` or the decision path. |
| G4-8 | **NOT MET** | Follows from G4-6 and G4-7. |

### 3.3 Outcome — **PARTIAL**

Honest reading: **strong, runtime-wired, well-tested replay of execution
evidence** (G4-1…G4-5), and **no offline runtime mode and no market-data
replay at all** (G4-6…G4-8). The gate's name promises both; only the first
half exists. Building the second half would touch the runtime closure and
the live decision path, which every v4.70 grant excludes.

---

## 4. Gate 5 — CORE_REFACTORING

### 4.1 Why this gate is different

Gates 2–4 are promotion gates: once their conditions hold, they hold.
Core refactoring is continuous code health: every new module (P1 and P2 this
week) re-enters the architecture gate, and the gate is re-run on every
change. "Complete" is not a state it can honestly reach. What can be stated
is whether it is **currently in an accepted-good state**, defined as:

| # | Criterion for "currently accepted" |
| --- | --- |
| G5-a | The architecture gate runs, and every live module has a layer. |
| G5-b | Every forbidden edge the gate reports is a recorded, owner-accepted edge. |
| G5-c | No new forbidden edge has been introduced since the acceptance decision. |

### 4.2 Evidence

| # | Result | Evidence |
| --- | --- | --- |
| G5-a | **MET** | `python tools/build_architecture_inventory.py check` this session: `OK: runtime closure matches (106 modules)`, `OK: architecture map assigns every live module a layer (106 modules)`. |
| G5-b | **MET** | The same run reports exactly two forbidden edges, `atlas_finance/market_data/contracts.py -> atlas_finance/__init__.py` and `-> atlas_finance/market_data/__init__.py` (B2.1, B2.2). Permanently accepted as red by owner decision: registry v4.63 `GRANT-B2-PERMANENT-CLOSURE`; `governance/findings/ARCH-EDGE-001_ANCESTOR_PACKAGE_FORBIDDEN_EDGES.md`, section "Group B2 permanent closure — 2026-09-23, registry v4.63" (commit `de2de76`) — "expected to remain red on exactly these 2 edges indefinitely, by owner decision"; explicitly not a `permitted_exception`. The other 15 of ARCH-EDGE-001's 17 edges (Groups A, B1, C) were resolved at `f2c25e2` (core/data_layer package inits reclassified to L1); `370567f` (PEP 562 lazy `atlas_finance` inits) removed B2's runtime coupling but not the two static edges. |
| G5-c | **MET** | Same two edges, byte-identical, in every run recorded since v4.29 (TEST-QUALITY-002 closure, P1 checkpoint, this session's reverse-order run and architecture check). |

### 4.3 Status — **ONGOING BY DESIGN, CURRENTLY IN AN OWNER-ACCEPTED STATE**

Not COMPLETE, and not labelled COMPLETE. `tests/architecture/test_forbidden_layer_imports.py`
is red indefinitely by owner decision; the gate itself must keep running on
every change. The accepted state is conditional on G5-c continuing to hold:
the first new forbidden edge would take Gate 5 out of this state.

---

## 5. What this record does not do

- Does not certify any gate, advance `current_gate`, or change REM-001's
  status, `production_authority` (`NONE`) or `live_trading_authority`
  (`DENIED`).
- Does not modify any test, workflow, lock file, script or runtime file.
- Does not edit TEST-ISO-001's document (see §2.3), CI-EVIDENCE-001,
  SUPPLY-CHAIN-001, ARCH-EDGE-001, or any historical registry.
- Does not touch Gate 1 or Gates 6–10.
