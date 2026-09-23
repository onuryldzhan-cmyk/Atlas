# ADR-0007: Durable State Relocated Off the OneDrive-Synced Volume

## Status

Accepted. STATE-MOVE-1, executed 2026-09-18 (UTC). Supersedes nothing;
records the operational relocation performed with the mechanism introduced by
commit `d323365` ("feat(state): make the durable and archive roots
operator-relocatable, fail closed"), which shipped the mechanism without an
ADR of its own.

## Context

The installation directory of this deployment sits inside a OneDrive-synced
tree. `DEFAULT_STATE_DIRECTORY` anchors the durable state root to that
installation directory, so Atlas's execution transaction journal, idempotency
store, capital reservations, risk accounting state and audit event log were
all being written into a directory a cloud sync client also writes to.

That is not a theoretical hazard for these particular files. The sync client
takes its own locks, may upload a partially written file, and may reorder or
delay writes. The execution transaction journal and the idempotency store are
the two authorities Atlas cross-checks at startup; a torn or stale write to
either produces `SOURCE_DISAGREEMENT` or `RECOVERY_REQUIRED` and halts the
runtime — and in the worst case would let an already-executed request execute
a second time. Kapı 1, the first sustained unattended paper run, would have
run for hours with no operator watching that surface, which is why the
relocation was made a precondition for it rather than a cleanup afterwards.

`d323365` supplied the mechanism (`ATLAS_STATE_DIRECTORY` and
`ATLAS_MARKET_ARCHIVE_DIRECTORY`, resolved through one fail-closed validator
that accepts only an absolute path to an existing directory and raises
otherwise). This record covers the operational move itself.

## Decisions

- **The live durable state root is now `C:\AtlasState\memory_data`**, and the
  historical market-data archive root is `C:\AtlasState\market_archive`. Both
  are outside the OneDrive tree and outside the repository.

- **The overrides are set per-user with `setx`**, not per-shell. The
  supervisor hands its child a full copy of `os.environ`, so a variable
  exported once survives every supervised restart without changing how Atlas
  is launched. Persistence was verified by reading the values back in a fresh
  terminal, not only in the shell that set them.

- **The old locations were renamed, never deleted.** Each acquired a
  `.relocated_20260918` suffix in place:

  | before | after |
  | --- | --- |
  | `memory_data/` | `memory_data.relocated_20260918/` |
  | `memory_data_backup_20260915/` | `memory_data_backup_20260915.relocated_20260918/` |
  | `paper_trades.json.legacy_backup_20260915` | `paper_trades.json.legacy_backup_20260915.relocated_20260918` |
  | `data/market_archive/` | `data/market_archive.relocated_20260918/` |

  They remain on disk, byte-for-byte unmodified, as the rollback of last
  resort. Renaming rather than deleting is the whole point: a relocation that
  destroys its own source has no way back if the new root turns out to be
  wrong.

- **The installation defaults were deliberately left pointing at the original,
  now-absent names.** `DEFAULT_STATE_DIRECTORY` still resolves to
  `<repo>/memory_data` and `DEFAULT_MARKET_ARCHIVE_DIRECTORY` to
  `<repo>/data/market_archive`. This is correct, not an oversight: the default
  is the documented behaviour of a deployment that sets no override, and
  rewriting it to a machine-specific absolute path would bake one operator's
  filesystem into the composition root. The `.gitignore` rules `/memory_data/`
  and `/paper_trades.json` still guard those original names against a
  re-created directory entering version control.

## Consequences

- **A missing override is now a materially different run.** If
  `ATLAS_STATE_DIRECTORY` is unset, Atlas falls back to `<repo>/memory_data`,
  which no longer exists — the validator never creates a state root, so the
  run opens fresh empty state rather than the live one. Operators must confirm
  the variable is in force before starting. ADR-0005's runbook gained a
  section 0 saying so, and every `--state-directory` example there now names
  the live root.

- **The renamed directories fell out from under their ignore rules.**
  `/memory_data/` and `data/market_archive/*.sqlite3` are anchored on the
  original names, so the suffixed copies — including ~101 MB of sqlite —
  became untracked and visible to a bulk `git add -A`. Explicit
  `.relocated_20260918` ignore entries were added alongside the existing
  runtime-state rules to close that.

- **OneDrive sync was paused by the operator for the duration of the move**
  and is resumed only after this record lands, so the sync client never
  observed a half-copied or half-renamed state tree.

## Evidence

- Phase C/D: hash-for-hash copy of both roots into `C:\AtlasState`, verified
  per file.
- Phase E: two independent supervised restarts against the new root, both
  reporting `execution_halted=false`, `execution_recovery_required=false`,
  `journal_unresolved=False`; override persistence confirmed from a fresh
  terminal.
- Phase F (this record): Atlas proven stopped before the renames
  (`/api/health` refused connection, zero `python.exe` processes, zero
  listeners on port 8000); each of the four renames verified individually by
  destination existence, source absence, and an exact file-count and
  byte-count match against the pre-rename census.

## Addendum (additive, superseded-not-deleted): `memory_data/` has reappeared, empty

The Consequences section above states that `<repo>/memory_data`, the
`DEFAULT_STATE_DIRECTORY` fallback, "no longer exists" following the
2026-09-18 rename. That sentence is not rewritten or deleted here, per this
project's governance rule that drift is reconciled only by adding a new
record, never by editing history in place - but it is now stale as a literal
filesystem claim and needs this correction alongside it.

An empty `memory_data/` directory exists at the repository root again,
confirmed by a fresh check at the time this addendum was written:
directory present, zero entries inside it (`find memory_data -mindepth 1`
returns nothing), and still covered by the `.gitignore` `/memory_data/`
rule this ADR's Decisions section put in place, so it is untracked and
never entered version control. Its filesystem birth/modify timestamps are
both `2026-09-18 13:57:2x`, i.e. the same day as STATE-MOVE-1 itself - most
likely something in that day's activity (not this ADR's rename mechanism,
which only renames and never creates a state root) recreated an empty
directory at the old default path after the rename. The exact process that
created it is UNKNOWN - requires verification; it is not determinable from
the filesystem alone.

This does not change the substantive finding above. Atlas resolves its live
durable state root through the `ATLAS_STATE_DIRECTORY` override (this ADR's
Decisions section), not by checking whether `<repo>/memory_data` exists or
is empty; an operator who has the override in force is unaffected by this
directory's presence. The hazard the Consequences section actually warns
about - a run with the override unset silently opening fresh empty state -
is unchanged: this reappeared directory is that same "fresh empty state,"
not a new or different risk. Operators still must confirm
`ATLAS_STATE_DIRECTORY` is in force before starting, exactly as stated
above.

Authorized by governance registry v4.58,
`adr0007_directory_reappearance_correction_and_d6_d7_definition_proposal_authorization.grant_a_adr0007_stale_claim_correction`
(`GRANT-ADR0007-STALE-CLAIM-CORRECTION`).
