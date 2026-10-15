#!/usr/bin/env python3
"""Compile REAL Game2Mobile host Makefile sources against the iOS Apple SDK.

By default this is an asset-free object compilation inventory. With the explicit
--private-derived-headers flag, a local owner can privately verify all 91/91
units using exactly three headers legally generated from their own game RomFS.
No proprietary headers, executables, or private data enter a GitHub artifact.

On macOS with Xcode:
    python3 scripts/ci_production_compile.py --profiles metal4,m3 \
      --report /tmp/g2m-production-compile.json

A green non-strict audit means baseline modules compiled and every source was
classified. It does NOT mean zero compilation errors, a linked game or an IPA.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

from ci_xcodegen_profiles import staged_project
from private_build_inputs import (
    private_output_is_safe, stage_private_headers, PrivateInputError,
)

PROFILES = {
    "metal4": ("arm64-apple-ios26.0", "apple-a18", ()),
    "m3": ("arm64-apple-ios18.0", "apple-a14", ("-DDM_NVN_M3=1",)),
}
GAME_DERIVED_INCLUDES = frozenset({
    "dm_vault_tab.h", "dm_hud_exp.h", "dm_bright_levels.inc",
    "dm_touch_native_art.c", "dm_touch_native_art.h",
})
# These three translation units have already compiled on Apple's own
# iPhoneOS toolchain in earlier CI. Catch regressions unconditionally.
MANDATORY = frozenset({"host/loader.c", "host/main.c", "gfx/nvn/nvn_mtl.m"})
# First real Apple compile sweep identified exactly these three units as
# legitimately requiring game-derived private headers. New missing headers
# elsewhere are regressions until explicitly reviewed and classified.
KNOWN_GENERATED_BLOCKS = frozenset({
    "host/diag.c", "host/dm_bright.c", "host/dm_vault_ui.c",
})


def parse_header_paths(xcconfig: str) -> list[str]:
    line = next((s for s in xcconfig.splitlines()
                 if s.startswith("HEADER_SEARCH_PATHS = ")), None)
    if line is None:
        raise ValueError("Missing host HEADER_SEARCH_PATHS in gen_build output")
    paths = shlex.split(line.partition("=")[2])
    return list(dict.fromkeys(p for p in paths if p != "$(inherited)"))


def compile_status(returncode: int, message: str) -> str:
    if returncode == 0:
        return "compiled"
    # Only a *direct* failure to locate a known game-generated dependency is
    # expected without RomFS. Everything else is a real compiler error.
    missing = re.findall(
        r"(?:fatal error|error):\s*['<]([^'>]+)[>']\s+file not found",
        message, flags=re.IGNORECASE,
    )
    if any(Path(value).name in GAME_DERIVED_INCLUDES for value in missing):
        return "blocked_generated_asset"
    return "compile_error"


def origin_for(link: Path, dm: Path) -> str:
    resolved = link.resolve(strict=True)
    if not resolved.is_relative_to(dm.resolve()):
        raise ValueError(f"Generated source escapes private staging: {link.name}")
    return resolved.relative_to(dm.resolve()).as_posix()


def summarize_diagnostic(stderr: str, stage: Path, root: Path) -> str:
    text = stderr.replace(str(stage.resolve()), "<isolated>")
    text = text.replace(str(stage), "<isolated>")
    text = text.replace(str(root.resolve()), "<repo>")
    lines = [x.strip() for x in text.splitlines()
             if "error:" in x.lower() or "warning:" in x.lower()
             or "file not found" in x.lower()]
    return " | ".join(lines[:3])[:700] or text.strip().split("\n")[-1][:700]


def compile_inventory(staged: Path, targets: list[str], output: Path) -> dict:
    ios, dm = staged / "dm/ios", staged / "dm"
    include_paths = parse_header_paths(
        (ios / "Gen/dm.xcconfig").read_text(encoding="utf-8")
    )
    sources = sorted((ios / "Gen/src").iterdir()) + [ios / "Gen/main/main.c"]
    origins = [origin_for(link, dm) for link in sources]
    if len(sources) < 85 or len(set(origins)) != len(origins):
        raise ValueError("Unexpected source coverage or duplicate real sources")

    sysroot = subprocess.check_output(
        ["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True
    ).strip()
    if not Path(sysroot).is_dir():
        raise RuntimeError("Apple iPhoneOS SDK not found")
    output.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []
    for name in targets:
        target, cpu, extra = PROFILES[name]
        object_dir = output / name
        object_dir.mkdir(exist_ok=True)
        compiled = Counter()
        for link, origin in zip(sources, origins):
            suffix = link.suffix
            if suffix not in {".c", ".m", ".S"}:
                raise ValueError(f"Unexpected generated source type {origin}")
            obj = object_dir / (link.name.replace(".", "_") + ".o")
            args = [
                "xcrun", "--sdk", "iphoneos", "clang",
                "-target", target, "-isysroot", sysroot,
                "-mcpu=" + cpu, "-O0", "-c", "-o", str(obj),
            ]
            if suffix == ".c":
                args.append("-std=gnu11")
            if suffix == ".m":
                args.append("-fobjc-arc")
            args.extend(extra)
            if origin == "host/main.c":
                args.append("-Dmain=dm_main")
            for p in include_paths:
                args.extend(["-I", p])
            args.append(str(link))
            try:
                run = subprocess.run(
                    args, cwd=ios, capture_output=True, text=True, timeout=80
                )
                status = compile_status(run.returncode, run.stderr)
                reason = summarize_diagnostic(run.stderr, staged, staged) if status != "compiled" else ""
            except subprocess.TimeoutExpired:
                status, reason = "compile_error", "Apple clang timeout (80 seconds)"
            if status == "compiled":
                arch = subprocess.run(
                    ["lipo", "-archs", str(obj)], capture_output=True, text=True
                )
                if arch.returncode or arch.stdout.strip() != "arm64":
                    status, reason = "compile_error", "Object was not ARM64 Mach-O"
            compiled[status] += 1
            reports.append({
                "profile": name, "source": origin, "status": status,
                **({"diagnostic": reason} if reason else {}),
            })
        print(
            f"{name}: {compiled['compiled']} ARM64 object files; "
            f"{compiled['blocked_generated_asset']} generated-asset blocks; "
            f"{compiled['compile_error']} other compiler errors",
            flush=True,
        )

    summary = {
        "verification": "real-tracked-host-source-apple-arm64-object-inventory",
        "full_app_linked": False,
        "game_assets_used": False,
        "device_or_simulator_tested": False,
        "mandatory_sources": sorted(MANDATORY),
        "sources_per_profile": len(sources),
        "profiles": {},
        "files": reports,
    }
    failed_mandatory = []
    for name in targets:
        subset = [e for e in reports if e["profile"] == name]
        summary["profiles"][name] = dict(Counter(x["status"] for x in subset))
        for source in MANDATORY:
            if not any(e["source"] == source and e["status"] == "compiled"
                       for e in subset):
                failed_mandatory.append(f"{name}:{source}")
    summary["mandatory_compilation_regressions"] = failed_mandatory
    blocked = {
        x["source"] for x in reports
        if x["status"] == "blocked_generated_asset"
    }
    summary["unreviewed_generated_asset_blocks"] = sorted(
        blocked - KNOWN_GENERATED_BLOCKS
    )
    summary["expected_game_derived_header_blockers"] = sorted(
        KNOWN_GENERATED_BLOCKS
    )
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profiles", default="metal4",
                   help="Comma-separated profile names: metal4,m3")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--strict", action="store_true",
                   help="also fail for any unclassified compiler error")
    p.add_argument("--private-derived-headers", type=Path,
                   help="locally generated owner-only headers in dm/host; NEVER for CI")
    args = p.parse_args()
    profiles = args.profiles.split(",")
    if not profiles or len(profiles) != len(set(profiles)) or any(
        name not in PROFILES for name in profiles
    ):
        p.error("Expected unique profiles from metal4,m3")
    if sys.platform != "darwin":
        p.error("Requires actual Apple SDK on macOS")
    if args.private_derived_headers is not None:
        if not private_output_is_safe(args.report, ROOT):
            p.error("Private-mode reports must be written outside the Git repository")
        if not args.strict:
            p.error("Private-header mode requires --strict for exact 91/91 verification")

    with tempfile.TemporaryDirectory(prefix="game2mobile-source-compile-") as temp:
        stage = Path(temp) / "sources"
        stage.mkdir()
        ios = staged_project(stage)
        # The source inventory itself remains git-tracked and unmodified.
        # The owner may inject *only* three legally generated local headers,
        # copied to this isolated temp tree, never to the public Git checkout.
        if args.private_derived_headers is not None:
            try:
                stage_private_headers(args.private_derived_headers, stage / "dm")
            except PrivateInputError as exc:
                p.error(str(exc))
        report = compile_inventory(stage, profiles, Path(temp) / "objects")
        if args.private_derived_headers is not None:
            # Do not put snippets from any private data/header in reports.
            for item in report["files"]:
                if "diagnostic" in item:
                    item["diagnostic"] = (
                        "Compiler failure; inspect original local-only build context"
                    )
            report["game_assets_used"] = True
            report["private_generated_headers_used"] = True
            report["expected_game_derived_header_blockers"] = []
        else:
            report["private_generated_headers_used"] = False
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"Saved codegen inventory: {args.report}", flush=True)
    bad = report["mandatory_compilation_regressions"]
    if bad:
        print("Previously-proven production modules regressed: " + ", ".join(bad),
              file=sys.stderr)
        return 1
    if args.strict:
        if report["unreviewed_generated_asset_blocks"]:
            print("Unreviewed new generated-asset blocks: " + ", ".join(
                report["unreviewed_generated_asset_blocks"]), file=sys.stderr
            )
            return 1
        if any(x.get("compile_error", 0)
               for x in report["profiles"].values()):
            print("Strict compile sweep detected unresolved source errors",
                  file=sys.stderr)
            return 1
        if args.private_derived_headers is not None:
            for name in profiles:
                count = report["profiles"][name].get("compiled", 0)
                if count != report["sources_per_profile"]:
                    print(f"{name}: private headers supplied but only "
                          f"{count}/{report['sources_per_profile']} sources compiled",
                          file=sys.stderr)
                    return 1
    print(
        "Baseline OK. This is a compilation inventory: "
        "see JSON for all blocks/errors; full game linking was NOT attempted.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
