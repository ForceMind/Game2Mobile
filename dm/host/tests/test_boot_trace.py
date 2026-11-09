#!/usr/bin/env python3
"""Portable native boot-trace regression; no Apple SDK or game files required.

Run from any directory: python3 dm/host/tests/test_boot_trace.py
The events in this test are synthetic protocol fixtures, not runtime evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


TEST_DIR = Path(__file__).resolve().parent
HOST_DIR = TEST_DIR.parent
PREFIX = "G2M_BOOT "
RECEIPT = "0123456789abcdef0123456789abcdef"


class BootTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="g2m-boot-trace-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = Path(cls.directory.name) / "boot-trace"
        cls.optional_binary = Path(cls.directory.name) / "boot-trace-optional"
        compiler = shlex.split(os.environ.get("CC", "cc"))
        flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pthread"]
        source = TEST_DIR / "boot_trace_fixture.c"
        for command in (
            compiler + flags + [str(HOST_DIR / "boot_trace.c"), str(source), "-o", str(cls.binary)],
            compiler + flags + ["-DDM_BOOT_TRACE_OPTIONAL=1", str(source), "-o", str(cls.optional_binary)],
        ):
            subprocess.run(command, check=True, capture_output=True, text=True)

    def run_fixture(self, mode=None, receipt=RECEIPT):
        env = os.environ.copy()
        env.pop("DM_RUN_RECEIPT", None)
        if receipt is not None:
            env["DM_RUN_RECEIPT"] = receipt
        result = subprocess.run(
            [str(self.binary)] + ([mode] if mode else []),
            check=True, capture_output=True, text=True, env=env, timeout=20,
        )
        self.assertEqual(result.stdout, "")
        records = []
        for line in result.stderr.splitlines():
            if PREFIX in line:
                self.assertTrue(line.startswith(PREFIX), line)
                records.append(json.loads(line[len(PREFIX):]))
        self.assertGreater(len(records), 0)
        self.assertEqual([r["seq"] for r in records], list(range(1, len(records) + 1)))
        elapsed = [r["elapsed_ms"] for r in records]
        self.assertEqual(elapsed, sorted(elapsed))
        self.assertTrue(all(value >= 0 for value in elapsed))
        self.assertEqual(len({r["run_id"] for r in records}), 1)
        for record in records:
            self.assertEqual(record["schema"], 1)
            self.assertRegex(record["run_id"], r"^[0-9a-f]{32}$")
            self.assertIn(record["status"], ("begin", "ok", "error"))
            self.assertRegex(record["code"], r"^[a-z0-9_]{0,63}$")
            self.assertEqual(set(record) - {"module"}, {
                "schema", "run_id", "seq", "elapsed_ms", "stage", "status", "code",
            })
            if "module" in record:
                self.assertRegex(record["module"], r"^[A-Za-z0-9_]{1,15}$")
        return records, result.stderr

    def test_protocol_and_once_only_hooks(self):
        records, _ = self.run_fixture()
        self.assertEqual(len(records), 17)
        self.assertTrue(all(r["run_id"] == RECEIPT for r in records))
        for stage in ("gpu_submit", "first_present"):
            self.assertEqual([(r["status"], r["code"]) for r in records if r["stage"] == stage], [("ok", "")])
        self.assertEqual(records[-1]["stage"], "host_return")
        self.assertEqual(records[-1]["code"], "returned")

    def test_threaded_initialization_and_line_integrity(self):
        records, stderr = self.run_fixture("threads")
        self.assertEqual(len(records), 8 * 128 + 2)
        self.assertEqual(sum(r["stage"] == "gpu_submit" for r in records), 1)
        self.assertEqual(sum(r["stage"] == "first_present" for r in records), 1)
        self.assertIn("fixture diagnostic", stderr)

    def test_receipt_is_snapshotted_once(self):
        records, _ = self.run_fixture("change_receipt")
        self.assertTrue(all(r["run_id"] == RECEIPT for r in records))

    def test_missing_receipt_generates_new_process_id(self):
        first, _ = self.run_fixture(receipt=None)
        second, _ = self.run_fixture(receipt=None)
        self.assertNotEqual(first[0]["run_id"], second[0]["run_id"])

    def test_invalid_receipt_is_never_echoed(self):
        for invalid in ("", "abc", "A" * 32, "g" * 32, RECEIPT + "0", 'secret\"\n/path'):
            with self.subTest(receipt=repr(invalid)):
                records, stderr = self.run_fixture(receipt=invalid)
                self.assertNotEqual(records[0]["run_id"], invalid)
                if invalid and not re.fullmatch(r"[0-9a-f]+", invalid):
                    self.assertNotIn(invalid, stderr)

    def test_invalid_fields_do_not_inject_json_or_consume_sequence(self):
        records, stderr = self.run_fixture("invalid")
        self.assertEqual(len(records), 4)
        self.assertEqual(records[0]["module"], "sdk")
        self.assertTrue(all("module" not in r for r in records[1:]))
        self.assertEqual(records[1]["code"], "")
        self.assertEqual(records[2]["status"], "error")
        self.assertEqual(records[2]["code"], "missing_symbol")
        self.assertNotIn("secret", stderr)
        self.assertNotIn("module_name_longer", stderr)

    def test_optional_graphics_hooks_link_without_host(self):
        result = subprocess.run([str(self.optional_binary)], check=True, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.stdout + result.stderr, "")


if __name__ == "__main__":
    unittest.main()
