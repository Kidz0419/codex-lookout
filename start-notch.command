#!/bin/zsh
set -eu
cd -- "${0:A:h}"
if [[ ! -x 'dist/Codex Lookout.app/Contents/MacOS/CodexLookout' ]]; then
  /bin/zsh native/build.sh
fi
open 'dist/Codex Lookout.app'
