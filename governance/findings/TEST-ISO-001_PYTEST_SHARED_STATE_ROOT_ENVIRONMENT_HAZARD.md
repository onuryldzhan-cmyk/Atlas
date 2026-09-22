# TEST-ISO-001 — pytest inherits the live financial/evidence state-root overrides from the shell environment

## Status

**RECORDED. PROPOSE-ONLY. No remediation is implemented or authorized by this
record.**

Authorized by `governance/current/ATLAS_MILESTONE_REGISTRY_v4.46.json`
(the five-grant investigation/documentation record), grant
`GRANT-PYTEST-STATE-ROOT-FINDING`. That grant authorizes creating exactly this
record, with a recommended remediation direction, and explicitly withholds
authorization to implement any fix.

| Field | Value |
| --- | --- |
| Finding ID | TEST-ISO-001 |
| Title | pytest inherits `ATLAS_STATE_DIRECTORY` / `ATLAS_MARKET_ARCHIVE_DIRECTORY` / `ATLAS_EVIDENCE_DIRECTORY` from the shell, with no test-side isolation |
| Finding type | `TEST_ISOLATION_SHARED_STATE_ROOT` |
| Operating mode | AUDIT MODE |
| Severity | **HIGH** |
| Status | `OPEN_PROPOSED_REMEDIATION_NOT_IMPLEMENTED` |
| Recorded on | 2026-09-22 |
| Recorded at commit | `370567f3d46c446f31c021ebad4799dda105137a` (branch `research/edge-validation`) |
| Production effect | NONE |
| Live effect | NONE |

## 1. Severity

**HIGH.** Not BLOCKING: it does not by itself stop this session's documentation
work or any single feature from proceeding, and per this project's severity
gate HIGH carries no immediate stop — it "must be fixed and re-reviewed before
a milestone is closed" rather than before the next feature. It is HIGH rather
than MEDIUM because the failure mode it describes is financial/evidentiary
state corruption on a Rule-7 protected surface ("Protect critical state and
migration integrity"), it has reportedly already come within one killed
process of occurring in this environment, and the precondition that currently
prevents it (an operator manually checking for a live Atlas process before
every full-suite run) is a human-remembered discipline, not a structural
control — exactly the gap CLAUDE.md's Financial/migration safety section
requires be closed with detection-and-halt, not with operator memory.

## 2. Location

- `core/application.py:184-186` — the three override environment-variable
  names (`STATE_DIRECTORY_ENV = "ATLAS_STATE_DIRECTORY"`,
  `MARKET_ARCHIVE_DIRECTORY_ENV = "ATLAS_MARKET_ARCHIVE_DIRECTORY"`,
  `EVIDENCE_DIRECTORY_ENV = "ATLAS_EVIDENCE_DIRECTORY"`).
- `core/application.py:196-236` (`_resolve_configured_directory`) —
  `raw = os.environ.get(variable)`. This reads the ambient process
  environment unconditionally; there is nothing in this function, or
  anywhere else in `core/application.py`, that distinguishes a pytest
  process from a supervised Atlas process.
- `conftest.py` (repository root) — the only `conftest.py` in this
  repository. Read in full for this finding: it implements
  `pytest_configure` / `pytest_sessionfinish` hooks that redirect and later
  promote `--junitxml` output for the observability panel. It does not read,
  clear, override, or even reference `ATLAS_STATE_DIRECTORY`,
  `ATLAS_MARKET_ARCHIVE_DIRECTORY`, or `ATLAS_EVIDENCE_DIRECTORY`. No other
  `conftest.py` exists under `tests/` or elsewhere in the tracked tree.
- Any test that constructs `AtlasApplication`, or the durable stores it owns,
  without passing an explicit isolated `state_directory` — the pattern this
  repository's own prior-session guidance (governance memory
  `atlas-runtime-state-isolation`) already flags as a standing requirement
  for reproductions, but which is not structurally enforced for the test
  *suite* itself.

## 3. Evidence

All of the following was directly observed in this session, read-only, with
no runtime constructed and no write performed to any live store.

1. **The hazard is live in the current shell, right now.** `env | grep
   ATLAS_` in the shell this Claude Code session runs in returns:
   ```
   ATLAS_STATE_DIRECTORY=C:\AtlasState\memory_data
   ATLAS_MARKET_ARCHIVE_DIRECTORY=C:\AtlasState\market_archive
   ATLAS_EVIDENCE_DIRECTORY=C:\AtlasState\evidence_store
   ```
   These are the operator's real, relocated financial/evidence roots (the
   relocation itself was a standing owner decision to move execution state
   off OneDrive sync, recorded in prior-session governance memory
   `atlas-execution-state-outside-onedrive`). Any process launched from this
   shell — including a bare `pytest` invocation with no special flags —
   inherits all three overrides and, per `_resolve_configured_directory`,
   is forced to treat `C:\AtlasState\...` as authoritative: an unset
   override falls back to a repo-relative default, but a *set* override
   that resolves to an existing directory is used unconditionally, with no
   pytest-aware exception.
2. **No code path isolates a test run.** Confirmed by reading
   `core/application.py`'s override-resolution code in full and by
   confirming, via `find`, that the repository contains exactly one
   `conftest.py` (repository root), whose full content concerns only JUnit
   XML publishing and never touches these three variables.
3. **The manual precondition this currently relies on is documented, and is
   manual.** Commit `370567f`'s own message records: *"Full regression suite
   (precondition: no live Atlas process sharing
   ATLAS_STATE_DIRECTORY/ATLAS_MARKET_ARCHIVE_DIRECTORY/ATLAS_EVIDENCE_DIRECTORY,
   independently verified via netstat and Win32_Process command-line scan):
   3224 passed, 1 failed in 151.68s."* This is direct evidence that, as of
   the most recent full-suite run on this branch, avoiding this hazard
   already requires a human to remember to run a process-liveness check
   before every full-suite invocation in a shell where these variables are
   set. Nothing fails closed if that check is skipped.
4. **The near-incident this session's context reports (a full-suite run
   killed mid-execution after it was found writing into the live evidence
   store): its exact write timestamps are UNKNOWN and are recorded as such
   rather than inferred.** This session located the evidence store the
   current environment points at
   (`C:\AtlasState\evidence_store\evidence_store.sqlite3`, last modified
   2026-09-22 17:26 local time) and, read-only, queried its `claims` table.
   The most recent rows all carry `run_id = "atlas_20260922_142619"` and
   `asserted_at_utc` values ending `2026-09-22T14:26:2x.xxxxxxZ` (UTC;
   14:26 UTC = 17:26 local at UTC+3, consistent with the file's mtime and
   independently cross-checked against that mtime rather than assumed). The
   314 rows visible are agent-labeled directional claims
   (`agent:technical`, `agent:momentum`) on real trading symbols
   (`XRPUSDT`, `SOLUSDT`, `BNBUSDT`), which is the shape of legitimate
   `AtlasApplication` paper-run output, not of pytest-originated test
   fixture data. **This record does not attribute this run to the reported
   near-incident** — doing so would be an unverified inference forbidden by
   CLAUDE.md's No Hallucination Policy. What is recorded as fact is only:
   the hazard mechanism is real and currently live (point 1 above); the
   evidence store the current environment points at contains no artifact in
   this session's reach that is legibly distinguishable as test-run
   pollution; and the incident's own timestamps are **UNKNOWN — requires
   verification** from whoever observed and killed the run.

## 4. Impact

If a full pytest run (or any narrower run that happens to exercise a test
constructing `AtlasApplication` or a durable store directly without an
explicit isolated `state_directory`) is launched from a shell where
`ATLAS_STATE_DIRECTORY`, `ATLAS_MARKET_ARCHIVE_DIRECTORY`, or
`ATLAS_EVIDENCE_DIRECTORY` are set to the operator's real roots — which is
the current, default state of the shell this session inherited — that test
run silently opens the operator's real financial state
(`execution_transaction_journal.jsonl`, `execution_idempotency.jsonl`,
`capital_reservations.json`, `risk_accounting_state.json`,
`memory_data/audit/atlas_audit_events.jsonl`) and/or the real research
Evidence Store (`evidence_store.sqlite3`) instead of disposable test state.
Consequences, per this repository's own documented failure semantics:

- A test that writes an unresolved entry into the real
  `execution_transaction_journal` would halt the operator's next genuine
  run with `RECOVERY_REQUIRED` (this is the exact mechanism prior-session
  governance memory `atlas-runtime-state-isolation` was written to guard
  against for manual reproductions; it applies identically to an automated
  test run).
- A test that writes spurious or malformed rows into the real evidence
  store corrupts the research record the Evidence Store exists to keep
  trustworthy (ADR-0008), with no git history to recover it from — these
  stores are gitignored by design, so there is no tracked baseline to
  restore.
- Because the override is "unconditionally used once present, never created,
  fail-closed only on a *malformed* value" (`core/application.py`'s own
  documented contract), a test relying on the repo-relative default without
  passing an explicit override does not get an error indicating it is
  touching the wrong root — it gets the operator's real root, successfully,
  silently.

## 5. Reasoning

The override mechanism (`_resolve_configured_directory`) was deliberately
designed to be inherited transparently by every child process of the
operator's shell, including across a supervised restart — that is its stated
purpose for the *live* Atlas process. `pytest` is, from the operating
system's point of view, just another child process of the same shell, and
nothing distinguishes it. The design that makes the override durable and
convenient for the live process is the same design that makes it invisible
and non-optional for a test process that has no legitimate reason to want it.
The current only defense is an operator manually checking for a live process
before running the suite (evidence, point 3 above) — a check that says
nothing about whether the *shell itself* still carries the override, which it
does regardless of whether a live process happens to be running at that
moment. A test run launched with no live Atlas process running, in a shell
that still exports the real state roots, passes that precondition check and
is still exposed to the hazard.

## 6. Remediation — PROPOSED ONLY, not implemented

Per Grant `GRANT-PYTEST-STATE-ROOT-FINDING`, this record proposes a direction
and implements nothing. Two non-exclusive options, for a future owner
decision:

1. **Fail closed at collection time.** A `pytest_configure` (or
   `pytest_sessionstart`) hook — most naturally added to the existing
   repository-root `conftest.py`, alongside its other startup-time checks —
   that inspects `os.environ` for `ATLAS_STATE_DIRECTORY`,
   `ATLAS_MARKET_ARCHIVE_DIRECTORY`, and `ATLAS_EVIDENCE_DIRECTORY` at
   session start and aborts collection with a clear message if any is set,
   on the reasoning that an ordinary test run has no legitimate reason to
   want the operator's live roots. An explicit opt-out (a distinctly-named
   variable, e.g. `ATLAS_TEST_ALLOW_LIVE_STATE_ROOTS=1`) could be offered
   for the rare case where a test deliberately needs to exercise the
   override-resolution code itself against a real path.
2. **Isolate rather than refuse.** A session-scoped `autouse` fixture that
   monkeypatches `os.environ` to point all three variables at a fresh
   `tmp_path`-derived directory for the duration of the test session,
   regardless of what the ambient shell carries, so every test that
   constructs `AtlasApplication` or a durable store gets an isolated root
   without needing to remember to pass one explicitly.

Choosing between (or combining) these, and implementing either, is
explicitly **not authorized by this record** and is left to a future
governance grant.

## 7. What this record does not do

- It does not implement any remediation, in `conftest.py` or anywhere else.
- It does not modify `core/application.py` or any override-resolution logic.
- It does not interact with any Atlas process, live or otherwise.
- It does not assert the near-incident's write timestamps as fact; it
  records them as UNKNOWN and states exactly what evidence was and was not
  found, per §3.4.
- It does not construct any runtime, test, or reproduction capable of
  writing to `C:\AtlasState\...` or any other real state root; every
  observation in §3 was a read-only filesystem check or a read-only SQLite
  query opened explicitly in `mode=ro`.
