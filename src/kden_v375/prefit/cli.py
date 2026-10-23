"""Command surface for the serial P01--P07 prefit stages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from ..contracts import ContractError, resolve_project_root
from .p01_foundation import run_p01, verify_p01
from .records import make_prefit_run_id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kden_v375.prefit.cli")
    parser.add_argument("--project-root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run-p01", help="publish and seal the P01 contracts")
    run.add_argument("--run-id")
    commands.add_parser("validate-p01", help="verify the sealed P01 PASS and artifacts")

    p02_preflight = commands.add_parser(
        "p02-preflight", help="verify P02 migration inputs without copying or network access"
    )
    p02_preflight.add_argument("--source-root", type=Path, required=True)

    run_p02 = commands.add_parser(
        "run-p02", help="run the owner-controlled P02 truth adoption workflow"
    )
    run_p02.add_argument("--source-root", type=Path, required=True)
    run_p02.add_argument("--run-id", required=True)

    resume_p02 = commands.add_parser(
        "resume-p02", help="resume P02 with the same run ID and migration source"
    )
    resume_p02.add_argument("--source-root", type=Path, required=True)
    resume_p02.add_argument("--run-id", required=True)

    p02_status = commands.add_parser("p02-status", help="show one P02 status snapshot")
    p02_status.add_argument("--run-id", required=True)

    p02_live = commands.add_parser(
        "p02-live-status", help="show append-only P02 progress until a terminal state"
    )
    p02_live.add_argument("--run-id", required=True)
    p02_live.add_argument("--interval-seconds", type=float, default=5.0)
    p02_live.add_argument("--json-lines", action="store_true")

    p02_eta = commands.add_parser("p02-eta", help="show a bounded P02 ETA snapshot")
    p02_eta.add_argument("--run-id", required=True)

    p02_pause = commands.add_parser("p02-pause", help="request a cooperative P02 pause")
    p02_pause.add_argument("--run-id", required=True)

    commands.add_parser(
        "validate-p02", help="deeply verify the sealed P02 PASS and copied evidence"
    )

    commands.add_parser(
        "p03-preflight",
        help="verify P03 predecessors and schedule authority without materializing rows",
    )
    run_p03 = commands.add_parser(
        "run-p03", help="materialize the owner-controlled P03 causal issue substrate"
    )
    run_p03.add_argument("--run-id", required=True)
    resume_p03 = commands.add_parser(
        "resume-p03", help="resume P03 from verified year checkpoints"
    )
    resume_p03.add_argument("--run-id", required=True)
    p03_status = commands.add_parser("p03-status", help="show one P03 status snapshot")
    p03_status.add_argument("--run-id", required=True)
    p03_live = commands.add_parser(
        "p03-live-status", help="show append-only P03 progress until a terminal state"
    )
    p03_live.add_argument("--run-id", required=True)
    p03_live.add_argument("--interval-seconds", type=float, default=5.0)
    p03_live.add_argument("--json-lines", action="store_true")
    p03_eta = commands.add_parser("p03-eta", help="show a bounded P03 ETA snapshot")
    p03_eta.add_argument("--run-id", required=True)
    p03_pause = commands.add_parser("p03-pause", help="request a cooperative P03 pause")
    p03_pause.add_argument("--run-id", required=True)
    commands.add_parser("validate-p03", help="verify the sealed P03 PASS and substrate")

    commands.add_parser(
        "p04-preflight",
        help="verify P04 authorities and registry generation without publishing",
    )
    run_p04 = commands.add_parser(
        "run-p04",
        help="publish and bounded-test the target-free P04 feature contract",
    )
    run_p04.add_argument("--run-id", required=True)
    commands.add_parser(
        "validate-p04",
        help="verify the sealed P04 registry, schemas, and bounded cases",
    )

    commands.add_parser(
        "p05-preflight",
        help="verify P05 authorities and local capacity without materializing rows",
    )
    run_p05 = commands.add_parser(
        "run-p05",
        help="run the owner-controlled full-history P05 materialization",
    )
    run_p05.add_argument("--run-id", required=True)
    resume_p05 = commands.add_parser(
        "resume-p05",
        help="resume P05 from verified target-day and target-year checkpoints",
    )
    resume_p05.add_argument("--run-id", required=True)
    p05_status = commands.add_parser("p05-status", help="show one P05 status snapshot")
    p05_status.add_argument("--run-id", required=True)
    p05_live = commands.add_parser(
        "p05-live-status", help="show append-only P05 progress until a terminal state"
    )
    p05_live.add_argument("--run-id", required=True)
    p05_live.add_argument("--interval-seconds", type=float, default=5.0)
    p05_live.add_argument("--json-lines", action="store_true")
    p05_eta = commands.add_parser("p05-eta", help="show a recent-performance P05 ETA")
    p05_eta.add_argument("--run-id", required=True)
    p05_pause = commands.add_parser("p05-pause", help="request a cooperative P05 pause")
    p05_pause.add_argument("--run-id", required=True)
    commands.add_parser(
        "validate-p05",
        help="verify the sealed P05 target-free universal substrate",
    )
    commands.add_parser(
        "p06-preflight",
        help="verify P06 authorities and scan plan without reading full partitions",
    )
    run_p06 = commands.add_parser(
        "run-p06",
        help="run the owner-controlled full-substrate P06 acceptance and freeze",
    )
    run_p06.add_argument("--run-id", required=True)
    resume_p06 = commands.add_parser(
        "resume-p06",
        help="resume P06 from verified acceptance checkpoints",
    )
    resume_p06.add_argument("--run-id", required=True)
    p06_status = commands.add_parser("p06-status", help="show one P06 status snapshot")
    p06_status.add_argument("--run-id", required=True)
    p06_live = commands.add_parser(
        "p06-live-status", help="show append-only P06 progress until a terminal state"
    )
    p06_live.add_argument("--run-id", required=True)
    p06_live.add_argument("--interval-seconds", type=float, default=5.0)
    p06_live.add_argument("--json-lines", action="store_true")
    p06_eta = commands.add_parser("p06-eta", help="show a recent-performance P06 ETA")
    p06_eta.add_argument("--run-id", required=True)
    p06_pause = commands.add_parser("p06-pause", help="request a cooperative P06 pause")
    p06_pause.add_argument("--run-id", required=True)
    commands.add_parser(
        "validate-p06",
        help="verify the sealed P06 substrate freeze and PASS records",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = resolve_project_root(args.project_root)
        if args.command == "run-p01":
            run_id = args.run_id or make_prefit_run_id(1, "ordinary", "foundation")
            result = run_p01(project_root=root, run_id=run_id)
        elif args.command == "validate-p01":
            result = verify_p01(root)
        elif args.command.startswith("p02") or args.command in {
            "run-p02",
            "resume-p02",
            "validate-p02",
        }:
            from .p02_truth import (
                p02_eta,
                p02_live_status,
                p02_pause,
                p02_preflight,
                p02_status,
                run_p02,
                verify_p02,
            )

            if args.command == "p02-preflight":
                result = p02_preflight(root, args.source_root)
            elif args.command == "run-p02":
                result = run_p02(
                    project_root=root,
                    source_root=args.source_root,
                    run_id=args.run_id,
                    resume=False,
                )
            elif args.command == "resume-p02":
                result = run_p02(
                    project_root=root,
                    source_root=args.source_root,
                    run_id=args.run_id,
                    resume=True,
                )
            elif args.command == "p02-status":
                result = p02_status(root, args.run_id)
            elif args.command == "p02-live-status":
                try:
                    p02_live_status(
                        root,
                        args.run_id,
                        interval_seconds=args.interval_seconds,
                        json_lines=args.json_lines,
                    )
                except KeyboardInterrupt:
                    pass
                return 0
            elif args.command == "p02-eta":
                result = p02_eta(root, args.run_id)
            elif args.command == "p02-pause":
                result = p02_pause(root, args.run_id)
            elif args.command == "validate-p02":
                result = verify_p02(root, deep=True)
            else:  # pragma: no cover
                raise ContractError(f"unknown prefit command: {args.command}")
        elif args.command.startswith("p03") or args.command in {
            "run-p03",
            "resume-p03",
            "validate-p03",
        }:
            from .p03_issue_spine import (
                p03_eta,
                p03_live_status,
                p03_pause,
                p03_preflight,
                p03_status,
                run_p03,
                verify_p03,
            )

            if args.command == "p03-preflight":
                result = p03_preflight(root)
            elif args.command == "run-p03":
                result = run_p03(
                    project_root=root,
                    run_id=args.run_id,
                    resume=False,
                )
            elif args.command == "resume-p03":
                result = run_p03(
                    project_root=root,
                    run_id=args.run_id,
                    resume=True,
                )
            elif args.command == "p03-status":
                result = p03_status(root, args.run_id)
            elif args.command == "p03-live-status":
                try:
                    p03_live_status(
                        root,
                        args.run_id,
                        interval_seconds=args.interval_seconds,
                        json_lines=args.json_lines,
                    )
                except KeyboardInterrupt:
                    pass
                return 0
            elif args.command == "p03-eta":
                result = p03_eta(root, args.run_id)
            elif args.command == "p03-pause":
                result = p03_pause(root, args.run_id)
            elif args.command == "validate-p03":
                result = verify_p03(root)
            else:  # pragma: no cover
                raise ContractError(f"unknown prefit command: {args.command}")
        elif args.command.startswith("p04") or args.command in {
            "run-p04",
            "validate-p04",
        }:
            from .p04_features import p04_preflight, run_p04, verify_p04

            if args.command == "p04-preflight":
                result = p04_preflight(root)
            elif args.command == "run-p04":
                result = run_p04(project_root=root, run_id=args.run_id)
            elif args.command == "validate-p04":
                result = verify_p04(root)
            else:  # pragma: no cover
                raise ContractError(f"unknown prefit command: {args.command}")
        elif args.command.startswith("p05") or args.command in {
            "run-p05",
            "resume-p05",
            "validate-p05",
        }:
            from .p05_materialization import (
                p05_eta,
                p05_live_status,
                p05_pause,
                p05_preflight,
                p05_status,
                run_p05,
                verify_p05,
            )

            if args.command == "p05-preflight":
                result = p05_preflight(root)
            elif args.command == "run-p05":
                result = run_p05(project_root=root, run_id=args.run_id, resume=False)
            elif args.command == "resume-p05":
                result = run_p05(project_root=root, run_id=args.run_id, resume=True)
            elif args.command == "p05-status":
                result = p05_status(root, args.run_id)
            elif args.command == "p05-live-status":
                try:
                    p05_live_status(
                        root,
                        args.run_id,
                        interval_seconds=args.interval_seconds,
                        json_lines=args.json_lines,
                    )
                except KeyboardInterrupt:
                    pass
                return 0
            elif args.command == "p05-eta":
                result = p05_eta(root, args.run_id)
            elif args.command == "p05-pause":
                result = p05_pause(root, args.run_id)
            elif args.command == "validate-p05":
                result = verify_p05(root)
            else:  # pragma: no cover
                raise ContractError(f"unknown prefit command: {args.command}")
        else:
            from .p06_acceptance import (
                p06_eta,
                p06_live_status,
                p06_pause,
                p06_preflight,
                p06_status,
                run_p06,
                verify_p06,
            )

            if args.command == "p06-preflight":
                result = p06_preflight(root)
            elif args.command == "run-p06":
                result = run_p06(project_root=root, run_id=args.run_id, resume=False)
            elif args.command == "resume-p06":
                result = run_p06(project_root=root, run_id=args.run_id, resume=True)
            elif args.command == "p06-status":
                result = p06_status(root, args.run_id)
            elif args.command == "p06-live-status":
                try:
                    p06_live_status(
                        root,
                        args.run_id,
                        interval_seconds=args.interval_seconds,
                        json_lines=args.json_lines,
                    )
                except KeyboardInterrupt:
                    pass
                return 0
            elif args.command == "p06-eta":
                result = p06_eta(root, args.run_id)
            elif args.command == "p06-pause":
                result = p06_pause(root, args.run_id)
            elif args.command == "validate-p06":
                result = verify_p06(root)
            else:  # pragma: no cover
                raise ContractError(f"unknown prefit command: {args.command}")
    except (ContractError, OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
