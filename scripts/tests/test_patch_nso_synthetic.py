"""Asset-free ARM64 encoder and safety checks for the D2R NSO rewriter.

The production script loads proprietary modules and Capstone at import time.
Test the *real* encoder AST without executing the module or reading game files.
"""
from __future__ import annotations

import ast
from pathlib import Path
import os
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
REWRITER = ROOT / "dm/tools/patch_nso.py"


def source_ast():
    return ast.parse(REWRITER.read_text(encoding="utf-8"), filename=str(REWRITER))


def isolated_encoders():
    definitions = {node.name: node for node in source_ast().body
                   if isinstance(node, ast.FunctionDef)}
    names = ("B", "ADRP")
    if not all(name in definitions for name in names):
        raise AssertionError("Production encoder missing")
    module = ast.Module(body=[definitions[name] for name in names], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(REWRITER), "exec"), namespace)
    return namespace


def signed(value: int, width: int) -> int:
    return value - (1 << width) if value & (1 << (width - 1)) else value


class PatchNsoSynthetic(unittest.TestCase):
    def test_branch_relative_immediate_round_trip(self):
        b = isolated_encoders()["B"]
        for delta in (-(1 << 27), -4, 0, 4, (1 << 27) - 4):
            with self.subTest(delta=delta):
                word = b(0x30000000, 0x30000000 + delta)
                self.assertEqual(word >> 26, 0b000101)
                self.assertEqual(signed(word & ((1 << 26) - 1), 26) * 4, delta)

    def test_branch_refuses_out_of_range_or_unaligned(self):
        b = isolated_encoders()["B"]
        for delta in (1 << 27, -(1 << 27) - 4, 1, -3, 7):
            with self.subTest(delta=delta), self.assertRaises(AssertionError):
                b(0x30000000, 0x30000000 + delta)

    def test_adrp_relative_pages_round_trip(self):
        adrp = isolated_encoders()["ADRP"]
        pc = 0x102345
        for pages in (-(1 << 20), -1, 0, 1, (1 << 20) - 1):
            with self.subTest(pages=pages):
                target = (pc & ~0xFFF) + (pages << 12)
                word = adrp(21, pc, target)
                self.assertEqual(word & 31, 21)
                imm = ((word >> 29) & 3) | (((word >> 5) & 0x7FFFF) << 2)
                self.assertEqual(signed(imm, 21), pages)

    def test_adrp_refuses_invalid_page_reach(self):
        adrp = isolated_encoders()["ADRP"]
        for pages in (1 << 20, -(1 << 20) - 1):
            with self.subTest(pages=pages), self.assertRaises(AssertionError):
                adrp(21, 0x10000000, 0x10000000 + (pages << 12))

    def test_optimized_python_refused_before_import_or_asset_load(self):
        nodes = source_ast().body
        guards = [node for node in nodes if isinstance(node, ast.If) and
                  isinstance(node.test, ast.UnaryOp) and
                  isinstance(node.test.op, ast.Not) and
                  isinstance(node.test.operand, ast.Name) and
                  node.test.operand.id == "__debug__"]
        self.assertEqual(len(guards), 1, "No guard against -O / -OO")
        self.assertLess(nodes.index(guards[0]), 5, "Guard must run before imports and I/O")
        for flag in ("-O", "-OO"):
            with self.subTest(flag=flag):
                result = subprocess.run([sys.executable, flag, str(REWRITER)],
                                        capture_output=True, text=True, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("NSO rewriter refuses optimized Python", result.stderr)
                self.assertNotIn("No module named", result.stderr)

    def test_pythonoptimize_environment_cannot_bypass_guards(self):
        env = os.environ.copy()
        env["PYTHONOPTIMIZE"] = "1"
        result = subprocess.run([sys.executable, str(REWRITER)], env=env,
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("safety assertions must remain enabled", result.stderr)


if __name__ == "__main__":
    unittest.main()
