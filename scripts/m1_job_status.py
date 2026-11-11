#!/usr/bin/env python3
"""Atomic private M1 stage snapshots, and strictly bounded read-only status parsing.

No game files, file paths, command lines, credentials, signing identity or raw
stage errors are copied to the snapshot. It is a local progress claim, not an
authenticated build attestation or proof of successful device gameplay.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import tempfile
try:
    from .local_io import read_bytes, strict_json, LocalInputError
except ImportError:
    from local_io import read_bytes, strict_json, LocalInputError

SCHEMA = "game2mobile.m1-job-status.v2"
LEGACY_SCHEMA = "game2mobile.m1-job-status.v1"
BASENAME = "m1-job-status.json"
MAX_BYTES = 32 * 1024
STAGES = ("preflight", "prepare", "headers", "verify", "build")
ERROR_STAGES = ("source", "environment", "arguments")
VALID_STATES = ("running", "failed", "partial", "passed", "cancelled")
VALID_RESULTS = ("incomplete", "failed", "partial", "passed", "cancelled")


class JobStatusError(ValueError):
    """An incomplete/invalid local progress report cannot be trusted."""


def _hex(text: object, length: int) -> bool:
    return isinstance(text, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, text) is not None


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise JobStatusError("Duplicate job status field")
        result[key] = value
    return result


def _validate(value: object) -> dict:
    if not isinstance(value, dict) or value.get("schema") not in (SCHEMA, LEGACY_SCHEMA):
        raise JobStatusError("Unknown M1 job status schema")
    job_id, commit = value.get("job_id"), value.get("source_commit")
    if not _hex(job_id, 32) or not _hex(commit, 40):
        raise JobStatusError("Invalid M1 job identity")
    profile, action = value.get("profile"), value.get("action")
    if profile not in ("metal4", "m3") or action not in (*STAGES, "all"):
        raise JobStatusError("Invalid M1 job selection")
    state, result = value.get("state"), value.get("result")
    stage = value.get("current_stage")
    if state not in VALID_STATES or result not in VALID_RESULTS:
        raise JobStatusError("Invalid M1 job lifecycle")
    if stage is not None and stage not in (*STAGES, *ERROR_STAGES):
        raise JobStatusError("Unknown current stage")
    if (state == "running" and result != "incomplete") or (
        state != "running" and result != state
    ):
        raise JobStatusError("Inconsistent M1 job lifecycle")
    if state in ("passed", "partial") and stage is not None:
        raise JobStatusError("Completed M1 job still has an active stage")
    if state == "passed" and action != "all":
        raise JobStatusError("Only all stages can report complete")
    if state == "partial" and action == "all":
        raise JobStatusError("The full M1 pipeline cannot finish partial")
    steps = value.get("steps")
    if not isinstance(steps, dict) or len(steps) > len(STAGES) + len(ERROR_STAGES):
        raise JobStatusError("Invalid M1 step inventory")
    if any(name not in (*STAGES, *ERROR_STAGES) or status not in ("passed", "failed")
           for name, status in steps.items()):
        raise JobStatusError("Unknown M1 step status")
    if state in ("failed", "cancelled") and "failed" not in steps.values():
        raise JobStatusError("Failed M1 job has no failing stage")
    if state == "passed" and (set(steps) != set(STAGES) or
                             any(x != "passed" for x in steps.values())):
        raise JobStatusError("Full M1 success is missing stages")
    if state == "partial" and (set(steps) != {action} or steps[action] != "passed"):
        raise JobStatusError("Partial M1 job has inconsistent stages")
    flags = ("full_game_app_built", "app_signed_locally",
             "end_to_end_build_stages_verified")
    if any(type(value.get(key)) is not bool for key in flags):
        raise JobStatusError("Malformed M1 job flags")
    if value["end_to_end_build_stages_verified"] != (state == "passed"):
        raise JobStatusError("M1 end-to-end flag contradicts stage results")
    timestamp = value.get("updated_utc")
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp
    ) is None:
        raise JobStatusError("Invalid M1 timestamp")
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise JobStatusError("Invalid M1 calendar timestamp") from exc
    if value["full_game_app_built"] != value["app_signed_locally"]:
        raise JobStatusError("M1 build/signature flags disagree")
    if value["full_game_app_built"] and steps.get("build") != "passed":
        raise JobStatusError("M1 App claim has no successful build stage")
    if state == "passed" and not value["full_game_app_built"]:
        raise JobStatusError("Full M1 success has no signed App result")
    if state == "running" and any(v != "passed" for v in steps.values()):
        raise JobStatusError("Running M1 job already contains failed steps")
    if action != "all" and any(k not in (action, *ERROR_STAGES) for k in steps):
        raise JobStatusError("M1 stages do not match requested action")
    # Return only whitelisted, type-checked metadata. Never expose unknown fields.
    return {
        "schema": value["schema"], "job_id": job_id, "source_commit": commit,
        "profile": profile, "action": action, "state": state,
        "current_stage": stage, "steps": dict(steps), "result": result,
        "updated_utc": timestamp, **{key: value[key] for key in flags},
    }


def read_job_status(path: Path) -> dict:
    """Read at most 32 KiB; do not expose private paths or malformed contents."""
    try:
        return _validate(strict_json(read_bytes(path, MAX_BYTES)))
    except (LocalInputError, OSError, UnicodeError, ValueError, RecursionError, TypeError) as exc:
        raise JobStatusError("Unreadable or inconsistent M1 job status") from exc


def publish_job_status(evidence: Path, *, job_id: str, commit: str,
                       profile: str, action: str, state: str,
                       current_stage: str | None, record: dict) -> None:
    """Atomically replace the snapshot with metadata only (0600, private 0700 dir)."""
    evidence = Path(evidence)
    if evidence.is_symlink() or not evidence.is_dir():
        raise JobStatusError("Unsafe M1 evidence directory")
    payload = {
        "schema": SCHEMA, "job_id": job_id, "source_commit": commit,
        "profile": profile, "action": action, "state": state,
        "current_stage": current_stage, "steps": dict(record["steps"]),
        "result": record["result"],
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "full_game_app_built": bool(record["full_game_app_built"]),
        "app_signed_locally": bool(record["app_signed_locally"]),
        "end_to_end_build_stages_verified": bool(record["end_to_end_build_stages_verified"]),
    }
    _validate(payload)
    destination = evidence / BASENAME
    if destination.is_symlink():
        raise JobStatusError("Symlinked M1 job status destination")
    descriptor, temporary = tempfile.mkstemp(prefix=".m1-status-", dir=evidence)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            json.dump(payload, out, sort_keys=True, ensure_ascii=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
