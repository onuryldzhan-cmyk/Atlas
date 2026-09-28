"""Atlas organization governance contracts (L1: pure, stdlib only, no I/O).

- ``permissions``: explicit capability grants per organization unit.
- ``proposals``: the proposal lifecycle as an append-only, hash-chained
  event log; only the owner can approve or reject.
- ``memory_records``: Atlas Memory records with provenance and authority.

Owner decision 2026-09-28 (registry v5.34): "Önce yönetişim temeli".
Nothing here grants runtime, trading or deployment authority.
"""
