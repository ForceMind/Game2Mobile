# Game2Mobile build and release checklist

> **Status: source maintenance, not a released playable binary.** No Game2Mobile-signed IPA, macOS App or TestFlight build has been independently completed at this stage. Historical upstream measurements are not new Game2Mobile benchmarks.

## Source-level verification (Linux / macOS)

```sh
python3 scripts/release_checks.py source
python3 -m unittest discover -s scripts/tests -v
python3 dm/ios/tools/dm_i18n.py --check
```

GitHub Actions also runs asset-free C and Python regression tests. A green workflow is **not** proof that the project compiles on Apple platforms or runs on real devices.

## Verified native Apple compilation (without game assets)

The [`apple-native.yml`](../.github/workflows/apple-native.yml) workflow runs on a real GitHub-hosted **`macos-26` Apple Silicon ARM64** worker. Successful smoke checks include:

- Xcode/macOS/iPhoneOS SDK discovery and compilation/execution of native input, host core and Metal helper unit tests.
- `clang -fsyntax-only` of the **actual production** `dm/gfx/nvn/nvn_mtl.m` for macOS 26 Metal 4, macOS 15 M3, iOS 26 Metal 4 and iOS 18 M3 targets.
- ARM64 iOS SDK syntax checks for `front_ios.m` and `main.m`.
- Swift 6 type checking for the `RomfsDownloader.swift` extension with iOS 26.0 as its deployment target.
- Native `sips`/`iconutil` conversion of the committed RGB brand icon into `Game2Mobile.icns`.
- Standalone regression tests of all four iOS project configuration combinations (paid/free × Metal 4/M3).

[Verified Apple Silicon run](https://github.com/ForceMind/Game2Mobile/actions/runs/38612203914).

**Scope:** This verifies real Apple compilers and unit targets, but **not** a fully linked Xcode game App, asset derivation, game execution, signing, or a tested release.

**Native object code proof:** [dual-platform run at `fc5bb87e`](https://github.com/ForceMind/Game2Mobile/actions/runs/38613049859) emitted **10 real ARM64 Mach-O `.o` objects** on macOS 26 for both Metal API variants, iOS front-end/entry, and the production guest loader/host entry on iOS/macOS. A separate actual **macOS 15 ARM64 runner** also compiled the older Metal M3 backend and executed asset-free input and graphics math tests. These are genuinely executed compiler checks; they are not game-integration or playable-app evidence. The previously mismatched iOS 26.4 downloader extension target was aligned to the host app's iOS 26.0 target following successful Swift 6 type checking. Apple-hosted asset downloads on iOS 26.0 still require on-device testing.

## Verified XcodeGen project generation (four actual Apple projects)

An Apple Silicon macOS 26 runner with **XcodeGen 2.46.0 and Xcode 26.6**
successfully executed actual `xcodegen generate`, `xcodebuild -list -json`,
and `xcodebuild -showBuildSettings -json` for all four profiles: paid/free
accounts × Metal 4/iOS 26 or M3/iOS 18.

The app deployment target, CPU flags, extension target presence/absence, and
minimum OS of the managed asset downloader were checked in the **generated
Xcode projects**, not just in a YAML string transform.

[Successful CI run](https://github.com/ForceMind/Game2Mobile/actions/runs/38667796078) ·
[Test implementation](../scripts/ci_xcodegen_profiles.py) ·
[Isolation and limitations](XCODEGEN_CI.md).

A later [successful real-source CI run](https://github.com/ForceMind/Game2Mobile/actions/runs/38668287937) also executed **the actual host Makefile → `gen_build.py`** pipeline, generated 90 symlinked tracked host sources plus the real `Gen/main/main.c`, and then passed all four real Xcode project checks. Only game-derived `Gen/` resources remain inert CI placeholders.

The staging operation copies only git-tracked `dm/` source files, never local untracked game assets or signing files. This is **not** a full DmIOS compile, link, IPA, signed app, or device test.

## Prerequisites for the first Apple build

Use an Apple Silicon Mac with a supported Xcode/Apple SDK, XcodeGen, .NET SDK, spirv-cross and Python. You must legally supply matching Nintendo Switch Diablo II: Resurrected game files: `ExeFS/main`, `sdk`, `subsdk0` and `RomFS/data`. Do not upload game assets or Apple signing credentials to GitHub.

```sh
./setup.sh check                 # Toolchain, free disk, game-version hash and signing checks
./setup.sh                       # Build game patching and derived content locally
cd dm/ios
cp local.env.example local.env
# Set DM_TEAM_ID / DM_BUNDLE_ID for your own Apple developer account
./run.sh build                   # Build the internal test app
```

## Acceptance gates

| Stage | Acceptance criteria | Status |
|---|---|---|
| M0 | Complete tracked source, independent icon, repeatable offline CI | **Completed** |
| M1 | Apple Silicon clean Xcode build, internal IPA and recorded build logs | **Not yet verified** |
| M2 | iOS 26 physical-device installation, launch, video, input, audio and save smoke tests | **Not yet verified** |
| M3 | Validate older iOS APIs, macOS app, signing, licenses and asset-free public shell | **Not yet verified** |

The macOS packager builds `Game2Mobile.icns` from the same tracked iOS RGB icon. Apple SDK packaging must still be tested on a Mac.

## Package safety guards

The project already removes derived resources and scans built artifacts inside `dm/ios/tools/shell_build.sh`. A separate shell/package check now verifies basic IPA structure, brand metadata and a deny-list of game-derived files:

```sh
python3 scripts/release_checks.py shell /path/to/Game2Mobile-shell.ipa
python3 scripts/release_checks.py macapp /path/to/Game2Mobile.app
```

These checks are a **second line of defense**, not a guarantee that all proprietary material has been excluded. Inspect the full package and its legal provenance before distribution. Do not mark a release playable, report TestFlight success, or claim new performance figures until the relevant builds and device tests actually pass.

The first release should state the `dm/PRODUCT` version, source commit SHA, supported operating-system/hardware matrix, signing method, asset inclusion policy and bring-your-own-files instructions.
