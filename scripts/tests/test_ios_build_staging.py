"""Execute real run.sh orchestration with inert files and mocked external tools.

No game headers, game images, shaders, App compilation or signing occur here.
These tests prove shell argument/copy/error handling only. They also run on
Apple CI to exercise its native Bash and filesystem commands.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
# A single executable records invocations and delegates ordinary file copying
# to the actual platform cp. All compiler/generator/signing calls are mocks.
DRIVER = r'''
import json, os, pathlib, shutil, subprocess, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['TEST_TRACE'], 'a') as output:
    output.write(json.dumps([name, *args]) + '\n')
if name == 'python3':
    script = pathlib.Path(args[0]).name
    if script == 'gen_embed.py':
        if args[1:] != [os.environ['TEST_MODULES'], 'Gen/embed.S', 'main', 'sdk']:
            sys.exit(9)
        pathlib.Path(args[2]).write_text('// INERT orchestration fixture; no guest bytes\n')
    elif script == 'gen_romfs_overlay.py':
        dest = pathlib.Path(args[2]) / 'data'
        dest.mkdir(parents=True)
        (dest / '.build.config').write_text('vfs-root = INERT_TEST_ONLY\n')
elif name == 'cp':
    failure = os.environ.get('TEST_FAIL_COPY')
    if failure and any(failure in arg for arg in args):
        sys.exit(7)
    if args[0] == '-cR':
        # Simulate an unsupported/cross-volume clone with partial output.
        partial = pathlib.Path(args[-1]) / pathlib.Path(args[-2]).name
        partial.mkdir(parents=True)
        (partial / 'partial-copy').write_text('INERT partial copy')
        sys.exit(1)
    sys.exit(subprocess.call([shutil.which('cp', path=os.defpath), *args]))
elif name == 'codesign':
    if '--verify' in args and os.environ.get('TEST_FAIL_SIGNATURE') == '1':
        sys.exit(8)
'''


class IOSBuildStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ios = self.root / 'checkout/dm/ios'
        self.ios.mkdir(parents=True)
        shutil.copy2(ROOT / 'dm/ios/run.sh', self.ios / 'run.sh')
        (self.ios / 'tools').mkdir()
        for name in ('devlock.sh', 'asc_env.sh', 'local_env.sh'):
            (self.ios / 'tools' / name).write_text('asc_auth() { :; }\n')
        (self.ios / 'Sources').mkdir()
        (self.ios.parent / 'host').mkdir()
        (self.ios / 'Sources/main.m').write_text(
            'listen(0);\nif (log_port && !pthread_create(&lp, NULL, log_port_main\n'
        )
        gfx = self.ios.parent / 'gfx/nvn'
        gfx.mkdir(parents=True)
        (gfx / 'dmsh_chain.h').write_text('#define DMSH_CHAIN "inert"\n')
        for name in ('shader_map.tsv', 'pso_manifest.tsv', 'c1_full.tsv'):
            (gfx / name).write_text('INERT copy fixture, not shader metadata\n')
        (self.ios / 'asset_pointers.txt').write_text('INERT test fixture\n')
        # Ordinary paths isolate copy failures; the success case also tests spaces.
        self.workspace = self.root / 'owner-workspace'
        self.modules = self.workspace / 'module-outputs'
        self.modules.mkdir(parents=True)
        for module in ('main', 'sdk'):
            for suffix in ('fixups.tsv', 'gates.tsv'):
                (self.modules / f'{module}.{suffix}').write_text('INERT copy fixture\n')
        (self.modules / 'bootlist.tsv').write_text('INERT optional fixture\n')
        cache = self.workspace / 'build/ios/dmsh_b/b-inert'
        cache.mkdir(parents=True)
        (cache / 'cache-copy.txt').write_text('INERT ordinary file, not a Metal library\n')
        tools = self.root / 'mock-tools'
        tools.mkdir()
        for name in ('python3', 'make', 'cp', 'xcodegen', 'xcodebuild', 'codesign', 'plutil'):
            path = tools / name
            path.write_text(f'#!{sys.executable}\n' + DRIVER)
            path.chmod(0o755)
        self.trace = self.root / 'trace.jsonl'
        self.env = {
            'HOME': str(self.root), 'PATH': str(tools) + os.pathsep + os.defpath,
            'DM_ROOT': str(self.workspace), 'DM_OUT': str(self.modules),
            'DM_BUNDLE_ID': 'invalid.orchestration.fixture', 'DM_GEN_ONLY': '1',
            'TEST_TRACE': str(self.trace), 'TEST_MODULES': str(self.modules),
        }

    def run_build(self, **extra):
        return subprocess.run(['bash', str(self.ios / 'run.sh'), 'build'],
                              env=self.env | extra, text=True, capture_output=True,
                              timeout=30)

    def calls(self, name):
        return [row for line in self.trace.read_text().splitlines()
                if (row := json.loads(line))[0] == name]

    def use_space_paths(self):
        moved = self.root / 'owner workspace'
        self.workspace.rename(moved)
        self.workspace = moved
        self.modules = moved / 'module-outputs'
        self.env.update(DM_ROOT=str(moved), DM_OUT=str(self.modules),
                        TEST_MODULES=str(self.modules))

    def test_space_paths_clone_fallback_and_fresh_headers(self):
        self.use_space_paths()
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.ios / 'Gen/dm/sdk.gates.tsv').read_text(),
                         'INERT copy fixture\n')
        staged = self.ios / 'Gen/msl/b-inert'
        self.assertTrue((staged / 'cache-copy.txt').is_file())
        self.assertFalse((staged / 'partial-copy').exists())
        self.assertIn('-B', self.calls('make')[0])
        self.assertEqual(len(self.calls('xcodegen')), 1)
        self.assertEqual(self.calls('xcodebuild'), [])

    def test_build_arguments_keep_space_paths_and_verify_signature(self):
        self.use_space_paths()
        result = self.run_build(DM_GEN_ONLY='0')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        xcode = self.calls('xcodebuild')[0]
        expected_dd = str(self.workspace / 'run/ios/dd')
        self.assertEqual(xcode[xcode.index('-derivedDataPath') + 1], expected_dd)
        signature = self.calls('codesign')[0]
        self.assertEqual(signature[1:4], ['--verify', '--deep', '--strict'])
        self.assertEqual(signature[-1],
                         expected_dd + '/Build/Products/Release-iphoneos/DmIOS.app')

    def test_required_copy_failure_never_reaches_xcode(self):
        for failure in ('sdk.gates.tsv', 'shader_map.tsv', 'asset_pointers.txt'):
            with self.subTest(failure=failure):
                self.trace.write_text('')
                result = self.run_build(TEST_FAIL_COPY=failure)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.calls('xcodegen'), [])
                self.assertEqual(self.calls('xcodebuild'), [])

    def test_fallback_copy_failure_never_reaches_xcode(self):
        result = self.run_build(TEST_FAIL_COPY='b-inert')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls('xcodegen'), [])

    def test_existing_optional_file_copy_failure_is_fatal(self):
        result = self.run_build(TEST_FAIL_COPY='bootlist.tsv')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls('xcodegen'), [])

    def test_present_reference_save_copy_failure_is_fatal(self):
        save = self.workspace / 'data/switch/save_ref/0000000000000001/0'
        save.mkdir(parents=True)
        (save / 'inert-copy.txt').write_text('NOT A GAME SAVE\n')
        result = self.run_build(TEST_FAIL_COPY='save_ref/')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls('xcodegen'), [])

    def test_signature_failure_is_not_reported_as_build_success(self):
        result = self.run_build(DM_GEN_ONLY='0', TEST_FAIL_SIGNATURE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls('xcodebuild')), 1)
        self.assertIn('--verify', self.calls('codesign')[0])


if __name__ == '__main__':
    unittest.main()
