#!/usr/bin/env python3
"""Owner-only, post-build verification for a REAL Game2Mobile DmIOS game app.

Not a playable-game test and not usable on public CI: an authentic bundle
contains privately generated, commercially owned game resources and modules.
This module never uploads or prints resource content or local identifiers.

The actual iOS build embeds guest main/sdk into Mach-O __TEXT/__DM*W sections
via dm/ios/tools/gen_embed.py. A signed diagnostic app or a no-content shell
must *not* satisfy these acceptance checks.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import plistlib
import re
import subprocess

EXPECTED_MODULES = ("main", "sdk")
EXPECTED_RUNTIME_FILES = (
    "dm/main.fixups.tsv", "dm/main.gates.tsv",
    "dm/sdk.fixups.tsv", "dm/sdk.gates.tsv",
    "dm/shader_map.tsv", "dm/pso_manifest.tsv",
    "romfs_overlay/data/.build.config",
    "Assets.car", "embedded.mobileprovision",
)
EXPECTED_OS = {"metal4": (26, 0), "m3": (18, 0)}


class BundleValidationError(ValueError):
    """Authentic signed game app requirements were not met."""


def ios_version(value: object) -> tuple[int, int]:
    """Normalize iOS deployment-target spelling without accepting wrong OS."""
    if not isinstance(value, str):
        raise BundleValidationError("Missing MinimumOSVersion in iOS Info.plist")
    match = re.fullmatch(r"([0-9]+)(?:\.([0-9]+))?(?:\.0)?", value)
    if not match:
        raise BundleValidationError("Invalid MinimumOSVersion in iOS Info.plist")
    return int(match.group(1)), int(match.group(2) or "0")


def require_guest_sections(otool_text: str) -> dict[str, list[str]]:
    """Check embedded *real game* segments; a no-game shell lacks these."""
    sections = set(re.findall(r"(?m)^\s*sectname\s+(\S+)\s*$", otool_text))
    segments = set(re.findall(r"(?m)^\s*segname\s+(\S+)\s*$", otool_text))
    accepted: dict[str, list[str]] = {}
    for module in EXPECTED_MODULES:
        expected_sections = {f"__dm{module}x0", f"__dm{module}x1"}
        expected_segment = f"__DM{module}W"
        missing = expected_sections - sections
        if missing or expected_segment not in segments:
            raise BundleValidationError(
                f"Game guest {module} missing executable or writable Mach-O sections"
            )
        accepted[module] = sorted(expected_sections) + [expected_segment]
    if "__img" not in sections:
        raise BundleValidationError("Game guest __img writable image section missing")
    return accepted


def require_runtime_resources(app: Path) -> dict[str, object]:
    """Verify necessary game-derived runtime resources exist (not their origin)."""
    missing = [
        path for path in EXPECTED_RUNTIME_FILES
        if not (app / path).is_file() or (app / path).stat().st_size == 0
    ]
    if missing:
        raise BundleValidationError(
            "Signed game bundle missing required runtime resources: "
            + ", ".join(missing)
        )
    shader_bundles = sorted(
        path for path in (app / "msl").glob("b-*/*_b.metallib")
        if path.is_file() and path.stat().st_size > 0
    )
    if not shader_bundles:
        raise BundleValidationError("Missing translated iPhoneOS shader libraries")
    return {
        "required_runtime_file_count": len(EXPECTED_RUNTIME_FILES),
        "translated_shader_library_count": len(shader_bundles),
    }


def _apple_tool(args: list[str], description: str) -> str:
    try:
        result = subprocess.run(args, text=True, capture_output=True, check=False)
    except OSError as exc:
        raise BundleValidationError(
            f"Apple {description} tool unavailable; validate on your Mac"
        ) from exc
    if result.returncode != 0:
        raise BundleValidationError(f"Apple {description} check failed")
    return result.stdout


def validate_real_game_bundle(app: Path, profile: str) -> dict[str, object]:
    """Validate an owner-only signed, game-bearing DmIOS app. No device claim."""
    if profile not in EXPECTED_OS:
        raise BundleValidationError("Unknown Game2Mobile Metal build profile")
    app = Path(app)
    if not app.is_dir() or app.is_symlink():
        raise BundleValidationError("Fresh DmIOS.app missing or is a symlink")
    executable = app / "DmIOS"
    info_file = app / "Info.plist"
    if not executable.is_file() or not info_file.is_file():
        raise BundleValidationError("Fresh DmIOS.app lacks executable or Info.plist")
    try:
        info = plistlib.loads(info_file.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        raise BundleValidationError("Invalid game Info.plist") from exc

    if info.get("CFBundleDisplayName") != "Game2Mobile":
        raise BundleValidationError("Game app display name does not match Game2Mobile")
    if info.get("CFBundleExecutable") != "DmIOS":
        raise BundleValidationError("App executable is not the real DmIOS target")
    bundle_id = info.get("CFBundleIdentifier")
    if not isinstance(bundle_id, str) or not bundle_id or bundle_id == "com.game2mobile.diagnostics.smoke":
        raise BundleValidationError("Invalid game bundle identifier")
    if ios_version(info.get("MinimumOSVersion")) != EXPECTED_OS[profile]:
        raise BundleValidationError(
            f"Built game iOS deployment target does not match {profile} profile"
        )

    archs = _apple_tool(["lipo", "-archs", str(executable)], "ARM64 architecture")
    if "arm64" not in archs.split():
        raise BundleValidationError("Game executable is not ARM64 Mach-O")

    load_commands = _apple_tool(["otool", "-l", str(executable)], "Mach-O sections")
    sections = require_guest_sections(load_commands)
    resources = require_runtime_resources(app)

    # Device signing, not only an ad-hoc Mach-O signature, is required:
    # a provisioning profile must be embedded for this internal iPhoneOS App.
    _apple_tool(
        ["codesign", "--verify", "--deep", "--strict", str(app)],
        "device code-signature",
    )
    signature = app / "embedded.mobileprovision"
    if signature.stat().st_size < 128:
        raise BundleValidationError("Invalid embedded iPhoneOS provisioning profile")

    hasher = hashlib.sha256()
    with executable.open("rb") as game_file:
        for chunk in iter(lambda: game_file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return {
        "real_guest_macho_segments_verified": True,
        "guest_module_count": len(sections),
        "game_runtime_resources_verified": True,
        "app_device_signature_verified": True,
        "actual_minimum_ios_version_verified": True,
        "transformed_shader_library_count": resources["translated_shader_library_count"],
        "executable_sha256": hasher.hexdigest(),
        "source_kind": "owner-local-licensed-game",
        "real_device_installed": False,
        "gameplay_tested": False,
    }
