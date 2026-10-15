# Asset-free Xcode project generation checks / 无游戏资源的工程生成验证

Game2Mobile uses XcodeGen to generate its iOS projects. Prior Python checks
covered only source YAML transformations. Run this Apple Silicon macOS smoke
test to **actually execute XcodeGen and let Xcode parse every generated
`.xcodeproj`**, without private game files, signing identities or package outputs.

```bash
brew install xcodegen                # if missing
python3 scripts/ci_xcodegen_profiles.py --report /tmp/g2m-xcodegen-report.json
```

The script copies **only git-tracked `dm/` source files** into an isolated temporary
directory, then runs the **real `dm/host/Makefile` → `gen_build.py`** flow to
create ~90 tracked host-source symlinks and the main-entry symlink. Only
proprietary game-derived `Gen/` resources are replaced with inert, clearly
marked placeholders. The script never copies untracked local game assets,
`local.env`, provisioning profiles or signing keys.

It checks all four combinations: paid/Metal 4, free/Metal 4, paid/M3 (iOS 18),
free/M3 (iOS 18). Each passes through the same transformation scripts used by
`dm/ios/run.sh`, followed by `xcodegen generate`, `xcodebuild -list -json`,
and `xcodebuild -showBuildSettings -json` with signing disabled. The report
records target membership, minimum iOS version and CPU/Metal compiler flags.

**This does not compile/link a full DmIOS app**, produce an IPA, test rendering
or imply that the dummy `Gen/` sources are functional. A real Apple build must
still be performed with legitimately obtained matching ExeFS/RomFS, generated
assets, developer signing and physical-device tests.

中文：本检查会使用真实的 XcodeGen 与 Xcode 工具链，实际生成并检查四类工程配置；不包含、不复制也不上传任何游戏资源或签名材料。生成的 `Gen/` 内容是临时占位文件，不可用于真实发布。

## Verified CI run / 实际验证记录

- Environment: **macos-26 ARM64**, Xcode **26.6**, XcodeGen **2.46.0**
- Validated profiles: paid-metal4, free-metal4, paid-m3, free-m3
- [Passing GitHub Actions workflow](https://github.com/ForceMind/Game2Mobile/actions/runs/38667796078)
- A JSON report is saved as the `game2mobile-xcodegen-profiles` Actions artifact.
- A dedicated Python regression test ensures that untracked local
  `dm/ios/local.env` and game-derived `Gen/` content are excluded from staging.

工程生成通过并不等于正式 iOS 应用链接成功，不能据此宣布已有可安装版本。

## Real host-source expansion / 真实宿主源码展开

[Passing Apple Silicon CI (with actual generated host source graph)](https://github.com/ForceMind/Game2Mobile/actions/runs/38668287937)

In addition to four XcodeGen profiles, CI verifies that the host Makefile
expands into at least 80 existing, safely resolved source symlinks; the current
project generated **90** plus its separate `main.c` link. The NVN/Metal backend
is checked among those generated source inputs. Its JSON report now includes
`makefile_source_links`, making source coverage auditable. None of those
steps execute game ROM data or assemble game binaries.
