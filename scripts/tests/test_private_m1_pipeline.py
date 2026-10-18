"""M1 owner-only input isolation and local build workflow tests, with no game data."""
from __future__ import annotations

import json
import os
import stat
import sys
import subprocess
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
    execute, new_private_evidence_dir, private_environment, run_pipeline,
    workspace_is_safe, write_private_json,
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
            passed = {
                "real_guest_macho_segments_verified": True,
                "game_runtime_resources_verified": True,
                "app_device_signature_verified": True,
                "executable_sha256": "c" * 64,
            }
            with mock.patch("scripts.m1_local_pipeline.validate_real_game_bundle",
                            return_value=passed) as check:
                self.assertEqual(validate_app(app, "metal4"), passed)
                check.assert_called_once_with(app, "metal4")
            from scripts.m1_game_bundle import BundleValidationError
            with mock.patch("scripts.m1_local_pipeline.validate_real_game_bundle",
                            side_effect=BundleValidationError("Missing guest segments")):
                with self.assertRaisesRegex(StageError, "Missing guest segments"):
                    validate_app(app, "m3")


class FreshBuildEvidenceTests(unittest.TestCase):
    def test_evidence_runs_are_unique_and_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            first = new_private_evidence_dir(workspace, "a" * 40, "metal4")
            second = new_private_evidence_dir(workspace, "a" * 40, "metal4")
            self.assertNotEqual(first, second)
            self.assertTrue(first.name.startswith("run-"))
            self.assertTrue(second.name.startswith("run-"))
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(second.stat().st_mode), 0o700)
            self.assertTrue(first.is_relative_to(workspace))

    def test_evidence_rejects_symlink_into_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "m1-private-evidence").symlink_to(ROOT, target_is_directory=True)
            with self.assertRaisesRegex(StageError, "symlink"):
                new_private_evidence_dir(workspace, "a" * 40, "metal4")

    def test_inherited_build_shortcuts_do_not_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            evidence = new_private_evidence_dir(workspace, "a" * 40, "m3")
            env = private_environment(
                {"DM_GEN_ONLY": "1", "DM_IOS_DD": "/stale",
                 "DM_OUT": "/wrong", "DM_NOINSTALL": "1",
                 "PATH": "/usr/bin", "DM_FREE_ACCOUNT": "1"},
                workspace, workspace / "data/RomFS", "m3", evidence
            )
            self.assertNotIn("DM_GEN_ONLY", env)
            self.assertNotIn("DM_OUT", env)
            self.assertNotIn("DM_NOINSTALL", env)
            self.assertEqual(Path(env["DM_IOS_DD"]), evidence / "derived-data")
            self.assertEqual(env["DM_M1_FRESH_DERIVED_DATA"], env["DM_IOS_DD"])
            self.assertEqual(env["DM_IOS_M3"], "1")
            self.assertEqual(env["DM_M1_REQUIRED_PROFILE"], "m3")
            self.assertEqual(env["DM_FREE_ACCOUNT"], "1")

    def test_logs_are_restricted_before_running_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary)
            code = (
                "import os,stat,sys;"
                "p=sys.argv[1];"
                "assert stat.S_IMODE(os.stat(p).st_mode)==0o600;"
                "print('permission checked while process running')"
            )
            logfile = evidence / "preflight.private.log"
            execute("preflight", [sys.executable, "-c", code, str(logfile)],
                    cwd=ROOT, env=os.environ.copy(), evidence_dir=evidence)
            self.assertIn("permission checked",
                          logfile.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(logfile.stat().st_mode), 0o600)

    def test_private_summary_cannot_overwrite_prior_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "summary.json"
            write_private_json(path, {"result": "passed"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                write_private_json(path, {"result": "failed"})
            self.assertEqual(json.loads(path.read_text()), {"result": "passed"})

    def test_existing_old_app_cannot_satisfy_a_new_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "owner-workspace"
            old = workspace / "run/ios/dd/Build/Products/Release-iphoneos/DmIOS.app"
            old.mkdir(parents=True)
            (old / "DmIOS").write_bytes(b"stale object" * 100)
            romfs = workspace / "data/switch/3.3.94012/Update/RomFS"
            with (
                mock.patch("scripts.m1_local_pipeline.checked_platform"),
                mock.patch("scripts.m1_local_pipeline.tracked_clean"),
                mock.patch("scripts.m1_local_pipeline.ignored_headers", return_value=True),
                mock.patch("scripts.m1_local_pipeline.head_sha", return_value="b" * 40),
                mock.patch("scripts.m1_local_pipeline.execute", return_value=None),
            ):
                with self.assertRaisesRegex(StageError, "Fresh DmIOS.app missing"):
                    run_pipeline("build", "metal4", workspace, romfs)
            root = workspace / "m1-private-evidence" / ("b" * 12) / "metal4"
            folders = list(root.glob("run-*"))
            self.assertEqual(len(folders), 1)
            report = json.loads((folders[0] / "m1-summary.json").read_text())
            self.assertEqual(report["result"], "failed")
            self.assertFalse(report["full_game_app_built"])
            self.assertFalse(report["app_signed_locally"])
            self.assertEqual(report["steps"], {"build": "failed"})

    def test_standalone_build_reports_partial_not_end_to_end(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "owner-workspace"
            romfs = workspace / "data/switch/3.3.94012/Update/RomFS"
            observed = []
            def fake_execute(stage, command, *, cwd, env, evidence_dir):
                self.assertNotIn("DM_GEN_ONLY", env)
                self.assertEqual(env["DM_M1_FRESH_DERIVED_DATA"], env["DM_IOS_DD"])
                self.assertTrue(Path(env["DM_IOS_DD"]).is_relative_to(evidence_dir))
                observed.append((stage, Path(env["DM_IOS_DD"])))
            with (
                mock.patch("scripts.m1_local_pipeline.checked_platform"),
                mock.patch("scripts.m1_local_pipeline.tracked_clean"),
                mock.patch("scripts.m1_local_pipeline.ignored_headers", return_value=True),
                mock.patch("scripts.m1_local_pipeline.head_sha", return_value="c" * 40),
                mock.patch("scripts.m1_local_pipeline.execute", side_effect=fake_execute),
                mock.patch("scripts.m1_local_pipeline.validate_app", return_value={
                    "real_guest_macho_segments_verified": True,
                    "game_runtime_resources_verified": True,
                    "shader_map_coverage_verified": True,
                    "shader_reflection_coverage_verified": True,
                    "shader_chain_verified": True,
                    "transformed_shader_library_count": 6938,
                    "seeded_shader_count": 181,
                    "app_device_signature_verified": True,
                    "executable_sha256": "e" * 64,
                }),
            ):
                with mock.patch.dict(os.environ, {"DM_GEN_ONLY": "1"}, clear=False):
                    record = run_pipeline("build", "metal4", workspace, romfs)
                self.assertEqual(record["steps"], {"build": "passed"})
            self.assertEqual(record["result"], "partial")
            self.assertFalse(record["end_to_end_build_stages_verified"])
            self.assertTrue(record["full_game_app_built"])
            self.assertTrue(record["real_game_module_sections_verified"])
            self.assertTrue(record["game_runtime_resources_verified"])
            self.assertTrue(record["shader_map_coverage_verified"])
            self.assertTrue(record["shader_reflection_coverage_verified"])
            self.assertTrue(record["shader_chain_verified"])
            self.assertEqual(record["translated_shader_library_count"], 6938)
            self.assertEqual(record["seeded_shader_count"], 181)
            self.assertEqual(record["app_binary_sha256"], "e" * 64)
            self.assertEqual(len(observed), 1)
            self.assertFalse(observed[0][1].is_relative_to(ROOT))


class M1ShellOverrideTests(unittest.TestCase):
    """Exercise the real run.sh override in an isolated shell, without game files."""

    def override_script(self) -> str:
        contents = (ROOT / "dm/ios/run.sh").read_text(encoding="utf-8")
        marker = 'if [ -n "${DM_M1_FRESH_DERIVED_DATA:-}" ]; then'
        start = contents.index(marker)
        end = contents.index("\nfi\n", start) + len("\nfi\n")
        self.assertLess(contents.index("source tools/local_env.sh"), start)
        self.assertLess(end, contents.index("DD=${DM_IOS_DD:-"))
        return contents[start:end]

    def run_guard(self, fresh: str | None, gen_only: str,
                  profile: str = "metal4") -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary) / "local.env"
            local.write_text(
                'DM_IOS_DD=/stale-previous-build\n'
                'DM_OUT=/stale-previous-game-patch\n'
                'DM_IOS_M3=1\n'
                f'DM_GEN_ONLY={gen_only}\n',
                encoding="utf-8",
            )
            script = (
                "set -u\n" +
                "source " + str(local) + "\n" +
                self.override_script() +
                "\nprintf '%s|%s|%s' \"${DM_IOS_DD:-}\" \"${DM_OUT:-}\" \"${DM_IOS_M3:-}\"\n"
            )
            env = os.environ.copy()
            env.pop("DM_M1_FRESH_DERIVED_DATA", None)
            env.pop("DM_M1_REQUIRED_PROFILE", None)
            if fresh is not None:
                env["DM_M1_FRESH_DERIVED_DATA"] = fresh
                env["DM_M1_REQUIRED_PROFILE"] = profile
            return subprocess.run(
                ["bash", "-c", script], env=env,
                capture_output=True, text=True, check=False,
            )

    def test_private_override_wins_after_local_env(self):
        result = self.run_guard("/isolated/new-derived-data", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "/isolated/new-derived-data||0")

    def test_selected_m3_overrides_old_local_config(self):
        result = self.run_guard("/isolated/new-derived-data", "0", "m3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "/isolated/new-derived-data||1")

    def test_gen_only_from_local_env_fails_fast(self):
        result = self.run_guard("/isolated/new-derived-data", "1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("refuses DM_GEN_ONLY=1", result.stderr)

    def test_missing_m1_profile_fails_closed(self):
        result = self.run_guard("/isolated/new-derived-data", "0", "bogus")
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires DM_M1_REQUIRED_PROFILE", result.stderr)

    def test_normal_build_configuration_is_unchanged(self):
        result = self.run_guard(None, "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout, "/stale-previous-build|/stale-previous-game-patch|1"
        )


if __name__ == "__main__":
    unittest.main()
