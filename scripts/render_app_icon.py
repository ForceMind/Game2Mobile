#!/usr/bin/env python3
"""Render the independent Game2Mobile brand icon to the iOS asset catalog.

Source of truth: assets/brand/game2mobile-icon.svg.
Requires CairoSVG and Pillow (only when re-rendering; not for regular Xcode builds).
Run: python3 scripts/render_app_icon.py [--check]
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/brand/game2mobile-icon.svg"
OUTPUT = ROOT / "dm/ios/Assets.xcassets/AppIcon.appiconset/AppIcon1024.png"


def render() -> bytes:
    import cairosvg
    from PIL import Image

    data = cairosvg.svg2png(url=str(SOURCE), output_width=1024, output_height=1024)
    with Image.open(io.BytesIO(data)) as img:
        if img.size != (1024, 1024):
            raise RuntimeError("App icon must be 1024×1024")
        rgb = Image.new("RGB", img.size, (10, 24, 34))
        rgb.paste(img, mask=img.getchannel("A") if img.mode == "RGBA" else None)
        buf = io.BytesIO()
        rgb.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the existing icon differs from the SVG")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_bytes() != expected:
            raise SystemExit("App icon is missing or stale; run python3 scripts/render_app_icon.py")
        print("Game2Mobile AppIcon1024.png is current (opaque RGB, 1024×1024)")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(expected)
    print(f"Rendered {OUTPUT.relative_to(ROOT)} ({len(expected):,} bytes)")


if __name__ == "__main__":
    main()
