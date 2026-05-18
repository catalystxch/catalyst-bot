#!/usr/bin/env bash
set -euo pipefail

release_ref="${1:?release tag required, e.g. v1.2.36}"
version="${release_ref#v}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_path="${APP_PATH:-"$root/dist/CATalyst.app"}"
dmg_stage="$root/build/macos-dmg"
dmg_path="$root/Catalyst-macos-${release_ref}.dmg"
sha_path="${dmg_path}.sha256"

if [[ ! -d "$app_path" ]]; then
  echo "macOS app bundle not found: $app_path" >&2
  exit 1
fi

cleanup_keychain() {
  if [[ -n "${_CATALYST_SIGNING_KEYCHAIN:-}" ]]; then
    security delete-keychain "$_CATALYST_SIGNING_KEYCHAIN" >/dev/null 2>&1 || true
  fi
}
trap cleanup_keychain EXIT

sign_identity="-"
timestamp_args=()

if [[ -n "${MACOS_CERTIFICATE_B64:-}" ]]; then
  keychain_password="${MACOS_KEYCHAIN_PASSWORD:-$(uuidgen)}"
  _CATALYST_SIGNING_KEYCHAIN="${RUNNER_TEMP:-/tmp}/catalyst-signing.keychain-db"
  cert_path="${RUNNER_TEMP:-/tmp}/catalyst-macos-signing.p12"

  echo "$MACOS_CERTIFICATE_B64" | base64 --decode > "$cert_path"
  security create-keychain -p "$keychain_password" "$_CATALYST_SIGNING_KEYCHAIN"
  security set-keychain-settings -lut 21600 "$_CATALYST_SIGNING_KEYCHAIN"
  security unlock-keychain -p "$keychain_password" "$_CATALYST_SIGNING_KEYCHAIN"
  security import "$cert_path" \
    -k "$_CATALYST_SIGNING_KEYCHAIN" \
    -P "${MACOS_CERTIFICATE_PASSWORD:-}" \
    -T /usr/bin/codesign \
    -T /usr/bin/security
  security set-key-partition-list \
    -S apple-tool:,apple:,codesign: \
    -s \
    -k "$keychain_password" \
    "$_CATALYST_SIGNING_KEYCHAIN"

  sign_identity="${MACOS_CODESIGN_IDENTITY:-Developer ID Application}"
  timestamp_args=(--timestamp)
  echo "Signing CATalyst.app with Developer ID identity: $sign_identity"
else
  echo "MACOS_CERTIFICATE_B64 not configured; using ad-hoc signature."
fi

if [[ ${#timestamp_args[@]} -gt 0 ]]; then
  codesign \
    --force \
    --deep \
    --options runtime \
    "${timestamp_args[@]}" \
    --sign "$sign_identity" \
    "$app_path"
else
  codesign \
    --force \
    --deep \
    --options runtime \
    --sign "$sign_identity" \
    "$app_path"
fi
codesign --verify --deep --strict --verbose=2 "$app_path"

rm -rf "$dmg_stage"
rm -f "$dmg_path" "$sha_path"
mkdir -p "$dmg_stage"
ditto "$app_path" "$dmg_stage/CATalyst.app"
ln -s /Applications "$dmg_stage/Applications"

hdiutil create \
  -volname "CATalyst ${version}" \
  -srcfolder "$dmg_stage" \
  -ov \
  -format UDZO \
  "$dmg_path"

if [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ]]; then
  echo "Submitting DMG for Apple notarization."
  xcrun notarytool submit "$dmg_path" \
    --apple-id "$APPLE_ID" \
    --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_SPECIFIC_PASSWORD" \
    --wait
  xcrun stapler staple "$dmg_path"
  xcrun stapler validate "$dmg_path"
else
  echo "Apple notarization credentials not configured; DMG is not notarized."
fi

digest="$(shasum -a 256 "$dmg_path" | awk '{print $1}')"
printf "%s  %s\n" "$digest" "$(basename "$dmg_path")" > "$sha_path"
echo "Created $dmg_path"
echo "Created $sha_path"
