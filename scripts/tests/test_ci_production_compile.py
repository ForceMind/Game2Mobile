"""Offline checks for classification and source provenance of compiler sweeps."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci_production_compile import (
    compile_status, origin_for, parse_header_paths, summarize_diagnostic
)


class CompilerInventoryTests(unittest.TestCase):
    def test_success(self):
        self.assertEqual(compile_status(0, ""), "compiled")

    def test_missing_generated_game_table(self):
        for include in ("dm_vault_tab.h", "dm_hud_exp.h",
                        "dm_bright_levels.inc", "dm_touch_native_art.c"):
            with self.subTest(include=include):
                log = f"test.c:2:10: fatal error: '{include}' file not found"
                self.assertEqual(compile_status(1, log), "blocked_generated_asset")

    def test_unrelated_missing_header_is_real_error(self):
        self.assertEqual(
            compile_status(1, "foo.c:9:10: fatal error: 'not_there.h' file not found"),
            "compile_error",
        )

    def test_warning_not_false_asset_block(self):
        self.assertEqual(
            compile_status(1, "warning: use dm_vault_tab.h somewhere"),
            "compile_error",
        )

    def test_header_paths(self):
        text = (
            'HEADER_SEARCH_PATHS = $(inherited) "/a b" "/tmp/gfx" "/tmp/gfx"\n'
            'OTHER_CFLAGS = $(inherited) -DFLAG\n'
        )
        self.assertEqual(parse_header_paths(text), ["/a b", "/tmp/gfx"])

    def test_provenance_accepts_internal_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            dm = Path(d) / "dm"
            (dm / "host").mkdir(parents=True)
            real = dm / "host/loader.c"
            real.write_text("int f(void){return 1;}\n")
            link = dm / "loader-link.c"
            link.symlink_to(real)
            self.assertEqual(origin_for(link, dm), "host/loader.c")

    def test_provenance_rejects_escape(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dm = root / "dm"
            dm.mkdir()
            outside = root / "secret.data"
            outside.write_text("test")
            link = dm / "leak.c"
            link.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "escapes"):
                origin_for(link, dm)

    def test_diagnostics_redact_staging(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = summarize_diagnostic(
                f"{root}/dm/host/a.c:10:2: error: invalid token",
                root, root
            )
            self.assertIn("<isolated>", result)
            self.assertNotIn(d, result)


if __name__ == "__main__":
    unittest.main()
