"""Asset-free evidence, privacy, cancellation and actual subprocess regressions."""
from __future__ import annotations
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import zipfile

from scripts import evidence_tools as evidence, g2mctl, m1_local_pipeline as pipeline
from scripts.local_io import read_bytes, LocalInputError
from scripts.m1_job_status import BASENAME, read_job_status, publish_job_status, JobStatusError
from scripts.process_control import run_stage, ProcessFailure, exclusive_checkout
from scripts.tests.test_boot_diagnostics import boot, encoded, A
from scripts.tests import test_build_identity as identity_fixture

ROOT = Path(__file__).resolve().parents[2]

class DiagnosticBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / 'private boot.txt'
        self.log.write_bytes(b'/secret/private/account prod.keys token=do-not-export\n' + encoded(*boot()))
        self.dest = self.root / 'diagnostics.zip'

    def test_summary_bundle_is_private_and_does_not_copy_raw_logs(self):
        result = evidence.export_bundle(self.dest, log=self.log)
        self.assertTrue(result['exported'])
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o600)
        with zipfile.ZipFile(self.dest) as z:
            self.assertEqual(set(z.namelist()), {'summary.json', 'manifest.json'})
            data = z.read('summary.json')
            for private in (b'/secret', b'prod.keys', b'do-not-export', str(self.root).encode()):
                self.assertNotIn(private, data)
            summary = json.loads(data)
            self.assertEqual(summary['boot']['run_id'], A)
            self.assertEqual(summary['boot']['playability'], 'unverified')
        self.assertTrue(evidence.inspect_bundle(self.dest)['bundle_integrity_verified'])

    def test_export_rejects_repository_and_existing_output(self):
        with self.assertRaises(evidence.EvidenceError):
            evidence.export_bundle(ROOT / 'should-not-write.zip', log=self.log)
        self.dest.write_bytes(b'previous')
        with self.assertRaises(evidence.EvidenceError):
            evidence.export_bundle(self.dest, log=self.log)
        self.assertEqual(self.dest.read_bytes(), b'previous')

    def test_malformed_or_path_traversal_zip_is_not_trusted(self):
        for extra in ('../private', 'raw.log', 'summary.json'):
            with self.subTest(extra=extra):
                self.dest.unlink(missing_ok=True)
                evidence.export_bundle(self.dest, log=self.log)
                with zipfile.ZipFile(self.dest, 'a') as z:
                    z.writestr(extra, 'malicious')
                with self.assertRaises(evidence.EvidenceError):
                    evidence.inspect_bundle(self.dest)
        self.dest.write_bytes(b'not a zip')
        with self.assertRaises(evidence.EvidenceError):
            evidence.inspect_bundle(self.dest)

    def test_cli_export_requires_explicit_destination_and_is_single_json(self):
        result = g2mctl.operate(['bundle', '--log', str(self.log), '--output', str(self.dest)])
        self.assertEqual(result['code'], 'DIAGNOSTIC_EXPORTED')
        self.assertEqual(result['scope'], 'explicit-local-export')
        self.assertNotIn(str(self.root), json.dumps(result))
        result = g2mctl.operate(['inspect-bundle', str(self.dest)])
        self.assertEqual(result['code'], 'DIAGNOSTIC_INTEGRITY_CHECKED')
        self.assertEqual(result['authenticity'], 'not_attested')

    def test_symlink_and_fifo_never_block_or_escape(self):
        sym = self.root / 'link'; sym.symlink_to(self.log)
        with self.assertRaises(LocalInputError):
            read_bytes(sym, 100000)
        fifo = self.root / 'fifo'; os.mkfifo(fifo)
        with self.assertRaises(LocalInputError):
            read_bytes(fifo, 100000)
        result = g2mctl.operate(['diagnose', '--log', str(fifo)])
        self.assertEqual(result['exit_code'], 2)
        self.assertNotIn(str(fifo), json.dumps(result))

class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        # Reuse inert Mach-O builder, but call the REAL byte verifier.
        self.fixture = identity_fixture.BuildIdentityTests('test_roundtrip_binds_six_actual_sections_and_shader_bytes')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.base
        self.log = self.root / 'boot.txt'; self.log.write_bytes(encoded(*boot()))
        self.record = self.root / 'acceptance.json'
        real_verify = evidence.verify_identity
        patcher = mock.patch.object(evidence, 'verify_identity', side_effect=lambda app, profile, **kw:
            real_verify(app, profile, repo=self.fixture.repo, **kw))
        patcher.start(); self.addCleanup(patcher.stop)
        self.value = evidence.acceptance_template(self.fixture.app, 'metal4', self.log)
        self.value.update(device_model='iPhone16,1', os_version='26.0.1', duration_seconds=1800)
        self.value['checks'] = {key: 'passed' for key in evidence.CHECKS}
        for name in evidence.ATTACHMENTS:
            p = self.root / (name + '.test')
            p.write_bytes((b'\x89PNG\r\n\x1a\n' if name == 'frame' else b'') + b'INERT SYNTHETIC RECORD, NOT GAME EVIDENCE\n')
            self.value['attachments'][name] = {'path': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        self.save()

    def save(self):
        self.record.write_text(json.dumps(self.value))

    def check(self):
        return evidence.check_acceptance(self.record, self.fixture.app, 'metal4', self.log)

    def test_complete_synthetic_record_is_not_device_authentication(self):
        result = self.check()
        self.assertTrue(result['record_complete'])
        self.assertFalse(result['device_execution_verified_by_tool'])
        self.assertEqual(result['playability'], 'requires_manual_review')
        self.assertEqual(result['authenticity'], 'not_attested')
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_template_never_prechecks_human_acceptance(self):
        value = evidence.acceptance_template(self.fixture.app, 'metal4', self.log)
        self.assertEqual(value['duration_seconds'], 0)
        self.assertTrue(all(v == 'not_tested' for v in value['checks'].values()))

    def test_tampered_real_binary_rejected_even_with_matching_claims(self):
        p = self.fixture.app / 'DmIOS'; data = bytearray(p.read_bytes())
        offset, _ = self.fixture.locations[('__TEXT', '__dmmainx0')]
        data[offset] ^= 1; p.write_bytes(data)
        with self.assertRaises(ValueError):
            self.check()

    def test_mismatched_source_profile_run_or_log_cannot_be_borrowed(self):
        original = copy.deepcopy(self.value)
        for field, value in [('source_commit', 'f'*40), ('profile', 'm3'),
                             ('run_id', 'malformed'), ('boot_log_sha256', 'f'*64),
                             ('build_fingerprint', 'e'*64)]:
            self.value = copy.deepcopy(original); self.value[field] = value; self.save()
            with self.subTest(field=field), self.assertRaises(evidence.EvidenceError):
                self.check()
        self.value = copy.deepcopy(original); self.value['run_id'] = 'f'*32; self.save()
        self.assertFalse(self.check()['record_complete'])

    def test_missing_short_or_failed_manual_observations_stay_incomplete(self):
        self.value['checks']['save_reload'] = 'failed'
        self.value['duration_seconds'] = 1799
        self.value['os_version'] = '18.4.1'
        self.save(); result = self.check()
        self.assertFalse(result['record_complete'])
        self.assertIn('save_reload_not_passed', result['unmet'])
        self.assertIn('os_profile_mismatch', result['unmet'])
        self.assertIn('declared_30_minute_session_required', result['unmet'])

    def test_attachments_cannot_escape_or_pass_wrong_digest(self):
        for path in ('../private', '/private/secret', 'frame.test'):
            self.value['attachments']['frame'] = {'path': path, 'sha256': '0'*64}
            self.save(); result = self.check()
            self.assertFalse(result['record_complete'])
            self.assertIn('frame_evidence_invalid', result['unmet'])

class ProcessLifecycleTests(unittest.TestCase):
    def test_success_and_nonzero_exit_do_not_fake_success(self):
        with tempfile.TemporaryFile('w+b') as out:
            run_stage([sys.executable, '-c', 'print("ok")'], cwd=ROOT, env=os.environ,
                      output=out, timeout=2)
            with self.assertRaisesRegex(ProcessFailure, 'stage_command_failed'):
                run_stage([sys.executable, '-c', 'raise SystemExit(7)'], cwd=ROOT,
                          env=os.environ, output=out, timeout=2)

    def test_timeout_kills_descendants_not_just_parent(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile('w+b') as out:
            marker = Path(tmp) / 'escaped'
            descendant = f'import time;from pathlib import Path;time.sleep(0.5);Path({str(marker)!r}).write_text("escaped")'
            parent = f'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",{descendant!r}]);time.sleep(10)'
            with self.assertRaisesRegex(ProcessFailure, 'stage_timeout'):
                run_stage([sys.executable, '-c', parent], cwd=ROOT, env=os.environ,
                          output=out, timeout=0.1)
            time.sleep(0.6)
            self.assertFalse(marker.exists())

    def test_sigterm_cancels_the_actual_child_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'child-started'
            child = f'import time;from pathlib import Path;Path({str(marker)!r}).write_text("ready");time.sleep(20)'
            wrapper = ("from scripts.process_control import *;import sys,os;"
                       "\ntry:\n with cancellation_signals():\n  run_stage([sys.executable,'-c'," + repr(child) + "],cwd='.',env=os.environ,output=sys.stdout,timeout=30)"
                       "\nexcept ProcessFailure as e:\n print(e.code)\n raise SystemExit(130 if e.code=='stage_cancelled' else 1)")
            process = subprocess.Popen([sys.executable, '-c', wrapper], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                for _ in range(200):
                    if marker.exists(): break
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                process.send_signal(signal.SIGTERM)
                text, _ = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 130, text)
                self.assertIn('stage_cancelled', text)
            finally:
                if process.poll() is None:
                    process.kill(); process.wait()

    def test_checkout_lock_rejects_overlapping_builds(self):
        with exclusive_checkout(ROOT):
            with self.assertRaisesRegex(ProcessFailure, 'checkout_build_busy'):
                with exclusive_checkout(ROOT):
                    self.fail('second lock acquired')
        with exclusive_checkout(ROOT):
            pass

    def test_pipeline_cancellation_persists_terminal_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp); romfs = work / 'data/switch/3.3.94012/Update/RomFS'
            with (mock.patch.object(pipeline, 'checked_platform'),
                  mock.patch.object(pipeline, 'tracked_clean'),
                  mock.patch.object(pipeline, 'ignored_headers', return_value=True),
                  mock.patch.object(pipeline, 'head_sha', return_value='a'*40),
                  mock.patch.object(pipeline, 'execute', side_effect=KeyboardInterrupt)):
                with self.assertRaises(pipeline.StageError) as caught:
                    pipeline.run_pipeline('preflight', 'metal4', work, romfs)
            self.assertEqual(caught.exception.code, 'stage_cancelled')
            path = next(work.glob('m1-private-evidence/**/' + BASENAME))
            self.assertEqual(read_job_status(path)['state'], 'cancelled')
            result = g2mctl.operate(['job-status', '--status-file', str(path)])
            self.assertEqual(result['exit_code'], 130)
            self.assertEqual(result['job_liveness'], 'not_checked')
            summary = json.loads(path.with_name('m1-summary.json').read_text())
            self.assertFalse(summary['full_game_app_built'])

    def test_unexpected_pipeline_exception_does_not_leave_running_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp); romfs = work / 'data/switch/3.3.94012/Update/RomFS'
            with (mock.patch.object(pipeline, 'checked_platform'),
                  mock.patch.object(pipeline, 'tracked_clean'),
                  mock.patch.object(pipeline, 'ignored_headers', return_value=True),
                  mock.patch.object(pipeline, 'head_sha', return_value='a'*40),
                  mock.patch.object(pipeline, 'execute', side_effect=KeyError('/private/secret'))):
                with self.assertRaises(pipeline.StageError):
                    pipeline.run_pipeline('preflight', 'metal4', work, romfs)
            path = next(work.glob('m1-private-evidence/**/' + BASENAME))
            self.assertEqual(read_job_status(path)['state'], 'failed')
            self.assertNotIn('/private/secret', path.read_text())

    def test_implicit_build_cannot_run_but_explicit_build_reuses_pipeline(self):
        with mock.patch.object(pipeline, 'run_pipeline', side_effect=AssertionError('unexpected execution')):
            self.assertEqual(g2mctl.operate(['build'])['code'], 'NOT_SUPPORTED')
            self.assertEqual(g2mctl.operate(['build', '--execute-local'])['code'], 'BAD_ARGUMENT')
        with mock.patch.object(pipeline, 'run_pipeline', return_value={'result':'partial'}) as run:
            result = g2mctl.operate(['build', '--execute-local', '--workspace', '/private/work', '--stage', 'preflight'])
        run.assert_called_once()
        self.assertEqual(result['scope'], 'explicit-local-build')
        self.assertEqual(result['playability'], 'unverified')

if __name__ == '__main__':
    unittest.main()
