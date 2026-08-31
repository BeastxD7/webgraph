
### D61 — Full 100-site route benchmark re-run: no regression

Re-run after a session that changed `extract_links`, `Frontier`, `render_page`, the graph
builder and reading order. Baseline saved at
`benchmark/route_discovery/baseline-2026-09-01.txt`, replacing the August one.

```
sites scored          96      (was 93)
perfect recall        77/96   (was 85/93)
mean recall (engine)  98.1%   (was 97.7%)
mean recall (static)  31.0%
```

Mean recall up, sites scored up. **Perfect recall down, and that is the oracle moving rather
than the engine**: a deeper oracle finds more routes on large sites, so "perfect on every
one" gets harder while the mean holds. Both are reported for exactly this reason -- a single
headline number would have hidden the change in the denominator.

Four sites still block headless browsers outright and have no oracle at all: Behance,
Dribbble, Work & Co, Etsy.

Process note: the first two attempts at this run stalled. `uv run … | tail -40` under
`run_in_background` blocked the writer once the pipe filled -- 0% CPU, no browser, no output,
for 53 minutes. Redirect long background runs to a file; never pipe them through `tail`.
