"""Command-line control surface for the serial KDEN v3.75 pipeline."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .contracts import (
    ContractError,
    ExclusiveRunLock,
    PauseController,
    PauseRequested,
    RunStateStore,
    load_project_paths,
    resolve_project_root,
    validate_run_id,
    validate_runtime_isolation,
    validate_scope,
    verify_step_pass,
)
from .logging import append_event
from .monitoring import build_monitor_snapshot, live_status


STEP_MODULES = {
    0: "kden_v375.steps.step_00_initialize",
    1: "kden_v375.steps.step_01_registries",
    2: "kden_v375.steps.step_02_cycle_schedule",
    3: "kden_v375.steps.step_03_r14_request_plans",
    4: "kden_v375.steps.step_04_pilot",
    5: "kden_v375.steps.step_05_r14_acquisition",
    6: "kden_v375.steps.step_06_wrfsubhf",
    7: "kden_v375.steps.step_07_archive_readers",
    8: "kden_v375.steps.step_08_acceptance",
}


def _root(value: str | None) -> Path:
    return resolve_project_root(value)


def _emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _run_step(
    *,
    project_root: Path,
    step_no: int,
    run_id: str,
    scope: str,
    resume: bool,
) -> dict[str, Any]:
    validate_scope(step_no, scope)
    validate_run_id(run_id, step_no=step_no, scope=scope)
    paths = load_project_paths(project_root)
    store = RunStateStore(project_root, run_id)
    existing = store.initialize()
    module = importlib.import_module(STEP_MODULES[step_no])
    if existing["status"] == "PASS":
        if hasattr(module, "verify_pass"):
            return module.verify_pass(project_root)
        return verify_step_pass(project_root, step_no)
    if existing["status"] in {"PAUSED", "PAUSE_REQUESTED"} and not resume:
        raise ContractError(f"run {run_id} is paused; use resume")
    if resume and existing["status"] not in {"PAUSED", "PAUSE_REQUESTED", "FAILED"}:
        raise ContractError(f"run {run_id} is not resumable from {existing['status']}")

    pause = PauseController(store.pause_path)
    if resume:
        pause.clear()
    with ExclusiveRunLock(paths.state / f"STEP_{step_no:02d}.lock"):
        pause.install()
        store.transition("RUNNING", message="resumed" if resume else "started")
        append_event(
            store.events_path,
            run_id=run_id,
            step_id=f"STEP_{step_no:02d}",
            severity="INFO",
            event_code="RUN_RESUMED" if resume else "RUN_STARTED",
            details={"scope": scope},
        )
        try:
            result = module.run(project_root=project_root, run_id=run_id, pause=pause)
        except PauseRequested as exc:
            store.transition("PAUSED", message=str(exc))
            append_event(
                store.events_path,
                run_id=run_id,
                step_id=f"STEP_{step_no:02d}",
                severity="INFO",
                event_code="RUN_PAUSED",
                details={"reason": str(exc)},
            )
            return {"run_id": run_id, "step_id": f"STEP_{step_no:02d}", "status": "PAUSED"}
        except Exception as exc:
            store.transition("FAILED", message=f"{type(exc).__name__}: {exc}")
            append_event(
                store.events_path,
                run_id=run_id,
                step_id=f"STEP_{step_no:02d}",
                severity="ERROR",
                event_code="RUN_FAILED",
                details={"error_type": type(exc).__name__, "error": str(exc)},
            )
            raise
        else:
            pause.clear()
            store.transition("PASS", message="step gate passed")
            append_event(
                store.events_path,
                run_id=run_id,
                step_id=f"STEP_{step_no:02d}",
                severity="INFO",
                event_code="RUN_PASSED",
                details={"record_sha256": result["record_sha256"]},
            )
            return result
        finally:
            pause.restore()


def _status(project_root: Path, run_id: str | None) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    if run_id is not None:
        state = RunStateStore(project_root, run_id).read()
        progress_path = paths.runs / run_id / "step03_r14_progress.json"
        if progress_path.is_file():
            with progress_path.open("r", encoding="utf-8") as stream:
                state = {**state, "step03_r14_progress": json.load(stream)}
        state = {**state, "monitoring": build_monitor_snapshot(project_root, run_id)}
        return state
    runs: list[dict[str, Any]] = []
    for path in sorted(paths.runs.glob("*/run.json")):
        try:
            with path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
        except (OSError, json.JSONDecodeError):
            value = {"run_id": path.parent.name, "status": "UNREADABLE"}
        runs.append(value)
    steps: list[dict[str, Any]] = []
    for pass_path in sorted(paths.state.glob("STEP_??_PASS.json")):
        step_no = int(pass_path.stem.split("_")[1])
        try:
            record = verify_step_pass(project_root, step_no)
            steps.append(
                {
                    "step_id": record["step_id"],
                    "status": "PASS",
                    "record_sha256": record["record_sha256"],
                }
            )
        except ContractError as exc:
            steps.append({"step_id": f"STEP_{step_no:02d}", "status": "STALE", "error": str(exc)})
    r14_steps: list[dict[str, Any]] = []
    from .r14_records import verify_r14_attestation

    for record_id in ("STEP_01_R14", "STEP_02_R14"):
        try:
            record = verify_r14_attestation(project_root, record_id)
            r14_steps.append(
                {
                    "step_id": record_id,
                    "status": "PASS",
                    "record_sha256": record["record_sha256"],
                }
            )
        except (ContractError, OSError):
            continue
    try:
        from .r14_plan_records import verify_r14_step03_pass

        record = verify_r14_step03_pass(project_root)
        r14_steps.append(
            {
                "step_id": "STEP_03_R14",
                "status": "PASS",
                "record_sha256": record["record_sha256"],
            }
        )
    except (ContractError, OSError):
        pass
    try:
        from .r14_pilot_records import verify_r14_step04_pass

        record = verify_r14_step04_pass(project_root)
        r14_steps.append(
            {
                "step_id": "STEP_04_R14",
                "status": "PASS",
                "record_sha256": record["record_sha256"],
            }
        )
    except (ContractError, OSError):
        pass
    try:
        from .acquisition.records import (
            verify_combined_pass,
            verify_product_pass,
            verify_ready_record,
        )

        ready = verify_ready_record(project_root)
        r14_steps.append(
            {
                "step_id": "R14_READY_FOR_OWNER_RUN",
                "status": "PASS",
                "record_sha256": ready["record_sha256"],
            }
        )
        for product, label in (
            ("wrfsfcf", "WRFSFCF_R14"),
            ("wrfsubhf", "WRFSUBHF_Q05_R14"),
        ):
            try:
                record = verify_product_pass(
                    project_root, product, deep=False
                )
            except (ContractError, OSError):
                continue
            r14_steps.append(
                {
                    "step_id": label,
                    "status": "PASS",
                    "record_sha256": record["record_sha256"],
                }
            )
        try:
            combined = verify_combined_pass(project_root, deep=False)
        except (ContractError, OSError):
            pass
        else:
            r14_steps.append(
                {
                    "step_id": "R14",
                    "status": "PASS",
                    "record_sha256": combined["record_sha256"],
                }
            )
    except (ContractError, OSError):
        pass
    return {
        "project_root": str(project_root),
        "steps": steps,
        "r14_steps": r14_steps,
        "runs": runs,
    }


def _validate(project_root: Path, step_no: int | None) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    isolation = validate_runtime_isolation(project_root)
    selected: list[int]
    if step_no is not None:
        selected = [step_no]
    else:
        selected = sorted(
            int(path.stem.split("_")[1]) for path in paths.state.glob("STEP_??_PASS.json")
        )
    if not selected:
        raise ContractError("no PASS records are available to validate")
    records: list[dict[str, Any]] = []
    for number in selected:
        module = importlib.import_module(STEP_MODULES[number])
        if hasattr(module, "verify_pass"):
            records.append(module.verify_pass(project_root))
        else:
            records.append(verify_step_pass(project_root, number))
    return {
        "status": "VALID",
        "validated_steps": [
            record.get("record_id", record.get("step_id")) for record in records
        ],
        "record_sha256": {
            record.get("record_id", record.get("step_id")): record["record_sha256"]
            for record in records
        },
        "runtime_isolation": isolation,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kden-v375")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_step = subparsers.add_parser("run-step", help="run one serial project step")
    run_step.add_argument("step", type=int, choices=range(0, 9))
    run_step.add_argument("--run-id", required=True)
    run_step.add_argument(
        "--scope",
        choices=("ordinary", "diagnostic", "owner-full", "validation", "synthetic"),
        default="ordinary",
    )
    run_step.add_argument("--project-root")

    status = subparsers.add_parser("status", help="show immutable step and run state")
    status.add_argument("--run-id")
    status.add_argument("--project-root")

    live = subparsers.add_parser(
        "live-status", help="follow a run with non-clearing progress and ETA updates"
    )
    live.add_argument("--run-id", required=True)
    live.add_argument("--interval-seconds", type=float, default=5.0)
    live.add_argument("--recent-records", type=int, default=20)
    live.add_argument("--json-lines", action="store_true")
    live.add_argument("--project-root")

    eta = subparsers.add_parser(
        "eta", help="estimate remaining active runtime from recent committed work"
    )
    eta.add_argument("--run-id", required=True)
    eta.add_argument("--recent-records", type=int, default=20)
    eta.add_argument("--project-root")

    pilot_preflight = subparsers.add_parser(
        "pilot-preflight", help="validate the bounded R14 pilot without network access"
    )
    pilot_preflight.add_argument("--project-root")

    acquisition_preflight = subparsers.add_parser(
        "acquisition-preflight",
        help="validate the complete R14 owner run without network access",
    )
    acquisition_preflight.add_argument("--project-root")

    pause_run = subparsers.add_parser("pause-run", help="request a cooperative pause")
    pause_run.add_argument("run_id")
    pause_run.add_argument("--project-root")

    resume = subparsers.add_parser("resume", help="resume a paused run with the same run ID")
    resume.add_argument("run_id")
    resume.add_argument("--project-root")

    validate = subparsers.add_parser("validate-only", help="validate state without acquisition")
    validate.add_argument("--step", type=int, choices=range(0, 9))
    validate.add_argument("--project-root")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        project_root = _root(getattr(args, "project_root", None))
        if args.command == "run-step":
            result = _run_step(
                project_root=project_root,
                step_no=args.step,
                run_id=args.run_id,
                scope=args.scope,
                resume=False,
            )
        elif args.command == "status":
            result = _status(project_root, args.run_id)
        elif args.command == "live-status":
            try:
                live_status(
                    project_root,
                    args.run_id,
                    interval_seconds=args.interval_seconds,
                    recent_records=args.recent_records,
                    json_lines=args.json_lines,
                )
            except KeyboardInterrupt:
                pass
            return 0
        elif args.command == "eta":
            result = build_monitor_snapshot(
                project_root, args.run_id, recent_records=args.recent_records
            )
        elif args.command == "pilot-preflight":
            from .pilot import pilot_preflight

            result = pilot_preflight(project_root)
        elif args.command == "acquisition-preflight":
            from .acquisition.workflow import acquisition_preflight

            result = acquisition_preflight(project_root)
        elif args.command == "pause-run":
            result = RunStateStore(project_root, args.run_id).request_pause()
        elif args.command == "resume":
            store = RunStateStore(project_root, args.run_id)
            state = store.read()
            identity = validate_run_id(args.run_id)
            result = _run_step(
                project_root=project_root,
                step_no=identity.step_no,
                run_id=args.run_id,
                scope=identity.scope,
                resume=True,
            )
            if state["step_id"] != f"STEP_{identity.step_no:02d}":
                raise ContractError("run-state step disagrees with run ID")
        elif args.command == "validate-only":
            result = _validate(project_root, args.step)
        else:  # pragma: no cover
            parser.error("unknown command")
            return 2
    except (ContractError, NotImplementedError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _emit(result)
    return 0
