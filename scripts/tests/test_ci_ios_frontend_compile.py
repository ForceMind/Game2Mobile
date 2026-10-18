"""Safety and inventory tests for the real iOS frontend source compile sweep."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from scripts.ci_ios_frontend_compile import (
    EXPECTED_CORE, PROFILES, command_for_source, redact, tracked_sources,
)


class FrontendCompilerTests(unittest.TestCase):
    def test_actual_tracked_frontend_inventory(self):
        sources = tracked_sources()
        self.assertEqual(len(sources), 17)
        self.assertTrue(EXPECTED_CORE.issubset({s.name for s in sources}))
        self.assertFalse(any("native_art.c" in s.name for s in sources))
        self.assertEqual(
            len([s for s in sources if s.suffix == ".m"]), 12
        )
        self.assertEqual(
            len([s for s in sources if s.suffix == ".c"]), 5
        )

    def test_metal4_and_legacy_use_device_targets(self):
        for profile, (target, cpu, flags) in PROFILES.items():
            with self.subTest(profile=profile):
                path = Path("/safe/Sources/dm_shader_prep.m")
                cmd = command_for_source(
                    path, Path("/tmp/test.o"),
                    target=target, cpu=cpu, flags=flags,
                    sdk="/safe/iPhoneOS.sdk",
                )
                self.assertIn("-target", cmd)
                self.assertEqual(cmd[cmd.index("-target") + 1], target)
                self.assertIn("-mcpu=" + cpu, cmd)
                self.assertIn("-fobjc-arc", cmd)
                self.assertIn("-fmodules", cmd)
                self.assertEqual("-DDM_NVN_M3=1" in cmd, profile == "m3")
                self.assertIn(str(path), cmd)

    def test_c_uses_c11_without_objc_arc(self):
        cmd = command_for_source(
            Path("/safe/Sources/dm_touch_controls.c"),
            Path("/tmp/c.o"),
            target="arm64-apple-ios26.0", cpu="apple-a18",
            flags=(), sdk="/safe/iPhoneOS.sdk",
        )
        self.assertIn("-std=gnu11", cmd)
        self.assertNotIn("-fobjc-arc", cmd)

    def test_ios18_excludes_unavailable_managed_asset_apis(self):
        """Old-device SDK lacks BAAssetPackManager and its 26.x delegate."""
        from scripts.ci_ios_frontend_compile import ROOT
        source = (ROOT / "dm/ios/Sources/main.m").read_text(encoding="utf-8")
        excluded = []
        names = re.compile(
            r"\b(?:BAAssetPackManager|BAAssetPackStatus|BAAssetPack|"
            r"BAManagedAssetPackDownloadDelegate)\b"
        )
        found = 0
        for number, raw in enumerate(source.splitlines(), start=1):
            line = raw.strip()
            if line.startswith(("#if ", "#ifdef ", "#ifndef ")):
                excluded.append(line == "#if !defined(DM_NVN_M3)")
                continue
            if line.startswith(("#else", "#elif ")):
                if excluded:
                    excluded[-1] = False
                continue
            if line.startswith("#endif"):
                if excluded:
                    excluded.pop()
                continue
            if line.startswith("//") or not names.search(line):
                continue
            found += 1
            self.assertTrue(
                any(excluded),
                f"iOS18-incompatible BackgroundAssets type exposed at line {number}",
            )
        self.assertGreaterEqual(found, 10)
        self.assertEqual(excluded, [])

    def test_diagnostic_redaction(self):
        from scripts.ci_ios_frontend_compile import ROOT
        diagnostic = f"{ROOT}/dm/ios/Sources/front_ios.m:99:5: error: code mismatch"
        self.assertIn("<source>/dm/ios/", redact(diagnostic))
        self.assertNotIn(str(ROOT), redact(diagnostic))


if __name__ == "__main__":
    unittest.main()
