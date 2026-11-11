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

## M1 build staging hardening — 2026-10-20

- Rechecked remote main `3027208e02a44071c7faee9bc485f683827446f9`; its post-merge Linux and Apple native workflows passed. No open PR was present when this stage began.
- Reproduced shell failures using inert copy fixtures and mocked external tools: module paths with spaces fail at guest embedding; resource-copy failures and signature-check failures can still return success.
- `run.sh build` now quotes module/App paths, regenerates private tables each build, checks required and present-optional copy failures, retries failed APFS clones with an ordinary copy after removing partial output, and requires code-signature verification after Xcode succeeds.
- The new orchestration regression suite runs locally on Linux and is included in the existing native Apple XcodeGen job. Generator/compiler/signing calls in that suite are mocks: it provides no game codegen, real App link, signature or device evidence.
- The current execution environment remains Linux x86_64 without connected owner-Mac game resources, Apple signing or a physical device. M1's private 91/91, generated touch art, full game link and gameplay gates remain unverified.

## Module cache acceptance — 2026-10-20

- Build staging PR #12 merged as `3305b4c7b3b295bec2e117b2a2c6f8777016bbad` after all four workflows passed: [Linux](https://github.com/ForceMind/Game2Mobile/actions/runs/39390754921), [production ARM64](https://github.com/ForceMind/Game2Mobile/actions/runs/39390754808), [Apple native / UIKit / XcodeGen / staging](https://github.com/ForceMind/Game2Mobile/actions/runs/39390754849), [independent diagnostics](https://github.com/ForceMind/Game2Mobile/actions/runs/39390754870).
- Setup's single-main-file cache shortcut was replaced with `product.sh check`, reusing the existing rewriter SHA receipt and checking all three modules in every product variant. A final completion receipt is created only after a full variant rewrite; interruption/failure leaves an unfinished marker and forces a later rebuild. Legacy caches without completion receipts rebuild once.
- Cache and setup-stage regression tests use inert text files and a mock rewriter. They validate cache control flow only, not NSO rewriting or authentic game outputs. Existing module rewriting code is unchanged.
- Remaining M1 dependency is still the owner's licensed inputs plus a controlled Apple Silicon Mac, local signing and device evidence. No private 91/91, full game link or gameplay result is claimed by these changes.

## Device-run evidence integrity — 2026-10-20

- Rechecked remote main `ef62b195f67bcc8bf9f1ac404e2e1fe91e7e4679`: post-merge Linux and Apple native workflows passed, no open PR present. Current executor remains Linux x86_64; no owner-Mac or device connection is exposed.
- In inert control-flow reproductions, the old `run.sh` returned success for early exit, stale DONE, failed launch, and even attempted installation after a failed device lock.
- Require device-lock success; quote install/run paths; validate modes/timeouts; honor launch return codes and structured PID results; distinguish process-query failure from a confirmed exited process. Pull logs through a temporary file and require this launch's random receipt plus an exact completion marker.
- The actual UIKit entrypoint now logs a bounded optional run receipt and writes a failure marker instead of DONE when the guest-host entrypoint returns nonzero. Ordinary icon launches do not set the receipt. Rebuild/reinstall the App when using the updated launcher; old packages cannot satisfy the new freshness check.
- New regressions use mock CoreDevice commands, plus native C execution of the extracted receipt logger. These prove orchestration and helper behavior only; licensed game construction, App installation, graphics/input/audio/saves and physical-device gameplay remain unverified.
- Existing watchdog-driven screenshot/timing collectors explicitly select log-collection mode. A fresh receipt and confirmed PID exit are required; collection success is separate from command completion and downstream image/timing checks remain in place.

## S2Arm-inspired startup diagnostics and build identity — 2026-11-09

- Development began from `14af5aa48358063ccb38b5b6b6bb504a5cb7db95`. The [integration plan](S2ARM_INTEGRATION_PLAN.zh-CN.md) and [fixed-source comparison](S2ARM_DIFFERENCES.zh-CN.md) distinguish existing shared ancestry from proposed changes. No S2Arm implementation was copied into this change.
- Native startup events identify one process/run, serialize concurrent writers, and observe module loading, relocation, SDK/module initialization, guest entry, first GPU submission and the first actual drawable presented callback. The [read-only analyzer](STARTUP_DIAGNOSTICS.zh-CN.md) isolates runs and refuses stale, malformed or incomplete evidence. A present callback is not proof of a correct or playable frame.
- `run.sh build` generates `dm/build_identity.json` before compilation and verifies the resulting App after signature checking. The manifest binds source commit/dirty state, product/profile, rewriter and module IDs, module images/tables, shader chain and copied cache. Final verification reads the six actual Mach-O guest sections, checks their original bytes and zero padding, and rejects mixed resources. The M1 gate requires clean source, including nonignored untracked files.
- The extra portable C compilation unit changes the host inventory from 91 to 92. Current strict private acceptance requires **92/92**; historical **88/91** public reports above retain their original scope. Current public expectation is **89/92** plus the same three private-header blockers; success must be confirmed on the corresponding Apple CI run.
- Local synthetic tests cover C concurrency, cross-language log parsing, binary/resource mismatches and shell failure propagation. Apple CI additionally compiles both Metal APIs and links a harmless anonymous-section fixture for the binary parser. Those checks do not constitute a linked game App, authentic resource transformation, signing acceptance or physical-device gameplay. M1 remains open.

## S2Arm lessons implemented — 2026-11-09 (asset-free)

- [PR #15](https://github.com/ForceMind/Game2Mobile/pull/15) merged as `15b2fa53b2f20ebaeda4e4cdc5e01f4e1a61f2cc`: native structured startup/first-present events, strict same-run analyzer, final-bundle embedded guest module/shader byte identity verification, 92-source private expectation, and local read-only JSON AI CLI (`capabilities/status/next/diagnose`). [9-job CI on feature head](https://github.com/ForceMind/Game2Mobile/actions/runs/42754211339) passed; 89/92 public compiled, three private header blockers unchanged.
- [PR #16](https://github.com/ForceMind/Game2Mobile/pull/16) merged as `4c3b8f5bb2ca306cb4603dff207a5cbec933ebbd`: prevent optimized Python from removing critical NSO rewriting assertions; synthetic AArch64 B/ADRP branch-page reach tests. Nine CI jobs passed.
- [PR #17](https://github.com/ForceMind/Game2Mobile/pull/17) merged as `dd771c9d22c400256b8155241ea2e0ab05ed5a97`: fix texture cache staleness after guest memory pool destruction/reuse, correct actual 4096-capacity overflow test, run native write protection concurrency tests on macOS 15 and 26. Nine CI jobs passed.
- Current S2-08 first-stage work adds per-stage atomic private M1 progress and read-only JSON `g2mctl job-status` for owner-machine debugging, but no shared GUI executor, remote write control, or independent device gameplay validation. All tests are synthetic/asset-free.
- M1 [issue #1](https://github.com/ForceMind/Game2Mobile/issues/1) **remains open**: no owner Mac licensed-game 92/92 full link/sign, real iOS gameplay, frame screenshots, audio, save restore or playable release evidence.

## Asset-free reliability work — 2026-11-10

[PR #20](https://github.com/ForceMind/Game2Mobile/pull/20) extends the existing implementation with bounded loader metadata/gate validation, conservative memory-protection failure handling, checkout-serialized and cancellable M1 stages, explicit local CLI build/export, summary-only diagnostic archives, and consistency checking for owner-authored device acceptance records. The production source inventory remains 92; no game-dependent header is fabricated. See [implementation and remaining scope](ASSET_FREE_CLOSEOUT.zh-CN.md) and [operator commands](AI_OPERATOR_CLI.zh-CN.md).

Public/synthetic test results remain separate from licensed-module semantics, full linked/signed game builds, device installation and playability. No complete frame recorder/replayer, graphical launcher, second-game adaptation or new-platform release is claimed. M1 remains open.
