"""A live view of the benchmark runs on this machine, in the browser.

A board run takes minutes to hours and prints its progress to a log nobody is watching.
This serves one page that shows every run in the run directories -- running, finished or
failed -- with its elapsed time, a progress bar read from the runner's own `N/M` lines,
the last lines it printed and the result lines once they land. The page polls every
three seconds; nothing is installed and nothing is written.

    uv run python tools/runs_dashboard.py                      # watches ./runs
    uv run python tools/runs_dashboard.py --runs /path/a --runs /path/b --port 8765

Start a run through `tools/run_logged.py` so its command, pid, start and exit are recorded
beside the log and the state is exact; a bare `*.log` in a run directory is shown too,
with its state inferred from the file (a `Traceback` at the end means failed, a final
`done` line or ten quiet minutes means finished, a change in the last three minutes
means running -- so a bare log of a runner that prints no final line shows "running"
for up to ten minutes after it exits). The progress bar reads the runner's own counter
lines (`extracted 200/738`, `scored 1000/1476`, `12/23 sites`), never a result line.

Stdlib only, on purpose: it must work on a machine where the engine's optional extras
are not installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

_PROGRESS = re.compile(
    r"(?:extracted|scored|fetched|processed|page|site|done|progress|\bat)\s+(\d+)\s*/\s*(\d+)(?![\d.])"
    r"|^\s*(\d+)\s*/\s*(\d+)\b",
    re.IGNORECASE,
)
_RESULT = re.compile(
    r"done:|mean F1|\bF1\b|overall|median|\bP\s+R\b|^\s*\w[\w+-]*\s+\d\.\d{3}", re.IGNORECASE
)
_FAILED = re.compile(r"Traceback \(most recent call last\)|Killed: 9|MemoryError")
QUIET_RUNNING_SECONDS = 180
QUIET_FINISHED_SECONDS = 600
TAIL_LINES = 6
RESULT_LINES = 40


@dataclass
class Run:
    name: str
    directory: str
    state: str  # running | finished | failed
    started: float | None
    ended: float | None
    elapsed_seconds: float
    last_change: float
    progress_done: int | None
    progress_total: int | None
    milestone: str
    tail: list[str]
    results: list[str]
    command: str
    exit_code: int | None
    log_bytes: int


def _pid_alive(pid: int | None) -> bool | None:
    if not pid:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_tail(path: Path, max_bytes: int = 256_000) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        return handle.read().decode("utf-8", "replace")


def _inspect(log: Path) -> Run:
    meta_path = log.with_suffix(".meta.json")
    meta: dict[str, object] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            meta = {}
    stat = log.stat()
    text = _read_tail(log)
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    now = time.time()

    done: int | None = None
    total: int | None = None
    milestone = ""
    for line in lines:
        # The last counter printed is the current stage; a board run prints one per
        # corpus, so the bar shows where the run is now, not a total nobody printed.
        for match in _PROGRESS.finditer(line):
            a = int(match.group(1) or match.group(3))
            b = int(match.group(2) or match.group(4))
            if b >= max(a, 2):
                done, total = a, b
        if "done:" in line or line.strip().endswith("done") or ":" in line and "pages" in line:
            milestone = line.strip()
    results = [line for line in lines if _RESULT.search(line)][-RESULT_LINES:]
    # A traceback near the end is a crash; one in the middle was a page the runner
    # reported and moved past.
    crashed = bool(_FAILED.search("\n".join(lines[-40:]))) and not (lines and lines[-1].strip() == "done")

    raw_pid = meta.get("pid")
    pid = raw_pid if isinstance(raw_pid, int) else None
    raw_exit = meta.get("exit_code")
    exit_code = raw_exit if isinstance(raw_exit, int) else None
    raw_started = meta.get("started")
    started = float(raw_started) if isinstance(raw_started, (int, float)) else None
    raw_ended = meta.get("ended")
    ended = float(raw_ended) if isinstance(raw_ended, (int, float)) else None
    if started is None:
        started = float(getattr(stat, "st_birthtime", stat.st_ctime))

    alive = _pid_alive(pid)
    if exit_code is not None:
        state = "finished" if exit_code == 0 else "failed"
    elif alive is True:
        state = "running"
    elif alive is False:
        state = "failed" if crashed else "finished"
    elif crashed:
        state = "failed"
    elif lines and lines[-1].strip() == "done":
        state = "finished"
    elif now - stat.st_mtime < QUIET_RUNNING_SECONDS:
        state = "running"
    elif now - stat.st_mtime > QUIET_FINISHED_SECONDS:
        state = "finished"
    else:
        state = "running"
    end = ended if ended is not None else (stat.st_mtime if state != "running" else now)
    return Run(
        name=log.stem,
        directory=str(log.parent),
        state=state,
        started=started,
        ended=ended,
        elapsed_seconds=max(0.0, end - started),
        last_change=stat.st_mtime,
        progress_done=done,
        progress_total=total,
        milestone=milestone,
        tail=lines[-TAIL_LINES:],
        results=results,
        command=str(meta.get("command", "")),
        exit_code=exit_code,
        log_bytes=stat.st_size,
    )


def scan(directories: list[Path]) -> list[Run]:
    runs: list[Run] = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for log in sorted(directory.glob("*.log")):
            try:
                runs.append(_inspect(log))
            except OSError:
                continue
    order = {"running": 0, "failed": 1, "finished": 2}
    runs.sort(key=lambda r: (order[r.state], -(r.last_change)))
    return runs


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>webgraph runs</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--muted:#6b7280;--line:#e5e7eb;--run:#2563eb;--ok:#16a34a;--bad:#dc2626;--bar:#e5e7eb}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a20;--ink:#e6e8eb;--muted:#9aa3ad;--line:#2a2f37;--bar:#2a2f37}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:20px 16px}
h1{font-size:18px;margin:0 0 4px}.sub{color:var(--muted);margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;min-width:0}
.head{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.name{font-weight:600;word-break:break-all}.dir{color:var(--muted);font-size:12px;word-break:break-all}
.state{font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;white-space:nowrap}
.state.running{background:color-mix(in srgb,var(--run) 15%,transparent);color:var(--run)}
.state.finished{background:color-mix(in srgb,var(--ok) 15%,transparent);color:var(--ok)}
.state.failed{background:color-mix(in srgb,var(--bad) 15%,transparent);color:var(--bad)}
.bar{height:8px;background:var(--bar);border-radius:4px;overflow:hidden;margin:10px 0 4px}
.bar>i{display:block;height:100%;background:var(--run);transition:width .6s}
.finished .bar>i{background:var(--ok)}.failed .bar>i{background:var(--bad)}
.meta{color:var(--muted);font-size:12px;display:flex;gap:12px;flex-wrap:wrap}
pre{margin:8px 0 0;font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;word-break:break-word;color:var(--muted);max-height:150px;overflow:auto}
pre.results{color:var(--ink);max-height:320px}
details{margin-top:6px}summary{cursor:pointer;color:var(--muted);font-size:12px}
.pulse{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--run);margin-right:6px;animation:p 1.2s infinite}
@keyframes p{0%,100%{opacity:.25}50%{opacity:1}}
.empty{color:var(--muted)}
</style></head><body>
<h1>webgraph runs</h1><div class="sub" id="sub">loading…</div>
<div class="grid" id="grid"></div>
<script>
const fmt=s=>{s=Math.round(s);const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return (h?h+'h ':'')+(h||m?m+'m ':'')+x+'s'};
const ago=t=>fmt(Date.now()/1000-t)+' ago';
const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function tick(){
  let data;try{data=await (await fetch('/api/runs')).json()}catch(e){document.getElementById('sub').textContent='dashboard stopped';return}
  const runs=data.runs;const running=runs.filter(r=>r.state==='running').length;
  document.getElementById('sub').innerHTML=(running?'<span class="pulse"></span>'+running+' running · ':'')+runs.length+' runs in '+data.directories.length+' director'+(data.directories.length===1?'y':'ies')+' · refreshed '+new Date().toLocaleTimeString();
  const grid=document.getElementById('grid');
  if(!runs.length){grid.innerHTML='<div class="empty">No *.log files yet. Start a run with <code>uv run python tools/run_logged.py &lt;label&gt; -- &lt;command&gt;</code>.</div>';return}
  grid.innerHTML=runs.map(r=>{
    const pct=r.progress_total?Math.min(100,Math.round(100*r.progress_done/r.progress_total)):(r.state==='finished'?100:0);
    return `<div class="card ${r.state}"><div class="head"><div><div class="name">${esc(r.name)}</div><div class="dir">${esc(r.directory)}</div></div><span class="state ${r.state}">${r.state}</span></div>
    <div class="bar"><i style="width:${pct}%"></i></div>
    <div class="meta"><span>${r.progress_total?r.progress_done+' / '+r.progress_total+' ('+pct+'%)':'no counter yet'}</span><span>elapsed ${fmt(r.elapsed_seconds)}</span><span>last output ${ago(r.last_change)}</span>${r.exit_code!==null?'<span>exit '+r.exit_code+'</span>':''}</div>
    ${r.milestone?'<div class="meta" style="margin-top:4px"><span>'+esc(r.milestone)+'</span></div>':''}
    <pre>${esc(r.tail.join('\\n'))}</pre>
    ${r.results.length?'<details open><summary>results ('+r.results.length+' lines)</summary><pre class="results">'+esc(r.results.join('\\n'))+'</pre></details>':''}
    ${r.command?'<details><summary>command</summary><pre>'+esc(r.command)+'</pre></details>':''}
    </div>`}).join('');
}
tick();setInterval(tick,3000);
</script></body></html>
"""


def serve(directories: list[Path], port: int, open_browser: bool) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            if parts.path == "/api/runs":
                body = json.dumps(
                    {"directories": [str(d) for d in directories], "runs": [asdict(r) for r in scan(directories)]}
                ).encode()
                self._send(200, "application/json", body)
            elif parts.path == "/api/log":
                name = parse_qs(parts.query).get("name", [""])[0]
                for directory in directories:
                    candidate = directory / f"{name}.log"
                    if name and "/" not in name and candidate.is_file():
                        self._send(200, "text/plain; charset=utf-8", _read_tail(candidate, 2_000_000).encode())
                        return
                self._send(404, "text/plain", b"no such log")
            elif parts.path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE.encode())
            else:
                self._send(404, "text/plain", b"not found")

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"webgraph runs dashboard: {url}  (watching {', '.join(str(d) for d in directories)})")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", action="append", type=Path, help="a directory of run logs (repeatable; default ./runs)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    parser.add_argument("--once", action="store_true", help="print the runs as JSON and exit (no server)")
    args = parser.parse_args()
    directories = args.runs or [Path("runs")]
    if args.once:
        print(json.dumps([asdict(r) for r in scan(directories)], indent=1))
        return 0
    serve(directories, args.port, args.open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
