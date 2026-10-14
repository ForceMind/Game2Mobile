"""Lock down every supported iOS XcodeGen configuration without private game files."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
IOS = ROOT / "dm/ios"
SPEC = IOS / "project.yml"
FREE = IOS / "tools/project_free.py"
M3 = IOS / "tools/project_m3.py"


class ProjectVariantsTest(unittest.TestCase):
    def variant(self, free: bool, old_api: bool) -> str:
        with tempfile.TemporaryDirectory(prefix="game2mobile-xcodegen-") as d:
            parent = Path(d)
            source = SPEC
            if free:
                target = parent / "free.yml"
                subprocess.run([sys.executable, str(FREE), str(source), str(target)], check=True, capture_output=True, text=True)
                source = target
            if old_api:
                target = parent / "m3.yml"
                args = [sys.executable, str(M3), str(source), str(target)]
                if free:
                    args.append("free")
                subprocess.run(args, check=True, capture_output=True, text=True)
                source = target
            return source.read_text(encoding="utf-8")

    def test_all_four_build_profiles(self) -> None:
        for free in (False, True):
            for old_api in (False, True):
                with self.subTest(free=free, old_api=old_api):
                    text = self.variant(free, old_api)
                    target = '    iOS: "18.0"' if old_api else '    iOS: "26.0"'
                    self.assertIn(target, text)
                    other = 'OTHER_CFLAGS: $(inherited) -mcpu=apple-a14 -DDM_NVN_M3=1' if old_api else 'OTHER_CFLAGS: $(inherited) -mcpu=apple-a18'
                    self.assertIn(other, text)
                    self.assertIn('CFBundleDisplayName: Game2Mobile', text)
                    includes_extension = not free and not old_api
                    self.assertEqual('  RomfsDownloader:\n' in text, includes_extension)
                    self.assertEqual('        BAUsesAppleHosting: true' in text, includes_extension)
                    self.assertEqual('      - target: RomfsDownloader' in text, includes_extension)
                    self.assertEqual('      IPHONEOS_DEPLOYMENT_TARGET: "26.0"' in text, includes_extension)
                    self.assertEqual('com.apple.developer.icloud-services' in text, not free)
                    self.assertEqual('com.apple.developer.kernel.extended-virtual-addressing' in text, not free)
                    self.assertIn('  TouchSmokeTests:', text)

    def test_m3_requires_exactly_one_cpu_flag(self) -> None:
        spec = self.variant(False, True)
        self.assertEqual(spec.count('OTHER_CFLAGS: $(inherited) -mcpu=apple-a14 -DDM_NVN_M3=1'), 1)
        self.assertNotIn('OTHER_CFLAGS: $(inherited) -mcpu=apple-a18', spec)


if __name__ == '__main__':
    unittest.main()
