#!/usr/bin/env python3
"""Local JSON Game2Mobile operator CLI; writes require explicit commands.

Examples (run from the repository root):
    python3 scripts/g2mctl.py capabilities
    python3 scripts/g2mctl.py status --log /private/boot.txt
    python3 scripts/g2mctl.py next --log /private/boot.txt --run-id <run_id>
    python3 scripts/g2mctl.py status --log /private/boot.txt --app /private/DmIOS.app --profile metal4

No network listener, launch/install or uploads. Explicit local build/export only.
An observed first present is not evidence of a playable game.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

if __package__:
    from .boot_diagnostics import analyze_log
    from .build_identity import IdentityError, ROOT, verify_identity
    from .m1_job_status import JobStatusError, read_job_status
else:
    from boot_diagnostics import analyze_log
    from build_identity import IdentityError, ROOT, verify_identity
    from m1_job_status import JobStatusError, read_job_status

SCHEMA = "game2mobile.operator.v1"
CAPABILITIES = {"capabilities": True, "status": True, "next": True,
                "diagnose": True, "job-status": True, "build": False, "install": False,
                "build-plan": True, "build-local-explicit": True,
                "bundle": True, "inspect-bundle": True,
                "acceptance-template": True, "acceptance-check": True,
                "launch": False, "http_control": False}
ERRORS = {
    "first_present_observed": "FIRST_PRESENT_OBSERVED",
    "no_boot_evidence": "NO_BOOT_EVIDENCE",
    "run_not_found": "RUN_NOT_FOUND",
    "input_error": "BOOT_INPUT_INVALID",
    "invalid_evidence": "BOOT_EVIDENCE_INVALID",
    "startup_incomplete": "STARTUP_INCOMPLETE",
    "awaiting_gpu_submit": "AWAITING_GPU_SUBMIT",
    "awaiting_first_present": "AWAITING_FIRST_PRESENT",
    "host_returned_before_first_present": "HOST_RETURNED_EARLY",
    "runtime_error": "RUNTIME_ERROR",
}


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Do not echo user-supplied file names/paths in machine output.
        raise ValueError("invalid arguments")


def parser() -> JsonArgumentParser:
    result = JsonArgumentParser(description=__doc__)
    subs = result.add_subparsers(dest="command", required=True)
    subs.add_parser("capabilities", help="List supported read-only operations")
    for name in ("status", "next", "diagnose"):
        sub = subs.add_parser(name)
        sub.add_argument("--log", type=Path, help="Local boot.txt path (read-only)")
        sub.add_argument("--run-id", help="Explicit 32-character lowercase hex run ID")
        if name == "status":
            sub.add_argument("--app", type=Path, help="Explicit final DmIOS.app to verify")
            sub.add_argument("--profile", choices=("metal4", "m3"))
            sub.add_argument("--require-clean", action="store_true")
    # A progress file must be selected explicitly: never scan an owner's
    # private evidence directory or infer success from a previous run.
    job = subs.add_parser("job-status", help="Read an explicit private M1 status snapshot")
    job.add_argument("--status-file", type=Path, required=True)
    # An explicit unsupported command must never silently execute a build.
    build = subs.add_parser("build", help="Requires --execute-local and explicit workspace")
    build.add_argument("--execute-local", action="store_true")
    build.add_argument("--workspace", type=Path)
    build.add_argument("--profile", choices=("metal4", "m3"), default="metal4")
    build.add_argument("--stage", choices=("preflight", "prepare", "headers", "verify", "build", "all"), default="all")
    subs.add_parser("build-plan", help="Read-only shared build stage plan")
    bundle = subs.add_parser("bundle", help="Explicit summary-only private ZIP export")
    bundle.add_argument("--log", type=Path)
    bundle.add_argument("--job-status-file", type=Path)
    bundle.add_argument("--run-id")
    bundle.add_argument("--output", type=Path, required=True)
    inspect = subs.add_parser("inspect-bundle", help="Check ZIP integrity, not device authenticity")
    inspect.add_argument("path", type=Path)
    for name in ("acceptance-template", "acceptance-check"):
        accept = subs.add_parser(name)
        accept.add_argument("--app", type=Path, required=True)
        accept.add_argument("--profile", choices=("metal4", "m3"), required=True)
        accept.add_argument("--log", type=Path, required=True)
        if name == "acceptance-check":
            accept.add_argument("--record", type=Path, required=True)
    return result


def _response(command: str, code: str, exit_code: int, **details: object) -> dict:
    return {"schema": SCHEMA, "command": command, "code": code,
            "ok": exit_code == 0, "exit_code": exit_code,
            "scope": "local-read-only", **details}


def _log_path(value: Path | None, environ: dict[str, str]) -> Path:
    if value is not None:
        return value
    root = environ.get("DM_ROOT") or str(Path.home() / "dm-work")
    return Path(root).expanduser() / "run/ios/out/boot.txt"


def operate(argv: list[str] | None = None, *, environ: dict[str, str] | None = None) -> dict:
    args_list = sys.argv[1:] if argv is None else argv
    try:
        args = parser().parse_args(args_list)
    except ValueError:
        return _response("unknown", "BAD_ARGUMENT", 2)
    command = args.command
    if command == "capabilities":
        return _response(command, "OK", 0, operations=CAPABILITIES,
                         playability="unverified")
    if command in ("build", "build-plan"):
        if command == "build" and not args.execute_local:
            return _response(command, "NOT_SUPPORTED", 3,
                             next_action="Explicit --execute-local and --workspace are required; no build started.")
        if __package__:
            from .m1_local_pipeline import run_pipeline, build_plan, StageError
            from .process_control import cancellation_signals
        else:
            from m1_local_pipeline import run_pipeline, build_plan, StageError
            from process_control import cancellation_signals
        if command == "build-plan":
            return _response(command, "OK", 0, stages=[
                {"stage": stage, "description": description} for stage, description in build_plan("metal4")],
                requirements=["Apple Silicon Mac", "version-matched lawful game inputs", "local signing"],
                playability="unverified")
        if args.workspace is None:
            return _response(command, "BAD_ARGUMENT", 2)
        from contextlib import redirect_stdout
        import io
        workspace = args.workspace  # run_pipeline owns guarded canonicalization
        romfs = workspace / "data/switch/3.3.94012/Update/RomFS"
        try:
            with cancellation_signals(), redirect_stdout(io.StringIO()):
                result = run_pipeline(args.stage, args.profile, workspace, romfs)
        except StageError as error:
            return _response(command, "M1_BUILD_CANCELLED" if error.code == "stage_cancelled" else "M1_BUILD_FAILED",
                             130 if error.code == "stage_cancelled" else 1,
                             scope="explicit-local-build", stage=error.stage, error_code=error.code,
                             playability="unverified")
        return _response(command, "M1_STAGES_PASSED" if result["result"] == "passed" else "M1_STAGE_PARTIAL", 0,
                         scope="explicit-local-build", build=result, playability="unverified")
    if command in ("bundle", "inspect-bundle", "acceptance-template", "acceptance-check"):
        if __package__:
            from . import evidence_tools as evidence
        else:
            import evidence_tools as evidence
        try:
            if command == "bundle":
                result = evidence.export_bundle(args.output, log=args.log,
                         status=args.job_status_file, run_id=args.run_id)
                return _response(command, "DIAGNOSTIC_EXPORTED", 0,
                                 scope="explicit-local-export", **result)
            if command == "inspect-bundle":
                result = evidence.inspect_bundle(args.path)
                return _response(command, "DIAGNOSTIC_INTEGRITY_CHECKED", 0, **result)
            if command == "acceptance-template":
                return _response(command, "ACCEPTANCE_TEMPLATE", 0,
                    template=evidence.acceptance_template(args.app, args.profile, args.log),
                    playability="unverified")
            result = evidence.check_acceptance(args.record, args.app, args.profile, args.log)
            return _response(command, "ACCEPTANCE_RECORD_COMPLETE" if result["record_complete"] else "ACCEPTANCE_INCOMPLETE",
                             result["exit_code"], acceptance=result, playability="requires_manual_review")
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            return _response(command, "LOCAL_EVIDENCE_INVALID", 2, playability="unverified")
    if command == "job-status":
        try:
            job = read_job_status(args.status_file)
        except (JobStatusError, OSError, ValueError, UnicodeError, RuntimeError):
            return _response(command, "M1_STATUS_INVALID", 2, playability="unverified")
        code, exit_code = {
            "running": ("M1_JOB_RUNNING", 1),
            "failed": ("M1_JOB_FAILED", 1),
            "cancelled": ("M1_JOB_CANCELLED", 130),
            "partial": ("M1_JOB_PARTIAL", 1),
            "passed": ("M1_STAGES_PASSED", 0),
        }[job["state"]]
        return _response(command, code, exit_code, job=job, job_liveness="not_checked", playability="unverified")
    if command == "status" and ((args.app is None) != (args.profile is None) or
                                 (args.require_clean and args.app is None)):
        return _response(command, "BAD_ARGUMENT", 2)
    try:
        report = analyze_log(_log_path(args.log, os.environ if environ is None else environ),
                             args.run_id)
    except (OSError, ValueError, RuntimeError):
        return _response(command, "BOOT_INPUT_INVALID", 2, playability="unverified")
    exit_code = report["exit_code"]
    code = ERRORS.get(report["result"], "BOOT_UNCLASSIFIED")
    if command == "diagnose":
        return _response(command, code, exit_code, diagnosis=report,
                         playability="unverified")
    if command == "next":
        return _response(command, code, exit_code, run_id=report["run_id"],
                         result=report["result"], next_action=report["next_action"],
                         playability="unverified")
    observation = {key: report[key] for key in (
        "run_id", "result", "last_stage", "last_incomplete_stage", "gpu_submit",
        "first_present", "issue_count", "next_action")}
    identity: dict = {"status": "not_checked", "verified": False}
    if args.app is not None:
        try:
            identity = {"status": "verified", "verified": True, "profile": args.profile,
                        **verify_identity(args.app, args.profile, repo=ROOT,
                                          require_clean=args.require_clean)}
        except (IdentityError, OSError, ValueError, UnicodeError, RuntimeError):
            # Never print an exception: OS errors may contain private paths.
            identity = {"status": "invalid", "verified": False, "profile": args.profile}
            code, exit_code = "BUILD_IDENTITY_INVALID", 2
    return _response(command, code, exit_code, observation=observation,
                     identity=identity, playability="unverified")


def main(argv: list[str] | None = None) -> int:
    result = operate(argv)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
