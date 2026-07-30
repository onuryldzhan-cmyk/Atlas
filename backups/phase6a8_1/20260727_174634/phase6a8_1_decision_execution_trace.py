from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "phase6_decision_execution_trace"


def safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {
            str(k): safe_value(v)
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [safe_value(v) for v in value]

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return safe_value(to_dict())
        except Exception:
            pass

    if hasattr(value, "__dict__"):
        try:
            return safe_value(vars(value))
        except Exception:
            pass

    return repr(value)


def append_event(events: list[dict[str, Any]], stage: str, **payload: Any) -> None:
    events.append(
        {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "stage": stage,
            **{
                key: safe_value(value)
                for key, value in payload.items()
            },
        }
    )


def main() -> int:
    print("=" * 72)
    print("ATLAS PHASE 6A8.1 - DECISION / EXECUTION TRACE")
    print("=" * 72)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    events: list[dict[str, Any]] = []
    app = None

    try:
        from core.application import AtlasApplication

        app = AtlasApplication(
            execution_mode="PAPER",
            symbols=["BTCUSDT"],
            market_interval=2.0,
        )

        loop = app.market_loop
        brain = app.brain
        execution = app.execution

        original_brain = brain.analyze_and_decide
        original_normalize = loop.normalize_decision
        original_route = loop.route_execution
        original_execute = execution.execute

        def traced_brain(*args: Any, **kwargs: Any) -> Any:
            symbol = args[0] if args else kwargs.get("symbol")
            append_event(
                events,
                "brain.input",
                symbol=symbol,
                market_data=args[1] if len(args) > 1 else kwargs.get("market_data"),
            )
            result = original_brain(*args, **kwargs)
            append_event(
                events,
                "brain.output",
                symbol=symbol,
                raw_decision=result,
            )
            return result

        def traced_normalize(*args: Any, **kwargs: Any) -> Any:
            append_event(
                events,
                "normalize.input",
                raw_decision=kwargs.get("raw_decision"),
                symbol=kwargs.get("symbol"),
                price=kwargs.get("price"),
            )
            result = original_normalize(*args, **kwargs)
            append_event(
                events,
                "normalize.output",
                normalized_decision=result,
            )
            return result

        def traced_route(*args: Any, **kwargs: Any) -> Any:
            append_event(
                events,
                "route.input",
                decision=kwargs.get("decision"),
                market_state=kwargs.get("market_state"),
            )
            result = original_route(*args, **kwargs)
            append_event(
                events,
                "route.output",
                execution_result=result,
            )
            return result

        def traced_execute(*args: Any, **kwargs: Any) -> Any:
            decision = args[0] if args else kwargs.get("decision")
            market_state = args[1] if len(args) > 1 else kwargs.get("market_state")
            append_event(
                events,
                "execution.input",
                decision=decision,
                market_state=market_state,
            )
            try:
                result = original_execute(*args, **kwargs)
            except Exception as exc:
                append_event(
                    events,
                    "execution.exception",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
                raise
            append_event(
                events,
                "execution.output",
                result=result,
            )
            return result

        brain.analyze_and_decide = traced_brain
        loop.normalize_decision = traced_normalize
        loop.route_execution = traced_route
        execution.execute = traced_execute

        append_event(events, "application.start.requested")

        started = app.start()

        append_event(
            events,
            "application.start.result",
            started=started,
            running=app.running,
            started_services=app.started_services,
            errors=app.errors,
        )

        if not started:
            raise RuntimeError("AtlasApplication failed to start.")

        time.sleep(8)

        snapshot = None
        snapshot_fn = getattr(loop, "snapshot", None)
        if not callable(snapshot_fn):
            snapshot_fn = getattr(loop, "health", None)
        if callable(snapshot_fn):
            try:
                snapshot = snapshot_fn()
            except Exception as exc:
                snapshot = {
                    "snapshot_error": repr(exc),
                }

        append_event(
            events,
            "runtime.snapshot",
            snapshot=snapshot,
            metrics=getattr(loop, "metrics", None),
            last_signals=getattr(loop, "last_signals", None),
            last_executions=getattr(loop, "last_executions", None),
        )

        stopped = app.stop()

        append_event(
            events,
            "application.stop.result",
            stopped=stopped,
            running=app.running,
            errors=app.errors,
        )

        report = {
            "phase": "6A8.1",
            "generated_utc": datetime.now(UTC).isoformat(),
            "mode": "PAPER",
            "symbol": "BTCUSDT",
            "duration_seconds": 8,
            "production_source_files_modified": False,
            "events": events,
        }

        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        report_path = REPORT_DIR / f"phase6a8_1_trace_{stamp}.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        text_path = REPORT_DIR / f"phase6a8_1_trace_{stamp}.txt"
        with text_path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(
                    json.dumps(event, ensure_ascii=False)
                    + "\n"
                )

        stage_counts: dict[str, int] = {}
        for event in events:
            stage = event["stage"]
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

        print()
        print("TRACE COUNTS")
        print("-" * 72)
        for stage, count in sorted(stage_counts.items()):
            print(f"{stage:<30} {count}")

        print()
        print(f"JSON report : {report_path}")
        print(f"Text report : {text_path}")

        execution_outputs = [
            event
            for event in events
            if event["stage"] == "execution.output"
        ]

        print()
        print(
            "Execution calls : "
            + str(stage_counts.get("execution.input", 0))
        )
        print(
            "Execution results: "
            + str(len(execution_outputs))
        )
        print(
            "Atlas errors     : "
            + str(len(app.errors))
        )

        print()
        print("PHASE 6A8.1 COMPLETED")
        return 0

    except Exception as exc:
        append_event(
            events,
            "phase.exception",
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
        )

        if app is not None:
            try:
                app.stop()
            except Exception:
                pass

        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        failure_path = REPORT_DIR / f"phase6a8_1_failure_{stamp}.json"
        failure_path.write_text(
            json.dumps(
                {
                    "phase": "6A8.1",
                    "generated_utc": datetime.now(UTC).isoformat(),
                    "events": events,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print()
        print("PHASE 6A8.1 FAILED")
        print(f"Failure report: {failure_path}")
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
