#!/bin/zsh
# Source build: ./native/build.sh
# Release: PULSE_BUILD_PYTHON=/path/to/python3 ./native/build.sh --release
set -eu
set -o pipefail
PULSE_ROOT="${0:A:h:h}"
PULSE_MODE="${1:---dev}"
if [[ "$PULSE_MODE" != --dev && "$PULSE_MODE" != --release ]]; then
  print -u2 'Usage: native/build.sh [--dev|--release]'
  exit 2
fi
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  print -u2 'This release target is Apple Silicon macOS. Intel releases are not validated.'
  exit 2
fi
PULSE_PRODUCT="${PRODUCT_NAME:-Codex Lookout}"
PULSE_EXECUTABLE="${PRODUCT_EXECUTABLE:-CodexLookout}"
PULSE_BUNDLE_ID="${PRODUCT_BUNDLE_ID:-io.github.kidz0419.codexlookout}"
PULSE_VERSION="${PRODUCT_VERSION:-0.1.0}"
PULSE_BUILD_NUMBER="${PRODUCT_BUILD_NUMBER:-1}"
PULSE_BUILD_DIR="$PULSE_ROOT/native/.build"
PULSE_OUTPUT_DIR="${PULSE_OUTPUT_DIR:-$PULSE_ROOT/dist}"
PULSE_IDENTITY="${CODE_SIGN_IDENTITY:--}"
mkdir -p "$PULSE_BUILD_DIR" "$PULSE_OUTPUT_DIR"
PULSE_WORK="$(mktemp -d "$PULSE_BUILD_DIR/stage.XXXXXX")"
trap 'rm -rf "$PULSE_WORK"' EXIT
PULSE_APP="$PULSE_WORK/$PULSE_PRODUCT.app"
mkdir -p "$PULSE_APP/Contents/MacOS" "$PULSE_APP/Contents/Resources"
if [[ "$PULSE_MODE" == --release ]]; then
  PULSE_PYTHON="${PULSE_BUILD_PYTHON:-python3}"
  "$PULSE_PYTHON" -c 'import sys, platform; assert sys.version_info >= (3, 10), "Release builds require Python 3.10+"; assert platform.machine() == "arm64", "Use native arm64 Python"'
  if [[ ! -x "$PULSE_BUILD_DIR/release-venv/bin/python" ]]; then
    "$PULSE_PYTHON" -m venv "$PULSE_BUILD_DIR/release-venv"
  fi
  PULSE_PYTHON="$PULSE_BUILD_DIR/release-venv/bin/python"
  "$PULSE_PYTHON" -m pip install --disable-pip-version-check -r "$PULSE_ROOT/scripts/requirements-build.txt"
  export PYINSTALLER_CONFIG_DIR="$PULSE_BUILD_DIR/pyinstaller-config"
  PULSE_SIGN_ARGS=()
  if [[ "$PULSE_IDENTITY" != - ]]; then
    PULSE_SIGN_ARGS=(--codesign-identity "$PULSE_IDENTITY")
  fi
  "$PULSE_PYTHON" -m PyInstaller --noconfirm --clean --onedir \
    --name pulse-backend --target-arch arm64 \
    --paths "$PULSE_ROOT" --paths "$PULSE_ROOT/native" \
    --add-data "$PULSE_ROOT/static:static" \
    --distpath "$PULSE_WORK/frozen" --workpath "$PULSE_BUILD_DIR/pyinstaller" \
    --specpath "$PULSE_WORK" "${PULSE_SIGN_ARGS[@]}" \
    "$PULSE_ROOT/native/backend_entry.py"
  ditto "$PULSE_WORK/frozen/pulse-backend" "$PULSE_APP/Contents/Resources/backend"
  "$PULSE_PYTHON" "$PULSE_ROOT/scripts/copy-runtime-licenses.py" "$PULSE_APP/Contents/Resources/Licenses"
else
  mkdir -p "$PULSE_APP/Contents/Resources/backend/static"
  cp "$PULSE_ROOT/collector.py" "$PULSE_ROOT/server.py" "$PULSE_ROOT/native/monitor.py" \
    "$PULSE_ROOT/native/backend_entry.py" "$PULSE_APP/Contents/Resources/backend/"
  cp "$PULSE_ROOT/static/index.html" "$PULSE_ROOT/static/styles.css" "$PULSE_ROOT/static/app.js" \
    "$PULSE_APP/Contents/Resources/backend/static/"
fi
PULSE_SWIFT_SOURCES=(native/Backend.swift native/PulseUI.swift native/main.swift)
if [[ -f "$PULSE_ROOT/native/Preferences.swift" ]]; then
  PULSE_SWIFT_SOURCES+=(native/Preferences.swift)
fi
# Relative input paths also keep #filePath literals free of the builder's home.
(
cd "$PULSE_ROOT"
xcrun swiftc -swift-version 5 -parse-as-library -O -target arm64-apple-macosx13.0 \
  -file-prefix-map "$PULSE_ROOT"=. \
  "${PULSE_SWIFT_SOURCES[@]}" \
  -framework AppKit -framework SwiftUI -framework Combine -framework ServiceManagement \
  -o "$PULSE_APP/Contents/MacOS/$PULSE_EXECUTABLE"
)
cp "$PULSE_ROOT/native/Info.plist" "$PULSE_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleExecutable $PULSE_EXECUTABLE" "$PULSE_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName $PULSE_PRODUCT" "$PULSE_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $PULSE_PRODUCT" "$PULSE_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $PULSE_BUNDLE_ID" "$PULSE_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $PULSE_VERSION" "$PULSE_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $PULSE_BUILD_NUMBER" "$PULSE_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :PulseBuildMode string ${PULSE_MODE#--}" "$PULSE_APP/Contents/Info.plist"
if [[ -f "$PULSE_ROOT/native/Resources/AppIcon.icns" ]]; then
  cp "$PULSE_ROOT/native/Resources/AppIcon.icns" "$PULSE_APP/Contents/Resources/AppIcon.icns"
  /usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string AppIcon' "$PULSE_APP/Contents/Info.plist"
fi
if [[ -f "$PULSE_ROOT/LICENSE" ]]; then
  cp "$PULSE_ROOT/LICENSE" "$PULSE_APP/Contents/Resources/LICENSE.txt"
fi
if [[ "$PULSE_MODE" == --release ]]; then
  "$PULSE_PYTHON" "$PULSE_ROOT/scripts/audit-build-paths.py" "$PULSE_APP"
fi
PULSE_OUTER_SIGN_ARGS=(--force --sign "$PULSE_IDENTITY")
if [[ "$PULSE_IDENTITY" != - ]]; then
  PULSE_OUTER_SIGN_ARGS+=(--options runtime --timestamp)
fi
codesign "${PULSE_OUTER_SIGN_ARGS[@]}" "$PULSE_APP"
codesign --verify --deep --strict "$PULSE_APP"
# Keep the old build until a complete signed replacement exists.
PULSE_DESTINATION="$PULSE_OUTPUT_DIR/$PULSE_PRODUCT.app"
if [[ -e "$PULSE_DESTINATION" ]]; then
  mv "$PULSE_DESTINATION" "$PULSE_WORK/previous.app"
fi
if ! mv "$PULSE_APP" "$PULSE_DESTINATION"; then
  if [[ -e "$PULSE_WORK/previous.app" ]]; then
    mv "$PULSE_WORK/previous.app" "$PULSE_DESTINATION"
  fi
  exit 1
fi
print -r -- "$PULSE_DESTINATION"
