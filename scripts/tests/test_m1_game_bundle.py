"""Asset-free tests of the real-game bundle acceptance gate.

Fake fixtures here validate the gate logic only; they are NOT compiled
games, signed Apple bundles or replacements for the owner's licensed assets.
"""
from __future__ import annotations

from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest import mock

from scripts.m1_game_bundle import (
    BundleValidationError,
    EXPECTED_RUNTIME_FILES,
    ios_version,
    require_guest_sections,
    require_runtime_resources,
    validate_real_game_bundle,
)

MACHO_GUEST_SECTIONS = """
Load command 0
   segname __TEXT
Section
   sectname __dmmainx0
   segname __TEXT
Section
   sectname __dmmainx1
   segname __TEXT
Section
   sectname __dmsdkx0
   segname __TEXT
Section
   sectname __dmsdkx1
   segname __TEXT
Load command 7
   segname __DMmainW
Section
   sectname __img
   segname __DMmainW
Load command 8
   segname __DMsdkW
Section
   sectname __img
   segname __DMsdkW
"""


def make_mock_game_app(directory: Path, minimum: str = "26.0") -> Path:
    app = directory / "DmIOS.app"
    app.mkdir()
    (app / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleDisplayName": "Game2Mobile",
        "CFBundleIdentifier": "com.example.game2mobile.owner",
        "CFBundleExecutable": "DmIOS",
        "MinimumOSVersion": minimum,
    }))
    (app / "DmIOS").write_bytes(b"fake-file-for-acceptance-tests" * 100)
    for name in EXPECTED_RUNTIME_FILES:
        path = app / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"local-test-fixture" * 20)
    shader = app / "msl/b-testchain/example_b.metallib"
    shader.parent.mkdir(parents=True, exist_ok=True)
    shader.write_bytes(b"fake-metallib-content-test")
    return app


def valid_tools(args, description):
    if args[0] == "lipo":
        return "arm64\n"
    if args[0] == "otool":
        return MACHO_GUEST_SECTIONS
    if args[0] == "codesign":
        return ""
    raise AssertionError("Unexpected Apple verification tool")


class RealGameBundleChecksTests(unittest.TestCase):
    def test_version_decoder(self):
        self.assertEqual(ios_version("26.0"), (26, 0))
        self.assertEqual(ios_version("18"), (18, 0))
        self.assertEqual(ios_version("18.0.0"), (18, 0))
        with self.assertRaises(BundleValidationError):
            ios_version("n/a")

    def test_embedded_game_guest_segments(self):
        found = require_guest_sections(MACHO_GUEST_SECTIONS)
        self.assertEqual(sorted(found), ["main", "sdk"])

    def test_unsigned_shell_cannot_pass_guest_sections(self):
        with self.assertRaisesRegex(BundleValidationError, "main missing"):
            require_guest_sections("""
            Load command 0
                segname __TEXT
            Section
                sectname __text
                segname __TEXT
            """)

    def test_partial_game_sdk_rejected(self):
        with self.assertRaisesRegex(BundleValidationError, "sdk missing"):
            require_guest_sections(MACHO_GUEST_SECTIONS.replace("__dmsdkx1", "__not_sdk"))

    def test_real_game_bundle_acceptance_logic(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            with mock.patch("scripts.m1_game_bundle._apple_tool",
                            side_effect=valid_tools) as apple:
                outcome = validate_real_game_bundle(app, "metal4")
            self.assertEqual(apple.call_count, 3)
            self.assertEqual(outcome["guest_module_count"], 2)
            self.assertTrue(outcome["game_runtime_resources_verified"])
            self.assertTrue(outcome["app_device_signature_verified"])
            self.assertFalse(outcome["real_device_installed"])
            self.assertFalse(outcome["gameplay_tested"])
            self.assertEqual(len(outcome["executable_sha256"]), 64)

    def test_wrong_os_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary), "26.0")
            with self.assertRaisesRegex(BundleValidationError, "deployment target"):
                validate_real_game_bundle(app, "m3")

    def test_m3_bundle_with_ios18_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary), "18.0")
            with mock.patch("scripts.m1_game_bundle._apple_tool", side_effect=valid_tools):
                result = validate_real_game_bundle(app, "m3")
            self.assertTrue(result["actual_minimum_ios_version_verified"])

    def test_missing_or_empty_resource_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            (app / "dm/sdk.gates.tsv").unlink()
            with self.assertRaisesRegex(BundleValidationError, "sdk.gates.tsv"):
                require_runtime_resources(app)
            (app / "dm/sdk.gates.tsv").write_bytes(b"")
            with self.assertRaisesRegex(BundleValidationError, "sdk.gates.tsv"):
                require_runtime_resources(app)

    def test_missing_translated_shaders_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            (app / "msl/b-testchain/example_b.metallib").unlink()
            with self.assertRaisesRegex(BundleValidationError, "shader libraries"):
                require_runtime_resources(app)

    def test_empty_provisioning_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            (app / "embedded.mobileprovision").write_bytes(b"small")
            with mock.patch("scripts.m1_game_bundle._apple_tool", side_effect=valid_tools):
                with self.assertRaisesRegex(BundleValidationError, "provisioning profile"):
                    validate_real_game_bundle(app, "metal4")

    def test_signature_failure_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            def unsigned(args, description):
                if args[0] == "codesign":
                    raise BundleValidationError("Apple device code-signature check failed")
                return valid_tools(args, description)
            with mock.patch("scripts.m1_game_bundle._apple_tool", side_effect=unsigned):
                with self.assertRaisesRegex(BundleValidationError, "code-signature"):
                    validate_real_game_bundle(app, "metal4")

    def test_diagnostic_app_identity_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            info = plistlib.loads((app / "Info.plist").read_bytes())
            info["CFBundleIdentifier"] = "com.game2mobile.diagnostics.smoke"
            (app / "Info.plist").write_bytes(plistlib.dumps(info))
            with self.assertRaisesRegex(BundleValidationError, "bundle identifier"):
                validate_real_game_bundle(app, "metal4")

    def test_missing_assets_catalog_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            (app / "Assets.car").unlink()
            with self.assertRaisesRegex(BundleValidationError, "Assets.car"):
                require_runtime_resources(app)


if __name__ == "__main__":
    unittest.main()
