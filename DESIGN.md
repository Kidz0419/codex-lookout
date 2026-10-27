# Codex Lookout interface

## Primary surface

A native macOS notch/top-center accessory answers a small question: **can I keep waiting, or should I check a session?** Hover reveals the evidence. The panel does not take keyboard focus, and the menu bar provides a reliable secondary entry point.

The compact state shows the product identity, running-conversation count, and status color. On a notch display, indicators reserve the camera gap reported by the system. Without that geometry, the app uses a top-center capsule. Expansion is limited to a readable width and height; long session lists scroll. Pointer exit collapses the panel after a short delay, and reduced-motion preferences are respected.

## Expanded content

Each conversation has a readable title, separate **stage** and **health** rows, turn duration, time since visible progress, and current tool/duration when available. Attention explanations wrap directly below the task instead of being hidden in tooltips. Child tasks remain visible in their parent's group. Recent uncertain or failed tasks do not inflate the running count.

A completed parent with active children remains visible. Clicking a task opens its Codex thread. The footer shows local sampling information and refresh; the browser is optional. Collection errors and stale snapshots are visible above the task content and cannot look like a healthy live feed.

Settings live in a normal interactive window, separate from the nonactivating hover panel. The first-run flow explains the local data source and privacy boundary. Hiding titles is a native display preference. Login startup requires an explicit opt-in.

## Color and language

Use green for recent observed progress, amber for attention/connection warnings or stale data, and neutral gray for waiting, unknown, or idle states. Always pair color with text. Avoid completion percentages, ornamental charts, or animations that imply data is flowing when it is not.

The UI is currently Simplified Chinese. Status wording must describe observations: “recent reasoning activity” is different from “currently thinking”; “compaction completed” is different from “compacting.” Preserve this distinction in future translations.

## Optional web details

The web view is a quiet, dense workspace with a task list and persistent evidence inspector. Warm neutral surfaces, navy selection, native sans typography, tabular time values, and visible focus rings keep it readable. At narrow widths the views stack without horizontal overflow.

Search and state filters narrow the task list. A selected task shows its diagnosis, confidence, action suggestion, stage, elapsed durations, sampled token usage, evidence timeline, and data coverage. Preserve selection by task ID and use stable ordering rather than moving rows after every activity event. Keep synthetic demo mode prominent and separate from real data.

## Verification boundary

Top-center hover behavior has been user-verified during local development. Synthetic offscreen SwiftUI renders check text and layout. Neither proves real built-in notch geometry, login-item behavior, nor all display transitions; those require device interaction and are recorded in the release checklist.
