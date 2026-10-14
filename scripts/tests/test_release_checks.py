"""Offline regression for the source and game-free release artifact gates."""
from __future__ import annotations

from pathlib import Path
import plistlib
import tempfile
import unittest
import zipfile

from scripts.release_checks import (
    ReleaseError,
    check_macapp,
    check_shell_ipa,
    check_source,
    png_info,
)


def fake_shell(path: Path, *, extra: tuple[str, ...] = (), display: str = "Game2Mobile") -> None:
    info = plistlib.dumps({"CFBundleDisplayName": display, "CFBundleExecutable": "DmIOS"})
    with zipfile.ZipFile(path, "w") as z:
        root = "Payload/DmIOS.app/"
        z.writestr(root + "Info.plist", info)
        z.writestr(root + "DmIOS", b"fake executable")
        z.writestr(root + "dm/shell_manifest.txt", "dm/derived.tsv\n")
        z.writestr(root + "dm/shell_info.txt", "PRODUCT=3.3.94012-r44\n")
        for e in extra:
            z.writestr(root + e, b"fake data")


class ReleaseChecksTest(unittest.TestCase):
    def test_source_tree_and_icon(self):
        check_source()

    def test_png_is_rgb(self):
        asset = Path(__file__).resolve().parents[2] / (
            "dm/ios/Assets.xcassets/AppIcon.appiconset/AppIcon1024.png"
        )
        self.assertEqual(png_info(asset.read_bytes()), (1024, 1024, 8, 2))

    def test_fake_good_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Game2Mobile-shell.ipa"
            fake_shell(path)
            check_shell_ipa(path)

    def test_shell_rejects_game_derived_files(self):
        bad_files = (
            "msl/b-something/0.metallib", "dm/main.patched.bin",
            "Frameworks/Guest.framework/Guest", "romfs_overlay/cache.dat",
            "dm/derived.tsv", "dm_native_mana.png", "assets/game.nso",
        )
        with tempfile.TemporaryDirectory() as tmp:
            for i, file in enumerate(bad_files):
                path = Path(tmp) / f"bad-{i}.ipa"
                fake_shell(path, extra=(file,))
                with self.subTest(file=file), self.assertRaises(ReleaseError):
                    check_shell_ipa(path)

    def test_shell_rejects_wrong_brand(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-brand.ipa"
            fake_shell(path, display="Other App")
            with self.assertRaises(ReleaseError):
                check_shell_ipa(path)

    def test_shell_rejects_zip_slip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traversal.ipa"
            fake_shell(path)
            with zipfile.ZipFile(path, "a") as z:
                z.writestr("../outside.txt", "unsafe")
            with self.assertRaises(ReleaseError):
                check_shell_ipa(path)

    def test_mac_app_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Game2Mobile.app"
            (root / "Contents/Resources").mkdir(parents=True)
            (root / "Contents/MacOS").mkdir(parents=True)
            plist = {
                "CFBundleName": "Game2Mobile", "CFBundleDisplayName": "Game2Mobile",
                "CFBundleExecutable": "Game2Mobile", "CFBundleIconFile": "Game2Mobile.icns",
            }
            (root / "Contents/Info.plist").write_bytes(plistlib.dumps(plist))
            (root / "Contents/Resources/Game2Mobile.icns").write_bytes(b"icns\0\0\0\x08")
            (root / "Contents/MacOS/Game2Mobile").write_bytes(b"fake executable")
            check_macapp(root)
            (root / "Contents/Resources/Game2Mobile.icns").unlink()
            with self.assertRaises(ReleaseError):
                check_macapp(root)


if __name__ == "__main__":
    unittest.main()
