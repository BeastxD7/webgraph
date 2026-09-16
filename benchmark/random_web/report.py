"""Summarise a fidelity run over the random sample: how often the engine reads the page,
how completely, and what went wrong when it did not.

    uv run python benchmark/random_web/report.py score.json [--worst 15]

Outcomes, in the order they are decided:

- `refused`: the engine returned an error -- a wall, a login redirect, robots.txt, a 404,
  a non-HTML answer, both fetches failing. Honest, and counted separately from a wrong
  output: the product rule is that a refusal beats a false page.
- `oracle blocked` / `oracle failed`: Chromium itself was walled or timed out, so there is
  nothing to score against; the engine's output is unjudged, not wrong.
- `scored`: recall (share of the page's visible words we produced), extra (share of our
  words the page does not show) and order inversions. The distribution is reported in
  bands, because a mean hides exactly the pages that matter.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path


def outcome(record: dict) -> str:
    error = record.get("error") or ""
    if error.lower().startswith("oracle blocked"):
        return "oracle blocked"
    if record.get("recall") is None:
        if "CalledProcessError" in error or "oracle" in error.lower():
            return "oracle failed"
        return "refused"
    return "scored"


def refusal_kind(error: str) -> str:
    text = error.lower()
    for key, label in (
        ("robots.txt", "robots.txt disallows"),
        ("login", "login wall"),
        ("bot challenge", "bot challenge"),
        ("block page", "block page"),
        ("refused this client", "HTTP 403/5xx"),
        ("does not exist", "HTTP 404/410"),
        ("unsupported content", "not HTML"),
        ("no readable text", "empty page"),
        ("javascript shell", "empty page"),
        ("timed out", "timeout"),
        ("timeout", "timeout"),
    ):
        if key in text:
            return label
    return "other: " + error[:60]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("score", type=Path)
    parser.add_argument("--worst", type=int, default=15)
    args = parser.parse_args()
    data = json.loads(args.score.read_text())
    outcomes = Counter(outcome(r) for r in data.values())
    total = len(data)
    print(f"{total} pages")
    for name, count in outcomes.most_common():
        print(f"  {name:15} {count:4}  ({100 * count / total:.0f}%)")

    refusals = Counter(refusal_kind(r.get("error") or "") for r in data.values() if outcome(r) == "refused")
    if refusals:
        print("\nrefusals, by reason:")
        for name, count in refusals.most_common():
            print(f"  {count:4}  {name}")

    scored = {k: r for k, r in data.items() if outcome(r) == "scored"}
    if scored:
        recalls = [r["recall"] for r in scored.values()]
        extras = [r["extra"] for r in scored.values()]
        print(f"\nscored {len(scored)}: recall median {statistics.median(recalls):.3f}, mean {statistics.mean(recalls):.3f}; "
              f"extra median {statistics.median(extras):.3f}, mean {statistics.mean(extras):.3f}")
        bands = [(1.0, "= 1.000"), (0.99, "0.99–0.999"), (0.95, "0.95–0.99"), (0.90, "0.90–0.95"), (0.80, "0.80–0.90"), (0.0, "< 0.80")]
        print("recall bands:")
        for floor, label in bands:
            n = sum(1 for v in recalls if (v >= floor if floor < 1.0 else v >= 1.0) and not any(v >= f for f, _ in bands if f > floor))
            print(f"  {label:12} {n:4}  ({100 * n / len(scored):.0f}%)")
        print("extra bands:")
        for floor, label in [(0.3, "> 0.30"), (0.1, "0.10–0.30"), (0.05, "0.05–0.10"), (0.0, "< 0.05")]:
            n = sum(1 for v in extras if v > floor and not any(v > f for f, _ in [(0.3, ""), (0.1, ""), (0.05, "")] if f > floor)) if floor > 0 else sum(1 for v in extras if v <= 0.05)
            print(f"  {label:12} {n:4}")
        print(f"\nlowest recall ({args.worst}):")
        for name, r in sorted(scored.items(), key=lambda kv: kv[1]["recall"])[: args.worst]:
            print(f"  {r['recall']:.3f}  extra {r['extra']:.3f}  {r['page_words']:6} words  {r['url'][:80]}  missing {r['missing_top'][:4]}")
        print(f"\nhighest extra ({args.worst}):")
        for name, r in sorted(scored.items(), key=lambda kv: -kv[1]["extra"])[: args.worst]:
            print(f"  {r['extra']:.3f}  recall {r['recall']:.3f}  {r['url'][:80]}  extra {r['extra_top'][:4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
