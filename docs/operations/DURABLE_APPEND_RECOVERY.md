# Recovering from an indeterminate durable write (Phase-2 A2)

Applies to the audit log, the transaction journal and the idempotency log under the state directory
(`C:\AtlasState\memory_data` on the owner's machine).

## When this happens
A disk write failed in a way Atlas could not classify (the record may or may not be on disk). Atlas then:
- refuses every further write to that file in the running process;
- leaves a marker file next to it, `<file>.recovery_required`;
- refuses to load that file on every later start, until the marker is resolved. For the audit log this means
  Atlas exits on start with the integrity exit code, and the supervisor does not restart it.

A plain, classified failure (`NOT_WRITTEN`) does **not** leave a marker; it only degrades audit persistence, which
blocks new buys until the next restart (Phase-2 A3).

## Procedure (Atlas stopped)
1. Stop Atlas (Ctrl+C) and copy the whole state directory to a backup before touching anything.
2. Open the marker file. It names the file, the last verified size (`verified_size`) and the error.
3. Compare the file's real size with `verified_size`:
   - **equal** - nothing extra reached the disk: go to step 4.
   - **larger** - the bytes after `verified_size` are the unconfirmed record. Do not edit by hand; keep the backup and
     ask for an investigation (the record may describe a trade that really happened).
4. Delete only the `.recovery_required` marker file.
5. Start Atlas. Every load re-validates the file from scratch (torn tail, sequence order, hash chain), so removing the
   marker can never make a corrupt file loadable: if the file is not clean, Atlas still refuses to start.

`<file>.lock` files are normal and can stay; the operating system releases the lock when the process ends.
Windows behaviour of the lock and of the rollback (`ftruncate`) is not yet verified on the owner's machine.

Do not "reset" a flagged store to get past the marker: since the 2026-10-03 re-review `reset(delete_file=True)` refuses while a marker exists, so the evidence is kept.
