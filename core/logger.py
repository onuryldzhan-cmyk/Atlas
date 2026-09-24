"""
Atlas AI Logger System v6.0

Responsibility:
- Attach the durable MarketLoop telemetry file (registry v4.71)
- Provide named loggers

History
-------

Until registry v4.71 this class was constructed and registered by
AtlasApplication but initialize() was never called anywhere, and no
record says why. It could not simply start being called as written:

- its target, ``logs/atlas.log``, was relative to the process working
  directory, which puts it inside the OneDrive-synced installation tree
  whenever Atlas starts from the repository root (the hazard ADR-0007
  fixed for durable state);
- it added a second console handler to the root logger, which would have
  printed every existing console log line twice;
- it attached its file to the root logger, persisting every log line of
  every module - a general logging overhaul, not the two measurements
  the grant covers.

initialize() therefore now attaches exactly one file, to exactly one
non-propagating telemetry logger, in an operator-configured directory,
and touches no root handler, root level, or console output. With no
directory configured it writes nothing.
"""

from __future__ import annotations

import logging
import logging.handlers
import queue
import threading
from pathlib import Path

TELEMETRY_LOG_FILE = "market_loop_telemetry.jsonl"

# Upper bound on how long close() waits for queued records to be written.
# A hung volume must not hang AtlasApplication.stop() forever.
TELEMETRY_CLOSE_TIMEOUT_SECONDS = 5.0

# Marks the handler this class attaches, so a second concurrent durable
# handler on the same telemetry logger can be detected and refused.
_OWNED_HANDLER_ATTRIBUTE = "_atlas_durable_telemetry_handler"

logger = logging.getLogger(
    "AtlasAI.Logger"
)

# Serializes the check-then-attach in initialize(), so two applications
# constructed concurrently cannot both attach a durable handler.
_ATTACH_LOCK = threading.Lock()


class TelemetryHandlerConflictError(RuntimeError):
    """
    The telemetry logger already has an active durable handler.

    Two handlers would write every record twice, silently doubling every
    sample in the evidence the file exists to collect.
    """


class _TelemetryFileWriter:
    """
    The QueueListener's sink: appends one message per line to the file.

    Deliberately NOT a logging.Handler, for two reasons:

    - logging.shutdown() runs at interpreter exit and waits on the lock of
      every registered Handler. A writer stuck in a write to a hung volume
      would then block process exit indefinitely. A plain object is never
      registered, so exit never waits on it.
    - The stdlib Handler.handleError prints a traceback AND the record's
      text to stderr on every failed write, which on a full or failing
      disk would flood the operator console with telemetry lines. Failures
      are counted instead; the first produces one WARNING naming no record
      content.

    Only the listener thread calls handle(), so no lock is needed.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.write_failures = 0
        # Opened now, so an unusable directory fails at construction.
        # newline="\n" keeps the file strict JSON-lines (LF) on Windows.
        self._stream = open(
            path,
            mode="a",
            encoding="utf-8",
            newline="\n",
        )

    def handle(self, record: logging.LogRecord) -> None:
        try:
            self._stream.write(
                record.getMessage() + "\n"
            )
            self._stream.flush()

        except Exception:
            self.write_failures += 1

            if self.write_failures == 1:
                logger.warning(
                    "Durable telemetry write failed; further failures "
                    "are counted, not reported: %s",
                    self.path,
                )

    def close(self) -> None:
        self._stream.close()


class _BoundedQueueListener(logging.handlers.QueueListener):
    """
    QueueListener whose stop waits a bounded time.

    The stdlib stop() joins its thread with no timeout, so a listener stuck
    in a write to a hung volume would block shutdown indefinitely.
    """

    def stop_within(self, timeout: float) -> bool:
        thread = self._thread

        if thread is None:
            return True

        self.enqueue_sentinel()
        thread.join(timeout)

        if thread.is_alive():
            return False

        self._thread = None

        return True


class AtlasLogger:
    """
    Durable telemetry file manager.
    """

    def __init__(
        self,
        name="AtlasAI",
        level=logging.INFO,
        *,
        log_directory: str | Path | None = None,
        telemetry_logger_name: str | None = None,
    ):

        self.name = name

        self.level = level

        self.log_directory = (
            None
            if log_directory is None
            else Path(log_directory)
        )

        self.telemetry_logger_name = telemetry_logger_name

        self.log_file: Path | None = None

        self._initialized = False

        self._file_handler: _TelemetryFileWriter | None = None

        self._queue_handler: logging.handlers.QueueHandler | None = None

        self._listener: _BoundedQueueListener | None = None

    @property
    def enabled(self) -> bool:
        return self._listener is not None

    @property
    def write_failures(self) -> int:
        handler = self._file_handler

        return 0 if handler is None else handler.write_failures

    def initialize(self):
        """
        Attach the durable telemetry file, or record that it is disabled.

        The file is opened here, so an unwritable directory fails loudly
        at construction rather than at the first cycle. Writes happen on
        a QueueListener thread, never on the caller's thread, so a slow
        disk cannot delay a MarketLoop cycle.
        """

        if self._initialized:
            return

        if self.log_directory is None:
            self._initialized = True

            logger.info(
                "Durable telemetry log disabled: no log directory "
                "configured"
            )

            return

        if not self.telemetry_logger_name:
            raise ValueError(
                "telemetry_logger_name is required when a log "
                "directory is configured"
            )

        # Defence in depth for an explicit constructor argument, which
        # (like state_directory) bypasses the environment validator: a
        # relative path would make the file follow the working directory.
        if not self.log_directory.is_absolute():
            raise ValueError(
                f"log_directory must be an absolute path, got "
                f"{str(self.log_directory)!r}"
            )

        with _ATTACH_LOCK:
            self._attach()

    def _attach(self):
        target = logging.getLogger(
            self.telemetry_logger_name
        )

        if any(
            getattr(
                handler,
                _OWNED_HANDLER_ATTRIBUTE,
                False,
            )
            for handler in target.handlers
        ):
            raise TelemetryHandlerConflictError(
                f"{self.telemetry_logger_name} already has an active "
                f"durable telemetry handler in this process"
            )

        log_file = self.log_directory / TELEMETRY_LOG_FILE

        file_handler = _TelemetryFileWriter(
            log_file
        )

        try:
            record_queue: queue.SimpleQueue = queue.SimpleQueue()

            queue_handler = logging.handlers.QueueHandler(
                record_queue
            )

            setattr(
                queue_handler,
                _OWNED_HANDLER_ATTRIBUTE,
                True,
            )

            listener = _BoundedQueueListener(
                record_queue,
                file_handler,
            )

            listener.start()

        except Exception:
            file_handler.close()
            raise

        target.addHandler(
            queue_handler
        )

        self._file_handler = file_handler
        self._queue_handler = queue_handler
        self._listener = listener
        self.log_file = log_file
        self._initialized = True

        logger.info(
            "Durable telemetry log: %s",
            log_file,
        )

    def close(
        self,
        timeout: float = TELEMETRY_CLOSE_TIMEOUT_SECONDS,
    ) -> bool:
        """
        Detach the telemetry handler, drain queued records, close the file.

        Idempotent; a no-op when the telemetry file is disabled. Never
        raises and never blocks much longer than ``timeout``: telemetry is
        observability, so a failure here must not change the outcome of
        the shutdown that calls it. Returns False, after one WARNING, when
        the queue could not be drained or the file could not be closed.
        """

        queue_handler = self._queue_handler
        listener = self._listener
        file_handler = self._file_handler

        self._queue_handler = None
        self._listener = None
        self._file_handler = None

        try:
            if queue_handler is not None and self.telemetry_logger_name:
                logging.getLogger(
                    self.telemetry_logger_name
                ).removeHandler(
                    queue_handler
                )

            if listener is not None and not listener.stop_within(
                timeout
            ):
                # The writer thread is still inside a write: leave the
                # file to it (a daemon thread) rather than closing it
                # underneath the write.
                logger.warning(
                    "Durable telemetry writer did not finish within "
                    "%.1fs; queued records may be lost",
                    timeout,
                )

                return False

            if file_handler is not None:
                file_handler.close()

        except Exception:
            logger.warning(
                "Durable telemetry log did not close cleanly",
                exc_info=True,
            )

            return False

        return True

    def get(
        self,
        module_name: str
    ):

        return logging.getLogger(
            module_name
        )
