# Privacy

Codex Lookout is a local, passive observer. It does not require a Lookout account, API key, or cloud service. It has no analytics, crash-report upload, or automatic update check.

## Data it reads

The configured Codex folder defaults to `CODEX_HOME` or `~/.codex`. The collector opens supported SQLite databases read-only and reads bounded tails of session JSONL files. These source files can contain sensitive material; the collector must parse some records to extract the allowed metadata.

Returned snapshots contain session IDs and titles, project paths, model names, parent/child relationships, status and timestamps, event categories, tool names, token counters, and classified connection errors. Parsing is local. The UI does not receive full prompt bodies, reasoning text, tool arguments, tool output, authentication credentials, raw log bodies, or context-compaction contents. No authentication files are read.

Session titles can be derived from prompts and remain sensitive. Project paths may contain account or customer names. The native **hide titles** preference masks visible titles; it does not anonymize source files or the separate web dashboard. Review screens before sharing them.

## Storage and connections

- Preferences are stored locally using macOS preferences. Cached snapshots and parsed event metadata are held in process memory; Lookout does not create a session-history archive.
- The native monitor communicates with its own local helper process. It makes no external connectivity probe and does not send session metadata to a remote service.
- The optional web service binds to `127.0.0.1`. It rejects unexpected Host values and cross-site browser requests and serves no third-party assets. It has no user authentication: other processes running on your Mac can access this local endpoint.
- Clicking a session opens its Codex URL. The app's project/help links may open a browser at your request.
- Build scripts download build dependencies. CI processes checked-in synthetic test fixtures, not your Codex folder. This is separate from normal monitoring.

Lookout does not use the camera, take screenshots, record keystrokes, or change Codex's settings, databases, or running tasks. Launch at login is optional and starts Lookout, not a new Codex task.

## Removal and reports

Quit Lookout to end its monitor and any web service it started. Stop a separately launched web service in its terminal. Removing the app does not remove Codex data.

When reporting a problem, provide the application version, macOS version, chip architecture, source availability, and a synthetic reproduction. Do not upload `.codex`, databases, session JSONL, authentication files, raw logs, or unreviewed screenshots. See [SECURITY.md](SECURITY.md) for vulnerability reporting.
