"""Asset-free regressions for the local read-only operator contract."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import g2mctl


def fake_report(result: str, exit_code: int) -> dict:
    return {
        "run_id": "a" * 32, "result": result, "exit_code": exit_code,
        "last_stage": {"stage": "guest_entry", "status": "begin", "seq": 4},
        "last_incomplete_stage": None,
        "gpu_submit": {"observed": result == "first_present_observed", "elapsed_ms": 120},
        "first_present": {"observed": result == "first_present_observed",
                          "valid": result == "first_present_observed", "elapsed_ms": 130},
        "issue_count": 0, "next_action": "检查本次首帧后继续验收。",
        "playability": "unverified", "timeline": [],
    }


class OperatorCLITests(unittest.TestCase):
    def test_capabilities_are_read_only(self):
        with patch.object(g2mctl, "analyze_log", side_effect=AssertionError("read")):
            result = g2mctl.operate(["capabilities"])
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["operations"]["status"])
        self.assertFalse(result["operations"]["build"])
        self.assertFalse(result["operations"]["http_control"])
        self.assertEqual(result["playability"], "unverified")

    def test_build_is_explicitly_unsupported_and_never_runs(self):
        with patch.object(g2mctl, "analyze_log", side_effect=AssertionError("read")), \
             patch.object(g2mctl, "verify_identity", side_effect=AssertionError("read")):
            result = g2mctl.operate(["build"])
        self.assertEqual((result["code"], result["exit_code"]), ("NOT_SUPPORTED", 3))

    def test_default_log_is_within_dm_root_and_only_read(self):
        with patch.object(g2mctl, "analyze_log", return_value=fake_report("awaiting_gpu_submit", 1)) as log:
            result = g2mctl.operate(["next"], environ={"DM_ROOT": "/tmp/owned-private-work"})
        log.assert_called_once_with(Path("/tmp/owned-private-work/run/ios/out/boot.txt"), None)
        self.assertEqual(result["code"], "AWAITING_GPU_SUBMIT")
        self.assertEqual(result["exit_code"], 1)

    def test_explicit_run_id_is_not_replaced(self):
        with patch.object(g2mctl, "analyze_log", return_value=fake_report("no_boot_evidence", 1)) as log:
            result = g2mctl.operate(["next", "--log", "boot.txt", "--run-id", "b" * 32])
        log.assert_called_once_with(Path("boot.txt"), "b" * 32)
        self.assertEqual(result["code"], "NO_BOOT_EVIDENCE")

    def test_status_without_app_does_not_claim_build_verification(self):
        with patch.object(g2mctl, "analyze_log", return_value=fake_report("first_present_observed", 0)), \
             patch.object(g2mctl, "verify_identity", side_effect=AssertionError("verify")):
            result = g2mctl.operate(["status", "--log", "boot.txt"])
        self.assertEqual(result["code"], "FIRST_PRESENT_OBSERVED")
        self.assertFalse(result["identity"]["verified"])
        self.assertEqual(result["identity"]["status"], "not_checked")
        self.assertEqual(result["playability"], "unverified")

    def test_app_check_calls_actual_byte_verifier(self):
        actual = {"build_identity_verified": True,
                  "embedded_guest_bytes_verified": True,
                  "bundled_shader_bytes_verified": True,
                  "build_identity_fingerprint": "0" * 64}
        with patch.object(g2mctl, "analyze_log", return_value=fake_report("awaiting_first_present", 1)), \
             patch.object(g2mctl, "verify_identity", return_value=actual) as verify:
            result = g2mctl.operate(["status", "--app", "/private/DmIOS.app",
                                     "--profile", "m3", "--require-clean"])
        verify.assert_called_once_with(Path("/private/DmIOS.app"), "m3", repo=g2mctl.ROOT,
                                       require_clean=True)
        self.assertEqual(result["exit_code"], 1)  # Boot remains incomplete.
        self.assertTrue(result["identity"]["embedded_guest_bytes_verified"])
        self.assertEqual(result["identity"]["profile"], "m3")

    def test_private_path_from_os_error_never_printed(self):
        with patch.object(g2mctl, "analyze_log", return_value=fake_report("first_present_observed", 0)), \
             patch.object(g2mctl, "verify_identity", side_effect=OSError("/secret/private/asset")):
            result = g2mctl.operate(["status", "--app", "/secret/private/asset",
                                     "--profile", "metal4"])
        self.assertEqual((result["code"], result["exit_code"]), ("BUILD_IDENTITY_INVALID", 2))
        self.assertNotIn("/secret", json.dumps(result))
        self.assertFalse(result["identity"]["verified"])

    def test_app_and_profile_must_be_explicit_pair(self):
        for args in (["status", "--app", "/private/DmIOS.app"],
                     ["status", "--profile", "metal4"],
                     ["status", "--require-clean"],
                     ["status", "--app", "/private/DmIOS.app", "--profile", "invalid"]):
            with self.subTest(args=args), patch.object(g2mctl, "analyze_log", side_effect=AssertionError("read")):
                report = g2mctl.operate(args)
                self.assertEqual((report["code"], report["exit_code"]), ("BAD_ARGUMENT", 2))

    def test_invalid_cli_arguments_have_fixed_json_error(self):
        with patch.object(g2mctl, "analyze_log", side_effect=AssertionError("read")):
            for args in (["missing", "--log", "/secret/private"],
                         ["status", "--app", "/secret/private", "--profile", "invalid"]):
                report = g2mctl.operate(args)
                self.assertEqual(report["code"], "BAD_ARGUMENT")
                self.assertNotIn("/secret", json.dumps(report))

    def test_diagnose_preserves_underlying_analyzer_result(self):
        data = fake_report("runtime_error", 1)
        with patch.object(g2mctl, "analyze_log", return_value=data):
            report = g2mctl.operate(["diagnose", "--log", "boot.txt"])
        self.assertEqual(report["diagnosis"], data)
        self.assertEqual(report["code"], "RUNTIME_ERROR")
        self.assertEqual(report["exit_code"], 1)

    def test_exit_code_matches_single_json_line(self):
        with patch.object(g2mctl, "analyze_log", return_value=fake_report("awaiting_gpu_submit", 1)):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = g2mctl.main(["status", "--log", "/private/boot.txt"])
        self.assertEqual(status, 1)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(json.loads(output.getvalue())["exit_code"], status)
        self.assertNotIn("/private", output.getvalue())


if __name__ == "__main__":
    unittest.main()
