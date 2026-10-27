#!/bin/zsh
# Runs only on an ephemeral GitHub-hosted runner after a signed build is requested.
set -eu
if [[ "${GITHUB_ACTIONS:-}" != true ]]; then
  print -u2 'This helper is reserved for the ephemeral CI runner.'
  exit 2
fi
: "${PULSE_CERTIFICATE_BASE64:?Missing Developer ID certificate secret}"
: "${PULSE_CERTIFICATE_PASSWORD:?Missing certificate password secret}"
: "${PULSE_SIGNING_IDENTITY:?Missing Developer ID Application identity secret}"
: "${PULSE_APPLE_ID:?Missing Apple ID secret}"
: "${PULSE_TEAM_ID:?Missing team ID secret}"
: "${PULSE_APPLE_PASSWORD:?Missing app-specific password secret}"
PULSE_KEYCHAIN="$RUNNER_TEMP/codex-lookout-signing.keychain-db"
PULSE_CERTIFICATE="$RUNNER_TEMP/codex-lookout-certificate.p12"
PULSE_KEYCHAIN_PASSWORD="$(openssl rand -hex 24)"
printf '::add-mask::%s\n' "$PULSE_KEYCHAIN_PASSWORD"
printf '%s' "$PULSE_CERTIFICATE_BASE64" | base64 --decode > "$PULSE_CERTIFICATE"
security create-keychain -p "$PULSE_KEYCHAIN_PASSWORD" "$PULSE_KEYCHAIN"
security set-keychain-settings -lut 21600 "$PULSE_KEYCHAIN"
security unlock-keychain -p "$PULSE_KEYCHAIN_PASSWORD" "$PULSE_KEYCHAIN"
security import "$PULSE_CERTIFICATE" -P "$PULSE_CERTIFICATE_PASSWORD" -A -t cert -f pkcs12 -k "$PULSE_KEYCHAIN"
security set-key-partition-list -S apple-tool:,apple: -k "$PULSE_KEYCHAIN_PASSWORD" "$PULSE_KEYCHAIN"
security list-keychains -d user -s "$PULSE_KEYCHAIN" login.keychain-db
xcrun notarytool store-credentials codex-lookout-ci --apple-id "$PULSE_APPLE_ID" \
  --team-id "$PULSE_TEAM_ID" --password "$PULSE_APPLE_PASSWORD" --keychain "$PULSE_KEYCHAIN"
printf 'CODE_SIGN_IDENTITY=%s\nNOTARY_PROFILE=codex-lookout-ci\nNOTARY_KEYCHAIN=%s\n' "$PULSE_SIGNING_IDENTITY" "$PULSE_KEYCHAIN" >> "$GITHUB_ENV"
