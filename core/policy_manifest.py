"""Phase-2 G1: the policy manifest - critical runtime policy pinned to governance metadata.

The owner-controlled switches that decide what risk Atlas may take (execution
mode, live enablement, confidence floors, the paper experiment, loss/sleeve/
slippage/fee switches, fusion denominator, ExitGuard, ...) are literals at one
call site in main.py. This module compares the switches the runtime *actually
has* with a versioned manifest under governance/policy/ (kept out of governance/current/, whose files form the registry chain) that names the
governance registry and proposal it belongs to.

It only reads and compares. It never applies a manifest value, never changes
runtime configuration, never claims owner approval (``owner_approval`` is
recorded as written, normally UNKNOWN) and can never enable LIVE: a manifest
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
from decimal import Decimal
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "governance" / "policy" / "ATLAS_POLICY_MANIFEST_v1.json"

# The governance binding this code expects. Changing the manifest's registry or
# proposal is a governance act, so it also needs a code change here.
EXPECTED_REGISTRY_ID = "ATLAS_MILESTONE_REGISTRY_v5.83"
EXPECTED_PROPOSAL_ID = "PHASE2-G1-POLICY-MANIFEST"

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

# Every switch the manifest must cover - no more, no fewer.
CRITICAL_SWITCHES = (
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

_REQUIRED = ("manifest_version", "registry_id", "registry_path", "registry_sha256", "proposal_id",
             "owner_approval", "policy", "integrity")


def _decimal_text(value: Any) -> str:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("non-finite")
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


def _matches(spec: Any, actual: Any) -> bool:
    if actual == UNREADABLE:
        return False
    if isinstance(spec, Mapping):
        allowed = spec.get("one_of")
        return isinstance(allowed, list) and set(spec) == {"one_of"} and any(
            type(actual) is type(a) and actual == a for a in allowed)
    return type(actual) is type(spec) and actual == spec


def verify(runtime: Mapping[str, Any], path: Path | str = MANIFEST_PATH, *,
           repository_root: Path | str = REPOSITORY_ROOT) -> PolicyManifestCheck:
    """Compare ``runtime`` with the manifest at ``path``. Never raises, never writes."""

    runtime = dict(runtime)
    path = Path(path)
    try:
        if not path.is_file():
            return PolicyManifestCheck(MISSING, f"no manifest at {path}", runtime=runtime)
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return PolicyManifestCheck(MALFORMED, f"unreadable manifest: {type(exc).__name__}", runtime=runtime)

    if not isinstance(manifest, dict) or any(k not in manifest for k in _REQUIRED):
        return PolicyManifestCheck(MALFORMED, "manifest is not an object with the required fields", runtime=runtime)
    meta = {"manifest_version": manifest.get("manifest_version"), "registry_id": manifest.get("registry_id"),
            "proposal_id": manifest.get("proposal_id"), "owner_approval": manifest.get("owner_approval"),
            "runtime": runtime}
    policy, integrity = manifest.get("policy"), manifest.get("integrity")
    if not isinstance(policy, dict) or not isinstance(integrity, dict):
        return PolicyManifestCheck(MALFORMED, "policy and integrity must be objects", **meta)
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
        digest = hashlib.sha256(registry.read_bytes()).hexdigest()
    except OSError:
        return PolicyManifestCheck(REGISTRY_MISMATCH, "registry file unreadable", **meta)
    if digest != manifest.get("registry_sha256"):
        return PolicyManifestCheck(REGISTRY_MISMATCH, "registry file changed since the manifest pinned it", **meta)

    if manifest.get("proposal_id") != EXPECTED_PROPOSAL_ID:
        return PolicyManifestCheck(PROPOSAL_MISMATCH,
                                   f"manifest names {manifest.get('proposal_id')!r}, expected {EXPECTED_PROPOSAL_ID}",
                                   **meta)

    mismatches = tuple((name, policy[name], runtime.get(name, UNREADABLE)) for name in CRITICAL_SWITCHES
                       if not _matches(policy[name], runtime.get(name, UNREADABLE)))
    if mismatches:
        return PolicyManifestCheck(POLICY_MISMATCH, f"{len(mismatches)} switch(es) differ from the manifest",
                                   mismatches, **meta)
    return PolicyManifestCheck(MATCH, "runtime policy matches the manifest", **meta)


__all__ = [
    "BLOCK_NEW_RISK", "CRITICAL_SWITCHES", "EXPECTED_PROPOSAL_ID", "EXPECTED_REGISTRY_ID", "INTEGRITY_FAILED",
    "LIVE_REFUSED", "MALFORMED", "MANIFEST_PATH", "MATCH", "MISSING", "POLICY_MISMATCH", "PROPOSAL_MISMATCH",
    "PolicyManifestCheck", "REGISTRY_MISMATCH", "integrity_digest", "runtime_policy", "verify",
]

