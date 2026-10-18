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

## Genuine unsigned iOS diagnostics App builds (not the game)

A standalone, game-free diagnostic App has been **compiled and linked by Xcode** for both Apple Silicon iPhoneOS and iOS Simulator, then checked for identity, ARM64 executable, original brand icon and absence of game resource file types. The initial [successful artifact CI run](https://github.com/ForceMind/Game2Mobile/actions/runs/38736461658) uploaded explicitly **NON-PLAYABLE** ZIP outputs and JSON reports. See [diagnostic target documentation](../ci/ios-diagnostics/README.md).

**No Simulator runtime launch is confirmed.** In a [subsequent attempted launch](https://github.com/ForceMind/Game2Mobile/actions/runs/38736867676), the simulator boot check finished but `simctl install` timed out after 120 seconds. This does not demonstrate a game build, a physical-device launch, or a running diagnostic UI. Further Simulator installation is a separately, manually triggered bounded check; verified compile outputs are not held hostage by shared runner installation timeouts.

## Real production source codegen: both Apple SDK paths passed

[Strict Apple Silicon CI on both operating systems](https://github.com/ForceMind/Game2Mobile/actions/runs/38744154022) compiled the actual `dm/host/Makefile` sources to ARM64 Mach-O objects, using genuine Apple Clang:

| Toolchain target | Object compilations | Missing private generated headers | Other compiler errors |
|---|---:|---:|---:|
| macOS 26, iOS 26 Metal 4 | **88 / 91** | 3 | **0** |
| macOS 15, iOS 18 Metal M3 | **88 / 91** | 3 | **0** |

The same three source files require genuine derived game headers:
`host/diag.c`, `host/dm_bright.c`, and `host/dm_vault_ui.c`. They are
not missing repository files. All other host sources compiled successfully,
producing **176 ARM64 object files** in total across both toolchains.

This is **not** a fully linked/signed DmIOS app or verified gameplay. See
[the source-by-source coverage report](PRODUCTION_COMPILE_COVERAGE.md).

## Complete source and owner-only shader cache preflight

The **tracked** `dm/gfx/nvn/shader_map.tsv` is a genuine 1.33 MB shader mapping
file containing **6,927 unique controls** for the pinned version; it is **not**
an empty placeholder. The tracked PSO warmup list contains 181 unique valid
shader controls, all represented in the map.

```sh
python3 scripts/m1_shader_inventory.py source
# On the owner Mac only, after real shader assets have been generated:
V=$(awk '/^#define DMSH_CHAIN / { gsub(/"/, "", $3); print $3 }' dm/gfx/nvn/dmsh_chain.h)
python3 scripts/m1_shader_inventory.py cache \
  --ios-root "${DM_ROOT:-$HOME/dm-work}/build/ios/dmsh_b" \
  --mac-marker "${DM_ROOT:-$HOME/dm-work}/build/cache/metal_shader_cache/b-$V/_b_build.json"
```

The same preflight is now used **in `./setup.sh` and before `run.sh build`
copies/link-packages the resources**. It requires an exact one-to-one
translator receipt, `ok` status for every mapped control, and each paired
iPhoneOS `_b.metallib` and reflection `_b.json` with matching chain/key/route.
Missing assets fail early instead of being detected only after an expensive
Xcode App build. It does not download, upload, or include licensed game data,
and it is **not** evidence of a playable game.

## Private owner-only M1 full game build workflow (prepared, not yet executed)

To go beyond the public Apple CI's **88/91** host object compilation,
an owner may now run [`m1_local_pipeline.py`](../scripts/m1_local_pipeline.py)
on their own Apple Silicon Mac. This requires the owner's legally obtained
version-matched game files and local Apple signing identity:

```sh
python3 scripts/m1_local_pipeline.py plan
python3 scripts/m1_local_pipeline.py all --profile metal4
```

The workflow re-generates exactly three private RomFS headers, requires a
strict real **91/91** ARM64 compile, then calls the existing `DmIOS` Xcode build
and locally validates the signing. Every run has a **new isolated DerivedData directory** and it drops inherited `DM_GEN_ONLY`, `DM_OUT`, and stale build-path settings, preventing a previously compiled app from being accepted as a fresh artifact. Private logs and summaries use restrictive file permissions. A single-stage run is marked **partial**.
Proprietary headers, original/derived game data, private logs and resulting App bundles are **never uploaded to GitHub**. See [owner-only instructions](M1_PRIVATE_BUILD.zh-CN.md).

**Authentic-game bundle validation:** after `run.sh build`, the
owner-only verifier now requires real guest `main/sdk` non-empty
executable/writable Mach-O sections **in the correct segments**, all
source-derived fixups/gates manifests, the actual generated shader map,
one matching iPhoneOS `*_b.metallib` **and** `*_b.json` reflection for
**every mapped shader key**, the current source translation-chain version,
PSO seed coverage, RomFS overlay configuration, a compiled icon, an
embedded provisioning profile and a verifiable Apple code signature. The actual
minimum iOS version must match Metal 4 (iOS 26) or M3 (iOS 18);
`local.env` can no longer silently change that selected profile.
The executable SHA-256 is recorded in the **private** per-run report.
These checks reject unsigned diagnostics and game-free install shells.
[Verifier source](../scripts/m1_game_bundle.py).

**No successful private 91/91 run, full game link, signed game App or real-device
gameplay is being claimed by this preparatory code change.**

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
