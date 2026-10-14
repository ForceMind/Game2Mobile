#!/usr/bin/env python3
"""Import the exact source snapshot supplied by the user, then apply Game2Mobile branding.

One-time bootstrap helper. It will refuse an archive whose Git tree differs
from the tree independently reconstructed from d2r-mobile-main.zip.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/jhaizhou-ops/d2r-mobile"
SOURCE_SHA = "685d3ddef8bf75768fd4c51228566f2e8d2a5182"
SOURCE_TREE = "59ab9da0b9726a699d7e45a855ea4cf5c0ee00a2"
EXPECTED_FILES = 1024


def cmd(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def import_source():
    url = "https://codeload.github.com/jhaizhou-ops/d2r-mobile/zip/" + SOURCE_SHA
    request = urllib.request.Request(url, headers={"User-Agent": "Game2Mobile-bootstrap/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        archive = response.read()
    with tempfile.TemporaryDirectory() as directory:
        staged = Path(directory) / "verified-source"
        staged.mkdir()
        count = 0
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for item in z.infolist():
                bits = item.filename.split("/", 1)
                if len(bits) != 2 or not bits[1] or item.is_dir():
                    continue
                rel = Path(bits[1])
                if rel.is_absolute() or ".." in rel.parts or ".git" in rel.parts:
                    raise RuntimeError("Unsafe source path: " + item.filename)
                target = staged / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(item))
                mode = (item.external_attr >> 16) & 0o777
                target.chmod(0o755 if mode & 0o111 else 0o644)
                count += 1
        if count != EXPECTED_FILES:
            raise RuntimeError(f"Source file count mismatch: {count} != {EXPECTED_FILES}")
        cmd("git", "init", "-q", "-b", "main", cwd=staged)
        cmd("git", "add", "-f", "-A", cwd=staged)
        tree = cmd("git", "write-tree", cwd=staged)
        if tree != SOURCE_TREE:
            raise RuntimeError(f"Source tree mismatch: {tree} != {SOURCE_TREE}")
        for source in staged.rglob("*"):
            if not source.is_file() or ".git" in source.relative_to(staged).parts:
                continue
            dest = ROOT / source.relative_to(staged)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    print(f"Verified and imported {count} exact-source files, tree {SOURCE_TREE}")


def brand():
    changes = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in {".git", "__pycache__", "third_party"} for part in path.relative_to(ROOT).parts):
            continue
        if path.name == "LICENSE" or path == Path(__file__).resolve():
            continue
        raw = path.read_bytes()
        if b"\x00" in raw[:8192]:
            continue
        try:
            original = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        updated = original.replace("D2RMobile", "Game2Mobile").replace("D2R Mobile", "Game2Mobile")
        rel = path.relative_to(ROOT).as_posix()
        if rel == "dm/tools/mac_app.sh":
            updated = updated.replace("org.d2rmobile.mac", "com.game2mobile.mac")
        elif rel == "dm/ios/tools/shell_build.sh":
            updated = updated.replace("org.d2rmobile.app", "com.game2mobile.app")
        elif rel == "dm/ios/local.env.example":
            updated = updated.replace("org.example.d2rmobile", "com.example.game2mobile")
        if rel == "README.md":
            intro = (
                "> **Status:** Game2Mobile currently adapts Diablo II: Resurrected for "
                "iOS/macOS; it is not a universal game porting tool. Code was imported "
                "from the MIT-licensed [D2R Mobile source](" + UPSTREAM + ") at "
                + SOURCE_SHA[:12] + ". Images, benchmarks and beta-test claims below "
                "are from that source, **not independent Game2Mobile tests**. "
                "Users must supply their own game files. "
                "See [project notes](docs/PROJECT_STATUS.md).\n\n"
                "> **Binaries:** This repository has not published Game2Mobile IPA "
                "or macOS builds yet. Build from source; release package names below "
                "refer to future Game2Mobile builds.\n\n"
            )
            updated = updated.replace("# Game2Mobile\n", "# Game2Mobile\n\n" + intro, 1)
        elif rel == "README.zh-CN.md":
            intro = (
                "> **项目状态：** Game2Mobile 目前只针对《暗黑破坏神 II：狱火重生》"
                "提供 iOS / macOS 兼容适配，尚不是通用游戏移植工具。"
                "本项目基于 MIT 授权的[原 D2R Mobile 项目](" + UPSTREAM + ") "
                + SOURCE_SHA[:12] + " 版本继续维护。下面的截图、性能数据、内测统计"
                "来自原项目，**未经 Game2Mobile 独立复测**。游戏资源须用户自行合法提供。"
                "参见[项目说明](docs/PROJECT_STATUS.md)。\n\n"
                "> **发布状态：** 本仓库目前没有 Game2Mobile 预构建 IPA 或 macOS App，"
                "请先从源码构建；文中的安装包文件名指后续本项目产物。\n\n"
            )
            updated = updated.replace("# Game2Mobile\n", "# Game2Mobile\n\n" + intro, 1)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changes.append(rel)

    for rel, message in {
        "docs/NO_XCODE.md": (
            "> **Game2Mobile note:** Linked upstream Releases contain the original "
            "project's packages, not Game2Mobile builds. There is no Game2Mobile "
            "prebuilt shell yet; generate one with dm/ios/tools/shell_build.sh.\n\n"
        ),
        "docs/NO_XCODE.zh-CN.md": (
            "> **Game2Mobile 提示：** 文中的上游 Releases 链接只提供原项目产物，"
            "不是 Game2Mobile 构建。本仓库尚未发布预构建安装壳，"
            "需先在有对应环境的 Mac 上执行 dm/ios/tools/shell_build.sh。\n\n"
        )
    }.items():
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("\n\n", "\n\n" + message, 1), encoding="utf-8")

    (ROOT / "docs/PROJECT_STATUS.md").write_text(
        "# Game2Mobile · 项目说明 / Project status\n\n"
        "Game2Mobile 基于原有开源适配层继续开发，当前仅针对《暗黑破坏神 II：狱火重生》"
        "Switch 版在 iOS 和 macOS 运行，**不是通用游戏移植引擎**。\n\n"
        "Game2Mobile is currently a Diablo II: Resurrected compatibility project, "
        "not a universal one-click game porting tool.\n\n"
        "## 代码来源 / Provenance\n\n"
        "- Upstream: " + UPSTREAM + "\n"
        "- Source commit: " + SOURCE_SHA + "\n"
        "- The uploaded d2r-mobile-main.zip was verified against upstream Git "
        "tree " + SOURCE_TREE + " (" + str(EXPECTED_FILES) + " files).\n"
        "- Original MIT license and copyright notices retained: [LICENSE](../LICENSE).\n"
        "- Third-party licenses remain applicable; repository does not contain "
        "commercial game assets or binaries.\n"
        "- Original screenshots and performance claims are from upstream, "
        "not Game2Mobile verification.\n\n"
        "## 更名范围 / Rebranding\n\n"
        "- README, documentation, iOS display name, macOS application and "
        "executable, diagnostic file names, local shell IPA artifact names.\n"
        "- Default packaging bundle IDs: com.game2mobile.mac and "
        "com.game2mobile.app (override with your own signing identity).\n"
        "- Compatibility-critical dm file paths and original org.d2rmobile "
        "migration keys are deliberately preserved.\n"
        "- Translation header regenerated from dm/i18n/ui_text.tsv.\n\n"
        "## 尚未完成 / Remaining work\n\n"
        "- No signed app, IPA, TestFlight release or device benchmarks have "
        "been produced or independently tested here.\n"
        "- An Apple build environment and legally obtained game files are needed.\n"
        "- The app icon and original upstream screenshot links have not "
        "been redesigned. Renamed app IDs/data folders may require save migration; "
        "back up saves first.\n\n"
        "## Entry points\n\n"
        "- [中文 README](../README.zh-CN.md) / [English README](../README.md)\n"
        "- [iOS build](../dm/ios/run.sh) / [macOS build](../dm/tools/mac_app.sh)\n"
        "- [Shell builder](../dm/ios/tools/shell_build.sh)\n",
        encoding="utf-8"
    )
    header = cmd(sys.executable, str(ROOT / "dm/ios/tools/dm_i18n.py"), "--header")
    (ROOT / "dm/host/dm_i18n_tab.h").write_text(header + "\n", encoding="utf-8")
    print("Branded", len(changes), "text/code files; generated i18n header")


if __name__ == "__main__":
    import_source()
    brand()
