#!/usr/bin/env python3
"""Import exactly three locally generated Game2Mobile RomFS headers for M1 checks.

This is for an OWNER'S PRIVATE MACHINE ONLY. Never use this function to copy
game-generated files into git, an Actions artifact, or a public working tree.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat

HEADER_NAMES = (
    "dm_hud_exp.h",
    "dm_bright_levels.inc",
    "dm_vault_tab.h",
)
MAX_HEADER_SIZE = 4 * 1024 * 1024


class PrivateInputError(ValueError):
    """The provided owner-generated headers are incomplete or unsafe."""


def inspect_private_headers(folder: Path) -> tuple[Path, ...]:
    """Validate exact required names, file type and plausible nonempty content.

    Never return file bytes or header contents. No file-size/digest metadata is
    written into the externally shareable compiler coverage report.
    """
    folder = Path(folder).expanduser()
    if not folder.is_dir() or folder.is_symlink():
        raise PrivateInputError("Derived-header source must be an existing real directory")
    result = []
    for name in HEADER_NAMES:
        item = folder / name
        try:
            info = item.lstat()
        except FileNotFoundError as exc:
            raise PrivateInputError(f"Missing locally generated header: {name}") from exc
        if not stat.S_ISREG(info.st_mode):
            raise PrivateInputError(f"Generated header must be a regular file, not a link: {name}")
        if not 32 <= info.st_size <= MAX_HEADER_SIZE:
            raise PrivateInputError(f"Invalid generated-header size for {name}")
        # Reject obviously blank files, binary/placeholder data, or injected
        # synthetic files from unrelated CI smoke jobs. Do not print contents.
        with item.open("rb") as f:
            beginning = f.read(4096)
        if b"\0" in beginning or b"CI fixture only" in beginning or not beginning.strip():
            raise PrivateInputError(f"Invalid generated game header: {name}")
        result.append(item)
    return tuple(result)


def stage_private_headers(folder: Path, stage_dm: Path) -> None:
    """Copy only three validated private headers into an ephemeral git-free tree."""
    sources = inspect_private_headers(folder)
    host = Path(stage_dm) / "host"
    if not host.is_dir() or host.is_symlink():
        raise PrivateInputError("Ephemeral build tree is missing its host/ directory")
    for original in sources:
        dest = host / original.name
        if dest.exists() or dest.is_symlink():
            raise PrivateInputError(
                f"Refusing to overwrite an existing staged source: {original.name}"
            )
        # Stage is a temporary directory owned by this compilation run;
        # no source files or reports are uploaded from it.
        shutil.copyfile(original, dest)
        os.chmod(dest, 0o600)


def private_output_is_safe(path: Path, repository: Path) -> bool:
    """Prevent local output files or game assets from being placed in git."""
    resolved = Path(path).expanduser().resolve()
    return not resolved.is_relative_to(Path(repository).resolve())
