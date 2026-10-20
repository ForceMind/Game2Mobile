"""Run the real device shell with mock CoreDevice, no App or device involved.

These tests exercise status propagation and per-launch receipt matching. They
are not installation, boot, rendering, input, audio or save evidence.
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
DRIVER = r'''
import json, os, pathlib, sys, time
if pathlib.Path(sys.argv[0]).name == 'sleep':
    time.sleep(0.05)
    sys.exit(0)
a = sys.argv[1:]
scenario = os.environ.get('TEST_SCENARIO', 'complete')
statefile = pathlib.Path(os.environ['TEST_STATE'])
state = json.loads(statefile.read_text()) if statefile.exists() else {}
with open(os.environ['TEST_TRACE'], 'a') as f:
    f.write(json.dumps({'args': a, 'receipt': os.environ.get('DEVICECTL_CHILD_DM_RUN_RECEIPT')}) + '\n')
def write_json(value):
    if '--json-output' in a:
        p = pathlib.Path(a[a.index('--json-output') + 1])
        p.write_text(value if isinstance(value, str) else json.dumps(value))
if a[:4] == ['devicectl', 'device', 'install', 'app']:
    sys.exit(5 if scenario == 'install_failure' else 0)
if a[:4] == ['devicectl', 'device', 'process', 'launch']:
    state['receipt'] = os.environ.get('DEVICECTL_CHILD_DM_RUN_RECEIPT', 'missing')
    state['copies'] = 0
    statefile.write_text(json.dumps(state))
    print('Launched application')
    write_json('invalid JSON' if scenario == 'bad_launch_json' else
               {'result': {'process': {'processIdentifier': 1234}}})
    sys.exit(6 if scenario == 'launch_failure' else 0)
if a[:4] == ['devicectl', 'device', 'copy', 'from']:
    state['copies'] += 1
    statefile.write_text(json.dumps(state))
    receipt = state.get('receipt', 'missing')
    if scenario == 'stale_done': receipt = 'old-run'
    if scenario == 'launch_log_only' and a[a.index('--source') + 1] == 'Documents/boot.txt': receipt = 'old-run'
    done = scenario in ('complete', 'stale_done', 'launch_failure', 'bad_launch_json', 'failed_copy_with_done', 'launch_log_only')
    if scenario == 'late_complete': done = state['copies'] > 1
    content = 'RUN_RECEIPT ' + receipt + '\n' + ('DONE\n' if done else 'inert running log\n')
    if scenario == 'host_failure': content += 'FAILED dm_main 5\nDONE\n'
    pathlib.Path(a[a.index('--destination') + 1]).write_text(content)
    sys.exit(7 if scenario == 'failed_copy_with_done' else 0)
if a[:4] == ['devicectl', 'device', 'info', 'processes']:
    rows = [{'processIdentifier': 1234, 'executable': '/app/DmIOS.app/DmIOS'}] if scenario == 'running' else []
    if scenario == 'other_pid': rows = [{'processIdentifier': 5678, 'executable': '/app/DmIOS.app/DmIOS'}]
    if scenario == 'query_failure':
        print('CoreDevice query failed', file=sys.stderr)
        sys.exit(8)
    write_json('invalid JSON' if scenario == 'bad_process_json' else {'result': {'runningProcesses': rows}})
    for row in rows: print(row['processIdentifier'], row['executable'])
    sys.exit(0)
sys.exit('Unexpected mock invocation: ' + repr(a))
'''


class DeviceRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ios = self.root / 'checkout/dm/ios'
        (self.ios / 'tools').mkdir(parents=True)
        shutil.copy2(ROOT / 'dm/ios/run.sh', self.ios / 'run.sh')
        shutil.copy2(ROOT / 'dm/ios/tools/local_env.sh', self.ios / 'tools/local_env.sh')
        (self.ios / 'tools/asc_env.sh').write_text('asc_auth() { :; }\n')
        (self.ios / 'tools/devlock.sh').write_text('''
devlock_acquire() { [ "${TEST_LOCK_FAIL:-0}" = 0 ]; }
devlock_release() { echo released >> "$TEST_RELEASE"; }
''')
        (self.ios.parent / 'tools').mkdir()
        (self.ios.parent / 'tools/product.sh').write_text('echo /unused-no-game-modules\n')
        tools = self.root / 'mock-tools'
        tools.mkdir()
        for name in ('xcrun', 'sleep'):
            exe = tools / name
            exe.write_text(f'#!{sys.executable}\n' + DRIVER)
            exe.chmod(0o755)
        self.trace = self.root / 'trace.jsonl'
        self.release = self.root / 'release.txt'
        self.workspace = self.root / 'owner-workspace'
        self.env = {
            'HOME': str(self.root), 'PATH': str(tools) + os.pathsep +
            str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            'DM_ROOT': str(self.workspace), 'DM_BUNDLE_ID': 'invalid.mock.device.run',
            'DM_DEVICE': 'mock-device', 'TEST_TRACE': str(self.trace),
            'TEST_STATE': str(self.root / 'state.json'), 'TEST_RELEASE': str(self.release),
        }

    def run_mode(self, *args, **env):
        return subprocess.run(['bash', str(self.ios / 'run.sh'), *args],
                              env=self.env | env, text=True, capture_output=True,
                              timeout=8)

    def calls(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def test_native_receipt_logger_accepts_only_bounded_hex(self):
        source = (ROOT / 'dm/ios/Sources/main.m').read_text()
        start = source.index('static void log_run_receipt(void)')
        end = source.index('\n}\n', start) + 3
        code = """
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
static char captured[128];
static void plog(const char *fmt, const char *arg) {
    snprintf(captured, sizeof captured, fmt, arg);
}
""" + source[start:end] + r"""
int main(void) {
    unsetenv("DM_RUN_RECEIPT"); log_run_receipt(); assert(!captured[0]);
    const char *bad[] = {"", "abc", "0123456789abcdef0123456789abcdef0",
                        "0123456789ABCDEF0123456789ABCDEF", "0123456789abcdef0123456789abcde\n"};
    for (unsigned i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        setenv("DM_RUN_RECEIPT", bad[i], 1); log_run_receipt(); assert(!captured[0]);
    }
    setenv("DM_RUN_RECEIPT", "0123456789abcdef0123456789abcdef", 1);
    log_run_receipt();
    assert(!strcmp(captured, "RUN_RECEIPT 0123456789abcdef0123456789abcdef"));
    return 0;
}
"""
        cfile = self.root / 'receipt.c'
        binary = self.root / 'receipt-test'
        cfile.write_text(code)
        compiler = shutil.which('cc')
        self.assertIsNotNone(compiler)
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(cfile), '-o', str(binary)], check=True, capture_output=True)
        subprocess.run([str(binary)], check=True, capture_output=True)

    def test_install_space_paths_and_failures(self):
        result = self.run_mode('install', DM_ROOT=str(self.root / 'owner workspace'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        args = self.calls()[0]['args']
        self.assertIn(str(self.root / 'owner workspace/run/ios/dd/Build/Products/Release-iphoneos/DmIOS.app'), args)
        self.assertTrue(self.release.is_file())
        self.assertNotEqual(self.run_mode('install', TEST_SCENARIO='install_failure').returncode, 0)

    def test_lock_failure_never_touches_a_device(self):
        oldlog = self.workspace / 'run/ios/out/boot.txt'
        oldlog.parent.mkdir(parents=True)
        oldlog.write_text('INERT active run log')
        for mode in ('install', 'boot'):
            with self.subTest(mode=mode):
                result = self.run_mode(mode, TEST_LOCK_FAIL='1')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.release.exists())
                self.assertEqual(oldlog.read_text(), "INERT active run log")

    def test_launch_error_cannot_be_overruled_by_launched_text(self):
        result = self.run_mode('boot', TEST_SCENARIO='launch_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls()), 1)
        self.assertTrue(self.release.is_file())

    def test_early_exit_query_failure_and_bad_json_fail_closed(self):
        for scenario in ('early_exit', 'query_failure', 'bad_process_json', 'bad_launch_json', 'other_pid'):
            with self.subTest(scenario=scenario):
                result = self.run_mode('boot', TEST_SCENARIO=scenario)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_old_done_and_failed_copy_are_not_completion(self):
        for scenario in ('stale_done', 'failed_copy_with_done', 'host_failure'):
            with self.subTest(scenario=scenario):
                result = self.run_mode('boot', TEST_SCENARIO=scenario)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_only_current_receipt_completes_and_nonce_changes(self):
        for _ in range(2):
            result = self.run_mode('boot', DM_ROOT=str(self.root / 'owner workspace'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        launches = [call for call in self.calls() if call['args'][:4] == ['devicectl', 'device', 'process', 'launch']]
        self.assertEqual(len(launches), 2)
        self.assertRegex(launches[0]['receipt'], r'^[0-9a-f]{32}$')
        self.assertNotEqual(launches[0]['receipt'], launches[1]['receipt'])

    def test_boot_launch_log_is_used_when_promotion_did_not_happen(self):
        result = self.run_mode('boot', TEST_SCENARIO='launch_log_only')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any('Documents/boot.launch.txt' in call['args'] for call in self.calls()))

    def test_final_pull_can_capture_quick_probe_completion(self):
        result = self.run_mode('msl', TEST_SCENARIO='late_complete')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_running_without_completion_times_out(self):
        self.assertNotEqual(self.run_mode('boot', '1', TEST_SCENARIO='running').returncode, 0)
        self.assertTrue(self.release.is_file())

    def test_explicit_collection_requires_a_fresh_log_and_confirmed_exit(self):
        result = self.run_mode('boot', TEST_SCENARIO='early_exit', DM_RUN_COLLECT_ONLY='1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('未验证命令完成', result.stdout)
        for scenario in ('query_failure', 'stale_done', 'launch_failure', 'host_failure'):
            with self.subTest(scenario=scenario):
                self.assertNotEqual(self.run_mode('boot', TEST_SCENARIO=scenario,
                                                 DM_RUN_COLLECT_ONLY='1').returncode, 0)

    def test_existing_watch_collectors_use_explicit_collection_mode(self):
        for name in ('frame_cmp.sh', 'pages.sh', 'bootprof.sh', 'gpu_read.sh'):
            path = ROOT / 'dm/ios/tools' / name
            subprocess.run(['bash', '-n', str(path)], check=True, capture_output=True)
            for line in path.read_text().splitlines():
                if './run.sh boot ' in line and not line.lstrip().startswith('#'):
                    self.assertIn('DM_RUN_COLLECT_ONLY=1 ./run.sh boot ', line, name)
                    self.assertIn('||', line, name)

    def test_invalid_arguments_do_not_touch_device_or_output_path(self):
        for args in ((), ('../escape',), ('boot', 'x'), ('boot', '-1'), ('boot', '0')):
            with self.subTest(args=args):
                self.assertEqual(self.run_mode(*args).returncode, 2)
                self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
