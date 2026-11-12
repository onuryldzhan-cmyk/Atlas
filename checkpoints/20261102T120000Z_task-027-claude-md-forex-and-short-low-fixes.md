# ATLAS CHECKPOINT — Task 027: CLAUDE.md forex update and the Task 026 LOW fixes

## Objective
Bring the project doctrine in line with the forex pivot, and close the three LOW findings of the Task 026 review
(grant GRANT-TASK-027-CLAUDE-MD-FOREX-AND-SHORT-LOW-FIXES, registry v5.110).

Owner message 2026-11-02: 'Devam onay'. Asked what it approves, the owner chose 'CLAUDE.md + LOW düzeltmeleri
(Önerilen)' (quoted verbatim in v5.110).

Authority is unchanged: live DENIED, production NONE.

## Completed
- **CLAUDE.md:** the text of `proposals/2026-10-27_CLAUDE_md_forex_update_PROPOSAL.md`, applied exactly.
  - forex is the market;
  - the venue is in the decision flow;
  - the forex invariants are under Financial / migration safety;
  - `atlas_finance` and `governance` are in the directory map.
  - No authority, ladder, rule or roadmap text changed.
- **T026-F3 (Brain memory caution):** the BRAIN-MEM-001 caution (up to 5 points less on a losing book) also applies
  to a SELL that opens a forex short.
  - FOREX hands the Brain the MarketLoop's short-entry check (`AtlasBrain.short_entry_check`, forwarded in
    `load_intelligence`).
  - A check that raises or answers anything but False counts as new risk. A book the loop cannot read answers
    False, and the loop then opens no short either.
  - A SELL that reduces exposure still never gets the caution.
  - CRYPTO has no check, so it is unchanged.
- **T026-F4 (PaperTrader mirror):** the passive mirror carries `side: "SHORT"` for a short only, and its legacy
  profit uses the short's sign.
- **T026-F5 (reports):**
  - `paper_position_report` accepts `short:` identities, attributes a short exactly to its own RISK_APPROVED SELL,
    and labels each approval BUY or SELL.
  - A SELL approval never takes part in a LEGACY timestamp match.
  - `lesson_book` enters a closed short as a SELL lesson row.

## Files changed
- **Commit 1:** registry v5.110.
- **Commit 2:**
  - `CLAUDE.md`;
  - `ai/core/atlas_brain.py`, `core/brain.py`, `core/application.py`;
  - `core/paper_trader.py`;
  - `tools/paper_position_report.py`, `tools/lesson_book.py`;
  - `tests/test_task027_short_low_fixes.py` (new);
  - the packaging maps (if a cited line moved);
  - this checkpoint.
- **Test change, disclosed:** `tests/test_phase2_f1_trade_attribution.py`. The malformed-identity test listed
  `short:BTCUSDT:<64 hex>` as malformed; it has been a real identity format since Task 026.
  - That entry is replaced by two truly malformed ones: `flat:…` and `short:BTCUSDT:abc`.
  - A new assertion states that a forged short identity is canonical but never matches a request it was not minted
    from (`opened_by` is still False).
- **Environment (not committed):** this new container lacked pytest, fastapi and the other pinned packages.
  - Installed: `pytest==9.1.1` and `requirements/all.txt` with `requirements/constraints.txt`.
  - `httpx2` is a real dependency: Starlette 1.5's test client imports it.

## Tests
- **Task 027:** 16 passed.
- **Mutation check:** 8 planted bugs. The first pass caught 7. The survivor (SELL approvals dropped by the audit
  loader) was killed by an added test. So 8 of 8 are caught.
- **Neighbouring tests:** brain memory, reports, lesson book, attribution, agent cycle: 303 passed.
- **Independent review:** 0 BLOCKING / 0 HIGH / 0 MEDIUM / 2 LOW / 5 INFO.
  - LOW-1 (registry wording about the unsure check) is fixed, and v5.110 was rebuilt.
  - LOW-2 (the stale "no RISK_APPROVED BUY" message) is fixed.
  - INFO-5, kept: `core/portfolio_manager.py` and `core/position_lifecycle.py` compute profit without a side.
    Whether they ever read forex short records is UNKNOWN.
- **Full suite (Python 3.13):** 11636 passed, 13 skipped, 1 failed.
  - The failure was the quality ratchet: a two-line call pushed `analyze_and_decide` over 300 lines. Fixed with a
    one-line call and the `_memory_caution` helper.
  - After the fix, the ratchet and the Task 027 neighbours gave 55 passed. Total: 11637 passed (11622 + 16 new, less
    one test that now skips in this container), 0 failed.

## Known issues / Risks
- **Waiting on the owner's MT5 test:** the MT5 verification, the measured commission and swap, the December
  early-close hours, and crypto removal (Task 020).
- **Carried over:** T023-F4/F5/F6. `paper_position_report`'s live price lookup is still the crypto one (use
  `--no-price` for forex).

## Remaining work
1. Owner: the MT5 test on Windows (`proposals/2026-10-27_owner_mt5_windows_test_GUIDE.md`).
2. The measured commission and swap (new manifest).
3. Task 020: crypto removal.

## Next exact action
Wait for the owner's MT5 results; then write the commission and swap manifest (v6) and its registry record.
