#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Produce a local, unnotarized engineering-tool disk image only.
# No game App, developer signing, keychain, resources or network publishing.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
package="$root/dm/launcher/MacOperator"
out="$package/out"
app="$out/Game2MobileOperator.app"
name='Game2Mobile-Operator-local.dmg'
dmg="$out/$name"
digest="$out/$name.sha256"
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo 'An Apple Silicon Mac is required' >&2; exit 2
fi
if [[ -L "$out" || -L "$app" || -L "$dmg" || -L "$digest" ]]; then
  echo 'Refusing symlinked packaging inputs or outputs' >&2; exit 4
fi
if [[ -e "$dmg" || -e "$digest" ]]; then
  echo 'Refusing to overwrite an existing engineering-tool disk image' >&2; exit 4
fi
bash "$root/dm/launcher/build_mac_operator.sh"
/usr/bin/codesign --verify --strict "$app"
work="$(mktemp -d "$out/.g2m-dmg.XXXXXXXX")"
trap 'rm -rf "$work"' EXIT
/usr/bin/hdiutil create -quiet -srcfolder "$app" -volname 'Game2Mobile Operator' \
  -format UDZO "$work/$name"
/usr/bin/hdiutil verify -quiet "$work/$name"
# Files are owned by the local user; publish the digest last, with a relative
# filename so shasum -c does not expose owner paths when reviewing a package.
chmod 0600 "$work/$name"
mv "$work/$name" "$dmg"
(cd "$out" && /usr/bin/shasum -a 256 "$name" > "$name.sha256")
chmod 0600 "$digest"
(cd "$out" && /usr/bin/shasum -a 256 -c "$name.sha256")
echo 'Created unnotarized local macOS engineering installer:'
echo "$dmg"
echo 'Not an iOS game App and not a notarized public release.'
