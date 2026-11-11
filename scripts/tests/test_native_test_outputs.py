"""Native test output must not make a clean M1 source checkout appear dirty."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NativeTestOutputIgnoreTests(unittest.TestCase):
    def ignored(self, relative: str) -> bool:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", relative], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        )
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.returncode == 0

    def test_new_executables_and_debug_symbols_are_ignored(self):
        for binary in ("t_dirty_init", "t_dirty_failures"):
            with self.subTest(binary=binary):
                self.assertTrue(self.ignored("dm/gfx/tests/" + binary))
                self.assertTrue(self.ignored(
                    "dm/gfx/tests/" + binary + ".dSYM/Contents/Resources/DWARF/" + binary))

    def test_corresponding_test_sources_remain_trackable(self):
        for binary in ("t_dirty_init", "t_dirty_failures"):
            with self.subTest(binary=binary):
                self.assertFalse(self.ignored("dm/gfx/tests/" + binary + ".c"))


if __name__ == "__main__":
    unittest.main()
