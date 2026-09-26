"""
EXEC-ID-REDACTION-001: opaque execution identifiers survive the execution
authorities byte-exact.

The transaction journal, the idempotency store and audit events ran every
record through `sanitize_sensitive_data`, whose card detector rewrote a
13-19 digit Luhn-valid run to ``[REDACTED]``. That hit about 10% of candle
``request_id`` values (``SYMBOL|open:<13-digit ms>|SIDE``) and about 0.23%
of uuid4 ``execution_id`` values, and recovery compares both byte-exact.

The fix preserves by field identity (`preserve_identifiers=True`, opted into
only by those three authorities), never by tuning the detector. These tests
prove, on large generated corpora, that:

- every identifier class is preserved exactly, and the same corpus IS
  corrupted without the switch (so the tests discriminate);
- every non-identity field is redacted exactly as before;
- structurally invalid identity values fall back to ordinary redaction;
- events written under the old sanitizer still verify.
"""

from __future__ import annotations

import hashlib
import random
import uuid

from enum import Enum

import pytest

from atlas_security import sanitize_sensitive_data, sanitize_sensitive_text
from atlas_security.sensitive_data_guard import (
    DIGEST_KEYS,
    OPAQUE_IDENTIFIER_KEYS,
    _is_sensitive_key,
)
from core.audit_event import AuditEvent
from core.audit_event_store import AuditEventStore
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_transaction_journal import ExecutionTransactionJournal


SEED = 20260926
UUID_SAMPLES = 100_000
CANDLE_SAMPLES = 100_000
DIGEST_SAMPLES = 50_000
STORE_SAMPLES = 150

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
SIDES = ("BUY", "SELL")


def _uuids(count: int) -> list[str]:
    rng = random.Random(SEED)
    return [str(uuid.UUID(int=rng.getrandbits(128), version=4)) for _ in range(count)]


def _candle_ids(count: int) -> list[str]:
    """Minute-aligned and arbitrary millisecond candle request ids."""
    rng = random.Random(SEED + 1)
    base = 1_786_112_160_000
    ids = []
    for index in range(count):
        open_ms = base + 60_000 * index if index % 2 else rng.randrange(10**12, 10**13)
        ids.append(f"{rng.choice(SYMBOLS)}|open:{open_ms}|{rng.choice(SIDES)}")
    return ids


def _digests(count: int) -> list[str]:
    rng = random.Random(SEED + 2)
    return [hashlib.sha256(rng.randbytes(16)).hexdigest() for _ in range(count)]


def _corrupted(values: list[str]) -> list[str]:
    return [value for value in values if sanitize_sensitive_text(value) != value]


UUIDS = _uuids(UUID_SAMPLES)
CANDLE_IDS = _candle_ids(CANDLE_SAMPLES)
DIGESTS = _digests(DIGEST_SAMPLES)
#: The subset the legacy sanitizer actually rewrites - the discriminating cases.
BAD_UUIDS = _corrupted(UUIDS)
BAD_CANDLE_IDS = _corrupted(CANDLE_IDS)
BAD_DIGESTS = _corrupted(DIGESTS)


def _preserve(value):
    return sanitize_sensitive_data(value, preserve_identifiers=True)


# ---------------------------------------------------------------------------
# Corpus sanity: the defect is real at the measured scale
# ---------------------------------------------------------------------------


def test_corpora_reproduce_the_defect_without_the_switch():
    # Measured rates: ~0.23% uuid4, ~10% candle ids, ~0.4% sha256 digests.
    assert len(BAD_UUIDS) > 100
    assert len(BAD_CANDLE_IDS) > 5_000
    assert len(BAD_DIGESTS) > 50
    for value in BAD_UUIDS[:50] + BAD_CANDLE_IDS[:50]:
        assert sanitize_sensitive_data({"request_id": value})["request_id"] != value


# ---------------------------------------------------------------------------
# Fuzz: zero corruption for every identity field and every identifier class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(OPAQUE_IDENTIFIER_KEYS))
def test_every_identity_key_preserves_every_uuid_and_candle_id(key):
    for value in UUIDS + CANDLE_IDS:
        assert _preserve({key: value}) == {key: value}


def test_digest_key_preserves_every_digest():
    for value in DIGESTS:
        assert _preserve({"instrument_rules_digest": value}) == {
            "instrument_rules_digest": value
        }


def test_identity_preserved_at_depth_and_inside_lists():
    for execution_id, request_id in zip(BAD_UUIDS, BAD_CANDLE_IDS):
        record = {
            "execution_id": execution_id,
            "request_id": request_id,
            "data": {
                "request_id": request_id,
                "position": {"position": {"metadata": {
                    "execution_id": execution_id,
                    "idempotency_key": request_id,
                    "execution_fingerprint": request_id,
                }}},
            },
            "fills": [{"trade_id": execution_id, "order_id": execution_id}],
            "metadata": {"candle_identity": request_id.split("|")[1]},
        }
        assert _preserve(record) == record


def test_uuid_object_under_identity_key_serializes_canonically():
    for text in BAD_UUIDS:
        assert _preserve({"execution_id": uuid.UUID(text)}) == {"execution_id": text}


def test_enum_under_identity_key_is_preserved():
    Identity = Enum("Identity", {"VALUE": BAD_CANDLE_IDS[0]})
    assert _preserve({"request_id": Identity.VALUE}) == {"request_id": BAD_CANDLE_IDS[0]}


# ---------------------------------------------------------------------------
# Free text and every other field: redaction completely unchanged
# ---------------------------------------------------------------------------

CARD = "4111 1111 1111 1111"
FREE_TEXT = [
    f"card {CARD} declined",
    "contact ops@example.com now",
    "Authorization: Bearer abcdefghijklmnop",
    "api_key=sk-live-123456",
    "IBAN GB82WEST12345698765432",
    "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
]


def test_non_identity_fields_are_redacted_exactly_as_before():
    rng = random.Random(SEED + 3)
    keys = ("message", "error", "reason", "details", "note", "symbol", "id",
            "brain_session_id", "request", "execution", "request_ids")
    for index in range(5_000):
        record = {
            rng.choice(keys): rng.choice(FREE_TEXT + BAD_UUIDS[:20] + BAD_CANDLE_IDS[:20]),
            "nested": {rng.choice(keys): [rng.choice(FREE_TEXT), index]},
        }
        assert _preserve(record) == sanitize_sensitive_data(record)


def test_free_text_inside_identity_bearing_records_still_redacted():
    record = {"request_id": BAD_CANDLE_IDS[0], "error": f"card {CARD}", "api_key": "x"}
    out = _preserve(record)
    assert out["request_id"] == BAD_CANDLE_IDS[0]
    assert CARD not in out["error"] and "[REDACTED]" in out["error"]
    assert out["api_key"] == "[REDACTED]"


def test_identity_keys_are_never_sensitive_keys():
    for key in OPAQUE_IDENTIFIER_KEYS | DIGEST_KEYS:
        assert not _is_sensitive_key(key)


@pytest.mark.parametrize("bad", [
    f" {CARD}", f"{CARD} ", f"x\n{CARD}", f"x\t{CARD}", f"x\r{CARD}", f"x\x00{CARD}",
    CARD + "9" * 200, "",
])
def test_structurally_invalid_identity_falls_back_to_redaction(bad):
    assert _preserve({"request_id": bad}) == sanitize_sensitive_data({"request_id": bad})


def test_non_string_identity_is_not_coerced():
    # A mapping or list under an identity key is sanitized recursively as before.
    value = {"inner": f"card {CARD}"}
    assert _preserve({"execution_id": value}) == sanitize_sensitive_data({"execution_id": value})
    assert _preserve({"execution_id": [CARD]}) == {"execution_id": ["[REDACTED]"]}


@pytest.mark.parametrize("bad", [
    "A" * 64, DIGESTS[0].upper(), DIGESTS[0][:63], DIGESTS[0] + "0", f" {DIGESTS[0]}",
    f"card {CARD}",
])
def test_malformed_digest_falls_back_to_redaction(bad):
    assert _preserve({"instrument_rules_digest": bad}) == sanitize_sensitive_data(
        {"instrument_rules_digest": bad}
    )


def test_default_callers_are_unchanged():
    # Only the execution authorities opt in; event publishers etc. do not.
    value = BAD_CANDLE_IDS[0]
    assert sanitize_sensitive_data({"request_id": value}) == {
        "request_id": sanitize_sensitive_text(value)
    }


# ---------------------------------------------------------------------------
# Through the real stores, persisted and reloaded from disk
# ---------------------------------------------------------------------------


def _result(request_id: str, execution_id: str) -> dict:
    return {
        "request_id": request_id,
        "execution_id": execution_id,
        "status": "FILLED",
        "success": True,
        "position_id": execution_id,
        "data": {"request_id": request_id},
        "metadata": {
            "idempotency_key": request_id,
            "execution_fingerprint": request_id,
            "candle_identity": request_id.split("|")[1],
            "note": f"card {CARD}",
        },
    }


def test_journal_round_trip_preserves_identity(tmp_path):
    path = tmp_path / "execution_transaction_journal.jsonl"
    journal = ExecutionTransactionJournal(path)
    pairs = list(zip(BAD_CANDLE_IDS[:STORE_SAMPLES], BAD_UUIDS))
    for index, (request_id, execution_id) in enumerate(pairs):
        assert journal.prepare(request_id, {"request_id": request_id,
                                            "metadata": {"idempotency_key": request_id}})
        result = _result(request_id, execution_id)
        if index % 2:
            assert journal.mark_committed(request_id, result)
        else:
            assert journal.mark_not_committed(request_id, reason="X", result=result)

    reloaded = ExecutionTransactionJournal(path)
    assert reloaded.loaded and not reloaded.load_failed
    for request_id, execution_id in pairs:
        entry = reloaded.entries[request_id]
        # The recovery tool refuses unless this equals the envelope key.
        assert entry["request"]["request_id"] == request_id
        assert entry["result"]["request_id"] == request_id
        assert entry["result"]["execution_id"] == execution_id
        assert entry["result"]["data"]["request_id"] == request_id
        assert entry["result"]["metadata"]["idempotency_key"] == request_id
        assert CARD not in entry["result"]["metadata"]["note"]
        # Committed facts repeat idempotently after reload.
    for index, (request_id, execution_id) in enumerate(pairs):
        if index % 2:
            assert reloaded.mark_committed(request_id, _result(request_id, execution_id))


def test_idempotency_round_trip_preserves_identity(tmp_path):
    path = tmp_path / "execution_idempotency.jsonl"
    store = ExecutionIdempotencyStore(path)
    pairs = list(zip(BAD_CANDLE_IDS[:STORE_SAMPLES], BAD_UUIDS))
    for request_id, execution_id in pairs:
        assert store.record(request_id, _result(request_id, execution_id))

    reloaded = ExecutionIdempotencyStore(path)
    for request_id, execution_id in pairs:
        record = reloaded.get(request_id)
        assert record["request_id"] == request_id
        assert record["execution_id"] == execution_id
        assert record["position_id"] == execution_id
        assert record["metadata"]["execution_fingerprint"] == request_id
        assert CARD not in record["metadata"]["note"]


def test_audit_round_trip_preserves_identity_and_verifies(tmp_path):
    path = tmp_path / "audit" / "atlas_audit_events.jsonl"
    store = AuditEventStore(path)
    triples = list(zip(BAD_CANDLE_IDS[:STORE_SAMPLES], BAD_UUIDS, BAD_DIGESTS * 3))
    for request_id, execution_id, digest in triples:
        store.append(
            event_type="RISK_ACCOUNTING_REALIZED_PNL_PREPARED",
            source="test",
            aggregate_type="execution_request",
            aggregate_id=request_id,
            correlation_id=request_id,
            payload={"request_id": request_id, "execution_id": execution_id,
                     "details": {"instrument_rules_digest": digest},
                     "message": f"card {CARD}"},
        )

    reloaded = AuditEventStore(path)
    assert reloaded.verify_chain()["valid"]
    events = reloaded.read_all()
    assert len(events) == len(triples)
    for event, (request_id, execution_id, digest) in zip(events, triples):
        assert event.aggregate_id == request_id
        assert event.payload["request_id"] == request_id
        assert event.payload["execution_id"] == execution_id
        assert event.payload["details"]["instrument_rules_digest"] == digest
        assert CARD not in event.payload["message"]


def test_events_written_under_the_legacy_sanitizer_still_verify(monkeypatch):
    """Existing on-disk hash chains must not break: a value the old pass
    redacted is stored redacted and is preserved verbatim now."""
    legacy = staticmethod(lambda value: sanitize_sensitive_data(value))
    payloads = [{"request_id": r, "execution_id": e, "message": f"card {CARD}"}
                for r, e in zip(BAD_CANDLE_IDS[:200], BAD_UUIDS)]
    with monkeypatch.context() as patch:
        patch.setattr(AuditEvent, "_safe_payload", classmethod(lambda cls, v: legacy(v)))
        stored = [
            AuditEvent.create(event_type="E", source="s", aggregate_type="a",
                              aggregate_id=p["request_id"], payload=p).to_dict()
            for p in payloads
        ]
    for data in stored:
        assert "[REDACTED]" in data["payload"]["request_id"]
        event = AuditEvent.from_dict(data)
        assert event.verify_hash()
        assert event.payload == data["payload"]


# ---------------------------------------------------------------------------
# Independent-audit follow-ups (F1, F2, F4, legacy journal/idempotency load)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(OPAQUE_IDENTIFIER_KEYS))
@pytest.mark.parametrize("text", [
    "user a@b.com", "ops@example.com", "api_key=zzz", "token=abc123",
    f"card {CARD}", "Bearer abcdefghijklmnop", "a/b", "x+y",
])
def test_f1_identity_key_is_not_a_channel_for_free_text(key, text):
    """Outside the identifier charset the value is redacted exactly as before."""
    record = {"metadata": {key: text}}
    assert _preserve(record) == sanitize_sensitive_data(record)


def test_f1_generated_ids_are_all_inside_the_preservable_charset():
    from atlas_security.sensitive_data_guard import _PRESERVABLE_IDENTIFIER_PATTERN
    for value in UUIDS + CANDLE_IDS:
        assert _PRESERVABLE_IDENTIFIER_PATTERN.fullmatch(value)


def test_f2_new_events_are_forward_only_for_legacy_readers(monkeypatch):
    """Pinned: an event preserving a Luhn-positive id verifies under the new
    code but NOT under the pre-fix sanitizer. Rolling this change back would
    break verify_chain on such events - rollback is one-way for hash chains."""
    payload = {"request_id": BAD_CANDLE_IDS[0], "execution_id": BAD_UUIDS[0]}
    data = AuditEvent.create(event_type="E", source="s", aggregate_type="a",
                             aggregate_id="agg", payload=payload).to_dict()
    assert AuditEvent.from_dict(data).verify_hash()
    with monkeypatch.context() as patch:
        patch.setattr(AuditEvent, "_safe_payload",
                      classmethod(lambda cls, v: sanitize_sensitive_data(v)))
        assert not AuditEvent.from_dict(data).verify_hash()


def test_f4_ids_directly_inside_lists_are_not_preserved():
    """Pinned: preservation is by field identity; a bare list element has none."""
    value = BAD_CANDLE_IDS[0]
    assert _preserve({"request_id": [value]}) == {"request_id": [sanitize_sensitive_text(value)]}


def test_logs_written_under_the_legacy_sanitizer_reload_unchanged(tmp_path, monkeypatch):
    """Existing journal/idempotency logs are neither repaired nor altered."""
    import core.execution_idempotency_store as idem_module
    import core.execution_transaction_journal as journal_module

    legacy = lambda value, **_: sanitize_sensitive_data(value)  # noqa: E731
    pairs = list(zip(BAD_CANDLE_IDS[:40], BAD_UUIDS))
    journal_path = tmp_path / "journal.jsonl"
    idem_path = tmp_path / "idem.jsonl"
    with monkeypatch.context() as patch:
        patch.setattr(journal_module, "sanitize_sensitive_data", legacy)
        patch.setattr(idem_module, "sanitize_sensitive_data", legacy)
        journal = ExecutionTransactionJournal(journal_path)
        idem = ExecutionIdempotencyStore(idem_path)
        for request_id, execution_id in pairs:
            journal.prepare(request_id, {"request_id": request_id})
            journal.mark_committed(request_id, _result(request_id, execution_id))
            idem.record(request_id, _result(request_id, execution_id))
        legacy_entries = ExecutionTransactionJournal(journal_path).entries
        legacy_records = ExecutionIdempotencyStore(idem_path).completed_requests

    assert ExecutionTransactionJournal(journal_path).entries == legacy_entries
    assert ExecutionIdempotencyStore(idem_path).completed_requests == legacy_records
    # The historical corruption is still there: no silent repair.
    request_id = pairs[0][0]
    assert legacy_entries[request_id]["request"]["request_id"] != request_id
