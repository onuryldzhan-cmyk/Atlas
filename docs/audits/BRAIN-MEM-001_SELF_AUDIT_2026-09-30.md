# BRAIN-MEM-001: audit-mode review (2026-09-30)

**This is NOT the independent audit.** It was written by the same session that implemented BRAIN-MEM-001, in AUDIT MODE. The independent audit required by CLAUDE.md for CRITICAL work is still **UNKNOWN / pending**.

**Scope:**
- `ai/core/intelligence/trade_evidence.py`
- `ai/core/intelligence/memory_adapter.py` (`_trade_book`)
- `ai/core/atlas_brain.py` (`_memory_buy_caution`)
- `core/brain.py` (`_read_closed_positions`)

## Findings

### M-1 MEDIUM: removing evidence removes caution (NB-4-shaped)

- **Location:** `memory_adapter._trade_book` and `trade_evidence.symbol_evidence`.
- **Evidence:** An unreadable archive (`ARCHIVE_UNREADABLE`) or one malformed record for the coin (`MALFORMED_ARCHIVE_RECORD`) returns `effect 0.0`. A coin whose book is losing therefore loses its −5 caution whenever the archive cannot be read.
- **Impact:** Confidence for that coin's BUY rises by up to 5 points when evidence is **removed**. That is the NB-4 pattern ("confidence must not rise when evidence is removed").
  - It never goes above the pre-BRAIN-MEM-001 baseline.
  - The risk engine, capital and execution gates are unchanged.
- **Remediation options** (CRITICAL, owner decision):
  - **(a) Fail closed:** unreadable or malformed data applies `LOSING_EFFECT` to BUYs until the archive is readable. It is conservative, but a broken file cautions every coin.
  - **(b) Keep the last good evidence** per coin in memory (in-process) and use it while the archive is unreadable.
  - **Recommended: (b), with (a) when no last-good evidence exists.**

### L-1 LOW: the reader bypasses archive validation

- **Location:** `core/brain.py _read_closed_positions`.
- **Evidence:** It parses raw JSONL, not the portfolio foundation's validated `load_index()`. Duplicate or unvalidated rows are counted as they are.
- **Impact:** A duplicated row would double-count one trade in expectancy.
- **Remediation:** Deduplicate by `position_id`, or read through the validated index.

### L-2 LOW: the whole archive is re-read for every coin decision

- **Evidence:** 20 coins every minute means 20 full reads per minute. The cost grows linearly with trade count.
- **Impact:** Latency only, no correctness issue.
- **Remediation:** Cache the records by file mtime and size.

### I-1 INFORMATIONAL: estimated fees

- Net P/L uses an estimated fee of 0.1 % per side, not the book's recorded fees. It is stated in the module and consistent with the reports.

## Verified as correct

- The effect is never positive. A winning book gives 0 (rule 3, NB-4 in the upward direction).
- There is no effect below 10 trades.
- Only a BUY is touched; SELL and HOLD are unchanged.
- The penalty is capped at 5 points.
- The adjustment is recorded in `metadata.memory_adjustment`.
- An unreadable archive never raises into the decision path.

## Status

- M-1, L-1 and L-2 are **OPEN**. The fixes touch the decision path, so they are CRITICAL and need the owner's approval.
- The independent audit is still required.
