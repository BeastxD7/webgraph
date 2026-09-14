"""Run a command with its output in a run log the dashboard can read.

    uv run python tools/run_logged.py wceb-main -- uv run python benchmark/wceb/run.py --corpus ...
    uv run python tools/run_logged.py --runs /tmp/runs zyte-cand -- uv run python benchmark/article_extraction/run.py --corpus ...

Writes `runs/<label>.log` (stdout and stderr, as they arrive) and `runs/<label>.meta.json`
(command, working directory, pid, start; then end and exit code), which is what
`tools/runs_dashboard.py` shows as a card with a state, a clock and a progress bar. A
second run with the same label gets a numbered suffix rather than overwriting the first.

On macOS the command runs under `caffeinate -i` when it is available, because a
two-hour board run on a laptop that sleeps on battery is a run that stops at 17:18 and
looks like a hang the next morning. `--no-caffeinate` turns that off.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _unique(directory: Path, label: str) -> Path:
    log = directory / f"{label}.log"
    n = 2
    while log.exists() or log.with_suffix(".meta.json").exists():
        log = directory / f"{label}-{n}.log"
        n += 1
    return log


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("label", help="a short name for the run, used as the file name")
    parser.add_argument("--runs", type=Path, default=Path("runs"), help="the run directory (default ./runs)")
    parser.add_argument("--no-caffeinate", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command to run")
    args = parser.parse_args()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        parser.error("give the command after --")

    args.runs.mkdir(parents=True, exist_ok=True)
    log = _unique(args.runs, args.label)
    meta = log.with_suffix(".meta.json")
    if sys.platform == "darwin" and not args.no_caffeinate and shutil.which("caffeinate"):
        command = ["caffeinate", "-i", *command]

    started = time.time()
    with log.open("wb") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, cwd=os.getcwd())
        meta.write_text(
            json.dumps(
                {"command": " ".join(command), "cwd": os.getcwd(), "pid": process.pid, "started": started},
                indent=1,
            )
        )
        print(f"{log}  (pid {process.pid})")
        try:
            code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            code = process.wait()
    record = json.loads(meta.read_text())
    record.update({"ended": time.time(), "exit_code": code})
    meta.write_text(json.dumps(record, indent=1))
    return code


if __name__ == "__main__":
    sys.exit(main())
