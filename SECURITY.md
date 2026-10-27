# Security

## Reporting a vulnerability

Please avoid posting exploit details, credentials, private session content, or raw `.codex` files in a public issue.

Use GitHub's **Report a vulnerability** option on this repository's Security page when private vulnerability reporting is enabled. If that option is unavailable, open a minimal issue titled **Security contact requested** without sensitive details so a private reporting route can be arranged. Do not assume an unlisted email address is monitored.

Include the affected version, operating system, impact, reproduction steps using synthetic data, and any proposed fix. This is a volunteer project; there is no guaranteed response SLA.

## Scope and support

Security fixes target the latest release and the default development branch. There is no separate maintenance commitment for older versions during the initial 0.x releases.

Lookout reads local Codex files with the current user's permissions. The optional HTTP dashboard is loopback-only, validates Host/Origin, and does not offer write endpoints. It is **not a security boundary against other processes under the same account**. Session titles and paths can be private even when raw contents are filtered.

Default distribution builds are ad-hoc signed. Developer ID signing and Apple notarization are optional release steps, and must be stated per release rather than assumed. Verify the release's source and SHA-256 checksum. Do not publish signing credentials or bypass platform security globally to run Lookout.

See [PRIVACY.md](PRIVACY.md) for collected fields and [docs/building.md](docs/building.md) for the release process.
