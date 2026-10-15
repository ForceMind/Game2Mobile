#!/usr/bin/env python3
"""Check an unsigned Game2Mobile Diagnostics .app, not the playable game."""
from __future__ import annotations
import argparse
import json
import plistlib
import subprocess
from pathlib import Path

EXPECTED_ID = "com.game2mobile.diagnostics.smoke"
EXPECTED_NAME = "Game2Mobile Diagnostics"

def verify(app: Path, platform: str, sha: str) -> dict:
    if platform not in ("iphoneos", "iphonesimulator"):
        raise ValueError("Unsupported Apple SDK")
    if not app.is_dir():
        raise ValueError("Missing .app folder")
    info = plistlib.loads((app / "Info.plist").read_bytes())
    for key, expected in {
        "CFBundleDisplayName": EXPECTED_NAME,
        "CFBundleIdentifier": EXPECTED_ID,
        "CFBundleExecutable": "Game2MobileDiagnostics",
    }.items():
        if info.get(key) != expected:
            raise ValueError(f"Unexpected {key}: {info.get(key)!r} != {expected!r}")
    executable = app / "Game2MobileDiagnostics"
    if not executable.is_file() or executable.stat().st_size < 10000:
        raise ValueError("Missing or empty Apple app executable")
    architectures = subprocess.check_output(["lipo", "-archs", str(executable)], text=True).split()
    if "arm64" not in architectures:
        raise ValueError(f"Not ARM64 Mach-O: {architectures}")
    if not (app / "Assets.car").is_file():
        raise ValueError("Brand AppIcon was not compiled into Assets.car")
    entries = sorted(p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file())
    prohibited = []
    for path in entries:
        name = path.lower()
        if (
            name.startswith(("dm/", "msl/", "romfs_overlay/", "frameworks/guest.framework/"))
            or name.endswith((".nso", ".nsp", ".xci", ".metallib", ".data"))
            or name.startswith("dm_native_")
        ):
            prohibited.append(path)
    if prohibited:
        raise ValueError("Unexpected game-derived files: " + ", ".join(prohibited[:8]))
    report = {
        "artifact_kind": "non-playable-game2mobile-build-diagnostics",
        "platform": platform, "source_commit": sha,
        "arm64_macho": True, "app_icon_compiled": True,
        "bundle_id": EXPECTED_ID, "app_display_name": EXPECTED_NAME,
        "game_runtime_included": False, "proprietary_game_assets_included": False,
        "signed_for_devices": False, "gameplay_tested": False,
        "file_count": len(entries), "executable_size_bytes": executable.stat().st_size,
    }
    print(json.dumps(report, indent=2))
    return report

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("app", type=Path)
    p.add_argument("--platform", choices=("iphoneos", "iphonesimulator"), required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    result = verify(a.app, a.platform, a.sha)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
