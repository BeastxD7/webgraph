"""Read a page the block model got wrong: every block, its label, its out-of-fold probability.

The training run prints a number per page; this prints the page, so the failure can be seen
rather than guessed at. Blocks are shown in order with `y` (the label against the ground
truth), `p` (the cross-validated probability from `oof_<candidate>.npy`), the model's
decision at the chosen threshold, and the first 90 characters of text.

    cd packages/engine && uv run --group bench python ../../benchmark/train/blockmodel_inspect.py 1234 0042
    ... --worst product          # the five worst pages of one type, from cv_report.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "wcxb"))
from analyze import prf

TRAIN_DIR = Path(
    "/private/tmp/claude-501/-Users-shashank-Desktop-shashank-codes-webgraph/"
    "c0642a19-5001-45ad-9934-ec93af8ed544/scratchpad/train"
)
CORPUS = TRAIN_DIR.parent / "corpora" / "wcxb"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--worst", default=None, help="page type: show its five worst pages")
    parser.add_argument("--data", type=Path, default=TRAIN_DIR / "blocks.jsonl.gz")
    parser.add_argument("--max-blocks", type=int, default=80)
    parser.add_argument("--candidate", default=None, help="override cv_report's chosen candidate")
    parser.add_argument("--threshold", type=float, default=None)
    args = parser.parse_args()

    report_path = TRAIN_DIR / "cv_report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {"chosen": {}, "worst": {}}
    candidate = args.candidate or report["chosen"]["candidate"]
    threshold = args.threshold if args.threshold is not None else report["chosen"]["threshold"]
    oof = np.load(TRAIN_DIR / f"oof_{candidate}.npy")

    ids = list(args.ids)
    if args.worst:
        ids.extend(e["id"] for e in report["worst"][args.worst])
    wanted = set(ids)

    offset = 0
    found: dict[str, tuple[dict, int]] = {}
    with gzip.open(args.data, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            n = len(record["blocks"])
            if record["id"] in wanted:
                found[record["id"]] = (record, offset)
            offset += n

    for file_id in ids:
        record, start = found[file_id]
        gt = json.loads((CORPUS / "dev" / "ground-truth" / f"{file_id}.json").read_text())
        probs = oof[start : start + len(record["blocks"])]
        kept = [b["text"] for b, p in zip(record["blocks"], probs, strict=True) if p >= threshold]
        p, r, f = prf("\n\n".join(kept), record["reference"])
        pp, pr, pf = prf(record["production_text"], record["reference"])
        ref_words = len(record["reference"].split())
        print(f"\n{'=' * 100}")
        print(f"{file_id} [{record['type']}] {gt['url']}")
        print(f"model P {p:.2f} R {r:.2f} F1 {f:.2f} | production P {pp:.2f} R {pr:.2f} F1 {pf:.2f} | "
              f"{len(record['blocks'])} blocks, ground truth {ref_words} words")
        print(f"ground truth starts: {record['reference'][:160]!r}")
        print(f"ground truth ends:   {record['reference'][-160:]!r}")
        print(f"{'i':>4} {'y':>1} {'p':>5} {'?':>1} {'kind':<9} {'w':>4} {'ld':>4}  text")
        blocks = record["blocks"]
        shown = blocks if len(blocks) <= args.max_blocks else [*blocks[: args.max_blocks // 2], None, *blocks[-args.max_blocks // 2 :]]
        i = 0
        for b in shown:
            if b is None:
                print("  ...")
                i = len(blocks) - args.max_blocks // 2
                continue
            pr_ = probs[i]
            mark = "K" if pr_ >= threshold else "."
            wrong = "X" if (pr_ >= threshold) != bool(b["y"]) else " "
            words = len(b["text"].split())
            ld = b["f"][3]
            text = " ".join(b["text"].split())[:90]
            print(f"{i:>4} {b['y']:>1} {pr_:>5.2f} {mark}{wrong} {b['kind']:<9} {words:>4} {ld:>4.2f}  {text}")
            i += 1


if __name__ == "__main__":
    main()
