#!/bin/zsh
# Optional notarization is explicit: NOTARY_PROFILE=<existing-profile> ... --notarize.
set -eu
set -o pipefail
PULSE_ROOT="${0:A:h:h}"
PULSE_PRODUCT="${PRODUCT_NAME:-Codex Lookout}"
PULSE_APP="${PULSE_OUTPUT_DIR:-$PULSE_ROOT/dist}/$PULSE_PRODUCT.app"
PULSE_NOTARIZE="${1:-}"
if [[ -n "$PULSE_NOTARIZE" && "$PULSE_NOTARIZE" != --notarize ]]; then
  print -u2 'Usage: scripts/package-release.sh [--notarize]'
  exit 2
fi
if [[ ! -x "$PULSE_APP/Contents/Resources/backend/pulse-backend" ]]; then
  print -u2 'Build the self-contained app with native/build.sh --release first.'
  exit 2
fi
PULSE_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$PULSE_APP/Contents/Info.plist")"
PULSE_SLUG="${PRODUCT_SLUG:-codex-lookout}"
PULSE_RELEASE_DIR="$PULSE_ROOT/dist/releases"
PULSE_ZIP="$PULSE_RELEASE_DIR/$PULSE_SLUG-$PULSE_VERSION-macos-arm64.zip"
mkdir -p "$PULSE_RELEASE_DIR"
codesign --verify --deep --strict "$PULSE_APP"
if [[ "$PULSE_NOTARIZE" == --notarize ]]; then
  : "${NOTARY_PROFILE:?Set an existing notarytool keychain profile name}"
  if ! codesign --display --verbose=4 "$PULSE_APP" 2>&1 | /usr/bin/grep -q 'Authority=Developer ID Application:'; then
    print -u2 'Notarization requires a Developer ID Application signed build.'
    exit 2
  fi
  PULSE_SUBMISSION="$(mktemp -d "$PULSE_ROOT/native/.build/notarization.XXXXXX")"
  trap 'rm -rf "$PULSE_SUBMISSION"' EXIT
  ditto -c -k --sequesterRsrc --keepParent "$PULSE_APP" "$PULSE_SUBMISSION/submit.zip"
  PULSE_NOTARY_ARGS=(--keychain-profile "$NOTARY_PROFILE")
  if [[ -n "${NOTARY_KEYCHAIN:-}" ]]; then
    PULSE_NOTARY_ARGS+=(--keychain "$NOTARY_KEYCHAIN")
  fi
  xcrun notarytool submit "$PULSE_SUBMISSION/submit.zip" "${PULSE_NOTARY_ARGS[@]}" --wait
  xcrun stapler staple "$PULSE_APP"
  xcrun stapler validate "$PULSE_APP"
  spctl --assess --type execute --verbose "$PULSE_APP"
fi
ditto -c -k --sequesterRsrc --keepParent "$PULSE_APP" "$PULSE_ZIP"
(cd "$PULSE_RELEASE_DIR" && shasum -a 256 "${PULSE_ZIP:t}" > "${PULSE_ZIP:t}.sha256")
print -r -- "$PULSE_ZIP"
