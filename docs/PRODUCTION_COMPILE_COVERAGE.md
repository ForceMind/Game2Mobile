# Game2Mobile · Real production source ARM64 compilation coverage

> **Verified on 2026-10-15.** This is a source-codegen milestone, **not a
> game build**. No Nintendo Switch ExeFS/RomFS, licensed game resources, or
> developer signing credentials were used.

## Actual Apple Silicon CI results

The list comes from the production `dm/host/Makefile` expanded by the
unchanged `dm/ios/tools/gen_build.py`: **90 source links + `host/main.c`**.
Every compilation unit is submitted to Apple's genuine iPhoneOS Clang as
an ARM64 target; successful Mach-O `.o` objects are verified with
`lipo -archs`.

| Production configuration | Mac runner | Total units | ARM64 Mach-O built | Game-generated header blocks | Other compile errors |
|---|---|---:|---:|---:|---:|
| iOS 26 / Metal 4, `apple-a18` | macOS 26 | 91 | **88** | 3 | **0** |
| iOS 18 / Metal M3, `apple-a14` | macOS 15 | 91 | **88** | 3 | **0** |

**176 Apple ARM64 production object compilations succeeded** across the two
profiles. The strict CI fails for any other compiler error, newly blocked
source, or regression in the previously verified loader/main/Metal modules.

[Strict two-runner GitHub Actions results](https://github.com/ForceMind/Game2Mobile/actions/runs/38744154022).
Two separate JSON artifacts retain the per-file results for each profile.

## Real iOS frontend compilation: both SDK versions passed (2026-10-19)

The project also has **17 separate tracked iOS frontend** Objective-C/C units
(`dm/ios/Sources`) for UIKit, touch, gamepad, shader preparation, save
synchronization, downloads and the iOS entrypoint. These are not the same as
the `Gen/src` host compilation units: `gen_build.py` deliberately skips
host-borrowed iOS Sources to avoid double-linking.

| iOS source group | iOS 26 / macOS 26 | iOS 18 / macOS 15 |
|---|---:|---:|
| Host/graphics Makefile units | 88 / 91 compiled | 88 / 91 compiled |
| Real tracked UIKit/frontend units | **17 / 17 compiled** | **17 / 17 compiled** |
| **Total distinct tracked units** | **105 / 108** | **105 / 108** |
| Additional C/Obj-C compiler errors | **0** | **0** |

The original legacy iOS 18 compiler run failed on `main.m`: iOS 18 has
no `BAAssetPackManager` or iOS 26 managed-asset download delegate.
The source now excludes those APIs under `DM_NVN_M3`, while preserving the
iOS 26 managed download implementation and the iOS 18
local/direct-download fallback. Recompilation on the real Apple iOS 18
SDK confirmed **17/17** compiled with no errors.

[Verified dual-profile frontend run](https://github.com/ForceMind/Game2Mobile/actions/runs/39153982764)
· [Source compiler](../scripts/ci_ios_frontend_compile.py).

**Important:** the 108-unit total counts only tracked host plus tracked iOS
frontend sources. The generated `Sources/dm_touch_native_art.c` and three
RomFS-derived headers still require the owner's lawful game data. Object-code
success is not evidence of full target linking, signing or gameplay.

## Exactly three expected RomFS-derived dependencies

| Source | Missing generated file | Generation path in repository |
|---|---|---|
| `dm/host/diag.c` | `dm_hud_exp.h` | `dm/ios/tools/gen_hud_exp.py` |
| `dm/host/dm_bright.c` | `dm_bright_levels.inc` | `dm/tools/gen_bright_levels.py` |
| `dm/host/dm_vault_ui.c` | `dm_vault_tab.h` | `dm/ios/tools/gen_vault_table.py` |

These are **not missing tracked source files**. They must be derived from the
game files legally supplied by the owner. CI deliberately refuses to
fabricate, download or distribute them. The same three blocked units were
confirmed in both independent Apple profile reports.

## Reproduce without game files

On a Mac with Xcode:

```bash
python3 scripts/ci_production_compile.py --profiles metal4 --strict \
    --report /tmp/Game2Mobile-production-ios26.json

# Use a suitable Apple SDK for iOS 18/M3 (the CI uses macOS 15)
python3 scripts/ci_production_compile.py --profiles m3 --strict \
    --report /tmp/Game2Mobile-production-ios18.json
```

Only Git-tracked `dm/` source is copied into an isolated temporary tree.
The sweep is **object-code compilation**, not `xcodebuild` compilation/linking
of the actual DmIOS game target. The three private generated headers, shader
libraries, program images, bundle signing, simulator execution, and physical
device gameplay are all still outside the validated scope.

**Next M1 gate:** on a controlled Apple Silicon Mac with properly owned and
version-matched ExeFS/RomFS, generate the three game tables and all asset
outputs; then perform **actual DmIOS target compilation, full link, signing
and real-device boot**. Track that milestone in
[Issue #1](https://github.com/ForceMind/Game2Mobile/issues/1).
