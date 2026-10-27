# Contributing

Thanks for helping make Codex sessions easier to understand. Small compatibility fixes, clearer status wording, translations, and accessibility improvements are useful contributions.

## Get started

1. Read [README.md](README.md), [signal evidence](docs/signal-evidence.md), and [PRIVACY.md](PRIVACY.md).
2. Build on an Apple Silicon Mac with Xcode command-line tools and Python. The collector and web view use Python's standard library; release packaging has separate pinned dependencies.
3. Run `./scripts/test.sh`. For packaging changes, also build a release and run the synthetic package smoke test in [docs/building.md](docs/building.md).
4. Open a pull request explaining the user-visible problem, the change, and the checks you ran.

Use an issue first for larger changes to collection, permissions, network access, or supported platforms so the data and compatibility boundaries can be reviewed.

## Project map

| Area | Responsibility |
| --- | --- |
| `collector.py` | Read-only adapters, identity/time filtering, stages, and health judgments |
| `server.py`, `static/` | Loopback detail dashboard and synthetic demo |
| `native/` | Swift macOS app, settings, process lifecycle, and JSONL collector entry |
| `tests/`, `native/tests/` | Synthetic collector/server and native model regressions |
| `scripts/`, `.github/workflows/` | Test, package, sign, and CI workflows |
| `docs/` | Signal contracts, build instructions, and verification boundaries |

## Rules that protect trust

- Keep observed facts, inference, and unknown states distinct. An old `inProgress` field is not a heartbeat.
- Match connection errors to the current thread **and turn**. Text that merely mentions “timeout” is not an error event.
- Retries and token-counter updates are not progress. Do not invent tokens/second, completion percentages, or ETAs from sparse records.
- Do not include prompts, reasoning, tool arguments/output, credentials, raw logs, or private fixtures in patches.
- Collection must remain read-only. Task mutation, new external requests, or expanded data collection need an explicit design discussion.
- Keep demo and real data clearly separated. Prefer small synthetic fixtures over recorded sessions.
- Include a regression test when changing parsing, health decisions, identity filtering, or process recovery. For visual changes, report the device/display mode and show a synthetic preview.

## Review and conduct

Describe the behavior rather than the development conversation. Separate automated tests, offscreen layout checks, and actual device interaction in your validation notes. Be specific and respectful in reviews; challenge ideas without attacking people. Do not publish another person's data.

Contributions are provided under the project's [MIT license](LICENSE). Keep required notices for third-party components. No contributor agreement is required.
