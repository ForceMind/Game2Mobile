"""Synthetic tests for private M1 progress snapshots and AI read-only query."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from scripts import g2mctl
from scripts import m1_local_pipeline as pipeline
from scripts.m1_job_status import (
    BASENAME, JobStatusError, MAX_BYTES, publish_job_status, read_job_status,
)


COMMIT = "a" * 40
JOB = "b" * 32


def make_record():
    return pipeline.build_record(COMMIT, "metal4")


class M1ProgressTests(unittest.TestCase):
    def test_atomically_publish_owner_only_metadata_and_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = make_record()
            publish_job_status(root, job_id=JOB, commit=COMMIT, profile="metal4",
                               action="all", state="running", current_stage="preflight", record=record)
            path = root / BASENAME
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            first = read_job_status(path)
            self.assertEqual((first["state"], first["current_stage"]), ("running", "preflight"))
            self.assertEqual(first["job_id"], JOB)
            record["steps"]["preflight"] = "passed"
            publish_job_status(root, job_id=JOB, commit=COMMIT, profile="metal4",
                               action="all", state="running", current_stage=None, record=record)
            latest = read_job_status(path)
            self.assertEqual(latest["steps"], {"preflight": "passed"})
            self.assertEqual(latest["job_id"], JOB)
            self.assertEqual(sorted(p.name for p in root.iterdir()), [BASENAME])
            self.assertFalse(latest["full_game_app_built"])

    def test_publish_and_read_completed_all_stages_without_claiming_playable(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = make_record()
            record["steps"] = {name: "passed" for name in pipeline.STAGE_COMMANDS}
            record["end_to_end_build_stages_verified"] = True
            record["result"] = "passed"
            record["full_game_app_built"] = True
            record["app_signed_locally"] = True
            publish_job_status(Path(tmp), job_id=JOB, commit=COMMIT, profile="metal4",
                               action="all", state="passed", current_stage=None, record=record)
            r = read_job_status(Path(tmp) / BASENAME)
            self.assertEqual(r["state"], "passed")
            operator = g2mctl.operate(["job-status", "--status-file", str(Path(tmp) / BASENAME)])
            self.assertEqual(operator["code"], "M1_STAGES_PASSED")
            self.assertEqual(operator["exit_code"], 0)
            self.assertEqual(operator["playability"], "unverified")
            self.assertNotIn(str(tmp), json.dumps(operator))

    def test_partial_and_failed_status_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = make_record()
            record["steps"]["preflight"] = "passed"
            record["result"] = "partial"
            p = Path(tmp)
            publish_job_status(p, job_id=JOB, commit=COMMIT, profile="metal4",
                               action="preflight", state="partial", current_stage=None, record=record)
            r = g2mctl.operate(["job-status", "--status-file", str(p / BASENAME)])
            self.assertEqual((r["code"], r["exit_code"]), ("M1_JOB_PARTIAL", 1))
            record["steps"] = {"source": "failed"}
            record["result"] = "failed"
            publish_job_status(p, job_id=JOB, commit=COMMIT, profile="metal4",
                               action="all", state="failed", current_stage="source", record=record)
            r = g2mctl.operate(["job-status", "--status-file", str(p / BASENAME)])
            self.assertEqual((r["code"], r["exit_code"]), ("M1_JOB_FAILED", 1))

    def test_reader_rejects_symlink_missing_and_oversized(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            missing = p / "missing.json"
            invalid = g2mctl.operate(["job-status", "--status-file", str(missing)])
            self.assertEqual((invalid["code"], invalid["exit_code"]), ("M1_STATUS_INVALID", 2))
            large = p / "large.json"
            large.write_bytes(b"x" * (MAX_BYTES + 1))
            with self.assertRaises(JobStatusError):
                read_job_status(large)
            sym = p / "link.json"
            sym.symlink_to(large)
            with self.assertRaises(JobStatusError):
                read_job_status(sym)

    def test_reader_rejects_inconsistent_and_malicious_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / BASENAME
            record = make_record()
            publish_job_status(Path(tmp), job_id=JOB, commit=COMMIT, profile="metal4",
                               action="all", state="running", current_stage="build", record=record)
            original = json.loads(p.read_text())
            for mutation in (
                {"schema": "unknown"},
                {"source_commit": "/private/secret"},
                {"state": "passed", "result": "passed"},
                {"steps": {"build": "/private/secret"}},
                {"current_stage": "/private/secret"},
                {"updated_utc": "/private/secret"},
                {"end_to_end_build_stages_verified": 1},
            ):
                altered = original | mutation
                with self.subTest(mutation=mutation):
                    p.write_text(json.dumps(altered))
                    with self.assertRaises(JobStatusError):
                        read_job_status(p)
            p.write_text('{"schema":"game2mobile.m1-job-status.v1","schema":"evil"}')
            with self.assertRaises(JobStatusError):
                read_job_status(p)
            p.write_text(json.dumps(original | {"unknown_private_path": "/private/secret"}))
            self.assertNotIn("unknown_private_path", read_job_status(p))

    def test_publish_refuses_symlink_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "outside"
            out.write_text("untouched")
            (root / BASENAME).symlink_to(out)
            with self.assertRaises(JobStatusError):
                publish_job_status(root, job_id=JOB, commit=COMMIT,
                                   profile="metal4", action="all", state="running",
                                   current_stage=None, record=make_record())
            self.assertEqual(out.read_text(), "untouched")

    def test_pipeline_publishes_running_before_stage_and_partial_at_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            romfs = work / "data/switch/3.3.94012/Update/RomFS"
            captured = []
            def fake_execute(stage, command, *, cwd, env, evidence_dir):
                progress = read_job_status(evidence_dir / BASENAME)
                captured.append(progress)
                self.assertEqual(progress["state"], "running")
                self.assertEqual(progress["current_stage"], stage)
                self.assertEqual(stat.S_IMODE((evidence_dir / BASENAME).stat().st_mode), 0o600)
            with (
                mock.patch.object(pipeline, "checked_platform"),
                mock.patch.object(pipeline, "tracked_clean"),
                mock.patch.object(pipeline, "ignored_headers", return_value=True),
                mock.patch.object(pipeline, "head_sha", return_value=COMMIT),
                mock.patch.object(pipeline, "execute", side_effect=fake_execute),
            ):
                result = pipeline.run_pipeline("preflight", "metal4", work, romfs)
            self.assertEqual(result["result"], "partial")
            self.assertEqual(len(captured), 1)
            root = next(work.glob("m1-private-evidence/**/m1-job-status.json"))
            final = read_job_status(root)
            self.assertEqual(final["state"], "partial")
            self.assertEqual(final["steps"], {"preflight": "passed"})

    def test_pipeline_failure_status_and_summary_do_not_leak_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            romfs = work / "data/switch/3.3.94012/Update/RomFS"
            def fail(stage, command, **kwargs):
                progress = read_job_status(kwargs["evidence_dir"] / BASENAME)
                self.assertEqual(progress["current_stage"], "preflight")
                raise pipeline.StageError("preflight", "/private/credentials/secret")
            with (
                mock.patch.object(pipeline, "checked_platform"),
                mock.patch.object(pipeline, "tracked_clean"),
                mock.patch.object(pipeline, "ignored_headers", return_value=True),
                mock.patch.object(pipeline, "head_sha", return_value=COMMIT),
                mock.patch.object(pipeline, "execute", side_effect=fail),
            ):
                with self.assertRaises(pipeline.StageError):
                    pipeline.run_pipeline("preflight", "metal4", work, romfs)
            snapshot = next(work.glob("m1-private-evidence/**/m1-job-status.json"))
            progress = read_job_status(snapshot)
            self.assertEqual(progress["state"], "failed")
            self.assertEqual(progress["current_stage"], "preflight")
            self.assertEqual(progress["steps"], {"preflight": "failed"})
            self.assertNotIn("/private/credentials", snapshot.read_text())
            summary = json.loads(snapshot.with_name("m1-summary.json").read_text())
            self.assertEqual(summary["result"], "failed")

    def test_cli_cannot_access_status_without_explicit_file(self):
        result = g2mctl.operate(["job-status"])
        self.assertEqual((result["code"], result["exit_code"]), ("BAD_ARGUMENT", 2))
        self.assertTrue(g2mctl.operate(["capabilities"])["operations"]["job-status"])


if __name__ == "__main__":
    unittest.main()
