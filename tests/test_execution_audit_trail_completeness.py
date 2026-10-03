"""
Execution audit-trail completeness: three deferred findings closed together.

C1 (v4.85 F3): ``provenance_ref`` (``transaction-journal:<request_id>``) is
preserved byte-exact under ``preserve_identifiers=True`` - but only in that
exact shape, with the embedded id passing every rule an opaque identifier
must pass. Anything else is redacted exactly as before.

C2 (v4.84 LOW-C): every audit event the recovery tool causes carries
``metadata.origin``; a booking the tool rolls back is followed by one
``RISK_ACCOUNTING_RECOVERY_BOOKING_ROLLED_BACK`` event naming what it left.

C3: a refused automatic PAPER risk-day rollover is recorded as a
``RISK_ACCOUNTING_DAY_ROLLOVER_REFUSED`` audit event alongside its WARNING
log line; the refusal itself is unchanged.

Every test runs against its own ``tmp_path`` state directory.
"""

from __future__ import annotations

import random
import uuid

from datetime import timedelta
from decimal import Decimal

import pytest

import core.execution_manager as execution_manager_module
from atlas_security import sanitize_sensitive_data, sanitize_sensitive_text
from atlas_security.sensitive_data_guard import (
    DIGEST_KEYS,
    MAX_IDENTIFIER_LENGTH,
    OPAQUE_IDENTIFIER_KEYS,
    PROVENANCE_REF_KEYS,
    PROVENANCE_REF_PREFIX,
    _is_sensitive_key,
)
from core.application import EXECUTION_AUDIT_EVENT_FILE, RISK_ACCOUNTING_STATE_FILE
from core.audit_event import AuditEvent
from core.audit_event_store import AuditEventStore
from core.execution_idempotency_store import ExecutionIdempotencyStore
from core.execution_manager import ExecutionManager
from core.execution_transaction_journal import ExecutionTransactionJournal
from core.risk_state_store import JsonRiskStateStore

import tools.reconcile_execution_authorities as reconcile_module
from tools.reconcile_execution_authorities import (
    AUDIT_ORIGIN,
    AUDIT_ORIGIN_FIELD,
    RECOVERY_BOOKING_ROLLED_BACK,
    ReconciliationOutcome,
)

from tests.test_execution_crash_recovery_f1_f6 import _recover
from tests.test_recovery_risk_accounting_booking import (
    _baseline,
    _crash_before_accounting_write,
    _crash_k2,
    _crashed_sell,
    _figures,
    _risk_bytes,
)
from tests.test_risk_accounting_day_auto_rollover import (
    STALE_REASON,
    _app,
    _risk_check,
    _stale_state,
    _stored,
    _today,
)
from tests.test_risk_accounting_realized_pnl_wiring import PNL_COMMITTED, PNL_PREPARED


D = Decimal
SEED = 20260927
SAMPLES = 100_000
KEY = "provenance_ref"
REFUSED = ExecutionManager.RISK_DAY_ROLLOVER_REFUSED
CARD = "4111 1111 1111 1111"


@pytest.fixture(autouse=True)
def _isolated_roots(monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)


# ===========================================================================
# C1 - provenance_ref preservation
# ===========================================================================


def _uuids(count: int) -> list[str]:
    rng = random.Random(SEED)
    return [str(uuid.UUID(int=rng.getrandbits(128), version=4)) for _ in range(count)]


def _candle_ids(count: int) -> list[str]:
    rng = random.Random(SEED + 1)
    base = 1_786_112_160_000
    return [
        f"{rng.choice(('BTCUSDT', 'ETHUSDT', 'SOLUSDT'))}|open:"
        f"{base + 60_000 * index if index % 2 else rng.randrange(10**12, 10**13)}|"
        f"{rng.choice(('BUY', 'SELL'))}"
        for index in range(count)
    ]


REFS = [PROVENANCE_REF_PREFIX + value for value in _uuids(SAMPLES) + _candle_ids(SAMPLES)]
#: The subset the legacy sanitizer rewrites - the discriminating cases.
BAD_REFS = [ref for ref in REFS if sanitize_sensitive_text(ref) != ref]


def _preserve(value):
    return sanitize_sensitive_data(value, preserve_identifiers=True)


def test_c1_corpus_reproduces_the_defect_without_the_switch():
    assert len(BAD_REFS) > 5_000
    for ref in BAD_REFS[:200]:
        assert sanitize_sensitive_data({KEY: ref})[KEY] != ref


def test_c1_fuzz_every_generated_provenance_ref_is_preserved_exactly():
    for ref in REFS:
        assert _preserve({KEY: ref}) == {KEY: ref}


def test_c1_preserved_at_depth_and_in_list_elements_that_are_records():
    for ref in BAD_REFS[:500]:
        record = {"result": {KEY: ref, "data": [{KEY: ref}]}, "note": f"card {CARD}"}
        assert _preserve(record) == {
            "result": {KEY: ref, "data": [{KEY: ref}]},
            "note": sanitize_sensitive_text(f"card {CARD}"),
        }


def test_c1_key_sets_are_disjoint_and_never_sensitive():
    assert PROVENANCE_REF_KEYS == {"provenance_ref"}
    assert not PROVENANCE_REF_KEYS & (OPAQUE_IDENTIFIER_KEYS | DIGEST_KEYS)
    assert not _is_sensitive_key(KEY)


def test_c1_without_the_switch_provenance_ref_is_redacted_as_before():
    for ref in BAD_REFS[:200]:
        assert sanitize_sensitive_data({KEY: ref}) == {KEY: sanitize_sensitive_text(ref)}


@pytest.mark.parametrize("value", [
    # Wrong or altered prefix: only the shape the authorities write.
    "paper-journal:" + "4111111111111111",
    "Transaction-journal:" + "4111111111111111",
    "transaction_journal:" + "4111111111111111",
    "transaction-journal" + "4111111111111111",
    "4111111111111111",
    # Embedded id fails the opaque-identifier structure.
    PROVENANCE_REF_PREFIX,
    PROVENANCE_REF_PREFIX + " 4111111111111111",
    PROVENANCE_REF_PREFIX + "4111111111111111 ",
    " " + PROVENANCE_REF_PREFIX + "4111111111111111",
    PROVENANCE_REF_PREFIX + "4111111111111111\n",
    PROVENANCE_REF_PREFIX + "41111111\t11111111",
    PROVENANCE_REF_PREFIX + "4111111111111111\x00",
    PROVENANCE_REF_PREFIX + "4" * (MAX_IDENTIFIER_LENGTH + 1),
    # F1: outside the identifier charset it is never a channel for free text.
    PROVENANCE_REF_PREFIX + f"card {CARD}",
    PROVENANCE_REF_PREFIX + "ops@example.com",
    PROVENANCE_REF_PREFIX + "api_key=zzz",
    PROVENANCE_REF_PREFIX + "token=4111111111111111",
    PROVENANCE_REF_PREFIX + "Bearer abcdefghijklmnop",
    PROVENANCE_REF_PREFIX + "a/4111111111111111",
    PROVENANCE_REF_PREFIX + "x+4111111111111111",
    PROVENANCE_REF_PREFIX + "[REDACTED]",
])
def test_c1_anything_outside_the_grammar_is_redacted_exactly_as_before(value):
    record = {KEY: value, "metadata": {KEY: value}}
    assert _preserve(record) == sanitize_sensitive_data(record)


@pytest.mark.parametrize("value", [None, 4111111111111111, b"transaction-journal:1",
                                   uuid.UUID(int=1)])
def test_c1_non_string_values_take_ordinary_sanitization(value):
    assert _preserve({KEY: value}) == sanitize_sensitive_data({KEY: value})


def test_c1_length_bound_applies_to_the_embedded_identifier():
    at_bound = PROVENANCE_REF_PREFIX + "4111111111111111" + "7" * (MAX_IDENTIFIER_LENGTH - 16)
    over = at_bound + "7"
    assert _preserve({KEY: at_bound}) == {KEY: at_bound}
    assert _preserve({KEY: over}) == sanitize_sensitive_data({KEY: over})


def test_c1_legacy_sanitized_values_are_fixed_points():
    """What the old sanitizer already persisted reloads unchanged: no repair."""
    for ref in BAD_REFS[:2_000]:
        legacy = sanitize_sensitive_text(ref)
        assert _preserve({KEY: legacy}) == {KEY: legacy}


def _result(request_id: str) -> dict:
    return {
        "request_id": request_id, "execution_id": str(uuid.uuid4()),
        "status": "PAPER_EXECUTED", "success": True,
        "idempotency_key": request_id,
        "provenance_ref": PROVENANCE_REF_PREFIX + request_id,
        "note": f"card {CARD}",
    }


def test_c1_round_trip_through_the_real_authorities(tmp_path):
    request_ids = [ref[len(PROVENANCE_REF_PREFIX):] for ref in BAD_REFS[:150]]
    journal = ExecutionTransactionJournal(tmp_path / "journal.jsonl")
    idem = ExecutionIdempotencyStore(tmp_path / "idem.jsonl")
    audit = AuditEventStore(tmp_path / "audit.jsonl")
    for request_id in request_ids:
        assert journal.prepare(request_id, {"request_id": request_id})
        assert journal.mark_committed(request_id, _result(request_id))
        assert idem.record(request_id, _result(request_id))
        audit.append(event_type="E", source="s", aggregate_type="a",
                     aggregate_id="agg", payload=_result(request_id),
                     correlation_id=request_id)

    entries = ExecutionTransactionJournal(tmp_path / "journal.jsonl").entries
    records = ExecutionIdempotencyStore(tmp_path / "idem.jsonl").completed_requests
    reloaded = AuditEventStore(tmp_path / "audit.jsonl", verify_on_load=True)
    assert reloaded.loaded
    events = {event.correlation_id: event for event in reloaded.read_all()}
    for request_id in request_ids:
        expected = PROVENANCE_REF_PREFIX + request_id
        assert entries[request_id]["result"]["provenance_ref"] == expected
        assert records[request_id]["provenance_ref"] == expected
        assert events[request_id].payload["provenance_ref"] == expected
        assert events[request_id].verify_hash()
        # Every other field keeps its redaction.
        assert records[request_id]["note"] == sanitize_sensitive_text(f"card {CARD}")


def test_c1_legacy_audit_events_still_verify(monkeypatch):
    """An event created and hashed under the pre-C1 sanitizer holds the
    redacted ref, which is a fixed point of the new one, so it still verifies."""
    legacy_sanitizer = classmethod(lambda cls, v: sanitize_sensitive_data(v))
    for ref in BAD_REFS[:200]:
        with monkeypatch.context() as patch:
            patch.setattr(AuditEvent, "_safe_payload", legacy_sanitizer)
            data = AuditEvent.create(event_type="E", source="s", aggregate_type="a",
                                     aggregate_id="agg", payload={KEY: ref}).to_dict()
        assert data["payload"][KEY] != ref
        event = AuditEvent.from_dict(data)
        assert event.payload == data["payload"]
        assert event.verify_hash()


# ===========================================================================
# C2 - recovery-tool audit origin and rollback marker
# ===========================================================================


def _audit_events(state_dir):
    store = AuditEventStore(state_dir / EXECUTION_AUDIT_EVENT_FILE, verify_on_load=True)
    assert store.loaded
    return store.read_all()


def _markers(state_dir):
    return [e for e in _audit_events(state_dir) if e.event_type == RECOVERY_BOOKING_ROLLED_BACK]


def _origin(event):
    return (event.metadata or {}).get(AUDIT_ORIGIN_FIELD)


def test_c2_tool_booking_events_carry_the_origin_marker(tmp_path, monkeypatch):
    expected, _, _ = _baseline(tmp_path, base="100", price="9")
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")

    outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert _figures(state_dir) == expected
    booked = [e for e in _audit_events(state_dir)
              if e.event_type in {PNL_PREPARED, PNL_COMMITTED}]
    assert [e.event_type for e in booked] == [PNL_PREPARED, PNL_COMMITTED]
    assert all(_origin(e) == AUDIT_ORIGIN for e in booked)
    # The hook's own metadata is kept; only the marker is added.
    assert all(e.metadata["mode"] == "PAPER" and "manager_version" in e.metadata for e in booked)
    assert _markers(state_dir) == []


def test_c2_runtime_events_never_carry_the_origin_marker(tmp_path, monkeypatch):
    """Redo path: the runtime's PREPARED (no marker) is followed by the
    tool's PREPARED/COMMITTED (marked) - the two are now distinguishable."""
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_before_accounting_write,
                              base="100", price="9")
    runtime_events = _audit_events(state_dir)
    assert runtime_events and all(_origin(e) is None for e in runtime_events)

    assert _recover(state_dir).outcome is ReconciliationOutcome.RECOVERED
    events = _audit_events(state_dir)
    prepared = [e for e in events if e.event_type == PNL_PREPARED]
    assert [_origin(e) for e in prepared] == [None, AUDIT_ORIGIN]
    assert [_origin(e) for e in events if e.event_type == PNL_COMMITTED] == [AUDIT_ORIGIN]


def test_c2_failed_booking_is_followed_by_a_rollback_marker(tmp_path, monkeypatch):
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    risk_before = _risk_bytes(state_dir)

    def failing_save(self, value):
        raise OSError("disk full")

    with monkeypatch.context() as patched:
        patched.setattr(JsonRiskStateStore, "save", failing_save)
        outcome = _recover(state_dir)

    assert outcome.reason_code == "RISK_ACCOUNTING_UPDATE_FAILED"
    assert _risk_bytes(state_dir) == risk_before
    events = _audit_events(state_dir)
    prepared = [e for e in events if e.event_type == PNL_PREPARED]
    assert len(prepared) == 1 and _origin(prepared[0]) == AUDIT_ORIGIN
    [marker] = _markers(state_dir)
    assert events[-1].event_id == marker.event_id
    assert marker.source == AUDIT_ORIGIN
    assert _origin(marker) == AUDIT_ORIGIN
    assert marker.correlation_id == "s1"
    assert marker.causation_id == prepared[0].event_id
    assert marker.aggregate_type == prepared[0].aggregate_type
    assert marker.aggregate_id == prepared[0].aggregate_id
    assert marker.payload["reason"] == "RISK_ACCOUNTING_UPDATE_FAILED"
    assert marker.payload["request_id"] == "s1"
    assert marker.payload["rolled_back_event_ids"] == [prepared[0].event_id]
    assert marker.payload["rolled_back_event_types"] == [PNL_PREPARED]
    assert marker.payload["risk_accounting_state_restored"] is True


def test_c2_failure_after_booking_marks_both_events_and_rerun_is_unaffected(
    tmp_path, monkeypatch,
):
    expected, _, _ = _baseline(tmp_path, base="100", price="9")
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")

    with monkeypatch.context() as patched:
        patched.setattr(ExecutionTransactionJournal, "mark_committed",
                        lambda self, request_id, result: False)
        outcome = _recover(state_dir)

    assert outcome.reason_code == "RECOVERY_WRITE_FAILED"
    [marker] = _markers(state_dir)
    booked = [e for e in _audit_events(state_dir)
              if e.event_type in {PNL_PREPARED, PNL_COMMITTED}]
    assert marker.payload["rolled_back_event_ids"] == [e.event_id for e in booked]
    assert marker.payload["rolled_back_event_types"] == [PNL_PREPARED, PNL_COMMITTED]
    assert marker.causation_id == booked[-1].event_id
    assert marker.payload["reason"] == "RECOVERY_WRITE_FAILED"
    assert marker.payload["risk_accounting_state_restored"] is True

    # The rerun's classification and booking are exactly as before.
    rerun = _recover(state_dir)
    assert rerun.outcome is ReconciliationOutcome.RECOVERED, rerun
    assert _figures(state_dir) == expected
    assert len(_markers(state_dir)) == 1


def test_c2_verification_failure_marks_with_its_own_reason(tmp_path, monkeypatch):
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    with monkeypatch.context() as patched:
        patched.setattr(reconcile_module, "_verify_recovery",
                        lambda plan, **kwargs: "POST_RECOVERY_VERIFICATION_FAILED")
        outcome = _recover(state_dir)

    assert outcome.reason_code == "POST_RECOVERY_VERIFICATION_FAILED"
    [marker] = _markers(state_dir)
    assert marker.payload["reason"] == "POST_RECOVERY_VERIFICATION_FAILED"


def test_c2_rollback_without_a_booking_writes_no_marker(tmp_path, monkeypatch):
    """A BUY books nothing; a failed BUY recovery has nothing to mark."""
    from tests.test_execution_crash_recovery_f1_f6 import (
        _buy, _crash_on, _fresh_state, _run_until_crash,
    )
    from tests.test_risk_accounting_realized_pnl_wiring import _app as pnl_app

    state_dir = _fresh_state(tmp_path)
    app = pnl_app(state_dir)
    _crash_on(monkeypatch, app.portfolio_foundation.applied_archive, "append", after=True)
    _run_until_crash(app, lambda running: _buy(running, request_id="b1"))
    audit_before = (state_dir / EXECUTION_AUDIT_EVENT_FILE).read_bytes()

    with monkeypatch.context() as patched:
        patched.setattr(ExecutionTransactionJournal, "mark_committed",
                        lambda self, request_id, result: False)
        outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.FAILED
    assert (state_dir / EXECUTION_AUDIT_EVENT_FILE).read_bytes() == audit_before


def test_c2_marker_reports_an_unrestored_risk_state_honestly(tmp_path, monkeypatch):
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    real_restore = reconcile_module._restore

    def restore_all_but_risk(path, original):
        if path.name != RISK_ACCOUNTING_STATE_FILE:
            real_restore(path, original)

    with monkeypatch.context() as patched:
        patched.setattr(reconcile_module, "_restore", restore_all_but_risk)
        patched.setattr(ExecutionTransactionJournal, "mark_committed",
                        lambda self, request_id, result: False)
        _recover(state_dir)

    [marker] = _markers(state_dir)
    assert marker.payload["risk_accounting_state_restored"] is False


def test_c2_marker_write_failure_changes_nothing_else(tmp_path, monkeypatch):
    state_dir = _crashed_sell(tmp_path, monkeypatch, _crash_k2, base="100", price="9")
    risk_before = _risk_bytes(state_dir)
    real_append = AuditEventStore.append

    def failing_marker(self, **kwargs):
        if kwargs.get("event_type") == RECOVERY_BOOKING_ROLLED_BACK:
            raise OSError("audit disk full")
        return real_append(self, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(AuditEventStore, "append", failing_marker)
        patched.setattr(ExecutionTransactionJournal, "mark_committed",
                        lambda self, request_id, result: False)
        outcome = _recover(state_dir)

    assert outcome.outcome is ReconciliationOutcome.FAILED
    assert outcome.reason_code == "RECOVERY_WRITE_FAILED"
    assert _risk_bytes(state_dir) == risk_before
    assert _markers(state_dir) == []


# ===========================================================================
# C3 - rollover refusal audit events
# ===========================================================================


def _refusals(state_dir):
    return [e for e in AuditEventStore(state_dir / EXECUTION_AUDIT_EVENT_FILE).read_all()
            if e.event_type == REFUSED]


def _assert_refusal(event, reason, *, days_ago=1):
    today = _today()
    assert event.source == ExecutionManager.NAME
    assert event.aggregate_type == "risk_accounting_state"
    assert event.aggregate_id == today.isoformat()
    assert event.correlation_id == today.isoformat()
    assert event.payload == {
        "mode": "PAPER",
        "reason": reason,
        "from_accounting_day_utc": (today - timedelta(days=days_ago)).isoformat(),
        "to_accounting_day_utc": today.isoformat(),
    }
    assert event.metadata["mode"] == "PAPER"


def test_c3_unresolved_journal_refusal_is_audited_with_the_warning(tmp_path, caplog):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    assert app.transaction_journal.prepare("pending", {"request_id": "pending"})
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()

    with caplog.at_level("WARNING", logger=execution_manager_module.logger.name):
        result = _risk_check(app)

    assert result["reason"] == STALE_REASON
    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before
    assert any("reason=JOURNAL_UNRESOLVED" in r.getMessage() for r in caplog.records)
    [event] = _refusals(state_dir)
    _assert_refusal(event, "JOURNAL_UNRESOLVED")


def test_c3_orphan_reservation_refusal_is_audited_and_the_rollover_still_follows(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    app.reservation_ledger.reserve("orphan", "orphan", D("100"))

    assert _risk_check(app)["reason"] == STALE_REASON
    [event] = _refusals(state_dir)
    _assert_refusal(event, "ORPHAN_RESERVATION_PRESENT")

    app.execution._release_capital_reservation("orphan")
    assert _risk_check(app, "rc2")["approved"] is True
    assert _stored(state_dir).accounting_day_utc == _today()
    assert len(_refusals(state_dir)) == 1


def test_c3_a_persisting_refusal_is_recorded_once_not_per_request(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    app.reservation_ledger.reserve("orphan", "orphan", D("100"))

    for index in range(5):
        assert _risk_check(app, f"rc{index}")["reason"] == STALE_REASON

    assert len(_refusals(state_dir)) == 1


def test_c3_a_changed_reason_is_recorded_again(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    app.reservation_ledger.reserve("orphan", "orphan", D("100"))
    app.execution._auto_rollover_risk_accounting_day()
    monkeypatch.setattr(app.execution, "portfolio_foundation", None)
    app.execution._release_capital_reservation("orphan")
    app.execution._auto_rollover_risk_accounting_day()

    assert [e.payload["reason"] for e in _refusals(state_dir)] == [
        "ORPHAN_RESERVATION_PRESENT", "EQUITY_AUTHORITY_NOT_READY",
    ]


def test_c3_unverifiable_reservation_state_refusal_is_audited(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)

    def unreadable():
        raise OSError("reservation store unreadable")

    monkeypatch.setattr(app.reservation_ledger, "reserved", unreadable)
    app.execution._auto_rollover_risk_accounting_day()

    [event] = _refusals(state_dir)
    _assert_refusal(event, "RESERVATION_STATE_UNVERIFIABLE")


@pytest.mark.parametrize(("flag", "reason"), [
    ("execution_halted", "EXECUTION_HALTED"),
    ("recovery_required", "RECOVERY_REQUIRED"),
])
def test_c3_halted_runtime_refusal_is_audited(tmp_path, flag, reason):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    setattr(app.execution, flag, True)

    app.execution._auto_rollover_risk_accounting_day()

    assert _stored(state_dir).accounting_day_utc < _today()
    [event] = _refusals(state_dir)
    _assert_refusal(event, reason)


def test_c3_unloaded_journal_refusal_is_audited(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    monkeypatch.setattr(app.transaction_journal, "load_failed", True)

    app.execution._auto_rollover_risk_accounting_day()

    [event] = _refusals(state_dir)
    _assert_refusal(event, "JOURNAL_NOT_LOADED")


def test_c3_equity_authority_not_ready_refusal_is_audited(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    monkeypatch.setattr(app.execution, "portfolio_foundation", None)

    app.execution._auto_rollover_risk_accounting_day()

    [event] = _refusals(state_dir)
    _assert_refusal(event, "EQUITY_AUTHORITY_NOT_READY")


@pytest.mark.parametrize(("equity", "reason"), [
    ("0", "EQUITY_NOT_POSITIVE"), ("-5", "EQUITY_NOT_POSITIVE"),
    ("NaN", "EQUITY_NOT_FINITE"), ("Infinity", "EQUITY_NOT_FINITE"),
])
def test_c3_non_positive_equity_abort_is_audited(tmp_path, monkeypatch, equity, reason, caplog):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    before = (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes()
    foundation = app.portfolio_foundation
    real = foundation.snapshot
    monkeypatch.setattr(foundation, "snapshot", lambda **kw: {**real(**kw), "equity": D(equity)})

    with caplog.at_level("ERROR", logger=execution_manager_module.logger.name):
        app.execution._auto_rollover_risk_accounting_day()

    assert (state_dir / RISK_ACCOUNTING_STATE_FILE).read_bytes() == before
    assert any("aborted before any write" in r.getMessage() for r in caplog.records)
    [event] = _refusals(state_dir)
    _assert_refusal(event, reason)


def test_c3_unreadable_equity_abort_is_audited(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)

    def broken(**kwargs):
        raise RuntimeError("book unreadable")

    monkeypatch.setattr(app.portfolio_foundation, "snapshot", broken)
    app.execution._auto_rollover_risk_accounting_day()

    [event] = _refusals(state_dir)
    _assert_refusal(event, "EQUITY_UNREADABLE")


def test_c3_audit_disabled_refusal_writes_nothing_to_the_disabled_trail(tmp_path, caplog):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    app.execution.audit_enabled = False
    audit_path = state_dir / EXECUTION_AUDIT_EVENT_FILE
    audit_before = audit_path.read_bytes() if audit_path.exists() else None

    with caplog.at_level("WARNING", logger=execution_manager_module.logger.name):
        assert _risk_check(app)["reason"] == STALE_REASON

    assert any("reason=AUDIT_DISABLED" in r.getMessage() for r in caplog.records)
    assert (audit_path.read_bytes() if audit_path.exists() else None) == audit_before


def test_c3_prepared_audit_failure_is_not_reported_as_a_refusal(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    store = app.execution.audit_store
    original = store.append
    attempted = []

    def fail_prepared(**kwargs):
        attempted.append(kwargs["event_type"])
        if kwargs["event_type"] == ExecutionManager.RISK_DAY_ROLLOVER_PREPARED:
            raise OSError("audit disk full")
        return original(**kwargs)

    monkeypatch.setattr(store, "append", fail_prepared)
    app.execution._auto_rollover_risk_accounting_day()

    assert attempted == [ExecutionManager.RISK_DAY_ROLLOVER_PREPARED]
    assert _stored(state_dir).accounting_day_utc < _today()


def test_c3_refusal_audit_failure_keeps_the_refusal_and_degrades_audit(tmp_path, monkeypatch):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    app.reservation_ledger.reserve("orphan", "orphan", D("100"))
    store = app.execution.audit_store
    original = store.append

    def fail_refused(**kwargs):
        if kwargs["event_type"] == REFUSED:
            raise OSError("audit disk full")
        return original(**kwargs)

    monkeypatch.setattr(store, "append", fail_refused)
    failures_before = app.execution.stats["audit_write_failures"]

    # Phase-2 A3: the failed audit write degrades audit persistence inside
    # this very request, so the BUY is now blocked as new risk instead of
    # reaching RiskEngine's stale-day refusal. The day is still not rolled.
    assert _risk_check(app)["reason"] == "AUDIT_PERSISTENCE_DEGRADED"
    assert _stored(state_dir).accounting_day_utc < _today()
    assert app.execution.stats["audit_write_failures"] == failures_before + 1
    assert app.execution.audit_runtime_state == "AUDIT_DEGRADED"
    assert app.execution.last_audit_failure["event_type"] == REFUSED

    # Not marked as recorded, so the next request retries the write.
    monkeypatch.setattr(store, "append", original)
    assert _risk_check(app, "rc2")["reason"] == "AUDIT_PERSISTENCE_DEGRADED"
    [event] = _refusals(state_dir)
    _assert_refusal(event, "ORPHAN_RESERVATION_PRESENT")


def test_c3_missing_journal_lock_is_not_audited(tmp_path, monkeypatch):
    """Detected before the stored day is read, so it is not known to be due."""
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    monkeypatch.setattr(app.transaction_journal, "_lock", None)

    app.execution._auto_rollover_risk_accounting_day()

    assert _refusals(state_dir) == []


def test_c3_no_refusal_event_when_no_rollover_is_due(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    app.execution._auto_rollover_risk_accounting_day()
    assert _stored(state_dir).accounting_day_utc == _today()
    app.execution.execution_halted = True

    app.execution._auto_rollover_risk_accounting_day()

    assert _refusals(state_dir) == []


def test_c3_live_mode_writes_no_refusal(tmp_path):
    state_dir = _stale_state(tmp_path)
    app = _app(state_dir)
    app.execution.mode = ExecutionManager.MODE_LIVE
    app.execution.execution_halted = True

    app.execution._auto_rollover_risk_accounting_day()

    assert _refusals(state_dir) == []
