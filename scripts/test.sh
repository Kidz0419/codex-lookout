#!/bin/zsh
set -eu
PULSE_ROOT="${0:A:h:h}"
cd "$PULSE_ROOT"
"${PULSE_TEST_PYTHON:-python3}" -m unittest discover -s tests -v
if [[ "$(uname -s)" == Darwin ]]; then
  mkdir -p native/.build
  PULSE_TEST_SOURCES=(native/Backend.swift native/tests/main.swift)
  if [[ -f native/Preferences.swift ]]; then
    PULSE_TEST_SOURCES+=(native/Preferences.swift)
  fi
  xcrun swiftc -swift-version 5 -target arm64-apple-macosx13.0 \
    "${PULSE_TEST_SOURCES[@]}" \
    -framework AppKit -framework Combine -framework SwiftUI -framework ServiceManagement -o native/.build/backend-tests
  native/.build/backend-tests
  if [[ -f native/tests/preferences-main.swift ]]; then
    xcrun swiftc -swift-version 5 -parse-as-library -target arm64-apple-macosx13.0 \
      native/Backend.swift native/Preferences.swift native/tests/preferences-main.swift \
      -framework AppKit -framework SwiftUI -framework Combine -framework ServiceManagement \
      -o native/.build/preferences-tests
    native/.build/preferences-tests
  fi
fi
