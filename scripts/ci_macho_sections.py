#!/usr/bin/env python3
"""Asset-free integration of Game2Mobile's Mach-O section parser with Apple otool.

Creates a harmless, temporary ARM64 .o with the same SECTION NAMES as
gen_embed.py. NO game bytes are embedded, no App is linked or signed, and
passing this check is NOT an actual game build or a playable release.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import re
import sys

from m1_game_bundle import BundleValidationError, require_guest_sections


def run() -> int:
    if sys.platform != "darwin":
        print("Apple Mach-O integration requires macOS")
        return 2
    with tempfile.TemporaryDirectory(prefix="g2m-section-validator-") as work:
        root = Path(work)
        asm = root / "fake-sections.S"
        obj = root / "fake-sections.o"
        lines = ["// Test-only anonymous Mach-O sections; no proprietary assets."]
        for module in ("main", "sdk"):
            for suffix in ("x0", "x1"):
                lines.extend([
                    f".section __TEXT,__dm{module}{suffix},regular,pure_instructions",
                    ".p2align 14",
                    ".space 16384",
                ])
            lines.extend([
                f".section __DM{module}W,__img",
                ".p2align 14",
                ".space 16384",
            ])
        asm.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sdk = subprocess.check_output(
            ["xcrun", "--sdk", "iphoneos", "--show-sdk-path"],
            text=True,
        ).strip()
        subprocess.run([
            "xcrun", "--sdk", "iphoneos", "clang",
            "-target", "arm64-apple-ios26.0", "-isysroot", sdk,
            "-c", str(asm), "-o", str(obj),
        ], check=True, capture_output=True, text=True)
        arch = subprocess.check_output(["lipo", "-archs", str(obj)], text=True).strip()
        if arch != "arm64":
            raise RuntimeError("Fixture object was not ARM64")
        listing = subprocess.check_output(["otool", "-l", str(obj)], text=True)
        required = require_guest_sections(listing)
        if set(required) != {"main", "sdk"}:
            raise RuntimeError("Guest sections not recognized by real Apple otool output")
        # Validate the parser actually rejects misplaced sections.
        tampered, replaced = re.subn(
            r"(?m)(sectname[ \t]+__dmmainx0\n[ \t]*segname[ \t]+)__TEXT",
            r"\g<1>__DATA",
            listing, count=1,
        )
        if replaced != 1:
            # Real Apple formatting can vary; require an actual recognized
            # section to be rewritten instead of silently skipping this test.
            raise RuntimeError("Fixture section layout format changed")
        try:
            require_guest_sections(tampered)
        except BundleValidationError:
            pass
        else:
            raise RuntimeError("Incorrect segment unexpectedly passed verification")
    print("Apple ARM64 Mach-O and real otool section parsing passed (fixture only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
