# Changelog

## 0.1.0 — 2026-10-28 (public preview)

First public version of Codex Lookout, previously developed locally as Codex Pulse.

- Native macOS notch/top-center status indicator with hover details and a menu-bar fallback.
- Per-session stage, health, elapsed time, time since visible progress, and tool duration.
- Parent/child task grouping; recent uncertain and failed sessions remain visible without inflating the running count.
- Conservative current-turn connection diagnostics, explicit stale-data states, and helper recovery.
- Settings for the Codex data folder, sampling interval, task limit, display selection, title privacy, and optional launch at login.
- Optional loopback web dashboard with search, filters, evidence details, and synthetic examples.
- Self-contained Apple Silicon release packaging, synthetic regression tests, and CI workflows.
- MIT licensing, English/Chinese documentation, privacy boundaries, and contributor guidance.

This preview passed 54 Python regressions, 18 native model checks, 14 preferences checks, packaged runtime smoke tests, and local first-run/settings checks. See the [release checklist](docs/release-checklist.md) for pending device acceptance. Intel, remote/cloud sessions, accurate live token throughput, and confirmed hang detection are not supported in this version. Default builds are not Developer ID signed or notarized.
