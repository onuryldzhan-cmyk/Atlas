"""Acceptance tests for Knowledge Manager v1 (GRANT-KNOWLEDGE-MANAGER-V1-RESEARCH-ONLY, v5.87).

Each test names the v5.87 rule it pins (C-1 lineage, D1-D5, the
``p4_5_invariants_added_v5_87`` list). Keys here are fixed, obviously fake
test bytes: no real owner key appears in tests or in the repository.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

import pytest

from research.knowledge_manager import (
    OWNER,
    SIG_FIELD,
    ClaimStatus,
    ClaimView,
    IllegalKnowledgeTransitionError,
    KnowledgeInputError,
    KnowledgeIntegrityError,
    KnowledgeManager,
    KnowledgeManagerHalted,
    OwnerKeyError,
    SignatureState,
    _sha256,
    key_fingerprint,
    signing_body,
)

TEST_OWNER_KEY = b"TEST-ONLY-fake-owner-key-not-real-0123456789"
OTHER_KEY = b"TEST-ONLY-another-fake-key-not-real-9876543210"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64

RANK = {
    ClaimStatus.UNKNOWN: 0,
    ClaimStatus.CONTESTED: 1,
    ClaimStatus.UNVALIDATED: 1,
    ClaimStatus.VALIDATED: 2,
    ClaimStatus.AUTHORITATIVE: 3,
}


@pytest.fixture
def km() -> KnowledgeManager:
    return KnowledgeManager(owner_key_fingerprint=key_fingerprint(TEST_OWNER_KEY))


def _source(km, uri="archive://btcusdt/1h/2026-09") -> str:
    return km.register_source(kind="MARKET_ARCHIVE", uri=uri, retrieved_at="2026-10-01T00:00:00+00:00")


def _claim(km, author="research_agent") -> tuple[str, str]:
    src = _source(km)
    return km.register_claim(statement="BTC 1h momentum has no edge after fees",
                             author=author, source_ids=(src,)), src


def _support(km, cid, src, digest=DIGEST_A, submitter="research_agent", note="backtest report"):
    return km.add_evidence(claim_id=cid, stance="SUPPORTS", source_id=src,
                           submitter=submitter, description=note, content_digest=digest)


def _contradict(km, cid, src, digest=DIGEST_B, submitter="scout", note="counter study"):
    return km.add_evidence(claim_id=cid, stance="CONTRADICTS", source_id=src,
                           submitter=submitter, description=note, content_digest=digest)


def _validated(km):
    cid, src = _claim(km)
    ev = _support(km, cid, src)
    km.record_validation(claim_id=cid, validator="validator_agent")
    assert km.status(cid) is ClaimStatus.VALIDATED
    return cid, src, ev


def _authoritative(km):
    cid, src, ev = _validated(km)
    km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY)
    assert km.status(cid, owner_key=TEST_OWNER_KEY) is ClaimStatus.AUTHORITATIVE
    return cid, src, ev


# -- C-1 lineage: SOURCE -> CLAIM -> EVIDENCE -> VALIDATION -> VALIDATED ------


def test_unknown_claim_is_shown_as_unknown_never_invented(km):
    view = km.claim_view("f" * 64)
    assert view.status is ClaimStatus.UNKNOWN and view.reasons == ("CLAIM_NOT_REGISTERED",)
    assert view.verifiable_supporting == 0 and view.owner_signature is SignatureState.ABSENT


def test_malformed_claim_id_is_refused_not_guessed(km):
    with pytest.raises(KnowledgeInputError):
        km.claim_view("not-a-hash")
    assert not km.halted


def test_every_claim_is_linked_to_a_registered_source(km):
    with pytest.raises(KnowledgeInputError):
        km.register_claim(statement="x", author="a", source_ids=())
    with pytest.raises(KnowledgeInputError):
        km.register_claim(statement="x", author="a", source_ids=("e" * 64,))
    assert km.log == ()


@pytest.mark.parametrize("source_ids", [123, 1.5, object(), None, "a" * 64, {"a" * 64}])
def test_malformed_source_ids_are_refused_without_halting(km, source_ids):
    """Audit KM-A1: a non-iterable used to raise TypeError and halt the manager."""
    with pytest.raises(KnowledgeInputError):
        km.register_claim(statement="x", author="a", source_ids=source_ids)
    assert not km.halted and km.log == ()


def test_claim_without_evidence_is_unknown(km):
    cid, _ = _claim(km)
    view = km.claim_view(cid)
    assert view.status is ClaimStatus.UNKNOWN and view.reasons == ("NO_ACTIVE_EVIDENCE",)


def test_evidence_needs_a_registered_claim_and_source(km):
    cid, src = _claim(km)
    with pytest.raises(KnowledgeInputError):
        _support(km, "e" * 64, src)
    with pytest.raises(KnowledgeInputError):
        _support(km, cid, "e" * 64)


@pytest.mark.parametrize("bad", [
    {"stance": "MAYBE"}, {"content_digest": "abc"}, {"description": ""},
    {"submitter": "has space"}, {"submitter": ""},
])
def test_malformed_evidence_is_refused_without_writing_or_halting(km, bad):
    cid, src = _claim(km)
    before = len(km.log)
    fields = dict(claim_id=cid, stance="SUPPORTS", source_id=src, submitter="s",
                  description="d", content_digest=DIGEST_A)
    with pytest.raises(KnowledgeInputError):
        km.add_evidence(**{**fields, **bad})
    assert len(km.log) == before and not km.halted


@pytest.mark.parametrize("retrieved_at", ["2026-10-01T00:00:00", "yesterday", 5])
def test_source_timestamps_must_be_timezone_aware(km, retrieved_at):
    with pytest.raises(KnowledgeInputError):
        km.register_source(kind="NEWS", uri="news://x", retrieved_at=retrieved_at)


def test_lineage_reaches_validated(km):
    cid, src = _claim(km)
    _support(km, cid, src)
    assert km.status(cid) is ClaimStatus.UNVALIDATED
    km.record_validation(claim_id=cid, validator="validator_agent")
    view = km.claim_view(cid)
    assert view.status is ClaimStatus.VALIDATED and view.owner_signature is SignatureState.ABSENT
    assert view.reasons == ("VALIDATED_NOT_OWNER_SIGNED",)


def test_registration_is_idempotent(km):
    src = _source(km)
    assert _source(km) == src
    cid, _ = _claim(km)
    ev = _support(km, cid, src)
    before = len(km.log)
    assert _claim(km)[0] == cid and _support(km, cid, src) == ev
    assert len(km.log) == before


# -- D5: at least one verifiable supporting evidence item ------------------


def test_unverifiable_support_alone_cannot_be_validated(km):
    cid, src = _claim(km)
    _support(km, cid, src, digest=None)
    view = km.claim_view(cid)
    assert view.status is ClaimStatus.UNVALIDATED and view.unverifiable_supporting == 1
    with pytest.raises(IllegalKnowledgeTransitionError):
        km.record_validation(claim_id=cid, validator="validator_agent")


def test_one_verifiable_item_suffices_multiple_sources_not_required(km):
    _validated(km)  # single source, single verifiable item: explicit v1 boundary


# -- D3: validator != author, owner never validates ------------------------


@pytest.mark.parametrize("validator", ["research_agent", "Research_Agent", "RESEARCH_AGENT"])
def test_validator_must_differ_from_author(km, validator):
    cid, src = _claim(km, author="research_agent")
    _support(km, cid, src)
    with pytest.raises(IllegalKnowledgeTransitionError):
        km.record_validation(claim_id=cid, validator=validator)
    assert km.status(cid) is ClaimStatus.UNVALIDATED


@pytest.mark.parametrize("validator", ["owner", "Owner", "OWNER"])
def test_owner_is_never_a_validator(km, validator):
    cid, src = _claim(km)
    _support(km, cid, src)
    with pytest.raises(IllegalKnowledgeTransitionError):
        km.record_validation(claim_id=cid, validator=validator)


def test_validation_and_signature_are_separate_lanes(km):
    """Validation needs no key; a signature never stands in for a validation."""
    cid, src = _claim(km)
    _support(km, cid, src)
    with pytest.raises(IllegalKnowledgeTransitionError):
        km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY)
    assert km.status(cid, owner_key=TEST_OWNER_KEY) is ClaimStatus.UNVALIDATED


# -- D2: CONTESTED --------------------------------------------------------


def test_contradiction_makes_contested_and_blocks_validation(km):
    cid, src = _claim(km)
    _support(km, cid, src)
    _contradict(km, cid, src)
    assert km.status(cid) is ClaimStatus.CONTESTED
    with pytest.raises(IllegalKnowledgeTransitionError):
        km.record_validation(claim_id=cid, validator="validator_agent")


def test_unverifiable_contradiction_still_blocks(km):
    cid, src = _claim(km)
    _support(km, cid, src)
    _contradict(km, cid, src, digest=None)
    assert km.status(cid) is ClaimStatus.CONTESTED


def test_contradiction_after_validation_and_signature_blocks_both(km):
    cid, src, _ = _authoritative(km)
    _contradict(km, cid, src)
    view = km.claim_view(cid, owner_key=TEST_OWNER_KEY)
    assert view.status is ClaimStatus.CONTESTED
    assert view.owner_signature is SignatureState.ABSENT
    with pytest.raises(IllegalKnowledgeTransitionError):
        km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY)


def test_withdrawing_counter_evidence_needs_a_new_validation(km):
    cid, src, _ = _validated(km)
    counter = _contradict(km, cid, src)
    km.withdraw_evidence(evidence_id=counter, actor="scout", reason="wrong symbol in the study")
    view = km.claim_view(cid)
    assert view.status is ClaimStatus.UNVALIDATED
    assert view.reasons == ("VALIDATION_STALE_EVIDENCE_CHANGED",)
    km.record_validation(claim_id=cid, validator="validator_agent")
    assert km.status(cid) is ClaimStatus.VALIDATED


# -- D4: withdrawal -------------------------------------------------------


def test_only_submitter_or_owner_may_withdraw(km):
    cid, src = _claim(km)
    ev = _support(km, cid, src, submitter="research_agent")
    with pytest.raises(IllegalKnowledgeTransitionError):
        km.withdraw_evidence(evidence_id=ev, actor="someone_else", reason="r")
    km.withdraw_evidence(evidence_id=ev, actor="Research_Agent", reason="data error")
    with pytest.raises(IllegalKnowledgeTransitionError):
        km.withdraw_evidence(evidence_id=ev, actor="research_agent", reason="again")


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_withdrawal_needs_a_non_empty_reason(km, reason):
    cid, src = _claim(km)
    ev = _support(km, cid, src)
    with pytest.raises(KnowledgeInputError):
        km.withdraw_evidence(evidence_id=ev, actor="research_agent", reason=reason)


def test_owner_withdrawal_requires_the_pinned_owner_key(km):
    cid, src = _claim(km)
    ev = _contradict(km, cid, src)
    for key in (None, OTHER_KEY, b"short"):
        with pytest.raises(OwnerKeyError):
            km.withdraw_evidence(evidence_id=ev, actor="owner", reason="r", owner_key=key)
    assert km.status(cid) is ClaimStatus.CONTESTED  # impersonating the owner changed nothing
    entry = km.withdraw_evidence(evidence_id=ev, actor="OWNER", reason="retracted source",
                                 owner_key=TEST_OWNER_KEY)
    assert entry.payload["actor"] == OWNER


def test_withdrawal_changes_the_evidence_set_hash_and_invalidates_the_basis(km):
    cid, src, ev = _authoritative(km)
    extra = _support(km, cid, src, digest=DIGEST_C, note="second report")
    km.record_validation(claim_id=cid, validator="validator_agent")
    km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY)
    before = km.claim_view(cid, owner_key=TEST_OWNER_KEY)
    assert before.status is ClaimStatus.AUTHORITATIVE
    km.withdraw_evidence(evidence_id=extra, actor="research_agent", reason="duplicate run")
    after = km.claim_view(cid, owner_key=TEST_OWNER_KEY)
    assert after.evidence_set_hash != before.evidence_set_hash
    assert after.status is ClaimStatus.UNVALIDATED and after.withdrawn == 1


def test_withdrawn_evidence_cannot_be_resurrected_by_re_adding_it(km):
    cid, src = _claim(km)
    ev = _support(km, cid, src)
    km.withdraw_evidence(evidence_id=ev, actor="research_agent", reason="bad data")
    assert _support(km, cid, src) == ev  # idempotent: the same withdrawn item
    assert km.status(cid) is ClaimStatus.UNKNOWN
    assert [e.payload["evidence_id"] for e in km.evidence_for(cid)] == [ev]  # provenance kept


# -- C-1 / D1: owner signature only after VALIDATED, only yields AUTHORITATIVE --


def test_owner_signature_yields_authoritative_only_with_the_verified_key(km):
    cid, _, _ = _authoritative(km)
    unverified = km.claim_view(cid)
    assert unverified.status is ClaimStatus.VALIDATED
    assert unverified.owner_signature is SignatureState.UNVERIFIED
    with pytest.raises(OwnerKeyError):
        km.claim_view(cid, owner_key=OTHER_KEY)


@pytest.mark.parametrize("setup", ["unknown", "unvalidated", "contested"])
def test_signature_is_refused_before_validated_and_never_promotes(km, setup):
    cid, src = _claim(km)
    if setup != "unknown":
        _support(km, cid, src)
    if setup == "contested":
        _contradict(km, cid, src)
    before = km.status(cid, owner_key=TEST_OWNER_KEY)
    log_before = len(km.log)
    with pytest.raises(IllegalKnowledgeTransitionError):
        km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY)
    assert km.status(cid, owner_key=TEST_OWNER_KEY) is before
    assert len(km.log) == log_before


def test_no_pinned_key_means_never_authoritative():
    km = KnowledgeManager()
    cid, src = _claim(km)
    _support(km, cid, src)
    km.record_validation(claim_id=cid, validator="validator_agent")
    with pytest.raises(OwnerKeyError):
        km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY)
    with pytest.raises(OwnerKeyError):
        km.claim_view(cid, owner_key=TEST_OWNER_KEY)
    assert km.status(cid) is ClaimStatus.VALIDATED


@pytest.mark.parametrize("key", [OTHER_KEY, b"short", "TEST-ONLY-string-not-bytes-0123456789", None])
def test_a_wrong_or_short_key_cannot_sign(km, key):
    cid, _, _ = _validated(km)
    before = len(km.log)
    with pytest.raises(OwnerKeyError):
        km.owner_sign(claim_id=cid, owner_key=key)
    assert len(km.log) == before


def test_owner_signature_bytes_match_atlas_org_owner_auth(km):
    """D1: byte-compatible with the existing signer, which this module never imports."""
    from atlas_org import owner_auth

    cid, _, _ = _authoritative(km)
    entry = [e for e in km.log if e.kind == "OWNER_SIGNED"][-1]
    event = dict(entry.as_dict()["payload"])
    assert signing_body(event) == owner_auth.signing_body(event)
    assert event[SIG_FIELD] == owner_auth.sign(TEST_OWNER_KEY, event)
    assert owner_auth.check(event, TEST_OWNER_KEY) is True
    assert owner_auth.check(event, None) is None  # the shared "unverified, never verified" rule


def test_signing_is_idempotent(km):
    cid, _, _ = _authoritative(km)
    before = len(km.log)
    km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY)
    assert len(km.log) == before


def test_new_evidence_after_signing_requires_revalidation_and_resigning(km):
    cid, src, _ = _authoritative(km)
    _support(km, cid, src, digest=DIGEST_C, note="later report")
    assert km.status(cid, owner_key=TEST_OWNER_KEY) is ClaimStatus.UNVALIDATED
    km.record_validation(claim_id=cid, validator="validator_agent")
    assert km.status(cid, owner_key=TEST_OWNER_KEY) is ClaimStatus.VALIDATED
    km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY)
    assert km.status(cid, owner_key=TEST_OWNER_KEY) is ClaimStatus.AUTHORITATIVE


def test_a_second_validator_does_not_orphan_the_signature(km):
    cid, _, _ = _authoritative(km)
    km.record_validation(claim_id=cid, validator="second_validator")
    assert km.status(cid, owner_key=TEST_OWNER_KEY) is ClaimStatus.AUTHORITATIVE


def test_forged_signature_halts_when_verified(km):
    cid, _, _ = _authoritative(km)
    index = max(i for i, e in enumerate(km._log) if e.kind == "OWNER_SIGNED")
    entry = km._log[index]
    payload = {**entry.as_dict()["payload"], SIG_FIELD: "0" * 64}
    forged = replace(entry, payload=payload)
    # In-process rehash of the (unkeyed) chain: the chain check passes, so only
    # the HMAC under the pinned key can catch the forgery.
    km._log[index] = replace(forged, entry_hash=_sha256(forged.hashed_body()))
    with pytest.raises(KnowledgeIntegrityError):
        km.claim_view(cid, owner_key=TEST_OWNER_KEY)
    assert km.halted


# -- NB-4 / NB-5: absent or unverifiable evidence never raises status -------


def _snapshot_states(km_factory):
    """Every single withdrawal and every unverifiable addition, from every rich state."""
    outcomes = []
    for state in ("validated", "authoritative", "unvalidated"):
        for action in ("withdraw_support", "withdraw_counter", "add_unverifiable_support",
                       "add_unverifiable_counter"):
            km = km_factory()
            cid, src = _claim(km)
            sup = _support(km, cid, src)
            counter = _contradict(km, cid, src, submitter="scout")
            km.withdraw_evidence(evidence_id=counter, actor="scout", reason="initial withdrawal")
            if state in ("validated", "authoritative"):
                km.record_validation(claim_id=cid, validator="validator_agent")
            if state == "authoritative":
                km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY)
            live_counter = _contradict(km, cid, src, digest=DIGEST_C, submitter="scout")
            km.withdraw_evidence(evidence_id=live_counter, actor="scout", reason="setup")
            if state in ("validated", "authoritative"):
                km.record_validation(claim_id=cid, validator="validator_agent")
            if state == "authoritative":
                km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY)
            before = km.status(cid, owner_key=TEST_OWNER_KEY)
            if action == "withdraw_support":
                km.withdraw_evidence(evidence_id=sup, actor="research_agent", reason="r")
            elif action == "withdraw_counter":
                extra = _contradict(km, cid, src, digest="d" * 64, submitter="scout")
                before = km.status(cid, owner_key=TEST_OWNER_KEY)
                km.withdraw_evidence(evidence_id=extra, actor="scout", reason="r")
            elif action == "add_unverifiable_support":
                _support(km, cid, src, digest=None, note="hearsay")
            else:
                _contradict(km, cid, src, digest=None, note="rumour")
            outcomes.append((state, action, before, km.status(cid, owner_key=TEST_OWNER_KEY)))
    return outcomes


def test_nb4_removing_or_adding_unverifiable_evidence_never_raises_status():
    outcomes = _snapshot_states(
        lambda: KnowledgeManager(owner_key_fingerprint=key_fingerprint(TEST_OWNER_KEY)))
    assert len(outcomes) == 12
    for state, action, before, after in outcomes:
        assert RANK[after] <= RANK[before], (state, action, before, after)
        assert after not in (ClaimStatus.VALIDATED, ClaimStatus.AUTHORITATIVE), (state, action, after)


def test_nb5_counts_use_every_recorded_item_and_report_withdrawals(km):
    cid, src = _claim(km)
    _support(km, cid, src)
    _support(km, cid, src, digest=None, note="unverified note")
    gone = _support(km, cid, src, digest=DIGEST_C, note="retracted")
    km.withdraw_evidence(evidence_id=gone, actor="research_agent", reason="r")
    view = km.claim_view(cid)
    assert (view.verifiable_supporting, view.unverifiable_supporting, view.withdrawn) == (1, 1, 1)
    assert len(km.evidence_for(cid)) == 3


# -- tamper-safe reads and fail-safe halt (same contract as Experiment Manager) --


def test_returned_payloads_are_immutable(km):
    cid, _, _ = _authoritative(km)
    with pytest.raises(TypeError):
        km.log[-1].payload[SIG_FIELD] = "f" * 64
    with pytest.raises(TypeError):
        km.evidence_for(cid)[0].payload["content_digest"] = None
    with pytest.raises(dataclasses.FrozenInstanceError):
        km.claim_view(cid).status = ClaimStatus.AUTHORITATIVE  # type: ignore[misc]
    assert km.status(cid, owner_key=TEST_OWNER_KEY) is ClaimStatus.AUTHORITATIVE
    assert not km.halted


@pytest.mark.parametrize("read", ["log", "claim_view", "status", "evidence_for"])
def test_every_public_read_verifies_the_chain_and_halts(read):
    km = KnowledgeManager(owner_key_fingerprint=key_fingerprint(TEST_OWNER_KEY))
    cid, _, _ = _validated(km)
    entry = km._log[-1]
    km._log[-1] = replace(entry, payload={**entry.as_dict()["payload"], "validator": "forged"})
    call = (lambda: km.log) if read == "log" else (lambda: getattr(km, read)(cid))
    with pytest.raises(KnowledgeIntegrityError):
        call()
    assert km.halted
    for again in (
        lambda: km.claim_view(cid),
        lambda: km.record_validation(claim_id=cid, validator="v2"),
        lambda: km.owner_sign(claim_id=cid, owner_key=TEST_OWNER_KEY),
        lambda: km.withdraw_evidence(evidence_id="0" * 64, actor="x", reason=""),
        lambda: _source(km, uri="news://late"),
    ):
        with pytest.raises(KnowledgeManagerHalted):
            again()
    assert isinstance(km.log, tuple)  # forensic, unverified, still frozen


def test_unexpected_error_halts_and_appends_nothing(km, monkeypatch):
    cid, src = _claim(km)
    _support(km, cid, src)
    before = len(km.log)
    monkeypatch.setattr(km, "_facts", lambda _cid: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(KnowledgeManagerHalted):
        km.record_validation(claim_id=cid, validator="validator_agent")
    assert km.halted and len(km.log) == before


# -- no authority, no runtime hooks ----------------------------------------


def test_views_and_api_carry_no_trading_authority():
    fields = {f.name for f in dataclasses.fields(ClaimView)}
    forbidden = {"trading", "order", "execute", "capital", "risk", "position", "size", "live"}
    assert not [f for f in fields if any(tok in f for tok in forbidden)], fields
    names = [n.lower() for n in dir(KnowledgeManager) if not n.startswith("_")]
    for token in ("execute", "order", "trade", "risk", "capital", "portfolio", "publish", "bridge", "brain"):
        assert not [n for n in names if token in n], (token, names)


def test_constructor_rejects_a_malformed_fingerprint():
    with pytest.raises(OwnerKeyError):
        KnowledgeManager(owner_key_fingerprint="not-a-fingerprint")
    with pytest.raises(OwnerKeyError):
        KnowledgeManager(owner_key_fingerprint=TEST_OWNER_KEY)  # a key is never the pin
