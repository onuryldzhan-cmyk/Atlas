from __future__ import annotations

from pathlib import Path
import shutil


FILE_PATH = Path(
    "core/execution_manager.py"
)

BACKUP_PATH = Path(
    "core/execution_manager_v31_2b_backup.py"
)


def replace_once(
    source: str,
    old: str,
    new: str,
    description: str,
) -> str:
    count = source.count(old)

    if count != 1:
        raise RuntimeError(
            f"{description}: expected exactly one match, "
            f"found {count}. No changes were written."
        )

    return source.replace(
        old,
        new,
        1,
    )


if not FILE_PATH.exists():
    raise FileNotFoundError(
        f"File not found: {FILE_PATH.resolve()}"
    )


source = FILE_PATH.read_text(
    encoding="utf-8",
)


# ============================================================
# SAFETY CHECKS
# ============================================================

if 'VERSION = "31.2"' not in source:
    raise RuntimeError(
        'Expected VERSION = "31.2" was not found.'
    )

if "def _record_audit_failure(" not in source:
    raise RuntimeError(
        "v31.2-B audit failure recorder was not found."
    )

if "def _classify_audit_stage(" in source:
    raise RuntimeError(
        "Audit stage classification already exists. "
        "Patch was not applied again."
    )


# ============================================================
# BACKUP
# ============================================================

if not BACKUP_PATH.exists():
    shutil.copy2(
        FILE_PATH,
        BACKUP_PATH,
    )


# ============================================================
# 1. ADD AUDIT STAGE CLASSIFIER
# ============================================================

old_helper_marker = '''    def _record_audit_failure(
'''

new_classifier = '''    def _classify_audit_stage(
        self,
        event_type: str,
    ) -> str:
        """
        Classify an execution audit event by lifecycle stage.

        Classification is intentionally independent from the
        audit storage implementation. It prepares Atlas for
        stage-aware failure policy without changing the current
        execution flow.
        """

        normalized_event_type = str(
            event_type
        ).strip().upper()

        pre_execution_events = {
            "EXECUTION_REQUEST_RECEIVED",
            "EXECUTION_REQUEST_VALIDATED",
            "RISK_APPROVED",
        }

        post_execution_events = {
            "EXECUTION_COMPLETED",
            "EXECUTION_FAILED",
        }

        terminal_decision_events = {
            "EXECUTION_REQUEST_REJECTED",
            "RISK_REJECTED",
        }

        observational_events = {
            "DUPLICATE_REQUEST_PENDING",
            "DUPLICATE_REQUEST_COMPLETED",
            "DUPLICATE_REQUEST_DETECTED",
        }

        if normalized_event_type in pre_execution_events:
            return "PRE_EXECUTION"

        if normalized_event_type in post_execution_events:
            return "POST_EXECUTION"

        if normalized_event_type in terminal_decision_events:
            return "TERMINAL_DECISION"

        if normalized_event_type in observational_events:
            return "OBSERVATIONAL"

        return "UNKNOWN"

'''

source = replace_once(
    source,
    old_helper_marker,
    new_classifier + old_helper_marker,
    "Audit stage classifier insertion",
)


# ============================================================
# 2. CHANGE FAILURE RECORDER DEFAULT STAGE
# ============================================================

old_signature = '''        error: Exception,
        stage: str = "RUNTIME_AUDIT_WRITE",
    ) -> None:
'''

new_signature = '''        error: Exception,
        stage: str | None = None,
    ) -> None:
'''

source = replace_once(
    source,
    old_signature,
    new_signature,
    "Audit failure recorder signature",
)


# ============================================================
# 3. RESOLVE STAGE INSIDE FAILURE RECORDER
# ============================================================

old_request_block = '''        request_id = str(
            getattr(
                request,
                "request_id",
                "",
            )
        ).strip() or None

        failure = {
            "stage": stage,
'''

new_request_block = '''        request_id = str(
            getattr(
                request,
                "request_id",
                "",
            )
        ).strip() or None

        resolved_stage = (
            str(
                stage
            ).strip().upper()
            if stage
            else self._classify_audit_stage(
                event_type
            )
        )

        failure = {
            "stage": resolved_stage,
'''

source = replace_once(
    source,
    old_request_block,
    new_request_block,
    "Resolved audit stage",
)


# ============================================================
# 4. ADD FAILURE CRITICALITY
# ============================================================

old_failure_tail = '''            "manager_version": self.VERSION,
            "mode": self.mode,
        }
'''

new_failure_tail = '''            "manager_version": self.VERSION,
            "mode": self.mode,
            "criticality": (
                "CRITICAL"
                if resolved_stage
                in {
                    "PRE_EXECUTION",
                    "POST_EXECUTION",
                }
                else "WARNING"
            ),
        }
'''

source = replace_once(
    source,
    old_failure_tail,
    new_failure_tail,
    "Audit failure criticality",
)


# ============================================================
# WRITE
# ============================================================

FILE_PATH.write_text(
    source,
    encoding="utf-8",
)


print("=" * 78)
print("ATLAS EXECUTION MANAGER v31.2-C PATCH")
print("=" * 78)
print("FILE                    :", FILE_PATH)
print("BACKUP                  :", BACKUP_PATH)
print("AUDIT STAGE CLASSIFIER  : ADDED")
print("PRE EXECUTION STAGE     : ADDED")
print("POST EXECUTION STAGE    : ADDED")
print("TERMINAL DECISION STAGE : ADDED")
print("OBSERVATIONAL STAGE     : ADDED")
print("INCIDENT CRITICALITY    : ADDED")
print("EXECUTION FLOW          : UNCHANGED")
print("PATCH STATUS            : SUCCESS")
print("=" * 78)
