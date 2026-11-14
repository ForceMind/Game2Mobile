"""Synthetic safety and classification tests for public prerequisite probes."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest
from unittest.mock import patch

from scripts import g2mctl, local_doctor


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class LocalDoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".git").mkdir()
        self.invocations = []

    def find(self, name):
        return "/mock-tools/" + name

    def probe(self, command, **kwargs):
        self.invocations.append((tuple(command), kwargs))
        return Result()

    def report(self, **kwargs):
        return local_doctor.doctor_environment(
            root=self.root, system="darwin", machine="arm64",
            which=self.find, run=self.probe, xcrun_present=True, **kwargs)

    def test_ready_only_for_public_tools_not_device_game_or_signing(self):
        result = self.report()
        self.assertTrue(result["toolchain_ready"])
        self.assertFalse(result["private_inputs_verified"])
        self.assertFalse(result["signing_verified"])
        self.assertFalse(result["device_verified"])
        statuses = {i["id"]: i["status"] for i in result["checks"]}
        self.assertEqual(statuses["source_clean"], "ready")
        self.assertTrue(all(statuses[k] == "not_checked" for k in
                            ("licensed_inputs", "local_signing", "physical_device")))
        self.assertEqual(len(self.invocations), 4)
        self.assertEqual(self.invocations[0][0][-3:], ("status", "--porcelain", "--untracked-files=all"))
        self.assertTrue(all(k["timeout"] == 5 for _, k in self.invocations))
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_dirty_git_is_blocked_without_echoing_private_names(self):
        def runner(command, **kwargs):
            if "status" in command:
                return Result(stdout="?? /Users/private/secret-key.txt\n")
            return Result()
        self.probe = runner
        result = self.report()
        self.assertFalse(result["toolchain_ready"])
        self.assertEqual({c["id"]: c["status"] for c in result["checks"]}["source_clean"], "blocked")
        self.assertNotIn("secret-key", json.dumps(result))

    def test_missing_tools_do_not_run_commands(self):
        self.find = lambda name: None
        result = self.report()
        statuses = {c["id"]: c["status"] for c in result["checks"]}
        self.assertEqual(statuses["python3"], "missing")
        self.assertEqual(statuses["source_clean"], "unknown")
        self.assertEqual(len(self.invocations), 3)

    def test_non_apple_is_not_ready_and_never_executes_xcrun(self):
        result = local_doctor.doctor_environment(root=self.root, system="linux",
            machine="x86_64", which=self.find, run=self.probe, xcrun_present=False)
        self.assertFalse(result["toolchain_ready"])
        statuses = {c["id"]: c["status"] for c in result["checks"]}
        self.assertEqual(statuses["metal_compiler"], "unsupported")
        self.assertEqual(len(self.invocations), 1)

    def test_missing_apple_sdk_probe_does_not_execute_apple_commands(self):
        result = local_doctor.doctor_environment(root=self.root, system="darwin",
            machine="arm64", which=self.find, run=self.probe, xcrun_present=False)
        statuses = {c["id"]: c["status"] for c in result["checks"]}
        self.assertEqual(statuses["xcode"], "missing")
        self.assertEqual(statuses["iphoneos_sdk"], "missing")
        self.assertEqual(statuses["metal_compiler"], "missing")
        self.assertFalse(result["toolchain_ready"])
        self.assertEqual(len(self.invocations), 1)

    def test_missing_git_checkout_does_not_traverse_workspace(self):
        (self.root / ".git").rmdir()
        result = self.report()
        statuses = {c["id"]: c["status"] for c in result["checks"]}
        self.assertEqual(statuses["git_checkout"], "missing")
        self.assertEqual(statuses["source_clean"], "unknown")
        self.assertEqual(len(self.invocations), 3)

    def test_timeouts_and_command_failures_report_unknown_or_missing(self):
        def slow(command, **kwargs):
            if "status" in command:
                raise subprocess.TimeoutExpired(command, 5)
            if "xcodebuild" in command:
                return Result(returncode=1, stderr="private/internal/path")
            if "iphoneos" in command and "metal" in command:
                raise OSError("/private/build path")
            return Result()
        self.probe = slow
        result = self.report()
        statuses = {c["id"]: c["status"] for c in result["checks"]}
        self.assertEqual(statuses["source_clean"], "unknown")
        self.assertEqual(statuses["xcode"], "missing")
        self.assertEqual(statuses["metal_compiler"], "unknown")
        self.assertNotIn("/private/", json.dumps(result))

    def test_cli_protocol_does_not_expose_private_paths(self):
        fake = self.report()
        with patch.object(local_doctor, "doctor_environment", return_value=fake):
            result = g2mctl.operate(["doctor"])
            self.assertEqual(result["code"], "LOCAL_TOOLCHAIN_READY")
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["scope"], "local-read-only")
            self.assertEqual(result["playability"], "unverified")
            self.assertTrue(result["toolchain_ready"])
            self.assertNotIn(str(self.root), json.dumps(result))
            fake["toolchain_ready"] = False
            self.assertEqual(g2mctl.operate(["doctor"])["exit_code"], 1)


if __name__ == "__main__":
    unittest.main()
