"""Explicit local diagnostic export and owner-supplied acceptance record checks.

These tools never upload files. ZIP integrity and a complete manual record are
NOT authenticated evidence of device execution, pixels, audio or gameplay.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

try:
    from .boot_diagnostics import analyze_stream
    from .build_identity import ROOT, read_identity, verify_identity
    from .local_io import read_bytes, regular_file, strict_json, LocalInputError
    from .m1_job_status import read_job_status
except ImportError:
    from boot_diagnostics import analyze_stream
    from build_identity import ROOT, read_identity, verify_identity
    from local_io import read_bytes, regular_file, strict_json, LocalInputError
    from m1_job_status import read_job_status

BUNDLE_SCHEMA = 'game2mobile.diagnostic-bundle.v1'
RECORD_SCHEMA = 'game2mobile.acceptance-record.v1'
MAX_LOG = 16 * 1024 * 1024
MAX_JSON = 128 * 1024
CHECKS = ('menu', 'touch', 'controller', 'graphics', 'audio', 'save_reload', 'background_resume')
ATTACHMENTS = ('frame', 'session_log', 'save_reload_log')

class EvidenceError(ValueError):
    pass

def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()

def log_report(path: Path, run_id: str | None = None) -> tuple[dict, str]:
    raw = read_bytes(path, MAX_LOG)
    return analyze_stream(io.BytesIO(raw), run_id), hashlib.sha256(raw).hexdigest()

def safe_boot_summary(report: dict) -> dict:
    # Do not copy raw log lines, paths, free-text error codes or arbitrary fields.
    return {key: report[key] for key in ('run_id', 'result', 'exit_code',
            'first_present', 'gpu_submit', 'event_count', 'issue_count', 'playability')}

def export_bundle(destination: Path, *, log: Path | None = None,
                  status: Path | None = None, run_id: str | None = None,
                  repository: Path = ROOT) -> dict:
    if log is None and status is None:
        raise EvidenceError('diagnostic_input_required')
    destination = Path(destination).expanduser()
    if destination.resolve().is_relative_to(repository.resolve()):
        raise EvidenceError('diagnostic_output_must_be_outside_repository')
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink() or destination.exists() or destination.is_symlink():
        raise EvidenceError('diagnostic_output_unavailable')
    report = {'schema': BUNDLE_SCHEMA, 'scope': 'local-unattested-summary',
              'playability': 'unverified', 'review_before_sharing': True,
              'contains_raw_logs': False, 'contains_game_files': False}
    if log is not None:
        boot, digest = log_report(log, run_id)
        report['boot'] = safe_boot_summary(boot)
        report['input_log_sha256'] = digest
    if status is not None:
        report['job'] = read_job_status(status)
        report['job_liveness'] = 'not_checked'
    summary = canonical(report)
    manifest = canonical({'schema': BUNDLE_SCHEMA, 'files': {
        'summary.json': {'size': len(summary), 'sha256': hashlib.sha256(summary).hexdigest()}}})
    fd, temporary = tempfile.mkstemp(prefix='.g2m-diagnostics-', dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w+b') as output:
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', manifest)
                archive.writestr('summary.json', summary)
            output.flush(); os.fsync(output.fileno())
        # Publishing with a hard link is exclusive/atomic; never replace an old report.
        os.link(temporary, destination)
    except OSError as exc:
        raise EvidenceError('diagnostic_export_failed') from exc
    finally:
        os.unlink(temporary)
    return {'exported': True, 'entries': ['manifest.json', 'summary.json'],
            'contains_raw_logs': False, 'playability': 'unverified',
            'review_before_sharing': True}

def inspect_bundle(path: Path) -> dict:
    try:
        raw = read_bytes(path, 2 * MAX_JSON)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) != 2 or set(names) != {'manifest.json', 'summary.json'}:
                raise EvidenceError('unexpected_diagnostic_entries')
            for name in names:
                info = archive.getinfo(name)
                if not 0 < info.file_size <= MAX_JSON:
                    raise EvidenceError('diagnostic_entry_limit')
            summary = archive.read('summary.json')
            manifest = strict_json(archive.read('manifest.json'))
            value = strict_json(summary)
        expected = {'size': len(summary), 'sha256': hashlib.sha256(summary).hexdigest()}
        if (not isinstance(manifest, dict) or manifest.get('schema') != BUNDLE_SCHEMA or
            manifest.get('files') != {'summary.json': expected} or not isinstance(value, dict) or
            value.get('schema') != BUNDLE_SCHEMA or value.get('scope') != 'local-unattested-summary'):
            raise EvidenceError('diagnostic_manifest_mismatch')
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise EvidenceError('invalid_diagnostic_bundle') from exc
    return {'bundle_integrity_verified': True, 'scope': 'archive-integrity-only',
            'playability': 'unverified', 'authenticity': 'not_attested', 'review_before_sharing': True}

def acceptance_template(app: Path, profile: str, log: Path) -> dict:
    verified = verify_identity(app, profile, require_clean=True)
    identity = read_identity(app)
    boot, digest = log_report(log)
    return {'schema': RECORD_SCHEMA, 'profile': profile,
            'source_commit': identity['source']['commit'],
            'build_fingerprint': verified['build_identity_fingerprint'],
            'game_build_id': identity['modules']['main']['build_id'],
            'run_id': boot['run_id'], 'boot_log_sha256': digest,
            'device_model': '', 'os_version': '', 'duration_seconds': 0,
            'checks': {name: 'not_tested' for name in CHECKS},
            'attachments': {name: {'path': '', 'sha256': ''} for name in ATTACHMENTS}}

def _attachment(root: Path, item: object, kind: str) -> str:
    if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
        raise EvidenceError('invalid_attachment_record')
    name, digest = item['path'], item['sha256']
    if (not isinstance(name, str) or not name or '\\' in name or
        Path(name).is_absolute() or any(x in ('.', '..') for x in name.split('/')) or
        not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None):
        raise EvidenceError('invalid_attachment_identity')
    path = root
    for part in name.split('/'):
        if not part:
            raise EvidenceError('invalid_attachment_path')
        path /= part
        if path.is_symlink():
            raise EvidenceError('symlinked_attachment')
    if not path.resolve().is_relative_to(root.resolve()):
        raise EvidenceError('attachment_outside_record_directory')
    h = hashlib.sha256(); total = 0
    with regular_file(path) as source:
        beginning = source.read(32); h.update(beginning); total += len(beginning)
        if kind == 'frame' and not (beginning.startswith(b'\x89PNG\r\n\x1a\n') or beginning.startswith(b'\xff\xd8\xff')):
            raise EvidenceError('frame_container_not_png_or_jpeg')
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > 64 * 1024 * 1024:
                raise EvidenceError('attachment_size_limit')
            h.update(chunk)
    if total < 32 or h.hexdigest() != digest:
        raise EvidenceError('attachment_hash_mismatch')
    return digest

def check_acceptance(record_path: Path, app: Path, profile: str, log: Path) -> dict:
    """Compare real App bytes, explicit boot evidence and a human-authored record.

    A complete record still requires manual review: self-authored logs, duration,
    checkboxes and attachments cannot establish authentic physical execution.
    """
    if record_path.resolve().is_relative_to(ROOT.resolve()):
        raise EvidenceError('device_record_must_stay_private')
    record = strict_json(read_bytes(record_path, MAX_JSON))
    if not isinstance(record, dict) or record.get('schema') != RECORD_SCHEMA:
        raise EvidenceError('invalid_acceptance_schema')
    # This performs the actual byte verification, not just a manifest checksum.
    verified = verify_identity(app, profile, require_clean=True)
    identity = read_identity(app)
    expected = {'profile': profile, 'source_commit': identity['source']['commit'],
                'game_build_id': identity['modules']['main']['build_id'],
                'build_fingerprint': verified['build_identity_fingerprint']}
    if any(record.get(key) != value for key, value in expected.items()):
        raise EvidenceError('acceptance_build_mismatch')
    run_id = record.get('run_id')
    if not isinstance(run_id, str) or re.fullmatch('[0-9a-f]{32}', run_id) is None:
        raise EvidenceError('acceptance_run_id_invalid')
    boot, digest = log_report(log, run_id)
    if record.get('boot_log_sha256') != digest:
        raise EvidenceError('acceptance_log_mismatch')
    unmet = []
    if boot['exit_code'] != 0:
        unmet.append('valid_first_present_required')
    device, os_version = record.get('device_model'), record.get('os_version')
    if not isinstance(device, str) or re.fullmatch(r'[A-Za-z0-9 ,._()-]{2,64}', device) is None:
        unmet.append('device_model_required')
    if not isinstance(os_version, str) or re.fullmatch(r'\d{1,2}(\.\d{1,3}){1,2}', os_version) is None:
        unmet.append('os_version_required')
    elif int(os_version.split('.')[0]) < (26 if profile == 'metal4' else 18):
        unmet.append('os_profile_mismatch')
    duration = record.get('duration_seconds')
    if type(duration) is not int or not 1800 <= duration <= 86400:
        unmet.append('declared_30_minute_session_required')
    checks = record.get('checks')
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        raise EvidenceError('acceptance_check_inventory')
    for name in CHECKS:
        if checks[name] not in ('passed', 'failed', 'not_tested'):
            raise EvidenceError('invalid_acceptance_check')
        if checks[name] != 'passed':
            unmet.append(name + '_not_passed')
    attachments = record.get('attachments')
    if not isinstance(attachments, dict) or set(attachments) != set(ATTACHMENTS):
        raise EvidenceError('acceptance_attachment_inventory')
    hashes = {}
    for kind in ATTACHMENTS:
        try:
            hashes[kind] = _attachment(record_path.parent, attachments[kind], kind)
        except (EvidenceError, LocalInputError, OSError):
            unmet.append(kind + '_evidence_invalid')
    return {'schema': 'game2mobile.acceptance-check.v1', 'record_complete': not unmet,
            'exit_code': 1 if unmet else 0, 'unmet': unmet,
            'actual_app_bytes_checked': True, 'first_present_evidence_valid': boot['exit_code'] == 0,
            'profile': profile, 'run_id': run_id, 'attachment_hashes': hashes,
            'scope': 'local-record-consistency-only', 'playability': 'requires_manual_review',
            'authenticity': 'not_attested', 'device_execution_verified_by_tool': False}
