#!/usr/bin/env python3
"""Validate the *actual* Game2Mobile shader map and owner's iOS shader cache.

No game files are downloaded or uploaded. Source mode checks only tracked
metadata and works on Linux CI. Cache mode runs on the owner's Mac after
the legitimately derived shader libraries have been generated.

Examples:
    python3 scripts/m1_shader_inventory.py source
    python3 scripts/m1_shader_inventory.py cache \
        --ios-root ~/dm-work/build/ios/dmsh_b \
        --mac-marker ~/dm-work/build/cache/metal_shader_cache/b-V/_b_build.json

A passing cache check proves that all mapped shader-key libraries/reflections
are present, not that the actual DmIOS App has been linked or launched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

try:
    from .m1_game_bundle import (
        BundleValidationError, expected_shader_chain, seed_shader_keys,
        shader_keys_from_map,
    )
except ImportError:  # Standalone script invoked from repository root.
    from m1_game_bundle import (
        BundleValidationError, expected_shader_chain, seed_shader_keys,
        shader_keys_from_map,
    )

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "dm/gfx/nvn/shader_map.tsv"
PSO = ROOT / "dm/gfx/nvn/pso_manifest.tsv"
CHAIN = ROOT / "dm/gfx/nvn/dmsh_chain.h"


class ShaderInventoryError(ValueError):
    """A required shader source or privately generated output is inconsistent."""


def safe_read(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            raise ShaderInventoryError("Required shader metadata is absent or symlinked")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ShaderInventoryError("Cannot read tracked shader metadata") from exc


def inspect_source(
    map_file: Path = MAP, pso_file: Path = PSO, chain_file: Path = CHAIN
) -> tuple[set[str], set[str], str]:
    """Read all unique keys from the genuine tracked map, never a fake count."""
    try:
        mapped = shader_keys_from_map(safe_read(map_file))
        seeds = seed_shader_keys(safe_read(pso_file))
        chain = expected_shader_chain(chain_file)
    except BundleValidationError as exc:
        raise ShaderInventoryError(str(exc)) from exc
    if not seeds.issubset(mapped):
        raise ShaderInventoryError(
            "PSO warmup seeds are absent from the tracked shader mapping"
        )
    return mapped, seeds, chain


def inspect_cache(
    map_file: Path, pso_file: Path, chain_file: Path,
    ios_root: Path, mac_marker: Path,
) -> dict[str, int | str | bool]:
    """Require a complete marker AND complete paired iPhoneOS shader outputs.

    Never copy shaders or embed their keys in output reports. A successful
    process exit from the original translator alone is insufficient.
    """
    mapped, seeds, chain = inspect_source(map_file, pso_file, chain_file)
    ios_root = ios_root.expanduser()
    library_dir = ios_root / ("b-" + chain)
    if (ios_root.is_symlink() or library_dir.is_symlink()
            or not library_dir.is_dir()):
        raise ShaderInventoryError("Current-version iOS shader cache directory missing")

    try:
        if mac_marker.is_symlink() or not mac_marker.is_file():
            raise ShaderInventoryError("Shader translator completion marker missing")
        rows = json.loads(mac_marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ShaderInventoryError("Unreadable shader translation completion marker") from exc
    if not isinstance(rows, list) or not rows:
        raise ShaderInventoryError("Shader translation completion marker has no entries")
    completed: set[str] = set()
    duplicate = invalid = unfinished = 0
    for row in rows:
        if not isinstance(row, dict):
            invalid += 1
            continue
        key = row.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{16}", key):
            invalid += 1
            continue
        if key in completed:
            duplicate += 1
        completed.add(key)
        if row.get("st") != "ok":
            unfinished += 1
    if (invalid or duplicate or unfinished
            or completed != mapped):
        raise ShaderInventoryError(
            "Incomplete shader translation marker: "
            f"{len(mapped - completed)} missing mapped keys, "
            f"{len(completed - mapped)} unexpected keys, "
            f"{unfinished} unfinished, {duplicate} duplicates, {invalid} invalid"
        )

    missing_lib = missing_refl = mismatched = 0
    for key in mapped:
        library = library_dir / (key + "_b.metallib")
        reflection = library_dir / (key + "_b.json")
        if (not library.is_file() or library.is_symlink()
                or library.stat().st_size == 0):
            missing_lib += 1
        if (not reflection.is_file() or reflection.is_symlink()
                or reflection.stat().st_size == 0):
            missing_refl += 1
            continue
        try:
            record = json.loads(reflection.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            mismatched += 1
            continue
        if (not isinstance(record, dict)
                or record.get("chain") != chain
                or record.get("key") != key + "_b"
                or record.get("route") != "B"):
            mismatched += 1
    if missing_lib or missing_refl or mismatched:
        raise ShaderInventoryError(
            "Incomplete iPhoneOS cache: "
            f"{missing_lib} missing Metal libraries, "
            f"{missing_refl} missing reflection JSON files, "
            f"{mismatched} inconsistent reflections "
            f"for {len(mapped)} mapped keys"
        )
    return {
        "mapped_shader_keys": len(mapped),
        "pso_warmup_shader_keys": len(seeds),
        "mac_translation_entries": len(rows),
        "ios_paired_shader_libraries": len(mapped),
        "translation_chain": chain,
        "private_shader_data_uploaded": False,
        "real_game_app_linked": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("source", "cache"))
    parser.add_argument("--map", type=Path, default=MAP)
    parser.add_argument("--pso", type=Path, default=PSO)
    parser.add_argument("--chain-header", type=Path, default=CHAIN)
    parser.add_argument("--ios-root", type=Path)
    parser.add_argument("--mac-marker", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        if args.mode == "source":
            mapped, seeds, chain = inspect_source(
                args.map, args.pso, args.chain_header
            )
            result = {
                "mapped_shader_keys": len(mapped),
                "pso_warmup_shader_keys": len(seeds),
                "translation_chain": chain,
                "real_game_app_linked": False,
            }
        else:
            if args.ios_root is None or args.mac_marker is None:
                parser.error("cache mode requires --ios-root and --mac-marker")
            result = inspect_cache(
                args.map, args.pso, args.chain_header,
                args.ios_root, args.mac_marker,
            )
    except ShaderInventoryError as exc:
        if not args.quiet:
            print(f"Shader preflight failed: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
