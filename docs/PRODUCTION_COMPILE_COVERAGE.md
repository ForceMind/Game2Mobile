# Game2Mobile · Production ARM64 source compilation audit

**Goal:** use Apple's real iPhoneOS compiler to enumerate which original Game2Mobile
production files compile without private game assets. The list comes from the
actual `dm/host/Makefile`, via `gen_build.py`, not a manually-maintained subset.

## Command and report

On Apple Silicon with Xcode installed:

```bash
python3 scripts/ci_production_compile.py --profiles metal4 --report /tmp/g2m-host-coverage.json
# Optional legacy target (same source, iOS 18):
python3 scripts/ci_production_compile.py --profiles m3 --report /tmp/g2m-host-m3-coverage.json
```

Each tracked source is compiled individually with Apple clang into an actual
ARM64 Mach-O `.o` file using the selected iOS SDK/deployment settings. Successful
objects are verified with `lipo -archs`.

The JSON report distinguishes `compiled`, `blocked_generated_asset` (direct
missing references to known game-derived headers), and `compile_error` (other
compiler diagnostics). Missing proprietary headers **are never fabricated**.

**CI interpretation:** the non-strict inventory job is green when the three
previously proven loader/main/Metal modules still compile and source coverage
is complete. It can still report remaining errors; always inspect the JSON
before making claims. The optional `--strict` switch fails if any
`compile_error` remains.

Generated game tables are intentionally not uploaded. This compilation sweep
does not produce a full linked executable or a working Game2Mobile IPA.
The latest build status is governed by [Issue #1](https://github.com/ForceMind/Game2Mobile/issues/1).
