# Verification scope

Tests, rendered previews, and real interaction answer different questions. This page records those boundaries rather than presenting a local build as universal compatibility proof.

## Established during local development

- Synthetic Python regressions cover read-only collection, current-turn identity, safe event extraction, compaction, progress versus counters/retries, stale states, helper output, and HTTP behavior.
- Native model regressions cover parent/child grouping, recent uncertain/failed sessions, duplicate or cyclic relationships, and timestamp parsing.
- A real local Codex installation was read successfully through the packaged native process. The collector did not modify Codex data.
- A user confirmed that the top-center indicator expands on hover and collapses when the pointer leaves.
- The native expanded view was rendered from a synthetic fixture to inspect stage/health rows, child tasks, long explanations, and scrolling layout. An offscreen render is layout evidence, not live hover interaction.
- The local web view was exercised with real and synthetic data, filters, search, selection, empty states, and service interruption/recovery. Desktop and narrow layouts were checked.

These checks were performed during development on one Apple Silicon Mac. They do not certify all supported macOS versions or display modes. Test totals and exact build results belong in each release's notes; use `./scripts/test.sh` to verify the current source.

## 0.1.0 preview checks

The released preview passed 54 Python regressions, 18 native model checks, and 14 preferences checks locally. A self-contained package passed synthetic monitor/native/dashboard smoke checks, ZIP integrity, SHA-256 verification, and deep code-signature verification. The app is approximately 21 MB and its ZIP approximately 9.5 MB; the final archive is 9,977,812 bytes. These checks used ad-hoc signing. The release commit also passed the hosted [GitHub Checks run](https://github.com/Kidz0419/codex-lookout/actions/runs/40538285064), including native tests, a self-contained build, and packaged smoke checks. The optional signing/notarization workflow remains untested.

The final package passed an audit for private build paths in bundle bytes and 5,700 frozen Python code objects. Native first-run, settings/help navigation, refresh changes, empty source selection, and default-source recovery were exercised in the app. The actual helper process used the chosen 5-second interval; an empty source returned zero tasks/unavailable, and restoring the source returned a fresh real snapshot. Default settings were restored afterward.

Final ZIP SHA-256: `cb09009c3572bcdae1933a1da5dd88ac50f386957ca0f294ce7be3aae2b4f1bf`.

## Still requires release/device verification

- Self-contained release execution on a separate Mac with no Python or Xcode installation.
- Real built-in notch geometry outside a mirrored-display configuration, plus external/multiple-display transitions.
- End-to-end task-link activation, title privacy during live hover, and login-item approval on an installed release.
- Gatekeeper acceptance for a downloaded artifact. Ad-hoc signing is not equivalent to Developer ID signing or notarization.
- Continuous live compaction detection. Available local observations primarily contained completed compaction records; in-progress lifecycle behavior is synthetic-test coverage.
- Intel support, remote/cloud-session coverage, and accessibility behavior beyond the inspected paths.

## Reproduce the automated checks

```sh
./scripts/test.sh
PULSE_BUILD_PYTHON=/path/to/arm64/python3 ./native/build.sh --release
python3 scripts/smoke-release.py 'dist/Codex Lookout.app'
codesign --verify --deep --strict 'dist/Codex Lookout.app'
```

These commands are the intended validation sequence, not a claim that a new checkout has already passed. See [building](building.md) and the [release checklist](release-checklist.md). Public screenshots and fixtures must contain synthetic data only; local review captures are not release assets.

The [public v0.1.0 release](https://github.com/Kidz0419/codex-lookout/releases/tag/v0.1.0) was verified after publication: both ZIP and checksum were fetched without authentication and matched the local artifacts byte for byte.
