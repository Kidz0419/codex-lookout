# Build, verify, and package

The native target is Apple Silicon, macOS 13+. Build on an arm64 Mac with Xcode command-line tools. Intel is not a validated release target. The local collector and optional web view use the Python standard library.

## Development app

Use Python 3.9+ and run:

```sh
./native/build.sh
open 'dist/Codex Lookout.app'
```

`--dev` is equivalent to no build argument. This build copies Python source into the app and uses an installed Python runtime. It is intended for development, not dependency-free distribution.

## Self-contained release

Use a native arm64 Python 3.10+; CI is configured for Python 3.12:

```sh
PULSE_BUILD_PYTHON=/path/to/python3 ./native/build.sh --release
```

The build creates a project-local environment under `native/.build/release-venv`, installs the versions pinned in `scripts/requirements-build.txt`, and uses PyInstaller's one-folder mode. The app contains:

- `Contents/MacOS/CodexLookout`: native Swift executable.
- `Contents/Resources/backend/pulse-backend`: bundled collector/web helper with its runtime.
- `Contents/Resources/Licenses`: bundled runtime notices.

Only project code, static assets, and runtime dependencies belong in the app. The build must not copy a user's `.codex` folder or local screenshots. A complete replacement app is staged before it replaces the previous `dist/` app.

## Verify

```sh
./scripts/test.sh
python3 scripts/smoke-release.py 'dist/Codex Lookout.app'
codesign --verify --deep --strict 'dist/Codex Lookout.app'
```

`test.sh` runs Python regressions and, on macOS, native model checks. The release smoke test exercises the packaged helper with synthetic data and an isolated Codex folder. It checks the bundled app rather than relying only on source imports.

An optional local integration check reads your real Codex metadata without showing the panel:

```sh
'dist/Codex Lookout.app/Contents/MacOS/CodexLookout' --self-check
```

Do not paste private metadata from local diagnostics into a public issue. A successful self-check proves the local collector connection; it does not prove notch layout, click handling, login behavior, or another Mac's compatibility.

## ZIP and checksum

```sh
./scripts/package-release.sh
cd dist/releases
shasum -a 256 -c codex-lookout-0.1.0-macos-arm64.zip.sha256
```

The archive contains `Codex Lookout.app`. The version is read from the app's `Info.plist`; update the command's version when packaging a later release. Build output and temporary environments are not source files to commit.

Default builds use an ad-hoc signature. This verifies bundle integrity locally, but is not Developer ID signing and does not confer notarization or clean-Mac acceptance.

## Optional Developer ID signing and notarization

For maintainers with an installed Developer ID Application certificate:

```sh
CODE_SIGN_IDENTITY='Developer ID Application: Your Name (TEAMID)' \
  PULSE_BUILD_PYTHON=/path/to/python3 ./native/build.sh --release
NOTARY_PROFILE=your-existing-keychain-profile \
  ./scripts/package-release.sh --notarize
```

The profile must already exist in the keychain. The packaging script requires Developer ID signing before submission, waits for Apple's result, staples and validates the ticket, and runs Gatekeeper assessment. Claim notarization only after those steps succeed for the exact distributed build. Never commit certificates, passwords, or keychain profiles.

## CI

`.github/workflows/ci.yml` runs the regression/build checks. The manually dispatched **Build release candidate** workflow builds the self-contained app and uploads a ZIP/checksum as a GitHub Actions artifact. It **does not publish a GitHub Release**.

The default workflow builds an ad-hoc candidate. Its optional notarization path requires these repository secrets:

| Secret | Value |
| --- | --- |
| `DEVELOPER_ID_CERTIFICATE_BASE64` | Base64-encoded signing certificate export |
| `DEVELOPER_ID_CERTIFICATE_PASSWORD` | Password for that export |
| `DEVELOPER_ID_APPLICATION` | Exact Developer ID Application signing identity |
| `APPLE_ID` | Apple account used for notarization |
| `APPLE_TEAM_ID` | Developer team ID |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password for notarization |

Signing uses a temporary CI keychain and removes signing material at the end. Publishing is a separate reviewed step: complete the [release checklist](release-checklist.md), then upload the verified archive and matching checksum with accurate signing and compatibility notes.
