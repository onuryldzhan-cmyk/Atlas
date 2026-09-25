# ATLAS CHECKPOINT

## Objective

Owner brief (2026-09-25), read-only investigation: determine, with evidence,
whether STATE-MOVE (relocating `memory_data/` off the OneDrive-synced tree)
is done, partially done, or not done — because live supervised runs were
observed constructing durable state under `C:\AtlasState\...`, contradicting
a standing note that the move "was decided but never started" and the
reconciliation audit's assumption that it is still a pending Gate-1
precondition. No file moves, no Atlas restart, no env-var changes.

Classification: ROUTINE (read-only verification, no code/config change).
The full CRITICAL gate does not apply.

## Completed — first, checked whether this task was already done

`grep -rli "STATE-MOVE\|ATLAS_STATE_DIRECTORY" checkpoints/` found one hit,
`checkpoints/20260917T110452Z_observability-freshness-hook-and-dashboard-commit.md`,
which explicitly says STATE-MOVE-1 was **not yet started** as of 2026-09-17
("The next action is the separately-scoped STATE-MOVE-1 work ... whose
Phase A is code-only"). No checkpoint documents the move as *done*, so this
was not a re-run of prior work — the relocation evidently happened after
that checkpoint and was never separately checkpointed, only recorded in an
ADR and governance registries. Fresh investigation proceeded.

## Verdict

**(a) STATE-MOVE is fully done and can be closed as an open item.**
`C:\AtlasState\memory_data` is the sole, authoritative durable state root in
force today, has been since **2026-09-18 (UTC)**, and no code path reads or
falls back to the old OneDrive-located copies. The standing note that it
"was decided but never started" is stale; it predates the move. The
reconciliation audit's own precondition framing (I-5, "relocate
`memory_data/` outside OneDrive before any sustained or unattended paper
run") is **already satisfied** and should be marked closed in future work
referencing it.

## Evidence

### 1. Documentary record (git history, not guessed)

- `docs/adr/0007-durable-state-relocation-off-onedrive.md` — Status line:
  "Accepted. STATE-MOVE-1, executed 2026-09-18 (UTC)." States the live
  durable state root is `C:\AtlasState\memory_data`, the market-archive root
  is `C:\AtlasState\market_archive`, both outside OneDrive and outside the
  repository; overrides set per-user with `setx` (persists across every
  supervised restart, verified by the original author in a fresh terminal);
  old locations renamed (not deleted) with a `.relocated_20260918` suffix,
  kept as rollback of last resort.
- Commit `d323365` (2026-09-18 01:02:23 +0300), `feat(state): make the
  durable and archive roots operator-relocatable, fail closed` — shipped the
  `ATLAS_STATE_DIRECTORY`/`ATLAS_MARKET_ARCHIVE_DIRECTORY` mechanism the ADR
  operationalizes. Same calendar day as the move itself.
- Commit `1659986` (2026-09-21), `docs(adr): track the existing ADR-0007
  record, recovered not newly authored` — the ADR file existed on disk,
  complete, before this commit; it had been left untracked by oversight
  (commit `1fd0f12` committed three files that cite it while omitting the
  record itself). Tracked byte-unchanged (sha256 confirmed in the commit
  message).
- Commit `1174914` (2026-09-23), `docs(adr): additively correct ADR-0007's
  stale memory_data non-existence claim` — added an addendum, per
  governance registry v4.58's `GRANT-ADR0007-STALE-CLAIM-CORRECTION`,
  documenting that an *empty* `memory_data/` reappeared at the repo root the
  same day as the move (birth/modify timestamps `2026-09-18 13:57:2x`) and
  explaining it does not change the substantive finding: Atlas resolves its
  state root via the env-var override, never by checking whether that path
  exists.
- Governance registry `governance/current/ATLAS_MILESTONE_REGISTRY_v4.74.json`
  (the current one, verified as latest by directory listing) still contains
  3 references to "STATE-MOVE-1" and 7 to `ATLAS_STATE_DIRECTORY`, carried
  forward unmodified through every intervening additive registry version
  from v4.46 onward — including repeated in-session confirmations such as
  "`env | grep ATLAS_` ... all set, pointing at `C:\AtlasState\...`" and a
  live read-only query of `C:\AtlasState\market_archive\market_data.sqlite3`.

### 2. Direct filesystem verification this session (read-only)

- `env | grep ATLAS_` in this fresh Bash session (a process this session did
  not itself configure) shows:
  ```
  ATLAS_STATE_DIRECTORY=C:\AtlasState\memory_data
  ATLAS_MARKET_ARCHIVE_DIRECTORY=C:\AtlasState\market_archive
  ATLAS_EVIDENCE_DIRECTORY=C:\AtlasState\evidence_store
  ```
  `ATLAS_LOG_DIRECTORY` is unset in this shell. Because these three
  variables are present in a shell this session never exported them into,
  they can only have reached it via a persistent, user-level mechanism —
  consistent with ADR-0007's `setx` claim. A direct `reg query
  HKCU\Environment` was attempted (both directly and via a `.cmd` script
  through `cmd.exe`) to date the registry value itself, but produced no
  readable output in this sandboxed shell (tool/environment limitation, not
  a negative result) — **the exact `setx` timestamp is UNKNOWN**, but its
  *effect* (persistence into an unrelated fresh process) is directly
  confirmed.
- `C:\AtlasState\` contents (`ls -la`): `memory_data/`, `memory_data_backup_20260915/`,
  `market_archive/`, `evidence_store/`, `logs/`, `paper_trades.json.legacy_backup_20260915` —
  matching every path ADR-0007 and the registries describe.
- `C:\AtlasState\memory_data\` holds `execution_transaction_journal.jsonl`,
  `execution_idempotency.jsonl`, `capital_reservations.json`,
  `execution_financial_state.json`, `risk_accounting_state.json`, an
  `audit/` directory, plus the pre-migration `.migrated` legacy files
  (`execution_idempotency.json.migrated`, `execution_transaction_journal.json.migrated`,
  both dated 2026-08-13 — the v1→v2 migration this ADR is unrelated to).
  The live files' newest content timestamp is **2026-09-15 23:25** — i.e.
  no new BUY/SELL has journaled since before the move, though the directory
  itself has been present and stable since then (its own `.` entry mtime is
  also 2026-09-15 23:25; the *parent* `C:\AtlasState\` mtime of
  2026-09-24 17:57 reflects sibling directories, not writes to
  `memory_data/` itself).
- `C:\AtlasState\market_archive\market_data.sqlite3` (106,078,208 bytes,
  content dated 2026-08-28) plus live `-wal`/`-shm` files dated
  2026-09-23 22:17; `C:\AtlasState\evidence_store\evidence_store.sqlite3`
  dated 2026-09-24 23:53; `C:\AtlasState\logs\market_loop_telemetry.jsonl`
  dated 2026-09-24 23:53 — all three consistent with the durable roots
  being actively used by a running instance as recently as 2026-09-24, the
  day before this check (today is 2026-09-25 per system clock). No Atlas
  process is running *right now*: `curl -m 3 http://127.0.0.1:8000/api/health`
  refused connection (curl exit 7, no listener), and no Python process was
  visible to `tasklist`. This is expected between supervised runs and does
  not bear on where state lives when a run *is* active.
- The repository root (`ls -la .`) confirms the four renamed, frozen copies
  from ADR-0007's table exist exactly as described, all last legitimately
  written **before** the 2026-09-18 rename and byte-static since:
  `memory_data.relocated_20260918/` (mtime 2026-09-15 23:25 — matches the
  live copy's own last-write time, confirming they are the same content at
  the moment of the hash-for-hash copy),
  `memory_data_backup_20260915.relocated_20260918/` (mtime 2026-09-15 19:26),
  `paper_trades.json.legacy_backup_20260915.relocated_20260918` (mtime
  2026-08-13 — a pre-existing legacy backup, untouched by the move itself),
  and `data/market_archive.relocated_20260918/` (present, per `ls data/`).
  A separate, **empty** `memory_data/` (mtime 2026-09-18 13:57:31) also
  exists at the repo root — this is the "reappeared empty directory"
  ADR-0007's addendum documents and explains; it is git-ignored, untracked,
  and holds zero entries. This exact directory and timestamp were also
  independently confirmed earlier in this same session (execution
  reconciliation audit's `checkpoints/20260924T195526Z_...`), which reported
  it as evidence that no real runtime state was touched by that unrelated
  work.
- `.gitignore` (lines 187-200) carries both the original names
  (`/memory_data/`, `/paper_trades.json`) and all four `.relocated_20260918`
  suffix entries, matching ADR-0007's stated Consequence exactly.

### 3. Sole-authority confirmation — code read, not inferred

`core/application.py` (`_resolve_configured_directory`, `resolve_state_directory`,
`resolve_market_archive_directory`, `resolve_evidence_directory`,
`resolve_log_directory`, lines ~142-335) was read in full. The mechanism is
a single-path resolver with **no dual-read, no merge, and no OneDrive
fallback of any kind**:

- If the env var (`ATLAS_STATE_DIRECTORY` etc.) is set, its value is
  validated (absolute, exists, is a directory) and used **exclusively**; an
  invalid override raises `ConfiguredDirectoryError` rather than silently
  falling back to the installation default. This is explicit in the code's
  own comment: "an override that is present but unusable raises instead of
  falling back... That is why an override that is present but unusable
  raises instead of falling back."
- If the env var is unset, the installation-anchored default
  (`<repo>/memory_data`, i.e. the OneDrive-tree path) is used instead — but
  this is a genuine *either/or*, never a "try new, then old" chain. Since
  the override is set (confirmed above), this branch is not in force today.
- A targeted grep (`grep -rn "memory_data\b" core data_layer tools main.py
  web_app.py`, excluding the `DEFAULT_STATE_DIRECTORY` definition itself and
  tests) found **no other hardcoded reference** to the string `memory_data`
  anywhere in application code — no second reader, no legacy compatibility
  path, nothing that could read the old OneDrive copy while the override is
  in force.

## Files changed

None. This session added only this checkpoint file. No code, config,
environment variable, or state file was touched, moved, or modified, per
scope.

## Architecture decisions

None made — this is a verification task, not a design task.

## Tests

Not applicable; no code changed.

## Current state

- Branch `research/edge-validation`. HEAD unchanged by this session
  (`7a41279`, per `git log -1` — the previous session's governance-record
  commit). `git status --short` empty before and after this investigation.
- `C:\AtlasState\memory_data` (and `market_archive`, `evidence_store`,
  `logs`) confirmed as the live, sole-authoritative durable roots as of this
  check (2026-09-25).
- No Atlas process observed running at check time (expected; not evidence
  against the verdict).

## Known issues

- **UNKNOWN — requires verification**: the exact `setx` execution timestamp
  from the Windows user-environment registry (`HKCU\Environment`) could not
  be read in this sandboxed shell (both direct `reg query` and a `.cmd`
  script via `cmd.exe` produced no output — a tool limitation of this
  environment, not a finding about the registry itself). This does not
  affect the verdict: ADR-0007 states the mechanism and date directly, and
  this session's own fresh-shell environment inheritance independently
  confirms the override is in force and persistent.
- **UNKNOWN, pre-existing and explicitly documented as such (ADR-0007's own
  addendum)**: the exact process that recreated the empty `<repo>/memory_data`
  directory on 2026-09-18 (same day as the move) is not determinable from
  the filesystem alone. It is confirmed inert (empty, git-ignored, never
  read by any resolver) and does not bear on this verdict.
- The live `memory_data/` journal/idempotency/reservation files' newest
  content is dated 2026-09-15 23:25 — i.e. no new trade has journaled since
  before the move (this is the hash-for-hash copy's original content,
  unchanged since). Whether Atlas has executed any trade *since* the move on
  2026-09-18 is UNKNOWN from this check alone and was out of scope; it does
  not affect where state lives, only whether it has grown.

## Risks

None identified by this investigation. The relocation mechanism is
fail-closed by design (an invalid override halts rather than silently
opening a different, empty root), which is the property the reconciliation
audit's I-5 precondition was actually protecting against — and it is
already in force.

## Remaining work

- **Recommended, small, DOCS-only follow-up** (sized: TRIVIAL/ROUTINE,
  ~5-10 minutes): future references to "STATE-MOVE relocation is a pending
  Gate-1 precondition" — specifically I-5 in
  `checkpoints/20260924T195526Z_execution-financial-state-reconciliation-audit.md`
  and its downstream citation in
  `checkpoints/20260924T203700Z_execution-authority-crash-recovery.md`'s
  known-issues/remaining-work sections and governance registry
  v4.74's `known_issues_and_deferred_improvements` — should be corrected
  (additively, per the project's own drift-reconciliation convention: a new
  note, not an edit of the existing text) to state that I-5 is **already
  satisfied** as of 2026-09-18, evidenced by this checkpoint, rather than
  still being an open precondition. This is a documentation correction only;
  no code or state changes.
- No other remaining work identified. STATE-MOVE-1 itself needs no further
  action.

## Next exact action

If the owner wants the I-5 corrections above made, that is a TRIVIAL
docs-only task (update the two checkpoints' "known issues" language
additively, and/or file a new governance registry successor record noting
I-5 closed) citing this checkpoint as evidence. Otherwise, no action is
required — STATE-MOVE-1 is closed.
