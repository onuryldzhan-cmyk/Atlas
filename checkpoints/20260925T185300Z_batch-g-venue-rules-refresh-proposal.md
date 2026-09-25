# ATLAS CHECKPOINT

## Objective

Owner brief 2026-09-25, Part G: close two gaps.

1. Nothing fetches a current `exchangeInfo` snapshot.
2. The adapter never writes `config/instrument_rules.json`, the file the
   runtime reads.

If more than one safe design exists, propose options instead of
implementing.

**Status: PART G, AWAITING OWNER DECISION.** No code was changed.

## Findings (read in this session)

### `tools/venue_metadata_adapter.py` (Block 6C, `3265b44`)

- Operator-invoked. AtlasApplication never imports it. It opens no socket.
- Input: an operator-supplied snapshot file
  (`TRANSPORT_FILE = "OPERATOR_SUPPLIED_FILE"`). Provenance is stamped
  `OPERATOR_SUPPLIED_SNAPSHOT_UNVERIFIED_TRANSPORT`.
- Publication steps:
  1. validate
  2. write a temp file and fsync it
  3. re-load it through the runtime's own `load_instrument_ruleset`
  4. `os.replace`
- Output: `instrument_rules.published.json`.
- Its docstring records a deliberate design decision: it "cannot write the
  checked-in `config/instrument_rules.json`", and "wiring a runtime to a
  published artifact is a separate, explicit operator action".
- It reads `REFERENCE_CONFIG_PATH` only to learn which symbols to cover.
- The docstring already anticipates an HTTP transport "behind
  `ExchangeInfoSnapshot` without changing anything below it".

### Runtime (`core/application.py`)

- `_build_instrument_rules` is documented as "the sole place that reads
  `config/instrument_rules.json` (owner decision 1)".
- The path is the hard-coded constant `DEFAULT_INSTRUMENT_RULES_PATH`. There
  is no override.
- Rules load once, at startup. There is no hot reload.

### Freshness

- `core/venue_rule_freshness.py` sets
  `DEFAULT_MAXIMUM_RULE_AGE_SECONDS = 30 days`.
- The checked-in rules carry `retrieved_at 2026-08-19T17:47:48Z`, which is
  about 37 days old today, so they are STALE.
- Per Block 6A, staleness fails closed only under live authority. PAPER is
  unaffected, which makes this a readiness gap and not a Gate-1 blocker.

### Transport precedent

- `tools/fetch_historical_market_data.py` already uses
  `BinancePublicDataProvider(timeout_seconds=20.0)`, a keyless public
  endpoint with retry and backoff (`atlas_finance/market_data/`).
- A fetch of `GET https://api.binance.com/api/v3/exchangeInfo?symbols=[...]`
  fits the same operator-tool pattern.

## Options

### G1: manual fetch tool, with git as the review step (recommended now)

How it works:

- A new operator tool, e.g. `tools/fetch_exchange_info.py`, does one public
  GET for the symbols in the reference config.
- It writes the raw snapshot, its sha256, and `retrieved_at`.
- It then calls the existing `publish_venue_rules` to produce
  `instrument_rules.published.json`.
- The operator reviews the diff against `config/instrument_rules.json` and
  commits it. That commit is the wiring step.

Gains:

- Zero runtime change. Owner decision 1 and the Block 6C "cannot write the
  config" design both hold.
- Every rule change becomes a reviewed commit.

Costs:

- A manual ritual at least every 30 days.
- The copy into `config/` is manual. It could be a documented
  `copy + git diff` step, or a `--promote` flag that only prints the diff.

Cost to build: small, one tool plus tests with the transport faked.

### G2: G1 plus a runtime path override

How it works:

- Add `ATLAS_INSTRUMENT_RULES_PATH`, following the precedent of
  `ATLAS_STATE_DIRECTORY`. It fails closed when set but invalid.
- The runtime reads the published artifact directly, e.g.
  `C:\AtlasState\instrument_rules.published.json`.

Gains:

- No repo churn on each refresh.
- The artifact lives outside OneDrive, like the other operator state.

Costs:

- Amends owner decision 1.
- The runtime would then read a file that is not in git, so review moves
  from a git diff to the adapter's validation plus an operator action.
- This touches `core/application.py`, which makes it a CRITICAL-tier change.

### G3: scheduled fetch and auto-publish (not recommended)

How it works: Task Scheduler or an in-process timer runs G1/G2 on a cadence.

Costs:

- An automated write into a financial-core input with no human review.
- Rules load only at startup, so it still needs a restart to take effect.
- Adds a failure mode where a bad publish lands unattended. The adapter
  refuses invalid payloads, but it cannot judge whether a valid change is
  wanted.

### Recommendation

- **G1** now, for the Paper stage.
- Revisit **G2** before the Shadow stage, when freshness starts to matter.
- Do not do **G3** before Controlled Autonomous.

## Owner decisions needed

1. Pick G1, G2 or G3.
2. Trigger: manual (recommended), or a cadence.
3. Promotion into `config/instrument_rules.json`: a manual commit
   (recommended), or a tool-assisted promote step that still stops for
   review.
4. Whether a new governance authorization record is needed for the tool.
   Recommended: yes. It is a new operator tool that makes network calls.

## Files changed

This checkpoint only.

## Tests

None. No code changed.

## Risks

None introduced. The rules stay STALE, which is harmless in PAPER.

## Next exact action

The owner picks an option. For G1, the task is roughly STANDARD: one tool
plus fake-transport tests. No runtime file is touched.
