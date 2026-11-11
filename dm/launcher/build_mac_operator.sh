#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# On an owner-controlled Apple Silicon Mac, bundle the standalone engineering UI.
# This does not generate the proprietary game App or sign using developer secrets.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
package="$root/dm/launcher/MacOperator"
output="$package/out/Game2MobileOperator.app"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo 'macOS required for SwiftUI application' >&2; exit 2
fi
swift build --package-path "$package" --configuration release
bin_dir="$(swift build --package-path "$package" --configuration release --show-bin-path)"
if [[ ! -x "$bin_dir/Game2MobileOperator" ]]; then
  echo 'Native macOS operator binary was not built' >&2; exit 3
fi
mkdir -p "$package/out"
if [[ -e "$output" || -L "$output" ]]; then
  # Fixed project-owned output only; refuse symlinks to other directories.
  if [[ -L "$output" ]]; then echo 'Refusing a symlinked app output' >&2; exit 4; fi
  rm -rf "$output"
fi
mkdir -p "$output/Contents/MacOS" "$output/Contents/Resources"
cp "$bin_dir/Game2MobileOperator" "$output/Contents/MacOS/Game2MobileOperator"
cp "$package/Info.plist" "$output/Contents/Info.plist"
# Ad-hoc signature for local launch only, no keychain/developer signing identity.
/usr/bin/codesign --force --sign - "$output"
echo "Local-only macOS engineering UI: $output"
echo 'No game content, IPA, device installation, or developer signing performed.'
