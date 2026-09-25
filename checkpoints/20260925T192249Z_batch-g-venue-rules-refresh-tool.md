# ATLAS CHECKPOINT

## Objective

Owner brief 2026-09-25, Part G (following G1 from
`checkpoints/20260925T185300Z_batch-g-venue-rules-refresh-proposal.md`):
build a manual, operator-triggered tool that fetches a current
`exchangeInfo` snapshot, validates it through the existing Block 6C adapter,
and writes `config/instrument_rules.json` for the operator to review and
commit themselves. No auto-commit, no runtime change.

**Status: COMPLETE.**

## Completed

- New tool `tools/refresh_venue_instrument_rules.py`:
  - `fetch_exchange_info_snapshot()` performs one unauthenticated HTTP GET
    of `/api/v3/exchangeInfo`, fails closed on a network error, a non-200
    status, invalid JSON, or a non-object payload. Nothing is written for
    any of these.
  - `refresh_venue_instrument_rules()` wires that snapshot straight into
    `tools.venue_metadata_adapter.publish_venue_rules` (unmodified) with
    `destination=config/instrument_rules.json` by default, then prints a
    unified diff of the file's before/after content.
  - `main()` is a CLI (`--symbol`, `--venue`, `--destination`, `--base-url`,
    `--timeout-seconds`). It never calls `git`.
- `tools/venue_metadata_adapter.py` was **not** modified. Its "opens no
  socket, cannot write the checked-in config" docstring claims remain true
  of that module; the new tool is a separate, explicitly-named file that
  owner decision G1 authorized to be the one thing that writes
  `config/instrument_rules.json`.
- New test file `tests/test_refresh_venue_instrument_rules.py` (14 tests):
  transport-layer fetch success/failure (network error, HTTP 503, invalid
  JSON, non-object payload, empty symbol list), end-to-end successful
  refresh producing a loadable ruleset, default-symbols-from-destination
  behaviour, and three fail-closed cases proving the destination is
  byte-for-byte unchanged (and no `.tmp` artifact survives) after a
  malformed response, an incomplete `exchangeInfo` entry, or a requested
  symbol absent from the payload. Plus one CLI-level test asserting `main()`
  prints `REFUSED` and returns 1 on failure without creating the
  destination.

## Files changed

- `tools/refresh_venue_instrument_rules.py` (new)
- `tests/test_refresh_venue_instrument_rules.py` (new)

## Architecture decisions

- The refresh tool is the sole thing (besides the operator, by hand) that
  ever writes `config/instrument_rules.json`. It reuses
  `publish_venue_rules`'s existing atomic write / reload-through-canonical-
  loader / freshness-check sequence rather than reimplementing any of it, so
  the only new surface is the network fetch and the diff print.
- The HTTP fetch is implemented locally in the new tool file rather than by
  extending `atlas_finance/market_data/binance_public_provider.py`
  (`BinancePublicDataProvider` has no `exchangeInfo` method and PART G's
  scope was "new manual CLI tool only" - extending a shared provider class
  would have widened the change beyond that).
- A new transport/verification-status pair (`BINANCE_PUBLIC_HTTP`,
  `LIVE_HTTP_FETCH_UNVERIFIED_TRANSPORT`) distinguishes this snapshot's
  provenance from the file-transport adapter's
  (`OPERATOR_SUPPLIED_FILE`, `..._UNVERIFIED_TRANSPORT`). Both are honest
  about carrying no cryptographic verification of the venue's identity.

## Tests

`pytest tests/test_refresh_venue_instrument_rules.py tests/test_block6c_venue_metadata_adapter.py`
→ **34 passed**, 0 failed.

Full-suite regression (run once after both Part G and Part I were
complete): **3999 passed, 1 failed**. The one failure
(`test_forbidden_layer_imports`, an `atlas_finance/market_data/contracts.py`
architecture-layer violation) was verified pre-existing and unrelated to
this tool - see the Part I checkpoint
(`checkpoints/20260925T192249Z_batch-i-hypothesis-registry-hardening.md`)
for the isolation evidence (`git stash` + rerun against the base commit).

## Current state

`core/application.py`'s `_build_instrument_rules` is unchanged: still the
sole runtime reader of `config/instrument_rules.json`, still loaded once at
startup from the hard-coded `DEFAULT_INSTRUMENT_RULES_PATH`. Running the new
tool against the real network and committing its output remains a distinct,
manual, reviewed operator action - this session did not run it against the
real venue or touch the checked-in config file.

## Known issues

- None found in this package.
- Carried over from the G1 proposal, unchanged by this work: the checked-in
  `config/instrument_rules.json` is currently STALE per
  `core/venue_rule_freshness.py`'s 30-day policy (retrieved_at
  2026-08-19). Harmless under PAPER; running this tool against the real
  network and committing the result closes it, at the owner's discretion.

## Risks

None introduced. The tool cannot be invoked accidentally into a write: every
failure path (network, validation, freshness) refuses before touching the
destination, matching the fail-closed guarantee `publish_venue_rules`
already carried and this package's own tests exercise directly.

## Remaining work

- G2 (a runtime path override for the published artifact) and G3 (scheduled
  auto-publish) remain explicitly deferred per the prior checkpoint's
  recommendation - revisit G2 before the Shadow stage, do not build G3
  before Controlled Autonomous.
- A governance authorization record for this new network-calling operator
  tool was flagged as recommended in the prior checkpoint (open question 4).
  Not created in this session; deferred to the owner alongside Part I's
  registry-drift entry (see the Part I checkpoint's own remaining work).

## Next exact action

Owner decides whether/when to run
`python tools/refresh_venue_instrument_rules.py` against the live network
and commit the resulting `config/instrument_rules.json` diff.
