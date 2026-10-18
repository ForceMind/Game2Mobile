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
import json
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
    """Verify both guest images have NONEMPTY sections in the correct segments.

    Apple otool -l describes each section's own segname, which is more
    reliable than seeing a section and unrelated segment somewhere in the file.
    """
    sections: dict[tuple[str, str], int] = {}
    current: dict[str, str] | None = None

    def finish() -> None:
        if current is None or "sectname" not in current:
            return
        if "segname" not in current or "size" not in current:
            raise BundleValidationError("Game Mach-O section metadata incomplete")
        try:
            size = int(current["size"], 0)
        except ValueError as exc:
            raise BundleValidationError("Invalid guest section size") from exc
        if size <= 0:
            raise BundleValidationError("Empty game Mach-O guest section")
        key = (current["segname"], current["sectname"])
        if key in sections:
            raise BundleValidationError("Duplicate guest Mach-O section")
        sections[key] = size

    for raw in otool_text.splitlines():
        line = raw.strip()
        if line == "Section":
            finish()
            current = {}
        elif line.startswith("Load command "):
            finish()
            current = None
        elif current is not None:
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] in {"sectname", "segname", "size"}:
                current[parts[0]] = parts[1]
    finish()

    accepted: dict[str, list[str]] = {}
    for module in EXPECTED_MODULES:
        expected = {
            ("__TEXT", f"__dm{module}x0"),
            ("__TEXT", f"__dm{module}x1"),
            (f"__DM{module}W", "__img"),
        }
        if not expected.issubset(sections):
            raise BundleValidationError(
                f"Game guest {module} missing correctly placed executable or writable Mach-O sections"
            )
        accepted[module] = sorted(f"{segment}/{name}" for segment, name in expected)
    return accepted


def expected_shader_chain(header: Path | None = None) -> str:
    """Read the tracked runtime's translation-chain version, not private data."""
    if header is None:
        header = Path(__file__).resolve().parents[1] / "dm/gfx/nvn/dmsh_chain.h"
    try:
        content = header.read_text(encoding="utf-8")
    except OSError as exc:
        raise BundleValidationError("Tracked shader translation-chain header is missing") from exc
    match = re.search(r'(?m)^#define DMSH_CHAIN "([a-f0-9]{12})"\s*$', content)
    if not match:
        raise BundleValidationError("Invalid tracked shader translation-chain version")
    return match.group(1)


def shader_keys_from_map(text: str) -> set[str]:
    """Use precisely the map rows consumed by dmsh_build.py.

    The repository keeps an empty placeholder shader_map.tsv; the real map is
    generated from the owner's game data. A missing/empty bundle map is fatal.
    """
    keys: set[str] = set()
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) <= 4:
            continue
        if not (fields[0].endswith(".bin") or fields[0].startswith("main.rodata@")):
            continue
        key = fields[3]
        if not re.fullmatch(r"[0-9a-f]{16}", key):
            raise BundleValidationError("Malformed game shader mapping key")
        keys.add(key)
    if not keys:
        raise BundleValidationError("Game shader mapping table has no real shader keys")
    return keys


def seed_shader_keys(text: str) -> set[str]:
    """Cross-check shader seeds from the separate PSO warmup manifest."""
    required = set()
    for line in text.splitlines():
        fields = line.split("\t")
        if not fields or fields[0] not in {"S", "C"}:
            continue
        # Existing manifests may retain blank legacy seeds.
        if len(fields) < 2 or not fields[1].strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{16})_b", fields[1])
        if match is None:
            raise BundleValidationError("Malformed seeded shader key")
        required.add(match.group(1))
    if not required:
        raise BundleValidationError("Game PSO manifest has no valid shader seeds")
    return required


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and path.stat().st_size > 0


def require_runtime_resources(app: Path) -> dict[str, object]:
    """Verify the bundle includes ALL keys in its game-derived shader map."""
    missing = [path for path in EXPECTED_RUNTIME_FILES
               if not _regular_file(app / path)]
    if missing:
        raise BundleValidationError(
            "Signed game bundle missing required runtime resources: "
            + ", ".join(missing)
        )
    shader_map = (app / "dm/shader_map.tsv").read_text(encoding="utf-8")
    mapping_keys = shader_keys_from_map(shader_map)
    seeds = seed_shader_keys(
        (app / "dm/pso_manifest.tsv").read_text(encoding="utf-8")
    )
    if not seeds.issubset(mapping_keys):
        raise BundleValidationError(
            "PSO manifest refers to shaders absent from the bundled game map"
        )

    chain = expected_shader_chain()
    root = app / "msl"
    versioned = root / ("b-" + chain)
    if (root.is_symlink() or versioned.is_symlink()
            or not versioned.is_dir()):
        raise BundleValidationError("Expected game shader translation-chain directory is missing")

    missing_library_count = 0
    missing_reflection_count = 0
    invalid_reflection_count = 0
    for key in mapping_keys:
        library = versioned / (key + "_b.metallib")
        reflection = versioned / (key + "_b.json")
        if not _regular_file(library):
            missing_library_count += 1
        if not _regular_file(reflection):
            missing_reflection_count += 1
            continue
        try:
            value = json.loads(reflection.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            invalid_reflection_count += 1
            continue
        if (not isinstance(value, dict)
                or value.get("chain") != chain
                or value.get("key") != key + "_b"
                or value.get("route") != "B"):
            invalid_reflection_count += 1

    if missing_library_count or missing_reflection_count or invalid_reflection_count:
        raise BundleValidationError(
            "Incomplete iPhoneOS shader coverage: "
            f"{missing_library_count} missing Metal libraries, "
            f"{missing_reflection_count} missing reflections, "
            f"{invalid_reflection_count} inconsistent reflections "
            f"across {len(mapping_keys)} mapped shaders"
        )
    return {
        "required_runtime_file_count": len(EXPECTED_RUNTIME_FILES),
        "mapped_shader_count": len(mapping_keys),
        "seeded_shader_count": len(seeds),
        "translated_shader_library_count": len(mapping_keys),
        "shader_chain_verified": True,
        "reflection_coverage_verified": True,
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
    if (executable.is_symlink() or info_file.is_symlink()
            or not executable.is_file() or not info_file.is_file()):
        raise BundleValidationError("Fresh DmIOS.app lacks local executable or Info.plist")
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
        "shader_map_coverage_verified": True,
        "shader_chain_verified": resources["shader_chain_verified"],
        "shader_reflection_coverage_verified": resources["reflection_coverage_verified"],
        "seeded_shader_count": resources["seeded_shader_count"],
        "executable_sha256": hasher.hexdigest(),
        "source_kind": "owner-local-licensed-game",
        "real_device_installed": False,
        "gameplay_tested": False,
    }
