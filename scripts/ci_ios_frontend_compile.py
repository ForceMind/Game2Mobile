#!/usr/bin/env python3
"""Compile EVERY tracked Game2Mobile iOS frontend translation unit with Apple Clang.

Use an Apple Silicon Mac with Xcode; no Nintendo Switch game data, provisioning,
generated graphics, guest binary, or compiler-linking steps are required.

python3 scripts/ci_ios_frontend_compile.py --profile metal4 \
    --report /tmp/g2m-ios26-frontend.json --strict
python3 scripts/ci_ios_frontend_compile.py --profile m3 \
    --report /tmp/g2m-ios18-frontend.json --strict

This validates frontend ARM64 Mach-O object code only, NOT a full linked game,
a signed iPhone app, a runnable simulator app, or real-device behavior.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "dm/ios/Sources"
PROFILES = {
    "metal4": ("arm64-apple-ios26.0", "apple-a18", ()),
    "m3": ("arm64-apple-ios18.0", "apple-a14", ("-DDM_NVN_M3=1",)),
}
EXPECTED_CORE = frozenset({
    "DmTouchOverlay.m", "asset_dl.m", "cloud_ios.m", "dm_gamepad.m",
    "dm_shader_prep.m", "dm_touch_controls.c",
    "dm_touch_game_bridge.c", "front_ios.m", "main.m",
})
EXTENSIONS = frozenset({".c", ".m", ".mm", ".cc", ".cpp"})


class FrontendCompileError(RuntimeError):
    """The public source inventory was incomplete or unsafe."""


def tracked_sources(root: Path = ROOT) -> list[Path]:
    """Only compile tracked source files; ignored game-derived files stay out."""
    output = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "dm/ios/Sources"],
        check=True, capture_output=True,
    ).stdout
    names = [os.fsdecode(item) for item in output.split(b"\x00") if item]
    result: list[Path] = []
    for name in names:
        relative = Path(name)
        if relative.suffix not in EXTENSIONS:
            continue
        path = root / relative
        if (not path.is_file() or path.is_symlink()
                or not path.resolve().is_relative_to((root / "dm/ios/Sources").resolve())):
            raise FrontendCompileError("Invalid tracked iOS source entry")
        result.append(path)
    result.sort(key=lambda x: x.name)
    actual = {path.name for path in result}
    missing = EXPECTED_CORE - actual
    if missing or len(result) < 17 or len(actual) != len(result):
        raise FrontendCompileError(
            "Tracked iOS frontend inventory is incomplete or ambiguous"
        )
    return result


def command_for_source(
    source: Path, output: Path, *, target: str, cpu: str, flags: tuple[str, ...],
    sdk: str, root: Path = ROOT,
) -> list[str]:
    """Use the real project CPU/Metal selection and iPhoneOS SDK."""
    cmd = [
        "xcrun", "--sdk", "iphoneos", "clang",
        "-target", target, "-isysroot", sdk, "-mcpu=" + cpu,
        "-O0", "-c", "-o", str(output),
    ]
    if source.suffix == ".c":
        cmd.append("-std=gnu11")
    elif source.suffix in {".m", ".mm"}:
        cmd.extend(["-fobjc-arc", "-fmodules"])
    elif source.suffix in {".cpp", ".cc"}:
        cmd.append("-std=gnu++17")
    cmd.extend(flags)
    for directory in (
        "dm/ios/Sources", "dm/host", "dm/gfx/nvn", "dm/gfx/nvn/include",
    ):
        cmd.extend(["-I", str(root / directory)])
    cmd.append(str(source))
    return cmd


def redact(stderr: str, root: Path = ROOT) -> str:
    """Keep issue details while avoiding local absolute paths in reports."""
    text = stderr.replace(str(root.resolve()), "<source>")
    lines = [
        line.strip() for line in text.splitlines()
        if re.search(r"(?:fatal )?error:|file not found|unsupported|unknown type", line)
    ]
    return " | ".join(lines[:3])[:500] if lines else text.strip()[-400:]


def compile_profile(profile: str, sources: list[Path], output_dir: Path) -> dict:
    if profile not in PROFILES:
        raise FrontendCompileError("Unknown Apple iOS frontend profile")
    target, cpu, flags = PROFILES[profile]
    sdk = subprocess.check_output(
        ["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True
    ).strip()
    if not Path(sdk).is_dir():
        raise FrontendCompileError("Real iPhoneOS SDK is missing")
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for source in sources:
        obj = output_dir / (source.stem + "_" + source.suffix[1:] + ".o")
        args = command_for_source(
            source, obj, target=target, cpu=cpu, flags=flags, sdk=sdk,
        )
        try:
            run = subprocess.run(
                args, cwd=ROOT, capture_output=True, text=True, timeout=120
            )
            succeeded = run.returncode == 0 and obj.is_file()
            note = redact(run.stderr) if not succeeded else ""
        except subprocess.TimeoutExpired:
            succeeded, note = False, "Apple Clang compilation timed out"
        if succeeded:
            architecture = subprocess.run(
                ["lipo", "-archs", str(obj)], capture_output=True, text=True,
                timeout=20,
            )
            if architecture.returncode or architecture.stdout.strip() != "arm64":
                succeeded, note = False, "Compiled object is not ARM64 Mach-O"
        results.append({
            "path": source.relative_to(ROOT).as_posix(),
            "status": "compiled" if succeeded else "compile_error",
            **({"diagnostic": note} if note else {}),
        })
        print(
            ("PASS " if succeeded else "FAIL ") + source.name,
            flush=True,
        )
    summary = Counter(r["status"] for r in results)
    return {
        "profile": profile,
        "target": target,
        "source_units": len(results),
        "compiled_arm64_objects": summary["compiled"],
        "compile_errors": summary["compile_error"],
        "generated_private_sources_included": False,
        "full_game_target_linked": False,
        "real_device_tested": False,
        "sources": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires an actual Apple SDK on macOS")
    sources = tracked_sources()
    with tempfile.TemporaryDirectory(prefix="game2mobile-frontend-") as temp:
        report = compile_profile(args.profile, sources, Path(temp))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"{args.profile}: {report['compiled_arm64_objects']}/"
        f"{report['source_units']} Apple ARM64 source compilations; "
        f"{report['compile_errors']} errors",
        flush=True,
    )
    if args.strict and report["compile_errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
