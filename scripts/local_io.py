"""Bounded explicit local-file reads; no discovery, network or implicit uploads."""
from __future__ import annotations
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat

class LocalInputError(ValueError):
    pass

@contextmanager
def regular_file(path: Path):
    """Open once, reject symlinks/special files without blocking on a FIFO."""
    fd = None
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
        path = Path(path).expanduser()
        if path.is_symlink():
            raise LocalInputError('symlinked_input')
        fd = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise LocalInputError('not_regular_file')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            yield stream
    except (OSError, ValueError) as exc:
        if isinstance(exc, LocalInputError):
            raise
        raise LocalInputError('local_input_unreadable') from exc
    finally:
        if fd is not None:
            os.close(fd)

def read_bytes(path: Path, maximum: int) -> bytes:
    if type(maximum) is not int or maximum <= 0:
        raise LocalInputError('invalid_size_limit')
    with regular_file(path) as stream:
        if os.fstat(stream.fileno()).st_size > maximum:
            raise LocalInputError('input_size_limit')
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise LocalInputError('input_size_limit')
    return data

def strict_json(data: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise LocalInputError('duplicate_json_key')
            result[key] = value
        return result
    def constant(_):
        raise LocalInputError('nonfinite_json_number')
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise LocalInputError('invalid_json') from exc
