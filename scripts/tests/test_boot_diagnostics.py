"""Synthetic log regressions; these do not run a game, Metal, or an iOS app."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts import boot_diagnostics as diag

ROOT = Path(__file__).resolve().parents[2]
A = "0123456789abcdef0123456789abcdef"
B = "abcdef0123456789abcdef0123456789"


def event(seq: int, stage: str, status: str = "ok", *, run_id: str = A,
          elapsed: float | None = None, code: str = "", **extra: object) -> dict:
    return {"schema": 1, "run_id": run_id, "seq": seq,
            "elapsed_ms": float(seq) if elapsed is None else elapsed,
            "stage": stage, "status": status, "code": code, **extra}


def encoded(*events: dict) -> bytes:
    return b"".join(diag.PREFIX + json.dumps(value).encode() + b"\n" for value in events)


def boot(run_id: str = A) -> list[dict]:
    return [event(1, "host_start", "begin", run_id=run_id),
            event(2, "host_start", run_id=run_id),
            event(3, "guest_entry", "begin", run_id=run_id),
            event(4, "gpu_submit", run_id=run_id),
            event(5, "first_present", run_id=run_id)]


def analyze(data: bytes, **kwargs: object) -> dict:
    return diag.analyze_stream(io.BytesIO(data), **kwargs)


class BootDiagnosticsTests(unittest.TestCase):
    def test_first_present_is_startup_evidence_only(self):
        report = analyze(encoded(*boot()))
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(report["result"], "first_present_observed")
        self.assertTrue(report["first_present"]["valid"])
        self.assertEqual(report["first_present"]["elapsed_ms"], 5)
        self.assertEqual(report["playability"], "unverified")
        self.assertEqual(report["scope"], "startup-observation-only")
        self.assertIsNone(report["last_incomplete_stage"])
        self.assertIn("可玩性未验收", diag.human_report(report))

    def test_interleaved_module_stages_are_not_a_single_global_stack(self):
        rows = [event(1, "host_start", "begin"),
                event(2, "module_load", "begin", module="main"),
                event(3, "module_load", "begin", module="sdk"),
                event(4, "module_load", module="sdk"),
                event(5, "module_load", module="main"),
                event(6, "relocation", "begin"), event(7, "relocation"),
                event(8, "host_start"), event(9, "sdk_init", "begin"),
                event(10, "sdk_init"), event(11, "module_init", "begin"),
                event(12, "module_init"), event(13, "guest_entry", "begin"),
                event(14, "gpu_submit"), event(15, "first_present")]
        report = analyze(encoded(*rows))
        self.assertEqual(report["exit_code"], 0, report)
        self.assertEqual(report["pending_stages"], [])

    def test_present_callback_may_be_logged_before_submit_observation(self):
        rows = boot()[:3] + [event(4, "first_present"), event(5, "gpu_submit")]
        report = analyze(encoded(*rows))
        self.assertEqual(report["exit_code"], 0, report)
        self.assertTrue(report["first_present"]["valid"])
        self.assertEqual(report["first_present"]["elapsed_ms"], 4)
        self.assertEqual(report["gpu_submit"]["elapsed_ms"], 5)
        partial = analyze(encoded(*rows[:-1]))
        self.assertEqual(partial["exit_code"], 2)
        self.assertFalse(partial["first_present"]["valid"])

    def test_graphics_during_initialization_is_checked_at_end_of_same_run(self):
        rows = [event(1, "host_start", "begin"),
                event(2, "gpu_submit"), event(3, "first_present"),
                event(4, "host_start"), event(5, "sdk_init", "begin"),
                event(6, "sdk_init"), event(7, "module_init", "begin"),
                event(8, "module_init"), event(9, "guest_entry", "begin")]
        report = analyze(encoded(*rows))
        self.assertEqual(report["exit_code"], 0, report)
        self.assertTrue(report["first_present"]["valid"])
        partial = analyze(encoded(*rows[:3]))
        self.assertEqual(partial["exit_code"], 2)
        self.assertFalse(partial["first_present"]["valid"])
        missing_entry = analyze(encoded(*rows[:-1]))
        self.assertEqual(missing_entry["exit_code"], 2)
        self.assertFalse(missing_entry["first_present"]["valid"])

    def test_out_of_order_evidence_still_cannot_borrow_another_runs_dependencies(self):
        rows = [event(1, "host_start", "begin"), event(2, "host_start"),
                event(3, "first_present"), *boot(B)]
        report = analyze(encoded(*rows), run_id=A)
        self.assertEqual(report["exit_code"], 2)
        self.assertFalse(report["first_present"]["valid"])

    def test_out_of_order_frame_does_not_override_recorded_error(self):
        rows = boot()[:3] + [event(4, "first_present"), event(5, "gpu_submit"),
                            event(6, "host_return", "error", code="host_failed")]
        report = analyze(encoded(*rows))
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["result"], "runtime_error")
        self.assertTrue(report["first_present"]["observed"])

    def test_last_pending_stage_is_reported_without_claiming_deadlock(self):
        rows = boot()[:2] + [event(3, "sdk_init", "begin")]
        report = analyze(encoded(*rows))
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["last_incomplete_stage"]["stage"], "sdk_init")
        self.assertIn("不等于已确认卡死", report["next_action"])

    def test_no_submit_and_no_present_are_distinct_observations(self):
        guest = analyze(encoded(*boot()[:3]))
        submitted = analyze(encoded(*boot()[:4]))
        self.assertEqual(guest["result"], "awaiting_gpu_submit")
        self.assertEqual(submitted["result"], "awaiting_first_present")
        self.assertFalse(submitted["first_present"]["observed"])

    def test_error_after_frame_overrides_success(self):
        report = analyze(encoded(*boot(), event(6, "host_return", "error", code="host_failed")))
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["result"], "runtime_error")
        self.assertTrue(report["first_present"]["observed"])
        self.assertEqual(report["runtime_errors"][0]["code"], "host_failed")

    def test_clean_host_return_and_legacy_done_do_not_prove_a_frame(self):
        report = analyze(encoded(*boot()[:3], event(4, "host_return")) + b"DONE\n")
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["result"], "host_returned_before_first_present")
        self.assertFalse(report["first_present"]["valid"])

    def test_legacy_or_empty_log_is_unknown(self):
        for data in (b"", b"RUN_RECEIPT " + A.encode() + b"\nDONE\n", b"normal host output\n"):
            with self.subTest(data=data):
                report = analyze(data)
                self.assertEqual(report["exit_code"], 1)
                self.assertEqual(report["result"], "no_boot_evidence")
                self.assertIsNone(report["run_id"])

    def test_default_selects_new_launch_and_does_not_borrow_old_frame(self):
        data = encoded(*boot(), event(1, "host_start", "begin", run_id=B)) + b"DONE\n"
        report = analyze(data)
        self.assertEqual(report["run_id"], B)
        self.assertEqual(report["exit_code"], 1)
        self.assertFalse(report["first_present"]["observed"])
        old = analyze(data, run_id=A)
        self.assertEqual(old["exit_code"], 0)
        self.assertEqual(old["selection"], "explicit")

    def test_late_callback_from_old_run_does_not_change_latest_launch(self):
        data = encoded(*boot()[:4], event(1, "host_start", "begin", run_id=B), boot()[-1])
        report = analyze(data)
        self.assertEqual(report["run_id"], B)
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(analyze(data, run_id=A)["exit_code"], 0)

    def test_unattributed_bad_tail_after_old_callback_cannot_hide_corruption(self):
        data = encoded(*boot()[:4], *boot(B), boot()[-1]) + b"G2M_BOOT broken\n"
        report = analyze(data)
        self.assertEqual(report["run_id"], B)
        self.assertEqual(report["exit_code"], 2)
        self.assertFalse(report["first_present"]["valid"])
        self.assertEqual(analyze(data, run_id=A)["exit_code"], 2)

    def test_bad_identified_old_record_does_not_taint_new_run(self):
        bad = event(6, "host_return", run_id=A)
        bad["schema"] = 2
        report = analyze(encoded(*boot(), *boot(B), bad))
        self.assertEqual(report["run_id"], B)
        self.assertEqual(report["exit_code"], 0)

    def test_new_identifiable_invalid_run_does_not_fall_back_to_old_success(self):
        invalid = event(1, "host_start", run_id=B)
        invalid["schema"] = 2
        report = analyze(encoded(*boot(), invalid))
        self.assertEqual(report["run_id"], B)
        self.assertEqual(report["exit_code"], 2)
        self.assertEqual(report["event_count"], 0)
        self.assertFalse(report["first_present"]["valid"])

    def test_explicit_missing_or_invalid_id_fails(self):
        missing = analyze(encoded(*boot()), run_id=B)
        self.assertEqual(missing["result"], "run_not_found")
        for value in ("bad", A.upper(), "private\npath", 123):
            with self.subTest(value=value):
                report = analyze(encoded(*boot()), run_id=value)
                self.assertEqual(report["exit_code"], 2)
                self.assertIsNone(report["run_id"])

    def test_frame_requires_same_run_host_entry_and_submission(self):
        cases = [
            [event(1, "first_present")],
            [event(1, "host_start"), event(2, "first_present")],
            [event(1, "host_start"), event(2, "guest_entry", "begin"), event(3, "first_present")],
            [event(1, "host_start"), event(2, "gpu_submit"), event(3, "first_present")],
            [event(1, "host_start"), event(2, "guest_entry", "begin"),
             event(3, "gpu_submit", "begin"), event(4, "first_present")],
            [event(1, "host_start"), event(2, "guest_entry", "begin"),
             event(3, "gpu_submit"), event(4, "first_present")],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                report = analyze(encoded(*rows))
                self.assertEqual(report["exit_code"], 2)
                self.assertFalse(report["first_present"]["valid"])

    def test_sequence_duplicate_gap_reverse_and_missing_prefix_are_invalid(self):
        for sequence in ([1, 2, 3, 3, 4], [1, 2, 3, 5, 6], [1, 2, 4, 3, 5], [2, 3, 4, 5, 6]):
            with self.subTest(sequence=sequence):
                rows = boot()
                for row, seq in zip(rows, sequence):
                    row["seq"] = seq
                report = analyze(encoded(*rows))
                self.assertEqual(report["exit_code"], 2)
                self.assertFalse(report["first_present"]["valid"])

    def test_nonmonotonic_clock_rejected_but_equal_timestamps_allowed(self):
        rows = boot()
        for row in rows:
            row["elapsed_ms"] = 0
        self.assertEqual(analyze(encoded(*rows))["exit_code"], 0)
        rows[-2]["elapsed_ms"] = 10
        report = analyze(encoded(*rows))
        self.assertEqual(report["exit_code"], 2)
        self.assertIn("elapsed_time_reversed", [item["code"] for item in report["issues"]])

    def test_schema_and_field_types_do_not_accept_python_bool_as_integer(self):
        variants = [("schema", True), ("schema", 2), ("schema", "1"),
                    ("seq", True), ("seq", 0), ("seq", 1.0), ("seq", 2 ** 64),
                    ("elapsed_ms", False), ("elapsed_ms", -1), ("elapsed_ms", "2"),
                    ("elapsed_ms", 10 ** 400), ("stage", "future_stage"),
                    ("status", "success"), ("code", None), ("code", "private/path"),
                    ("code", "UPPER_CASE"), ("code", "x" * 64), ("code", "a-b"),
                    ("module", "../private"), ("module", "x" * 16),
                    ("module", "main.nso"), ("module", 1), ("run_id", A.upper())]
        for key, value in variants:
            with self.subTest(key=key, value=value):
                bad = event(6, "host_return")
                bad[key] = value
                report = analyze(encoded(*boot(), bad))
                self.assertEqual(report["exit_code"], 2)
                self.assertFalse(report["first_present"]["valid"])

    def test_missing_required_fields_fail_without_traceback(self):
        for key in ("schema", "run_id", "seq", "elapsed_ms", "stage", "status", "code"):
            with self.subTest(key=key):
                bad = event(6, "host_return")
                del bad[key]
                self.assertEqual(analyze(encoded(*boot(), bad))["exit_code"], 2)

    def test_duplicate_json_keys_nan_and_infinity_are_invalid(self):
        raw = json.dumps(event(6, "host_return"))
        malformed = [raw[:-1] + ', "seq": 6}', raw.replace('6.0', 'NaN'),
                     raw.replace('6.0', 'Infinity'), raw.replace('6.0', '-Infinity')]
        for value in malformed:
            with self.subTest(value=value):
                report = analyze(encoded(*boot()) + diag.PREFIX + value.encode() + b"\n")
                self.assertEqual(report["exit_code"], 2)

    def test_partial_and_non_utf8_tail_cannot_preserve_success(self):
        for suffix in (b'G2M_BOOT {"schema":1,', b"G2M_BOOT \xff\n", b"G2M_BOOT []\n",
                       b"G2M_BOOT", b"G2M_BO"):
            with self.subTest(suffix=suffix):
                report = analyze(encoded(*boot()) + suffix)
                self.assertEqual(report["exit_code"], 2)
                self.assertFalse(report["first_present"]["valid"])

    def test_complete_json_at_eof_is_valid_without_final_newline(self):
        self.assertEqual(analyze(encoded(*boot()).rstrip(b"\n"))["exit_code"], 0)

    def test_malformed_unattributed_older_log_does_not_poison_fresh_start(self):
        report = analyze(b"G2M_BOOT not-json\n" + encoded(*boot()))
        self.assertEqual(report["exit_code"], 0)

    def test_protocol_prefix_must_start_the_physical_line(self):
        fake = b"diagnostic message: " + encoded(*boot())
        # Only the first line has an extra prefix; subsequent records then lack
        # seq=1, so this cannot manufacture a complete new run.
        self.assertEqual(analyze(fake)["exit_code"], 2)
        self.assertEqual(analyze(b"fake G2M_BOOT " + json.dumps(boot()[-1]).encode())["exit_code"], 1)

    def test_oversized_protocol_line_is_drained_and_invalidates_evidence(self):
        data = encoded(*boot()) + b"G2M_BOOT " + b"x" * 900 + b"\nordinary tail\n"
        report = analyze(data, max_line_bytes=256)
        self.assertEqual(report["exit_code"], 2)
        self.assertIn("record_too_long", [item["code"] for item in report["issues"]])
        self.assertEqual(report["event_count"], 5)

    def test_large_nonprotocol_lines_are_ignored_in_bounded_chunks(self):
        report = analyze(b"ordinary " + b"x" * 900 + b"\n" + encoded(*boot()), max_line_bytes=256)
        self.assertEqual(report["exit_code"], 0)

    def test_input_record_and_run_resource_limits_are_explicit_failures(self):
        cases = [({"max_input_bytes": 256}, encoded(*boot()), "input_size_limit"),
                 ({"max_events": 4}, encoded(*boot()), "event_count_limit"),
                 ({"max_runs": 1}, encoded(*boot(), event(1, "host_start", run_id=B)), "run_count_limit")]
        for options, data, expected in cases:
            with self.subTest(options=options):
                report = analyze(data, **options)
                self.assertEqual(report["exit_code"], 2)
                self.assertIn(expected, [item["code"] for item in report["issues"]])

    def test_invalid_resource_limits_do_not_hang_or_disable_bounds(self):
        for name in ("max_line_bytes", "max_input_bytes", "max_events", "max_runs"):
            for value in (0, -1, True, 1.5):
                with self.subTest(name=name, value=value):
                    report = analyze(encoded(*boot()), **{name: value})
                    self.assertEqual(report["exit_code"], 2)
                    self.assertEqual(report["issues"][0]["code"], "invalid_resource_limit")

    def test_duplicate_singleton_milestones_are_not_accepted_as_clean_evidence(self):
        for stage in ("host_start", "gpu_submit", "first_present"):
            with self.subTest(stage=stage):
                self.assertEqual(analyze(encoded(*boot(), event(6, stage)))["exit_code"], 2)

    def test_long_timeline_and_errors_have_bounded_report_sizes(self):
        rows = boot()[:2]
        rows += [event(seq, "module_load", module="main") for seq in range(3, 500)]
        rows += [event(500, "guest_entry", "begin"), event(501, "gpu_submit"), event(502, "first_present")]
        report = analyze(encoded(*rows))
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(report["event_count"], 502)
        self.assertTrue(report["timeline_truncated"])
        self.assertLessEqual(len(report["timeline"]), diag.MAX_TIMELINE)
        corrupted = analyze(encoded(*boot()) + b"G2M_BOOT bad\n" * 100)
        self.assertEqual(corrupted["issue_count"], 100)
        self.assertEqual(len(corrupted["issues"]), diag.MAX_ISSUES)

    def test_unknown_fields_and_bad_values_are_not_echoed_into_reports(self):
        rows = boot()
        rows[0]["private_extra"] = "/private/do-not-echo-this"
        report = analyze(encoded(*rows))
        self.assertEqual(report["exit_code"], 0)
        self.assertNotIn("do-not-echo", json.dumps(report))
        bad = event(6, "host_return", code="/private/do-not-echo-this")
        report = analyze(encoded(*rows, bad))
        self.assertEqual(report["exit_code"], 2)
        self.assertNotIn("do-not-echo", json.dumps(report))

    def test_cli_json_and_human_output_do_not_modify_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-boot.txt"
            original = encoded(*boot())
            path.write_bytes(original)
            before = path.stat()
            for args in (["--json"], []):
                result = subprocess.run([sys.executable, str(ROOT / "scripts/boot_diagnostics.py"),
                                         str(path), *args], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                if args:
                    self.assertEqual(json.loads(result.stdout)["playability"], "unverified")
                else:
                    self.assertIn("仅启动观测", result.stdout)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), [path.name])

    def test_missing_file_cli_returns_structured_error_without_path_or_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "private-no-log.txt"
            result = subprocess.run([sys.executable, str(ROOT / "scripts/boot_diagnostics.py"),
                                     str(missing), "--json"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["result"], "input_error")
            self.assertNotIn(str(missing), result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stdout + result.stderr)
            report = diag.analyze_log(missing, "invalid-private-id")
            self.assertEqual(report["exit_code"], 2)
            self.assertIsNone(report["run_id"])
            self.assertEqual(report["issues"][0]["code"], "invalid_requested_run_id")


class NativeBootFixtureCompatibilityTests(unittest.TestCase):
    """Compile the real logger; fixture observations remain synthetic evidence."""

    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CC", "cc"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("A C compiler is required for native fixture compatibility")
        cls.directory = tempfile.TemporaryDirectory(prefix="g2m-boot-analyzer-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = Path(cls.directory.name) / "boot-trace"
        compiled = subprocess.run(
            compiler + ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pthread",
                        str(ROOT / "dm/host/boot_trace.c"),
                        str(ROOT / "dm/host/tests/boot_trace_fixture.c"),
                        "-o", str(cls.binary)],
            capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise RuntimeError(
                f"Native boot fixture compilation failed (exit {compiled.returncode}):\n"
                f"{compiled.stdout}{compiled.stderr}")

    def test_native_observation_orders_and_missing_dependencies(self):
        env = os.environ.copy()
        env["DM_RUN_RECEIPT"] = A
        for mode in (None, "present_before_submit", "gpu_during_init"):
            with self.subTest(mode=mode):
                command = [str(self.binary)] + ([mode] if mode else [])
                fixture = subprocess.run(command, env=env, check=True,
                                         capture_output=True, timeout=20)
                events = [json.loads(line[len(diag.PREFIX):])
                          for line in fixture.stderr.splitlines() if line.startswith(diag.PREFIX)]
                report = analyze(fixture.stderr)
                self.assertEqual(report["exit_code"], 0, report)
                self.assertTrue(report["first_present"]["valid"])
                self.assertEqual(report["event_count"], len(events))
                self.assertEqual(report["run_id"], A)
                if mode is None:
                    continue
                stages = [row["stage"] for row in events]
                presented = stages.index("first_present")
                dependency = "gpu_submit" if mode == "present_before_submit" else "guest_entry"
                self.assertLess(presented, stages.index(dependency))
                incomplete = analyze(encoded(*events[:presented + 1]))
                self.assertEqual(incomplete["exit_code"], 2)
                self.assertFalse(incomplete["first_present"]["valid"])


if __name__ == "__main__":
    unittest.main()
