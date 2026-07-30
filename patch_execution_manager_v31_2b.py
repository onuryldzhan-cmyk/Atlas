from __future__ import annotations

from pathlib import Path
import shutil


FILE_PATH = Path(
    "core/execution_manager.py"
)

BACKUP_PATH = Path(
    "core/execution_manager_v31_2a_backup.py"
)


def replace_once(
    source: str,
    old: str,
    new: str,
    description: str,
) -> str:
    count = source.count(
        old
    )

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
        'Expected VERSION = "31.2" was not found. '
        "Patch stopped."
    )

if "def _record_audit_failure(" in source:
    raise RuntimeError(
        "Audit failure incident support already exists. "
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
# 1. INSERT AUDIT FAILURE RECORDER
# ============================================================

write_method_marker = '''    def _write_audit_event(
'''

new_helper = '''    def _record_audit_failure(
        self,
        *,
        event_type: str,
        request: ExecutionRequest,
        error: Exception,
        stage: str = "RUNTIME_AUDIT_WRITE",
    ) -> None:
        """
        Record one runtime audit storage incident.

        This method extends the existing audit system without
        replacing audit persistence, execution routing, risk,
        idempotency, or result handling.

        The v31.2 policy is observational:
        - mark audit runtime as degraded
        - retain incident details
        - expose state through health() and status()
        - do not yet halt execution
        """

        request_id = str(
            getattr(
                request,
                "request_id",
                "",
            )
        ).strip() or None

        failure = {
            "stage": stage,
            "event_type": str(
                event_type
            ).strip().upper(),
            "request_id": request_id,
            "error_type": type(
                error
            ).__name__,
            "error": str(
                error
            ),
            "manager_version": self.VERSION,
            "mode": self.mode,
        }

        with self._lock:
            self.audit_runtime_state = (
                "AUDIT_DEGRADED"
            )

            self.audit_incident_count += 1

            self.last_audit_failure = dict(
                failure
            )

'''

source = replace_once(
    source,
    write_method_marker,
    new_helper + write_method_marker,
    "Audit failure recorder insertion",
)


# ============================================================
# 2. CALL INCIDENT RECORDER FROM AUDIT EXCEPTION
# ============================================================

old_exception_block = '''        except Exception as exc:
            with self._lock:
                self.stats[
                    "audit_write_failures"
                ] += 1

            logger.exception(
                "Execution audit event write failed "
                "type=%s request_id=%s error=%s",
                event_type,
                getattr(
                    request,
                    "request_id",
                    None,
                ),
                exc,
            )

            return None
'''

new_exception_block = '''        except Exception as exc:
            with self._lock:
                self.stats[
                    "audit_write_failures"
                ] += 1

            self._record_audit_failure(
                event_type=event_type,
                request=request,
                error=exc,
            )

            logger.exception(
                "Execution audit event write failed "
                "type=%s request_id=%s error=%s",
                event_type,
                getattr(
                    request,
                    "request_id",
                    None,
                ),
                exc,
            )

            return None
'''

source = replace_once(
    source,
    old_exception_block,
    new_exception_block,
    "Audit exception incident integration",
)


# ============================================================
# WRITE
# ============================================================

FILE_PATH.write_text(
    source,
    encoding="utf-8",
)


print("=" * 76)
print("ATLAS EXECUTION MANAGER v31.2-B PATCH")
print("=" * 76)
print("FILE                    :", FILE_PATH)
print("BACKUP                  :", BACKUP_PATH)
print("AUDIT FAILURE RECORDER  : ADDED")
print("AUDIT DEGRADED STATE    : ADDED")
print("INCIDENT COUNTER        : ADDED")
print("LAST FAILURE DETAILS    : ADDED")
print("EXECUTION FLOW          : UNCHANGED")
print("EXECUTION HALT          : NOT ENABLED")
print("PATCH STATUS            : SUCCESS")
print("=" * 76)
