"""Product cache control-flow tests: inert files, no NSO/game processing."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ProductCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.tools = root / 'checkout/dm/tools'
        self.tools.mkdir(parents=True)
        shutil.copy2(ROOT / 'dm/tools/product.sh', self.tools / 'product.sh')
        self.patch = self.tools / 'patch_nso.py'
        self.patch.write_text('INERT source-fingerprint fixture; never executed\n')
        (self.tools.parent / 'PRODUCT').write_text('inert-r0\n')
        self.workspace = root / 'private workspace'
        self.out = self.workspace / 'build/cache/dm/out'
        self.env = {'HOME': str(root), 'PATH': os.defpath,
                    'DM_ROOT': str(self.workspace)}
        wrapper = root / 'mock-rewriter'
        wrapper.write_text(f'#!{sys.executable}\n' + '''
import hashlib, os, pathlib, sys
script, nso, out, module = sys.argv[1:]
out = pathlib.Path(out)
for suffix in ('patched.bin', 'fixups.tsv', 'gates.tsv'):
    (out / (module + '.' + suffix)).write_text('INERT text fixture, no game bytes\\n')
(out / 'build_src.sha256').write_text(hashlib.sha256(pathlib.Path(script).read_bytes()).hexdigest() + '  patch_nso.py\\n')
if module == os.environ.get('TEST_FAIL_MODULE'):
    sys.exit(9)
''')
        wrapper.chmod(0o755)
        self.env['DM_PY'] = str(wrapper)

    def run_product(self, action, **extra):
        return subprocess.run(['bash', str(self.tools / 'product.sh'), action],
                              env=self.env | extra, text=True, capture_output=True,
                              timeout=30)

    def variant(self, name):
        return self.out / ('inert-r0-' + name)

    def run_setup_product_stage(self, **extra):
        source = (ROOT / 'setup.sh').read_text()
        start = source.index('# A main image alone')
        end = source.index('\npacks()', start)
        step = next(line for line in source.splitlines() if line.startswith('step()'))
        script = 'say() { :; }; die() { exit 1; };\n' + step + '\n' + source[start:end]
        return subprocess.run(['bash', '-c', script],
                              env=self.env | {'HERE': str(self.tools.parent.parent),
                                              'PY': self.env['DM_PY']} | extra,
                              text=True, capture_output=True, timeout=30)

    def test_setup_rebuilds_legacy_partial_cache_then_reuses_complete_cache(self):
        out = self.variant('touch')
        out.mkdir(parents=True)
        (out / 'main.patched.bin').write_text('INERT old file\n')
        result = self.run_setup_product_stage()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.run_product('check').returncode, 0)
        # If setup tried rebuilding a valid cache this mock would fail.
        self.assertEqual(self.run_setup_product_stage(TEST_FAIL_MODULE='main').returncode, 0)

    def test_setup_does_not_continue_after_failed_module_generation(self):
        self.assertNotEqual(self.run_setup_product_stage(TEST_FAIL_MODULE='sdk').returncode, 0)
        self.assertNotEqual(self.run_product('check').returncode, 0)

    def test_single_old_main_file_is_not_a_valid_cache(self):
        out = self.variant('touch')
        out.mkdir(parents=True)
        (out / 'main.patched.bin').write_text('INERT old file\n')
        self.assertNotEqual(self.run_product('check').returncode, 0)

    def test_successful_mock_control_flow_has_complete_cache(self):
        result = self.run_product('build')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.run_product('check').returncode, 0)
        self.assertEqual(list(self.out.glob('*/.product-building')), [])
        # Empty gate lists can be valid for a module; existence is sufficient.
        (self.variant('touch') / 'sdk.gates.tsv').write_text('')
        self.assertEqual(self.run_product('check').returncode, 0)

    def test_legacy_receipt_without_final_completion_is_rebuilt(self):
        self.assertEqual(self.run_product('build').returncode, 0)
        (self.variant('touch') / 'product.complete.sha256').unlink()
        self.assertNotEqual(self.run_product('check').returncode, 0)

    def test_source_change_and_each_incomplete_artifact_are_rejected(self):
        self.assertEqual(self.run_product('build').returncode, 0)
        original = self.patch.read_text()
        self.patch.write_text(original + 'changed\n')
        self.assertNotEqual(self.run_product('check').returncode, 0)
        self.patch.write_text(original)
        for kind in ('keypage', 'rules', 'touch'):
            for suffix in ('patched.bin', 'fixups.tsv', 'gates.tsv'):
                path = self.variant(kind) / ('sdk.' + suffix)
                contents = path.read_bytes()
                path.unlink()
                with self.subTest(kind=kind, suffix=suffix):
                    self.assertNotEqual(self.run_product('check').returncode, 0)
                path.write_bytes(contents)
        self.assertEqual(self.run_product('check').returncode, 0)

    def test_failed_rewrite_cannot_be_accepted_even_with_matching_receipt(self):
        self.assertEqual(self.run_product('build').returncode, 0)
        result = self.run_product('build', TEST_FAIL_MODULE='sdk')
        self.assertNotEqual(result.returncode, 0)
        out = self.variant('keypage')
        self.assertTrue((out / '.product-building').exists())
        self.assertEqual((out / 'build_src.sha256').read_text().split()[0],
                         hashlib.sha256(self.patch.read_bytes()).hexdigest())
        self.assertNotEqual(self.run_product('check').returncode, 0)
        self.assertEqual(self.run_product('build').returncode, 0)
        self.assertEqual(self.run_product('check').returncode, 0)


if __name__ == '__main__':
    unittest.main()
