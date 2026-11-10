#!/usr/bin/env python3
"""Read-only, JSON-only Game2Mobile operator CLI.

Examples (run from the repository root):
    python3 scripts/g2mctl.py capabilities
    python3 scripts/g2mctl.py status --log /private/boot.txt
    python3 scripts/g2mctl.py next --log /private/boot.txt --run-id <run_id>
    python3 scripts/g2mctl.py status --log /private/boot.txt --app /private/DmIOS.app --profile metal4

No network listener, launch/install, credential access or filesystem writes.
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
else:
    from boot_diagnostics import analyze_log
    from build_identity import IdentityError, ROOT, verify_identity

SCHEMA = "game2mobile.operator.v1"
CAPABILITIES = {"capabilities": True, "status": True, "next": True,
                "diagnose": True, "build": False, "install": False,
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
    # An explicit unsupported command must never silently execute a build.
    subs.add_parser("build", help="Not yet implemented; fails safely")
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
    if command == "build":
        return _response(command, "NOT_SUPPORTED", 3,
                         next_action="Use the existing local M1 pipeline explicitly; no build was started.")
    if command == "status" and ((args.app is None) != (args.profile is None) or
                                 (args.require_clean and args.app is None)):
        return _response(command, "BAD_ARGUMENT", 2)
    report = analyze_log(_log_path(args.log, os.environ if environ is None else environ),
                         args.run_id)
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
        except (IdentityError, OSError, ValueError, UnicodeError, RecursionError):
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
