"""Per-page WCXB scores for the current checkout, and the diff between two checkouts.

The runner reports means; a change is judged on the pages that moved. Dump per-page F1
from each checkout (a git worktree at `main`, and the candidate), then diff:

    uv run python benchmark/wcxb/per_page.py dump --out /tmp/main.json --corpus <clone>
    uv run python benchmark/wcxb/per_page.py dump --out /tmp/candidate.json --corpus <clone>
    uv run python benchmark/wcxb/per_page.py diff /tmp/main.json /tmp/candidate.json

The policy is the one for the page's *annotated* type, so a per-type mean here is the
"true-type" number in the pull requests; the routed production number comes from
`benchmark/wcxb/run.py`. Restrict with `--types article,forum` for a quick check.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

TYPES = (
    "article",
    "documentation",
    "service",
    "forum",
    "collection",
    "listing",
    "product",
)


def dump(corpus: Path, split: str, out: Path, types: set[str]) -> None:
    from webgraph.content import select_content
    from webgraph.pagetype import policy_for
    from webgraph.pipeline import build_document
    from webgraph.types import blocks_text

    spec = importlib.util.spec_from_file_location(
        "wcxb_evaluate", corpus / "evaluate.py"
    )
    assert spec and spec.loader
    evaluate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluate)

    results: dict[str, dict[str, object]] = {}
    for truth_path in sorted((corpus / split / "ground-truth").glob("*.json")):
        truth = json.loads(truth_path.read_text())
        page_type = truth["_internal"]["page_type"]["primary"]
        if types and page_type not in types:
            continue
        with gzip.open(
            corpus / split / "html" / f"{truth_path.stem}.html.gz"
        ) as handle:
            html = handle.read().decode("utf-8", "replace")
        document = build_document(html, truth.get("url") or "https://example.invalid/")
        reference = truth["ground_truth"].get("main_content") or ""
        selection = select_content(
            list(document.blocks),
            model=None,
            config=policy_for(page_type),
            title=document.title or "",
        )
        ours = blocks_text(selection.blocks)
        precision, recall, f1 = evaluate.word_f1(ours, reference)
        results[truth_path.stem] = {
            "type": page_type,
            "f1": f1,
            "p": precision,
            "r": recall,
            "words": len(ours.split()),
            "url": (truth.get("url") or "")[:70],
        }
    out.write_text(json.dumps(results))
    by_type: dict[str, list[float]] = defaultdict(list)
    for row in results.values():
        by_type[str(row["type"])].append(float(row["f1"]))
    for page_type in TYPES:
        if by_type[page_type]:
            print(
                f"{page_type:14} n={len(by_type[page_type]):4} mean F1 {statistics.mean(by_type[page_type]):.4f}"
            )


def diff(base_path: Path, cand_path: Path, threshold: float) -> None:
    base = json.loads(base_path.read_text())
    cand = json.loads(cand_path.read_text())
    shared = [k for k in base if k in cand]
    by_type: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    for key in shared:
        by_type[base[key]["type"]][0].append(base[key]["f1"])
        by_type[base[key]["type"]][1].append(cand[key]["f1"])
    for page_type in TYPES:
        a, b = by_type[page_type]
        if a:
            print(
                f"{page_type:14} n={len(a):4} base {statistics.mean(a):.4f} cand {statistics.mean(b):.4f} delta {statistics.mean(b) - statistics.mean(a):+.4f}"
            )
    a_all = [base[k]["f1"] for k in shared]
    b_all = [cand[k]["f1"] for k in shared]
    print(
        f"{'all':14} n={len(shared):4} base {statistics.mean(a_all):.4f} cand {statistics.mean(b_all):.4f} delta {statistics.mean(b_all) - statistics.mean(a_all):+.4f}"
    )
    moved = sorted(
        (cand[k]["f1"] - base[k]["f1"], k)
        for k in shared
        if abs(cand[k]["f1"] - base[k]["f1"]) > threshold
    )
    for delta, key in moved:
        a, b = base[key], cand[key]
        print(
            f"{delta:+.3f} {key} {a['type'][:6]} F1 {a['f1']:.3f}->{b['f1']:.3f} P {a['p']:.2f}->{b['p']:.2f} R {a['r']:.2f}->{b['r']:.2f} words {a['words']}->{b['words']} {b['url']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    dumper = sub.add_parser(
        "dump", help="score every page of a split with the current checkout"
    )
    dumper.add_argument(
        "--corpus",
        type=Path,
        default=Path(os.environ.get("WCXB_CORPUS", "benchmark/wcxb/corpus")),
    )
    dumper.add_argument("--split", default="dev", choices=("dev", "test"))
    dumper.add_argument("--out", type=Path, required=True)
    dumper.add_argument(
        "--types", default="", help="comma-separated page types (default: all)"
    )
    differ = sub.add_parser("diff", help="per-type means and the pages that moved")
    differ.add_argument("base", type=Path)
    differ.add_argument("candidate", type=Path)
    differ.add_argument("--threshold", type=float, default=0.002)
    args = parser.parse_args()
    if args.command == "dump":
        dump(args.corpus, args.split, args.out, {t for t in args.types.split(",") if t})
    else:
        diff(args.base, args.candidate, args.threshold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
