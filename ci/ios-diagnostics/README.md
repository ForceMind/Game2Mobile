# Game2Mobile — Asset-free iOS build diagnostics

This is a real Apple iOS ARM64 **build-smoke application**, not the playable game. It builds a standalone SwiftUI diagnostic screen with the same tracked Game2Mobile brand icon. It **does not link** the guest loader, game runtime, or commercial game assets.

Runtime checks: Metal availability, iOS version, temporary file read/write and diagnostic bundle identity. Users can rerun checks and copy a text report.

## CI output

The independent project lives in ci/ios-diagnostics/project.yml, and the build workflow lives in .github/workflows/ios-diagnostics.yml. On a macos-26 Apple Silicon runner, Xcode builds two unsigned ARM64 Mach-O applications: one for iPhoneOS and one for iOS Simulator.

The verifier checks the AppIcon in Assets.car, app identity, executable architecture, and absence of typical commercial game asset paths and extensions. The upload artifact is explicitly named Game2Mobile-DIAGNOSTICS-NOT-PLAYABLE.

## Local verification

Use an Apple Silicon Mac with Xcode and XcodeGen:

    cd ci/ios-diagnostics
    xcodegen generate
    xcodebuild -project Game2MobileDiagnostics.xcodeproj -scheme Game2MobileDiagnostics -configuration Release -sdk iphoneos -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build

The device build must be signed before it can be installed on a real iPhone or iPad. Simulator builds are separate.

**Never present a diagnostic app as a playable Game2Mobile release.** This tests the Apple app packaging pipeline, not the actual game runtime. The real app still requires properly licensed, matching ExeFS/RomFS, derived game data, shaders, complete game target linking, Apple signing and device testing.

中文说明：这是独立的 iOS 编译诊断 App，不是游戏，也不包含游戏代码、商业资源或已签名 IPA。只用于验证 Apple 原生编译和打包流程。
