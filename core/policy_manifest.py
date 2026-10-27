"""Phase-2 G1: the policy manifest - critical runtime policy pinned to governance metadata.

The owner-controlled switches that decide what risk Atlas may take (execution
mode, live enablement, confidence floors, the paper experiment, loss/sleeve/
slippage/fee switches, fusion denominator, ExitGuard, ...) are literals at one
call site in main.py. This module compares the switches the runtime *actually
has* with a versioned manifest under governance/policy/ (kept out of governance/current/, whose files form the registry chain) that names the
governance registry and proposal it belongs to (manifest v2 adds EXP-002's
parameters and the grant that authorises them).

It only reads and compares. It never applies a manifest value, never changes
runtime configuration, never claims owner approval on its own (the manifest's own
``owner_approval`` text is ignored; approval is reported only when the successor
registry's EXP-002 grant exists, is GRANTED and pins this manifest's exact
bytes) and can never enable LIVE: a manifest
that names anything but PAPER, or live execution enabled, is refused outright.

Any result other than MATCH means BLOCK_NEW_RISK: ExecutionManager then refuses
new BUYs while reduce-only exits stay governed by the Phase-2 B1 rules. The
integrity digest detects an accidental or partial edit of the manifest; it is
not an authenticity signature (anyone who can edit the repository can recompute
it) - authority still comes from the registry and the owner, not from the hash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# Task 023 (registry v5.106): manifest v3 (forex) is the active manifest. v2 stays sealed and is still verified by
# its own rules below when asked (``verify(..., path=MANIFEST_V2_PATH)``); nothing in v2's chain changes.
MANIFEST_V2_PATH = REPOSITORY_ROOT / "governance" / "policy" / "ATLAS_POLICY_MANIFEST_v2.json"
# Task 025 (registry v5.108): manifest v4 (forex leverage and stop-out) is the active manifest. v3 stays sealed and
# is still verified by its own rules when named (``MANIFEST_V3_PATH``).
MANIFEST_V3_PATH = REPOSITORY_ROOT / "governance" / "policy" / "ATLAS_POLICY_MANIFEST_v3.json"
MANIFEST_PATH = REPOSITORY_ROOT / "governance" / "policy" / "ATLAS_POLICY_MANIFEST_v4.json"
EXPECTED_MANIFEST_VERSION = 4

# The governance binding this code expects. Changing the manifest's registry or
# proposal is a governance act, so it also needs a code change here.
# The manifest pins this (sealed, earlier) registry by sha256 as its governance base.
EXPECTED_REGISTRY_ID = "ATLAS_MILESTONE_REGISTRY_v5.84"
EXPECTED_PROPOSAL_ID = "PHASE2-G1-POLICY-MANIFEST"

# The successor registry that carries the EXP-002 grant. The dependency runs one
# way only, so there is no circular checksum: the grant registry pins the
# manifest's file bytes; the manifest names the grant registry (id and path, no
# hash) and pins only the earlier base registry above.
EXPECTED_GRANT_REGISTRY_ID = "ATLAS_MILESTONE_REGISTRY_v5.85"
EXPECTED_GRANT_ID = "GRANT-EXP002-PAPER-CONFIDENCE-EXPERIMENT"
GRANT_RECORD_KEY = "exp002_grant"
# The grant registry is read from this exact path, never from a path the manifest chooses.
EXPECTED_GRANT_REGISTRY_PATH = "governance/current/ATLAS_MILESTONE_REGISTRY_v5.85.json"
# The grant registry is a sealed record: its (line-ending neutral) sha256 is pinned
# here, in reviewed code, exactly like the registry/proposal ids above. The chain is
# anchored in code -> v5.85 -> manifest v2 -> v5.84, so there is still no cycle (nothing
# in the registry or manifest contains a hash of this module). Editing the grant
# registry, alone or together with the manifest, is therefore GRANT_MISMATCH until a
# governed change updates this constant (a new grant is a new successor registry).
EXPECTED_GRANT_REGISTRY_SHA256 = "77f0c23ae150215dad6ef017eca8ca57b81d6c44e36c767a16278fc9efa2d0b8"

# Manifest v3 (forex; owner 2026-10-26). Same one-way chain, anchored in code:
#   code -> v5.106 (ratification record, pins manifest v3's bytes) -> manifest v3 -> v5.105 (its sealed base).
# EXP-002's parameters are still compared with the sealed v5.85 grant (pinned above); only v5.85's own manifest
# pin (which names v2) is not asked of v3, because v5.106 is the record that ratifies v3.
V3_EXPECTED_REGISTRY_ID = "ATLAS_MILESTONE_REGISTRY_v5.105"
V3_EXPECTED_PROPOSAL_ID = "FOREX-POLICY-MANIFEST-V3"
V3_RATIFICATION_REGISTRY_ID = "ATLAS_MILESTONE_REGISTRY_v5.106"
V3_RATIFICATION_REGISTRY_PATH = "governance/current/ATLAS_MILESTONE_REGISTRY_v5.106.json"
V3_RATIFICATION_RECORD_KEY = "policy_manifest_v3_ratification"
V3_RATIFICATION_REGISTRY_SHA256 = "146e680467194d10e2166d88a8ef766262a4c52ea5bc53dba64e97cdbaaeb4cf"

# Manifest v4 (Task 025: forex leverage 1:2 and a 100 % stop-out; owner 2026-10-26/27). The same one-way chain:
#   code -> v5.108 (ratification record, pins manifest v4's bytes) -> manifest v4 -> v5.107 (its sealed base).
V4_EXPECTED_REGISTRY_ID = "ATLAS_MILESTONE_REGISTRY_v5.107"
V4_EXPECTED_PROPOSAL_ID = "FOREX-POLICY-MANIFEST-V4"
V4_RATIFICATION_REGISTRY_ID = "ATLAS_MILESTONE_REGISTRY_v5.108"
V4_RATIFICATION_REGISTRY_PATH = "governance/current/ATLAS_MILESTONE_REGISTRY_v5.108.json"
V4_RATIFICATION_RECORD_KEY = "policy_manifest_v4_ratification"
V4_RATIFICATION_REGISTRY_SHA256 = "174a14018b819cd36a478ea21dc00e28b67d7d4a8e70ed1a8391c18628bdfb2b"

MATCH = "MATCH"
MISSING = "MISSING"
MALFORMED = "MALFORMED"
INTEGRITY_FAILED = "INTEGRITY_FAILED"
LIVE_REFUSED = "LIVE_REFUSED"
REGISTRY_MISMATCH = "REGISTRY_MISMATCH"
PROPOSAL_MISMATCH = "PROPOSAL_MISMATCH"
POLICY_MISMATCH = "POLICY_MISMATCH"
BLOCK_NEW_RISK = "BLOCK_NEW_RISK"
UNREADABLE = "UNREADABLE"
GRANT_MISSING = "GRANT_MISSING"
GRANT_MISMATCH = "GRANT_MISMATCH"
OWNER_RATIFIED = "OWNER_RATIFIED_VIA_REGISTRY"

# Every switch the manifest must cover - no more, no fewer.
BASE_SWITCHES = (
    "execution_mode",
    "live_execution_enabled",
    "execution_minimum_confidence",
    "risk_policy_version",
    "global_minimum_confidence",
    "paper_confidence_experiment",
    "paper_confidence_experiment_id",
    "paper_fee_rate",
    "paper_slippage_bps",
    "count_unrealized_in_daily_loss",
    "sleeves_enabled",
    "funding_sentiment",
    "fusion_full_weight_denominator",
    "order_lifecycle_observe",
    "paper_fill_model",
    "exit_guard_mode",
    "exit_guard_rules",
)

# EXP-002's own parameters (Phase-2 manifest v2). Read from the experiment the
# RiskEngine actually holds (or, if it did not attach, the pinned constant the
# application would have attached), so editing any of them is a policy mismatch.
EXP002_SWITCHES = (
    "exp002_enabled",
    "exp002_experiment_id",
    "exp002_buckets",
    "exp002_minimum_confidence",
    "exp002_global_minimum_confidence",
    "exp002_max_admissions",
    "exp002_starts_at",
    "exp002_ends_at",
    "exp002_sizing_mode",
    "exp002_sizing_max_allocation_pct",
    "exp002_sizing_exposure_ceiling_pct",
    "exp002_medium_default_floor",
    "exp002_paper_only",
    "exp002_funding_sentiment_off",
)
CRITICAL_SWITCHES = BASE_SWITCHES + EXP002_SWITCHES

# Manifest v3 adds the market and the forex switches (Task 023).
FOREX_SWITCHES = (
    "market",
    "forex_paper_fee_rate",
    "forex_weekend_close_minutes",
)
CRITICAL_SWITCHES_V3 = CRITICAL_SWITCHES + FOREX_SWITCHES

# Manifest v4 adds the account leverage, as the RiskPolicy and the durable book each hold it, and the stop-out
# margin level (Task 025).
LEVERAGE_SWITCHES = (
    "risk_leverage",
    "book_leverage",
    "forex_stop_out_margin_level",
)
CRITICAL_SWITCHES_V4 = CRITICAL_SWITCHES_V3 + LEVERAGE_SWITCHES


@dataclass(frozen=True)
class _Successor:
    """One forex successor manifest's governance binding (v3, v4), all pinned here in reviewed code."""

    version: int
    switches: tuple[str, ...]
    base_registry_id: str
    proposal_id: str
    ratification_registry_id: str
    ratification_registry_path: str
    ratification_record_key: str

    @property
    def ratification_registry_sha256(self) -> str:
        # read from the module constant at call time, so the pin lives in exactly one place
        return str(globals()[f"V{self.version}_RATIFICATION_REGISTRY_SHA256"])


_SUCCESSORS = {
    3: _Successor(3, CRITICAL_SWITCHES_V3, V3_EXPECTED_REGISTRY_ID, V3_EXPECTED_PROPOSAL_ID,
                  V3_RATIFICATION_REGISTRY_ID, V3_RATIFICATION_REGISTRY_PATH, V3_RATIFICATION_RECORD_KEY),
    4: _Successor(4, CRITICAL_SWITCHES_V4, V4_EXPECTED_REGISTRY_ID, V4_EXPECTED_PROPOSAL_ID,
                  V4_RATIFICATION_REGISTRY_ID, V4_RATIFICATION_REGISTRY_PATH, V4_RATIFICATION_RECORD_KEY),
}

_REQUIRED = ("manifest_version", "registry_id", "registry_path", "registry_sha256", "proposal_id",
             "owner_approval", "grant", "policy", "integrity")


def file_sha256(data: bytes) -> str:
    """sha256 of a pinned governance file, line-ending neutral (CRLF read as LF).

    The recorded pins are the sha256 of the committed (LF) bytes. A Windows
    checkout with ``core.autocrlf`` writes the same files with CRLF, which
    would make every byte pin fail and block all new risk although no content
    changed (verified 2026-10-04 by rewriting the chain with CRLF). Only the
    two-byte sequence CRLF is read as LF; any other change still changes the
    digest, so this accepts no edit.
    """

    return hashlib.sha256(b"\n".join(data.split(b"\r\n"))).hexdigest()


def _decimal_text(value: Any) -> str:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("non-finite")
    # Exact: normalize() rounds to the context precision (28), which would make
    # 0.62 and 0.62 + 1e-31 compare equal.
    with localcontext() as context:
        context.prec = max(len(number.as_tuple().digits) + 2, 28)
        text = format(number.normalize(), "f")
    return "0" if text in ("-0", "") else text


def runtime_policy(application: Any) -> dict[str, Any]:
    """The critical switches as the running AtlasApplication actually holds them.

    A switch that cannot be read is UNREADABLE, which never matches a manifest.
    """

    def read(getter):
        try:
            return getter()
        except Exception:
            return UNREADABLE

    execution = getattr(application, "execution", None)
    guard = getattr(application, "exit_guard", None)
    return {
        "execution_mode": read(lambda: str(application.execution_mode).upper()),
        "live_execution_enabled": read(lambda: execution.live_execution_enabled is True),
        "execution_minimum_confidence": read(lambda: _decimal_text(execution.minimum_confidence)),
        "risk_policy_version": read(lambda: str(application.risk_engine.policy.version)),
        "global_minimum_confidence": read(lambda: _decimal_text(application.risk_policy.global_minimum_confidence)),
        "paper_confidence_experiment": read(lambda: application.paper_confidence_experiment is True),
        "paper_confidence_experiment_id": read(lambda: str(application.paper_confidence_experiment_id)),
        "paper_fee_rate": read(lambda: _decimal_text(application.paper_fee_rate)),
        "paper_slippage_bps": read(lambda: _decimal_text(application.paper_slippage_bps)),
        "count_unrealized_in_daily_loss": read(lambda: application.count_unrealized_in_daily_loss is True),
        "sleeves_enabled": read(lambda: application.sleeves_enabled is True),
        "funding_sentiment": read(lambda: application.funding_sentiment is True),
        "fusion_full_weight_denominator": read(lambda: application.fusion_full_weight_denominator is True),
        "order_lifecycle_observe": read(lambda: application.order_lifecycle_observe is True),
        "paper_fill_model": read(lambda: str(application.paper_fill_model).upper()),
        "exit_guard_mode": read(lambda: str(guard.mode)),
        "exit_guard_rules": read(lambda: len(guard.rules)),
        **_exp002_runtime(application, read),
        **_forex_runtime(application, guard, read),
        **_leverage_runtime(application, guard, read),
    }


def _leverage_runtime(application: Any, guard: Any, read) -> dict[str, Any]:
    """Manifest v4's switches as the running application holds them (Task 025)."""

    def stop_out_level():
        if str(application.market).upper() != "FOREX":
            from atlas_finance.forex.instruments import STOP_OUT_MARGIN_LEVEL
            return _decimal_text(STOP_OUT_MARGIN_LEVEL)     # configured, unused outside FOREX
        levels = [rule.threshold for rule in guard.rules if rule.kind == "STOP_OUT"]
        if len(levels) != 1 or guard.mode != "ENFORCE":
            raise ValueError("FOREX needs exactly one STOP_OUT rule in ENFORCE")
        runner = getattr(application.market_loop, "exit_guard_runner", None)
        if runner is None or getattr(runner, "guard", None) is not guard:
            raise ValueError("the FOREX stop-out guard is not run from the cycle")
        return _decimal_text(levels[0])

    def int_value(value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("leverage is not an integer")
        return value

    return {
        "risk_leverage": read(lambda: int_value(application.risk_policy.leverage)),
        "book_leverage": read(lambda: int_value(application.portfolio_foundation.expected_leverage)),
        "forex_stop_out_margin_level": read(stop_out_level),
    }


def _forex_runtime(application: Any, guard: Any, read) -> dict[str, Any]:
    """Manifest v3's switches as the running application holds them (Task 023)."""

    def weekend_minutes():
        if str(application.market).upper() != "FOREX":
            from atlas_finance.forex.sessions import WEEKEND_CLOSE_MINUTES
            return int(WEEKEND_CLOSE_MINUTES)        # configured, unused outside FOREX
        minutes = [rule.minutes for rule in guard.rules if rule.kind == "WEEKEND_CLOSE"]
        if len(minutes) != 1:
            raise ValueError("FOREX needs exactly one WEEKEND_CLOSE rule")
        # review T023-F1: the rule only counts when the cycle actually runs this guard
        runner = getattr(application.market_loop, "exit_guard_runner", None)
        if runner is None or getattr(runner, "guard", None) is not guard:
            raise ValueError("the FOREX weekend-close guard is not run from the cycle")
        return int(minutes[0])

    return {
        "market": read(lambda: str(application.market).upper()),
        "forex_paper_fee_rate": read(lambda: _decimal_text(application.paper_fee_rate)),
        "forex_weekend_close_minutes": read(weekend_minutes),
    }


def _exp002_runtime(application: Any, read) -> dict[str, Any]:
    """EXP-002's effective parameters as the running application holds them."""

    from core import risk_engine

    def experiment():
        attached = application.risk_engine.experiment
        if attached is not None:
            return attached
        return risk_engine.PAPER_CONFIDENCE_EXPERIMENTS[str(application.paper_confidence_experiment_id)]

    def sizing(name):
        return _decimal_text(getattr(application.risk_policy.buckets[risk_engine.EXPERIMENT_SIZING_BUCKET], name))

    return {
        "exp002_enabled": read(lambda: application.paper_confidence_experiment is True
                               and str(application.paper_confidence_experiment_id) == "EXP-002"),
        "exp002_experiment_id": read(lambda: str(experiment().experiment_id)),
        "exp002_buckets": read(lambda: sorted(b.value for b in experiment().buckets)),
        "exp002_minimum_confidence": read(lambda: _decimal_text(experiment().minimum_confidence)),
        "exp002_global_minimum_confidence": read(
            lambda: _decimal_text(application.risk_policy.global_minimum_confidence)),
        "exp002_max_admissions": read(lambda: int(experiment().max_admissions)),
        "exp002_starts_at": read(lambda: experiment().starts_at.isoformat()),
        "exp002_ends_at": read(lambda: experiment().ends_at.isoformat()),
        "exp002_sizing_mode": read(lambda: f"{risk_engine.EXPERIMENT_SIZING_BUCKET.value}_BUCKET_LIMITS"),
        "exp002_sizing_max_allocation_pct": read(lambda: sizing("max_allocation_pct")),
        "exp002_sizing_exposure_ceiling_pct": read(lambda: sizing("exposure_ceiling_pct")),
        "exp002_medium_default_floor": read(lambda: _decimal_text(
            application.risk_policy.buckets[risk_engine.RiskBucket.MEDIUM].minimum_confidence)),
        "exp002_paper_only": read(lambda: str(application.execution_mode).upper() == "PAPER"),
        "exp002_funding_sentiment_off": read(lambda: application.funding_sentiment is not True),
    }


def integrity_digest(manifest: Mapping[str, Any]) -> str:
    """sha256 of the canonical JSON of everything except the ``integrity`` block."""

    body = {k: v for k, v in manifest.items() if k != "integrity"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PolicyManifestCheck:
    status: str
    detail: str = ""
    mismatches: tuple[tuple[str, Any, Any], ...] = ()
    manifest_version: Any = None
    registry_id: Any = None
    proposal_id: Any = None
    owner_approval: Any = "UNKNOWN"
    runtime: Mapping[str, Any] = field(default_factory=dict)

    @property
    def block_new_risk(self) -> bool:
        return self.status != MATCH

    @property
    def block_reason(self) -> str | None:
        return None if self.status == MATCH else f"POLICY_MANIFEST_{self.status}"

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "decision": BLOCK_NEW_RISK if self.block_new_risk else "ALLOW",
                "detail": self.detail,
                "mismatches": [{"switch": k, "manifest": m, "runtime": r} for k, m, r in self.mismatches],
                "manifest_version": self.manifest_version, "registry_id": self.registry_id,
                "proposal_id": self.proposal_id, "owner_approval": self.owner_approval}


def _matches(spec: Any, actual: Any, market: Any = None) -> bool:
    if actual == UNREADABLE:
        return False
    if isinstance(spec, Mapping) and set(spec) == {"by_market"}:
        # manifest v3: the value for the runtime's own market; an unknown market never matches
        by_market = spec.get("by_market")
        if not isinstance(by_market, Mapping) or not isinstance(market, str) or market not in by_market:
            return False
        chosen = by_market[market]
        return not isinstance(chosen, Mapping) and type(actual) is type(chosen) and actual == chosen
    if isinstance(spec, Mapping):
        allowed = spec.get("one_of")
        return isinstance(allowed, list) and set(spec) == {"one_of"} and any(
            type(actual) is type(a) and actual == a for a in allowed)
    return type(actual) is type(spec) and actual == spec


def _verify_grant(manifest: Mapping[str, Any], policy: Mapping[str, Any], manifest_path: Path,
                  root: Path) -> tuple[str, str] | None:
    """The EXP-002 grant in the successor registry must exist, pin THIS manifest, and equal its parameters.

    Returns (status, detail) on failure, None when the grant is intact. Reads only.
    """

    grant_ref = manifest.get("grant")
    if (not isinstance(grant_ref, dict) or grant_ref.get("grant_id") != EXPECTED_GRANT_ID
            or grant_ref.get("grant_registry_id") != EXPECTED_GRANT_REGISTRY_ID
            or grant_ref.get("grant_registry_path") != EXPECTED_GRANT_REGISTRY_PATH):
        return GRANT_MISSING, "manifest does not name the expected EXP-002 grant and grant registry"
    try:
        registry = (root / str(grant_ref.get("grant_registry_path"))).resolve()
        if root.resolve() not in registry.parents or registry.stem != EXPECTED_GRANT_REGISTRY_ID:
            return GRANT_MISSING, "grant_registry_path does not name the expected grant registry"
        registry_bytes = registry.read_bytes()
        record = json.loads(registry_bytes.decode("utf-8"))
        manifest_bytes = manifest_path.read_bytes()
    except Exception:  # unreadable or hostile input (incl. RecursionError) is never a pass
        return GRANT_MISSING, "grant registry or manifest unreadable"
    grant = record.get(GRANT_RECORD_KEY) if isinstance(record, dict) else None
    if not isinstance(grant, dict) or grant.get("grant_id") != EXPECTED_GRANT_ID or grant.get("status") != "GRANTED":
        return GRANT_MISSING, "grant registry holds no GRANTED EXP-002 grant"
    pinned = grant.get("manifest_pin")
    if (not isinstance(pinned, dict)
            or pinned.get("manifest_file_sha256") != file_sha256(manifest_bytes)
            or pinned.get("manifest_version") != manifest.get("manifest_version")):
        return GRANT_MISMATCH, "grant registry does not pin this manifest's bytes"
    parameters = grant.get("parameters")
    if (not isinstance(parameters, dict) or set(parameters) != set(EXP002_SWITCHES)
            or any(not _same(parameters[k], policy.get(k)) for k in EXP002_SWITCHES)):
        return GRANT_MISMATCH, "manifest EXP-002 parameters differ from the registry grant"
    if grant.get("live_effect") != "NONE" or parameters.get("exp002_paper_only") is not True:
        return GRANT_MISMATCH, "grant is not PAPER-only with no live effect"
    if file_sha256(registry_bytes) != EXPECTED_GRANT_REGISTRY_SHA256:
        return GRANT_MISMATCH, "grant registry differs from the sealed record pinned in code"
    return None


def _same(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


def verify(runtime: Mapping[str, Any], path: Path | str | None = None, *,
           repository_root: Path | str = REPOSITORY_ROOT) -> PolicyManifestCheck:
    """Compare ``runtime`` with the manifest at ``path`` (default: the active MANIFEST_PATH, read at call time).

    Never raises, never writes."""

    runtime = dict(runtime)
    path = Path(MANIFEST_PATH if path is None else path)
    try:
        if not path.is_file():
            return PolicyManifestCheck(MISSING, f"no manifest at {path}", runtime=runtime)
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # incl. RecursionError from a hostile manifest: never raises, always blocks
        return PolicyManifestCheck(MALFORMED, f"unreadable manifest: {type(exc).__name__}", runtime=runtime)

    if not isinstance(manifest, dict) or any(k not in manifest for k in _REQUIRED):
        return PolicyManifestCheck(MALFORMED, "manifest is not an object with the required fields", runtime=runtime)
    meta = {"manifest_version": manifest.get("manifest_version"), "registry_id": manifest.get("registry_id"),
            "proposal_id": manifest.get("proposal_id"), "owner_approval": "UNKNOWN",  # never taken from the manifest's own text
            "runtime": runtime}
    policy, integrity = manifest.get("policy"), manifest.get("integrity")
    if not isinstance(policy, dict) or not isinstance(integrity, dict):
        return PolicyManifestCheck(MALFORMED, "policy and integrity must be objects", **meta)
    successor = _SUCCESSORS.get(manifest.get("manifest_version")) \
        if isinstance(manifest.get("manifest_version"), int) and not isinstance(manifest.get("manifest_version"), bool) \
        else None
    if successor is not None:
        return _verify_successor(successor, manifest, policy, integrity, runtime, path, Path(repository_root), meta)
    if set(policy) != set(CRITICAL_SWITCHES):
        missing = sorted(set(CRITICAL_SWITCHES) - set(policy))
        extra = sorted(set(policy) - set(CRITICAL_SWITCHES))
        return PolicyManifestCheck(MALFORMED, f"switch coverage: missing={missing} unknown={extra}", **meta)

    if integrity.get("algorithm") != "sha256" or integrity.get("digest") != integrity_digest(manifest):
        return PolicyManifestCheck(INTEGRITY_FAILED, "manifest content does not match its integrity digest", **meta)

    # PAPER invariant: no manifest can authorise live trading, whatever it says.
    if policy.get("execution_mode") != "PAPER" or policy.get("live_execution_enabled") is not False:
        return PolicyManifestCheck(LIVE_REFUSED, "a manifest may only describe PAPER with live execution disabled",
                                   **meta)

    if manifest.get("registry_id") != EXPECTED_REGISTRY_ID:
        return PolicyManifestCheck(REGISTRY_MISMATCH,
                                   f"manifest names {manifest.get('registry_id')!r}, expected {EXPECTED_REGISTRY_ID}",
                                   **meta)
    try:
        registry = (Path(repository_root) / str(manifest.get("registry_path"))).resolve()
        if Path(repository_root).resolve() not in registry.parents or registry.stem != EXPECTED_REGISTRY_ID:
            return PolicyManifestCheck(REGISTRY_MISMATCH, "registry_path does not name the expected registry", **meta)
        digest = file_sha256(registry.read_bytes())
    except OSError:
        return PolicyManifestCheck(REGISTRY_MISMATCH, "registry file unreadable", **meta)
    if digest != manifest.get("registry_sha256"):
        return PolicyManifestCheck(REGISTRY_MISMATCH, "registry file changed since the manifest pinned it", **meta)

    if manifest.get("proposal_id") != EXPECTED_PROPOSAL_ID:
        return PolicyManifestCheck(PROPOSAL_MISMATCH,
                                   f"manifest names {manifest.get('proposal_id')!r}, expected {EXPECTED_PROPOSAL_ID}",
                                   **meta)

    grant_failure = _verify_grant(manifest, policy, path, Path(repository_root))
    if grant_failure is not None:
        return PolicyManifestCheck(grant_failure[0], grant_failure[1], **meta)
    meta["owner_approval"] = f"{OWNER_RATIFIED}:{EXPECTED_GRANT_REGISTRY_ID}"

    mismatches = tuple((name, policy[name], runtime.get(name, UNREADABLE)) for name in CRITICAL_SWITCHES
                       if not _matches(policy[name], runtime.get(name, UNREADABLE)))
    if mismatches:
        return PolicyManifestCheck(POLICY_MISMATCH, f"{len(mismatches)} switch(es) differ from the manifest",
                                   mismatches, **meta)
    return PolicyManifestCheck(MATCH, "runtime policy matches the manifest", **meta)


def _verify_successor(spec: _Successor, manifest: Mapping[str, Any], policy: Mapping[str, Any],
                      integrity: Mapping[str, Any], runtime: Mapping[str, Any], path: Path, root: Path,
                      meta: dict[str, Any]) -> PolicyManifestCheck:
    """Manifest v3 (Task 023) and v4 (Task 025): the v2 checks plus the version's own switches, ratified by the
    record pinned in code for that version. Reads only."""

    if set(policy) != set(spec.switches):
        missing = sorted(set(spec.switches) - set(policy))
        extra = sorted(set(policy) - set(spec.switches))
        return PolicyManifestCheck(MALFORMED, f"switch coverage: missing={missing} unknown={extra}", **meta)
    if integrity.get("algorithm") != "sha256" or integrity.get("digest") != integrity_digest(manifest):
        return PolicyManifestCheck(INTEGRITY_FAILED, "manifest content does not match its integrity digest", **meta)
    if policy.get("execution_mode") != "PAPER" or policy.get("live_execution_enabled") is not False:
        return PolicyManifestCheck(LIVE_REFUSED, "a manifest may only describe PAPER with live execution disabled",
                                   **meta)

    if manifest.get("registry_id") != spec.base_registry_id:
        return PolicyManifestCheck(REGISTRY_MISMATCH,
                                   f"manifest names {manifest.get('registry_id')!r}, expected {spec.base_registry_id}",
                                   **meta)
    try:
        registry = (root / str(manifest.get("registry_path"))).resolve()
        if root.resolve() not in registry.parents or registry.stem != spec.base_registry_id:
            return PolicyManifestCheck(REGISTRY_MISMATCH, "registry_path does not name the expected registry", **meta)
        digest = file_sha256(registry.read_bytes())
    except OSError:
        return PolicyManifestCheck(REGISTRY_MISMATCH, "registry file unreadable", **meta)
    if digest != manifest.get("registry_sha256"):
        return PolicyManifestCheck(REGISTRY_MISMATCH, "registry file changed since the manifest pinned it", **meta)
    if manifest.get("proposal_id") != spec.proposal_id:
        return PolicyManifestCheck(PROPOSAL_MISMATCH,
                                   f"manifest names {manifest.get('proposal_id')!r}, expected {spec.proposal_id}",
                                   **meta)

    ratification_failure = _verify_ratification(spec, manifest, path, root)
    if ratification_failure is not None:
        return PolicyManifestCheck(ratification_failure[0], ratification_failure[1], **meta)
    exp002_failure = _verify_exp002_parameters(policy, root)
    if exp002_failure is not None:
        return PolicyManifestCheck(exp002_failure[0], exp002_failure[1], **meta)
    meta["owner_approval"] = f"{OWNER_RATIFIED}:{spec.ratification_registry_id}"

    market = runtime.get("market")
    mismatches = tuple((name, policy[name], runtime.get(name, UNREADABLE)) for name in spec.switches
                       if not _matches(policy[name], runtime.get(name, UNREADABLE), market))
    if mismatches:
        return PolicyManifestCheck(POLICY_MISMATCH, f"{len(mismatches)} switch(es) differ from the manifest",
                                   mismatches, **meta)
    return PolicyManifestCheck(MATCH, "runtime policy matches the manifest", **meta)


def _verify_ratification(spec: _Successor, manifest: Mapping[str, Any], manifest_path: Path,
                         root: Path) -> tuple[str, str] | None:
    """The version's ratification record must exist, be RATIFIED, pin THIS manifest's bytes, and be the sealed file."""

    ref = manifest.get("ratification")
    if (not isinstance(ref, dict) or ref.get("registry_id") != spec.ratification_registry_id
            or ref.get("registry_path") != spec.ratification_registry_path):
        return GRANT_MISSING, f"manifest does not name the expected v{spec.version} ratification registry"
    try:
        registry = (root / spec.ratification_registry_path).resolve()     # the code's path, never the manifest's
        if root.resolve() not in registry.parents or registry.stem != spec.ratification_registry_id:
            return GRANT_MISSING, "ratification registry path is outside the repository"
        registry_bytes = registry.read_bytes()
        record = json.loads(registry_bytes.decode("utf-8"))
        manifest_bytes = manifest_path.read_bytes()
    except Exception:  # unreadable or hostile input is never a pass
        return GRANT_MISSING, "ratification registry or manifest unreadable"
    ratification = record.get(spec.ratification_record_key) if isinstance(record, dict) else None
    if not isinstance(ratification, dict) or ratification.get("status") != "RATIFIED":
        return GRANT_MISSING, f"ratification registry holds no RATIFIED manifest v{spec.version} record"
    pinned = ratification.get("manifest_pin")
    if (not isinstance(pinned, dict) or pinned.get("manifest_file_sha256") != file_sha256(manifest_bytes)
            or pinned.get("manifest_version") != spec.version):
        return GRANT_MISMATCH, "ratification registry does not pin this manifest's bytes"
    if ratification.get("live_effect") != "NONE":
        return GRANT_MISMATCH, "ratification is not PAPER-only with no live effect"
    if file_sha256(registry_bytes) != spec.ratification_registry_sha256:
        return GRANT_MISMATCH, "ratification registry differs from the sealed record pinned in code"
    return None


def _verify_exp002_parameters(policy: Mapping[str, Any], root: Path) -> tuple[str, str] | None:
    """EXP-002's parameters in a v3 manifest must equal the sealed v5.85 grant (its manifest pin names v2)."""

    try:
        registry_bytes = (root / EXPECTED_GRANT_REGISTRY_PATH).read_bytes()
        record = json.loads(registry_bytes.decode("utf-8"))
    except Exception:
        return GRANT_MISSING, "EXP-002 grant registry unreadable"
    if file_sha256(registry_bytes) != EXPECTED_GRANT_REGISTRY_SHA256:
        return GRANT_MISMATCH, "grant registry differs from the sealed record pinned in code"
    grant = record.get(GRANT_RECORD_KEY) if isinstance(record, dict) else None
    if not isinstance(grant, dict) or grant.get("grant_id") != EXPECTED_GRANT_ID or grant.get("status") != "GRANTED":
        return GRANT_MISSING, "grant registry holds no GRANTED EXP-002 grant"
    parameters = grant.get("parameters")
    if (not isinstance(parameters, dict) or set(parameters) != set(EXP002_SWITCHES)
            or any(not _same(parameters[k], policy.get(k)) for k in EXP002_SWITCHES)):
        return GRANT_MISMATCH, "manifest EXP-002 parameters differ from the registry grant"
    if grant.get("live_effect") != "NONE" or parameters.get("exp002_paper_only") is not True:
        return GRANT_MISMATCH, "grant is not PAPER-only with no live effect"
    return None


__all__ = [
    "BASE_SWITCHES", "BLOCK_NEW_RISK", "CRITICAL_SWITCHES", "CRITICAL_SWITCHES_V3", "CRITICAL_SWITCHES_V4",
    "EXP002_SWITCHES", "FOREX_SWITCHES", "LEVERAGE_SWITCHES", "MANIFEST_V2_PATH", "MANIFEST_V3_PATH",
    "V4_EXPECTED_PROPOSAL_ID", "V4_EXPECTED_REGISTRY_ID", "V4_RATIFICATION_RECORD_KEY", "V4_RATIFICATION_REGISTRY_ID",
    "V4_RATIFICATION_REGISTRY_PATH", "V4_RATIFICATION_REGISTRY_SHA256", "V3_EXPECTED_PROPOSAL_ID", "V3_EXPECTED_REGISTRY_ID",
    "V3_RATIFICATION_RECORD_KEY", "V3_RATIFICATION_REGISTRY_ID", "V3_RATIFICATION_REGISTRY_PATH",
    "V3_RATIFICATION_REGISTRY_SHA256", "EXPECTED_GRANT_ID",
    "EXPECTED_GRANT_REGISTRY_ID", "EXPECTED_GRANT_REGISTRY_SHA256", "GRANT_MISMATCH", "GRANT_MISSING", "OWNER_RATIFIED", "EXPECTED_PROPOSAL_ID", "EXPECTED_REGISTRY_ID", "INTEGRITY_FAILED",
    "LIVE_REFUSED", "MALFORMED", "MANIFEST_PATH", "MATCH", "MISSING", "POLICY_MISMATCH", "PROPOSAL_MISMATCH",
    "PolicyManifestCheck", "REGISTRY_MISMATCH", "file_sha256", "integrity_digest", "runtime_policy", "verify",
]

