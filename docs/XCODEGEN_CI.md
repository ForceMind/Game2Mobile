# Asset-free Xcode project generation checks / 无游戏资源的工程生成验证

Game2Mobile uses XcodeGen to generate its iOS projects. Prior Python checks
covered only source YAML transformations. Run this Apple Silicon macOS smoke
test to **actually execute XcodeGen and let Xcode parse every generated
`.xcodeproj`**, without private game files, signing identities or package outputs.

```bash
brew install xcodegen                # if missing
python3 scripts/ci_xcodegen_profiles.py --report /tmp/g2m-xcodegen-report.json
```

The script copies **only git-tracked `dm/ios` files** into an isolated temporary
directory and creates inert, clearly marked `Gen/` placeholders so that XcodeGen
has build-input paths. It never copies untracked local game assets, `local.env`,
provisioning profiles or signing keys.

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
