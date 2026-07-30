from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
import shutil


FILE_PATH = Path("core/execution_manager.py")
BACKUP_PATH = Path(
    "core/execution_manager_v31_1_before_runtime_state.py"
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
        f"ExecutionManager file not found: {FILE_PATH.resolve()}"
    )


source = FILE_PATH.read_text(
    encoding="utf-8",
)


# ============================================================
# SAFETY CHECK
# ============================================================

if 'VERSION = "31.2"' in source:
    raise RuntimeError(
        "ExecutionManager already reports version 31.2. "
        "Patch was not applied again."
    )

if 'VERSION = "31.1"' not in source:
    raise RuntimeError(
        'Expected VERSION = "31.1" was not found. '
        "Patch stopped to protect the existing file."
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
# 1. VERSION
# ============================================================

source = replace_once(
    source,
    'VERSION = "31.1"',
    'VERSION = "31.2"',
    "Version update",
)


# ============================================================
# 2. RUNTIME STATE FIELDS
# ============================================================

old_init_block = '''        self.audit_store = (
            audit_store
            if audit_store is not None
            else AuditEventStore(
                file_path=audit_file,
            )
        )

        self.stats: dict[str, int] = self._new_stats()
'''

new_init_block = '''        self.audit_store = (
            audit_store
            if audit_store is not None
            else AuditEventStore(
                file_path=audit_file,
            )
        )

        # =====================================================
        # OPERATIONAL RUNTIME STATE
        # =====================================================
        #
        # This state extends the existing execution architecture.
        # It does not replace idempotency, audit, risk, routing,
        # persistence, or execution behavior.
        #
        # HEALTHY:
        #   Normal execution admission is permitted.
        #
        # AUDIT_DEGRADED:
        #   At least one runtime audit write has failed.
        #
        # EXECUTION_HALTED:
        #   New execution admission has been stopped.
        #
        # RECOVERY_REQUIRED:
        #   Explicit operator recovery is required.
        self.audit_runtime_state = "HEALTHY"

        self.execution_halted = False

        self.recovery_required = False

        self.last_audit_failure: dict[
            str,
            Any,
        ] | None = None

        self.audit_incident_count = 0

        self.halt_reason: str | None = None

        self.stats: dict[str, int] = self._new_stats()
'''

source = replace_once(
    source,
    old_init_block,
    new_init_block,
    "Runtime state initialization",
)


# ============================================================
# 3. HEALTH CALCULATION
# ============================================================

old_health_condition = '''            healthy = (
                self.running
                and not (
                    self.mode == self.MODE_LIVE
                    and not self.live_execution_enabled
                )
            )
'''

new_health_condition = '''            healthy = (
                self.running
                and not self.execution_halted
                and not self.recovery_required
                and self.audit_runtime_state == "HEALTHY"
                and not (
                    self.mode == self.MODE_LIVE
                    and not self.live_execution_enabled
                )
            )
'''

source = replace_once(
    source,
    old_health_condition,
    new_health_condition,
    "Health calculation",
)


# ============================================================
# 4. HEALTH RUNTIME VISIBILITY
# ============================================================

old_health_output = '''                "live_execution_enabled": (
                    self.live_execution_enabled
                ),
                "statistics": dict(
                    self.stats
                ),
'''

new_health_output = '''                "live_execution_enabled": (
                    self.live_execution_enabled
                ),
                "operational_state": {
                    "audit_runtime_state": (
                        self.audit_runtime_state
                    ),
                    "execution_halted": (
                        self.execution_halted
                    ),
                    "recovery_required": (
                        self.recovery_required
                    ),
                    "halt_reason": (
                        self.halt_reason
                    ),
                    "audit_incident_count": (
                        self.audit_incident_count
                    ),
                    "last_audit_failure": (
                        dict(
                            self.last_audit_failure
                        )
                        if self.last_audit_failure
                        else None
                    ),
                },
                "statistics": dict(
                    self.stats
                ),
'''

source = replace_once(
    source,
    old_health_output,
    new_health_output,
    "Health operational state output",
)


# ============================================================
# 5. STATUS RUNTIME VISIBILITY
# ============================================================

old_status_output = '''                "live_execution_enabled": (
                    self.live_execution_enabled
                ),
                "history": len(
                    self.history
                ),
'''

new_status_output = '''                "live_execution_enabled": (
                    self.live_execution_enabled
                ),
                "operational_state": {
                    "audit_runtime_state": (
                        self.audit_runtime_state
                    ),
                    "execution_halted": (
                        self.execution_halted
                    ),
                    "recovery_required": (
                        self.recovery_required
                    ),
                    "halt_reason": (
                        self.halt_reason
                    ),
                    "audit_incident_count": (
                        self.audit_incident_count
                    ),
                    "last_audit_failure": (
                        dict(
                            self.last_audit_failure
                        )
                        if self.last_audit_failure
                        else None
                    ),
                },
                "history": len(
                    self.history
                ),
'''

source = replace_once(
    source,
    old_status_output,
    new_status_output,
    "Status operational state output",
)


# ============================================================
# WRITE
# ============================================================

FILE_PATH.write_text(
    source,
    encoding="utf-8",
)


print("=" * 72)
print("ATLAS EXECUTION MANAGER v31.2-A PATCH")
print("=" * 72)
print("FILE              :", FILE_PATH)
print("BACKUP            :", BACKUP_PATH)
print("VERSION           : 31.2")
print("RUNTIME STATE     : ADDED")
print("HEALTH VISIBILITY : ADDED")
print("STATUS VISIBILITY : ADDED")
print("EXECUTION FLOW    : UNCHANGED")
print("PATCH STATUS      : SUCCESS")
print("=" * 72)
