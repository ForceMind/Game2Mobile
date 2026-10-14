# Game2Mobile build and release checklist

> **Status: source maintenance, not a released playable binary.** No Game2Mobile-signed IPA, macOS App or TestFlight build has been independently completed at this stage. Historical upstream measurements are not new Game2Mobile benchmarks.

## Source-level verification (Linux / macOS)

```sh
python3 scripts/release_checks.py source
python3 -m unittest discover -s scripts/tests -v
python3 dm/ios/tools/dm_i18n.py --check
```

GitHub Actions also runs asset-free C and Python regression tests. A green workflow is **not** proof that the project compiles on Apple platforms or runs on real devices.

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
