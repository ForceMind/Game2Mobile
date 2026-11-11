"""Real directory aliases and repeated cancellation, without game inputs."""
from contextlib import ExitStack
import os
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from scripts import m1_local_pipeline as pipeline


class PipelinePathAliases(unittest.TestCase):
    def mocked_owner(self):
        stack = ExitStack()
        for name in ('checked_platform', 'tracked_clean'):
            stack.enter_context(mock.patch.object(pipeline, name))
        stack.enter_context(mock.patch.object(pipeline, 'ignored_headers', return_value=True))
        stack.enter_context(mock.patch.object(pipeline, 'head_sha', return_value='a' * 40))
        return stack

    def test_alias_and_canonical_path_are_same_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real = root / 'owner'; real.mkdir()
            alias = root / 'alias'; alias.symlink_to(real, target_is_directory=True)
            romfs = alias / 'data/switch/3.3.94012/Update/RomFS'
            with self.mocked_owner(), mock.patch.object(pipeline, 'execute') as execute:
                record = pipeline.run_pipeline('preflight', 'metal4', alias, romfs)
            self.assertEqual(record['result'], 'partial')
            self.assertEqual(execute.call_args.kwargs['env']['DM_ROOT'], str(real))
            self.assertEqual(execute.call_args.kwargs['env']['DM_ROMFS_SRC'], str(romfs.resolve()))
            self.assertEqual(len(list(real.glob('m1-private-evidence/**/m1-summary.json'))), 1)

    def test_alias_does_not_allow_different_romfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real = root / 'owner'; real.mkdir()
            alias = root / 'alias'; alias.symlink_to(real, target_is_directory=True)
            with self.mocked_owner(), mock.patch.object(pipeline, 'execute') as execute:
                with self.assertRaisesRegex(pipeline.StageError, 'canonical'):
                    pipeline.run_pipeline('preflight', 'metal4', alias, root / 'other')
            execute.assert_not_called()
            self.assertFalse((real / 'm1-private-evidence').exists())

    def test_alias_into_repository_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            alias = Path(tmp) / 'alias'; alias.symlink_to(pipeline.ROOT, target_is_directory=True)
            with self.mocked_owner(), mock.patch.object(pipeline, 'execute') as execute:
                with self.assertRaisesRegex(pipeline.StageError, 'outside'):
                    pipeline.run_pipeline('preflight', 'metal4', alias,
                                          alias / 'data/switch/3.3.94012/Update/RomFS')
            execute.assert_not_called()

    def test_both_build_clis_reject_symlink_loop_without_path_or_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = Path(tmp) / 'private-workspace-loop'
            loop.symlink_to(loop)
            commands = (
                ['scripts/g2mctl.py', 'build', '--execute-local', '--workspace', str(loop)],
                ['scripts/m1_local_pipeline.py', 'preflight', '--workspace', str(loop)],
            )
            for command in commands:
                with self.subTest(cli=command[0]):
                    result = subprocess.run([sys.executable, *command], cwd=pipeline.ROOT,
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertNotIn(str(tmp), result.stdout + result.stderr)
                    self.assertNotIn('Traceback', result.stdout + result.stderr)
                    if command[0].endswith('g2mctl.py'):
                        value = json.loads(result.stdout)
                        self.assertEqual(value['error_code'], 'workspace_path_invalid')
                    else:
                        self.assertIn('workspace_path_invalid', result.stderr)

    def test_evidence_path_loop_still_returns_one_sanitized_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = Path(tmp) / 'private-evidence-loop'
            loop.symlink_to(loop)
            result = subprocess.run(
                [sys.executable, 'scripts/g2mctl.py', 'bundle', '--log', 'boot.txt',
                 '--output', str(loop / 'report.zip')], cwd=pipeline.ROOT,
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['code'], 'LOCAL_EVIDENCE_INVALID')
            self.assertNotIn(str(tmp), result.stdout + result.stderr)
            self.assertNotIn('Traceback', result.stdout + result.stderr)

    def test_repeated_sigterm_during_cleanup_still_reaps_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready, stopping = Path(tmp) / 'ready', Path(tmp) / 'stopping'
            child = ("import os,signal,time;from pathlib import Path;"
                     f"signal.signal(signal.SIGTERM,lambda *_:Path({str(stopping)!r}).write_text('stopping'));"
                     f"Path({str(ready)!r}).write_text(str(os.getpid()));time.sleep(20)")
            wrapper = ("from scripts.process_control import *;import sys,os;"
                       "\ntry:\n with cancellation_signals():\n  run_stage([sys.executable,'-c'," + repr(child) +
                       "],cwd='.',env=os.environ,output=sys.stdout,timeout=30)"
                       "\nexcept ProcessFailure as e:\n print(e.code)\n raise SystemExit(130 if e.code=='stage_cancelled' else 1)")
            runner = subprocess.Popen([sys.executable, '-c', wrapper], cwd=pipeline.ROOT,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            child_pid = None
            try:
                for _ in range(500):
                    if ready.exists() and ready.read_text(): break
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                child_pid = int(ready.read_text())
                runner.send_signal(signal.SIGTERM)
                for _ in range(500):
                    if stopping.exists(): break
                    time.sleep(.01)
                self.assertTrue(stopping.exists(), 'child did not reach termination grace period')
                runner.send_signal(signal.SIGTERM)
                runner.send_signal(signal.SIGINT)
                output, _ = runner.communicate(timeout=6)
                self.assertEqual(runner.returncode, 130, output)
                self.assertIn('stage_cancelled', output)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if runner.poll() is None:
                    runner.kill(); runner.wait()
                if child_pid:
                    try: os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError: pass


if __name__ == '__main__':
    unittest.main()
