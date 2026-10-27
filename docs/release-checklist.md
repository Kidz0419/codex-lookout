# Release checklist

Target: **Codex Lookout 0.1.0**, Apple Silicon, macOS 13+. This is the initial public preview. A configured workflow or a local build alone does not mean the project has been published.

## Source and package

- [x] MIT license and English/Chinese README provided.
- [x] Privacy, security, contribution, signal-boundary, and build documentation provided.
- [x] Synthetic regression suites and separate release smoke-test entry points provided.
- [x] Run the complete current regression suite after integration; record results in release notes.
- [x] Build the self-contained app and pass the packaged synthetic smoke test.
- [x] Verify bundle signature, bundle version, runtime notices, archive contents, and checksum.
- [x] Confirm the archive contains no Codex database, session log, private screenshot, local path, signing material, or development cache.
- [ ] Run the installed package on a separate Apple Silicon Mac without Python/Xcode, or explicitly label this acceptance as pending.

## User experience

- [x] Top-center hover expand/collapse confirmed during local development.
- [x] Synthetic native layout and local web paths checked during development.
- [x] Verify the integrated first-run flow, settings navigation, sampling changes, and source switching. Persistence and title masking have isolated regression coverage; live title masking remains in the device checklist.
- [ ] Verify task links, refresh, helper failure/recovery, and quitting only owned helper processes.
- [ ] Verify optional login startup and disable/uninstall behavior on an installed release.
- [ ] Check a real notch display, external display, display switching, and full-screen behavior; list any untested cases.
- [x] Review public previews for synthetic data and accurate labels.

## Signing and publication

- [x] Choose the exact candidate and state its signing status. Default builds are **ad-hoc signed, not notarized**.
- [ ] If using Developer ID, complete notarization, stapling, and Gatekeeper assessment for the same artifact.
- [ ] Confirm repository visibility, default branch, license, and public issue/security routes.
- [ ] Publish the source and tag the reviewed commit.
- [ ] Upload the verified ZIP and its matching SHA-256 file; include requirements, installation, and known limitations.
- [ ] Verify the public source, download, and checksum links from a fresh browser session.
- [ ] Update candidate wording and this checklist with actual results, without turning untested items into claims.

A public preview release can retain documented pending device checks. It should not claim notarization, support for untested architectures, precise live token speed, or confirmed hang detection.
