"""Read-only, privacy-preserving toolchain prerequisites for local M1.

A green result means only that the public build tools appear present. This
never opens game files, queries identities/keychains, executes setup.sh or
claims that an App can be signed, installed, or played.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("python3", "git", "make", "xcodegen", "spirv-cross", "dotnet")


def _run(probe, command: list[str], *, cwd: Path | None = None) -> tuple[bool | None, str | None]:
    """Never return command output: SDK paths and Git status may be private."""
    try:
        result = probe(command, cwd=cwd, capture_output=True, text=True,
                       timeout=5, check=False)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        return None, None
    if result.returncode != 0:
        return False, None
    return True, result.stdout if command[-3:-1] == ["status", "--porcelain"] else None


def doctor_environment(*, root: Path = ROOT, system: str | None = None,
                       machine: str | None = None, which=None, run=None,
                       xcrun_present: bool | None = None) -> dict:
    """Check fixed local prerequisites only, without reading owner game data.

    Optional probes enable fully synthetic tests on Linux, independent of
    host tools or signing state. Results contain only enumerated flags.
    """
    system = sys.platform if system is None else system
    machine = platform.machine() if machine is None else machine
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run
    xcrun_present = (os.access("/usr/bin/xcrun", os.X_OK)
                     if xcrun_present is None else xcrun_present)
    checks: list[dict[str, str]] = []

    def add(identifier: str, status: str) -> None:
        checks.append({"id": identifier, "status": status})

    apple_silicon = system == "darwin" and machine == "arm64"
    add("platform", "ready" if apple_silicon else "unsupported")
    found = {name: which(name) for name in TOOLS}
    # Match setup.sh: owners may install .NET without Homebrew.
    if not found["dotnet"]:
        fallback = Path.home() / ".dotnet/dotnet"
        if fallback.is_file() and os.access(fallback, os.X_OK):
            found["dotnet"] = str(fallback)
    for tool in TOOLS:
        add(tool.replace("-", "_"), "ready" if found[tool] else "missing")

    checkout = Path(root) / ".git"
    if not checkout.exists():
        add("git_checkout", "missing")
        add("source_clean", "unknown")
    else:
        add("git_checkout", "ready")
        if found["git"]:
            # Disable optional index locks and fsmonitor hooks for this
            # read-only probe. Report only clean/dirty, never private names.
            status, changes = _run(run, [found["git"], "-c", "core.fsmonitor=false",
                                         "--no-optional-locks", "status", "--porcelain",
                                         "--untracked-files=all"], cwd=Path(root))
            if status is None or status is False:
                add("source_clean", "unknown")
            else:
                add("source_clean", "blocked" if changes and changes.strip() else "ready")
        else:
            add("source_clean", "unknown")

    apple_commands = (
        ("xcode", ["/usr/bin/xcrun", "--find", "xcodebuild"]),
        ("iphoneos_sdk", ["/usr/bin/xcrun", "--sdk", "iphoneos", "--show-sdk-path"]),
        ("metal_compiler", ["/usr/bin/xcrun", "-sdk", "iphoneos", "metal", "--version"]),
    )
    for identifier, command in apple_commands:
        if not apple_silicon:
            add(identifier, "unsupported")
        elif not xcrun_present:
            add(identifier, "missing")
        else:
            result, _ = _run(run, command)
            add(identifier, "ready" if result is True else "missing" if result is False else "unknown")

    # The exact private assets, local signing and device are intentionally not
    # inspected. Never turn an 'exists' check into evidence of lawful inputs.
    for name in ("licensed_inputs", "local_signing", "physical_device"):
        add(name, "not_checked")
    public = [item for item in checks if item["status"] != "not_checked"]
    return {"checks": checks,
            "toolchain_ready": all(item["status"] == "ready" for item in public),
            "private_inputs_verified": False,
            "signing_verified": False,
            "device_verified": False}
