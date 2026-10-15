"""M1 owner-only input isolation and local build workflow tests, with no game data."""
from __future__ import annotations

import json
from pathlib import Path
import plistlib
from unittest import mock
import tempfile
import unittest

from scripts.private_build_inputs import (
    HEADER_NAMES, PrivateInputError, inspect_private_headers,
    private_output_is_safe, stage_private_headers,
)
from scripts.m1_local_pipeline import (
    ROOT, StageError, build_plan, build_record, validate_app,
    workspace_is_safe,
)


def make_synthetic_header_set(folder: Path) -> None:
    # Trivial synthetic files are ONLY used to test boundary checks, never
    # compiled or described as generated game assets or real source code.
    folder.mkdir(parents=True, exist_ok=True)
    for name in HEADER_NAMES:
        (folder / name).write_text(
            f"/* Non-game synthetic safety test for {name}. */\n"
            "#pragma once\nint test_fixture_unused;\n",
            encoding="utf-8",
        )


class PrivateHeaderIsolationTests(unittest.TestCase):
    def test_stage_only_whitelisted_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "owner"
            make_synthetic_header_set(private)
            (private / "sensitive.save").write_text("DO NOT COPY", encoding="utf-8")
            staged = root / "isolated/dm"
            (staged / "host").mkdir(parents=True)
            stage_private_headers(private, staged)
            self.assertEqual(
                sorted(p.name for p in (staged / "host").iterdir()),
                sorted(HEADER_NAMES),
            )
            self.assertFalse((staged / "host/sensitive.save").exists())
            self.assertEqual(len(inspect_private_headers(private)), 3)

    def test_missing_private_header_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp) / "owned"
            make_synthetic_header_set(private)
            (private / HEADER_NAMES[0]).unlink()
            with self.assertRaisesRegex(PrivateInputError, "Missing locally generated header"):
                inspect_private_headers(private)

    def test_private_header_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp) / "owned"
            make_synthetic_header_set(private)
            target = private / HEADER_NAMES[0]
            actual = private / "private-not-for-staging"
            target.rename(actual)
            target.symlink_to(actual)
            with self.assertRaisesRegex(PrivateInputError, "regular file"):
                inspect_private_headers(private)

    def test_binary_and_stub_data_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp) / "owned"
            make_synthetic_header_set(private)
            (private / HEADER_NAMES[0]).write_bytes(b"binary\0" * 20)
            with self.assertRaisesRegex(PrivateInputError, "Invalid generated game header"):
                inspect_private_headers(private)
            (private / HEADER_NAMES[0]).write_text(
                "CI fixture only: no proprietary data to compile here\n" * 2
            )
            with self.assertRaisesRegex(PrivateInputError, "Invalid generated game header"):
                inspect_private_headers(private)

    def test_no_overwrite_of_staged_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "owner"
            make_synthetic_header_set(private)
            staged = root / "isolated/dm"
            (staged / "host").mkdir(parents=True)
            (staged / "host" / HEADER_NAMES[1]).write_text("already here")
            with self.assertRaisesRegex(PrivateInputError, "Refusing to overwrite"):
                stage_private_headers(private, staged)

    def test_private_json_cannot_be_saved_inside_repo(self):
        self.assertFalse(private_output_is_safe(ROOT / "unsafe.json", ROOT))
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(private_output_is_safe(Path(temp) / "safe.json", ROOT))


class OwnerPipelineTests(unittest.TestCase):
    def test_plan_is_asset_free_and_explicit(self):
        plan = build_plan("metal4")
        self.assertEqual([name for name, _ in plan],
                         ["preflight", "prepare", "headers", "verify", "build"])
        self.assertIn("91/91", plan[3][1])
        self.assertNotIn("GitHub", " ".join(d for _, d in plan))

    def test_workspace_must_be_outside_git_checkout(self):
        self.assertFalse(workspace_is_safe(ROOT / "dm/m1-private-evidence"))
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(workspace_is_safe(Path(temp)))

    def test_report_has_no_private_path_or_credentials(self):
        data = build_record("f" * 40, "metal4")
        self.assertTrue(data["uploaded_anything"] is False)
        self.assertFalse(data["report_contains_keys_or_device_identifiers"])
        self.assertFalse(data["physical_device_gameplay_tested"])
        serialized = json.dumps(data)
        for private_key in ("DM_TEAM_ID", "DM_IOS_UDID", "DM_BUNDLE_ID"):
            self.assertNotIn(private_key, serialized)

    def test_validate_real_bundle_signature_mock(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / "DmIOS.app"
            app.mkdir()
            (app / "DmIOS").write_bytes(b"MachO" * 120)
            (app / "Info.plist").write_bytes(
                plistlib.dumps({"CFBundleDisplayName": "Game2Mobile"})
            )
            with mock.patch("scripts.m1_local_pipeline.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout="arm64\n"),
                    mock.Mock(returncode=0, stdout=""),
                ]
                self.assertTrue(validate_app(app))
            with mock.patch("scripts.m1_local_pipeline.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout="arm64\n"),
                    mock.Mock(returncode=1, stdout=""),
                ]
                with self.assertRaisesRegex(StageError, "code signature"):
                    validate_app(app)


if __name__ == "__main__":
    unittest.main()
