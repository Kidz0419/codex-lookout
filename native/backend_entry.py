"""Single entry point for the self-contained, read-only backend.

Release builds freeze this file and the Python interpreter with PyInstaller.
The native client invokes ``pulse-backend monitor ...`` or ``... server ...``.
There is no network listener unless the user explicitly opens the dashboard.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Explicit imports let the freezer discover the complete runtime. monitor's
# source-checkout loader otherwise searches for .py files absent from a bundle.
from collector import Collector
import monitor
import server


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Local Codex monitor backend")
    parser.add_argument("command", choices=("monitor", "server"))
    args = parser.parse_args(argv[:1])
    if args.command == "monitor":
        monitor._load_collector = lambda: Collector
        return monitor.main(argv[1:])
    original = sys.argv
    try:
        sys.argv = [original[0], *argv[1:]]
        server.main()
    finally:
        sys.argv = original
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
