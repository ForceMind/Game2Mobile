"""Synchronous owner-machine stage execution with bounded cleanup of its children.

Never searches for/kills unrelated processes. Each child starts in its own POSIX
session. Tests use harmless Python subprocesses; no licensed input is involved.
"""
from __future__ import annotations
from contextlib import contextmanager
import math
import os
import signal
import subprocess
import threading

class ProcessFailure(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

@contextmanager
def _cleanup_signals():
    """Repeated Ctrl-C/TERM must not abandon children midway through cleanup."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _terminate_group(process: subprocess.Popen, grace: float = 2.0) -> None:
    with _cleanup_signals():
        _terminate_group_uninterruptible(process, grace)


def _terminate_group_uninterruptible(process: subprocess.Popen, grace: float) -> None:
    def send(sig):
        try:
            if os.name == 'posix':
                os.killpg(process.pid, sig)
            elif process.poll() is None:
                process.terminate() if sig == signal.SIGTERM else process.kill()
        except ProcessLookupError:
            pass
    send(signal.SIGTERM)
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    # A child can outlive its parent, so always clean the session on failure.
    send(signal.SIGKILL)
    process.wait(timeout=grace)

def run_stage(command: list[str], *, cwd, env, output, timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ProcessFailure('invalid_stage_timeout')
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=os.name == 'posix')
    except OSError as exc:
        raise ProcessFailure('stage_start_failed') from exc
    try:
        status = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_group(process)
        raise ProcessFailure('stage_timeout') from exc
    except KeyboardInterrupt as exc:
        _terminate_group(process)
        raise ProcessFailure('stage_cancelled') from exc
    except BaseException:
        _terminate_group(process)
        raise
    if status:
        _terminate_group(process)
        raise ProcessFailure('stage_command_failed')

@contextmanager
def cancellation_signals():
    """CLI-only: turn SIGTERM into the same clean cancellation as Ctrl-C."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)

@contextmanager
def exclusive_checkout(repository):
    """Serialize builds which share Gen/private generated files in this checkout.

    The lock stays in Git's private metadata directory. It is never removed
    while another process could be waiting on the same inode.
    """
    import fcntl
    import stat
    from pathlib import Path
    result = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=repository,
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ProcessFailure('checkout_lock_unavailable')
    directory = Path(result.stdout.strip())
    if not directory.is_absolute():
        directory = Path(repository) / directory
    fd = None
    try:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        fd = os.open(directory / 'game2mobile-m1.lock', flags, 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ProcessFailure('checkout_lock_unavailable')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProcessFailure('checkout_build_busy') from exc
        yield
    except OSError as exc:
        raise ProcessFailure('checkout_lock_unavailable') from exc
    finally:
        if fd is not None:
            os.close(fd)
