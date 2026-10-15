"""Regression: XcodeGen CI staging must never copy untracked game/user data."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.ci_xcodegen_profiles import RESOURCE_DIRS, staged_project


class XcodeGenIsolationTest(unittest.TestCase):
    def test_git_tracked_inputs_only_and_asset_free_placeholders(self):
        with tempfile.TemporaryDirectory(prefix="g2m-xcodegen-test-") as temp:
            base = Path(temp)
            root = base / "repo"
            src = root / "dm/ios"
            src.mkdir(parents=True)
            (src / ".gitignore").write_text(
                "local.env\nGen/\nproject_free.yml\nproject_m3.yml\n",
                encoding="utf-8",
            )
            (src / "project.yml").write_text(
                "name: DmIOS\n", encoding="utf-8"
            )
            # Enough git-tracked fixtures to exercise the same path as CI.
            for i in range(56):
                entry = src / "Sources" / f"tracked_{i}.txt"
                entry.parent.mkdir(parents=True, exist_ok=True)
                entry.write_text("Public source fixture\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)

            # Simulate developer-only data that must never enter a generated
            # XcodeGen report or isolated CI staging directory.
            (src / "local.env").write_text("DM_TEAM_ID=SECRET\n", encoding="utf-8")
            private = src / "Gen/romfs_overlay/secret_game_asset.data"
            private.parent.mkdir(parents=True, exist_ok=True)
            private.write_bytes(b"do-not-copy-private-game-data")
            untracked = src / "Sources/local_credential.txt"
            untracked.write_text("DO_NOT_COPY_ME", encoding="utf-8")
            staged = staged_project(base / "isolated", root=root, use_makefile_sources=False)
            self.assertEqual((staged / "project.yml").read_text(), "name: DmIOS\n")
            self.assertFalse((staged / "local.env").exists())
            self.assertFalse((staged / "Sources/local_credential.txt").exists())
            self.assertFalse((staged / "Gen/romfs_overlay/secret_game_asset.data").exists())
            self.assertIn("CI fixture", (staged / "Gen/src/ci_stub.c").read_text())
            self.assertIn("CI fixture", (staged / "Gen/embed.S").read_text())
            for path in RESOURCE_DIRS:
                self.assertTrue((staged / path).is_dir(), path)


if __name__ == "__main__":
    unittest.main()
