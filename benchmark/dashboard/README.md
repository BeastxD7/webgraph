# Live benchmark dashboard

Benchmark runs here take hours and speak only to a log file. This serves a page that reads
those logs as they are written, so a long run reports all the way through instead of only at
the end.

```
uv run --package webgraph python benchmark/dashboard/server.py --logs <dir of *.log>
```

Then open <http://127.0.0.1:8765>. It polls every 1.5 seconds and re-reads the logs each
time, so a run started after the server still appears.

Point `--logs` at wherever you redirected the runners. For example:

```
uv run --package webgraph python benchmark/wceb/run.py --corpus … > logs/wceb.log 2>&1 &
uv run --package webgraph python benchmark/dashboard/server.py --logs logs
```

## What it shows, and what it refuses to claim

Per run: the phase in words, a progress bar for the current unit of work, how many corpora
are finished out of how many, and every score printed so far with the best cell in each row
picked out.

Two honesty rules are built in, because both were bugs first.

* **Silence is not idleness.** The scoring phases go ten minutes or more between lines. An
  earlier version called a run idle after ninety seconds of quiet and reported two
  benchmarks that were working hard as stopped. A run is *running* until it prints its final
  table, and only a silence over thirty minutes reads as stalled.
* **Done means done.** Completion is the final report's rule of equals signs, and nothing
  else. Inferring it from quietness marked unfinished runs as complete.

## Adding a runner

Nothing to add. The page parses the three line shapes every runner in `benchmark/` already
prints -- `<corpus>: N pages`, `extracted N/M` or `scored N/M`, and `<corpus> done: a=… b=…`
-- so a new runner that follows the house style appears with no change here. Give it a title
in `TITLES` and a one-line description in `WHAT` if you want it labelled nicely.

It is dependency-free on purpose: `http.server` and the standard library. Adding a web
framework to this repo to watch a progress bar would be a poor trade.
