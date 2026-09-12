r"""Train the page-type router on WCXB dev, honestly, and export it for pure-Python inference.

Discipline
----------
- Reads the **dev** split only. Never opens `test/`.
- Reports 5-fold cross-validated accuracy with folds grouped by page (a page is in exactly
  one fold), and writes the **out-of-fold** predicted type for every dev page to
  `--oof <path>`. The WCXB runner can then apply per-type policies using those predictions,
  so the routed WCXB dev number is one the router never trained on.
- The shipped model (`--export`) is trained on all of dev; its number is the CV number
  above, not its training accuracy.
- Features are `webgraph.pagetype.page_features` -- generic URL/payload/structure signals,
  no domains, no page ids.

    uv run --package webgraph python benchmark/train/router_train.py \
        --corpus <wcxb clone> --oof <scratch>/router_oof.json \
        --export packages/engine/src/webgraph/models/router_gbdt.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from webgraph.pagetype import FEATURE_NAMES, TYPES, PageTypeRouter, page_features
from webgraph.pipeline import build_document

CLASSES = [t.value for t in TYPES]


def _one(args: tuple[Path, str, str, str]) -> tuple[str, str, list[float]] | None:
    corpus, file_id, url, page_type = args
    path = corpus / "dev" / "html" / f"{file_id}.html.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            html = handle.read()
        document = build_document(html, url or "https://example.invalid/")
    except Exception:  # noqa: BLE001 - one bad page is a skipped row, not a stop
        return None
    return file_id, page_type, page_features(document, url)


def load(corpus: Path, jobs: int) -> tuple[list[str], list[str], np.ndarray]:
    tasks = []
    for gt_path in sorted((corpus / "dev" / "ground-truth").glob("*.json")):
        data = json.loads(gt_path.read_text(encoding="utf-8"))
        file_id = str(data.get("file_id") or gt_path.stem)
        page_type = ((data.get("_internal") or {}).get("page_type") or {}).get("primary")
        if page_type not in CLASSES:
            continue
        tasks.append((corpus, file_id, data.get("url", ""), page_type))
    ids: list[str] = []
    labels: list[str] = []
    rows: list[list[float]] = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for done, result in enumerate(pool.map(_one, tasks, chunksize=8), 1):
            if result is None:
                continue
            file_id, page_type, features = result
            ids.append(file_id)
            labels.append(page_type)
            rows.append(features)
            if done % 200 == 0:
                print(f"  featurised {done}/{len(tasks)}", file=sys.stderr)
    return ids, labels, np.array(rows, dtype=float)


def make_model(seed: int = 0, class_weight: str | None = None):  # type: ignore[no-untyped-def]
    """`class_weight="balanced"` trades overall accuracy for recall on the rare classes.

    Worth trying because the corpus is 793 articles against 99 listings, and a model
    maximising plain accuracy is right more often by calling a doubtful listing an article.
    Whether that trade is *worth* making is not a question the confusion matrix can answer --
    a listing wrongly called an article and an article wrongly called a listing cost different
    things downstream -- so the routed WCXB score decides it, not the recall.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        max_iter=120,
        learning_rate=0.08,
        max_depth=4,
        max_leaf_nodes=15,
        min_samples_leaf=10,
        l2_regularization=1.0,
        class_weight=class_weight,
        random_state=seed,
    )


def export(model, feature_names: tuple[str, ...]) -> dict:  # type: ignore[no-untyped-def]
    """Flatten sklearn's HistGradientBoosting into the JSON the pure-Python router reads."""
    classes = list(model.classes_)
    baseline = [float(v) for v in np.ravel(model._baseline_prediction)]
    iterations: list[list[list[list[float]]]] = []
    for predictors in model._predictors:
        per_class: list[list[list[float]]] = []
        for predictor in predictors:
            nodes = predictor.nodes
            flat: list[list[float]] = []
            for node in nodes:
                if node["is_leaf"]:
                    flat.append([-1.0, 0.0, -1.0, -1.0, float(node["value"]), 0.0])
                else:
                    flat.append([
                        float(node["feature_idx"]),
                        float(node["num_threshold"]),
                        float(node["left"]),
                        float(node["right"]),
                        0.0,
                        float(node["missing_go_to_left"]),
                    ])
            per_class.append(flat)
        iterations.append(per_class)
    return {
        "classes": classes,
        "features": list(feature_names),
        "baseline": baseline,
        "trees": iterations,
        "trained_on": "WCXB dev (1,497 pages), 5-fold CV reported in benchmark/train/README.md",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--oof", type=Path, required=True, help="write out-of-fold predictions here")
    parser.add_argument("--export", type=Path, default=None, help="write the final model JSON here")
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--class-weight", default=None, choices=["balanced"],
                        help="weight classes inversely to their frequency")
    args = parser.parse_args()

    from sklearn.model_selection import StratifiedKFold

    ids, labels, X = load(args.corpus, args.jobs)
    y = np.array(labels)
    print(f"{len(ids)} pages, {X.shape[1]} features; classes {dict(Counter(labels))}")

    oof: dict[str, dict[str, object]] = {}
    per_type: dict[str, Counter[str]] = defaultdict(Counter)
    correct = 0
    skf = StratifiedKFold(n_splits=args.folds, shuffle=True, random_state=0)
    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y)):
        model = make_model(fold, args.class_weight)
        model.fit(X[train_idx], y[train_idx])
        proba = model.predict_proba(X[test_idx])
        for row, p in zip(test_idx, proba, strict=True):
            probs = {c: float(v) for c, v in zip(model.classes_, p, strict=True)}
            predicted = max(probs, key=lambda c: probs[c])
            oof[ids[row]] = {"type": predicted, "confidence": probs[predicted], "truth": labels[row]}
            per_type[labels[row]][predicted] += 1
            correct += predicted == labels[row]
    accuracy = correct / len(ids)
    print(f"\n5-fold CV accuracy: {accuracy:.3f}\n")
    print(f"{'truth':<14}{'N':>5}{'recall':>8}  predicted as")
    for truth in CLASSES:
        row = per_type[truth]
        n = sum(row.values())
        print(f"{truth:<14}{n:>5}{row[truth] / n if n else 0:>8.3f}  "
              + ", ".join(f"{k} {v}" for k, v in row.most_common(4)))
    args.oof.parent.mkdir(parents=True, exist_ok=True)
    args.oof.write_text(json.dumps(oof), encoding="utf-8")
    print(f"\nout-of-fold predictions -> {args.oof}")

    if args.export:
        final = make_model(0, args.class_weight)
        final.fit(X, y)
        payload = export(final, FEATURE_NAMES)
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(json.dumps(payload), encoding="utf-8")
        size = args.export.stat().st_size
        # Equivalence: the pure-Python router must reproduce sklearn exactly.
        router = PageTypeRouter(payload)
        sk = final.predict_proba(X)
        worst = 0.0
        started = time.perf_counter()
        for row, p in zip(X, sk, strict=True):
            raw = router.scores([float(v) for v in row])
            peak = max(raw)
            exps = [np.exp(v - peak) for v in raw]
            ours = [e / sum(exps) for e in exps]
            worst = max(worst, max(abs(a - b) for a, b in zip(ours, p, strict=True)))
        elapsed = (time.perf_counter() - started) / len(X) * 1000
        print(f"exported {args.export} ({size / 1024:.0f} KB); pure-Python vs sklearn max |dp| = {worst:.2e}; "
              f"{elapsed:.2f} ms per page")
        # Feature importance by permutation on the training set (indicative only).
        from sklearn.inspection import permutation_importance

        imp = permutation_importance(final, X, y, n_repeats=3, random_state=0, n_jobs=1)
        order = np.argsort(-imp.importances_mean)[:15]
        print("top features:", ", ".join(f"{FEATURE_NAMES[i]} {imp.importances_mean[i]:.3f}" for i in order))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
