r"""A live view of benchmark runs in progress.

Benchmark runs here take hours and speak only to a log file. That makes them invisible: the
only way to know whether a run is halfway or wedged is to tail a file and know the format.
This serves a page that reads those logs as they are written and shows, per run, what phase
it is in, how far through it is, and every score it has printed so far.

It is deliberately dependency-free -- `http.server` and the standard library, nothing else --
because it is a development tool and adding a web framework to this repo to watch a progress
bar would be a poor trade.

    uv run --package webgraph python benchmark/dashboard/server.py --logs <dir>

Then open http://127.0.0.1:8765. The page polls; the server re-reads the logs on each poll.
Nothing is cached, so a run that starts after the server does still appears.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent

# Every runner in benchmark/ prints these three shapes. Parsing them rather than asking the
# runners to emit structured progress keeps the runners unchanged and keeps this optional.
PROGRESS = re.compile(r"^\s*(extracted|scored|fetched)\s+([\d,]+)\s*/\s*([\d,]+)")
STAGE = re.compile(r"^\s*(scored)\s+(\S.*?)\s*$")
DATASET = re.compile(r"^\s*([\w.-]+):\s+([\d,]+)\s+(?:pages|rows|URLs)")
DONE = re.compile(r"^\s*([\w.-]+) done:\s+(.*)$")
PAIR = re.compile(r"([\w+.-]+)=([\d.]+)")

TITLES = {
    "wceb": "WCEB",
    "wcxb": "WCXB",
    "wmb545": "WebMainBench 545",
    "webmainbench": "WebMainBench",
    "scrape_evals": "Firecrawl scrape-evals",
    "zyte": "Zyte article-extraction",
    "cleaneval": "CleanEval",
}

EXPECTED = {"WCEB": 8}
"""Corpora per run, where the count is fixed and known. Absent means "do not claim a total"."""

WHAT = {
    "WCEB": "Eight corpora, 3,985 pages, ROUGE-LSum against 22 published systems.",
    "WCXB": "1,497 pages across seven page types, word-level F1.",
    "WebMainBench 545": "Edit distance over Markdown, tables and code graded separately.",
    "WebMainBench": "Edit distance over Markdown, tables and code graded separately.",
    "Firecrawl scrape-evals": "1,000 live fetches. The only benchmark that scores a real scrape.",
    "Zyte article-extraction": "181 news articles, 4-gram shingle F1.",
    "CleanEval": "2008 gold standards, scored with Evert's original Perl scorer.",
}


@dataclass
class Row:
    """One finished unit of work -- a dataset, a corpus, a split -- and its scores."""

    name: str
    scores: dict[str, float]


@dataclass
class Run:
    key: str
    title: str
    what: str
    phase: str
    """What it is doing now, in words a person can read."""

    done: int = 0
    total: int = 0
    unit: str = ""
    current: str = ""
    """The dataset or split being worked on."""

    rows: list[Row] = field(default_factory=list)
    corpora: str = ""
    """"5 of 8 corpora" for a multi-corpus run; empty when the run has only one."""

    tail: list[str] = field(default_factory=list)
    updated: float = 0.0
    stale: float = 0.0
    """Seconds since the log last grew. A run that stops growing is stuck or finished."""

    finished: bool = False


def title_for(path: Path) -> tuple[str, str]:
    stem = path.stem
    for key, title in TITLES.items():
        if stem.startswith(key):
            return title, WHAT.get(title, "")
    return stem, ""


def read(path: Path) -> Run:
    """Turn one log file into a Run. Tolerant by design: an unrecognised line is just tail."""
    title, what = title_for(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    run = Run(key=path.stem, title=title, what=what, phase="starting")
    run.updated = path.stat().st_mtime
    run.stale = max(0.0, time.time() - run.updated)

    for line in lines:
        if m := DATASET.match(line):
            run.current = m.group(1)
            run.total = int(m.group(2).replace(",", ""))
            run.done = 0
            run.unit = "pages"
            run.phase = f"extracting {run.current}"
        elif m := PROGRESS.match(line):
            verb, done, total = m.group(1), m.group(2), m.group(3)
            run.done = int(done.replace(",", ""))
            run.total = int(total.replace(",", ""))
            run.unit = "pages" if verb == "extracted" else "comparisons"
            run.phase = (
                f"{verb} {run.current}".strip() if run.current else verb
            )
        elif m := DONE.match(line):
            scores = {k: float(v) for k, v in PAIR.findall(m.group(2))}
            run.rows = [r for r in run.rows if r.name != m.group(1)]
            run.rows.append(Row(name=m.group(1), scores=scores))
            run.done = run.total
            run.phase = f"finished {m.group(1)}"
        elif m := STAGE.match(line):
            run.phase = f"scoring {m.group(2)}"

    # A multi-corpus run's progress bar restarts per corpus, so the bar alone understates
    # how far along it is. Name the corpus count beside it rather than inventing a global
    # percentage out of corpora of very different sizes.
    expected = EXPECTED.get(run.title)
    if run.rows:
        run.corpora = (
            f"{len(run.rows)} of {expected} corpora" if expected
            else f"{len(run.rows)} corpora done"
        )

    run.tail = lines[-6:]
    # Finished means the runner printed its final table -- nothing else. An earlier version
    # also called a run finished once its log had been quiet for five minutes, which was a
    # lie: the scoring phases here are silent for far longer than that, so a run in the
    # middle of its hardest work was reported as done. Quietness is shown as quietness.
    # Each runner prints one rule of equals signs, immediately before its final report, and
    # uses dashes for every sub-table above it. So the presence of that rule anywhere is the
    # completion signal; looking only at the tail missed it, because several pages of slice
    # tables follow it.
    run.finished = any(line.startswith("=" * 20) for line in lines)
    return run


def state(logs: Path) -> dict:
    runs = []
    for path in sorted(logs.glob("*.log")):
        try:
            runs.append(asdict(read(path)))
        except OSError:
            continue
    runs.sort(key=lambda r: (r["finished"], -r["updated"]))
    return {"runs": runs, "now": time.time()}


class Handler(BaseHTTPRequestHandler):
    logs: Path = Path()

    def log_message(self, *_args: object) -> None:
        """Silence the access log: one line per poll would bury the startup message."""
        return

    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # BaseHTTPRequestHandler dispatches on this exact name
        if self.path.startswith("/api/state"):
            self._send(json.dumps(state(self.logs)).encode(), "application/json")
            return
        page = (HERE / "index.html").read_bytes()
        self._send(page, "text/html; charset=utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", type=Path, required=True, help="directory of *.log files")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    Handler.logs = args.logs
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"benchmark dashboard on http://127.0.0.1:{args.port}  (reading {args.logs})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
