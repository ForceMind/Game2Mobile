#!/usr/bin/env python3
"""Verify all four real XcodeGen project variants on a Mac without game assets.

Only tracked dm/ios files are copied into an isolated temporary directory.
Placeholder Gen/* build inputs are CI fixtures, NOT real game resources.
No signing, pre-build asset generation, compiler linking or device launch occurs.

Usage: python3 scripts/ci_xcodegen_profiles.py --report /tmp/xcodegen-report.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IOS_REL = Path("dm/ios")
RESOURCE_DIRS = (
    "Gen/dm", "Gen/msl", "Gen/src", "Gen/main", "Gen/save_ref",
    "Gen/save_ref_warlock", "Gen/assets/NativeHUD/v4/hud_v4_ui",
    "Gen/assets/NativeHUD/mapgoal", "Gen/romfs_overlay",
    "Gen/romfs_overlay_variants", "Gen/romfs_overlay_astc",
    "Gen/romfs_overlay_astc_variants",
)
PROFILES = (
    ("paid-metal4", False, False),
    ("free-metal4", True, False),
    ("paid-m3", False, True),
    ("free-m3", True, True),
)


def command(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(
            f"{' '.join(args)} failed (exit {result.returncode})\n"
            f"stdout:\n{result.stdout[-3500:]}\nstderr:\n{result.stderr[-3500:]}"
        )
    return result.stdout


def staged_project(destination: Path, *, root: Path = ROOT) -> Path:
    """Copy git-tracked iOS files only: never copy local signing keys or game assets."""
    listed = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z", "--", IOS_REL.as_posix()]
    )
    names = [os.fsdecode(raw) for raw in listed.split(b"\0") if raw]
    if len(names) < 50 or "dm/ios/project.yml" not in names:
        raise RuntimeError("Expected tracked iOS project files; wrong git checkout?")
    for name in names:
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            raise RuntimeError(f"Unsafe tracked path: {name}")
        src, dst = root / rel, destination / rel
        if src.is_symlink():
            raise RuntimeError(f"Unexpected source symlink: {rel}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    ios = destination / IOS_REL
    for rel in RESOURCE_DIRS:
        directory = ios / rel
        directory.mkdir(parents=True, exist_ok=True)
        if rel not in {"Gen/src", "Gen/main"}:
            (directory / ".ci-placeholder").write_text(
                "CI fixture only; not a game asset.\n", encoding="utf-8"
            )
    (ios / "Gen/src/ci_stub.c").write_text(
        "/* CI fixture only: never ship in game builds. */\n"
        "int game2mobile_ci_stub(void) { return 0; }\n", encoding="utf-8"
    )
    (ios / "Gen/main/main.c").write_text(
        "/* CI fixture only: never ship in game builds. */\n"
        "int game2mobile_ci_entry(void) { return 0; }\n", encoding="utf-8"
    )
    (ios / "Gen/embed.S").write_text(
        "/* CI fixture only. No licensed code is embedded. */\n", encoding="utf-8"
    )
    (ios / "Gen/dm.xcconfig").write_text(
        "HEADER_SEARCH_PATHS = $(inherited)\n"
        "OTHER_CFLAGS = $(inherited)\n"
        "OTHER_LDFLAGS = $(inherited)\n", encoding="utf-8"
    )
    return ios


def variant_spec(ios: Path, *, free: bool, m3: bool) -> Path:
    original = ios / "project.yml"
    spec = original
    if free:
        spec = ios / "project_free.yml"
        command([sys.executable, "tools/project_free.py", original.name, spec.name],
                cwd=ios)
    if m3:
        output = ios / "project_m3.yml"
        args = [sys.executable, "tools/project_m3.py", spec.name, output.name]
        if free:
            args.append("free")
        command(args, cwd=ios)
        spec = output
    return spec


def json_from_output(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Expected JSON from xcodebuild: {raw[:500]}") from error


def verify_profile(ios: Path, *, name: str, free: bool, m3: bool) -> dict:
    env = os.environ.copy()
    env["DM_BUNDLE_ID"] = "com.example.game2mobile.ci"
    env["DM_TEAM_ID"] = "CI00000000"
    spec = variant_spec(ios, free=free, m3=m3)
    command(["xcodegen", "generate", "-q", "--spec", spec.name], cwd=ios, env=env)
    project = ios / "DmIOS.xcodeproj"
    if not (project / "project.pbxproj").is_file():
        raise RuntimeError(f"{name}: Xcode project file not created")

    raw_list = command(
        ["xcodebuild", "-list", "-json", "-project", str(project)], cwd=ios, env=env
    )
    details = json_from_output(raw_list)["project"]
    targets = set(details["targets"])
    expected = {"DmIOS", "TouchSmokeTests"}
    if not free and not m3:
        expected.add("RomfsDownloader")
    if targets != expected:
        raise RuntimeError(f"{name}: generated targets {sorted(targets)} != {sorted(expected)}")
    if "DmIOS" not in details["schemes"]:
        raise RuntimeError(f"{name}: missing game app scheme")

    raw_settings = command(
        ["xcodebuild", "-showBuildSettings", "-json", "-project", str(project),
         "-scheme", "DmIOS", "-configuration", "Release",
         "-sdk", "iphoneos", "CODE_SIGNING_ALLOWED=NO"],
        cwd=ios, env=env,
    )
    settings = {
        item["target"]: item["buildSettings"] for item in json_from_output(raw_settings)
    }
    app = settings.get("DmIOS")
    if not app:
        raise RuntimeError(f"{name}: missing DmIOS build settings")
    expected_os = "18.0" if m3 else "26.0"
    actual_os = app.get("IPHONEOS_DEPLOYMENT_TARGET")
    if actual_os != expected_os:
        raise RuntimeError(f"{name}: deployment target {actual_os} != {expected_os}")
    flags = app.get("OTHER_CFLAGS", "")
    expected_cpu = "-mcpu=apple-a14" if m3 else "-mcpu=apple-a18"
    if expected_cpu not in flags:
        raise RuntimeError(f"{name}: expected compiler flag {expected_cpu}, got: {flags}")
    if ("-DDM_NVN_M3=1" in flags) != m3:
        raise RuntimeError(f"{name}: Metal M3 flag does not match profile")
    if not free and not m3:
        ext = settings.get("RomfsDownloader")
        if ext is None or ext.get("IPHONEOS_DEPLOYMENT_TARGET") != "26.0":
            raise RuntimeError(f"{name}: managed asset downloader must target iOS 26.0")

    output = {
        "profile": name, "targets": sorted(targets),
        "schemes": sorted(details["schemes"]),
        "ios_deployment_target": actual_os,
        "metal_api": "M3" if m3 else "Metal4",
        "account": "free" if free else "paid",
        "cpu": expected_cpu,
        "app_bundle": app.get("PRODUCT_BUNDLE_IDENTIFIER", ""),
    }
    print(f"OK {name}: targets={','.join(sorted(targets))}, iOS={actual_os}, {expected_cpu}",
          flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Optional JSON report (no assets/secrets)")
    args = parser.parse_args()
    if not sys.platform.startswith("darwin"):
        raise SystemExit("Run this actual Xcode project validation on macOS only.")
    if shutil.which("xcodegen") is None or shutil.which("xcodebuild") is None:
        raise SystemExit("xcodegen and xcodebuild must both be available.")
    with tempfile.TemporaryDirectory(prefix="game2mobile-xcodegen-") as work:
        ios = staged_project(Path(work))
        results = [
            verify_profile(ios, name=name, free=free, m3=m3)
            for name, free, m3 in PROFILES
        ]
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps({"test_kind": "asset-free-xcodegen-generation",
                        "full_app_build": False, "profiles": results},
                       indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print("All four real XcodeGen/Xcode project configuration checks passed.")


if __name__ == "__main__":
    main()
