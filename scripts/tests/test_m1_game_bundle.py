"""Asset-free tests of the real-game bundle acceptance gate.

Fake fixtures here validate the gate logic only; they are NOT compiled
games, signed Apple bundles or replacements for the owner's licensed assets.
"""
from __future__ import annotations

from pathlib import Path
import json
import plistlib
import tempfile
import unittest
from unittest import mock

from scripts.m1_game_bundle import (
    BundleValidationError,
    EXPECTED_RUNTIME_FILES,
    ios_version,
    expected_shader_chain,
    seed_shader_keys,
    shader_keys_from_map,
    require_guest_sections,
    require_runtime_resources,
    validate_real_game_bundle,
)

MACHO_GUEST_SECTIONS = """
Load command 0
  cmd LC_SEGMENT_64
   segname __TEXT
Section
   sectname __dmmainx0
   segname __TEXT
      addr 0x0000000000400000
      size 0x0000000000010000
Section
   sectname __dmmainx1
   segname __TEXT
      addr 0x0000000000410000
      size 0x0000000000004000
Section
   sectname __dmsdkx0
   segname __TEXT
      addr 0x0000000000500000
      size 0x0000000000014000
Section
   sectname __dmsdkx1
   segname __TEXT
      addr 0x0000000000514000
      size 0x0000000000004000
Load command 7
    cmd LC_SEGMENT_64
   segname __DMmainW
Section
   sectname __img
   segname __DMmainW
      addr 0x0000000000600000
      size 0x0000000000010000
Load command 8
    cmd LC_SEGMENT_64
   segname __DMsdkW
Section
   sectname __img
   segname __DMsdkW
      addr 0x0000000000700000
      size 0x0000000000014000
"""
SHADER_KEYS = ("a" * 16, "b" * 16)



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

    # Synthetic shader map uses the SAME column/keys read by dmsh_build.py.
    # These files test acceptance logic only and are not game-derived assets.
    (app / "dm/shader_map.tsv").write_text(
        "sample.bin\t0\tvs\t" + SHADER_KEYS[0] + "\tpc-pair\n"
        "main.rodata@0x100\t0\t顶点\t" + SHADER_KEYS[1] + "\tpc-pair\n",
        encoding="utf-8",
    )
    (app / "dm/pso_manifest.tsv").write_text(
        "S\t" + SHADER_KEYS[0] + "_b\t5\n"
        "C\t" + SHADER_KEYS[1] + "_b\n",
        encoding="utf-8",
    )
    chain = expected_shader_chain()
    shaders = app / "msl" / ("b-" + chain)
    shaders.mkdir(parents=True)
    for key in SHADER_KEYS:
        (shaders / (key + "_b.metallib")).write_bytes(
            b"fake-apple-metallib-test-fixture"
        )
        (shaders / (key + "_b.json")).write_text(
            json.dumps({
                "chain": chain, "key": key + "_b",
                "dm_ctl": key, "route": "B", "stage": 5,
            }),
            encoding="utf-8",
        )
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
        self.assertIn("__DMsdkW/__img", found["sdk"])

    def test_wrong_guest_segment_pairing_fails(self):
        with self.assertRaisesRegex(BundleValidationError, "main missing"):
            require_guest_sections(
                MACHO_GUEST_SECTIONS.replace(
                    "sectname __dmmainx0\n   segname __TEXT",
                    "sectname __dmmainx0\n   segname __DATA",
                )
            )

    def test_guest_writable_image_required_per_module(self):
        with self.assertRaisesRegex(BundleValidationError, "sdk missing"):
            require_guest_sections(
                MACHO_GUEST_SECTIONS.replace(
                    "sectname __img\n   segname __DMsdkW",
                    "sectname __img\n   segname __DMmainW2",
                )
            )

    def test_zero_size_guest_section_is_rejected(self):
        with self.assertRaisesRegex(BundleValidationError, "Empty game"):
            require_guest_sections(
                MACHO_GUEST_SECTIONS.replace(
                    "size 0x0000000000010000",
                    "size 0x0000000000000000",
                    1,
                )
            )

    def test_unsigned_shell_cannot_pass_guest_sections(self):
        with self.assertRaisesRegex(BundleValidationError, "main missing"):
            require_guest_sections("""
            Load command 0
                segname __TEXT
            Section
                sectname __text
                segname __TEXT
                   size 0x0000000000004000
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
            self.assertTrue(outcome["shader_map_coverage_verified"])
            self.assertTrue(outcome["shader_reflection_coverage_verified"])
            self.assertEqual(outcome["transformed_shader_library_count"], 2)
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

    def test_symlinked_resources_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            app = make_mock_game_app(base)
            original = app / "dm/main.fixups.tsv"
            backup = base / "not-a-bundled-file.tsv"
            original.rename(backup)
            original.symlink_to(backup)
            with self.assertRaisesRegex(BundleValidationError, "main.fixups.tsv"):
                require_runtime_resources(app)

    def test_symlinked_executable_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            app = make_mock_game_app(base)
            executable = app / "DmIOS"
            moved = base / "unbundled-game"
            executable.rename(moved)
            executable.symlink_to(moved)
            with self.assertRaisesRegex(BundleValidationError, "local executable"):
                validate_real_game_bundle(app, "metal4")

    def test_missing_translated_shaders_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            chain = expected_shader_chain()
            (app / "msl" / ("b-" + chain) / (SHADER_KEYS[0] + "_b.metallib")).unlink()
            with self.assertRaisesRegex(BundleValidationError, "missing Metal libraries"):
                require_runtime_resources(app)

    def test_shader_map_parser_and_seed_parser(self):
        mapping = (
            "example.bin\t1\t5\t" + SHADER_KEYS[0] + "\tpaired\n"
            "main.rodata@0x10\t0\t顶点\t" + SHADER_KEYS[1] + "\tpaired\n"
            "# Ignored comment\n"
        )
        self.assertEqual(shader_keys_from_map(mapping), set(SHADER_KEYS))
        self.assertEqual(
            seed_shader_keys("S\t" + SHADER_KEYS[0] + "_b\t5\nC\t" + SHADER_KEYS[1] + "_b\n"),
            set(SHADER_KEYS)
        )

    def test_empty_mapping_rejected_even_if_shader_file_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            (app / "dm/shader_map.tsv").write_text("# no map\n")
            with self.assertRaisesRegex(BundleValidationError, "no real shader keys"):
                require_runtime_resources(app)

    def test_unmapped_pso_seed_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            (app / "dm/pso_manifest.tsv").write_text("S\t" + "c" * 16 + "_b\t5\n")
            with self.assertRaisesRegex(BundleValidationError, "absent from"):
                require_runtime_resources(app)

    def test_malformed_mapping_key_rejected(self):
        with self.assertRaisesRegex(BundleValidationError, "Malformed game shader"):
            shader_keys_from_map("demo.bin\t0\tvs\tNOT-16-HEX\tpc\n")

    def test_missing_companion_reflection_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            chain = expected_shader_chain()
            (app / "msl" / ("b-" + chain) / (SHADER_KEYS[0] + "_b.json")).unlink()
            with self.assertRaisesRegex(BundleValidationError, "missing reflections"):
                require_runtime_resources(app)

    def test_stale_reflection_chain_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            chain = expected_shader_chain()
            path = app / "msl" / ("b-" + chain) / (SHADER_KEYS[0] + "_b.json")
            value = json.loads(path.read_text(encoding="utf-8"))
            value["chain"] = "obsolete-chain"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(BundleValidationError, "inconsistent reflections"):
                require_runtime_resources(app)

    def test_wrong_shader_version_directory_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = make_mock_game_app(Path(temporary))
            correct = app / "msl" / ("b-" + expected_shader_chain())
            correct.rename(app / "msl/b-obsolete")
            with self.assertRaisesRegex(BundleValidationError, "translation-chain directory"):
                require_runtime_resources(app)

    def test_shader_directory_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            app = make_mock_game_app(base)
            correct = app / "msl" / ("b-" + expected_shader_chain())
            external = base / "owner-private-shader-cache"
            correct.rename(external)
            correct.symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(BundleValidationError, "translation-chain directory"):
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
