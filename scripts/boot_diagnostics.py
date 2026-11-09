#!/usr/bin/env python3
"""Read Game2Mobile startup observations without running or changing the app.

    python3 scripts/boot_diagnostics.py /private/boot.txt --json
    python3 scripts/boot_diagnostics.py /private/boot.txt --run-id <32 hex digits>

Only lines starting with ``G2M_BOOT `` are evidence. Legacy DONE lines, a
successful process exit, and observations from a different launch cannot prove
a frame. Exit 0 means a valid first-present observation, not game playability;
exit 1 means insufficient observations or a reported runtime error; exit 2
means invalid input/evidence. No input contents, paths, or arbitrary JSON fields
are copied into the report. This is a local diagnostic, not an authenticity or
cryptographic attestation check.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import sys
from typing import BinaryIO

PREFIX = b"G2M_BOOT "
RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
CODE = re.compile(r"[a-z0-9_]{0,63}\Z")
MODULE = re.compile(r"[a-zA-Z0-9_]{1,15}\Z")
STAGES = (
    "host_start", "module_load", "relocation", "sdk_init", "module_init",
    "guest_entry", "gpu_submit", "first_present", "host_return",
)
STATUSES = {"begin", "ok", "error"}
MAX_LINE_BYTES = 16 * 1024
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_EVENTS = 100_000
MAX_RUNS = 1024
MAX_ISSUES = 64
MAX_TIMELINE = 256

LABELS = {
    "host_start": "宿主启动", "module_load": "模块装载",
    "relocation": "模块重定位", "sdk_init": "SDK 初始化",
    "module_init": "模块初始化", "guest_entry": "进入游戏入口",
    "gpu_submit": "首次 GPU 提交", "first_present": "首次上屏回调",
    "host_return": "宿主返回",
}
RESULTS = {
    "first_present_observed": "本次运行已观察到首帧上屏；实际游玩尚未验收。",
    "runtime_error": "本次运行报告了错误；不能据首帧或 DONE 判断成功。",
    "host_returned_before_first_present": "宿主已返回，但未记录有效首帧。",
    "awaiting_first_present": "已观察到 GPU 提交，尚无首帧上屏证据。",
    "awaiting_gpu_submit": "已进入游戏入口，尚无 GPU 提交证据。",
    "startup_incomplete": "启动记录尚未到达游戏入口。",
    "no_boot_evidence": "没有结构化启动记录，当前启动状态未知。",
    "run_not_found": "日志中没有指定运行的结构化记录。",
    "invalid_evidence": "启动记录不完整或格式、顺序异常，无法确认有效首帧。",
    "input_error": "无法读取启动日志。",
}


class InvalidRecord(ValueError):
    pass


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise InvalidRecord("duplicate_json_key")
        result[name] = value
    return result


def _constant(_: str) -> None:
    raise InvalidRecord("non_finite_number")


def _validate(record: object) -> dict:
    if not isinstance(record, dict):
        raise InvalidRecord("record_not_object")
    if type(record.get("schema")) is not int or record["schema"] != 1:
        raise InvalidRecord("unsupported_schema")
    if not isinstance(record.get("run_id"), str) or not RUN_ID.fullmatch(record["run_id"]):
        raise InvalidRecord("invalid_run_id")
    seq = record.get("seq")
    if type(seq) is not int or not 1 <= seq <= (1 << 64) - 1:
        raise InvalidRecord("invalid_sequence")
    elapsed = record.get("elapsed_ms")
    if type(elapsed) not in (int, float):
        raise InvalidRecord("invalid_elapsed_ms")
    try:
        valid_elapsed = math.isfinite(elapsed) and elapsed >= 0
    except OverflowError:
        valid_elapsed = False
    if not valid_elapsed:
        raise InvalidRecord("invalid_elapsed_ms")
    if not isinstance(record.get("stage"), str) or record["stage"] not in STAGES:
        raise InvalidRecord("unknown_stage")
    if not isinstance(record.get("status"), str) or record["status"] not in STATUSES:
        raise InvalidRecord("unknown_status")
    if not isinstance(record.get("code"), str) or not CODE.fullmatch(record["code"]):
        raise InvalidRecord("invalid_code")
    if "module" in record and (
        not isinstance(record["module"], str) or not MODULE.fullmatch(record["module"])
    ):
        raise InvalidRecord("invalid_module")
    # Additive fields are ignored, not echoed: schema 1 only asserts these fields.
    return {name: record[name] for name in (
        "schema", "run_id", "seq", "elapsed_ms", "stage", "status", "code", "module"
    ) if name in record}


@dataclass
class Run:
    run_id: str
    first_line: int
    last_line: int
    events: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    issue_count: int = 0
    last_seq: int = 0
    last_elapsed: float = 0
    start_began: bool = False
    started: bool = False
    guest_entered: bool = False
    first_entry: dict | None = None
    gpu_submitted: bool = False
    first_present: dict | None = None
    first_submit: dict | None = None
    returned: bool = False
    pending: dict[tuple[str, str | None], dict] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)

    def issue(self, line: int, code: str) -> None:
        self.issue_count += 1
        if len(self.issues) < MAX_ISSUES:
            self.issues.append({"line": line, "code": code})

    def add(self, record: dict, line: int) -> None:
        self.last_line = line
        record = dict(record, line=line)
        seq = record["seq"]
        if seq != self.last_seq + 1:
            self.issue(line, "sequence_not_contiguous")
        self.last_seq = max(self.last_seq, seq)
        if record["elapsed_ms"] < self.last_elapsed:
            self.issue(line, "elapsed_time_reversed")
        self.last_elapsed = max(self.last_elapsed, record["elapsed_ms"])
        stage, status = record["stage"], record["status"]
        if not self.events and not (stage == "host_start" and status == "begin" and seq == 1):
            self.issue(line, "missing_initial_host_start")
        if stage == "host_start" and status == "begin":
            if self.start_began or self.started:
                self.issue(line, "duplicate_host_start")
            self.start_began = True
        elif stage == "host_start" and status == "ok":
            if self.started:
                self.issue(line, "duplicate_host_start")
            self.started = True
        elif stage == "guest_entry" and status in {"begin", "ok"}:
            self.guest_entered = True
            self.first_entry = self.first_entry or record
        elif stage == "gpu_submit" and status == "ok":
            if self.gpu_submitted:
                self.issue(line, "duplicate_first_gpu_submit")
            self.gpu_submitted = True
            self.first_submit = self.first_submit or record
        elif stage == "first_present" and status == "ok":
            if self.first_present is not None:
                self.issue(line, "duplicate_first_present")
            self.first_present = self.first_present or record
        elif stage == "host_return" and status in {"ok", "error"}:
            self.returned = True
        key = stage, record.get("module")
        if status == "begin":
            self.pending[key] = record
        else:
            self.pending.pop(key, None)
        if status == "error":
            self.errors.append(record)
        self.events.append(record)

    def validate_dependencies(self) -> None:
        # The logger serializes observations, not GPU execution. Presentation
        # callbacks may be logged before the submitting thread resumes, and
        # SDK/module initialization may perform graphics before nnMain. Check
        # the same-run evidence set after collection without inventing a
        # cross-thread causal order. Missing evidence still cannot pass.
        if self.first_entry and not self.started:
            self.issue(self.first_entry["line"], "guest_entry_without_host_start")
        if self.first_submit and not self.guest_entered:
            self.issue(self.first_submit["line"], "gpu_submit_without_guest_entry")
        if self.first_present and not (self.started and self.guest_entered and self.gpu_submitted):
            self.issue(self.first_present["line"], "first_present_without_startup_dependencies")


def _base_report(run_id: str | None, selection: str, runs: list[str]) -> dict:
    return {
        "schema": "game2mobile.boot-diagnostics.v1", "scope": "startup-observation-only",
        "playability": "unverified", "run_id": run_id, "selection": selection,
        "observed_runs": runs,
    }


def _empty_report(result: str, run_id: str | None, selection: str,
                  runs: list[str], issues: list[dict] | None = None) -> dict:
    return _base_report(run_id, selection, runs) | {
        "result": result, "summary": RESULTS[result],
        "exit_code": 1 if result == "no_boot_evidence" else 2,
        "first_present": {"observed": False, "valid": False, "elapsed_ms": None},
        "gpu_submit": {"observed": False, "elapsed_ms": None},
        "last_stage": None, "last_incomplete_stage": None, "pending_stages": [],
        "runtime_errors": [], "issues": issues or [], "issue_count": len(issues or []),
        "event_count": 0, "timeline": [], "timeline_truncated": False,
        "next_action": "获取当前运行的完整 G2M_BOOT 日志，并核对运行 ID；不要复用旧日志或 DONE。",
    }


def _event_summary(record: dict) -> dict:
    return {key: record[key] for key in (
        "seq", "line", "elapsed_ms", "stage", "status", "code", "module"
    ) if key in record}


def _report(run: Run, selection: str, runs: list[str], global_issues: list[dict]) -> dict:
    issues = run.issues + global_issues
    if run.issue_count or global_issues:
        result, exit_code = "invalid_evidence", 2
        action = "重新收集同一次启动的完整日志；先修复格式、序号或缺失事件，当前记录不能作为首帧证据。"
    elif run.errors:
        result, exit_code = "runtime_error", 1
        action = "查看本次运行的错误阶段与稳定错误码，再对照同一阶段的原生日志；首帧记录不覆盖后续错误。"
    elif run.first_present:
        result, exit_code = "first_present_observed", 0
        action = "继续验证可操作场景、输入、音频、存档恢复和持续运行；首帧回调不证明画面正确或游戏可玩。"
    elif run.returned:
        result, exit_code = "host_returned_before_first_present", 1
        action = "核对宿主返回前最后阶段及退出原因；不要把返回成功或 DONE 当成已出图。"
    elif run.gpu_submitted:
        result, exit_code = "awaiting_first_present", 1
        action = "检查 GPU 完成状态和上屏回调，并确认采集是否过早结束；仅凭缺少事件不能确定黑屏根因。"
    elif run.guest_entered:
        result, exit_code = "awaiting_gpu_submit", 1
        action = "检查游戏初始化、服务等待和图形调用；采集线程现场以区分等待、退出与尚未到达绘制。"
    else:
        result, exit_code = "startup_incomplete", 1
        action = "从最后未完成阶段继续检查模块、重定位或 SDK 初始化日志；没有后续记录不等于已确认卡死。"
    pending = sorted(run.pending.values(), key=lambda event: event["seq"])
    # guest_entry begin marks transfer of control; a running game need not return.
    unresolved = [event for event in pending if event["stage"] != "guest_entry"]
    timeline = run.events
    if len(timeline) > MAX_TIMELINE:
        half = MAX_TIMELINE // 2
        timeline = timeline[:half] + timeline[-half:]
    first = run.first_present
    submit = run.first_submit
    return _base_report(run.run_id, selection, runs) | {
        "result": result, "summary": RESULTS[result], "exit_code": exit_code,
        "first_present": {
            "observed": first is not None,
            "valid": first is not None and not (run.issue_count or global_issues),
            "elapsed_ms": first["elapsed_ms"] if first else None,
        },
        "gpu_submit": {"observed": submit is not None,
                       "elapsed_ms": submit["elapsed_ms"] if submit else None},
        "last_stage": _event_summary(run.events[-1]) if run.events else None,
        "last_incomplete_stage": _event_summary(unresolved[-1]) if unresolved else None,
        "pending_stages": [_event_summary(event) for event in unresolved],
        "runtime_errors": [_event_summary(event) for event in run.errors[:MAX_ISSUES]],
        "issues": issues, "issue_count": run.issue_count + len(global_issues),
        "event_count": len(run.events),
        "timeline": [_event_summary(event) for event in timeline],
        "timeline_truncated": len(run.events) > MAX_TIMELINE,
        "next_action": action,
    }


def analyze_stream(stream: BinaryIO, run_id: str | None = None, *,
                   max_line_bytes: int = MAX_LINE_BYTES,
                   max_input_bytes: int = MAX_INPUT_BYTES,
                   max_events: int = MAX_EVENTS, max_runs: int = MAX_RUNS) -> dict:
    """Analyze a binary stream with bounded input/record sizes, without writes.

    The default is the last newly encountered run, not the last callback from
    an older interleaved run. A malformed event with no usable run ID taints
    both the latest launch and the last active run when they differ; its
    ownership cannot be resolved safely. A parsed usable ID limits the issue
    to that run. Earlier unattributed corruption cannot taint a fresh launch.
    """
    if run_id is not None and (not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id)):
        return _empty_report("input_error", None, "explicit", [],
                             [{"line": 0, "code": "invalid_requested_run_id"}])
    limits = (max_line_bytes, max_input_bytes, max_events, max_runs)
    if any(type(value) is not int or value <= 0 for value in limits):
        return _empty_report("input_error", run_id, "explicit" if run_id else "latest", [],
                             [{"line": 0, "code": "invalid_resource_limit"}])
    runs: dict[str, Run] = {}
    latest: str | None = None
    global_issues: list[dict] = []
    orphan_issues: list[dict] = []
    line_number = total_bytes = records = 0

    def issue(code: str, owner: str | None = None) -> None:
        if owner is not None:
            runs[owner].issue(line_number, code)
        elif latest is not None:
            owners = {latest, next(reversed(runs))}
            for uncertain_owner in owners:
                runs[uncertain_owner].issue(line_number, code)
        elif len(orphan_issues) < MAX_ISSUES:
            orphan_issues.append({"line": line_number, "code": code})

    while True:
        raw = stream.readline(max_line_bytes + 1)
        if not raw:
            break
        line_number += 1
        total_bytes += len(raw)
        if total_bytes > max_input_bytes:
            global_issues.append({"line": line_number, "code": "input_size_limit"})
            break
        if not raw.endswith(b"\n") and raw.startswith(b"G2M_") and PREFIX.startswith(raw):
            issue("truncated_record_prefix")
            continue
        is_record = raw.startswith(PREFIX)
        oversized = len(raw) > max_line_bytes
        if oversized:
            # Drain the same physical line in bounded chunks.
            chunk = raw
            while not chunk.endswith(b"\n"):
                chunk = stream.readline(max_line_bytes + 1)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_input_bytes:
                    global_issues.append({"line": line_number, "code": "input_size_limit"})
                    break
            if global_issues:
                break
        if not is_record:
            continue
        records += 1
        if records > max_events:
            global_issues.append({"line": line_number, "code": "event_count_limit"})
            break
        if oversized:
            issue("record_too_long")
            continue
        try:
            value = json.loads(raw[len(PREFIX):].decode("utf-8"),
                               object_pairs_hook=_object, parse_constant=_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            issue(str(exc) if isinstance(exc, InvalidRecord) else "malformed_json")
            continue
        # Select identifiable runs before checking the other fields. An invalid
        # final run must not cause fallback to an older run with a valid frame.
        candidate = value.get("run_id") if isinstance(value, dict) else None
        if isinstance(candidate, str) and RUN_ID.fullmatch(candidate):
            if candidate not in runs:
                if len(runs) >= max_runs:
                    global_issues.append({"line": line_number, "code": "run_count_limit"})
                    break
                runs[candidate] = Run(candidate, line_number, line_number)
            latest = candidate
        try:
            record = _validate(value)
        except InvalidRecord as exc:
            owner = candidate if isinstance(candidate, str) and RUN_ID.fullmatch(candidate) else None
            issue(str(exc), owner)
            continue
        runs[record["run_id"]].add(record, line_number)
    selection = "explicit" if run_id is not None else "latest"
    selected = run_id if run_id is not None else next(reversed(runs), None)
    if selected is None:
        issues = orphan_issues + global_issues
        return _empty_report("invalid_evidence" if issues else "no_boot_evidence",
                             None, selection, list(runs), issues)
    if selected not in runs:
        return _empty_report("run_not_found", selected, selection, list(runs), global_issues)
    runs[selected].validate_dependencies()
    return _report(runs[selected], selection, list(runs), global_issues)


def analyze_log(path: Path, run_id: str | None = None) -> dict:
    """Open the requested local log read-only; do not copy raw error messages."""
    if run_id is not None and (not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id)):
        return _empty_report("input_error", None, "explicit", [],
                             [{"line": 0, "code": "invalid_requested_run_id"}])
    try:
        with Path(path).open("rb") as stream:
            return analyze_stream(stream, run_id)
    except (OSError, ValueError):
        return _empty_report("input_error", run_id, "explicit" if run_id else "latest", [],
                             [{"line": 0, "code": "log_unreadable"}])


def human_report(report: dict) -> str:
    lines = [report["summary"], "范围：仅启动观测；可玩性未验收。"]
    if report["run_id"]:
        lines.append("运行 ID：" + report["run_id"])
    lines.append("结构化事件数：" + str(report["event_count"]))
    submitted = report["gpu_submit"]
    lines.append("首次 GPU 提交：" + (
        f"有记录，{submitted['elapsed_ms']:g} ms" if submitted["observed"] else "未知（没有记录）"))
    presented = report["first_present"]
    if presented["observed"]:
        validity = "记录有效" if presented["valid"] else "记录存在异常"
        lines.append(f"首帧上屏：有记录，{presented['elapsed_ms']:g} ms，{validity}。")
    else:
        lines.append("首帧上屏：未知（没有记录）。")
    last = report["last_stage"]
    if last:
        lines.append(f"最后事件：{LABELS[last['stage']]} / {last['status']}，"
                     f"{last['elapsed_ms']:g} ms")
    pending = report["last_incomplete_stage"]
    if pending:
        lines.append("尚未完成：" + LABELS[pending["stage"]] +
                     ("（" + pending["module"] + "）" if pending.get("module") else ""))
    for error in report["runtime_errors"]:
        lines.append(f"运行错误：第 {error['line']} 行，{error['stage']}，{error['code'] or '未给错误码'}")
    for item in report["issues"]:
        lines.append(f"证据异常：第 {item['line']} 行，{item['code']}")
    if report["issue_count"] > len(report["issues"]):
        lines.append(f"另有 {report['issue_count'] - len(report['issues'])} 项异常未逐条显示。")
    lines.append("下一步：" + report["next_action"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="本机启动日志（只读）")
    parser.add_argument("--run-id", help="只分析指定的 32 位小写十六进制运行 ID")
    parser.add_argument("--json", action="store_true", help="输出机器可读诊断 JSON")
    args = parser.parse_args(argv)
    report = analyze_log(args.log, args.run_id)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
          if args.json else human_report(report))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
