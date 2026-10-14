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
- The app icon and original upstream screenshot links have not been redesigned. Renamed app IDs/data folders may require save migration; back up saves first.

## Entry points

- [中文 README](../README.zh-CN.md) / [English README](../README.md)
- [iOS build](../dm/ios/run.sh) / [macOS build](../dm/tools/mac_app.sh)
- [Shell builder](../dm/ios/tools/shell_build.sh)
