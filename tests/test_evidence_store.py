"""Evidence Store (ADR-0008): schema, idempotency, immutability, graph.

Every test points the store at pytest's tmp_path. Nothing here touches the
configured durable roots, and no test reads or writes real runtime state.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from data_layer.contracts import IntegrityViolation, MigrationError, StorageError
from data_layer.evidence_store import (
    CLAIM_SCHEMA_VERSION,
    EVIDENCE_MIGRATIONS,
    INACTIVE_STATUSES,
    ClaimSource,
    ClaimStatus,
    EvidenceStore,
    _CLAIM_COLUMNS,
    _STATUS_EXPR,
)


NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def store(tmp_path):
    instance = EvidenceStore(tmp_path / "evidence_store.sqlite3")
    instance.open()
    yield instance
    instance.close()


def _source(retrieved_at: datetime = NOW) -> ClaimSource:
    return ClaimSource(
        source_kind="MARKET_DATA",
        source_uri="market_data://BTCUSDT",
        source_version="1",
        retrieved_at=retrieved_at,
    )


def _record(store: EvidenceStore, **overrides) -> str:
    payload = {
        "claim_text": "BTC volatility regime shifted to HIGH",
        "claim_kind": "REGIME",
        "subject_scope": "SYMBOL",
        "subject_symbol": "BTCUSDT",
        "agent_id": "agent:technical",
        "agent_version": "1",
        "confidence": Decimal("0.80"),
        "asserted_at": NOW,
        "sources": [_source()],
        "payload": {"atr": "3.2"},
        "run_id": "run-1",
    }
    payload.update(overrides)
    return store.record_claim(**payload)


# =====================================================================
# SCHEMA / CONSTRAINT REJECTION
# =====================================================================


def test_confidence_above_one_is_rejected(store):
    with pytest.raises(IntegrityViolation):
        _record(store, confidence=Decimal("1.5"))


def test_confidence_below_zero_is_rejected(store):
    with pytest.raises(IntegrityViolation):
        _record(store, confidence=Decimal("-0.1"))


def test_float_confidence_is_rejected(store):
    """Floats are refused at the boundary, as in decision_intelligence."""

    with pytest.raises(IntegrityViolation):
        _record(store, confidence=0.8)


def test_bool_confidence_is_rejected(store):
    with pytest.raises(IntegrityViolation):
        _record(store, confidence=True)


def test_naive_asserted_at_is_rejected(store):
    with pytest.raises(IntegrityViolation):
        _record(store, asserted_at=datetime(2026, 9, 18, 12, 0, 0))


def test_naive_source_timestamp_is_rejected(store):
    naive = ClaimSource(
        source_kind="MARKET_DATA",
        source_uri="market_data://BTCUSDT",
        source_version="1",
        retrieved_at=datetime(2026, 9, 18, 12, 0, 0),
    )
    with pytest.raises(IntegrityViolation):
        _record(store, sources=[naive])


def test_symbol_scope_requires_a_symbol(store):
    with pytest.raises(IntegrityViolation):
        _record(store, subject_symbol=None)


def test_market_scope_permits_absent_symbol(store):
    claim_id = _record(store, subject_scope="MARKET", subject_symbol=None)
    assert store.get(claim_id).subject_symbol is None


def test_unserialisable_payload_is_rejected(store):
    with pytest.raises(IntegrityViolation):
        _record(store, payload={"bad": {1, 2, 3}})


def test_nan_payload_is_rejected(store):
    with pytest.raises(IntegrityViolation):
        _record(store, payload={"bad": float("nan")})


def test_payload_must_be_a_mapping(store):
    with pytest.raises(IntegrityViolation):
        _record(store, payload=["not", "a", "mapping"])


def test_at_least_one_source_is_required(store):
    with pytest.raises(IntegrityViolation):
        _record(store, sources=[])


def test_model_provider_and_name_must_be_paired(store):
    with pytest.raises(IntegrityViolation):
        _record(store, model_provider="anthropic", model_name=None)
    with pytest.raises(IntegrityViolation):
        _record(store, model_provider=None, model_name="claude-opus-5")


def test_invalid_claim_kind_is_rejected(store):
    with pytest.raises(IntegrityViolation):
        _record(store, claim_kind="NOT_A_KIND")


def test_blank_agent_id_is_rejected(store):
    with pytest.raises(IntegrityViolation):
        _record(store, agent_id="   ")


def test_observation_window_must_not_invert(store):
    with pytest.raises((IntegrityViolation, StorageError)):
        _record(
            store,
            observation_start=NOW,
            observation_end=NOW - timedelta(hours=1),
        )


def test_self_relation_is_rejected(store):
    claim_id = _record(store)
    with pytest.raises(IntegrityViolation):
        store.link(
            from_claim_id=claim_id,
            to_claim_id=claim_id,
            relation_kind="CONTRADICTS",
            created_by="test",
        )


def test_relation_to_unknown_claim_is_rejected(store):
    claim_id = _record(store)
    with pytest.raises(IntegrityViolation):
        store.link(
            from_claim_id=claim_id,
            to_claim_id="does-not-exist",
            relation_kind="SUPPORTS",
            created_by="test",
        )


def test_duplicate_relation_is_idempotent_not_doubled(store):
    first = _record(store)
    second = _record(store, agent_id="agent:macro")
    store.link(
        from_claim_id=first,
        to_claim_id=second,
        relation_kind="SUPPORTS",
        created_by="test",
    )
    store.link(
        from_claim_id=first,
        to_claim_id=second,
        relation_kind="SUPPORTS",
        created_by="test",
    )
    assert store.health()["relation_count"] == 1


def test_status_transition_on_unknown_claim_is_rejected(store):
    with pytest.raises(IntegrityViolation):
        store.set_status(
            "nope", "RETRACTED", reason="r", decided_by="system"
        )


# =====================================================================
# IDEMPOTENCY
# =====================================================================


def test_identical_claim_recorded_twice_yields_one_row(store):
    first = _record(store)
    second = _record(store)
    assert first == second
    assert store.health()["claim_count"] == 1
    assert store.health()["claims_deduplicated"] == 1


def test_idempotency_does_not_duplicate_sources(store):
    _record(store)
    _record(store)
    claim_id = _record(store)
    assert len(store.sources_for(claim_id)) == 1


def test_changed_payload_is_a_distinct_claim(store):
    first = _record(store)
    second = _record(store, payload={"atr": "9.9"})
    assert first != second
    assert store.health()["claim_count"] == 2


def test_idempotency_holds_for_symbolless_claims(store):
    """The unique index spans a NULL symbol, which SQL equality does not."""

    first = _record(store, subject_scope="MARKET", subject_symbol=None)
    second = _record(store, subject_scope="MARKET", subject_symbol=None)
    assert first == second
    assert store.health()["claim_count"] == 1


# =====================================================================
# IMMUTABILITY / LIFECYCLE
# =====================================================================


def test_status_history_is_append_only(store):
    claim_id = _record(store)
    assert store.set_status(
        claim_id, "PARTIALLY_SUPPORTED", reason="mixed", decided_by="system"
    ) == 1
    assert store.set_status(
        claim_id, "CONTRADICTED", reason="counter", decided_by="system"
    ) == 2

    connection = sqlite3.connect(store.database_path)
    try:
        rows = connection.execute(
            "SELECT sequence, status FROM claim_status_history "
            "WHERE claim_id = ? ORDER BY sequence",
            (claim_id,),
        ).fetchall()
    finally:
        connection.close()

    assert rows == [(1, "PARTIALLY_SUPPORTED"), (2, "CONTRADICTED")]


def test_current_status_reflects_latest_sequence(store):
    claim_id = _record(store)
    store.set_status(claim_id, "PARTIALLY_SUPPORTED", reason="a", decided_by="s")
    store.set_status(claim_id, "SUPERSEDED", reason="b", decided_by="s")
    assert store.get(claim_id).status == "SUPERSEDED"


def test_claim_without_history_reads_as_active(store):
    claim_id = _record(store)
    assert store.get(claim_id).status == ClaimStatus.ACTIVE.value


def test_current_status_view_agrees_with_library(store):
    claim_id = _record(store)
    store.set_status(claim_id, "EXPIRED", reason="old", decided_by="s")
    connection = sqlite3.connect(store.database_path)
    try:
        row = connection.execute(
            "SELECT status FROM claim_current_status WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row[0] == "EXPIRED" == store.get(claim_id).status


def test_no_update_statement_targets_claims():
    """The store never rewrites a claim; history is the only mutation."""

    source = (
        __import__("pathlib").Path("data_layer/evidence_store.py")
        .read_text(encoding="utf-8")
        .upper()
    )
    assert "UPDATE CLAIMS" not in source
    assert "UPDATE CLAIM_SOURCES" not in source
    assert "UPDATE CLAIM_RELATIONS" not in source
    assert "UPDATE CLAIM_STATUS_HISTORY" not in source


# =====================================================================
# COUNTER-EVIDENCE GRAPH
# =====================================================================


def test_contradicts_is_readable_from_both_directions(store):
    first = _record(store)
    second = _record(store, agent_id="agent:macro", payload={"atr": "1.0"})
    store.link(
        from_claim_id=second,
        to_claim_id=first,
        relation_kind="CONTRADICTS",
        created_by="test",
    )
    assert [c.claim_id for c in store.counter_evidence(first)] == [second]
    assert [c.claim_id for c in store.counter_evidence(second)] == [first]


def test_supersedes_is_directional_only(store):
    first = _record(store)
    second = _record(store, agent_id="agent:macro", payload={"atr": "1.0"})
    store.link(
        from_claim_id=second,
        to_claim_id=first,
        relation_kind="SUPERSEDES",
        created_by="test",
    )
    assert store.health()["relation_count"] == 1


def test_retracted_counter_evidence_is_excluded_by_default(store):
    subject = _record(store)
    against = _record(store, agent_id="agent:macro", payload={"atr": "1.0"})
    store.link(
        from_claim_id=against,
        to_claim_id=subject,
        relation_kind="CONTRADICTS",
        created_by="test",
    )
    store.set_status(against, "RETRACTED", reason="bad data", decided_by="s")

    assert store.counter_evidence(subject) == []
    assert [
        c.claim_id for c in store.counter_evidence(subject, include_inactive=True)
    ] == [against]


def test_superseded_counter_evidence_is_excluded_by_default(store):
    subject = _record(store)
    against = _record(store, agent_id="agent:macro", payload={"atr": "1.0"})
    store.link(
        from_claim_id=against,
        to_claim_id=subject,
        relation_kind="CONTRADICTS",
        created_by="test",
    )
    store.set_status(against, "SUPERSEDED", reason="newer", decided_by="s")
    assert store.counter_evidence(subject) == []


def test_counter_evidence_is_ordered_by_confidence(store):
    subject = _record(store)
    weak = _record(
        store, agent_id="agent:macro", confidence=Decimal("0.2"), payload={"a": 1}
    )
    strong = _record(
        store, agent_id="agent:risk", confidence=Decimal("0.9"), payload={"a": 2}
    )
    for other in (weak, strong):
        store.link(
            from_claim_id=other,
            to_claim_id=subject,
            relation_kind="CONTRADICTS",
            created_by="test",
        )
    assert [c.claim_id for c in store.counter_evidence(subject)] == [strong, weak]


def test_supporting_and_precedent_edges_are_separate(store):
    subject = _record(store)
    supporter = _record(store, agent_id="agent:macro", payload={"a": 1})
    precedent = _record(store, agent_id="agent:memory", payload={"a": 2})
    store.link(
        from_claim_id=supporter,
        to_claim_id=subject,
        relation_kind="SUPPORTS",
        created_by="test",
    )
    store.link(
        from_claim_id=precedent,
        to_claim_id=subject,
        relation_kind="PRECEDENT_OF",
        created_by="test",
    )
    assert [c.claim_id for c in store.supporting_evidence(subject)] == [supporter]
    assert [c.claim_id for c in store.precedents(subject)] == [precedent]
    assert store.counter_evidence(subject) == []


def test_counter_evidence_query_uses_the_index_and_never_scans(store):
    """The traversal must be an index seek, not a table scan."""

    subject = _record(store)
    against = _record(store, agent_id="agent:macro", payload={"a": 1})
    store.link(
        from_claim_id=against,
        to_claim_id=subject,
        relation_kind="CONTRADICTS",
        created_by="test",
    )

    placeholders = ",".join("?" for _ in INACTIVE_STATUSES)
    sql = (
        f"SELECT {_CLAIM_COLUMNS}, {_STATUS_EXPR} AS status "
        f"FROM claim_relations r "
        f"JOIN claims c ON c.claim_id = r.from_claim_id "
        f"WHERE r.to_claim_id = ? AND r.relation_kind = ? "
        f"AND {_STATUS_EXPR} NOT IN ({placeholders}) "
        f"ORDER BY CAST(c.confidence_text AS REAL) DESC, c.claim_id"
    )

    connection = sqlite3.connect(store.database_path)
    try:
        plan = [
            row[-1]
            for row in connection.execute(
                "EXPLAIN QUERY PLAN " + sql,
                (subject, "CONTRADICTS", *INACTIVE_STATUSES),
            )
        ]
    finally:
        connection.close()

    assert any("idx_relations_to" in step for step in plan), plan
    # A SCAN of any evidence table would mean the view/join regressed into
    # a full materialisation, which is what makes this store viable at
    # millions of rows rather than thousands.
    assert not any(step.startswith("SCAN") for step in plan), plan


# =====================================================================
# QUERY
# =====================================================================


def test_query_filters_by_symbol_agent_kind_and_time(store):
    _record(store)
    _record(store, subject_symbol="ETHUSDT", payload={"a": 1})
    _record(store, agent_id="agent:macro", payload={"a": 2})

    assert len(store.query(symbol="BTCUSDT")) == 2
    assert len(store.query(agent_id="agent:macro")) == 1
    assert len(store.query(claim_kind="REGIME")) == 3
    assert len(store.query(claim_kind="ANOMALY")) == 0
    assert len(store.query(since=NOW + timedelta(seconds=1))) == 0
    assert len(store.query(until=NOW)) == 3


def test_query_filters_by_status_and_confidence(store):
    keep = _record(store, confidence=Decimal("0.9"))
    drop = _record(store, agent_id="agent:macro", confidence=Decimal("0.1"))
    store.set_status(drop, "RETRACTED", reason="x", decided_by="s")

    assert [c.claim_id for c in store.query(min_confidence=Decimal("0.5"))] == [keep]
    assert [c.claim_id for c in store.query(statuses=["ACTIVE"])] == [keep]
    assert [c.claim_id for c in store.query(statuses=["RETRACTED"])] == [drop]


def test_round_trip_preserves_decimal_and_payload(store):
    claim_id = _record(
        store,
        confidence=Decimal("0.123456"),
        payload={"nested": {"k": "v"}, "n": 3},
        reason_codes=["A", "B"],
    )
    record = store.get(claim_id)
    assert record.confidence == Decimal("0.123456")
    assert isinstance(record.confidence, Decimal)
    assert record.payload == {"nested": {"k": "v"}, "n": 3}
    assert record.reason_codes == ("A", "B")
    assert record.schema_version == CLAIM_SCHEMA_VERSION


def test_get_returns_none_for_unknown_claim(store):
    assert store.get("missing") is None


# =====================================================================
# MIGRATIONS
# =====================================================================


def test_fresh_bootstrap_creates_schema(tmp_path):
    store = EvidenceStore(tmp_path / "evidence_store.sqlite3")
    store.open()
    connection = sqlite3.connect(store.database_path)
    try:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view','index')"
            )
        }
    finally:
        connection.close()
    for expected in (
        "claims",
        "claim_sources",
        "claim_relations",
        "claim_status_history",
        "claim_current_status",
        "idx_claims_idem",
        "idx_relations_to",
        "idx_relations_from",
        "idx_claims_symbol_time",
        "idx_claims_agent_time",
        "idx_claims_kind_time",
        "idx_sources_claim",
    ):
        assert expected in names


def test_reopen_is_a_no_op(tmp_path):
    path = tmp_path / "evidence_store.sqlite3"
    first = EvidenceStore(path)
    first.open()
    claim_id = _record(first)
    first.close()

    second = EvidenceStore(path)
    second.open()
    assert second.get(claim_id) is not None
    assert second.health()["schema_version"] == 1


def test_wal_mode_is_enabled(tmp_path):
    store = EvidenceStore(tmp_path / "evidence_store.sqlite3")
    store.open()
    connection = sqlite3.connect(store.database_path)
    try:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()
    assert mode.lower() == "wal"


def test_tampered_migration_checksum_raises(tmp_path):
    path = tmp_path / "evidence_store.sqlite3"
    EvidenceStore(path).open()

    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE atlas_schema_migrations SET checksum_sha256 = ? "
            "WHERE migration_id = 1",
            ("0" * 64,),
        )
        connection.commit()
    finally:
        connection.close()

    # MigrationError is a StorageError subclass and is surfaced directly
    # rather than wrapped, so the operator sees the precise cause.
    with pytest.raises(MigrationError):
        EvidenceStore(path).open()


def test_migration_sequence_is_contiguous_and_checksummed():
    ids = [m.migration_id for m in EVIDENCE_MIGRATIONS]
    assert ids == list(range(1, len(ids) + 1))
    for migration in EVIDENCE_MIGRATIONS:
        assert len(migration.checksum) == 64


# =====================================================================
# LIFECYCLE / FAILURE
# =====================================================================


def test_operations_before_open_raise_storage_error(tmp_path):
    store = EvidenceStore(tmp_path / "evidence_store.sqlite3")
    with pytest.raises(StorageError):
        _record(store)


def test_health_is_safe_on_an_unopened_store(tmp_path):
    store = EvidenceStore(tmp_path / "evidence_store.sqlite3")
    report = store.health()
    assert report["opened"] is False
    assert report["claim_count"] is None


def test_open_never_creates_the_evidence_directory(tmp_path):
    """A missing evidence root must fail, not be silently provisioned."""

    missing = tmp_path / "not_created_by_atlas"
    store = EvidenceStore(missing / "evidence_store.sqlite3")

    with pytest.raises(StorageError):
        store.open()

    assert not missing.exists()
    assert store.opened is False


def test_open_on_an_unusable_path_raises_storage_error(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    store = EvidenceStore(blocker / "evidence_store.sqlite3")
    with pytest.raises(StorageError):
        store.open()
    assert store.opened is False
    assert store.health()["last_error"] is not None


def test_record_write_failure_is_visible_in_health(tmp_path):
    store = EvidenceStore(tmp_path / "evidence_store.sqlite3")
    store.record_write_failure(RuntimeError("boom"))
    report = store.health()
    assert report["write_failures"] == 1
    assert "boom" in report["last_error"]


# =====================================================================
# CONCURRENCY
# =====================================================================


def test_concurrent_readers_during_writes_do_not_error(store):
    _record(store)
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        try:
            while not stop.is_set():
                store.query(limit=50)
        except BaseException as exc:  # noqa: BLE001 - recorded and asserted
            errors.append(exc)

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for thread in readers:
        thread.start()
    try:
        for index in range(40):
            _record(store, payload={"n": index}, agent_id=f"agent:w{index % 3}")
    finally:
        stop.set()
        for thread in readers:
            thread.join(timeout=10)

    assert errors == []
    assert store.health()["claim_count"] == 41


def test_relations_written_counter_excludes_ignored_duplicates(store):
    """health() must not overcount an idempotent re-link."""

    first = _record(store)
    second = _record(store, agent_id="agent:macro", payload={"a": 1})

    store.link(
        from_claim_id=first,
        to_claim_id=second,
        relation_kind="CONTRADICTS",
        created_by="test",
    )
    assert store.health()["relations_written"] == 2  # symmetric pair

    store.link(
        from_claim_id=first,
        to_claim_id=second,
        relation_kind="CONTRADICTS",
        created_by="test",
    )
    assert store.health()["relations_written"] == 2
    assert store.health()["relation_count"] == 2
