#!/usr/bin/env python3
"""Small, asset-free safety gates for Game2Mobile sources and release packages.

Run on Linux CI or macOS without private game files:
    python3 scripts/release_checks.py source
    python3 scripts/release_checks.py shell /path/to/Game2Mobile-shell.ipa
    python3 scripts/release_checks.py macapp /path/to/Game2Mobile.app

Shell validation is an additional guard, not a replacement for the stricter
binary/derived-content validation built into dm/ios/tools/shell_build.sh.
"""
from __future__ import annotations

import argparse
import hashlib
import plistlib
import struct
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ASSET = Path("dm/ios/Assets.xcassets/AppIcon.appiconset/AppIcon1024.png")
OLD_THIRD_PARTY_ICON = "cdf6e8838e1c453c5e91470ffeef8c1a12745d8f"


class ReleaseError(Exception):
    pass


def require(test: bool, explanation: str) -> None:
    if not test:
        raise ReleaseError(explanation)


def png_info(blob: bytes) -> tuple[int, int, int, int]:
    require(blob.startswith(b"\x89PNG\r\n\x1a\n"), "App icon: invalid PNG signature")
    require(len(blob) > 33 and blob[12:16] == b"IHDR", "App icon: IHDR missing")
    require(int.from_bytes(blob[8:12], "big") == 13, "App icon: invalid IHDR length")
    require(zlib.crc32(blob[12:29]) & 0xFFFFFFFF == int.from_bytes(blob[29:33], "big"),
            "App icon: IHDR checksum incorrect")
    return struct.unpack(">IIBB", blob[16:26])  # width, height, depth, color type


def git_blob_sha(blob: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(blob)).encode() + b"\0" + blob).hexdigest()


def check_source(root: Path = ROOT) -> None:
    core = (
        "dm/PRODUCT", "dm/tools/patch_nso.py", "dm/host/loader.c", "dm/host/main.c",
        "dm/gfx/nvn/nvn_mtl.m", "dm/ios/project.yml", "dm/tools/mac_app.sh",
        "dm/ios/tools/shell_build.sh", "assets/brand/game2mobile-icon.svg",
        "scripts/render_app_icon.py", "LICENSE",
    )
    for rel in core:
        require((root / rel).is_file(), f"Source file missing: {rel}")
    img_path = root / ASSET
    require(img_path.is_file(), f"App icon missing: {ASSET}")
    content = img_path.read_bytes()
    require(png_info(content) == (1024, 1024, 8, 2),
            "App icon must be an opaque 1024×1024 8-bit RGB PNG (no transparency)")
    require(git_blob_sha(content) != OLD_THIRD_PARTY_ICON,
            "Original game's old icon is still packaged; replace it with the independent brand")
    project = (root / "dm/ios/project.yml").read_text(encoding="utf-8")
    require("CFBundleDisplayName: Game2Mobile" in project, "iOS display name is incorrect")
    mac_builder = (root / "dm/tools/mac_app.sh").read_text(encoding="utf-8")
    require("CFBundleIconFile</key><string>Game2Mobile.icns" in mac_builder,
            "Mac app is missing a CFBundleIconFile declaration")
    require("iconutil -c icns" in mac_builder, "Mac icon generation is missing")
    require("Game2Mobile" in (root / "README.md").read_text(encoding="utf-8"),
            "English README is missing the project name")
    print("OK: source tree, independent RGB icon, iOS/macOS brand configuration")


SHELL_BANNED_PREFIXES = (
    "dm/romfs/", "msl/", "romfs_overlay/", "romfs_overlay_variants/",
    "hud_v4_ui/", "mapgoal/", "save_ref/", "save_ref_warlock/",
    "Frameworks/Guest.framework/", "romfs_overlay_astc/",
    "romfs_overlay_astc_variants/",
)
SHELL_BANNED_EXACT = (
    "dm/derived.tsv", "dm/main.patched.bin", "dm/sdk.patched.bin",
    "dm/subsdk0.patched.bin", "dm/bootlist.tsv", "native_art_manifest.json",
)


def check_shell_ipa(path: Path) -> None:
    require(path.is_file(), f"IPA does not exist: {path}")
    require(zipfile.is_zipfile(path), "Shell is not a valid ZIP/IPA")
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        require(names, "Shell IPA is empty")
        for name in names:
            p = PurePosixPath(name)
            require(not name.startswith("/") and ".." not in p.parts and "\\" not in name,
                    f"Invalid IPA path: {name}")
        plist_entries = [n for n in names if len(PurePosixPath(n).parts) == 3
                         and n.startswith("Payload/") and n.endswith(".app/Info.plist")]
        require(len(plist_entries) == 1, "Expected exactly one Payload/*.app/Info.plist")
        prefix = plist_entries[0][:-len("Info.plist")]
        require(all(n.startswith(prefix) for n in names),
                "Unexpected content outside the single App payload")
        info = plistlib.loads(archive.read(plist_entries[0]))
        require(info.get("CFBundleDisplayName") == "Game2Mobile",
                "Game2Mobile app display name missing in shell Info.plist")
        require((prefix + "dm/shell_manifest.txt") in names, "Shell manifest is missing")
        require((prefix + "dm/shell_info.txt") in names, "Shell version metadata is missing")
        forbidden: list[str] = []
        for name in names:
            rel = name[len(prefix):]
            if rel in SHELL_BANNED_EXACT or any(rel.startswith(p) for p in SHELL_BANNED_PREFIXES):
                forbidden.append(rel)
            if rel.startswith("dm_native_") and rel.endswith(".png"):
                forbidden.append(rel)
            if rel.lower().endswith(('.nso', '.nsp', '.xci', '.metallib')):
                forbidden.append(rel)
        require(not forbidden, "Commercial-game-derived content may be in shell: " + ", ".join(forbidden[:8]))
        print(f"OK: {path.name} / {len(names)} files / game-free shell structure, brand, metadata")


def check_macapp(path: Path) -> None:
    plist = path / "Contents/Info.plist"
    require(plist.is_file(), "macOS Info.plist missing")
    info = plistlib.loads(plist.read_bytes())
    require(info.get("CFBundleName", "").startswith("Game2Mobile"), "macOS CFBundleName incorrect")
    require(info.get("CFBundleDisplayName", "").startswith("Game2Mobile"),
            "macOS CFBundleDisplayName incorrect")
    require(info.get("CFBundleIconFile") == "Game2Mobile.icns", "macOS icon reference incorrect")
    icon = path / "Contents/Resources/Game2Mobile.icns"
    require(icon.is_file() and icon.read_bytes().startswith(b"icns"), "macOS .icns missing or invalid")
    executable = path / "Contents/MacOS" / info.get("CFBundleExecutable", "")
    require(executable.is_file(), "macOS executable missing")
    print(f"OK: macOS app name, executable, icon and Info.plist ({path})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("source", "shell", "macapp"))
    parser.add_argument("path", type=Path, nargs="?", help="IPA path or .app folder")
    args = parser.parse_args()
    try:
        if args.mode == "source":
            require(args.path is None, "source mode does not take an artifact path")
            check_source()
        else:
            require(args.path is not None, f"{args.mode} mode requires an artifact path")
            if args.mode == "shell":
                check_shell_ipa(args.path)
            else:
                check_macapp(args.path)
    except (ReleaseError, plistlib.InvalidFileException, OSError, zipfile.BadZipFile) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
