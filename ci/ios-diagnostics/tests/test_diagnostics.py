"""Offline regression tests for the NON-PLAYABLE iOS diagnostic build tools."""
from __future__ import annotations
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import simulator_smoke
import verify_artifact


class DiagnosticArtifactTests(unittest.TestCase):
    def make_app(self, folder: Path) -> Path:
        app = folder / "Game2MobileDiagnostics.app"
        app.mkdir(parents=True)
        (app / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleDisplayName": "Game2Mobile Diagnostics",
            "CFBundleIdentifier": "com.game2mobile.diagnostics.smoke",
            "CFBundleExecutable": "Game2MobileDiagnostics",
        }))
        (app / "Game2MobileDiagnostics").write_bytes(b"fake-machine-code" * 1000)
        (app / "Assets.car").write_bytes(b"asset-catalog-fixture")
        return app

    def test_valid_non_playable_binary_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(Path(temp))
            with mock.patch.object(verify_artifact.subprocess, "check_output", return_value="arm64\n"):
                result = verify_artifact.verify(app, "iphoneos", "test-sha")
            self.assertTrue(result["arm64_macho"])
            self.assertFalse(result["gameplay_tested"])
            self.assertFalse(result["proprietary_game_assets_included"])

    def test_reject_game_runtime_derived_file(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(Path(temp))
            extra = app / "dm/main.patched.bin"
            extra.parent.mkdir(parents=True)
            extra.write_bytes(b"not-allowed")
            with mock.patch.object(verify_artifact.subprocess, "check_output", return_value="arm64\n"):
                with self.assertRaisesRegex(ValueError, "game-derived"):
                    verify_artifact.verify(app, "iphoneos", "test-sha")

    def test_reject_wrong_bundle_id(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(Path(temp))
            info = plistlib.loads((app / "Info.plist").read_bytes())
            info["CFBundleIdentifier"] = "com.someone.else"
            (app / "Info.plist").write_bytes(plistlib.dumps(info))
            with self.assertRaisesRegex(ValueError, "CFBundleIdentifier"):
                verify_artifact.verify(app, "iphoneos", "test-sha")

    def test_reject_non_arm64_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(Path(temp))
            with mock.patch.object(verify_artifact.subprocess, "check_output", return_value="x86_64\n"):
                with self.assertRaisesRegex(ValueError, "ARM64"):
                    verify_artifact.verify(app, "iphonesimulator", "test-sha")


class SimulatorSelectionTests(unittest.TestCase):
    def test_prefers_latest_available_ios_iphone(self):
        entries = {"devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-25-6": [
                {"udid": "old", "name": "iPhone 16", "isAvailable": True, "state": "Shutdown"}
            ],
            "com.apple.CoreSimulator.SimRuntime.iOS-26-2": [
                {"udid": "new", "name": "iPhone 17", "isAvailable": True, "state": "Booted"},
                {"udid": "ipad", "name": "iPad Air", "isAvailable": True, "state": "Shutdown"},
            ],
        }}
        _, uuid, runtime, state = simulator_smoke.select_simulator(entries)
        self.assertEqual(uuid, "new")
        self.assertIn("26-2", runtime)
        self.assertEqual(state, "Booted")

    def test_does_not_claim_runtime_without_iphone(self):
        entries = {"devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-26-2": [
                {"udid": "ipad", "name": "iPad Air", "isAvailable": True, "state": "Shutdown"}
            ],
        }}
        with self.assertRaisesRegex(RuntimeError, "No available"):
            simulator_smoke.select_simulator(entries)


if __name__ == "__main__":
    unittest.main()
