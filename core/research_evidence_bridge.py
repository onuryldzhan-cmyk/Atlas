"""The sanctioned L3 bridge from a research verdict to the Evidence Store.

ADR-0009 settles ``research/`` as L4 and holds it to a stricter line than
its layer requires: it imports nothing first-party outside ``research/``,
not even an L1 contract. The cost of that line, named in the ADR's
consequences, is "one small translation function outside ``research/``,
paid once, in the bridge package". This module is that function.

The shape ADR-0009 sanctions, and the one implemented here::

    research/hypothesis_registry.py   (L4, pure, stdlib-only)
          └─ produces the five-check verdict value object
                              │
                              ▼  read by
    core/research_evidence_bridge.py  (L3)
          ├─ imports research.hypothesis_registry       (L3 -> L4, allowed)
          ├─ imports data_layer.contracts.ClaimSource   (L3 -> L1, allowed)
          └─ calls record_claim() on an injected store  (L3 -> L2, allowed)

The dependency is one-way by construction: ``research/`` never learns the
store exists. The store arrives as a constructor parameter typed ``Any``
and is never imported here, mirroring ``ai/core/atlas_brain.py``, which
holds the injected ``EvidenceStore`` as ``Any | None`` and imports only
``ClaimSource`` from ``data_layer.contracts``.

**Not wired into the runtime.** ADR-0009 chose W1 over W2: this module is
imported by nothing in the runtime closure, so ``research/`` stays outside
it and the closure artifacts are unchanged. Wiring it into
``core/application.py`` is W2, deferred there as its own package.

Two deliberate divergences from the AtlasBrain precedent, both in the
conservative direction, both because this module sits on no decision path:

* **The store is required, not optional.** AtlasBrain's store defaults to
  absent and every interaction with it is fail-open, because a failed
  claim write must never perturb a trading decision. A bridge whose only
  job is to record has no decision to protect: a missing store is a
  misconstructed bridge, not a degraded one, so it is refused at
  construction where the composition root can see it, rather than
  silently dropping every verdict handed to it afterwards.
* **Store failures propagate.** For the same reason, a failed write is
  raised to the caller instead of being absorbed. Nothing downstream is
  put at risk by the exception, and swallowing it would report success
  for a verdict that was never persisted.

**NB-4 at this boundary.** The confidence written is
``passed_check_count / required_check_count`` -- the count the sealed plan
requires as the denominator, which is ``adjudicate_checks()``'s own NB-5
guard carried through unchanged. Because a required check with no recorded
result adjudicates as *missing* rather than being dropped from the
denominator, removing a recorded result can only lower the numerator while
the denominator holds, so confidence is monotone non-increasing under the
removal of evidence. No value is defaulted or invented: nothing here
substitutes a figure for a check that did not run, and the full
adjudication -- counts, missing checks, failed checks, status -- is written
into the claim payload and reason codes so the ratio is never the only
record of what happened.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

# L3 -> L1. The persistence value type only; the store that writes it is
# injected, never imported (ADR-0008, ADR-0009).
from data_layer.contracts import ClaimSource

# L3 -> L4. Read-only use of the research package's own vocabulary.
from research.hypothesis_registry import REGISTRY_FORMAT_VERSION


logger = logging.getLogger("AtlasAI.ResearchEvidenceBridge")


#: Claim identity of the research validation protocol. The Evidence Store
#: derives ``claim_id`` from this together with the subject symbol, the
#: claim kind, the payload digest and the assertion time, so it is part of
#: the idempotency key: two bridges recording the same verdict under the
#: same agent id collide in the database rather than duplicating.
CLAIM_AGENT_ID = "research:hypothesis_registry"

#: A validation verdict asserts that a pre-registered protocol was or was
#: not cleared. That is none of REGIME, DIRECTIONAL, RISK, CORRELATION,
#: ANOMALY or MACRO, and calling it DIRECTIONAL because the hypothesis
#: happens to carry a direction would file a protocol outcome as a market
#: opinion.
CLAIM_KIND = "OTHER"

#: The source examined is the sealed registry record, which is computed
#: from data rather than retrieved from a venue or a feed.
SOURCE_KIND = "DERIVED"

SOURCE_URI_SCHEME = "hypothesis-registry"


class ResearchEvidenceBridgeError(RuntimeError):
    """The bridge refused to record. Never raised by the store itself.

    Every use is fail-closed: the bridge raises rather than recording a
    claim it cannot vouch for, and rather than filling a gap with a
    substitute value.
    """


def _enum_text(value: Any) -> str:
    """The string behind a check name or status, enum or plain."""
    return value.value if isinstance(value, Enum) else str(value)


def _require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResearchEvidenceBridgeError(
            f"verdict {field_name} must be an int, got {value!r}"
        )
    return value


def _require_names(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or value is None:
        raise ResearchEvidenceBridgeError(
            f"verdict {field_name} must be a sequence of check names, "
            f"got {value!r}"
        )
    try:
        return tuple(_enum_text(item) for item in value)
    except TypeError as exc:
        raise ResearchEvidenceBridgeError(
            f"verdict {field_name} must be iterable, got {value!r}"
        ) from exc


def _require_aware(value: Any, field_name: str) -> datetime:
    """Parse an ISO-8601 research timestamp, refusing a naive one.

    ``research/`` writes ``datetime.now(UTC).isoformat()``, but its own
    parser accepts a naive string from a hand-edited file, and the store
    requires a timezone-aware value. Guessing UTC for a naive timestamp
    would invent the one fact -- when this was observed -- that the claim
    exists to preserve.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ResearchEvidenceBridgeError(
                f"{field_name} must be an ISO-8601 timestamp, got {value!r}"
            ) from exc
    if parsed.tzinfo is None:
        raise ResearchEvidenceBridgeError(
            f"{field_name} must carry a timezone offset, got {value!r}"
        )
    return parsed


class ResearchEvidenceBridge:
    """Records one hypothesis's five-check verdict as an Evidence Store claim.

    The store is injected. Construct one per recording run::

        bridge = ResearchEvidenceBridge(store, run_id="research-2026-09-20")
        claim_id = bridge.record_verdict(record)

    ``record`` is a ``research.hypothesis_registry.HypothesisRecord``. It is
    duck-typed rather than isinstance-checked so a caller may hand in an
    equivalent value object, which is also why every field it yields is
    validated here instead of being trusted.
    """

    def __init__(
        self,
        evidence_store: Any,
        *,
        run_id: str,
        agent_id: str = CLAIM_AGENT_ID,
    ) -> None:
        if evidence_store is None:
            raise ResearchEvidenceBridgeError(
                "evidence_store is required; a bridge with no store would "
                "discard every verdict handed to it"
            )
        if not isinstance(run_id, str) or not run_id.strip():
            raise ResearchEvidenceBridgeError("run_id is required")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ResearchEvidenceBridgeError("agent_id is required")

        self.evidence_store = evidence_store
        self.run_id = run_id
        self.agent_id = agent_id
        #: The registry's own format version, so a claim records which
        #: protocol revision produced it rather than a number chosen here.
        self.agent_version = str(REGISTRY_FORMAT_VERSION)

    # -----------------------------------------------------------------
    # RECORDING
    # -----------------------------------------------------------------

    def record_verdict(self, record: Any) -> str:
        """Record ``record``'s check adjudication; return its claim_id.

        Idempotent through the store: every input to the claim id is
        derived from the record, so recording the same verdict twice
        returns the same id and writes nothing the second time.
        """

        hypothesis_id = self._required_text(
            getattr(record, "hypothesis_id", None), "hypothesis_id"
        )
        preregistration = getattr(record, "preregistration", None)
        if preregistration is None:
            raise ResearchEvidenceBridgeError(
                f"{hypothesis_id} carries no preregistration"
            )

        (
            required_count,
            passed_count,
            recorded_count,
            missing_checks,
            failed_checks,
            status,
        ) = self._adjudicate(record, hypothesis_id)

        asserted_at = self._asserted_at(record, preregistration)
        scope, symbol = self._subject(preregistration, hypothesis_id)

        # The NB-5 denominator, carried through from adjudicate_checks()
        # unchanged. Exact division: no float ever touches the value.
        confidence = Decimal(passed_count) / Decimal(required_count)

        payload = {
            "hypothesis_id": hypothesis_id,
            "family_id": self._optional_text(
                getattr(record, "family_id", None)
            ),
            "state": self._optional_text(getattr(record, "state", None)),
            "preregistration_hash": self._optional_text(
                getattr(record, "preregistration_hash", None)
            ),
            "required_check_count": required_count,
            "passed_check_count": passed_count,
            "recorded_check_count": recorded_count,
            "missing_checks": list(missing_checks),
            "failed_checks": list(failed_checks),
            "check_plan_status": status,
            "universe": list(self._universe(preregistration)),
        }

        reason_codes = [status]
        reason_codes.extend(f"MISSING_{name}" for name in missing_checks)
        reason_codes.extend(f"FAILED_{name}" for name in failed_checks)

        source = ClaimSource(
            source_kind=SOURCE_KIND,
            source_uri=f"{SOURCE_URI_SCHEME}://{hypothesis_id}",
            source_version=self.agent_version,
            retrieved_at=asserted_at,
            # The seal. It ties the claim to the exact pre-registration
            # that was adjudicated, so a later edit to the hypothesis is
            # visible as a digest mismatch rather than being absorbed.
            source_digest=self._optional_text(
                getattr(record, "preregistration_hash", None)
            ),
        )

        claim_id = self.evidence_store.record_claim(
            claim_text=(
                f"{hypothesis_id}: {passed_count} of {required_count} "
                f"required checks passed ({status})"
            ),
            claim_kind=CLAIM_KIND,
            subject_scope=scope,
            subject_symbol=symbol,
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            confidence=confidence,
            asserted_at=asserted_at,
            sources=[source],
            payload=payload,
            run_id=self.run_id,
            reason_codes=reason_codes,
        )

        logger.debug(
            "Recorded %s verdict %s as claim %s",
            hypothesis_id,
            status,
            claim_id,
        )
        return claim_id

    # -----------------------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------------------

    def _adjudicate(
        self, record: Any, hypothesis_id: str
    ) -> tuple[int, int, int, tuple[str, ...], tuple[str, ...], str]:
        """Obtain and validate the five-check verdict value object.

        The counts are cross-checked against each other rather than taken
        on trust. An adjudication reporting fewer missing and failed checks
        than the plan's shortfall would raise the recorded confidence
        above what the evidence supports, which is the NB-4 failure this
        boundary has to refuse.
        """
        adjudicate = getattr(record, "adjudicate_checks", None)
        if not callable(adjudicate):
            raise ResearchEvidenceBridgeError(
                f"{hypothesis_id} exposes no adjudicate_checks(); it is not "
                f"a hypothesis record carrying a five-check verdict"
            )
        verdict = adjudicate()
        if verdict is None:
            raise ResearchEvidenceBridgeError(
                f"{hypothesis_id} produced no check adjudication"
            )

        for field_name in (
            "required_check_count",
            "passed_check_count",
            "recorded_check_count",
            "missing_checks",
            "failed_checks",
            "status",
        ):
            if not hasattr(verdict, field_name):
                raise ResearchEvidenceBridgeError(
                    f"{hypothesis_id} check adjudication is missing "
                    f"{field_name}"
                )

        required = _require_int(
            verdict.required_check_count, "required_check_count"
        )
        passed = _require_int(verdict.passed_check_count, "passed_check_count")
        recorded = _require_int(
            verdict.recorded_check_count, "recorded_check_count"
        )
        missing = _require_names(verdict.missing_checks, "missing_checks")
        failed = _require_names(verdict.failed_checks, "failed_checks")
        status = self._required_text(verdict.status, "status")

        if required < 1:
            raise ResearchEvidenceBridgeError(
                f"{hypothesis_id} check adjudication requires "
                f"{required} checks; a plan requiring none would make the "
                f"recorded confidence vacuous"
            )
        if not 0 <= passed <= required:
            raise ResearchEvidenceBridgeError(
                f"{hypothesis_id} passed {passed} of {required} required "
                f"checks, which is not a possible count"
            )
        if recorded < 0:
            raise ResearchEvidenceBridgeError(
                f"{hypothesis_id} reports {recorded} recorded checks"
            )
        if passed + len(missing) + len(failed) != required:
            raise ResearchEvidenceBridgeError(
                f"{hypothesis_id} check adjudication does not account for "
                f"every required check: {passed} passed, {len(missing)} "
                f"missing, {len(failed)} failed, {required} required"
            )

        return required, passed, recorded, missing, failed, status

    def _asserted_at(self, record: Any, preregistration: Any) -> datetime:
        """The verdict's own time, never the wall clock.

        ``datetime.now()`` here would defeat the store's idempotency -- the
        assertion time is part of the claim id, so the same verdict would
        land twice under two ids. The latest recorded check is the moment
        the verdict last changed; with nothing recorded, the
        pre-registration's own timestamp is the only time the record
        carries.
        """
        check_results = getattr(record, "check_results", None)
        latest: datetime | None = None
        if callable(check_results):
            for check in check_results():
                recorded_at = _require_aware(
                    getattr(check, "recorded_at", None), "recorded_at"
                )
                if latest is None or recorded_at > latest:
                    latest = recorded_at
        if latest is not None:
            return latest
        return _require_aware(
            getattr(preregistration, "preregistered_at", None),
            "preregistered_at",
        )

    def _subject(
        self, preregistration: Any, hypothesis_id: str
    ) -> tuple[str, str | None]:
        """SYMBOL for a single-symbol universe, MARKET for a wider one.

        A hypothesis over several symbols is not a claim about any one of
        them, and picking the first would file it against a subject it was
        never tested on.
        """
        universe = self._universe(preregistration)
        if not universe:
            raise ResearchEvidenceBridgeError(
                f"{hypothesis_id} preregistration carries an empty universe"
            )
        if len(universe) == 1:
            return "SYMBOL", universe[0]
        return "MARKET", None

    def _universe(self, preregistration: Any) -> tuple[str, ...]:
        universe = getattr(preregistration, "universe", None)
        if isinstance(universe, (str, bytes)) or universe is None:
            raise ResearchEvidenceBridgeError(
                f"preregistration universe must be a sequence of symbols, "
                f"got {universe!r}"
            )
        try:
            return tuple(str(symbol) for symbol in universe)
        except TypeError as exc:
            raise ResearchEvidenceBridgeError(
                f"preregistration universe must be iterable, got "
                f"{universe!r}"
            ) from exc

    @staticmethod
    def _required_text(value: Any, field_name: str) -> str:
        text = _enum_text(value) if value is not None else ""
        if not text.strip():
            raise ResearchEvidenceBridgeError(f"{field_name} is required")
        return text

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        return None if value is None else _enum_text(value)


__all__ = [
    "CLAIM_AGENT_ID",
    "CLAIM_KIND",
    "SOURCE_KIND",
    "SOURCE_URI_SCHEME",
    "ResearchEvidenceBridge",
    "ResearchEvidenceBridgeError",
]
