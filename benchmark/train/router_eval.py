"""Evaluate a router model on the WCXB **test** split, once.

The test split is the only held-out data there is, and it comes with a defect that has to
be stated next to every number read from it: the archiver stripped every `<script>` tag from
these 511 files, so the JSON-LD features are zero on all of them. URL, DOM shape, Open Graph
(meta tags survive), microdata and the page's own text are intact. That makes this a harder
distribution than the web -- and a fair one for asking how much a model leans on JSON-LD.

Run it after cross-validation has chosen a model, not while choosing one.

    uv run --package webgraph python benchmark/train/router_eval.py --corpus <clone>
    uv run --package webgraph python benchmark/train/router_eval.py --corpus <clone> \\
        --model <previous router_gbdt.json>   # to compare against an earlier export
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from webgraph.pagetype import FEATURE_NAMES, TYPES, PageTypeRouter, page_features
from webgraph.pipeline import build_document

CLASSES = [t.value for t in TYPES]


def _one(args: tuple[Path, str, str, str]) -> tuple[str, str, list[float]] | None:
    corpus, file_id, url, page_type = args
    path = corpus / "test" / "html" / f"{file_id}.html.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            html = handle.read()
        document = build_document(html, url or "https://example.invalid/")
    except Exception:
        return None
    return file_id, page_type, page_features(document, url)


def load_router(path: Path | None) -> PageTypeRouter:
    if path is None:
        router = PageTypeRouter.load()
        if router is None:
            raise SystemExit("no router is shipped")
        return router
    model = json.loads(path.read_text(encoding="utf-8"))
    # An earlier export lists fewer features. Its trees only ever index the ones it knew,
    # which are the leading columns of today's vector, so it can be scored on the full
    # vector once the name check is satisfied.
    if list(model["features"]) == list(FEATURE_NAMES[: len(model["features"])]):
        model["features"] = list(FEATURE_NAMES)
    return PageTypeRouter(model)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=None, help="a router JSON; default: the shipped one")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()

    tasks = []
    for gt_path in sorted((args.corpus / "test" / "ground-truth").glob("*.json")):
        data = json.loads(gt_path.read_text(encoding="utf-8"))
        page_type = ((data.get("_internal") or {}).get("page_type") or {}).get("primary")
        if page_type not in CLASSES:
            continue
        tasks.append((args.corpus, str(data.get("file_id") or gt_path.stem), data.get("url", ""), page_type))

    rows: list[tuple[str, str, list[float]]] = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for done, result in enumerate(pool.map(_one, tasks, chunksize=8), 1):
            if result is not None:
                rows.append(result)
            if done % 100 == 0:
                print(f"  featurised {done}/{len(tasks)}", file=sys.stderr)

    router = load_router(args.model)
    per: dict[str, Counter[str]] = defaultdict(Counter)
    committed = 0
    correct = 0
    correct_committed = 0
    for _, truth, features in rows:
        probabilities = router._probabilities(features)
        best = max(probabilities, key=lambda c: probabilities[c])
        per[truth][best] += 1
        correct += best == truth
        if probabilities[best] >= router.min_confidence:
            committed += 1
            correct_committed += best == truth

    n = len(rows)
    recalls = {c: per[c][c] / max(1, sum(per[c].values())) for c in CLASSES}
    precisions = {
        c: per[c][c] / max(1, sum(per[t][c] for t in CLASSES)) for c in CLASSES
    }
    f1s = [
        (2 * precisions[c] * recalls[c] / (precisions[c] + recalls[c])) if (precisions[c] + recalls[c]) else 0.0
        for c in CLASSES
    ]
    print(f"\ntest split: {n} pages (every <script> stripped by the archiver; JSON-LD features are zero)")
    print(f"model: {args.model or 'shipped'}  features known: {len(router.features)}")
    print(f"accuracy {correct / n:.3f}   macro-F1 {sum(f1s) / len(f1s):.3f}")
    print(
        f"with the {router.min_confidence:.1f} floor: committed on {committed / n:.1%} of pages, "
        f"accuracy on those {correct_committed / max(1, committed):.3f}"
    )
    print(f"\n{'truth':<14}{'N':>5}{'recall':>8}  predicted as")
    for truth in CLASSES:
        row = per[truth]
        total = sum(row.values())
        print(f"{truth:<14}{total:>5}{recalls[truth]:>8.3f}  " + ", ".join(f"{k} {v}" for k, v in row.most_common(4)))


if __name__ == "__main__":
    main()
