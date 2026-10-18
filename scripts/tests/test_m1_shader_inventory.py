"""Asset-free shader-cache preflight tests; fake libraries are NOT game assets."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.m1_shader_inventory import (
    ShaderInventoryError, inspect_cache, inspect_source,
)

KEYS = ("a" * 16, "b" * 16)
CHAIN = "15cf7ca29eaf"


def fake_inputs(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    """Synthesize a tiny shader map with receipt and fake paired output files."""
    source = root / "shader_map.tsv"
    source.write_text(
        "shader_one.bin\t0\tvs\t" + KEYS[0] + "\tpc-a\n"
        "shader_two.bin\t1\tps\t" + KEYS[1] + "\tpc-b\n",
        encoding="utf-8",
    )
    pso = root / "pso_manifest.tsv"
    pso.write_text("S\t" + KEYS[0] + "_b\t5\n", encoding="utf-8")
    header = root / "dmsh_chain.h"
    header.write_text('#define DMSH_CHAIN "' + CHAIN + '"\n', encoding="utf-8")
    ios = root / "ios"
    libraries = ios / ("b-" + CHAIN)
    libraries.mkdir(parents=True)
    for key in KEYS:
        (libraries / (key + "_b.metallib")).write_bytes(
            b"fake-asset-free-test-library"
        )
        (libraries / (key + "_b.json")).write_text(
            json.dumps({"key": key + "_b", "chain": CHAIN, "route": "B"}),
            encoding="utf-8",
        )
    marker = root / "receipt.json"
    marker.write_text(
        json.dumps([{"key": key, "st": "ok"} for key in KEYS]),
        encoding="utf-8",
    )
    return source, pso, header, ios, marker


class SourceInventoryTests(unittest.TestCase):
    def test_actual_repository_shader_map_and_warmup_seeds(self):
        """This is the real tracked 3.3.94012 map, NOT an empty placeholder."""
        mapped, seeds, chain = inspect_source()
        self.assertEqual(len(mapped), 6927)
        self.assertEqual(len(seeds), 181)
        self.assertTrue(seeds.issubset(mapped))
        self.assertRegex(chain, r"^[0-9a-f]{12}$")

    def test_mismatched_pso_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = fake_inputs(Path(temp))
            paths[1].write_text("S\t" + "c" * 16 + "_b\t5\n")
            with self.assertRaisesRegex(ShaderInventoryError, "absent"):
                inspect_source(*paths[:3])


class CacheInventoryTests(unittest.TestCase):
    def validate(self, paths):
        return inspect_cache(*paths)

    def test_complete_local_receipt_and_paired_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory = self.validate(fake_inputs(Path(temp)))
            self.assertEqual(inventory["mapped_shader_keys"], 2)
            self.assertEqual(inventory["ios_paired_shader_libraries"], 2)
            self.assertEqual(inventory["pso_warmup_shader_keys"], 1)
            self.assertFalse(inventory["real_game_app_linked"])

    def test_empty_marker_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = fake_inputs(Path(temp))
            paths[-1].write_text("[]")
            with self.assertRaisesRegex(ShaderInventoryError, "no entries"):
                self.validate(paths)

    def test_partial_marker_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = fake_inputs(Path(temp))
            paths[-1].write_text(json.dumps([{"key": KEYS[0], "st": "ok"}]))
            with self.assertRaisesRegex(ShaderInventoryError, "1 missing mapped"):
                self.validate(paths)

    def test_failed_translation_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = fake_inputs(Path(temp))
            paths[-1].write_text(
                json.dumps([{"key": key, "st": "fail" if key == KEYS[0] else "ok"}
                            for key in KEYS])
            )
            with self.assertRaisesRegex(ShaderInventoryError, "1 unfinished"):
                self.validate(paths)

    def test_duplicate_marker_entries_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = fake_inputs(Path(temp))
            paths[-1].write_text(
                json.dumps([{"key": KEYS[0], "st": "ok"},
                            {"key": KEYS[0], "st": "ok"},
                            {"key": KEYS[1], "st": "ok"}])
            )
            with self.assertRaisesRegex(ShaderInventoryError, "1 duplicates"):
                self.validate(paths)

    def test_unmapped_success_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = fake_inputs(Path(temp))
            paths[-1].write_text(
                json.dumps([{"key": key, "st": "ok"} for key in KEYS + ("c" * 16,)])
            )
            with self.assertRaisesRegex(ShaderInventoryError, "1 unexpected"):
                self.validate(paths)

    def test_missing_iPhoneOS_metallib_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = fake_inputs(Path(temp))
            (paths[-2] / ("b-" + CHAIN) / (KEYS[1] + "_b.metallib")).unlink()
            with self.assertRaisesRegex(ShaderInventoryError, "1 missing Metal libraries"):
                self.validate(paths)

    def test_missing_reflection_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = fake_inputs(Path(temp))
            (paths[-2] / ("b-" + CHAIN) / (KEYS[1] + "_b.json")).unlink()
            with self.assertRaisesRegex(ShaderInventoryError, "1 missing reflection"):
                self.validate(paths)

    def test_stale_shader_chain_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = fake_inputs(Path(temp))
            reflection = paths[-2] / ("b-" + CHAIN) / (KEYS[1] + "_b.json")
            data = json.loads(reflection.read_text())
            data["chain"] = "old-translation"
            reflection.write_text(json.dumps(data))
            with self.assertRaisesRegex(ShaderInventoryError, "1 inconsistent"):
                self.validate(paths)

    def test_symlinked_shaders_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = fake_inputs(root)
            original = paths[-2] / ("b-" + CHAIN) / (KEYS[0] + "_b.metallib")
            private = root / "private-test-only"
            original.rename(private)
            original.symlink_to(private)
            with self.assertRaisesRegex(ShaderInventoryError, "missing Metal libraries"):
                self.validate(paths)


if __name__ == "__main__":
    unittest.main()
