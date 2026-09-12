r"""Score the block model on WCXB dev **out of fold**, with the corpus's own metric.

Why this file exists
--------------------
The shipped model (`webgraph/models/block_gbdt.json`) is trained on all 1,497 WCXB dev
pages. Running it over dev therefore measures it on its own training data, and the number
that comes out is meaningless -- higher than anything the model would do on a page it has
not seen. `benchmark/wcxb/run.py` passes `model=None` for exactly this reason.

The honest number comes from the fold artefacts `blockmodel_train.py` writes: for every
block, the probability assigned by a model fitted on the four folds that did **not** contain
that block's page. This file maps those probabilities back to pages, applies the same
threshold and fail-open guard that `select_by_model` applies in production, and scores the
result against the corpus ground truth with `word_f1` imported from the corpus clone.

Nothing here shares code with the trainer's own reporting, which is the point: the trainer
could be scoring itself wrongly and this would disagree. It reads the ground truth from the
corpus, not from the trainer's cache.

    uv run --package webgraph python benchmark/train/blockmodel_oof.py \
        --corpus <wcxb clone> --train-dir <scratch with blocks.jsonl.gz and oof_*.npy>

Discipline: reads the **dev** split only, never `test/`.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

import numpy as np

from webgraph.blockmodel import BlockModel
from webgraph.main_content import word_count

ORDER = ("article", "documentation", "service", "forum", "collection", "listing", "product")


def load_word_f1(corpus: Path):  # type: ignore[no-untyped-def]
    """The corpus's own scorer, imported rather than reimplemented.

    WCXB averages **per-page** F1; a runner that pooled precision and recall corpus-wide
    would print a number that looks like the leaderboard's and is not.
    """
    spec = importlib.util.spec_from_file_location("wcxb_evaluate", corpus / "evaluate.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"{corpus}/evaluate.py not found -- is this a WCXB clone?")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.word_f1


def ground_truth(corpus: Path) -> dict[str, tuple[str, str]]:
    """`{file_id: (main_content, page_type)}` for the dev split."""
    out: dict[str, tuple[str, str]] = {}
    for path in sorted((corpus / "dev" / "ground-truth").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        gt = data.get("ground_truth") or {}
        if not isinstance(gt, dict):
            continue
        page_type = ((data.get("_internal") or {}).get("page_type") or {}).get("primary")
        out[str(data.get("file_id") or path.stem)] = (
            gt.get("main_content") or "",
            page_type or "unknown",
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True, help="a WCXB clone")
    parser.add_argument(
        "--train-dir", type=Path, required=True,
        help="where blockmodel_train.py wrote blocks.jsonl.gz and oof_<candidate>.npy",
    )
    parser.add_argument("--candidate", default="d6-i150-lr0.1", help="which oof_*.npy to read")
    args = parser.parse_args()

    word_f1 = load_word_f1(args.corpus)
    model = BlockModel.load()
    truth = ground_truth(args.corpus)
    oof = np.load(args.train_dir / f"oof_{args.candidate}.npy")
    print(
        f"threshold {model.threshold}, fail-open below {model.min_share:.0%} of page words; "
        f"{len(truth)} dev pages, {len(oof)} out-of-fold block probabilities"
    )

    cursor = 0
    model_scores: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    boundary_scores: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    fail_open = 0
    with gzip.open(args.train_dir / "blocks.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            texts = [b["text"] for b in record["blocks"]]
            probabilities = oof[cursor : cursor + len(texts)]
            cursor += len(texts)
            if record["id"] not in truth:
                continue
            reference, page_type = truth[record["id"]]
            words = [word_count(t) for t in texts]
            keep = [i for i, p in enumerate(probabilities) if p >= model.threshold]
            total = sum(words)
            if not keep or (total and sum(words[i] for i in keep) < total * model.min_share):
                kept_text = "\n".join(texts)  # the fail-open guard, as `select_by_model` has it
                fail_open += 1
            else:
                kept_text = "\n".join(texts[i] for i in keep)
            model_scores[page_type].append(word_f1(kept_text, reference))
            # What production did before the model: the trainer stored it per page.
            boundary_scores[page_type].append(word_f1(record["production_text"], reference))

    if cursor != len(oof):
        raise SystemExit(f"block count mismatch: consumed {cursor} of {len(oof)} probabilities")
    print(f"every probability consumed; {fail_open} page(s) failed open\n")

    print(f"{'type':<15}{'N':>6}{'boundary F1':>14}{'model OOF F1':>14}{'delta':>9}")
    every_model: list[tuple[float, float, float]] = []
    every_boundary: list[tuple[float, float, float]] = []
    for page_type in ORDER:
        rows, base = model_scores.get(page_type, []), boundary_scores.get(page_type, [])
        if not rows:
            continue
        every_model += rows
        every_boundary += base
        m, b = mean(f for _, _, f in rows), mean(f for _, _, f in base)
        print(f"{page_type:<15}{len(rows):>6}{b:>14.3f}{m:>14.3f}{m - b:>+9.3f}")
    m = mean(f for _, _, f in every_model)
    b = mean(f for _, _, f in every_boundary)
    print(f"{'overall':<15}{len(every_model):>6}{b:>14.3f}{m:>14.3f}{m - b:>+9.3f}")
    print(f"{'precision':<15}{'':>6}{mean(p for p, _, _ in every_boundary):>14.3f}"
          f"{mean(p for p, _, _ in every_model):>14.3f}")
    print(f"{'recall':<15}{'':>6}{mean(r for _, r, _ in every_boundary):>14.3f}"
          f"{mean(r for _, r, _ in every_model):>14.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
