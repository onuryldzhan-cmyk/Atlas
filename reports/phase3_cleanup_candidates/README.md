# Atlas Phase 3B Cleanup Candidate Report

This report is read-only. No source file was moved or deleted.

## Classification counts

- `DUPLICATE_REMOVE_CANDIDATE`: 1
- `DUPLICATE_REVIEW`: 1
- `EMPTY_REMOVE_CANDIDATE`: 1
- `KEEP_CANONICAL`: 36
- `KEEP_PACKAGE_MARKER`: 14
- `KEEP_REVIEW`: 160
- `KEEP_TEST_REVIEW`: 61
- `KEEP_TOOL_REVIEW`: 7
- `PARSE_ERROR_REVIEW`: 13
- `QUARANTINE_SAFE`: 13

## Safety rule

A file is never deleted only because it is not reachable from `main.py`.

## Next action

Only high-confidence backup/archive and exact-duplicate candidates will be considered for reversible quarantine.