# ATLAS CHECKPOINT — Task 008: Exchange Adapter Safety, Idempotency & Transaction Journal

## Objective
Implement Task 008 under GRANT-TASK-008-EXCHANGE-ADAPTER-SAFETY-IDEMPOTENCY-JOURNAL (registry v5.92):
close the verified safety gaps of the dormant exchange order path against the brief's failure vectors
(A memory/replay leak, B duplicate fills, C silent failures). Real order submission stays disabled.

## Completed
- **CONFLICTs C-1..C-5** were reported and decided by the owner in session on 2026-10-10:
  - v5.92 was absent and Task 007 was still open;
  - the brief's "no governance changes" rule contradicted its own v5.92 deliverable;
  - `exchange/venue_rule_freshness.py` does not exist (the module is in `core/`);
  - real submission is disabled;
  - most of the requested machinery already existed.
- **Owner decisions:**
  - draft v5.92 (close Task 007, grant Task 008);
  - audit first, fix only verified gaps;
  - derive the client order id once, persist it and reuse it.
- **Registry v5.92** (committed on its own): Task 007 CLOSED; Task 008 defined in roadmap Phase 2 and granted.
  It records the CONFLICTs in the Expected/Actual/Evidence/Impact/Decision format, the verified gaps,
  reviews 10–14, the known limitations, the UNKNOWNs, and one agent safety deviation: HTTP 5xx is
  reconciled, never retried.
- **exchange/exchange_manager.py:**
  - Pending reconciliations never expire and are never evicted; at capacity, new orders are refused.
  - Before a new order on a pair, every unresolved order on that pair is reconciled; if one stays
    ambiguous, the pair is halted (`HALT_VENUE_PAIR`). In-flight orders are excluded.
  - Venue error taxonomy:
    - rate limit → full-jitter backoff, retried under the same id;
    - unknown outcome (5xx, 408, -1006/-1007, "Duplicate order sent") → reconciled, never resent;
    - terminal rejection → `PERMANENTLY_REJECTED`, cached.
  - Optional durable order journal (core `DurableAppendLog`):
    - records INTENT_CREATED, DISPATCHED, VENUE_ACK, TERMINAL, UNRECONCILED, DISPATCH_FAILED and
      PAIR_HALTED;
    - each event is written before its state, under one writer lock;
    - the journal is checked before the gates and again atomically at leader election;
    - the index is bounded for finished ids, and journaled unresolved orders are restored as pending
      at startup;
    - an order the journal proves was never dispatched is released atomically.
  - Optional 24-hour venue precision gate: step, minimum quantity, minimum notional, tick and upper
    bounds.
  - Priced (limit) requests are refused, because the adapter places market orders only.
  - `status()` gains `halted_pairs`, `order_journal`, `venue_precision_gate`, `rate_limit_retry` and
    `live_prerequisites`.
- **exchange/persistent_idempotency_store.py:**
  - pending entries never expire or truncate;
  - a malformed pending entry or an unknown state fails the store closed;
  - the file and its directory are fsynced on save.
- **exchange/base_exchange.py:** `derive_client_order_id` (SHA-256, `atl-` + 32 hex = 36 chars),
  `CLIENT_ORDER_ID_PATTERN`, the `VenueError` taxonomy and `classify_venue_failure`.
- **exchange/execution_safety_gate.py:** the `HALT_VENUE_PAIR` reason.
- **exchange/adapters/binance_global.py:** the disabled `place_order` refuses a missing or invalid client
  order id.

## Files changed
exchange/exchange_manager.py, exchange/persistent_idempotency_store.py, exchange/base_exchange.py,
exchange/execution_safety_gate.py, exchange/adapters/binance_global.py, tests/exchange/__init__.py (new),
tests/exchange/test_task008_safety_idempotency.py (new, 58 tests),
governance/current/ATLAS_MILESTONE_REGISTRY_v5.92.json (separate commit), this checkpoint.

## Architecture decisions
- Pinned contracts are kept (existing tests unmodified):
  - a generic adapter exception is a retryable, definite local failure;
  - Timeout and ConnectionError become pending;
  - terminal results are cached.
- The journal, venue rules and persistent store are optional constructor inputs, so existing callers keep
  working. v5.92 makes all three mandatory before any live enablement, along with a live adapter that
  raises the taxonomy for every post-transmission failure.
- `core/` execution authorities (idempotency store, transaction journal, venue_rule_freshness) were
  audited and left unchanged: they have no venue dispatch, and the paper runtime is untouched.

## Tests
- Full suite (final tree): 10480 passed, 12 skipped, 0 failed.
- The Task 008 tests cover:
  - 100 simultaneous submissions → exactly 1 dispatch;
  - a timeout reconciled before the next order on the pair, and the pair halt;
  - pending entries that never expire;
  - the taxonomy and backoff;
  - the journal milestones and the crash-inside-adapter case;
  - the precision gate and stale rules;
  - every TOCTOU interleaving the reviews found;
  - restore and failure paths.
- Every review fix was mutation-checked: removing the fix makes its test fail. Where two independent
  guards cover the same case, they were removed together.

## Reviews (fresh context, red team, threshold 0 BLOCKING / 0 HIGH / 0 MEDIUM)
- Review 10 FAIL: H-1 (journal race), M-1..M-3, L-1..L-3.
- Reviews 11, 12 and 13 FAIL with 0 HIGH (MEDIUMs: index growth on failure paths, missing safety tests, a
  release TOCTOU, a journal-gate TOCTOU, the DISPATCHED-order test).
- Review 14 PASS: 0/0/0. An 8-thread fuzz test over 14 seeds found no re-dispatch of an id that may have
  reached the venue.
- Every finding was fixed and re-tested.

## Current state
Task 008 implemented and verified; the milestone is ACTIVE (closing it is the owner's decision). The
exchange path stays dormant: no runtime caller, `PAPER_ONLY` adapter, live DENIED.

## Known issues / limitations (all recorded in v5.92)
- The journal file is append-only and never compacted (about 0.5–1 KB per order, read in full at
  startup). Rotation is a deferred owner decision.
- Finished ids are indexed only up to `idempotency_max_entries`. An older finished id resent by a caller
  could be dispatched again.
- There is no operator resolution path for a pair halted on an order the venue cannot report and that
  has no journal proof.
- `live_prerequisites` is reported but not enforced. The helpers have no production caller.
- If restore fails at startup, the journal is disabled until restart.
- Pre-existing, unrelated: the `ore/position_sizing.py` metadata bug in
  `tools/build_architecture_inventory.py`, and the clock flake in `tests/test_apprentice.py`.

## Risks
None to the current runtime. Before live use, the binding prerequisites in v5.92 apply.

## Remaining work
- The owner confirms or reverses the 5xx deviation.
- The owner closes Task 008.
- Live enablement, if ever, under a separate grant.

## Next exact action
Report to the owner.
