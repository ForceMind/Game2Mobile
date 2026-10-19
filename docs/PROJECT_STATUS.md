# Game2Mobile · 项目说明 / Project status

Game2Mobile 基于原有开源适配层继续开发，当前仅针对《暗黑破坏神 II：狱火重生》Switch 版在 iOS 和 macOS 运行，**不是通用游戏移植引擎**。

Game2Mobile is currently a Diablo II: Resurrected compatibility project, not a universal one-click game porting tool.

## 代码来源 / Provenance

- Upstream: https://github.com/jhaizhou-ops/d2r-mobile
- Source commit: 685d3ddef8bf75768fd4c51228566f2e8d2a5182
- The uploaded d2r-mobile-main.zip was verified against upstream Git tree 59ab9da0b9726a699d7e45a855ea4cf5c0ee00a2 (1024 files).
- Original MIT license and copyright notices retained: [LICENSE](../LICENSE).
- Third-party licenses remain applicable; repository does not contain commercial game assets or binaries.
- Original screenshots and performance claims are from upstream, not Game2Mobile verification.

## 更名范围 / Rebranding

- README, documentation, iOS display name, macOS application and executable, diagnostic file names, local shell IPA artifact names.
- Default packaging bundle IDs: com.game2mobile.mac and com.game2mobile.app (override with your own signing identity).
- Compatibility-critical dm file paths and original org.d2rmobile migration keys are deliberately preserved.
- Translation header regenerated from dm/i18n/ui_text.tsv.

## 尚未完成 / Remaining work

- No signed app, IPA, TestFlight release or device benchmarks have been produced or independently tested here.
- An Apple build environment and legally obtained game files are needed.
- The app icon is now independent ([SVG source](../assets/brand/game2mobile-icon.svg), [iOS PNG](../dm/ios/Assets.xcassets/AppIcon.appiconset/AppIcon1024.png)); macOS generates an ICNS file from that artwork at build time. Screenshots still link to original upstream reference assets.
- Renamed app IDs/data folders may require save migration; back up saves first.
- [中文构建及发布验收清单](BUILD_AND_RELEASE.zh-CN.md) / [English build and release checklist](BUILD_AND_RELEASE.md) defines all remaining Apple builds and device tests.

## Entry points

- [中文 README](../README.zh-CN.md) / [English README](../README.md)
- [iOS build](../dm/ios/run.sh) / [macOS build](../dm/tools/mac_app.sh)
- [Shell builder](../dm/ios/tools/shell_build.sh)

## M1 takeover verification — 2026-10-19

- Remote baseline rechecked: `332b79c34abf76cba9e8e620bafdd2959ebe16b0`, product `3.3.94012-r44`; PR #10 merged, M1 issue #1 open.
- Baseline main CI: [Linux](https://github.com/ForceMind/Game2Mobile/actions/runs/39154502564) and [Apple native / UIKit / XcodeGen](https://github.com/ForceMind/Game2Mobile/actions/runs/39154502664) completed successfully. These are source/object/project checks, not a real game link.
- Build chain: licensed version-matched ExeFS/RomFS → `setup.sh` module patching and shader translation → private host headers and touch art → Makefile-derived Xcode inputs and guest embedding → XcodeGen profile → signed device build → bundle verification → separate device installation and gameplay checks.
- Fixed private-build provenance: the final App uses the pipeline-selected workspace/RomFS/shader root after local configuration is loaded; tracked source or HEAD changes during any stage invalidate commit-based acceptance. Local toolchain lock changes require review and a clean commit before retrying.
- This execution environment is Linux x86_64. The actual `all --profile metal4` invocation rejected it at the Apple Silicon platform gate. No licensed inputs, Apple signing or physical device were available to this execution; no private 91/91 compile, touch-art compilation, full game link or device success is claimed.
- Next owner-Mac action: follow [M1 private build](M1_PRIVATE_BUILD.zh-CN.md), run `python3 scripts/m1_local_pipeline.py all --profile metal4`, retain private stage logs and summary locally, and address the first actual failure. M1 remains open.
