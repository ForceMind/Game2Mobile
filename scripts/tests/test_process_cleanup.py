"""Post-merge Darwin EPERM regression: zombie-only is not live permission denial."""
import errno
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from scripts import process_control as control

ROOT = Path(__file__).resolve().parents[2]


class ProcessCleanupTests(unittest.TestCase):
    def ps(self, stdout='', status=0, stderr=''):
        return subprocess.CompletedProcess([], status, stdout=stdout, stderr=stderr)

    def test_darwin_confirmed_zombies_or_vanished_group_only(self):
        with mock.patch.object(control.sys, 'platform', 'darwin'):
            for result in (self.ps('321 Z\n321 ZN\n'), self.ps(''), self.ps('', 1)):
                with self.subTest(result=result), mock.patch.object(control.subprocess, 'run', return_value=result) as ps:
                    self.assertTrue(control._darwin_group_exited(321))
                    self.assertEqual(ps.call_args.args[0], ['/bin/ps', '-x', '-g', '321', '-o', 'pgid=,stat='])
                    self.assertEqual(ps.call_args.kwargs['timeout'], 1)
            for result in (self.ps('321 S\n'), self.ps('321 Z\n321 R\n'),
                           self.ps('999 Z\n'), self.ps('321\n'), self.ps('321 Z\n', 1),
                           self.ps('', 2), self.ps('', 0, '/private/error'),
                           self.ps('321 Z\n' * 12000)):
                with self.subTest(result=result.returncode), mock.patch.object(control.subprocess, 'run', return_value=result):
                    self.assertFalse(control._darwin_group_exited(321))

    def test_unavailable_probe_and_non_darwin_do_not_hide_denial(self):
        with mock.patch.object(control.sys, 'platform', 'darwin'):
            for error in (OSError('/private/error'), subprocess.TimeoutExpired('ps', 1)):
                with mock.patch.object(control.subprocess, 'run', side_effect=error):
                    self.assertFalse(control._darwin_group_exited(321))
        with mock.patch.object(control.sys, 'platform', 'linux'), mock.patch.object(control.subprocess, 'run') as ps:
            self.assertFalse(control._darwin_group_exited(321))
            ps.assert_not_called()

    def test_timeout_preserved_after_confirmed_darwin_zombie_eperm(self):
        process = mock.Mock(pid=321)
        process.wait.side_effect = [subprocess.TimeoutExpired('stage', .1), -15, -15]
        with (mock.patch.object(control.subprocess, 'Popen', return_value=process),
              mock.patch.object(control.os, 'killpg', side_effect=[None, PermissionError(errno.EPERM, '/private/error')]),
              mock.patch.object(control, '_darwin_group_exited', return_value=True) as exited):
            with self.assertRaisesRegex(control.ProcessFailure, '^stage_timeout$'):
                control.run_stage(['fixture'], cwd=ROOT, env={}, output=None, timeout=.1)
        exited.assert_called_once_with(321)
        process.kill.assert_not_called()

    def test_live_or_uninspectable_eperm_fails_closed_and_reaps_child(self):
        process = mock.Mock(pid=321)
        process.wait.return_value = -9
        with (mock.patch.object(control.os, 'killpg', side_effect=PermissionError(errno.EPERM, '/private/error')),
              mock.patch.object(control, '_darwin_group_exited', return_value=False)):
            with self.assertRaisesRegex(control.ProcessFailure, '^stage_cleanup_failed$'):
                control._terminate_group(process)
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_cleanup_wait_timeout_is_sanitized_not_success(self):
        process = mock.Mock(pid=321)
        process.wait.side_effect = subprocess.TimeoutExpired('/private/command', 2)
        with mock.patch.object(control.os, 'killpg'):
            with self.assertRaisesRegex(control.ProcessFailure, '^stage_cleanup_failed$'):
                control._terminate_group(process)

    def test_kill_reaches_term_ignoring_descendant_after_parent_exits(self):
        # Parent remains alive until child installs SIG_IGN; its own TERM exit
        # must not bypass the KILL of the still-live descendant group member.
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile('w+b') as out:
            ready = Path(tmp) / 'ready'
            escaped = Path(tmp) / 'escaped'
            child = ('import os,signal,time;from pathlib import Path;'
                     'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                     f'Path({str(ready)!r}).write_text(str(os.getpid()));'
                     f'time.sleep(1);Path({str(escaped)!r}).write_text("escaped")')
            parent = f'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",{child!r}]);time.sleep(10)'
            process = subprocess.Popen([sys.executable, '-c', parent], cwd=ROOT,
                                       stdout=out, stderr=out, start_new_session=True)
            try:
                for _ in range(500):
                    if ready.exists() and ready.read_text():
                        break
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                control._terminate_group(process, grace=.1)
                self.assertIsNotNone(process.returncode)
                time.sleep(1.05)
                self.assertFalse(escaped.exists(), 'descendant survived private group cleanup')
            finally:
                try: os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError): pass
                process.wait(timeout=3)


if __name__ == '__main__':
    unittest.main()
