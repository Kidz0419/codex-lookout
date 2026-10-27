# Signal evidence and limits

Lookout observes existing local Codex sessions. It does not attach to the model's private reasoning, intercept traffic, or start replacement tasks. A useful status must state both **what was observed** and **what that observation cannot prove**.

Codex's local storage is an internal implementation detail, not a stable public API. The adapters below describe supported formats; a newer Codex release may need a compatibility update.

## Sources

| Source | Extracted evidence | Limits |
| --- | --- | --- |
| `state_5.sqlite` | Thread identity, title, model, timestamps, usage, and parent relationships | A thread update timestamp is not a model heartbeat. A cumulative counter is not a streaming speed. |
| `thread_history_1.sqlite` | Latest turn identity and status; item type, status, and paired start/end times | Old `inProgress` rows may remain after activity ends. A completed item may have no completion timestamp. |
| `logs_2.sqlite` | Allowlisted connection/retry classifications and safe numeric fields | An error needs the current thread and turn identity before it affects current-turn health. Log text is not sent to the UI. |
| Session JSONL | Normalized turn, item, tool, token, and compaction events | Reads are bounded to a 2 MiB tail or incremental chunk; truncated, missing, or malformed coverage is reported. |

SQLite connections use read-only URI mode and `PRAGMA query_only`. The rollout cache retains up to 2,400 normalized records per file. Raw prompts, reasoning, compaction content, tool arguments, and tool output are discarded from the returned event model. Session titles and paths remain potentially sensitive metadata; see [privacy](../PRIVACY.md).

## Stage is different from health

A **stage** describes the latest supported observation. A **health** assessment describes whether there is visible progress, a reason to look closer, or insufficient evidence.

| Stage observation | Safe interpretation |
| --- | --- |
| Reasoning item completed | Reasoning activity was observed recently. It does not prove that the model is still thinking. |
| Assistant output item | Output was observed recently. This is not a measurement of token arrival rate. |
| Tool started with no known completion | A tool appears to be executing; its own internal progress may be unavailable. |
| Explicit wait call | The task is waiting for a result. Waiting is not a confirmed failure. |
| Compaction started with no later completion/activity | Compaction is in progress according to an explicit lifecycle event. |
| Compaction completed, or top-level `compacted` | Compaction happened. Completed duration is fixed, not an increasing timer. |
| No reliable current event | The phase is unconfirmed. Do not default to “thinking.” |

The adapter normalizes event-type casing, including `ContextCompaction` / `contextCompaction` and `Reasoning` / `reasoning`. Top-level `compacted` records retain only safe event metadata; replacement history, summaries, and retained context are excluded.

Observed local samples have primarily supplied completed reasoning and compaction records. Recognition of in-progress compaction is covered by synthetic lifecycle tests; continuous live compaction tracking has not been verified on a real session.

## Progress and silence

Progress includes observed reasoning/output activity, successful tool activity, and compaction events. Error records, retries, failed tools, turn starts, and token-counter updates do not reset the progress clock. A counter update also does not clear an outstanding connection warning.

After **120 seconds without visible progress**, including a turn that has never produced its first progress event, the UI asks the user to check. It does not declare a hang. Long reasoning, a quiet tool, persistence delay, computer sleep, and a stalled request can all look similar from local records.

A stale `inProgress` turn with no supporting activity for more than 15 minutes becomes uncertain rather than being counted as definitely running. Missing data is separate from an observed task failure. Recent uncertain or failed tasks may remain visible for 24 hours without increasing the running count.

The native snapshot becomes stale after `max(12 seconds, 3 × configured sampling interval)`. The web dashboard uses its own 3-second polling cycle and marks old data separately. Freshness is about the observer's connection to its data, not a claim about the model's connection to its provider.

## Connection evidence and identity

Supported error classifications require a recognized source and message pattern, such as an explicit stream disconnect/retry or a failed WebSocket connection. A prompt or tool argument that merely contains “network timeout” must not trigger an alert.

Before an error changes current-turn health:

1. Its thread identity must match.
2. Its turn identity must match; a time window alone is insufficient because turns can overlap.
3. Its timestamp must fall inside the applicable turn and not exceed the sampling time by more than the small clock-tolerance window.
4. A later qualifying progress event may establish recovery; another retry does not.

Errors without sufficient identity are not promoted into current-turn connection diagnoses. Old-turn errors and implausible future events do not refresh the current task's state.

“Connection interrupted; retrying” is an observation. “Your Wi-Fi is slow” is a root-cause claim that these records cannot support. HTTP access errors and rate limits also do not prove a slow local network.

## Deliberately unavailable metrics

Lookout does not infer real-time tokens/second from sparse aggregate usage records. It does not assign global, unidentified delta events to individual sessions. It does not estimate completion percentages or remaining time, and does not issue network probes whose results might be mistaken for the current model request.

The official [Codex App Server documentation](https://learn.chatgpt.com/docs/app-server) describes typed turn, item, and usage events. Starting another App Server is not evidence that it observes already-running desktop tasks. A future streaming integration needs a verified, supported subscription tied to the current task before it can improve these claims.

## Regression expectations

Tests must cover stale running rows, completed tools without end timestamps, cross-turn errors, overlapping turns, future timestamps, malformed/truncated files, unavailable databases, child-task identity, PascalCase event types, compaction lifecycles, counter-only updates, long silence before the first progress event, and recovery after a real progress event. Fixtures must be synthetic and contain no private session contents.
