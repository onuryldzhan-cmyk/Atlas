"""
============================================================
ATLAS EXECUTION STATE v2.1
============================================================

Deprecated execution persistence layer retained for compatibility evidence.

This class is not wired into the canonical Atlas application. Any future
reuse must preserve its fail-closed recovery contract.

Responsibilities:

- Active position storage
- Trade lifecycle tracking
- Recovery
- Persistence
- Audit compatibility

============================================================
"""


from pathlib import Path
from datetime import datetime, UTC

import json
import os
import shutil
import threading



class ExecutionStateRecoveryRequired(RuntimeError):
    """Raised when persisted financial state requires reconciliation."""


class ExecutionState:



    VERSION = "2.1"
    COMPONENT_STATUS = "LEGACY_NON_CANONICAL_DEPRECATED"



    def __init__(

        self,

        storage="database",

        audit=None

    ):


        self.lock = threading.RLock()


        self.audit = audit


        self.path = Path(storage)


        self.path.mkdir(

            exist_ok=True

        )


        self.file = (

            self.path /

            "execution_state.json"

        )

        self.recovery_marker_file = (
            self.path / "execution_state.recovery-required.json"
        )


        self.active = {}

        self.history = []

        self.recovered = False

        self.recovery_required = False

        self.load_failed = False

        self.last_error = None


        self.load()



    # ==================================================
    # ADD POSITION
    # ==================================================


    def add(

        self,

        trade

    ):


        self._require_operational()

        with self.lock:


            symbol = trade.get(

                "symbol"

            )


            self.active[symbol] = trade



            self.history.append(

                {

                "event":

                "OPEN",


                "symbol":

                symbol,


                "trade":

                trade,


                "time":

                self.time()

                }

            )



            self.audit_event(

                "POSITION_OPENED",

                trade

            )


            self.save()



            return trade





    # ==================================================
    # CLOSE POSITION
    # ==================================================


    def close(

        self,

        symbol,

        result

    ):


        self._require_operational()

        with self.lock:


            trade = self.active.pop(

                symbol,

                None

            )



            event = {


                "event":

                "CLOSE",


                "symbol":

                symbol,


                "result":

                result,


                "time":

                self.time()


            }



            self.history.append(

                event

            )


            self.audit_event(

                "POSITION_CLOSED",

                event

            )


            self.save()



            return trade





    # ==================================================
    # CHECK
    # ==================================================


    def exists(

        self,

        symbol

    ):


        return symbol in self.active





    def get(

        self,

        symbol

    ):


        return self.active.get(

            symbol

        )





    # ==================================================
    # RECOVERY
    # ==================================================


    def recover(self):


        self.load()

        self._require_operational()


        self.recovered = True



        self.audit_event(

            "RECOVERY",

            {

            "active":

            len(self.active)

            }

        )


        return self.active


    def resolve_recovery(
        self,
        *,
        active,
        history,
        operator_reference,
    ):
        """Persist explicitly reconciled state and clear the recovery gate.

        The unreadable original is preserved before replacement. Calling this
        method is an operator/reconciliation action, not an automatic repair.
        """
        reference = str(operator_reference or "").strip()
        if not reference:
            raise ValueError("operator_reference is required")
        if not isinstance(active, dict) or not isinstance(history, list):
            raise ValueError("reconciled active/history schema is invalid")
        if not self.recovery_required:
            raise RuntimeError("execution state does not require recovery")

        preserved_file = self.file.with_suffix(
            self.file.suffix + ".recovery-original"
        )
        if self.file.exists() and not preserved_file.exists():
            shutil.copy2(self.file, preserved_file)

        previous = (
            self.active,
            self.history,
            self.recovery_required,
            self.load_failed,
            self.last_error,
        )
        self.active = dict(active)
        self.history = list(history)
        self.recovery_required = False
        self.load_failed = False
        self.last_error = None
        try:
            self._save_unchecked()
            self.recovery_marker_file.unlink(missing_ok=True)
        except Exception:
            (
                self.active,
                self.history,
                self.recovery_required,
                self.load_failed,
                self.last_error,
            ) = previous
            raise

        self.recovered = True
        self.audit_event(
            "RECOVERY_RESOLVED",
            {
                "operator_reference": reference,
                "active": len(self.active),
                "preserved_file": str(preserved_file),
            },
        )
        return dict(self.active)


    def _require_operational(self):
        if self.recovery_required:
            raise ExecutionStateRecoveryRequired(
                "execution state requires explicit operator reconciliation"
            )


    def _write_recovery_marker(self):
        """Persist a data-free recovery gate for restart safety."""
        temporary_file = self.recovery_marker_file.with_suffix(
            self.recovery_marker_file.suffix + ".tmp"
        )
        payload = {
            "version": "1.0",
            "recovery_required": True,
            "source_file": str(self.file),
            "error": self.last_error,
        }
        try:
            with temporary_file.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_file, self.recovery_marker_file)
            return True
        except Exception:
            temporary_file.unlink(missing_ok=True)
            return False





    # ==================================================
    # STORAGE
    # ==================================================


    def save(self):
        """
        Persist the complete execution-state snapshot atomically.

        The last valid state file is preserved until the new snapshot
        has been completely serialized, flushed, synchronized to disk,
        and atomically promoted into place.
        """

        self._require_operational()
        self._save_unchecked()


    def _save_unchecked(self):
        temporary_file = self.file.with_suffix(
            self.file.suffix + ".tmp"
        )

        payload = {
            "version": self.VERSION,
            "active": self.active,
            "history": self.history,
            "updated": self.time(),
        }

        try:
            self.file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with temporary_file.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as stream:
                json.dump(
                    payload,
                    stream,
                    ensure_ascii=False,
                    indent=4,
                    default=str,
                )

                stream.flush()

                os.fsync(
                    stream.fileno()
                )

            os.replace(
                temporary_file,
                self.file,
            )

        except Exception:
            try:
                temporary_file.unlink(
                    missing_ok=True
                )

            except Exception:
                pass

            raise


    def load(self):


        if not self.file.exists():
            if self.recovery_marker_file.exists():
                self.recovery_required = True
                self.load_failed = True
                self.last_error = {
                    "type": "PersistedRecoveryMarker",
                    "message": "explicit reconciliation remains required",
                    "time": self.time(),
                }
            else:
                self.recovery_required = False
                self.load_failed = False
                self.last_error = None
            return



        try:


            with self.file.open("r", encoding="utf-8") as stream:
                data = json.load(stream)

            if not isinstance(data, dict):
                raise ValueError("execution state root must be an object")
            if data.get("version") != self.VERSION:
                raise ValueError("unsupported execution state version")
            active = data.get("active")
            history = data.get("history")
            if not isinstance(active, dict) or not isinstance(history, list):
                raise ValueError("execution state schema is invalid")

            self.active = active
            self.history = history
            if self.recovery_marker_file.exists():
                self.recovery_required = True
                self.load_failed = True
                self.last_error = {
                    "type": "PersistedRecoveryMarker",
                    "message": "explicit reconciliation remains required",
                    "time": self.time(),
                }
            else:
                self.recovery_required = False
                self.load_failed = False
                self.last_error = None

        except Exception as exc:
            self.active = {}
            self.history = []
            self.recovery_required = True
            self.load_failed = True
            self.last_error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "time": self.time(),
            }
            self._write_recovery_marker()
            self.audit_event(
                "EXECUTION_STATE_RECOVERY_REQUIRED",
                {
                    "error_type": type(exc).__name__,
                    "file": str(self.file),
                },
            )





    # ==================================================
    # AUDIT
    # ==================================================


    def audit_event(

        self,

        event,

        data

    ):


        if self.audit:


            if hasattr(

                self.audit,

                "record"

            ):


                self.audit.record(

                    event,

                    data

                )





    def time(self):


        return datetime.now(

            UTC

        ).isoformat()





    # ==================================================
    # STATUS
    # ==================================================


    def status(self):


        return {


            "version":

            self.VERSION,


            "active":

            len(self.active),


            "history":

            len(self.history),


            "recovered":

            self.recovered,


            "component_status":

            self.COMPONENT_STATUS,


            "recovery_required":

            self.recovery_required,


            "load_failed":

            self.load_failed,


            "last_error":

            dict(self.last_error) if self.last_error else None,


            "recovery_marker":

            str(self.recovery_marker_file),


            "file":

            str(self.file)

        }
