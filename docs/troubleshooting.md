# Troubleshooting

## The indicator is missing

Use the menu-bar icon to expand the panel or open settings. Check the selected display. Automatic placement uses the system's reported notch geometry; otherwise it uses the top center. Mirrored displays can report a different screen geometry than the physical built-in display. Select the main-display option when appropriate.

Lookout is an accessory app and does not need a Dock icon. Quitting it removes both the indicator and its menu-bar item. Reopen the app to resume observation.

## No tasks, missing data, or an old snapshot

Check the Codex folder in settings. A normal installation uses `~/.codex`, while a custom setup may use `CODEX_HOME`. Select the folder containing the supported databases, not a project repository. Lookout also recognizes a selected parent folder that contains `.codex`.

Open a local Codex task and refresh Lookout. The collector only inspects the configured number of recent unarchived local tasks; archived, older-than-limit, remote, and cloud tasks may not appear. Increase the task limit if necessary.

A database format change, unreadable file, or temporary collection failure can leave the last snapshot visible with a warning. This is a monitoring problem, not proof that a Codex task failed. Lookout retries collection and restarts its own failed helper with backoff. It does not restart Codex.

## A task says “needs attention,” but is still working

This is possible. More than 120 seconds without a visible progress event is a prompt to inspect the task, not a hang diagnosis. Quiet tools and long reasoning can legitimately take time. Read the stage, tool duration, and evidence, then click the session to check Codex.

A token-counter update or repeated connection retry does not count as progress. A connection warning describes a recorded error; it does not establish whether the cause is your network, proxy, or the upstream service.

## The app will not open after download

Default release candidates are ad-hoc signed and are not notarized. Verify the download and checksum, then use the system's explicit approval flow if you trust that build, or build from source. An integrity failure or “damaged” result should be investigated against the exact archive; do not disable platform security globally.

If reporting the problem, include the release version, macOS version, chip architecture, and exact non-sensitive message. Do not include your Codex data directory.

## Login startup does not work

Launch at login is opt-in. Enable it in Lookout's settings and follow any macOS approval prompt. Install the app in a stable location such as Applications before enabling it. If macOS shows it as awaiting approval or unavailable, check the system's login-item settings. Source builds and relocated apps can behave differently from an installed release.

## The web dashboard will not open

The optional dashboard uses `127.0.0.1:4318`. Another service may already occupy that port, or an existing Lookout dashboard may use a different folder/task limit. The native app checks the existing service before reusing it and reports a mismatch rather than silently showing another data source.

Stop only the service you started, then try again. For a source-launched dashboard, choose another port if needed:

```sh
python3 server.py --port 4319 --codex-home ~/.codex
```

The native menu still targets its configured default port. A terminal-launched service stays running until you stop it with Ctrl+C.

## Reset or uninstall

To reset local preferences, quit Lookout first and run:

```sh
defaults delete io.github.kidz0419.codexlookout
```

The command may report that the domain does not exist if no preferences were saved. It does not delete Codex conversations. Disable login startup before removing the app; deleting preferences alone is not an instruction to macOS to unregister a login item.

To uninstall, turn off login startup, quit from the menu bar, remove the app, and stop any independently launched dashboard. Your `.codex` folder belongs to Codex and should not be removed as part of uninstalling Lookout.

## Report a compatibility issue

Use the [bug template](https://github.com/Kidz0419/codex-lookout/issues/new/choose). Include versions, display mode, the source-availability message, and a minimal synthetic reproduction. Screenshots must have titles and paths reviewed or hidden. Never attach raw databases, session JSONL, authentication files, or full logs.
