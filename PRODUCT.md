# Codex Lookout

<!-- impeccable:product-schema 1 -->

## Platform

Native macOS accessory for Apple Silicon, with an optional local web detail view.

## Users

People running several local Codex conversations who need to know whether work is progressing, waiting, or worth checking.

## Product Purpose

Make the decision to keep waiting or return to a task easier using visible evidence: observed stage, recent progress, tool duration, and explicit problems. The primary surface is the notch/top-center hover panel, so checking health does not require opening a browser.

## Operating Context

Lookout reads supported local Codex records without moving sessions to a new client. It uses system-reported notch geometry and falls back to top-center placement. The menu bar provides settings, a secondary entry point, and quit. The panel does not take keyboard focus.

The native interface currently uses Simplified Chinese. English and Chinese documentation support the first open-source release. The project is independent of OpenAI.

## Capabilities and Constraints

- Read-only database and bounded session-file collection; no authentication-file reads or external probes.
- Separate stage and health fields, with explicit uncertainty and stale-data handling.
- Defaults of 2-second sampling and 200 recent unarchived local tasks; configurable sampling and limits. Web source mode defaults to 80 tasks and a 3-second cycle.
- Parent/child grouping; running children retain the parent conversation in view. Recent uncertain/failed tasks are visible without increasing the running count.
- Preferences for data folder, refresh interval, task limit, automatic/main display, hidden native titles, and opt-in login startup.
- No camera or accessibility permission requirement. Session titles and paths remain sensitive; title hiding is a presentation preference, not anonymization.
- Self-contained release packaging; source development builds use an installed Python runtime. Default builds are ad-hoc signed.
- No remote/cloud coverage, precise streaming token speed, completion estimate, confirmed hang diagnosis, or task-control action.
- Internal Codex formats may change. Unavailable or incomplete data is visible instead of being interpreted as task failure.

## Product Principles

1. Separate facts, inferences, and unknowns.
2. Silence is a reason to inspect, not proof of a hang.
3. Repeated retries and counter updates are not meaningful progress.
4. Never show stale snapshots as fresh observations.
5. Do not mutate, restart, or interrupt monitored tasks.
6. Keep the primary health explanation visible in the native panel.
7. State release and device verification limits explicitly.
